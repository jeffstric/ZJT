"""
CDN 存储管理模块
专门负责将本地文件同步到 CDN（如 AI Tools 生成的结果）
"""
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Optional
from config.config_util import get_dynamic_config_value
import logging

logger = logging.getLogger(__name__)


class CDNStorageManager:
    """CDN 存储管理器"""

    def __init__(self):
        self.enabled = get_dynamic_config_value("cdn_storage", "enabled", default=False)
        self.provider = get_dynamic_config_value("cdn_storage", "provider", default="qiniu")
        self._storage = None

        if self.enabled and self.provider == "qiniu":
            self._init_qiniu_storage()

    def _init_qiniu_storage(self):
        """初始化七牛云存储"""
        try:
            from utils.file_storage.qiniu_storage import QiniuFileStorage

            access_key = get_dynamic_config_value("cdn_storage", "access_key")
            secret_key = get_dynamic_config_value("cdn_storage", "secret_key")
            bucket_name = get_dynamic_config_value("cdn_storage", "bucket_name")
            cdn_domain = get_dynamic_config_value("cdn_storage", "cdn_domain")

            if access_key and secret_key and bucket_name and cdn_domain:
                self._storage = QiniuFileStorage(
                    access_key=access_key,
                    secret_key=secret_key,
                    bucket_name=bucket_name,
                    cdn_domain=cdn_domain
                )
                logger.info("CDN 存储初始化成功")
            else:
                logger.warning("CDN 七牛云配置不完整")
                self._storage = None
        except Exception as e:
            logger.error(f"初始化 CDN 存储失败: {e}")
            self._storage = None

    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self.enabled and self._storage is not None

    def _get_cdn_prefix(self) -> str:
        """获取 CDN 路径前缀"""
        return get_dynamic_config_value("cdn_storage", "prefix", default="ai_tools")

    async def upload_local_file(self, local_path: str) -> Optional[str]:
        """
        上传本地文件到 CDN

        Args:
            local_path: 本地文件相对路径（如 upload/medias/xxx.jpg）

        Returns:
            CDN 公开访问 URL，失败返回 None
        """
        if not self.is_enabled():
            return None

        try:
            # 获取项目根目录
            root_dir = Path(__file__).parent.parent
            file_path = root_dir / local_path

            if not file_path.exists():
                logger.error(f"本地文件不存在: {file_path}")
                return None

            # 生成 CDN key
            prefix = self._get_cdn_prefix()
            cdn_key = f"{prefix}/{local_path}"

            # 上传文件
            result = await self._storage.upload_file(cdn_key, str(file_path))

            if result.success:
                logger.info(f"文件上传 CDN 成功: {local_path} -> {result.url}")
                return result.url
            else:
                logger.error(f"文件上传 CDN 失败: {result.error}")
                return None

        except Exception as e:
            logger.error(f"上传到 CDN 异常: {e}")
            return None

    def upload_local_file_sync(self, local_path: str) -> Optional[str]:
        """同步版本的上传方法"""
        if not self.is_enabled():
            return None

        def _sync_upload():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.upload_local_file(local_path))
            finally:
                loop.close()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在独立线程中执行以避免嵌套事件循环
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(_sync_upload)
                    return future.result(timeout=60)
            else:
                return _sync_upload()
        except Exception as e:
            logger.error(f"同步上传到 CDN 失败: {e}")
            return None

    def get_public_url(self, cloud_key: str) -> Optional[str]:
        """
        获取 CDN 公开访问 URL

        Args:
            cloud_key: 云端存储路径

        Returns:
            CDN 公开访问 URL
        """
        if not self._storage:
            return None

        try:
            return self._storage.get_public_url(cloud_key)
        except Exception as e:
            logger.error(f"获取 CDN URL 失败: {e}")
            return None


# 全局单例
_cdn_storage = None


def get_cdn_storage() -> CDNStorageManager:
    """获取 CDN 存储管理器单例"""
    global _cdn_storage
    if _cdn_storage is None:
        _cdn_storage = CDNStorageManager()
    return _cdn_storage
