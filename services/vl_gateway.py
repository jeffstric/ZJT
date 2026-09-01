# -*- coding: utf-8 -*-
"""VL（视觉语言模型）调用共享网关。

统一三处 VL 识图链路的公共部分，消除重复实现：
- 画风识别：api/script_writer.py recognize_style（POST /api/recognize-style）
- 导演台环境对齐：services/director_stage_env_fit.py
- 图片描述：services/image_describe.py（POST /api/video-workflow/describe-image）

公共能力：
- pick_vl_model：可用 VL 模型挑选（已配置密钥 + 偏好排序）
- image_url_to_base64：图片 URL → base64 data URL（本站 upload 路径本地读取；
  allow_remote=True 时 http(s) 远程 URL 下载兜底）
- call_vl：多模态消息构造 + VL 调用（request_timeout 兼容探测 + 全链路超时保护）

各调用方的业务提示词与结果解析（画风 JSON / 估参 JSON / 描述清洗）仍留在调用方。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from config.constant import (
    DS_ENV_FIT_ALLOWED_IMAGE_EXTENSIONS,
    VL_GATEWAY_CLIENT_INIT_TIMEOUT,
    VL_GATEWAY_DB_TIMEOUT,
    VL_GATEWAY_REMOTE_FETCH_TIMEOUT,
)
from llm.llm_client_factory import get_available_models, get_llm_client
from utils.image_compressor import (
    async_download_and_compress_to_base64,
    compress_local_image_to_base64,
)
from utils.project_path import get_upload_dir

logger = logging.getLogger(__name__)

# 与 utils/image_compressor 的 LLM 视觉输入推荐参数一致（≤2MB、≤2,073,600 像素）
_MAX_SIZE_MB = 2.0
_MAX_PIXELS = 2_073_600

# 通用图片扩展白名单（与 DS_ENV_FIT_ALLOWED_IMAGE_EXTENSIONS 同值，复用避免重复常量）
_ALLOWED_IMAGE_EXTENSIONS = DS_ENV_FIT_ALLOWED_IMAGE_EXTENSIONS


def resolve_upload_path(
    image_url: str,
    user_id: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """把本站 upload URL 安全解析为本地路径。失败返回 (None, error)。

    安全规则（与 services/director_stage_env_fit.py 加固版一致）：
    - URL 先 unquote 再校验；拒绝反斜杠与 ``.``/``..`` 路径段（防目录穿越）；
    - 必须以 upload/ 或 /upload/ 开头，resolve 后必须仍在 upload 根内；
    - 扩展名白名单；传入 user_id 时进一步限定到该用户的 workflow 目录。
    """
    if not image_url or not str(image_url).strip():
        return None, "缺少图片 url"
    raw_path = str(image_url).strip()
    parsed = urlparse(raw_path)
    path = unquote(parsed.path if parsed.scheme else raw_path)
    if "\\" in path:
        return None, "非法的图片路径"
    if path.startswith("/upload/"):
        path = path[len("/upload/"):]
    elif path.startswith("upload/"):
        path = path[len("upload/"):]
    else:
        return None, "非法的图片路径"

    parts = [part for part in path.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        return None, "非法的图片路径"

    upload_root = Path(get_upload_dir()).resolve()
    allowed_root = upload_root
    if user_id is not None:
        allowed_root = (upload_root / "workflow" / str(user_id)).resolve()
    try:
        local_path = upload_root.joinpath(*parts).resolve(strict=False)
        local_path.relative_to(allowed_root)
    except (OSError, RuntimeError, ValueError):
        return None, "非法的图片路径"
    if local_path.suffix.lower() not in _ALLOWED_IMAGE_EXTENSIONS:
        return None, "不支持的图片格式"
    if not local_path.is_file():
        return None, "图片文件不存在"
    return str(local_path), None


async def pick_vl_model(
    pref_vendor: str,
    pref_model: str,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """选出已配置密钥的 VL 模型。没有则返回 None（调用方应降级）。

    排序：指定 model 精确匹配 > 偏好 vendor+model > 偏好 vendor > 名称序。
    """
    result = await asyncio.wait_for(
        get_available_models(), timeout=VL_GATEWAY_DB_TIMEOUT
    )
    models = [m for m in (result.get("models") or []) if m.get("supports_vl")]
    if not models:
        return None
    pref_vendor = (pref_vendor or "").lower()
    pref_model = (pref_model or "").lower()
    if model:
        name = str(model).lower()
        for m in models:
            if (m.get("name") or "").lower() == name:
                if vendor_id is None or m.get("vendor_id") == vendor_id:
                    return m
        for m in models:
            if pref_model in (m.get("name") or "").lower():
                return m
        return models[0]

    def sort_key(item: dict):
        vendor = (item.get("vendor_name") or "").lower()
        name = (item.get("name") or "").lower()
        is_pref = 0 if (vendor == pref_vendor and pref_model in name) else 1
        is_volc = 0 if vendor == pref_vendor else 1
        return (is_pref, is_volc, vendor, name)

    models.sort(key=sort_key)
    return models[0]


async def image_url_to_base64(
    image_url: str = "",
    *,
    compress_timeout: float,
    allow_remote: bool = False,
    remote_timeout: Optional[float] = None,
    local_path: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """图片 URL → 压缩后的 base64 data URL。

    - local_path：调用方已自行完成安全解析（如 env_fit 的用户隔离版）时直通压缩，
      跳过 URL 解析；
    - 否则按本站 upload 路径解析（user_id 可限定到该用户 workflow 目录）；
    - allow_remote=True 时 http(s) 远程 URL 走下载压缩兜底（其余来源一律拒绝）。

    返回 (ok, data_url, error)。
    """
    if local_path is None:
        local_path, path_err = resolve_upload_path(image_url, user_id=user_id)
    if local_path:
        try:
            ok, data_url, err = await asyncio.wait_for(
                asyncio.to_thread(
                    compress_local_image_to_base64,
                    local_path,
                    _MAX_SIZE_MB,
                    _MAX_PIXELS,
                ),
                timeout=compress_timeout,
            )
        except asyncio.TimeoutError:
            return False, None, "图片压缩超时"
        return ok, data_url, err

    parsed = urlparse(str(image_url or ""))
    if allow_remote and parsed.scheme in ("http", "https"):
        timeout = remote_timeout or VL_GATEWAY_REMOTE_FETCH_TIMEOUT
        try:
            ok, data_url, err = await asyncio.wait_for(
                async_download_and_compress_to_base64(
                    str(image_url).strip(), _MAX_SIZE_MB, _MAX_PIXELS
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return False, None, "图片下载超时"
        return ok, data_url, err
    return False, None, path_err if local_path is None else "非法的图片路径"


async def call_vl(
    system_prompt: str,
    user_text: str,
    image_data_url: str,
    *,
    model: str,
    llm_timeout: float,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
    auth_token: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 400,
) -> Tuple[bool, str, Optional[str]]:
    """调用 VL 模型分析一张图片。返回 (ok, content, error)。

    - 图片以 base64 data URL 放入 OpenAI 多模态消息；
    - 仅 OpenAI 兼容系列 client 支持 request_timeout，先探测签名再条件传入；
    - to_thread + 外层 wait_for 兜底超时（超时红线 R4/R5/R6）；
    - 同时传 auth_token 与 model_id 时由 client 内部上报 token 用量（算力计费）。
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]

    try:
        client = await asyncio.wait_for(
            asyncio.to_thread(get_llm_client, model, vendor_id),
            timeout=VL_GATEWAY_CLIENT_INIT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return False, "", "视觉模型客户端初始化超时"

    call_kwargs = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        auth_token=auth_token or None,
        vendor_id=vendor_id,
        model_id=model_id,
    )
    if "request_timeout" in inspect.signature(client.call_api).parameters:
        call_kwargs["request_timeout"] = llm_timeout
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(client.call_api, **call_kwargs),
            timeout=llm_timeout + 10,
        )
    except asyncio.TimeoutError:
        return False, "", "视觉模型调用超时"
    except Exception:
        logger.exception("VL 调用失败 (model=%s)", model)
        return False, "", "视觉模型调用失败"

    try:
        content = (
            response.choices[0].message.content
            if response and response.choices
            else ""
        )
    except Exception:
        content = ""
    if not content or not str(content).strip():
        return False, "", "视觉模型返回内容为空"
    return True, str(content), None
