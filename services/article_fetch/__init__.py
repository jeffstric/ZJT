# -*- coding: utf-8 -*-
"""图文抓取入口：白名单校验 → 域名分发 → 用户级限流。

支持来源与状态：
- 微信公众号（mp.weixin.qq.com）：已实现，免登录纯 HTTP（2026-09 实测可行）
- 小红书（xiaohongshu.com / xhslink.com）：TikHub 供应商（article_fetch.xhs_provider 启用）
- 抖音（douyin.com / v.douyin.com / iesdouyin.com）：TikHub 供应商（需 TikHub key）
"""

import logging
import time
from collections import deque
from urllib.parse import urlparse

from config.constant import (
    ARTICLE_FETCH_ALLOWED_HOSTS,
    ARTICLE_FETCH_RATE_LIMIT_PER_USER_HOUR,
)
from services.article_fetch.models import (
    ArticleContent,
    ArticleFetchNotAllowed,
    ArticleFetchRateLimited,
)
from services.article_fetch import wechat_fetcher, xhs_fetcher, douyin_fetcher

logger = logging.getLogger(__name__)

# 进程内滑动窗口限流：user_id -> deque[timestamps]。多进程部署时各进程独立计数，
# 实际上限为 配置值×进程数，作为防滥用软限制足够（P0 不引入 Redis）。
_rate_windows: dict = {}


def _host_allowed(hostname: str) -> bool:
    """域名后缀匹配白名单（mp.weixin.qq.com 命中 mp.weixin.qq.com）。"""
    hostname = (hostname or "").lower()
    return any(
        hostname == allowed or hostname.endswith("." + allowed)
        for allowed in ARTICLE_FETCH_ALLOWED_HOSTS
    )


def _check_rate_limit(user_id) -> None:
    if user_id is None:
        return
    now = time.time()
    # 顺手回收一小时未活跃用户的窗口（否则 _rate_windows 随历史用户数单调增长）
    if len(_rate_windows) > 1024:
        expired = [uid for uid, win in _rate_windows.items()
                   if not win or now - win[-1] > 3600]
        for uid in expired:
            _rate_windows.pop(uid, None)
    window = _rate_windows.setdefault(int(user_id), deque())
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) >= ARTICLE_FETCH_RATE_LIMIT_PER_USER_HOUR:
        raise ArticleFetchRateLimited(
            f"已达到每小时 {ARTICLE_FETCH_RATE_LIMIT_PER_USER_HOUR} 次抓取上限。"
        )
    window.append(now)


async def fetch_article(url: str, user_id=None, include_comments: bool = False) -> ArticleContent:
    """抓取图文内容统一入口。

    Args:
        url: 用户提交的文章/笔记 URL（需在 ARTICLE_FETCH_ALLOWED_HOSTS 白名单内）
        user_id: 用户 ID（限流计数与媒体映射归属）
        include_comments: 是否附带精选评论（公众号 + 已配置 TikHub 时生效，按次计费）

    Returns:
        ArticleContent（图片已转存为本系统 /upload/ 路径）

    Raises:
        ArticleFetchError 子类：全部携带面向用户的 hint 文案。
    """
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not _host_allowed(parsed.hostname):
        supported = ", ".join(ARTICLE_FETCH_ALLOWED_HOSTS)
        raise ArticleFetchNotAllowed(f"暂不支持该链接（{parsed.hostname or '无效 URL'}）。支持的域名：{supported}")

    _check_rate_limit(user_id)

    hostname = (parsed.hostname or "").lower()
    if hostname.endswith("weixin.qq.com"):
        article = await wechat_fetcher.fetch_wechat_article(url, user_id=user_id, include_comments=include_comments)
    elif hostname.endswith("xiaohongshu.com") or hostname.endswith("xhslink.com"):
        article = await xhs_fetcher.fetch_xhs_note(url, user_id=user_id)
    elif hostname.endswith("douyin.com") or hostname.endswith("iesdouyin.com"):
        article = await douyin_fetcher.fetch_douyin_note(url, user_id=user_id)
    else:
        raise ArticleFetchNotAllowed("暂不支持该链接域名。")

    logger.info(
        "[article_fetch] ok user=%s source=%s title=%r images=%d chars=%d comments=%d",
        user_id, article.source_type, article.title[:40], len(article.images), len(article.text),
        len(article.comments),
    )
    return article
