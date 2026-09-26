# -*- coding: utf-8 -*-
"""小红书抓取供应商抽象协议（本期仅定义接口，不写实现）。

小红书免登录纯 HTTP 不可行（2026-09 实测：WAF 按 TLS 指纹拦截 + PC web 强制
登录态）。下期接入第三方代采 API（TikHub/Rnote 均约 $0.01/次按量计费）或
自研 curl_cffi+登录 cookie 兜底方案，接入时新增 provider 文件并注册到
xhs_fetcher.PROVIDERS 即可，工具层与前端零改动。
"""

from typing import Protocol

from services.article_fetch.models import ArticleContent


class XhsProvider(Protocol):
    """小红书抓取供应商协议。

    实现方约定：
    - 异步非阻塞，内部 HTTP 一律 AsyncSession / httpx.AsyncClient；
    - 成功返回 ArticleContent（source_type="xiaohongshu"）；
    - 失败抛 services.article_fetch.models 中的 ArticleFetchError 子类，
      语义映射：笔记不存在/token 失效 → NotFound；限流 → RateLimited；
      供应商故障 → UpstreamError；未配置 → NotSupported。
    """

    async def fetch(self, url: str, user_id=None) -> ArticleContent:
        """抓取单条小红书笔记（分享链接或 explore 详情页 URL）。"""
        ...
