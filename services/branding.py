"""
品牌定制公共门面。

本模块定义品牌定制的「读取契约」。社区版默认实现只返回默认值（智剧通），
**不读取、不感知任何 ``branding.*`` 动态配置**，因此社区版用户即使直接
往 ``system_config`` 表写入 ``branding.*`` 记录也无法生效——读取链路在社区
版根本不存在。

商业版在启动时通过 ``register_provider`` 注入实现（见
``enterprise/services/branding_provider.py``），该实现才会读取
``branding.*`` 配置并覆盖默认值。

设计参考：``services/registration_quota.py`` 的 Provider 模式。

调用方：
- ``server.py`` 的 ``_get_processed_html`` 调用 ``get_branding_config()``
  获取品牌信息做 SSR 占位符替换。
- ``enterprise/routes/branding.py`` 调用 provider 的写入方法（仅商业版）。
"""
import logging
from typing import Protocol, Dict

from config.constant import BrandingConstants

logger = logging.getLogger(__name__)


class BrandingProvider(Protocol):
    """商业实现需要满足的最小协议；只声明能力，不包含业务算法。"""

    available: bool

    def get_config(self) -> Dict[str, str]:
        """
        返回当前品牌配置 dict，包含：
        - site_name: 系统名称
        - logo_url: Logo URL
        - favicon_url: Favicon URL
        - terms_url_zh: 中文用户手册 URL
        - terms_url_en: 英文用户手册 URL
        - wx_group_qr_url: 微信群二维码 URL（空串表示未定制，走原有逻辑）

        商业版实现应读取 branding.* 动态配置并覆盖默认值。
        """
        ...


class CommunityBrandingProvider:
    """
    社区版默认实现：永远返回默认值，不读取任何 branding.* 配置。

    这是安全设计的关键——社区版的读取链路对 branding.* 配置完全无感知，
    即使有人直接写库也无法注入定制品牌。
    """

    available = False

    def get_config(self) -> Dict[str, str]:
        return {
            "site_name": BrandingConstants.DEFAULT_SITE_NAME,
            "logo_url": BrandingConstants.DEFAULT_LOGO_URL,
            "favicon_url": BrandingConstants.DEFAULT_FAVICON_URL,
            "terms_url_zh": BrandingConstants.DEFAULT_TERMS_URL_ZH,
            "terms_url_en": BrandingConstants.DEFAULT_TERMS_URL_EN,
            # 微信群二维码：社区版返回空串，表示未定制，由 api/system.py 走原有
            # wx_group_guide.qr_url 配置逻辑（保持向后兼容）
            "wx_group_qr_url": "",
        }


_community_provider = CommunityBrandingProvider()
_provider: BrandingProvider = _community_provider


def register_provider(provider: BrandingProvider) -> None:
    """由经过加载校验的企业模块注册真实实现。"""
    if provider is None or not getattr(provider, 'available', False):
        raise ValueError('品牌定制 Provider 必须声明 available=True')
    global _provider
    _provider = provider
    logger.info("企业版品牌定制 Provider 已注册")


def reset_provider() -> None:
    """重置为社区版默认实现（enterprise 加载失败时回退）。"""
    global _provider
    _provider = _community_provider


def get_branding_config() -> Dict[str, str]:
    """
    获取当前品牌配置（供 server.py SSR 注入使用）。

    社区版：返回默认值（智剧通），不读 branding.* 配置。
    商业版：返回注入实现的配置（读取 branding.* 动态配置）。
    """
    return _provider.get_config()


def is_available() -> bool:
    """
    品牌定制功能是否可用（供前端功能探查使用）。

    - 社区版 / 工作室版（enterprise 未注入 branding provider）：返回 False
    - 企业版（enterprise 注入了 EnterpriseBrandingProvider）：返回 True

    前端据此决定是否显示品牌定制管理入口，避免在不可用的版本中显示坏入口。
    设计参考 task.runninghub_key_pool.is_available()。
    """
    return bool(getattr(_provider, 'available', False))
