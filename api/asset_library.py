# -*- coding: utf-8 -*-
"""资产库 API 路由（/api/asset-library，见 docs/backend/asset_library.md）。

用户侧：加入/浏览/编辑资产、分组目录、容量查询、成员搜索、@引用数据源。
管理侧：资产清除走本路由 DELETE /assets/{id}（admin only），
配额设置在 api/admin.py（PUT /api/admin/users/{id}/asset-quota）。

鉴权：@require_permission + request.state.user_id（登录即可，
资产级权限由 services/asset_library_service.py 判定）。
所有同步 DB/IO 调用均经 asyncio.to_thread 包装，不阻塞事件循环（AGENTS.md 第 1 条）。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config.constant import AssetLibraryConstants as ALC
from model.users import UsersModel
from perseids_server.utils.permission import require_permission
from perseids_server.utils.auth_identity import get_auth_user_id
from services import asset_library_service as svc
from services.asset_library_service import AssetLibraryError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/asset-library", tags=["asset-library"])


# ============ 辅助 ============

def _current_user_id(request: Request) -> int:
    user_id = get_auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录状态失效，请重新登录")
    return int(user_id)


async def _is_admin(user_id: int) -> bool:
    user = await asyncio.to_thread(UsersModel.get_by_id, user_id)
    return bool(user and getattr(user, "role", None) == "admin")


def _http_error(e: AssetLibraryError) -> HTTPException:
    # not_found / group_not_found 均为"资源不存在"→ 统一 404（防枚举语义一致）
    status = 404 if e.code in ("not_found", "group_not_found") else (403 if e.code in ("forbidden", "quota_exceeded") else 400)
    return HTTPException(status_code=status, detail=e.message)


# ============ 请求模型 ============

class AssetAddRequest(BaseModel):
    source_url: str = Field(..., description="生成产物地址（http(s) 外链或本站 /upload 路径）")
    name: str = Field("未命名资产", max_length=ALC.ASSET_NAME_MAX_LENGTH)
    group_id: Optional[int] = None
    asset_type: str = ALC.ASSET_TYPE_IMAGE
    view_permission: str = ALC.PERMISSION_PRIVATE
    edit_permission: str = ALC.PERMISSION_PRIVATE
    view_members: List[int] = Field(default_factory=list)
    edit_members: List[int] = Field(default_factory=list)


class AssetUpdateRequest(BaseModel):
    name: Optional[str] = None
    group_id: Any = "__unset__"
    view_permission: Optional[str] = None
    edit_permission: Optional[str] = None
    view_members: Optional[List[int]] = None
    edit_members: Optional[List[int]] = None


class GroupCreateRequest(BaseModel):
    name: str = Field(..., max_length=ALC.GROUP_NAME_MAX_LENGTH)


class GroupRenameRequest(BaseModel):
    name: str = Field(..., max_length=ALC.GROUP_NAME_MAX_LENGTH)


# ============ 资产 ============

@router.get("/assets")
@require_permission("asset_library:view")
async def list_assets(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(ALC.DEFAULT_PAGE_SIZE, ge=1, le=ALC.MAX_PAGE_SIZE),
    group_id: Optional[int] = Query(None, description="分组筛选；配合 group_scope=ungrouped 查未分组"),
    group_scope: Optional[str] = Query(None, description="ungrouped=未分组"),
    asset_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, max_length=100),
    scope: str = Query("all", pattern="^(all|mine|shared)$"),
):
    """资产列表（仅返回当前用户可见的资产）。group_scope=ungrouped 查未分组。"""
    user_id = _current_user_id(request)
    effective_group = "ungrouped" if group_scope == "ungrouped" else group_id
    try:
        result = await asyncio.to_thread(
            svc.list_assets, user_id, page, page_size, effective_group, asset_type, keyword, scope,
        )
        return {"code": 0, "data": result}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.post("/assets")
@require_permission("asset_library:create")
async def add_asset(request: Request, body: AssetAddRequest):
    """加入资产库：下载/复制源文件到永久目录 + 配额预留。"""
    user_id = _current_user_id(request)
    try:
        asset = await svc.add_asset(
            user_id=user_id,
            source_url=body.source_url,
            name=body.name,
            group_id=body.group_id,
            asset_type=body.asset_type,
            view_permission=body.view_permission,
            edit_permission=body.edit_permission,
            view_members=body.view_members,
            edit_members=body.edit_members,
        )
        detail = await asyncio.to_thread(svc.get_asset_detail, user_id, asset.id)
        return {"code": 0, "data": detail}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.get("/assets/{asset_id}")
@require_permission("asset_library:view")
async def get_asset(request: Request, asset_id: int):
    """资产详情（需查看权限；管理员可查看任意资产）。"""
    user_id = _current_user_id(request)
    is_admin = await _is_admin(user_id)
    try:
        detail = await asyncio.to_thread(svc.get_asset_detail, user_id, asset_id, is_admin)
        return {"code": 0, "data": detail}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.put("/assets/{asset_id}")
@require_permission("asset_library:edit")
async def update_asset(request: Request, asset_id: int, body: AssetUpdateRequest):
    """编辑资产元信息（名称/分组/权限设置，需编辑权限）。"""
    user_id = _current_user_id(request)
    is_admin = await _is_admin(user_id)
    try:
        detail = await asyncio.to_thread(
            svc.update_asset, user_id, asset_id, is_admin,
            body.name, body.group_id, body.view_permission, body.edit_permission,
            body.view_members, body.edit_members,
        )
        return {"code": 0, "data": detail}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.delete("/assets/{asset_id}")
@require_permission("asset_library:purge")
async def purge_asset(request: Request, asset_id: int):
    """清除资产（仅管理员；删文件 + 删记录 + 释放该用户容量记录）。"""
    user_id = _current_user_id(request)
    if not await _is_admin(user_id):
        raise HTTPException(status_code=403, detail="资产库内容不允许删除，仅管理员可清除")
    try:
        result = await asyncio.to_thread(svc.purge_asset, asset_id)
        return {"code": 0, "data": result}
    except AssetLibraryError as e:
        raise _http_error(e)


# ============ 分组 ============

@router.get("/groups")
@require_permission("asset_library:view")
async def list_groups(request: Request):
    """共享分组目录（含每组可见资产计数与未分组计数）。"""
    user_id = _current_user_id(request)
    is_admin = await _is_admin(user_id)
    try:
        def _run():
            groups, ungrouped = svc.list_groups(user_id)
            for g in groups:
                g["can_manage"] = bool(is_admin or g.get("creator_user_id") == user_id)
            return {"groups": groups, "ungrouped_count": ungrouped}

        data = await asyncio.to_thread(_run)
        return {"code": 0, "data": data}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.post("/groups")
@require_permission("asset_library:create")
async def create_group(request: Request, body: GroupCreateRequest):
    """创建分组（共享目录，任何登录用户可建）。"""
    user_id = _current_user_id(request)
    try:
        group = await asyncio.to_thread(svc.create_group, user_id, body.name)
        return {"code": 0, "data": group}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.put("/groups/{group_id}")
@require_permission("asset_library:edit")
async def rename_group(request: Request, group_id: int, body: GroupRenameRequest):
    """重命名分组（创建者或管理员）。"""
    user_id = _current_user_id(request)
    is_admin = await _is_admin(user_id)
    try:
        result = await asyncio.to_thread(svc.rename_group, user_id, group_id, body.name, is_admin)
        return {"code": 0, "data": result}
    except AssetLibraryError as e:
        raise _http_error(e)


@router.delete("/groups/{group_id}")
@require_permission("asset_library:edit")
async def delete_group(request: Request, group_id: int):
    """删除分组（创建者或管理员；组内有资产时拒绝）。"""
    user_id = _current_user_id(request)
    is_admin = await _is_admin(user_id)
    try:
        result = await asyncio.to_thread(svc.delete_group, user_id, group_id, is_admin)
        return {"code": 0, "data": result}
    except AssetLibraryError as e:
        raise _http_error(e)


# ============ 配额 / 成员搜索 ============

@router.get("/quota")
@require_permission("asset_library:view")
async def get_quota(request: Request):
    """当前用户资产库容量使用情况。"""
    user_id = _current_user_id(request)
    quota = await asyncio.to_thread(svc.get_quota, user_id)
    return {"code": 0, "data": quota}


@router.get("/users")
@require_permission("asset_library:view")
async def search_users(
    request: Request,
    keyword: str = Query("", max_length=50),
    limit: int = Query(ALC.MEMBER_SEARCH_LIMIT, ge=1, le=ALC.MEMBER_SEARCH_LIMIT),
):
    """按昵称/手机号/邮箱搜索用户（指定成员选择器数据源，仅返回 id + 展示名）。"""
    _current_user_id(request)
    users = await asyncio.to_thread(svc.search_users, keyword, limit)
    return {"code": 0, "data": {"items": users}}
