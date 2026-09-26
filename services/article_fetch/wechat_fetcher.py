# -*- coding: utf-8 -*-
"""微信公众号文章抓取（免登录，纯 HTTP，2026-09 实测可行）。

mp.weixin.qq.com 文章页为服务端渲染：标题 #activity-name、公众号名 #js_name、
正文 #js_content（段落文本 + img[data-src] 图片）。部分受限文章返回
"微信扫一扫可打开此内容"遮罩页，据此抛 ArticleFetchBlocked 引导用户粘贴正文。

HTTP 统一走 curl_cffi impersonate=chrome（AsyncSession 原生异步）：
普通 requests/httpx 的 Python TLS 指纹会被 WAF 拦截。
"""

import asyncio
import logging
from typing import List
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession

from config.constant import (
    ARTICLE_FETCH_HTTP_TIMEOUT,
    ARTICLE_FETCH_MAX_IMAGES,
    ARTICLE_FETCH_MAX_TEXT_CHARS,
    ARTICLE_FETCH_WECHAT_UA,
)
from services.article_fetch.models import (
    ArticleContent,
    ArticleFetchBlocked,
    ArticleFetchNotFound,
    ArticleFetchUpstreamError,
)

logger = logging.getLogger(__name__)

# 遮罩页强特征：仅微信内可见（外部浏览器/服务端均无法看到正文）
_BLOCKED_STRONG_MARKER = "微信扫一扫可打开此内容"


def is_wechat_article_url(url: str) -> bool:
    """判定是否微信公众号文章 URL（/s/ 短链或 ?__biz= 参数形态）。"""
    parsed = urlparse(url)
    if parsed.hostname != "mp.weixin.qq.com":
        return False
    return parsed.path.startswith("/s") or "__biz=" in (parsed.query or "")


async def fetch_wechat_article(url: str, user_id=None) -> ArticleContent:
    """抓取公众号文章，返回含已转存图片的 ArticleContent。"""
    html = await _fetch_html(url)

    # 解析在 to_thread 中做：bs4 遍历大 HTML 属同步 CPU 操作，避免阻塞事件循环
    parsed = await asyncio.to_thread(_parse_html, html, url)

    if parsed is None:
        # 正文缺失时再判遮罩/风控：页面 JS 源码内置"环境异常"等文案，
        # 不能在 HTML 层直接判 Blocked，否则正常文章会误判（2026-09 实测踩坑）。
        if _is_blocked_page(html):
            raise ArticleFetchBlocked("该文章存在访问限制（仅限微信内查看或触发验证）。")
        raise ArticleFetchNotFound("文章不存在或已被删除。")

    # 图片转存（异步 IO）
    from services.article_fetch.image_store import download_and_store_images
    async with AsyncSession() as session:
        images = await download_and_store_images(
            session, parsed["image_urls"][:ARTICLE_FETCH_MAX_IMAGES], user_id=user_id
        )

    return ArticleContent(
        source_type="wechat",
        source_url=url,
        title=parsed["title"],
        author=parsed["author"],
        text=parsed["text"],
        images=images,
    )


def _is_blocked_page(html: str) -> bool:
    """遮罩/风控页判定：仅正文缺失后调用。"仅微信内查看"是强特征；"环境异常"弱特征需配合页面标题缺失。"""
    if "微信扫一扫可打开此内容" in html:
        return True
    # 风控验证页：无文章标题节点 + 环境异常提示
    return "环境异常" in html and "activity-name" not in html


async def _fetch_html(url: str) -> str:
    """GET 文章页 HTML。404/被删 → NotFound；遮罩特征 → Blocked。"""
    try:
        async with AsyncSession() as session:
            response = await asyncio.wait_for(
                session.get(
                    url,
                    headers={"User-Agent": ARTICLE_FETCH_WECHAT_UA},
                    impersonate="chrome",
                    allow_redirects=True,
                ),
                timeout=ARTICLE_FETCH_HTTP_TIMEOUT,
            )
    except asyncio.TimeoutError as e:
        raise ArticleFetchUpstreamError(
            f"文章抓取超时（{ARTICLE_FETCH_HTTP_TIMEOUT}s）"
        ) from e
    except Exception as e:
        raise ArticleFetchUpstreamError(f"文章抓取失败: {type(e).__name__}") from e

    if response.status_code == 404:
        raise ArticleFetchNotFound("文章不存在或已被删除。")
    if response.status_code != 200:
        raise ArticleFetchUpstreamError(f"文章抓取失败（HTTP {response.status_code}）")

    return response.text or ""


def _parse_html(html: str, url: str):
    """解析文章页。返回 None 表示页面结构不含文章（已删除/参数错误）。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise ArticleFetchUpstreamError("服务端缺少解析依赖（beautifulsoup4/lxml）") from e

    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("#activity-name") or soup.find("meta", attrs={"property": "og:title"})
    title = (title_el.get_text(strip=True) if hasattr(title_el, "get_text") else "") or ""
    if not title and title_el is not None:
        title = (title_el.get("content") or "").strip()

    author_el = soup.select_one("#js_name")
    author = author_el.get_text(strip=True) if author_el else ""

    content_el = soup.select_one("#js_content")
    if content_el is None:
        if "该内容已被发布者删除" in html:
            return None
        return None

    # 段落文本：按 DOM 顺序提取块级文本节点
    lines: List[str] = []
    for node in content_el.find_all(["p", "section", "li", "h1", "h2", "h3", "blockquote"]):
        text = node.get_text(" ", strip=True)
        if text and (not lines or text != lines[-1]):
            lines.append(text)
    # 嵌套 section 会重复取到子级文本，用 find_all 父级去重效果有限，再做整体去重保序
    seen = set()
    text_parts: List[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            text_parts.append(line)
    text = "\n".join(text_parts).strip()
    if len(text) > ARTICLE_FETCH_MAX_TEXT_CHARS:
        text = text[:ARTICLE_FETCH_MAX_TEXT_CHARS] + "…（正文过长已截断）"

    # 图片：img[data-src]（懒加载真实地址），过滤小表情/CDN 装饰图（data-type）
    image_urls = []
    for img in content_el.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src.startswith("http"):
            continue
        if img.get("data-type") == "gif" and img.get("data-w", "") in ("", "0", "1"):
            continue
        if src not in image_urls:
            image_urls.append(src)

    if not title:
        title = "未命名文章"

    return {"title": title, "author": author, "text": text, "image_urls": image_urls}
