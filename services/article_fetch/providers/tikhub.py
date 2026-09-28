# -*- coding: utf-8 -*-
"""TikHub 信息采集供应商实现（第三方付费 API，按次计费 $0.01/次）。

接口基础（https://docs.tikhub.io，openapi.json 实测核对 2026-09-28）：
- 公众号文章详情：POST /api/v1/wechat_mp/v2/fetch_article_detail_h5（body: url）
  （h5 版对"仅微信内查看"受限文章成功率更高；失败回退 fetch_article_detail）
- 公众号文章评论：POST /api/v1/wechat_mp/v2/fetch_article_comments
  （body: url/buffer/comment_id/raw；raw=false 精简视图；官方建议客户端超时 30s）
- 小红书图文/视频笔记详情：GET /api/v1/xiaohongshu/app_v2/get_image_note_detail
  与 get_video_note_detail（参数 note_id 或 share_text）

认证：Authorization: Bearer <api_key>。
计费提醒：每次调用 $0.01；402 表示余额不足；超时可能已扣费但无响应，故超时
设置足够宽（30s）且不做自动重试（重试=重复扣费），失败让上层降级。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from config.constant import (
    ARTICLE_FETCH_TIKHUB_BASE_URL,
    ARTICLE_FETCH_TIKHUB_TIMEOUT,
    ARTICLE_FETCH_MAX_TEXT_CHARS,
    ARTICLE_FETCH_WECHAT_UA,
)
from services.article_fetch.models import (
    ArticleComment,
    ArticleContent,
    ArticleFetchError,
    ArticleFetchNotFound,
    ArticleFetchNotSupported,
    ArticleFetchUpstreamError,
)

logger = logging.getLogger(__name__)


def get_tikhub_api_key() -> str:
    """读取 TikHub API key：动态配置（admin 后台可改）优先，环境变量兜底。

    必须用 get_dynamic_config_value（DB 优先 + YAML 兜底）——admin 快速配置
    写入的是 system_config 表，get_config_value 只读 YAML 永远读不到
    （2026-09-28 事故：admin 已配 key 但兜底不生效，受限文章仍 Blocked）。
    """
    try:
        from config.config_util import get_dynamic_config_value

        key = str(get_dynamic_config_value("article_fetch", "tikhub_api_key", default="") or "").strip()
        if key:
            return key
    except Exception:
        pass
    import os

    return (os.environ.get("TIKHUB_API_KEY") or "").strip()


def is_tikhub_configured() -> bool:
    return bool(get_tikhub_api_key())


class TikHubClient:
    """TikHub REST 客户端（异步非阻塞）。"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or get_tikhub_api_key()
        self.base_url = (base_url or ARTICLE_FETCH_TIKHUB_BASE_URL).rstrip("/")
        if not self.api_key:
            raise ArticleFetchNotSupported("未配置信息采集供应商（TikHub API Key）。")

    async def _request(
        self, method: str, path: str, *, params: Optional[Dict] = None, json_body: Optional[Dict] = None
    ) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": ARTICLE_FETCH_WECHAT_UA,
        }
        try:
            async with httpx.AsyncClient(timeout=ARTICLE_FETCH_TIKHUB_TIMEOUT, verify=False) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=headers, params=params, json=json_body
                )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            # TikHub 官方提醒：超时可能已扣费；不自动重试，交给上层降级
            raise ArticleFetchUpstreamError(
                f"信息采集供应商响应超时/网络异常（{type(e).__name__}），本条请求已中止"
            ) from e

        if response.status_code == 401:
            raise ArticleFetchNotSupported("TikHub API Key 无效或已过期，请联系管理员更新。")
        if response.status_code == 402:
            raise ArticleFetchUpstreamError("TikHub 账户余额不足，请联系管理员充值。")
        if response.status_code == 404:
            raise ArticleFetchNotFound("内容不存在（供应商返回 404）。")
        if response.status_code != 200:
            raise ArticleFetchUpstreamError(f"信息采集供应商异常（HTTP {response.status_code}）")

        try:
            payload = response.json()
        except Exception as e:
            raise ArticleFetchUpstreamError("信息采集供应商返回非 JSON 响应") from e
        if not isinstance(payload, dict) or payload.get("code") not in (None, 0, 200):
            # TikHub 失败响应形如 {"code": xxx, "message": "..."}
            message = payload.get("message") if isinstance(payload, dict) else None
            raise ArticleFetchUpstreamError(f"信息采集供应商返回错误: {message or payload}")
        return payload.get("data") if isinstance(payload.get("data"), (dict, list)) else {}

    # ── 公众号 ──────────────────────────────────────────────

    async def fetch_wechat_article_raw(self, url: str) -> Dict[str, Any]:
        """公众号文章详情（原始 dict）。h5 版优先，失败回退标准版。"""
        try:
            return await self._request(
                "POST", "/api/v1/wechat_mp/v2/fetch_article_detail_h5", json_body={"url": url}
            )
        except ArticleFetchError as e:
            if isinstance(e, ArticleFetchNotSupported):
                raise
            logger.info("[tikhub] h5 详情失败回退标准版: %s", str(e)[:80])
            return await self._request(
                "POST", "/api/v1/wechat_mp/v2/fetch_article_detail", json_body={"url": url}
            )

    async def fetch_wechat_comments(
        self, url: str, comment_id: str = "", top_n: int = 10
    ) -> List[ArticleComment]:
        """公众号文章精选评论（第一页，点赞数排序取 top_n）。每次调用 $0.01。"""
        data = await self._request(
            "POST",
            "/api/v1/wechat_mp/v2/fetch_article_comments",
            json_body={"url": url, "buffer": "", "comment_id": comment_id, "raw": False},
        )
        comments: List[ArticleComment] = []
        for item in data.get("comments") or []:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            try:
                like_num = int(item.get("like_num") or 0)
            except (TypeError, ValueError):
                like_num = 0
            comments.append(
                ArticleComment(
                    nick_name=str(item.get("nick_name") or "匿名"),
                    content=content,
                    like_num=like_num,
                    is_elected=bool(item.get("is_elected")),
                )
            )
        comments.sort(key=lambda c: c.like_num, reverse=True)
        return comments[:top_n]

    # ── 小红书 ──────────────────────────────────────────────

    async def fetch_xhs_note_raw(self, note_id: str = "", share_text: str = "") -> Dict[str, Any]:
        """小红书笔记详情（图文接口，视频笔记仅返回封面）。

        note_id 优先；没有 note_id 时传 share_text（支持 xiaohongshu.com 长链与
        xhslink.com/.cn 短链，供应商自行解析）。营销场景只需标题/正文/图片，
        视频笔记不再二次调 get_video_note_detail（省一次计费）。
        """
        params = {"note_id": note_id} if note_id else {"share_text": share_text}
        return await self._request(
            "GET", "/api/v1/xiaohongshu/app_v2/get_image_note_detail", params=params
        )


def _html_to_text(html: str) -> str:
    """HTML 片段转纯文本（bs4 同步 CPU 操作，调用方需在 to_thread 中执行）。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    return soup.get_text("\n", strip=True)


def _clean_text(text: str) -> str:
    """清洗 h5 content_text 尾部常见残留：话题标签的转义实体与标签碎片。"""
    import re

    text = text or ""
    # 转义实体（\x26quot; / &quot; / &lt; / &gt; / &amp;）与残余标签
    text = re.sub(r"<[^>]*>", "", text)
    text = text.replace("\\x26quot;", '"').replace("&quot;", '"')
    text = text.replace("\\x26lt;", "<").replace("&lt;", "<")
    text = text.replace("\\x26gt;", ">").replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    # 收敛多余空行
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def parse_wechat_article(data: Dict[str, Any], url: str) -> Dict[str, Any]:
    """TikHub 公众号详情响应 → 标题/作者/纯文本/图片清单。

    h5 接口实测结构（2026-09-28 受限文章实测核对）：
      data = {"url":..., "content": {title/nick_name/content_text/
              picture_page_info_list[{cdn_url,...}], ...}, ...}
    - 正文纯文本：content_text（h5 直出，免 bs4）；旧版 HTML 响应走 content + bs4 兜底
    - 作者：content.nick_name（公众号昵称；author 字段常为空）
    - 图片：content.picture_page_info_list[].cdn_url（过滤二维码图）
    """
    content_obj = data.get("content") if isinstance(data.get("content"), dict) else data

    title = (
        content_obj.get("title")
        or data.get("title")
        or (data.get("article") or {}).get("title")
        or ""
    )
    author = (
        content_obj.get("nick_name")
        or (data.get("account") or {}).get("nickname")
        or content_obj.get("author")
        or data.get("author")
        or ""
    )

    # 正文：h5 纯文本优先，HTML 兜底（bs4 清洗属同步操作，调用方在 to_thread 中执行）
    text = (content_obj.get("content_text") or content_obj.get("content_noencode") or "").strip()
    html = (
        content_obj.get("content")
        or (data.get("article") or {}).get("content")
        or content_obj.get("text")
        or data.get("text")
        or ""
    )
    if not text and html:
        text = html if "<" not in html[:200] else _html_to_text(str(html))
    text = _clean_text(text)
    if len(text) > ARTICLE_FETCH_MAX_TEXT_CHARS:
        text = text[:ARTICLE_FETCH_MAX_TEXT_CHARS] + "…（正文过长已截断）"

    # 图片：picture_page_info_list（h5 图片型文章直出，含 cdn_url/宽高/二维码标记）
    image_urls: List[str] = []
    for item in content_obj.get("picture_page_info_list") or []:
        if not isinstance(item, dict) or item.get("is_qr_code"):
            continue
        u = item.get("cdn_url") or ""
        if u and u not in image_urls:
            image_urls.append(u)
    # HTML 正文内嵌图片兜底（旧版响应）
    raw_html = str(html) if html else ""
    if raw_html:
        import re

        for src in re.findall(r'https://mmbiz\.qpic\.cn/[^"\s\\)]+', raw_html):
            src = src.replace("&amp;", "&")
            if src not in image_urls:
                image_urls.append(src)
    for key in ("images", "image_list", "image_url_list"):
        for item in data.get(key) or content_obj.get(key) or []:
            u = item if isinstance(item, str) else (item.get("url") or item.get("src") or "")
            if u and u not in image_urls:
                image_urls.append(u)

    if not title and not text:
        raise ArticleFetchUpstreamError("供应商返回内容为空，无法解析文章")
    return {"title": str(title) or "未命名文章", "author": str(author), "text": text, "image_urls": image_urls}


def parse_xhs_note(data: Dict[str, Any], url: str) -> Dict[str, Any]:
    """TikHub 小红书响应 → 标题/作者/纯文本/图片清单。

    实测结构（2026-09-28 官方实测响应核对）：
      data = {"code":0, "success":true, "data":[{"note_list":[{笔记}]}, ...], "msg":"成功"}
    计费陷阱（官方文档）：错误/不存在的笔记 ID 仍返回 200 并计费，data 内
    为上游"服务异常"信息——必须按 success/note_list 判定失败。
    图片取 original（原图）→ url_size_large(1440) → url(576)，
    CDN 参数 format/webp 替换为 format/jpg（参考图通用性更好）。
    """
    # 服务异常 / 笔记不存在检测
    if not isinstance(data, dict) or data.get("success") is not True or data.get("code") != 0:
        msg = (data or {}).get("msg") if isinstance(data, dict) else None
        raise ArticleFetchNotFound(f"小红书笔记抓取失败（{msg or '服务异常'}）。请确认链接有效。")

    try:
        note = data["data"][0]["note_list"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise ArticleFetchNotFound("小红书笔记不存在或已被删除。") from e

    title = note.get("title") or note.get("display_title") or ""
    author = ((note.get("user") or {}).get("nickname")) or ""
    text = (note.get("desc") or note.get("content") or "").strip()[:ARTICLE_FETCH_MAX_TEXT_CHARS]

    def _pick_image_url(item: Any) -> str:
        if isinstance(item, str):
            return item
        if not isinstance(item, dict):
            return ""
        # url_size_large(1440) 优先：original(5000) 单张 1-2MB 偶发下载超时，
        # 1440 档对视频参考图足够且下载稳定；再回退 url(576)/multi_level
        u = item.get("url_size_large") or item.get("original") or item.get("url") or ""
        if not u and isinstance(item.get("url_multi_level"), dict):
            u = item["url_multi_level"].get("high") or item["url_multi_level"].get("medium") or ""
        # format/webp → format/jpg（小红书 CDN 参数，参考图通用性；替换失败无碍仍可用）
        return u.replace("format/webp", "format/jpg") if u else ""

    image_urls: List[str] = []
    for item in note.get("images_list") or note.get("image_list") or note.get("images") or []:
        u = _pick_image_url(item)
        if u and u not in image_urls:
            image_urls.append(u)
    # 视频笔记：本接口仅返回封面；取 share_info.image 或视频封面兜底
    if not image_urls:
        cover = ((note.get("share_info") or {}).get("image")) or ""
        if cover:
            image_urls.append(cover)

    if not title and not text:
        raise ArticleFetchUpstreamError("供应商返回内容为空，无法解析笔记")
    return {"title": str(title) or "未命名笔记", "author": str(author), "text": text, "image_urls": image_urls}
