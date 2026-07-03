"""
CDN 工具类 - 统一处理 CDN 配置和 URL 获取逻辑

【函数族选择指南】
  get_cdn_url(media_mapping_id)      → 根据 media_file_mapping ID 获取公开 CDN URL
  get_signed_download_url(url,name)  → 为 CDN URL 生成带 Content-Disposition 的签名下载链接
  refresh_url_if_needed(url)         → 查数据库确认映射后刷新签名，返回 Optional[str]
  refresh_cdn_signed_url(url)        → 仅根据域名判断 + 直接重签名，始终返回 str（不查DB）
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
    def is_cdn_url(url: str) -> bool:
        """
        判断 URL 是否属于已配置的 CDN 域名

        Args:
            url: 待检测的完整 URL

        Returns:
            True 如果 URL 的 host 匹配任一已配置的 CDN 域名
        """
        from urllib.parse import urlparse
        from config.config_util import get_dynamic_config_value

        if not url:
            return False

        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return False

            cdn_domain = get_dynamic_config_value("file_storage", "qiniu_long_term", "cdn_domain", default="")
            qiniu_domain = get_dynamic_config_value("file_storage", "qiniu", "cdn_domain", default="")
            valid_hosts = {cdn_domain, qiniu_domain} - {""}

            return parsed.netloc in valid_hosts
        except Exception:
            return False

    @staticmethod
    def get_signed_download_url(url: str, attname: str) -> Optional[str]:
        """
        根据 CDN URL 重新生成带 attname 的签名下载链接
        attname 参与签名，使 CDN 返回 Content-Disposition: attachment

        Args:
            url: 原始 CDN URL
            attname: 下载时的自定义文件名

        Returns:
            带 attname 签名的下载 URL，失败返回 None
        """
        from urllib.parse import urlparse
        from config.config_util import get_dynamic_config_value
        from utils.file_storage.qiniu_storage import QiniuFileStorage

        try:
            parsed = urlparse(url)
            host = parsed.netloc
            # 提取文件 key（路径部分，去掉前导 /）
            key = parsed.path.lstrip('/')

            # 根据域名匹配对应的存储配置
            qiniu_long_term_domain = get_dynamic_config_value("file_storage", "qiniu_long_term", "cdn_domain", default="")
            qiniu_domain = get_dynamic_config_value("file_storage", "qiniu", "cdn_domain", default="")

            if host == qiniu_long_term_domain and qiniu_long_term_domain:
                access_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "access_key")
                secret_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "secret_key")
                bucket_name = get_dynamic_config_value("file_storage", "qiniu_long_term", "bucket_name")
                cdn_dom = qiniu_long_term_domain
            elif host == qiniu_domain and qiniu_domain:
                access_key = get_dynamic_config_value("file_storage", "qiniu", "access_key")
                secret_key = get_dynamic_config_value("file_storage", "qiniu", "secret_key")
                bucket_name = get_dynamic_config_value("file_storage", "qiniu", "bucket_name")
                cdn_dom = qiniu_domain
            else:
                logger.warning(f"[get_signed_download_url] 未匹配到 CDN 配置: host={host}")
                return None

            if not (access_key and secret_key and bucket_name and cdn_dom):
                logger.warning(f"[get_signed_download_url] CDN 存储配置不完整: host={host}")
                return None

            storage = QiniuFileStorage(
                access_key=access_key,
                secret_key=secret_key,
                bucket_name=bucket_name,
                cdn_domain=cdn_dom
            )
            # attname 参与签名，有效期 28 小时
            return storage.get_download_url(key, expires=100800, attname=attname)
        except Exception as e:
            logger.error(f"[get_signed_download_url] 生成签名下载 URL 失败: {e}")
            return None

    @staticmethod
    def refresh_url_if_needed(url: str) -> Optional[str]:
        """
        检查 URL 是否需要刷新签名，如果是则返回新签名的 URL

        用于后台定时任务或数据加载场景：先查询 media_file_mapping 表确认该文件
        是否已上传到 CDN，再重新生成签名 URL。如果文件未上传到 CDN（无映射记录），
        返回 None 表示不需要刷新。

        与 refresh_cdn_signed_url 的区别：
        - refresh_url_if_needed: 先查数据库确认映射关系，适合需要精确判断的场景
        - refresh_cdn_signed_url: 仅根据 URL 域名判断是否为 CDN 链接并直接刷新签名，
          适合导出剪影草稿等已知 URL 是 CDN 链接的场景

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
    def refresh_cdn_signed_url(url: str) -> str:
        """
        检查 URL 是否为 CDN 链接，如果是则重新生成签名（防止 token 过期导致 403）。

        仅根据 URL 的域名判断是否为 CDN 链接（通过 is_cdn_url 检查），
        匹配则提取 cloud_path 直接重新签名，不查询数据库。
        非 CDN URL 原样返回，刷新失败也返回原始 URL（不会返回 None）。

        与 refresh_url_if_needed 的区别：
        - refresh_cdn_signed_url: 不查数据库，仅根据域名判断 + 直接重签名，始终返回 str。
          适合导出剪影草稿等批量刷新 URL 签名的场景。
        - refresh_url_if_needed: 先查 media_file_mapping 确认映射关系，返回 Optional[str]。
          适合需要精确判断文件是否已上传 CDN 的场景。

        Args:
            url: 原始媒体 URL（可能包含过期的 e/token 参数）

        Returns:
            刷新签名后的 URL 或原始 URL（刷新失败时也返回原始 URL）
        """
        if not url:
            return url

        try:
            from urllib.parse import urlparse
            from config.config_util import get_dynamic_config_value
            from utils.file_storage.qiniu_storage import QiniuFileStorage

            if not CDNUtil.is_cdn_url(url):
                return url

            parsed = urlparse(url)
            # 提取文件 key（路径部分，去掉前导 /），忽略旧的过期查询参数
            key = parsed.path.lstrip('/')

            host = parsed.netloc
            qiniu_long_term_domain = get_dynamic_config_value("file_storage", "qiniu_long_term", "cdn_domain", default="")
            qiniu_domain = get_dynamic_config_value("file_storage", "qiniu", "cdn_domain", default="")

            if host == qiniu_long_term_domain and qiniu_long_term_domain:
                access_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "access_key")
                secret_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "secret_key")
                bucket_name = get_dynamic_config_value("file_storage", "qiniu_long_term", "bucket_name")
                cdn_dom = qiniu_long_term_domain
            elif host == qiniu_domain and qiniu_domain:
                access_key = get_dynamic_config_value("file_storage", "qiniu", "access_key")
                secret_key = get_dynamic_config_value("file_storage", "qiniu", "secret_key")
                bucket_name = get_dynamic_config_value("file_storage", "qiniu", "bucket_name")
                cdn_dom = qiniu_domain
            else:
                return url

            if not (access_key and secret_key and bucket_name and cdn_dom):
                logger.warning(f"[refresh_cdn_signed_url] CDN 配置不完整，使用原始 URL: {url[:100]}")
                return url

            storage = QiniuFileStorage(
                access_key=access_key,
                secret_key=secret_key,
                bucket_name=bucket_name,
                cdn_domain=cdn_dom
            )
            # 重新生成签名 URL，有效期 28 小时，不使用 attname（仅用于内容下载）
            fresh_url = storage.get_download_url(key, expires=100800)
            logger.info(f"[refresh_cdn_signed_url] 已刷新 CDN URL 签名: {url[:80]}... -> 新签名")
            return fresh_url

        except Exception as e:
            logger.warning(f"[refresh_cdn_signed_url] 刷新 CDN URL 失败，使用原始 URL: {e}")
            return url

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
            from model.media_file_mapping import MediaFileMappingModel
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
