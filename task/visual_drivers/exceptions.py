"""
Driver exceptions
"""


class DriverConfigError(Exception):
    """驱动配置缺失异常"""

    def __init__(self, driver_name: str, missing_configs: list):
        self.driver_name = driver_name
        self.missing_configs = missing_configs
        self.message = f"驱动 {driver_name} 缺少必要配置: {', '.join(missing_configs)}"
        super().__init__(self.message)


class ImageExpiredError(RuntimeError):
    """第三方图床签名 URL 已过期且无法恢复，需提示用户重新上传。

    触发条件（ensure_fresh_image_url 主动探测到 401/403）：
    - 第三方图床（非自有 CDN），我们拿不到 secret_key 无法重新签名；
    - 下载转存同样会 401（URL 已失效），无法救回。

    自有图床（zjtcdn 等）即便签名过期，也会通过「重签名」或「/upload/ 本地映射」恢复，
    **永远不会**走到这里抛此异常。
    """
    pass

