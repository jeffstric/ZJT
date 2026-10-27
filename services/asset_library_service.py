# -*- coding: utf-8 -*-
"""资产库服务层：权限过滤、容量配额、文件持久化与管理员清除。

核心规则（见 docs/backend/asset_library.md）：
- 资产文件永久存放在 upload/asset_library/<user_id>/ 下，不受媒体缓存
  清理策略影响；删除限属主/管理员（删文件+删记录+释放配额）。
- 加入资产库按 file_size 预留用户配额（asset_library_quota.try_reserve
  原子条件 UPDATE，无事务依赖）；任何失败路径必须释放预留并清理临时文件。
- 可见性：自己的 + view=public + 被指定 view/edit 成员；编辑权限隐含查看。
- 分组目录全局共享（asset_group），任何登录用户可见、可创建。

非阻塞约定（AGENTS.md 第 1/10 条）：HTTP 下载用 aiohttp，写盘/复制/删除
丢 utils.download_io_pool 模块级长寿 executor，DB 调用由 API 层
asyncio.to_thread 包装（本服务层方法本身为同步 DB 组装 + 少量 async IO）。
"""
import asyncio
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import aiohttp

from config.constant import (
    AssetLibraryConstants as ALC,
    UploadPathConstants,
)
from model.asset_group import AssetGroupModel
from model.asset_library import AssetLibraryModel, AssetItem
from model.asset_library_quota import AssetLibraryQuotaModel
from model.asset_permission_member import AssetPermissionMemberModel
from model.database import execute_query
from model.users import UsersModel
from utils.download_io_pool import get_download_io_executor
from utils.project_path import get_upload_subdir, resolve_upload_url_to_local_path

logger = logging.getLogger(__name__)


class AssetLibraryError(Exception):
    """资产库业务错误（message 面向用户可读）。"""

    def __init__(self, message: str, code: str = "asset_error"):
        super().__init__(message)
        self.code = code
        self.message = message


# ============ 权限判定 ============

def _perm_members(asset_id: int) -> Dict[str, List[int]]:
    mapping = AssetPermissionMemberModel.map_by_assets([asset_id])
    return mapping.get(asset_id, {'view': [], 'edit': []})


def can_view(asset: AssetItem, user_id: int) -> bool:
    """查看权限：属主 / view=public / 被指定 view 或 edit 成员 / edit=public。"""
    if asset.user_id == user_id:
        return True
    if asset.view_permission == ALC.PERMISSION_PUBLIC or asset.edit_permission == ALC.PERMISSION_PUBLIC:
        return True
    if asset.view_permission == ALC.PERMISSION_SPECIFIED or asset.edit_permission == ALC.PERMISSION_SPECIFIED:
        members = _perm_members(asset.id)
        return user_id in members.get('view', []) or user_id in members.get('edit', [])
    return False


def can_edit(asset: AssetItem, user_id: int, is_admin: bool = False) -> bool:
    """编辑权限（元信息/权限设置）：属主 / edit=public / 被指定 edit 成员 / 管理员。"""
    if is_admin or asset.user_id == user_id:
        return True
    if asset.edit_permission == ALC.PERMISSION_PUBLIC:
        return True
    if asset.edit_permission == ALC.PERMISSION_SPECIFIED:
        members = _perm_members(asset.id)
        return user_id in members.get('edit', [])
    return False


def can_delete(asset: AssetItem, user_id: int, is_admin: bool = False) -> bool:
    """删除权限：属主 / 管理员（删除是管理操作，不受 public/specified 编辑权限影响）。"""
    return bool(is_admin or asset.user_id == user_id)


def asset_file_exists(file_path: Optional[str]) -> bool:
    """资产文件是否仍在磁盘上。

    外部误删/磁盘迁移导致文件丢失时返回 False（列表据此标记「文件缺失」，
    避免无声裂图）；file_path 脏数据同样按缺失处理。
    """
    if not file_path:
        return False
    try:
        return os.path.isfile(resolve_upload_url_to_local_path(file_path))
    except ValueError:
        return False


def verify_asset_files() -> Dict[str, Any]:
    """启动完整性检查：找出 DB 记录在磁盘上缺失文件的资产。

    只读（os.path.isfile），不修改任何数据；资产量大时由调用方丢线程池执行
    （server 启动钩子 asyncio.to_thread 包装）。返回缺失清单供日志告警。
    """
    rows = execute_query("SELECT id, file_path FROM asset_library", (), fetch_all=True) or []
    missing = [int(r["id"]) for r in rows if not asset_file_exists(r.get("file_path"))]
    return {"total": len(rows), "missing": missing}


def _visible_where(user_id: int) -> Tuple[str, List[Any]]:
    """可见资产 SQL 片段（列表/计数共用）：own OR public OR specified-member。"""
    where = """(
        a.user_id = %s
        OR a.view_permission = 'public'
        OR a.edit_permission = 'public'
        OR (
            (a.view_permission = 'specified' OR a.edit_permission = 'specified')
            AND EXISTS (
                SELECT 1 FROM asset_permission_member m
                WHERE m.asset_id = a.id AND m.user_id = %s
            )
        )
    )"""
    return where, [user_id, user_id]


# ============ 参数校验 ============

def _validate_permission(value: str, field: str) -> str:
    if value not in ALC.PERMISSION_CHOICES:
        raise AssetLibraryError(f"{field} 取值非法", "invalid_permission")
    return value


def _normalize_members(raw: Any) -> List[int]:
    if not raw:
        return []
    if not isinstance(raw, (list, tuple)):
        raise AssetLibraryError("成员列表格式非法", "invalid_members")
    ids: List[int] = []
    for item in raw:
        if item is None or item == '':
            continue
        try:
            uid = int(item)
        except (TypeError, ValueError):
            raise AssetLibraryError("成员 ID 必须是数字", "invalid_members")
        if uid > 0 and uid not in ids:
            ids.append(uid)
    if len(ids) > 50:
        raise AssetLibraryError("指定成员一次最多 50 人", "too_many_members")
    return ids


# Content-Type → 扩展名显式映射（mimetypes.guess_extension 对 webp 等在
# Windows 上返回 None，平台差异会导致扩展名与内容错配）
_CONTENT_TYPE_EXT = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'image/bmp': '.bmp',
}


def _guess_extension(url: str, content_type: Optional[str] = None) -> str:
    """从 URL 路径 / Content-Type 推断图片扩展名，兜底 .png。"""
    allowed = ALC.ASSET_TYPE_EXTENSIONS[ALC.ASSET_TYPE_IMAGE]
    path = urlparse(url).path if "://" in url else url
    lower = path.lower()
    for ext in allowed:
        if lower.endswith(ext):
            return ext
    if content_type:
        mapped = _CONTENT_TYPE_EXT.get(content_type.split(";")[0].strip().lower())
        if mapped in allowed:
            return mapped
    return ".png"


# ============ 文件持久化 ============

async def _download_to_file(url: str, dest_path: Path) -> int:
    """非阻塞下载远程文件到 dest_path，返回字节数。超限/失败抛 AssetLibraryError。"""
    timeout = aiohttp.ClientTimeout(
        total=ALC.DOWNLOAD_TOTAL_TIMEOUT_SECONDS,
        connect=ALC.DOWNLOAD_CONNECT_TIMEOUT_SECONDS,
    )
    loop = asyncio.get_running_loop()
    executor = get_download_io_executor()
    connector = aiohttp.TCPConnector(force_close=True)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise AssetLibraryError(f"源文件下载失败（HTTP {response.status}）", "download_failed")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > ALC.MAX_FILE_SIZE_BYTES:
                    raise AssetLibraryError("源文件超过资产库单文件大小限制", "file_too_large")
                f = await asyncio.wait_for(
                    loop.run_in_executor(executor, open, dest_path, "wb"),
                    timeout=ALC.DOWNLOAD_WRITE_CHUNK_TIMEOUT_SECONDS,
                )
                try:
                    written = 0
                    async for chunk in response.content.iter_chunked(ALC.DOWNLOAD_IO_CHUNK_BYTES):
                        written += len(chunk)
                        if written > ALC.MAX_FILE_SIZE_BYTES:
                            raise AssetLibraryError("源文件超过资产库单文件大小限制", "file_too_large")
                        await asyncio.wait_for(
                            loop.run_in_executor(executor, f.write, chunk),
                            timeout=ALC.DOWNLOAD_WRITE_CHUNK_TIMEOUT_SECONDS,
                        )
                finally:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, f.close),
                        timeout=ALC.DOWNLOAD_WRITE_CHUNK_TIMEOUT_SECONDS,
                    )
                return written
    except AssetLibraryError:
        raise
    except asyncio.TimeoutError:
        raise AssetLibraryError("源文件下载超时", "download_timeout")
    except aiohttp.ClientError as e:
        raise AssetLibraryError(f"源文件下载失败：{e}", "download_failed")


async def _copy_to_file(src_path: Path, dest_path: Path) -> int:
    """非阻塞复制本地文件，返回字节数。"""
    size = src_path.stat().st_size
    if size > ALC.MAX_FILE_SIZE_BYTES:
        raise AssetLibraryError("源文件超过资产库单文件大小限制", "file_too_large")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(get_download_io_executor(), shutil.copyfile, str(src_path), str(dest_path))
    return size


def _remove_file_quietly(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.warning(f"Failed to remove asset temp file {path}: {e}")


# ============ 功能开关 / 全局容量 ============

def _bool_config(value: Any, default: bool = False) -> bool:
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def get_feature_config() -> Dict[str, Any]:
    """读取资产库功能配置（system_config，缓存 + YAML 兜底）。

    enabled：总开关（默认关）；total_quota_gb：全站总磁盘上限 GB（0=不限）；
    allow_all_users：全员可用（关闭时按 quota.enabled 逐用户放行）。
    """
    from config.config_util import get_dynamic_config_value
    enabled = _bool_config(get_dynamic_config_value(ALC.CONFIG_NAMESPACE, ALC.CONFIG_KEY_ENABLED, default=False))
    allow_all = _bool_config(get_dynamic_config_value(ALC.CONFIG_NAMESPACE, ALC.CONFIG_KEY_ALLOW_ALL_USERS, default=False))
    try:
        total_gb = float(get_dynamic_config_value(ALC.CONFIG_NAMESPACE, ALC.CONFIG_KEY_TOTAL_QUOTA_GB, default=0) or 0)
    except (TypeError, ValueError):
        total_gb = 0.0
    return {
        'enabled': enabled,
        'allow_all_users': allow_all,
        'total_quota_bytes': max(0, int(total_gb * 1024 * 1024 * 1024)),
    }


def total_used_bytes() -> int:
    """全站资产总占用（全局容量展示与校验用）。"""
    row = execute_query(
        "SELECT COALESCE(SUM(file_size), 0) AS total FROM asset_library",
        (), fetch_one=True,
    )
    return int(row['total']) if row else 0


def ensure_user_allowed(user_id: int, is_admin: bool = False) -> None:
    """功能开关 + 用户级权限校验，不通过抛 AssetLibraryError（403 语义）。

    管理员恒通过（管理通道不受功能开关限制的接口不调用本函数）。
    """
    cfg = get_feature_config()
    if not cfg['enabled']:
        raise AssetLibraryError('资产库功能未开启，请联系管理员', 'feature_disabled')
    if is_admin or cfg['allow_all_users']:
        return
    if not AssetLibraryQuotaModel.is_enabled(user_id):
        raise AssetLibraryError('您还没有资产库使用权限，请联系管理员开启', 'user_not_allowed')


def check_global_capacity(new_size: int) -> None:
    """全站总磁盘上限校验（total_quota_gb=0 不限）。

    SUM 与 INSERT 之间存在并发窗口，属软限制：入库低频 + 用户/全局双层
    限制，少量并发超卖可接受（避免为严丝合缝引入全局计数行的锁竞争）。
    """
    cfg = get_feature_config()
    total_limit = cfg['total_quota_bytes']
    if total_limit <= 0:
        return
    used = total_used_bytes()
    if used + new_size > total_limit:
        raise AssetLibraryError(ALC.GLOBAL_QUOTA_EXCEEDED_MSG, 'global_quota_exceeded')


# ============ 加入资产库 ============

async def add_asset(
    user_id: int,
    source_url: str,
    name: str,
    group_id: Optional[int] = None,
    asset_type: str = ALC.ASSET_TYPE_IMAGE,
    view_permission: str = ALC.PERMISSION_PRIVATE,
    edit_permission: str = ALC.PERMISSION_PRIVATE,
    view_members: Optional[Sequence[int]] = None,
    edit_members: Optional[Sequence[int]] = None,
    is_admin: bool = False,
) -> AssetItem:
    """把生成产物加入资产库：校验 → 下载/复制 → 配额预留 → 落库。

    失败路径统一 try/finally 清理临时文件并释放预留（AGENTS.md 第 10 条）。
    """
    # 功能开关 + 用户级权限（总开关关闭时管理员同样不可入库）
    ensure_user_allowed(user_id, is_admin=is_admin)
    text = (source_url or "").strip()
    if not text:
        raise AssetLibraryError("源文件地址不能为空", "invalid_source_url")
    if not re.match(r"^https?://", text) and "/upload/" not in text and not text.startswith("upload/"):
        raise AssetLibraryError("仅支持 http(s) 地址或本站 /upload 路径", "invalid_source_url")
    asset_name = (name or "").strip()[:ALC.ASSET_NAME_MAX_LENGTH] or "未命名资产"
    if asset_type != ALC.ASSET_TYPE_IMAGE:
        raise AssetLibraryError("当前仅支持图片类型资产", "unsupported_type")
    _validate_permission(view_permission, "查看权限")
    _validate_permission(edit_permission, "编辑权限")
    view_ids = _normalize_members(view_members)
    edit_ids = _normalize_members(edit_members)

    # 源文件可达性预检（轻量 stat，不触发 DB/网络）：本站 /upload 路径本地已
    # 缺失时快速失败，避免无效请求继续走分组/配额 DB 交互
    local_candidate = None
    if "/upload/" in text or text.startswith("upload/"):
        try:
            candidate = resolve_upload_url_to_local_path(text)
            if candidate and os.path.isfile(candidate):
                local_candidate = candidate
        except ValueError:
            local_candidate = None
        if local_candidate is None and not re.match(r"^https?://", text):
            raise AssetLibraryError("源文件已被清理或不可访问，无法入库", "source_missing")

    # 分组校验（共享目录：任何用户可用任何分组）
    if group_id is not None:
        group = AssetGroupModel.get_by_id(int(group_id))
        if not group:
            raise AssetLibraryError("分组不存在", "group_not_found")

    # 确保配额行存在（首次访问初始化默认配额）
    AssetLibraryQuotaModel.ensure_for_user(user_id)

    # 目标目录与临时文件（同盘 rename，避免下载成功后跨盘移动失败）
    user_dir = Path(get_upload_subdir(UploadPathConstants.ASSET_LIBRARY_DIR, str(user_id)))
    token = uuid.uuid4().hex
    tmp_path = user_dir / f".tmp_{token}"

    reserved = 0
    asset_id: Optional[int] = None
    final_path: Optional[Path] = None
    try:
        # 1) 持久化文件：本站 /upload 路径直接复制，外链走 aiohttp 下载
        if local_candidate:
            ext = _guess_extension(text) or Path(local_candidate).suffix or ".png"
            file_size = await _copy_to_file(Path(local_candidate), tmp_path)
        else:
            ext = _guess_extension(text)
            file_size = await _download_to_file(text, tmp_path)
        if file_size <= 0:
            raise AssetLibraryError("源文件为空", "empty_file")

        # 1.5) 全站总磁盘上限（total_quota_gb=0 不限）；失败会走 finally 清理
        check_global_capacity(file_size)

        # 2) 配额预留（原子条件 UPDATE；quota=0 不限）
        if not AssetLibraryQuotaModel.try_reserve(user_id, file_size):
            # 配额详情仅用于错误文案，查询失败不改变 quota_exceeded 语义
            quota: Dict[str, Any] = {}
            try:
                quota = AssetLibraryQuotaModel.get_by_user(user_id) or {}
            except Exception as detail_error:  # noqa: BLE001
                logger.warning(f"Failed to read quota detail for user {user_id}: {detail_error}")
            raise AssetLibraryError(
                "资产库容量不足，请联系管理员调整配额"
                f"（已用 {quota.get('used_bytes', 0)}/{quota.get('quota_bytes', 0)} 字节）",
                "quota_exceeded",
            )
        reserved = file_size

        # 3) 转正文件名 + 落库
        filename = f"{ALC.FILENAME_PREFIX}_{user_id}_{token}{ext}"
        final_path = user_dir / filename
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(get_download_io_executor(), os.replace, str(tmp_path), str(final_path))
        relative_path = f"{UploadPathConstants.ASSET_LIBRARY_DIR}/{user_id}/{filename}"

        asset_id = AssetLibraryModel.create(
            user_id=user_id,
            group_id=int(group_id) if group_id is not None else None,
            asset_type=asset_type,
            name=asset_name,
            source_url=text,
            file_path=relative_path,
            file_size=file_size,
            view_permission=view_permission,
            edit_permission=edit_permission,
        )

        # 4) 指定成员（perm=specified 才有意义，但统一存以便切换权限时保留；
        #    属主自身无意义，统一剔除）
        AssetPermissionMemberModel.replace_for_asset(asset_id, ALC.PERM_TYPE_VIEW, view_ids, exclude_user_id=user_id)
        AssetPermissionMemberModel.replace_for_asset(asset_id, ALC.PERM_TYPE_EDIT, edit_ids, exclude_user_id=user_id)

        asset = AssetLibraryModel.get_by_id(asset_id)
        logger.info(f"Asset {asset_id} added to library by user {user_id}: {file_size} bytes, group={group_id}")
        return asset
    except AssetLibraryError:
        raise
    except Exception as e:
        logger.error(f"Failed to add asset for user {user_id}: {e}")
        raise AssetLibraryError("加入资产库失败，请稍后重试", "add_failed")
    finally:
        # 失败清理：临时文件 / 已转正但落库失败的文件 / 已预留的配额
        if asset_id is None:
            _remove_file_quietly(tmp_path)
            if final_path is not None:
                _remove_file_quietly(final_path)
            if reserved > 0:
                AssetLibraryQuotaModel.release(user_id, reserved)


# ============ 查询 ============

def _apply_filters(
    sql_params: List[Any],
    group_id: Any = None,
    asset_type: Optional[str] = None,
    keyword: Optional[str] = None,
    scope: str = "all",
    owner_user_id: Optional[int] = None,
) -> str:
    """组装 group/type/keyword/scope 过滤片段（参数顺序追加到 sql_params）。

    group_id 支持 'ungrouped' 哨兵：筛选未分组资产（group_id IS NULL）。
    """
    clauses = []
    if group_id == "ungrouped":
        clauses.append("a.group_id IS NULL")
    elif group_id is not None:
        clauses.append("a.group_id = %s")
        sql_params.append(int(group_id))
    if asset_type:
        clauses.append("a.asset_type = %s")
        sql_params.append(asset_type)
    if keyword and keyword.strip():
        clauses.append("a.name LIKE %s")
        sql_params.append(f"%{keyword.strip()}%")
    if scope == "mine" and owner_user_id is not None:
        clauses.append("a.user_id = %s")
        sql_params.append(owner_user_id)
    elif scope == "shared" and owner_user_id is not None:
        clauses.append("a.user_id != %s")
        sql_params.append(owner_user_id)
    return (" AND " + " AND ".join(clauses)) if clauses else ""


def list_assets(
    user_id: int,
    page: int = 1,
    page_size: int = ALC.DEFAULT_PAGE_SIZE,
    group_id: Optional[int] = None,
    asset_type: Optional[str] = None,
    keyword: Optional[str] = None,
    scope: str = "all",
    is_admin: bool = False,
    lite: bool = False,
) -> Dict[str, Any]:
    """列出用户可见的资产（分页 + 附加属主名/成员映射/可编辑/可删除标志）。

    lite=True：@ 提及等轻量场景——跳过 COUNT(*)（LIMIT page_size+1 探测
    has_more）、跳过属主名/成员映射/权限标志/文件存在性检查（后者为每条
    一次磁盘 stat，资产多时是列表请求的主要额外开销），只返回
    id/name/file_url/group_id。
    """
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or ALC.DEFAULT_PAGE_SIZE)), ALC.MAX_PAGE_SIZE)

    visible_where, visible_params = _visible_where(user_id)
    filters = _apply_filters(visible_params, group_id, asset_type, keyword, scope, user_id)

    if lite:
        # has_more 探测：多取一条，多出即还有下一页——省掉可见性 OR 过滤下的全表 COUNT
        lite_params = list(visible_params)
        lite_sql = f"""
            SELECT a.id, a.name, a.file_path, a.group_id FROM asset_library a
            WHERE {visible_where}{filters}
            ORDER BY a.create_at DESC, a.id DESC
            LIMIT %s OFFSET %s
        """
        lite_params.extend([page_size + 1, (page - 1) * page_size])
        rows = execute_query(lite_sql, tuple(lite_params), fetch_all=True) or []
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        items = [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "file_url": f"/upload/{r['file_path']}" if r["file_path"] else "",
                "group_id": r["group_id"],
            }
            for r in rows
        ]
        return {"items": items, "has_more": has_more, "page": page, "page_size": page_size}

    count_sql = f"SELECT COUNT(*) AS cnt FROM asset_library a WHERE {visible_where}{filters}"
    count_row = execute_query(count_sql, tuple(visible_params), fetch_one=True)
    total = int(count_row["cnt"]) if count_row else 0

    params = list(visible_params)
    list_sql = f"""
        SELECT a.* FROM asset_library a
        WHERE {visible_where}{filters}
        ORDER BY a.create_at DESC, a.id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([page_size, (page - 1) * page_size])
    rows = execute_query(list_sql, tuple(params), fetch_all=True) or []
    items = [AssetItem(**row) for row in rows]

    owner_ids = list({item.user_id for item in items})
    names = UsersModel.get_display_names(owner_ids) if owner_ids else {}
    member_map = AssetPermissionMemberModel.map_by_assets([item.id for item in items])

    data = []
    for item in items:
        d = item.to_dict()
        d["owner_name"] = names.get(item.user_id, f"用户{item.user_id}")
        d["can_edit"] = can_edit(item, user_id, is_admin)
        d["can_delete"] = can_delete(item, user_id, is_admin)
        d["file_missing"] = not asset_file_exists(item.file_path)
        members = member_map.get(item.id, {})
        d["view_members"] = members.get("view", [])
        d["edit_members"] = members.get("edit", [])
        data.append(d)
    return {"items": data, "total": total, "page": page, "page_size": page_size}


def get_asset_detail(user_id: int, asset_id: int, is_admin: bool = False) -> Dict[str, Any]:
    """资产详情（需查看权限；管理员可查看任意资产）。"""
    asset = AssetLibraryModel.get_by_id(int(asset_id))
    if not asset or not (can_view(asset, user_id) or is_admin):
        raise AssetLibraryError("资产不存在或无权访问", "not_found")
    d = asset.to_dict()
    d["owner_name"] = UsersModel.get_display_names([asset.user_id]).get(asset.user_id, f"用户{asset.user_id}")
    d["can_edit"] = can_edit(asset, user_id, is_admin)
    d["can_delete"] = can_delete(asset, user_id, is_admin)
    d["file_missing"] = not asset_file_exists(asset.file_path)
    members = _perm_members(asset.id)
    d["view_members"] = members.get("view", [])
    d["edit_members"] = members.get("edit", [])
    return d


# ============ 编辑 / 清除 ============

def update_asset(
    user_id: int,
    asset_id: int,
    is_admin: bool = False,
    name: Optional[str] = None,
    group_id: Any = "__unset__",
    view_permission: Optional[str] = None,
    edit_permission: Optional[str] = None,
    view_members: Optional[Sequence[int]] = None,
    edit_members: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """编辑资产元信息（名称/分组/权限设置），需编辑权限。"""
    asset = AssetLibraryModel.get_by_id(int(asset_id))
    if not asset or not (can_view(asset, user_id) or is_admin):
        raise AssetLibraryError("资产不存在或无权访问", "not_found")
    if not can_edit(asset, user_id, is_admin):
        raise AssetLibraryError("没有该资产的编辑权限", "forbidden")

    fields: Dict[str, Any] = {}
    if name is not None:
        fields["name"] = (name or "").strip()[:ALC.ASSET_NAME_MAX_LENGTH] or asset.name
    if group_id != "__unset__":
        if group_id in (None, "", 0):
            fields["group_id"] = None
        else:
            group = AssetGroupModel.get_by_id(int(group_id))
            if not group:
                raise AssetLibraryError("分组不存在", "group_not_found")
            fields["group_id"] = group.id
    if view_permission is not None:
        _validate_permission(view_permission, "查看权限")
        fields["view_permission"] = view_permission
    if edit_permission is not None:
        _validate_permission(edit_permission, "编辑权限")
        fields["edit_permission"] = edit_permission

    if fields:
        AssetLibraryModel.update(asset.id, **fields)
    if view_members is not None:
        AssetPermissionMemberModel.replace_for_asset(
            asset.id, ALC.PERM_TYPE_VIEW, _normalize_members(view_members), exclude_user_id=asset.user_id)
    if edit_members is not None:
        AssetPermissionMemberModel.replace_for_asset(
            asset.id, ALC.PERM_TYPE_EDIT, _normalize_members(edit_members), exclude_user_id=asset.user_id)
    return get_asset_detail(user_id, asset_id, is_admin)


def purge_asset(asset_id: int, user_id: Optional[int] = None, is_admin: bool = False) -> Dict[str, Any]:
    """删除资产（属主或管理员）：删文件 + 删记录 + 删成员 + 释放配额（幂等）。

    user_id 为 None 视为内部管理直调（不做属主校验）；否则须属主或管理员。
    文件删除丢调用方线程池（API 层 asyncio.to_thread 包装本函数）；
    记录/配额已清理，文件路径异常（脏数据）不应让接口失败造成"半清除"误报
    """
    asset = AssetLibraryModel.get_by_id(int(asset_id))
    if not asset:
        raise AssetLibraryError("资产不存在", "not_found")
    if user_id is not None and not can_delete(asset, user_id, is_admin):
        raise AssetLibraryError("没有该资产的删除权限", "forbidden")
    AssetPermissionMemberModel.delete_for_asset(asset.id)
    AssetLibraryModel.delete(asset.id)
    AssetLibraryQuotaModel.release(asset.user_id, asset.file_size)
    if asset.file_path:
        try:
            local = resolve_upload_url_to_local_path(f"/upload/{asset.file_path}")
            _remove_file_quietly(Path(local))
        except ValueError as e:
            logger.warning(f"Asset {asset_id} has invalid file_path '{asset.file_path}', skip file removal: {e}")
    logger.info(f"Asset {asset_id} purged (by user={user_id}, admin={is_admin}, owner={asset.user_id}, freed {asset.file_size} bytes)")
    return {"asset_id": asset.id, "freed_bytes": asset.file_size, "owner_user_id": asset.user_id}


# ============ 分组 ============

def list_groups(user_id: int) -> Tuple[List[Dict[str, Any]], int]:
    """共享分组目录 + 每组可见资产计数 + 未分组计数。返回 (groups, ungrouped_count)。"""
    groups = AssetGroupModel.list_all()
    visible_where, visible_params = _visible_where(user_id)
    count_sql = f"""
        SELECT a.group_id, COUNT(*) AS cnt FROM asset_library a
        WHERE {visible_where}
        GROUP BY a.group_id
    """
    rows = execute_query(count_sql, tuple(visible_params), fetch_all=True) or []
    counts = {int(r["group_id"]): int(r["cnt"]) for r in rows if r["group_id"] is not None}
    ungrouped = int(next((int(r["cnt"]) for r in rows if r["group_id"] is None), 0))
    data = [{
        "id": g.id,
        "name": g.name,
        "creator_user_id": g.creator_user_id,
        "asset_count": counts.get(g.id, 0),
        "can_manage": None,  # 由 API 层按 is_admin 填充
    } for g in groups]
    return data, ungrouped


def create_group(user_id: int, name: str) -> Dict[str, Any]:
    text = (name or "").strip()[:ALC.GROUP_NAME_MAX_LENGTH]
    if not text:
        raise AssetLibraryError("分组名称不能为空", "invalid_group_name")
    existing = AssetGroupModel.get_by_name(text)
    if existing:
        raise AssetLibraryError("分组已存在", "group_exists")
    group_id = AssetGroupModel.create(text, user_id)
    group = AssetGroupModel.get_by_id(group_id)
    return {"id": group.id, "name": group.name, "creator_user_id": group.creator_user_id, "asset_count": 0}


def _ensure_group_manager(group, user_id: int, is_admin: bool) -> None:
    if not is_admin and group.creator_user_id != user_id:
        raise AssetLibraryError("只有分组创建者或管理员可以管理该分组", "forbidden")


def rename_group(user_id: int, group_id: int, name: str, is_admin: bool = False) -> Dict[str, Any]:
    group = AssetGroupModel.get_by_id(int(group_id))
    if not group:
        raise AssetLibraryError("分组不存在", "group_not_found")
    _ensure_group_manager(group, user_id, is_admin)
    text = (name or "").strip()[:ALC.GROUP_NAME_MAX_LENGTH]
    if not text:
        raise AssetLibraryError("分组名称不能为空", "invalid_group_name")
    existing = AssetGroupModel.get_by_name(text)
    if existing and existing.id != group.id:
        raise AssetLibraryError("分组名称已被使用", "group_exists")
    AssetGroupModel.rename(group.id, text)
    return {"id": group.id, "name": text}


def delete_group(user_id: int, group_id: int, is_admin: bool = False) -> Dict[str, Any]:
    group = AssetGroupModel.get_by_id(int(group_id))
    if not group:
        raise AssetLibraryError("分组不存在", "group_not_found")
    _ensure_group_manager(group, user_id, is_admin)
    counts = AssetLibraryModel.count_by_group([group.id])
    if counts.get(group.id, 0) > 0:
        raise AssetLibraryError("分组内仍有资产，请先移出后再删除", "group_not_empty")
    AssetGroupModel.delete(group.id)
    return {"id": group.id}


# ============ 配额 / 用户搜索 ============

def get_quota(user_id: int) -> Dict[str, Any]:
    quota = AssetLibraryQuotaModel.get_by_user(user_id)
    if not quota:
        return {"quota_bytes": ALC.DEFAULT_QUOTA_BYTES, "used_bytes": 0}
    return quota


def search_user_exact(account: str) -> Optional[Dict[str, Any]]:
    """按完整账号精确查找用户（指定成员添加）。

    必须完整输入（手机号 / 邮箱 / 昵称全等），不做模糊联想：
    找到返回 {user_id, display_name}，找不到返回 None（前端据此提示
    「用户共享成功 / 没有查找到这个用户」）。
    """
    uid = UsersModel.find_id_by_exact_account((account or "").strip())
    if not uid:
        return None
    names = UsersModel.get_display_names([uid])
    return {"user_id": uid, "display_name": names.get(uid, f"用户{uid}")}


def list_user_assets_for_admin(user_id: int, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """管理员按用户列资产（清除入口用）。"""
    items = AssetLibraryModel.list_by_user(user_id, limit=limit, offset=offset)
    return {
        "items": [item.to_dict() for item in items],
        "total": AssetLibraryModel.count_by_user(user_id),
    }
