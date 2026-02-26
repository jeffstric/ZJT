"""
文件存储抽象基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Union


@dataclass
class UploadResult:
    """上传结果"""
    success: bool
    key: str = ""  # 文件在存储中的唯一标识
    hash: str = ""  # 文件哈希值
    url: str = ""  # 文件访问URL（如果是公开的）
    error: str = ""  # 错误信息


class BaseFileStorage(ABC):
    """
    文件存储抽象基类

    所有存储后端（如七牛云、阿里云OSS等）都需要继承此类并实现相关方法
    """

    @abstractmethod
    async def upload_data(
        self,
        key: str,
        data: Union[bytes, str],
        content_type: Optional[str] = None
    ) -> UploadResult:
        """
        上传数据到存储

        Args:
            key: 文件在存储中的唯一标识（路径）
            data: 要上传的数据（bytes或str）
            content_type: 文件MIME类型（可选）

        Returns:
            UploadResult: 上传结果
        """
        pass

    @abstractmethod
    async def upload_file(
        self,
        key: str,
        file_path: str,
        content_type: Optional[str] = None
    ) -> UploadResult:
        """
        上传本地文件到存储

        Args:
            key: 文件在存储中的唯一标识（路径）
            file_path: 本地文件路径
            content_type: 文件MIME类型（可选）

        Returns:
            UploadResult: 上传结果
        """
        pass

    @abstractmethod
    def get_download_url(
        self,
        key: str,
        expires: int = 3600
    ) -> str:
        """
        获取文件下载URL

        Args:
            key: 文件在存储中的唯一标识
            expires: URL有效期（秒），默认1小时

        Returns:
            str: 下载URL
        """
        pass

    @abstractmethod
    def get_public_url(self, key: str) -> str:
        """
        获取文件公开URL（不带签名）

        Args:
            key: 文件在存储中的唯一标识

        Returns:
            str: 公开URL
        """
        pass

    def generate_key(self, prefix: str, filename: str) -> str:
        """
        生成存储key

        Args:
            prefix: 前缀路径（如 "images", "videos"）
            filename: 文件名

        Returns:
            str: 完整的存储key
        """
        import time
        import uuid
        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:8]
        # 获取文件扩展名
        ext = ""
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1]
        return f"{prefix}/{timestamp}_{unique_id}.{ext}" if ext else f"{prefix}/{timestamp}_{unique_id}"

    def generate_key_with_datetime(self, filename: str) -> str:
        """
        生成带日期时间前缀的存储key

        格式: /YYYY-MM-DD/HH/timestamp_uniqueid.ext

        Args:
            filename: 文件名

        Returns:
            str: 完整的存储key
        """
        import time
        import uuid
        from datetime import datetime

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%H")
        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:8]

        # 获取文件扩展名
        ext = ""
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1]

        if ext:
            return f"{date_str}/{hour_str}/{timestamp}_{unique_id}.{ext}"
        return f"{date_str}/{hour_str}/{timestamp}_{unique_id}"
