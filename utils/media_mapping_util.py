"""
媒体文件映射工具 - 为角色/场景/道具的图片和音频自动创建 CDN mapping

策略：
- 只对 reference_image（主图）和 default_voice（音频）创建 mapping
- 使用 (CHARACTER/LOCATION/PROPS, entity_db_id, label) 实体关联
- label 区分媒体类型："image"（主图）、"voice"（音频）
- 同 label 同 local_path → 跳过；同 label 不同 local_path → 删旧建新
"""
import logging
import os
from typing import Optional
from urllib.parse import unquote, urlparse

from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


def extract_local_path_from_url(url: str) -> Optional[str]:
    """
    从「本服务 upload 目录」的图片 URL 中提取本地相对路径（**与域名无关**）。

    只要 URL 的 path 以 `/upload/` 开头即认定为本服务文件，去掉前导 `/` 返回相对路径；
    其它路径（如外部 CDN、`/static/` 等）返回 None。

    本函数只做「字符串提取 + 路径穿越片段拒绝」，不读磁盘、不校验文件是否存在。
    **调用方拿到相对路径后，需通过安全路径解析器映射并校验文件存在**——否则当某
    `/upload/` URL 实际指向另一台机器的文件时，可能读到本机同名路径的错误文件。

    Examples:
        "http://localhost:8000/upload/character/pic/abc.png" → "upload/character/pic/abc.png"
        "http://zjt_dev.perseids.cn/upload/image_to_video/2/x.png" → "upload/image_to_video/2/x.png"
        "/upload/character/pic/abc.png" → "upload/character/pic/abc.png"
        "https://external-cdn.com/image.png" → None

    Args:
        url: 图片 URL 或路径

    Returns:
        本地相对路径（无前导 /）；非 `/upload/` 路径或空值返回 None。
    """
    if not url or not isinstance(url, str):
        return None

    parsed = urlparse(url)
    path = unquote(parsed.path)

    if not path.startswith("/upload/"):
        return None

    # URL path 最终会映射到本地文件，必须在任何 join 之前拒绝路径穿越。
    # 同时拒绝反斜杠，避免 Windows 将其解释为目录分隔符。
    relative_parts = path[len("/upload/"):].split("/")
    if "\\" in path or any(part in (".", "..") for part in relative_parts):
        return None

    return path.lstrip("/")


def upload_local_path(file_path: str) -> str:
    """
    计算上传目录内文件的规范 local_path（注册 CDN mapping 与中间件查询的统一格式）。

    格式：相对项目根、带 upload/ 前缀的 POSIX 路径，如 "upload/workflow/12/xxx.png"。
    cdn_redirect_middleware 以请求路径 lstrip("/") 后的值查库、trigger_cdn_upload 以
    项目根拼接该值定位文件，两处都要求此前缀——曾有用 upload 根做 relpath 基准导致
    前缀缺失、注册永不命中且不可上传的事故，故收敛到本函数单一出口。

    Args:
        file_path: upload 目录下文件的绝对路径（应在 get_upload_dir() 之内）

    Returns:
        规范 local_path；file_path 不在 upload 目录内时返回其相对项目根的 POSIX 路径。
    """
    from config.constant import UploadPathConstants
    from utils.project_path import get_upload_dir, get_project_root

    try:
        rel = os.path.relpath(file_path, get_upload_dir()).replace(os.sep, "/")
    except ValueError:
        # Windows 跨盘符等场景 relpath 抛 ValueError，退回相对项目根口径
        return os.path.relpath(file_path, get_project_root()).replace(os.sep, "/")
    if rel.startswith(".."):
        return os.path.relpath(file_path, get_project_root()).replace(os.sep, "/")
    return f"{UploadPathConstants.UPLOAD_ROOT}/{rel}"


def register_uploaded_file_mapping(
    user_id: Optional[int],
    local_path: str,
    entity_type: int,
    policy_code: str,
    source_id: Optional[int] = None,
) -> Optional[int]:
    """
    上传素材落盘后注册 CDN mapping 并触发异步上传七牛。

    供此前未接入 CDN 的上传链路（工作流素材、TTS 配音结果等）调用：
    注册后 cdn_redirect_middleware 会把后续 /upload/ 访问 302 到七牛，
    媒体出流量不再占用 frp 隧道带宽。

    本函数绝不抛异常——注册失败只记 warning，不影响上传主流程。

    Args:
        user_id: 上传用户 ID（可为 None）
        local_path: 相对项目根、含 upload/ 前缀的 POSIX 路径，
            如 "upload/workflow/12/xxx.png"（统一用 upload_local_path() 生成）
        entity_type: MediaFileEntity 枚举值（如 WORKFLOW / TTS）
        policy_code: MediaFilePolicy 策略（用户长期资产用 NEVER_EXPIRE）
        source_id: 关联业务记录 ID（可选）

    Returns:
        mapping_id；未启用 CDN 或注册失败返回 None
    """
    try:
        from config.config_util import get_config
        from model.media_file_mapping import MediaFileMappingModel
        from utils.cdn_util import CDNUtil
        from utils.mime_type import get_mime_type_from_extension

        if not get_config().get("server", {}).get("auto_upload_to_cdn", False):
            return None
        if not local_path:
            return None

        # 同路径已注册过则复用（文件名含时间戳+uuid，正常不会重复；防御性兜底）
        existing = MediaFileMappingModel.get_by_local_path(local_path)
        if existing:
            return existing.id

        file_size = None
        try:
            abs_path = os.path.join(get_project_root(), local_path)
            if os.path.exists(abs_path):
                file_size = os.path.getsize(abs_path)
        except Exception:
            pass

        ext = os.path.splitext(local_path)[1].lower()
        mapping_id = MediaFileMappingModel.create(
            user_id=user_id,
            local_path=local_path,
            cloud_path=None,
            policy_code=policy_code,
            entity_type=entity_type,
            source_id=source_id,
            media_type=get_mime_type_from_extension(ext),
            original_url=None,
            file_size=file_size,
        )
        CDNUtil.trigger_cdn_upload(mapping_id, local_path)
        logger.info(f"Registered CDN mapping {mapping_id} for uploaded file: {local_path}")
        return mapping_id
    except Exception as e:
        logger.warning(f"注册 CDN mapping 失败（不影响上传主流程）: {local_path}, {e}")
        return None


def ensure_entity_image_mapping(
    user_id,
    image_url: str,
    entity_type: int,
    entity_id: int,
    label: str = "image"
) -> Optional[int]:
    """
    为实体的媒体文件创建 CDN mapping

    Args:
        user_id: 用户 ID（str 或 int）
        image_url: 媒体文件 URL（图片或音频）
        entity_type: MediaFileEntity.CHARACTER / LOCATION / PROPS
        entity_id: 实体数据库 ID
        label: 媒体标签（"image" 主图 / "voice" 音频），默认 "image"

    Returns:
        mapping_id，跳过或失败返回 None
    """
    from config.config_util import get_config
    from config.media_file_policy import MediaFilePolicy
    from model.media_file_mapping import MediaFileMappingModel
    from utils.cdn_util import CDNUtil
    from utils.mime_type import get_mime_type_from_extension

    # 检查 CDN 是否启用
    if not get_config().get("server", {}).get("auto_upload_to_cdn", False):
        return None

    # 提取本地路径
    local_path = extract_local_path_from_url(image_url)
    if not local_path:
        return None

    # 按 (entity_type, source_id, label) 查找已有 mapping
    existing = MediaFileMappingModel.get_by_entity_and_label(entity_type, entity_id, label)

    # 如果已有 mapping 且 local_path 相同 → 跳过
    if existing and existing.local_path == local_path:
        logger.info(f"CDN mapping already exists for entity ({entity_type}, {entity_id}, label={label}) with same path: {local_path}, skip")
        return existing.id

    # local_path 不同（文件换了）→ 删旧建新
    if existing:
        try:
            MediaFileMappingModel.delete_by_local_path(existing.local_path)
        except Exception as e:
            logger.warning(f"Failed to delete old mapping {existing.local_path}: {e}")

    # 确定用户 ID
    try:
        uid = int(user_id) if user_id else None
    except (ValueError, TypeError):
        uid = None

    # MIME 类型
    ext = os.path.splitext(local_path)[1].lower()
    media_type = get_mime_type_from_extension(ext)

    # 文件大小（best-effort）
    file_size = None
    try:
        abs_path = os.path.join(get_project_root(), local_path)
        if os.path.exists(abs_path):
            file_size = os.path.getsize(abs_path)
    except Exception:
        pass

    # 创建 mapping
    mapping_id = MediaFileMappingModel.create(
        user_id=uid,
        local_path=local_path,
        cloud_path=None,
        policy_code=MediaFilePolicy.NEVER_EXPIRE,
        entity_type=entity_type,
        source_id=entity_id,
        media_type=media_type,
        original_url=image_url,
        file_size=file_size,
        label=label
    )

    # 触发异步 CDN 上传
    CDNUtil.trigger_cdn_upload(mapping_id, local_path)
    logger.info(f"Created CDN mapping {mapping_id} for entity ({entity_type}, {entity_id}, label={label}): {local_path}")

    return mapping_id


def ensure_character_image_mapping(user_id, world_id, character_name: str, image_url: str) -> Optional[int]:
    """为角色主图创建 CDN mapping"""
    from model.character import CharacterModel
    from model.media_file_mapping import MediaFileEntity

    try:
        world_id_int = int(world_id)
    except (ValueError, TypeError):
        return None

    char = CharacterModel.get_by_name(world_id_int, character_name)
    if not char or not char.id:
        logger.debug(f"Character '{character_name}' not found in DB, skip CDN mapping")
        return None

    return ensure_entity_image_mapping(user_id, image_url, MediaFileEntity.CHARACTER, char.id)


def ensure_location_image_mapping(user_id, world_id, location_name: str, image_url: str) -> Optional[int]:
    """为场景主图创建 CDN mapping"""
    from model.location import LocationModel
    from model.media_file_mapping import MediaFileEntity

    try:
        world_id_int = int(world_id)
    except (ValueError, TypeError):
        return None

    loc = LocationModel.get_by_name(world_id_int, location_name)
    if not loc or not loc.id:
        logger.debug(f"Location '{location_name}' not found in DB, skip CDN mapping")
        return None

    return ensure_entity_image_mapping(user_id, image_url, MediaFileEntity.LOCATION, loc.id)


def ensure_prop_image_mapping(user_id, world_id, prop_name: str, image_url: str) -> Optional[int]:
    """为道具主图创建 CDN mapping"""
    from model.props import PropsModel
    from model.media_file_mapping import MediaFileEntity

    try:
        world_id_int = int(world_id)
    except (ValueError, TypeError):
        return None

    prop = PropsModel.get_by_name(world_id_int, prop_name)
    if not prop or not prop.id:
        logger.debug(f"Prop '{prop_name}' not found in DB, skip CDN mapping")
        return None

    return ensure_entity_image_mapping(user_id, image_url, MediaFileEntity.PROPS, prop.id)
