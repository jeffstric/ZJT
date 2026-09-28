# -*- coding: utf-8 -*-
"""小红书抓取分发：按配置选择供应商实现。

供应商注册表：本期已实现 tikhub（TikHub app_v2 笔记详情）。
未配置供应商时抛 ArticleFetchNotSupported，Agent 侧引导用户粘贴文字与图片。
"""

import logging
import re
from urllib.parse import urlparse, parse_qs

from services.article_fetch.models import ArticleContent, ArticleFetchNotSupported

logger = logging.getLogger(__name__)

ENV_PROVIDER = "XHS_DATA_PROVIDER"


def _get_xhs_provider_name() -> str:
    """供应商名：统一配置 article_fetch.xhs_provider 优先，环境变量兜底。"""
    try:
        from config.config_util import get_config_value
        from config.constant import ARTICLE_FETCH_XHS_PROVIDER

        name = str(get_config_value("article_fetch", "xhs_provider", default=ARTICLE_FETCH_XHS_PROVIDER) or "").strip()
        if name:
            return name
    except Exception:
        pass
    import os

    return (os.environ.get(ENV_PROVIDER) or "").strip()


def _extract_note_id(url: str) -> str:
    """从小红书 URL 提取 note_id（explore/{id} / discovery/item/{id} / query 的 target 参数）。"""
    parsed = urlparse(url)
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{16,32})", parsed.path or "")
    if m:
        return m.group(1)
    q = parse_qs(parsed.query or "")
    for key in ("target", "note_id", "id"):
        if q.get(key):
            return q[key][0]
    raise ArticleFetchNotSupported("无法从小红书链接中解析笔记 ID，请粘贴完整的分享链接。")


def _build_providers():
    """惰性构建供应商注册表（避免未配置依赖时 import 失败）。"""
    providers = {}
    try:
        from services.article_fetch.providers.tikhub import TikHubClient, is_tikhub_configured

        if is_tikhub_configured():

            class _TikhubXhsProvider:
                async def fetch(self, url: str, user_id=None) -> ArticleContent:
                    import asyncio

                    from config.constant import ARTICLE_FETCH_MAX_IMAGES
                    from services.article_fetch.image_store import download_and_store_images
                    from services.article_fetch.providers import tikhub as th

                    note_id = _extract_note_id(url)
                    client = TikHubClient()
                    data = await client.fetch_xhs_note_raw(note_id)
                    parsed = await asyncio.to_thread(th.parse_xhs_note, data, url)

                    images = []
                    if parsed["image_urls"]:
                        from curl_cffi.requests import AsyncSession

                        async with AsyncSession() as session:
                            images = await download_and_store_images(
                                session, parsed["image_urls"][:ARTICLE_FETCH_MAX_IMAGES], user_id=user_id
                            )
                    return ArticleContent(
                        source_type="xiaohongshu",
                        source_url=url,
                        title=parsed["title"],
                        author=parsed["author"],
                        text=parsed["text"],
                        images=images,
                    )

            providers["tikhub"] = _TikhubXhsProvider
    except Exception as e:  # 依赖缺失（httpx 等）时不注册
        logger.warning("[article_fetch] TikHub 小红书供应商不可用: %s", e)
    return providers


def has_provider() -> bool:
    """小红书抓取是否可用（配置了且存在已注册实现）。"""
    return _get_xhs_provider_name() in _build_providers()


async def fetch_xhs_note(url: str, user_id=None) -> ArticleContent:
    """按配置分发到具体 provider。"""
    provider_name = _get_xhs_provider_name()
    provider_cls = _build_providers().get(provider_name)
    if provider_cls is None:
        if provider_name:
            raise ArticleFetchNotSupported(f"小红书抓取供应商「{provider_name}」未配置 API Key 或不可用。")
        raise ArticleFetchNotSupported("小红书抓取暂未开通。")
    provider = provider_cls()
    return await provider.fetch(url, user_id=user_id)
