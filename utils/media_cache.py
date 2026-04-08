"""
媒体文件缓存管理模块
实现生成完成的图片/视频自动缓存到本地，按日期目录组织，并支持超时/容量限制自动清理
"""
import hashlib
import aiohttp
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from config.config_util import get_dynamic_config_value, get_config
from config.media_file_policy import MediaFilePolicy
from model.media_file_mapping import MediaFileEntity
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MediaCacheManager:
    """媒体缓存管理器"""
    
    def __init__(self):
        """初始化缓存管理器"""
        self.config = get_config()
        self.enabled = get_dynamic_config_value("media_cache", "enabled", default=True)
        self.cache_dir = get_dynamic_config_value("media_cache", "cache_dir", default="upload/cache")
        self.max_days = get_dynamic_config_value("media_cache", "max_days", default=30)
        self.max_size_gb = get_dynamic_config_value("media_cache", "max_size_gb", default=10)
        self.upload_to_cloud = get_dynamic_config_value("server", "auto_upload_to_cdn", default=False)
        self.cloud_prefix = get_dynamic_config_value("media_cache", "cloud_prefix", default="cache")

        # 获取项目根目录
        self.root_dir = Path(__file__).parent.parent
        self.cache_path = self.root_dir / self.cache_dir

        # 初始化云端存储
        self._storage = None
        if self.upload_to_cloud:
            self._init_storage()

        # 确保缓存目录存在
        self._ensure_cache_dir()

    def _init_storage(self):
        """初始化云端存储"""
        try:
            from utils.file_storage.qiniu_storage import QiniuFileStorage
            access_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "access_key")
            secret_key = get_dynamic_config_value("file_storage", "qiniu_long_term", "secret_key")
            bucket_name = get_dynamic_config_value("file_storage", "qiniu_long_term", "bucket_name")
            cdn_domain = get_dynamic_config_value("file_storage", "qiniu_long_term", "cdn_domain")

            if access_key and secret_key and bucket_name and cdn_domain:
                self._storage = QiniuFileStorage(
                    access_key=access_key,
                    secret_key=secret_key,
                    bucket_name=bucket_name,
                    cdn_domain=cdn_domain
                )
                logger.info("云端存储初始化成功")
            else:
                logger.warning("七牛云配置不完整，无法启用云端存储")
        except Exception as e:
            logger.error(f"初始化云端存储失败: {e}")
            self._storage = None

    async def _delete_from_cloud_async(self, cloud_path: str) -> bool:
        """
        异步从云端删除文件

        Args:
            cloud_path: 云端路径

        Returns:
            是否删除成功
        """
        if not self._storage or not cloud_path:
            return False

        try:
            result = await self._storage.delete(cloud_path)
            if result:
                logger.info(f"从云端删除成功: {cloud_path}")
            return result
        except Exception as e:
            logger.error(f"从云端删除失败: {e}")
            return False

    def _delete_from_cloud(self, cloud_path: str) -> bool:
        """
        从云端删除文件（同步封装）

        Args:
            cloud_path: 云端路径

        Returns:
            是否删除成功
        """
        if not self._storage or not cloud_path:
            return False

        def _sync_delete():
            """在独立事件循环中执行异步删除"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._delete_from_cloud_async(cloud_path))
            finally:
                loop.close()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在事件循环中，在独立线程中执行以避免嵌套事件循环
                future = loop.run_in_executor(None, _sync_delete)
                return future.result(timeout=30)
            else:
                return _sync_delete()
        except Exception as e:
            logger.error(f"从云端删除失败: {e}")
            return False
    
    def _ensure_cache_dir(self):
        """确保缓存目录存在"""
        try:
            self.cache_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"缓存目录已创建: {self.cache_path}")
        except Exception as e:
            logger.error(f"创建缓存目录失败: {e}")
    
    def _get_date_dir(self, date: Optional[datetime] = None) -> Path:
        """
        获取日期目录路径

        Args:
            date: 日期对象，默认为当前日期

        Returns:
            日期目录路径
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        date_dir = self.cache_path / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir
    
    def get_temp_date_dir(self, date: Optional[datetime] = None) -> Path:
        """
        获取临时文件的日期目录路径（upload/temp/YYYYMMDD）
        
        Args:
            date: 日期对象，默认为当前日期
        
        Returns:
            日期目录路径
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y%m%d")
        temp_dir = self.root_dir / "upload" / "temp" / date_str
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _generate_filename(self, task_id: int, url: str, media_type: str, timestamp: Optional[datetime] = None) -> str:
        """
        生成缓存文件名

        Args:
            task_id: 任务ID
            url: 原始URL
            media_type: 媒体类型 (video/image)
            timestamp: 时间戳对象，默认为当前时间

        Returns:
            文件名，格式: {task_id}_{timestamp}_{hash8}.{ext}
        """
        # 获取文件扩展名
        ext = Path(url.split('?')[0]).suffix or ('.mp4' if media_type == 'video' else '.png')

        # 生成8位hash
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

        # 生成时间戳
        if timestamp is None:
            timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d%H%M%S")

        return f"{task_id}_{timestamp_str}_{url_hash}{ext}"
    
    async def download_and_cache(self, url: str, task_id: int, media_type: str = "video") -> Optional[str]:
        """
        下载媒体文件并缓存到本地

        Args:
            url: 媒体文件URL
            task_id: 任务ID
            media_type: 媒体类型 (video/image)

        Returns:
            本地URL路径，失败返回None
        """
        if not self.enabled:
            logger.info("媒体缓存未启用，跳过下载")
            return None

        # 获取文件大小用于后续记录
        file_size = 0

        try:
            # 使用同一个时间戳生成日期目录和文件名，避免跨秒导致路径不匹配
            current_time = datetime.now()

            # 获取日期目录
            date_dir = self._get_date_dir(current_time)

            # 生成文件名（使用相同的时间戳）
            filename = self._generate_filename(task_id, url, media_type, current_time)
            file_path = date_dir / filename

            # 下载文件
            logger.info(f"开始下载媒体文件: {url} -> {file_path}")

            timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"下载失败，HTTP状态码: {response.status}")
                        return None

                    # 写入文件
                    with open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            # 获取文件大小
            file_size = file_path.stat().st_size

            # 生成本地URL（相对于upload目录）
            relative_path = file_path.relative_to(self.root_dir)
            local_url = f"/{relative_path.as_posix()}"


            logger.info(f"媒体文件缓存成功: {local_url}")
            return local_url

        except asyncio.TimeoutError:
            logger.error(f"下载超时: {url}")
            return None
        except Exception as e:
            logger.error(f"下载媒体文件失败: {e}")
            return None

    def save_data_url_to_cache(self, data_url: str, task_id: int) -> Optional[str]:
        """
        将 data URL (base64) 保存到本地缓存

        Args:
            data_url: data URL 格式的数据 (data:image/png;base64,xxx)
            task_id: 任务ID

        Returns:
            本地URL路径，失败返回None
        """
        import base64 as b64

        if not self.enabled:
            logger.info("媒体缓存未启用，跳过保存")
            return None

        try:
            # 检查是否是 data URL
            if not data_url or not data_url.startswith("data:"):
                return None

            # 解析 data URL
            # 格式: data:image/png;base64,xxxxx
            header, data = data_url.split(",", 1)
            mime_part = header.split(":")[1].split(";")[0]

            # 确定扩展名
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "video/mp4": ".mp4",
                "video/webm": ".webm"
            }
            ext = ext_map.get(mime_part, ".bin")

            # 判断媒体类型
            media_type = "image" if mime_part.startswith("image/") else "video"

            # 使用同一个时间戳生成日期目录和文件名
            current_time = datetime.now()

            # 获取日期目录
            date_dir = self._get_date_dir(current_time)

            # 生成文件名
            url_hash = hashlib.md5(data.encode()).hexdigest()[:8]
            timestamp_str = current_time.strftime("%Y%m%d%H%M%S")
            filename = f"{task_id}_{timestamp_str}_{url_hash}{ext}"
            file_path = date_dir / filename

            # 解码并保存
            logger.info(f"保存 data URL 到缓存: {file_path}")
            file_bytes = b64.b64decode(data)
            with open(file_path, 'wb') as f:
                f.write(file_bytes)

            # 获取文件大小
            file_size = file_path.stat().st_size

            # 生成本地URL（相对于项目根目录）
            relative_path = file_path.relative_to(self.root_dir)
            local_url = f"/{relative_path.as_posix()}"

            logger.info(f"data URL 缓存成功: {local_url}")
            return local_url

        except Exception as e:
            logger.error(f"保存 data URL 失败: {e}")
            return None

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        try:
            total_size = 0
            file_count = 0
            oldest_file = None
            oldest_mtime = None
            
            for date_dir in self.cache_path.iterdir():
                if not date_dir.is_dir():
                    continue
                
                for file_path in date_dir.iterdir():
                    if file_path.is_file():
                        file_count += 1
                        file_size = file_path.stat().st_size
                        total_size += file_size
                        
                        mtime = file_path.stat().st_mtime
                        if oldest_mtime is None or mtime < oldest_mtime:
                            oldest_mtime = mtime
                            oldest_file = file_path
            
            return {
                "total_size_gb": round(total_size / (1024**3), 2),
                "file_count": file_count,
                "oldest_file": str(oldest_file) if oldest_file else None,
                "oldest_date": datetime.fromtimestamp(oldest_mtime).strftime("%Y-%m-%d %H:%M:%S") if oldest_mtime else None
            }
        except Exception as e:
            logger.error(f"获取缓存统计信息失败: {e}")
            return {}
    
    def cleanup_expired_files(self) -> int:
        """
        清理过期文件（按天数）

        Returns:
            删除的文件数量
        """
        if self.max_days <= 0:
            logger.info("未设置过期天数限制，跳过清理")
            return 0

        try:
            deleted_count = 0
            cutoff_time = datetime.now() - timedelta(days=self.max_days)
            cutoff_timestamp = cutoff_time.timestamp()

            logger.info(f"开始清理超过 {self.max_days} 天的文件，截止时间: {cutoff_time}")

            for date_dir in self.cache_path.iterdir():
                if not date_dir.is_dir():
                    continue

                for file_path in date_dir.iterdir():
                    if file_path.is_file():
                        mtime = file_path.stat().st_mtime
                        if mtime < cutoff_timestamp:
                            # 获取相对路径
                            relative_path = file_path.relative_to(self.root_dir)
                            local_path_str = relative_path.as_posix()

                            # 同步删除云端文件
                            if self.upload_to_cloud:
                                try:
                                    from model.media_file_mapping import MediaFileMappingModel
                                    record = MediaFileMappingModel.get_by_local_path(local_path_str)
                                    if record and record.cloud_path:
                                        self._delete_from_cloud(record.cloud_path)
                                    # 删除映射记录
                                    MediaFileMappingModel.delete_by_local_path(local_path_str)
                                except Exception as e:
                                    logger.error(f"删除云端文件或映射记录失败: {e}")

                            # 删除本地文件
                            file_path.unlink()
                            deleted_count += 1
                            logger.debug(f"删除过期文件: {file_path}")

                # 如果日期目录为空，删除目录
                if not any(date_dir.iterdir()):
                    date_dir.rmdir()
                    logger.debug(f"删除空目录: {date_dir}")

            logger.info(f"过期文件清理完成，删除 {deleted_count} 个文件")
            return deleted_count

        except Exception as e:
            logger.error(f"清理过期文件失败: {e}")
            return 0
    
    def cleanup_by_size(self) -> int:
        """
        按容量限制清理（删除最旧的文件）

        Returns:
            删除的文件数量
        """
        if self.max_size_gb <= 0:
            logger.info("未设置容量限制，跳过清理")
            return 0

        try:
            # 获取所有文件及其信息
            files_info = []
            total_size = 0

            for date_dir in self.cache_path.iterdir():
                if not date_dir.is_dir():
                    continue

                for file_path in date_dir.iterdir():
                    if file_path.is_file():
                        stat = file_path.stat()
                        files_info.append({
                            "path": file_path,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime
                        })
                        total_size += stat.st_size

            # 检查是否超过容量限制
            max_size_bytes = self.max_size_gb * (1024**3)
            if total_size <= max_size_bytes:
                logger.info(f"当前缓存大小 {round(total_size / (1024**3), 2)} GB，未超过限制 {self.max_size_gb} GB")
                return 0

            # 按修改时间排序（从旧到新）
            files_info.sort(key=lambda x: x["mtime"])

            # 删除最旧的文件，直到低于阈值
            deleted_count = 0
            current_size = total_size

            logger.info(f"当前缓存大小 {round(total_size / (1024**3), 2)} GB，超过限制 {self.max_size_gb} GB，开始清理")

            for file_info in files_info:
                if current_size <= max_size_bytes:
                    break

                file_path = file_info["path"]
                file_size = file_info["size"]

                # 获取相对路径
                relative_path = file_path.relative_to(self.root_dir)
                local_path_str = relative_path.as_posix()

                # 同步删除云端文件
                if self.upload_to_cloud:
                    try:
                        from model.media_file_mapping import MediaFileMappingModel
                        record = MediaFileMappingModel.get_by_local_path(local_path_str)
                        if record and record.cloud_path:
                            self._delete_from_cloud(record.cloud_path)
                        # 删除映射记录
                        MediaFileMappingModel.delete_by_local_path(local_path_str)
                    except Exception as e:
                        logger.error(f"删除云端文件或映射记录失败: {e}")

                # 删除本地文件
                file_path.unlink()
                current_size -= file_size
                deleted_count += 1
                logger.debug(f"删除文件: {file_path}")

            # 清理空目录
            for date_dir in self.cache_path.iterdir():
                if date_dir.is_dir() and not any(date_dir.iterdir()):
                    date_dir.rmdir()
                    logger.debug(f"删除空目录: {date_dir}")

            logger.info(f"容量清理完成，删除 {deleted_count} 个文件，当前大小 {round(current_size / (1024**3), 2)} GB")
            return deleted_count

        except Exception as e:
            logger.error(f"按容量清理失败: {e}")
            return 0
    
    def cleanup_temp_dir(self, max_days: int = 2) -> int:
        """
        清理 upload/temp 目录中超过指定天数的文件
        
        Args:
            max_days: 保留天数，默认 2 天
        
        Returns:
            删除的文件数量
        """
        try:
            temp_path = self.root_dir / "upload" / "temp"
            if not temp_path.exists():
                logger.debug(f"临时目录不存在: {temp_path}")
                return 0
            
            deleted_count = 0
            cutoff_time = datetime.now() - timedelta(days=max_days)
            
            logger.info(f"开始清理 upload/temp 目录，保留 {max_days} 天，截止时间: {cutoff_time}")
            
            for date_dir in temp_path.iterdir():
                if not date_dir.is_dir():
                    continue
                
                # 尝试解析日期目录名（格式: YYYYMMDD）
                try:
                    dir_date = datetime.strptime(date_dir.name, "%Y%m%d")
                    if dir_date < cutoff_time:
                        # 目录过期，删除整个目录
                        import shutil
                        file_count = sum(1 for _ in date_dir.rglob('*') if _.is_file())
                        shutil.rmtree(date_dir)
                        deleted_count += file_count
                        logger.info(f"删除过期目录: {date_dir} ({file_count} 个文件)")
                except ValueError:
                    # 目录名不符合日期格式，跳过
                    logger.debug(f"跳过非日期格式目录: {date_dir.name}")
                    continue
            
            logger.info(f"upload/temp 清理完成，删除 {deleted_count} 个文件")
            return deleted_count
            
        except Exception as e:
            logger.error(f"清理 upload/temp 目录失败: {e}")
            return 0
    
    def cleanup_all(self) -> Dict[str, int]:
        """
        执行完整清理（按天数 + 按容量 + temp 目录）
        
        Returns:
            清理统计信息
        """
        logger.info("开始执行媒体缓存清理")
        
        expired_count = self.cleanup_expired_files()
        size_count = self.cleanup_by_size()
        temp_count = self.cleanup_temp_dir(max_days=2)
        
        result = {
            "expired_deleted": expired_count,
            "size_deleted": size_count,
            "temp_deleted": temp_count,
            "total_deleted": expired_count + size_count + temp_count
        }
        
        logger.info(f"清理完成: {result}")
        return result


# 全局单例
_cache_manager = None


def get_cache_manager() -> MediaCacheManager:
    """获取缓存管理器单例"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = MediaCacheManager()
    return _cache_manager


async def download_and_cache(url: str, task_id: int, media_type: str = "video") -> Optional[str]:
    """
    下载并缓存媒体文件（便捷函数）
    
    Args:
        url: 媒体文件URL
        task_id: 任务ID
        media_type: 媒体类型 (video/image)
        
    Returns:
        本地URL路径，失败返回原URL
    """
    manager = get_cache_manager()
    local_url = await manager.download_and_cache(url, task_id, media_type)
    return local_url if local_url else url


def cleanup_cache() -> Dict[str, int]:
    """
    执行缓存清理（便捷函数）
    
    Returns:
        清理统计信息
    """
    manager = get_cache_manager()
    return manager.cleanup_all()


def get_cache_stats() -> Dict[str, Any]:
    """
    获取缓存统计信息（便捷函数）
    
    Returns:
        统计信息字典
    """
    manager = get_cache_manager()
    return manager.get_cache_stats()


def get_temp_date_dir(date: Optional[datetime] = None) -> Path:
    """
    获取临时文件的日期目录路径（便捷函数）
    
    Args:
        date: 日期对象，默认为当前日期
    
    Returns:
        日期目录路径
    """
    manager = get_cache_manager()
    return manager.get_temp_date_dir(date)
