# -*- coding: utf-8 -*-
"""抖音图文抓取（TikHub douyin/web 详情接口，按次计费）。

入口：douyin_fetcher.fetch_douyin_note(url)
- 支持 www.douyin.com/video|note/{id} 与 v.douyin.com 短链（share_url 整链传供应商解析）
- 依赖 TikHub key（article_fetch.tikhub_api_key / XHS_DATA_PROVIDER 不相关）
"""

import logging
from urllib.parse import urlparse

from services.article_fetch.models import (
    ArticleContent,
    ArticleFetchNotSupported,
)

logger = logging.getLogger(__name__)


async def fetch_douyin_note(url: str, user_id=None) -> ArticleContent:
    """抓取抖音图文/视频笔记，返回含已转存图片的 ArticleContent。"""
    import asyncio

    from config.constant import ARTICLE_FETCH_MAX_IMAGES
    from services.article_fetch.image_store import download_and_store_images
    from services.article_fetch.providers import douyin as douyin_provider
    from services.article_fetch.providers.tikhub import TikHubClient, is_tikhub_configured

    if not is_tikhub_configured():
        raise ArticleFetchNotSupported("抖音抓取需要管理员配置信息采集供应商（TikHub）。")

    client = TikHubClient()
    # share_url 整链传供应商（支持 douyin.com 全链与 v.douyin.com 短链）
    data = await client._request(
        "GET", "/api/v1/douyin/web/fetch_one_video_by_share_url", params={"share_url": url}
    )
    parsed = await asyncio.to_thread(douyin_provider.parse_douyin_note, data, url)

    images = []
    if parsed["image_urls"]:
        from curl_cffi.requests import AsyncSession

        async with AsyncSession() as session:
            images = await download_and_store_images(
                session, parsed["image_urls"][:ARTICLE_FETCH_MAX_IMAGES], user_id=user_id
            )

    article = ArticleContent(
        source_type="douyin",
        source_url=url,
        title=parsed["title"],
        author=parsed["author"],
        text=parsed["text"],
        images=images,
    )

    # VL 识图（best-effort）：与公众号/小红书一致，让 Agent 看懂图片再选参考图
    try:
        from services.article_fetch.wechat_fetcher import _attach_image_descriptions

        await _attach_image_descriptions(article, user_id=user_id)
    except Exception:
        pass
    return article
