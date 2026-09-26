# -*- coding: utf-8 -*-
"""抓取图片下载与本地转存。

所有来源（公众号/小红书）的图片统一经此模块落盘到
upload/marketing_fetched/<yyyymmdd>/<uuid><ext>，并注册 media_file_mapping
（CACHE 实体 + MEDIA_CACHE 策略，过期清理由现有机制接管）。

下载统一走 curl_cffi AsyncSession：普通 requests/httpx 的 Python TLS 指纹
会被部分站点 WAF 拦截（2026-09 小红书实测），curl_cffi impersonate=chrome
在三系统均为纯 pip 依赖，无浏览器/系统组件。
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from curl_cffi.requests import AsyncSession

from config.constant import (
    ARTICLE_FETCH_IMAGE_MAX_BYTES,
    ARTICLE_FETCH_IMAGE_TIMEOUT,
    ARTICLE_FETCH_WECHAT_REFERER,
    ARTICLE_FETCH_WECHAT_UA,
)
from services.article_fetch.models import ArticleImage, ArticleFetchUpstreamError

logger = logging.getLogger(__name__)

# 按域名配置下载请求头：微信图片域必须带 Referer（防盗链保险），其余站默认浏览器头
_DOMAIN_HEADERS = {
    "mmbiz.qpic.cn": {
        "Referer": ARTICLE_FETCH_WECHAT_REFERER,
        "User-Agent": ARTICLE_FETCH_WECHAT_UA,
    },
}
_DEFAULT_HEADERS = {"User-Agent": ARTICLE_FETCH_WECHAT_UA}

_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _ext_from_url(url: str) -> str:
    """从 URL 路径推断扩展名；无扩展名时返回空串由 Content-Type 兜底。"""
    from urllib.parse import urlparse, unquote

    path = unquote(urlparse(url).path)
    ext = Path(path).suffix.lower()
    return ext if ext in _ALLOWED_IMAGE_EXTS else ""


def _ext_from_content_type(content_type: str) -> str:
    return _CONTENT_TYPE_EXT.get((content_type or "").split(";")[0].strip().lower(), ".jpg")


async def download_and_store_image(
    session: AsyncSession,
    url: str,
    index: int,
    user_id: Optional[int] = None,
) -> ArticleImage:
    """下载单张图片并转存到 upload/marketing_fetched/，注册媒体映射。

    超时/网络错误抛 ArticleFetchUpstreamError；单图失败即整体失败——
    参考图缺失会让后续图生视频脚本出现空洞，宁可让用户重试。
    """
    from config.constant import UploadPathConstants
    from utils.media_mapping_util import register_uploaded_file_mapping, upload_local_path
    from model.media_file_mapping import MediaFileEntity
    from config.media_file_policy import MediaFilePolicy
    from utils.project_path import get_project_root

    headers = dict(_DEFAULT_HEADERS)
    for domain, domain_headers in _DOMAIN_HEADERS.items():
        if domain in url:
            headers.update(domain_headers)
            break

    try:
        response = await asyncio.wait_for(
            session.get(url, headers=headers, impersonate="chrome"),
            timeout=ARTICLE_FETCH_IMAGE_TIMEOUT,
        )
    except asyncio.TimeoutError as e:
        raise ArticleFetchUpstreamError(f"图片下载超时（{ARTICLE_FETCH_IMAGE_TIMEOUT}s）") from e
    except Exception as e:
        raise ArticleFetchUpstreamError(f"图片下载失败: {type(e).__name__}") from e

    if response.status_code != 200:
        raise ArticleFetchUpstreamError(f"图片下载失败（HTTP {response.status_code}）")

    content = response.content or b""
    if len(content) == 0:
        raise ArticleFetchUpstreamError("图片下载内容为空")
    if len(content) > ARTICLE_FETCH_IMAGE_MAX_BYTES:
        raise ArticleFetchUpstreamError(
            f"图片超过大小上限（{ARTICLE_FETCH_IMAGE_MAX_BYTES // (1024 * 1024)}MB）"
        )

    ext = _ext_from_url(url) or _ext_from_content_type(response.headers.get("Content-Type", ""))
    day_dir = datetime.now().strftime("%Y%m%d")
    rel_dir = Path(UploadPathConstants.UPLOAD_ROOT) / "marketing_fetched" / day_dir
    abs_dir = Path(get_project_root()) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / f"{uuid.uuid4().hex}{ext}"
    abs_path.write_bytes(content)

    local_path = upload_local_path(str(abs_path))
    register_uploaded_file_mapping(
        user_id=user_id,
        local_path=local_path,
        entity_type=MediaFileEntity.CACHE,
        policy_code=MediaFilePolicy.MEDIA_CACHE,
    )
    return ArticleImage(index=index, original_url=url, url=f"/{local_path}")


async def download_and_store_images(
    session: AsyncSession,
    urls: List[str],
    user_id: Optional[int] = None,
) -> List[ArticleImage]:
    """按顺序下载并转存图片清单，返回带序号的 ArticleImage 列表。"""
    images: List[ArticleImage] = []
    for index, url in enumerate(urls):
        images.append(await download_and_store_image(session, url, index, user_id=user_id))
    return images
