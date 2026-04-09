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
                # 私有 bucket 需要生成带签名的临时 URL，有效期 28 小时
                return storage.get_download_url(mapping.cloud_path, expires=100800)
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

    @staticmethod
    def refresh_url_if_needed(url: str) -> Optional[str]:
        """
        检查 URL 是否需要刷新签名，如果是则返回新签名的 URL

        Args:
            url: 原始 CDN URL（可能已过期）

        Returns:
            新签名的 URL 或 None（不需要刷新或刷新失败）
        """
        from urllib.parse import urlparse
        from model.media_file_mapping import MediaFileMappingModel
        from config.config_util import get_dynamic_config_value

        try:
            # 检查是否启用了 auto_upload_to_cdn
            auto_upload = get_dynamic_config_value("server", "auto_upload_to_cdn", default=False)
            if not auto_upload:
                return None

            parsed = urlparse(url)
            # 检查 URL host 是否匹配配置的 CDN domain
            cdn_domain = get_dynamic_config_value("file_storage", "qiniu_long_term", "cdn_domain", default="")
            qiniu_domain = get_dynamic_config_value("file_storage", "qiniu", "cdn_domain", default="")
            valid_hosts = {cdn_domain, qiniu_domain} - {""}

            if parsed.netloc not in valid_hosts:
                return None

            # 提取 cloud_path 并查询 media_file_mapping
            cloud_path = parsed.path.lstrip("/")
            mapping = MediaFileMappingModel.get_by_local_path(cloud_path)

            if mapping and mapping.cloud_path:
                # 重新生成签名 URL，有效期 28 小时
                return CDNUtil.get_cdn_url(mapping.id)
        except Exception as e:
            logger.warning(f"刷新 CDN URL 失败: {e}")

        return None

    @staticmethod
    def trigger_cdn_upload(mapping_id: int, local_path: str):
        """
        触发 CDN 上传（异步）

        在独立线程中执行上传，避免阻塞主流程

        Args:
            mapping_id: media_file_mapping 记录 ID
            local_path: 本地文件相对路径
        """
        import concurrent.futures

        def _async_upload():
            try:
                storage, enabled = CDNUtil._get_cdn_storage()

                if not enabled:
                    logger.info(f"CDN 未启用，跳过上传: {local_path}")
                    MediaFileMappingModel.update_status(local_path, 'active')
                    return

                # 获取项目根目录
                import os
                from pathlib import Path
                root_dir = Path(__file__).parent.parent
                file_path = root_dir / local_path

                if not os.path.exists(file_path):
                    logger.error(f"本地文件不存在: {file_path}")
                    MediaFileMappingModel.update_status(local_path, 'active')
                    return

                # 上传文件
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(storage.upload_file(local_path, str(file_path)))
                finally:
                    loop.close()

                if result.success:
                    MediaFileMappingModel.update_cloud_path(local_path, local_path)
                    logger.info(f"CDN 上传成功: {local_path}")
                else:
                    MediaFileMappingModel.update_status(local_path, 'active')
                    logger.warning(f"CDN 上传失败: {result.error}")

            except Exception as e:
                logger.error(f"CDN 上传异常: {e}")
                try:
                    MediaFileMappingModel.update_status(local_path, 'active')
                except:
                    pass

        # 在线程池中执行
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(_async_upload)
