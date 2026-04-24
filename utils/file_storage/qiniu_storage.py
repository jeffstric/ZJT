"""
七牛云文件存储实现
"""

import asyncio
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Union
from concurrent.futures import ThreadPoolExecutor

import qiniu

from .base import BaseFileStorage, UploadResult


def _setup_qiniu_logger() -> logging.Logger:
    """配置七牛云专用日志，输出到单独文件"""
    qiniu_logger = logging.getLogger("qiniu_upload")
    if qiniu_logger.handlers:
        return qiniu_logger

    qiniu_logger.setLevel(logging.DEBUG)

    # 确保日志目录存在
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 按天轮转的文件处理器
    log_file = os.path.join(log_dir, "qiniu_upload.log")
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    ))
    qiniu_logger.addHandler(file_handler)

    return qiniu_logger


logger = _setup_qiniu_logger()


class QiniuFileStorage(BaseFileStorage):
    """
    七牛云文件存储实现

    使用七牛云SDK进行文件上传和下载链接生成
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        cdn_domain: str
    ):
        """
        初始化七牛云存储

        Args:
            access_key: 七牛云 Access Key
            secret_key: 七牛云 Secret Key
            bucket_name: 存储空间名称
            cdn_domain: CDN 加速域名
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.cdn_domain = cdn_domain

        # 初始化七牛云认证
        self._auth = qiniu.Auth(access_key, secret_key)

        # 线程池用于执行同步的七牛SDK操作
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _get_upload_token(self, key: Optional[str] = None) -> str:
        """获取上传凭证"""
        if key:
            return self._auth.upload_token(self.bucket_name, key)
        return self._auth.upload_token(self.bucket_name)

    def _sync_upload_data(
        self,
        key: str,
        data: bytes,
        content_type: Optional[str] = None
    ) -> UploadResult:
        """同步上传数据"""
        try:
            logger.info(f"[七牛云] 开始上传数据, key={key}, data_size={len(data)} bytes")
            token = self._get_upload_token(key)
            ret, info = qiniu.put_data(token, key, data)

            logger.info(f"[七牛云] 上传响应: ret={ret}, status_code={info.status_code}, "
                        f"req_id={info.req_id}, x_log={info.x_log}")
            if hasattr(info, 'error') and info.error:
                logger.error(f"[七牛云] 上传错误详情: error={info.error}, "
                            f"text_body={info.text_body}")

            if ret is not None:
                logger.info(f"[七牛云] 数据上传成功, key={ret.get('key')}, hash={ret.get('hash')}")
                return UploadResult(
                    success=True,
                    key=ret.get("key", key),
                    hash=ret.get("hash", ""),
                    url=self.get_public_url(key)
                )
            else:
                logger.error(f"[七牛云] 数据上传失败: {info}")
                return UploadResult(
                    success=False,
                    error=str(info)
                )
        except Exception as e:
            logger.exception(f"[七牛云] 数据上传异常: {e}")
            return UploadResult(
                success=False,
                error=str(e)
            )

    def _sync_upload_file(
        self,
        key: str,
        file_path: str,
        content_type: Optional[str] = None
    ) -> UploadResult:
        """同步上传文件"""
        try:
            logger.info(f"[七牛云] 开始上传文件, key={key}, file_path={file_path}")
            token = self._get_upload_token(key)
            logger.debug(f"[七牛云] 获取token成功, token={token}, key={key}, file_path={file_path}, bucket={self.bucket_name}")
            ret, info = qiniu.put_file(token, key, file_path) #qiniu 来自于 pip install qiniu

            logger.info(f"[七牛云] 上传响应: ret={ret}, status_code={info.status_code}, "
                        f"req_id={info.req_id}, x_log={info.x_log}")
            if hasattr(info, 'error') and info.error:
                logger.error(f"[七牛云] 上传错误详情: error={info.error}, "
                            f"text_body={info.text_body}")

            if ret is not None:
                logger.info(f"[七牛云] 文件上传成功, key={ret.get('key')}, hash={ret.get('hash')}")
                return UploadResult(
                    success=True,
                    key=ret.get("key", key),
                    hash=ret.get("hash", ""),
                    url=self.get_public_url(key)
                )
            else:
                logger.error(f"[七牛云] 文件上传失败: {info}")
                return UploadResult(
                    success=False,
                    error=str(info)
                )
        except Exception as e:
            logger.exception(f"[七牛云] 文件上传异常: {e}")
            return UploadResult(
                success=False,
                error=str(e)
            )

    async def upload_data(
        self,
        key: str,
        data: Union[bytes, str],
        content_type: Optional[str] = None
    ) -> UploadResult:
        """
        异步上传数据到七牛云

        Args:
            key: 文件在存储中的唯一标识（路径）
            data: 要上传的数据（bytes或str）
            content_type: 文件MIME类型（可选）

        Returns:
            UploadResult: 上传结果
        """
        # 确保数据是bytes类型
        if isinstance(data, str):
            data = data.encode("utf-8")

        # 在线程池中执行同步上传操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._sync_upload_data,
            key,
            data,
            content_type
        )

    async def upload_file(
        self,
        key: str,
        file_path: str,
        content_type: Optional[str] = None
    ) -> UploadResult:
        """
        异步上传本地文件到七牛云

        Args:
            key: 文件在存储中的唯一标识（路径）
            file_path: 本地文件路径
            content_type: 文件MIME类型（可选）

        Returns:
            UploadResult: 上传结果
        """
        # 在线程池中执行同步上传操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._sync_upload_file,
            key,
            file_path,
            content_type
        )

    def get_download_url(
        self,
        key: str,
        expires: int = 7200
    ) -> str:
        """
        获取私有下载URL（带签名）

        Args:
            key: 文件在存储中的唯一标识
            expires: URL有效期（秒），默认1小时

        Returns:
            str: 带签名的下载URL
        """
        base_url = self.get_public_url(key)
        return self._auth.private_download_url(base_url, expires=expires)

    def get_public_url(self, key: str) -> str:
        """
        获取文件公开URL（不带签名）

        Args:
            key: 文件在存储中的唯一标识

        Returns:
            str: 公开URL
        """
        # 确保域名不以/结尾，key不以/开头
        domain = self.cdn_domain.rstrip("/")
        key = key.lstrip("/")
        return f"http://{domain}/{key}"

    def _sync_delete(self, key: str) -> bool:
        """同步删除文件"""
        try:
            qiniu_bucket = qiniu.BucketManager(self._auth)
            ret, info = qiniu_bucket.delete(self.bucket_name, key)
            if ret is not None:
                return True
            # 如果返回404认为文件不存在也算删除成功
            if info.status_code == 612:
                return True
            return False
        except Exception as e:
            return False

    async def delete(self, key: str) -> bool:
        """
        异步删除存储中的文件

        Args:
            key: 文件在存储中的唯一标识

        Returns:
            bool: 删除是否成功
        """
        # 在线程池中执行同步删除操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._sync_delete,
            key
        )
