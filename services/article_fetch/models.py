# -*- coding: utf-8 -*-
"""图文抓取统一数据结构与异常语义。

抓取层（services/article_fetch）与 Agent 工具层（enterprise/tools/content_tools.py）
之间的唯一契约：任何来源（公众号/小红书/未来扩展）抓取成功都产出 ArticleContent，
失败都抛本模块定义的异常，由工具层翻译为面向 Agent 的错误文案。
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional


class ArticleFetchError(Exception):
    """抓取失败基类。message 面向 Agent/用户，可直接展示。"""

    default_hint = "请检查链接后重试，或直接粘贴文章文字内容。"

    def __init__(self, message: str, hint: Optional[str] = None):
        self.hint = hint or self.default_hint
        super().__init__(f"{message} {self.hint}")


class ArticleFetchNotAllowed(ArticleFetchError):
    """URL 不在白名单（域名不支持）。"""

    default_hint = "目前仅支持微信公众号文章链接（mp.weixin.qq.com）。"


class ArticleFetchNotSupported(ArticleFetchError):
    """来源支持但对应抓取实现未启用（如小红书 provider 未配置）。"""

    default_hint = "该平台抓取暂未开通，可直接粘贴笔记文字与图片。"


class ArticleFetchNotFound(ArticleFetchError):
    """文章不存在/已删除/链接失效。"""

    default_hint = "请确认文章链接是否有效（可在浏览器中打开验证）。"


class ArticleFetchBlocked(ArticleFetchError):
    """命中平台访问限制（验证页/仅微信内可见遮罩等）。"""

    default_hint = "该文章存在访问限制，请将文章正文复制粘贴给我。"


class ArticleFetchRateLimited(ArticleFetchError):
    """触发用户级抓取频率限制。"""

    default_hint = "抓取过于频繁，请稍后再试。"


class ArticleFetchUpstreamError(ArticleFetchError):
    """上游网络/服务异常（超时、5xx 等）。"""

    default_hint = "网络异常，请稍后重试；或直接粘贴文章文字内容。"


@dataclass
class ArticleImage:
    """单张已本地化的图片。original_url 保留溯源，url 为本系统可访问路径。"""

    index: int
    original_url: str
    url: str  # /upload/marketing_fetched/... 本地路径


@dataclass
class ArticleContent:
    """抓取产物统一中间结构：正文纯文本 + 已转存图片清单。"""

    source_type: str            # "wechat" | "xiaohongshu" | ...
    source_url: str
    title: str
    author: str
    text: str                   # 纯文本正文（已截断至 ARTICLE_FETCH_MAX_TEXT_CHARS）
    images: List[ArticleImage] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)

    def to_llm_summary(self) -> dict:
        """注入 Agent 上下文的精简视图：图片只进清单不进二进制，控制 token。"""
        return {
            "source_type": self.source_type,
            "source_url": self.source_url,
            "title": self.title,
            "author": self.author,
            "text": self.text,
            "image_count": len(self.images),
            "images": [
                {"index": img.index, "url": img.url} for img in self.images
            ],
        }
