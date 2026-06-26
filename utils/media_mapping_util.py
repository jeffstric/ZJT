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
from urllib.parse import urlparse

from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


def extract_local_path_from_url(url: str) -> Optional[str]:
    """
    从「本服务 upload 目录」的图片 URL 中提取本地相对路径（**与域名无关**）。

    只要 URL 的 path 以 `/upload/` 开头即认定为本服务文件，去掉前导 `/` 返回相对路径；
    其它路径（如外部 CDN、`/static/` 等）返回 None。

    本函数只做「字符串提取」，不读磁盘、不校验文件是否存在。
    **调用方拿到相对路径后，需自行 `os.path.join(get_project_root(), rel)` 拼成绝对路径，
    并用 `os.path.exists()` 校验后再使用**——否则当某 `/upload/` URL 实际指向另一台机器
    的文件时，可能读到本机同名路径的错误文件。

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
    path = parsed.path

    if not path.startswith("/upload/"):
        return None

    return path.lstrip("/")


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
