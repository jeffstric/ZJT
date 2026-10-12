# -*- coding: utf-8 -*-
"""抖音图文抓取供应商（TikHub douyin/web 详情接口）。

接口（openapi.json 实测核对 2026-10-13）：
- 详情：GET /api/v1/douyin/web/fetch_one_video_by_share_url?share_url=...
  支持 douyin.com 网页链接与 v.douyin.com 短链（供应商自行解析）。
  图文笔记与视频笔记通用；视频笔记只返回封面（与小红书接口同语义）。

实测响应结构（2026-10-13 图文笔记）：
  data = {"aweme_detail": {
      "desc": 正文文案,
      "author": {"nickname": ...},
      "images": [{"url_list": [...], "download_url_list": [...], "width", "height"}, ...]
  }}
注意：aweme_detail 为 null/缺失 = 笔记不存在或链接无效（供应商正常返回并计费）。
"""

import logging
from typing import Any, Dict, List

from config.constant import ARTICLE_FETCH_MAX_TEXT_CHARS
from services.article_fetch.models import (
    ArticleContent,
    ArticleFetchNotFound,
    ArticleFetchUpstreamError,
)

logger = logging.getLogger(__name__)


def parse_douyin_note(data: Dict[str, Any], url: str) -> Dict[str, Any]:
    """TikHub 抖音详情响应 → 标题/作者/纯文本/图片清单。

    - 笔记文本在 aweme_detail.desc（抖音图文无独立 title，用 desc 首行作标题）；
    - 图片优先 download_url_list[0]（直链，通常 .webp/.jpeg），回退 url_list[0]。
    """
    detail = data.get("aweme_detail") if isinstance(data, dict) else None
    if not isinstance(detail, dict) or not detail:
        raise ArticleFetchNotFound("抖音内容不存在或链接无效。")

    desc = (detail.get("desc") or "").strip()
    author = ((detail.get("author") or {}).get("nickname")) or ""
    lines = [ln.strip() for ln in desc.split("\n") if ln.strip()]
    title = lines[0][:60] if lines else "未命名笔记"
    text = desc[:ARTICLE_FETCH_MAX_TEXT_CHARS]

    image_urls: List[str] = []
    for item in detail.get("images") or []:
        if not isinstance(item, dict):
            continue
        # download_url_list[0] 是直链（第一个），url_list 为 CDN 备选
        candidates = (item.get("download_url_list") or []) + (item.get("url_list") or [])
        u = next((c for c in candidates if c and c.startswith("http")), "")
        if u and u not in image_urls:
            image_urls.append(u)

    if not title and not text and not image_urls:
        raise ArticleFetchUpstreamError("供应商返回内容为空，无法解析笔记")
    return {
        "title": title,
        "author": str(author),
        "text": text,
        "image_urls": image_urls,
    }
