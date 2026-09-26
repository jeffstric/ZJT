# -*- coding: utf-8 -*-
"""小红书抓取分发骨架（本期不实现具体 provider）。

按环境变量 XHS_DATA_PROVIDER 选择供应商实现；本期未提供任何实现，
未配置或值不对应已注册实现时统一抛 ArticleFetchNotSupported，
Agent 侧引导用户粘贴文字与图片（降级路径）。
"""

import logging
import os

from services.article_fetch.models import ArticleFetchNotSupported

logger = logging.getLogger(__name__)

# 下期实现注册表：{"tikhub": TikHubProvider, "rnote": RnoteProvider, ...}
PROVIDERS = {}

ENV_PROVIDER = "XHS_DATA_PROVIDER"


def has_provider() -> bool:
    """小红书抓取是否可用（配置了且存在已注册实现）。"""
    return os.environ.get(ENV_PROVIDER, "").strip() in PROVIDERS


async def fetch_xhs_note(url: str, user_id=None):
    """按配置分发到具体 provider；本期必然抛 NotSupported。"""
    provider_name = os.environ.get(ENV_PROVIDER, "").strip()
    provider_cls = PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ArticleFetchNotSupported("小红书抓取暂未开通。")
    provider = provider_cls()
    return await provider.fetch(url, user_id=user_id)
