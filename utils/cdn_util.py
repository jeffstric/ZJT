"""
CDN 工具类 - 统一处理 CDN 配置和 URL 获取逻辑
"""
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class CDNStatus:
    """CDN 状态枚举"""
    READY = "ready"       # CDN 已完成
    PENDING = "pending"    # CDN 还在处理中
    NOT_ENABLED = "not_enabled"  # 未启用 CDN
    ERROR = "error"       # 获取失败


class CDNUtil:
    """CDN 工具类"""

    @staticmethod
    def _get_cdn_storage():
        """
        获取 CDN 存储实例（使用 file_storage.qiniu_long_term 配置）

        Returns:
            tuple: (storage, enabled) - (QiniuFileStorage实例或None, 是否启用)
        """
        from config.config_util import get_dynamic_config_value
        from utils.file_storage.qiniu_storage import QiniuFileStorage

        auto_upload = get_dynamic_config_value("server", "auto_upload_to_cdn", default=False)
        if not auto_upload:
            return None, False

        access_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "access_key")
        secret_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "secret_key")
        bucket_name = get_dynamic_config_value("file_storage", "qiniu_long_term", "bucket_name")
        cdn_domain = get_dynamic_config_value("file_storage", "qiniu_long_term", "cdn_domain")

        if not (access_key and secret_key and bucket_name and cdn_domain):
            raise ValueError("server.auto_upload_to_cdn=true 但 file_storage.qiniu_long_term 配置不完整")

        storage = QiniuFileStorage(
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=bucket_name,
            cdn_domain=cdn_domain
        )
        return storage, True

    @staticmethod
    def get_cdn_url(media_mapping_id: int) -> Optional[str]:
        """
        获取 CDN URL

        Args:
            media_mapping_id: media_file_mapping 记录 ID

        Returns:
            CDN 公开访问 URL，如果未上传完成返回 None
        """
        from model.media_file_mapping import MediaFileMappingModel

        mapping = MediaFileMappingModel.get_by_id(media_mapping_id)
        if not mapping or not mapping.cloud_path:
            return None

        try:
            storage, enabled = CDNUtil._get_cdn_storage()
            if enabled:
                return storage.get_public_url(mapping.cloud_path)
        except Exception as e:
            logger.error(f"获取 CDN URL 失败: {e}")

        return None

    @staticmethod
    def get_media_url(
        media_mapping_id: Optional[int],
        local_url: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """
        获取媒体文件 URL，优先返回 CDN 地址

        Args:
            media_mapping_id: media_file_mapping 记录 ID
            local_url: 本地 URL（CDN 不可用时的 fallback）

        Returns:
            Tuple[url, status]:
            - (cdn_url, CDNStatus.READY) - CDN 已完成，返回 CDN 地址
            - (None, CDNStatus.PENDING) - CDN 还在处理中
            - (local_url, CDNStatus.NOT_ENABLED) - 未启用 CDN，直接使用本地地址
            - (local_url, CDNStatus.ERROR) - 获取 CDN URL 失败，fallback 到本地地址
        """
        # 无需 CDN
        if not media_mapping_id:
            return local_url, CDNStatus.NOT_ENABLED

        try:
            cdn_url = CDNUtil.get_cdn_url(media_mapping_id)
            if cdn_url:
                return cdn_url, CDNStatus.READY
            else:
                # CDN 还在处理中
                logger.info(f"CDN 还在处理中，media_mapping_id={media_mapping_id}")
                return None, CDNStatus.PENDING
        except Exception as e:
            logger.error(f"获取 CDN URL 失败: {e}")
            return local_url, CDNStatus.ERROR
