"""
七牛云文件存储实现
"""

import asyncio
import logging
from utils.logger_config import DailyFileHandler
from typing import Optional, Union
from concurrent.futures import ThreadPoolExecutor

import qiniu
import qiniu.config as _qiniu_config
import httpx

from config.constant import (
    QINIU_HTTP_CONNECTION_TIMEOUT,
    QINIU_UPLOAD_HARD_TIMEOUT,
)
from config.config_util import get_config_value

from .base import BaseFileStorage, UploadResult

# 显式设置 qiniu SDK 全局 HTTP 超时，避免依赖 SDK 内部默认值
# SDK 内部所有 requests 调用会读取 config.get_default('connection_timeout')
try:
    _qiniu_config.set_default(connection_timeout=QINIU_HTTP_CONNECTION_TIMEOUT)
except Exception:  # pragma: no cover - SDK 版本差异保护
    pass


def _setup_qiniu_logger() -> logging.Logger:
    """配置七牛云专用日志，输出到单独文件"""
    qiniu_logger = logging.getLogger("qiniu_upload")
    if qiniu_logger.handlers:
        return qiniu_logger

    qiniu_logger.setLevel(logging.DEBUG)

    # 使用项目统一的 DailyFileHandler，避免 Windows 上 TimedRotatingFileHandler
    # rename 操作导致的 WinError 32 文件锁问题
    file_handler = DailyFileHandler('qiniu_upload', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    ))
    qiniu_logger.addHandler(file_handler)

    return qiniu_logger


logger = _setup_qiniu_logger()

# 浏览器直传域名解析缓存：(access_key, bucket_name) -> "https://host"，进程内复用。
# 同 AK 不同 bucket（短期/长期桶）区域可能不同，必须按二元组缓存。
_browser_upload_host_cache = {}
# 源站 io 域名缓存，confirm 回源不走 CDN。同样按 (AK, bucket) 区分区域。
_io_host_cache = {}


def _upload_host_from_uc_v4(data) -> Optional[str]:
    """从 UC /v4/query 响应取出浏览器上传域名。

    v4 是 hosts[].up.domains（备选 up.old），不是旧版 up.acc.main。
    """
    if not isinstance(data, dict):
        return None
    hosts = data.get("hosts")
    if not isinstance(hosts, list) or not hosts or not isinstance(hosts[0], dict):
        return None
    up = hosts[0].get("up")
    if not isinstance(up, dict):
        return None
    for field in ("domains", "old"):
        domains = up.get(field)
        if not isinstance(domains, list):
            continue
        for item in domains:
            if isinstance(item, str) and item.strip():
                host = item.strip()
                return host if host.startswith("http") else f"https://{host}"
    return None


class QiniuFileStorage(BaseFileStorage):
    """
    七牛云文件存储实现

    使用七牛云SDK进行文件上传和下载链接生成
    """

    # ===== 浏览器直传（七牛 form 直传协议；非七牛后端不走这段）=====
    # 华东 z0 默认上传域名。不同 bucket 区域域名不同（复用会 400），
    # 解析优先级：配置 upload_host 覆盖 → UC 按 AK+bucket 查询（进程内缓存）→ 本默认值。
    DEFAULT_BROWSER_UPLOAD_HOST = "https://upload.qiniup.com"
    UC_QUERY_URL = "https://uc.qbox.me/v4/query"
    UC_QUERY_TIMEOUT = 5
    # 七牛 form 直传成功响应体（returnBody 占位符为七牛语法）
    _BROWSER_UPLOAD_RETURN_BODY = '{"key":"$(key)","hash":"$(etag)","fsize":"$(fsize)"}'

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        cdn_domain: str,
        upload_host: str = ""
    ):
        """
        初始化七牛云存储

        Args:
            access_key: 七牛云 Access Key
            secret_key: 七牛云 Secret Key
            bucket_name: 存储空间名称
            cdn_domain: CDN 加速域名
            upload_host: 浏览器直传域名覆盖（空则按 bucket 区域经 UC 查询自动解析）
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.cdn_domain = cdn_domain
        self.upload_host_override = (upload_host or "").strip()

        # 初始化七牛云认证
        self._auth = qiniu.Auth(access_key, secret_key)

        # 线程池用于执行同步的七牛SDK操作
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _get_upload_token(self, key: Optional[str] = None) -> str:
        """获取上传凭证"""
        if key:
            return self._auth.upload_token(self.bucket_name, key)
        return self._auth.upload_token(self.bucket_name)

    def get_upload_token(
        self,
        key: Optional[str] = None,
        expires: int = 3600,
        policy: Optional[dict] = None
    ) -> str:
        """
        生成上传凭证（同步，供接口直接调用）

        用于「前端直传」场景：后端颁发绑定 key 的短期 token，前端拿到后
        直接 POST 到七牛上传域名，不再经后端转发大文件。

        Args:
            key: 绑定的对象 key（强烈建议指定，避免前端覆盖任意文件）
            expires: token 有效期（秒），默认 1 小时
            policy: 七牛上传策略覆盖项（如 returnBody / fileType / mimeLimit）

        Returns:
            str: 上传凭证 token
        """
        return self._auth.upload_token(
            self.bucket_name,
            key=key,
            expires=expires,
            policy=policy or None,
        )

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
        import time as _time
        _t0 = _time.monotonic()
        try:
            logger.info(f"[七牛云] 开始上传文件, key={key}, file_path={file_path}")
            token = self._get_upload_token(key)
            logger.debug(f"[七牛云] 获取token成功, key={key}, file_path={file_path}, bucket={self.bucket_name}")
            ret, info = qiniu.put_file(token, key, file_path) #qiniu 来自于 pip install qiniu

            _elapsed = _time.monotonic() - _t0
            logger.info(f"[七牛云] 上传响应: ret={ret}, status_code={info.status_code}, "
                        f"req_id={info.req_id}, x_log={info.x_log}, elapsed={_elapsed:.2f}s")
            if _elapsed >= QINIU_UPLOAD_HARD_TIMEOUT:
                logger.warning(
                    f"[七牛云] 上传耗时过长 {_elapsed:.2f}s >= {QINIU_UPLOAD_HARD_TIMEOUT}s, "
                    f"key={key}（可能网络异常，需关注）"
                )
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
        expires: int = 7200,
        attname: Optional[str] = None
    ) -> str:
        """
        获取私有下载URL（带签名）

        Args:
            key: 文件在存储中的唯一标识
            expires: URL有效期（秒），默认1小时
            attname: 下载时的自定义文件名（参与签名，触发 Content-Disposition: attachment）

        Returns:
            str: 带签名的下载URL
        """
        from urllib.parse import quote
        base_url = self.get_public_url(key)
        if attname:
            encoded_attname = quote(attname, safe='')
            base_url = f"{base_url}?attname={encoded_attname}"
        return self._auth.private_download_url(base_url, expires=expires)

    def get_origin_download_request(self, key: str) -> dict:
        """构造 Kodo 源站下载请求，不经过 cdn_domain。

        confirm 回源用这个，避免每次确认都产生 CDN 下行。
        用户播放仍走 get_download_url / get_public_url。
        """
        from qiniu.utils import urlsafe_base64_encode

        host = self._resolve_io_host()
        encoded = urlsafe_base64_encode(f"{self.bucket_name}:{str(key).lstrip('/')}")
        url = f"{host}/getfile/{encoded}"
        token = self._auth.token_of_request(url)
        return {
            "url": url,
            "headers": {"Authorization": f"QBox {token}"},
        }

    def _resolve_io_host(self) -> str:
        cache_key = (self.access_key, self.bucket_name)
        cached = _io_host_cache.get(cache_key)
        if cached:
            return cached
        host = str(qiniu.Region().get_io_host(self.access_key, self.bucket_name) or "").strip().rstrip("/")
        if not host:
            raise RuntimeError("七牛未返回源站 io 域名")
        if not host.startswith("http"):
            host = "https://" + host
        _io_host_cache[cache_key] = host
        return host

    def get_public_url(self, key: str) -> str:
        """
        获取文件公开URL（不带签名）

        协议跟随 server.https.enabled：HTTPS 站点若仍下发 http:// 下载链接，
        浏览器会按混合内容下载拦截（表现为点击导出/下载后看不到文件）。

        Args:
            key: 文件在存储中的唯一标识

        Returns:
            str: 公开URL
        """
        # 确保域名不以/结尾，key不以/开头
        domain = self.cdn_domain.rstrip("/")
        key = key.lstrip("/")
        scheme = "https" if get_config_value("server", "https", "enabled", default=False) else "http"
        return f"{scheme}://{domain}/{key}"

    def _sync_list_items(self, prefix: str, limit: int = 1000) -> list:
        """同步列出对象。返回 {key, putTime}，putTime 为七牛 100 纳秒计数。"""
        try:
            bucket_manager = qiniu.BucketManager(self._auth)
            found = []
            marker = None
            while True:
                ret, eof, info = bucket_manager.list(
                    self.bucket_name, prefix=prefix, marker=marker, limit=min(limit - len(found), 1000)
                )
                if ret is None:
                    logger.error(f"[七牛云] 列出文件失败: prefix={prefix}, info={info}")
                    break
                items = ret.get('items', [])
                for item in items:
                    if not isinstance(item, dict) or not item.get('key'):
                        continue
                    found.append({
                        "key": item.get("key"),
                        "putTime": item.get("putTime"),
                    })
                if len(found) >= limit or eof:
                    break
                marker = ret.get('marker')
                if not marker:
                    break
            return found
        except Exception as e:
            logger.error(f"[七牛云] 列出文件异常: prefix={prefix}, error={e}")
            return []

    def _sync_list_by_prefix(self, prefix: str, limit: int = 1000) -> list:
        """同步列出指定前缀下的所有文件 key"""
        return [item["key"] for item in self._sync_list_items(prefix, limit) if item.get("key")]

    def list_object_stats(self, prefix: str, limit: int = 1000) -> list:
        """同步列出对象元信息。供调度进程清理孤儿对象，不走事件循环。"""
        return self._sync_list_items(prefix, limit)

    async def list_by_prefix(self, prefix: str, limit: int = 1000) -> list:
        """
        异步列出指定前缀下的所有文件 key

        Args:
            prefix: key 前缀（如 "marketing/session_123/"）
            limit: 最大返回数量

        Returns:
            list: 文件 key 列表
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._sync_list_by_prefix,
            prefix,
            limit
        )

    def _sync_stat(self, key: str) -> Optional[dict]:
        """同步查询文件元信息；文件不存在（612）或异常返回 None"""
        try:
            bucket_manager = qiniu.BucketManager(self._auth)
            ret, info = bucket_manager.stat(self.bucket_name, key)
            if ret is not None:
                return ret
            if info is not None and info.status_code == 612:
                return None
            logger.error(
                f"[七牛云] 查询文件元信息失败: key={key}, "
                f"status_code={getattr(info, 'status_code', None)}, error={getattr(info, 'error', None)}"
            )
            return None
        except Exception as e:
            logger.error(f"[七牛云] 查询文件元信息异常: key={key}, error={e}")
            return None

    async def stat(self, key: str) -> Optional[dict]:
        """
        异步查询文件元信息（含 fsize/hash/mimeType）

        供前端直传 upload-confirm 校验文件真实存在与大小一致，防伪造登记。

        Args:
            key: 文件在存储中的唯一标识

        Returns:
            dict；文件不存在返回 None
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._sync_stat,
            key
        )

    async def get_browser_upload_info(
        self,
        key: str,
        max_bytes: int,
        expires: int = 1800
    ) -> Optional[dict]:
        """
        颁发浏览器直传七牛的信息（七牛 form 直传协议）

        token 绑定单一 key + fsizeLimit + insertOnly + 短时效，浏览器只能新增
        服务端指定的对象，不能覆盖。confirm 之后播放会 302 到该 key，不再重做
        魔数校验，因此凭证必须拒绝覆盖。协议细节（UC 区域查询域名、returnBody
        占位符）全部封装在本实现内，端点层经 BaseFileStorage.get_browser_upload_info 调用。

        Args:
            key: 目标对象 key（如 "upload/workflow/12/xxx.mp4"）
            max_bytes: 文件大小上限（写入 fsizeLimit，七牛侧强校验）
            expires: 上传凭证有效期（秒）

        Returns:
            dict: {direct_upload, upload_url, token, key, expires}
        """
        return {
            "direct_upload": True,
            "upload_url": await self._resolve_browser_upload_host(),
            "token": self.get_upload_token(
                key=key,
                expires=expires,
                policy={
                    'fileType': 0,  # 标准存储
                    'fsizeLimit': max_bytes,
                    # confirm 成功后 CDN 302 不再校验内容，同一 key 不能被覆盖
                    'insertOnly': 1,
                    'returnBody': self._BROWSER_UPLOAD_RETURN_BODY,
                },
            ),
            "key": key,
            "expires": expires,
        }

    async def _resolve_browser_upload_host(self) -> str:
        """解析浏览器直传域名：构造传入的配置覆盖 → UC 按 AK+bucket 查询（缓存）→ 默认华东域名"""
        override = self.upload_host_override
        if override:
            return override if override.startswith("http") else f"https://{override}"

        cache_key = (self.access_key, self.bucket_name)
        cached = _browser_upload_host_cache.get(cache_key)
        if cached:
            return cached

        try:
            async with httpx.AsyncClient(timeout=self.UC_QUERY_TIMEOUT) as client:
                resp = await client.get(
                    self.UC_QUERY_URL,
                    params={"ak": self.access_key, "bucket": self.bucket_name},
                )
                resp.raise_for_status()
                data = resp.json()
            host = _upload_host_from_uc_v4(data)
            if host:
                _browser_upload_host_cache[cache_key] = host
                return host
            logger.warning("七牛 UC 区域查询未返回上传域名，回退默认上传域名")
        except Exception as e:
            logger.warning(f"七牛 UC 区域查询失败，回退默认上传域名: {e}")
        return self.DEFAULT_BROWSER_UPLOAD_HOST

    def move_sync(self, src_key: str, dst_key: str) -> bool:
        """同桶移动。不覆盖已存在的目标。调度清理任务调用，不占用事件循环。"""
        return self._sync_move(src_key, dst_key)

    def _sync_move(self, src_key: str, dst_key: str) -> bool:
        """同步移动。只有 HTTP 200 算成功，源文件不存在或目标已存在都保持原样。"""
        src_key = str(src_key or "").strip()
        dst_key = str(dst_key or "").strip()
        if not src_key or not dst_key or src_key == dst_key:
            return False
        try:
            bucket_manager = qiniu.BucketManager(self._auth)
            _ret, info = bucket_manager.move(
                self.bucket_name, src_key, self.bucket_name, dst_key, force="false",
            )
            status_code = getattr(info, "status_code", None)
            if status_code == 200:
                return True
            logger.warning(
                f"[七牛云] 移动文件失败: {src_key} -> {dst_key}, status_code={status_code}"
            )
            return False
        except Exception as e:
            logger.warning(f"[七牛云] 移动文件异常: {src_key} -> {dst_key}, error={e}")
            return False

    def delete_sync(self, key: str) -> bool:
        """同步删除。调度清理任务调用，不占用事件循环。"""
        return self._sync_delete(key)

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
