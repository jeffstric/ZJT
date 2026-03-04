"""
RunningHub 文件存储实现

用于上传图片、音频、视频等文件到 RunningHub 媒体服务器
- fileName: 用于 comfyUI 节点的相对路径（作为 key）
- download_url: 临时下载链接，有效期一天（作为 url）
"""

import os
import asyncio
import traceback
from typing import Optional, Union
from concurrent.futures import ThreadPoolExecutor

import requests

from .base import BaseFileStorage, UploadResult


class RunningHubFileStorage(BaseFileStorage):
    """
    RunningHub 文件存储实现

    上传文件到 RunningHub 媒体服务器，支持图片、音频、视频、ZIP压缩包
    API: POST /openapi/v2/media/upload/binary
    """

    def __init__(
        self,
        host: str,
        api_key: str,
        config: dict = None,
        logger: object = None
    ):
        """
        初始化 RunningHub 存储

        Args:
            host: RunningHub API 主机地址（如 https://www.runninghub.cn）
            api_key: API 密钥
            config: 完整配置字典（用于 URL 映射到本地文件）
            logger: 日志记录器（可选）
        """
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._config = config or {}
        self._logger = logger
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _log(self, level: str, message: str):
        """输出日志"""
        if self._logger:
            getattr(self._logger, level, print)(message)

    def _resolve_to_local_file(self, file_path_or_url: str) -> Optional[str]:
        """
        将路径/URL解析为本地文件路径

        Args:
            file_path_or_url: 文件路径或URL

        Returns:
            本地文件路径，公网URL返回None
        """
        # 延迟导入避免循环依赖
        from utils.network_utils import is_local_file_path, is_local_or_private_url
        from utils.image_upload_utils import try_map_url_to_local_file, download_url_to_temp

        if is_local_file_path(file_path_or_url):
            return file_path_or_url if os.path.exists(file_path_or_url) else None
        elif is_local_or_private_url(file_path_or_url):
            # 先尝试映射到本地文件
            local_path = try_map_url_to_local_file(file_path_or_url, self._config)
            if local_path and os.path.exists(local_path):
                self._log("info", f"URL映射到本地文件: {file_path_or_url} -> {local_path}")
                return local_path
            # 下载到临时文件
            self._log("info", f"下载局域网文件到临时文件: {file_path_or_url}")
            return asyncio.run(download_url_to_temp(file_path_or_url, os.getcwd()))
        return None  # 公网URL

    def _sync_upload_file(self, file_path: str) -> UploadResult:
        """
        同步上传文件到 RunningHub

        Args:
            file_path: 本地文件路径

        Returns:
            UploadResult: 上传结果
        """
        try:
            upload_url = f"{self._host}/openapi/v2/media/upload/binary"
            headers = {"Authorization": f"Bearer {self._api_key}"}

            with open(file_path, 'rb') as f:
                response = requests.post(
                    upload_url, headers=headers, files={'file': f}, timeout=60
                )

            self._log("info", f"RunningHub上传状态码: {response.status_code}")
            self._log("info", f"RunningHub上传响应头: {dict(response.headers)}")
            self._log("info", f"RunningHub上传响应体: {response.text}")

            if response.status_code != 200:
                return UploadResult(success=False, error=f"HTTP {response.status_code}")

            result = response.json()
            if result.get("code") != 0:
                return UploadResult(
                    success=False,
                    error=result.get("message", "上传失败")
                )

            data = result.get("data", {})
            self._log("info", f"RunningHub上传成功，完整数据: {data}")

            # 映射 API 响应到 UploadResult
            return UploadResult(
                success=True,
                key=data.get("fileName", ""),      # comfyUI 节点使用
                url=data.get("download_url", ""),  # 临时下载链接（有效期1天）
                hash=data.get("type", "")          # 复用 hash 字段存储文件类型
            )
        except Exception as e:
            self._log("error", f"上传到RunningHub失败: {str(e)}")
            self._log("error", traceback.format_exc())
            return UploadResult(success=False, error=str(e))

    async def upload_data(
        self,
        key: str,
        data: Union[bytes, str],
        content_type: Optional[str] = None
    ) -> UploadResult:
        """
        上传数据到 RunningHub（先写入临时文件再上传）

        Args:
            key: 忽略（RunningHub 自动生成 fileName）
            data: 要上传的数据（bytes或str）
            content_type: 文件MIME类型（用于确定临时文件后缀）

        Returns:
            UploadResult: key=fileName, url=download_url
        """
        import tempfile
        if isinstance(data, str):
            data = data.encode("utf-8")

        # 根据 content_type 确定后缀
        suffix = ".bin"
        if content_type:
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
                "audio/mp3": ".mp3",
                "audio/mpeg": ".mp3",
                "audio/wav": ".wav",
                "audio/flac": ".flac",
                "video/mp4": ".mp4",
                "video/avi": ".avi",
                "video/quicktime": ".mov",
                "application/zip": ".zip"
            }
            suffix = ext_map.get(content_type, ".bin")

        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with open(temp_path, 'wb') as f:
                f.write(data)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor, self._sync_upload_file, temp_path
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def upload_file(
        self,
        key: str,
        file_path: str,
        content_type: Optional[str] = None
    ) -> UploadResult:
        """
        上传文件到 RunningHub

        Args:
            key: 忽略（RunningHub 自动生成 fileName）
            file_path: 本地文件路径或URL
            content_type: 忽略（RunningHub 自动识别）

        Returns:
            UploadResult: key=fileName, url=download_url
        """
        # 解析为本地文件
        local_file = self._resolve_to_local_file(file_path)
        if local_file is None:
            # 公网URL，直接返回原路径
            self._log("info", f"公网URL，无需上传: {file_path}")
            return UploadResult(success=True, key=file_path, url=file_path)

        if not os.path.exists(local_file):
            return UploadResult(success=False, error=f"文件不存在: {local_file}")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._sync_upload_file, local_file
        )

    def get_download_url(self, key: str, expires: int = 3600) -> str:
        """
        获取下载URL

        注意：RunningHub 不支持动态生成下载链接，
        download_url 在上传时已返回，此处直接返回 key

        Args:
            key: fileName 或 download_url
            expires: 忽略

        Returns:
            str: 传入的 key
        """
        return key

    def get_public_url(self, key: str) -> str:
        """
        获取公开URL

        Args:
            key: fileName（comfyUI 节点引用）

        Returns:
            str: 传入的 key
        """
        return key
