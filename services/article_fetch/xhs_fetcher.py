# -*- coding: utf-8 -*-
"""小红书抓取分发：按配置选择供应商实现。

供应商注册表：本期已实现 tikhub（TikHub app_v2 笔记详情）。
未配置供应商时抛 ArticleFetchNotSupported，Agent 侧引导用户粘贴文字与图片。
"""

import asyncio
import logging
import re
from urllib.parse import urlparse, parse_qs

from services.article_fetch.models import ArticleContent, ArticleFetchNotSupported

logger = logging.getLogger(__name__)

ENV_PROVIDER = "XHS_DATA_PROVIDER"


def _get_xhs_provider_name() -> str:
    """供应商名：动态配置（admin 可改）优先，环境变量兜底。

    用 get_dynamic_config_value（DB 优先）：admin 快速配置写 system_config 表。
    """
    try:
        from config.config_util import get_dynamic_config_value
        from config.constant import ARTICLE_FETCH_XHS_PROVIDER

        name = str(get_dynamic_config_value("article_fetch", "xhs_provider", default=ARTICLE_FETCH_XHS_PROVIDER) or "").strip()
        if name:
            return name
    except Exception:
        pass
    import os

    return (os.environ.get(ENV_PROVIDER) or "").strip()


def _extract_note_id(url: str):
    """从 URL 提取 note_id（explore/{id} / discovery/item/{id} / query 的 target 参数）。

    提取不到（如 xhslink 短链）返回 None——短链走 TikHub 的 share_text 参数
    （支持 xiaohongshu.com / xhslink.com / xhslink.cn，供应商自行解析）。
    """
    parsed = urlparse(url)
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{16,32})", parsed.path or "")
    if m:
        return m.group(1)
    q = parse_qs(parsed.query or "")
    for key in ("target", "note_id", "id"):
        if q.get(key):
            return q[key][0]
    return None


def _build_providers():
    """惰性构建供应商注册表（避免未配置依赖时 import 失败）。"""
    providers = {}
    try:
        from services.article_fetch.providers.tikhub import TikHubClient, is_tikhub_configured

        if is_tikhub_configured():

            class _TikhubXhsProvider:
                async def fetch(self, url: str, user_id=None) -> ArticleContent:
                    from config.constant import ARTICLE_FETCH_MAX_IMAGES
                    from services.article_fetch.image_store import download_and_store_images
                    from services.article_fetch.providers import tikhub as th

                    note_id = _extract_note_id(url) or ""
                    client = TikHubClient()
                    data = await client.fetch_xhs_note_raw(
                        note_id=note_id, share_text="" if note_id else url
                    )
                    parsed = await asyncio.to_thread(th.parse_xhs_note, data, url)

                    images = []
                    if parsed["image_urls"]:
                        from curl_cffi.requests import AsyncSession

                        async with AsyncSession() as session:
                            images = await download_and_store_images(
                                session, parsed["image_urls"][:ARTICLE_FETCH_MAX_IMAGES], user_id=user_id
                            )
                    article = ArticleContent(
                        source_type="xiaohongshu",
                        source_url=url,
                        title=parsed["title"],
                        author=parsed["author"],
                        text=parsed["text"],
                        images=images,
                    )
                    # VL 识图（best-effort）：让 Agent 看懂图片再选参考图
                    try:
                        from services.article_fetch.wechat_fetcher import _attach_image_descriptions

                        await _attach_image_descriptions(article, user_id=user_id)
                    except Exception:
                        pass
                    return article

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
