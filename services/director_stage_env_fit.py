# -*- coding: utf-8 -*-
"""导演台全景环境尺度对齐：用已接入的 VL 模型估计 horizonY / sceneScale。"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from config.constant import (
    DS_ENV_FIT_COMPRESS_TIMEOUT,
    DS_ENV_FIT_DEFAULT_GROUND,
    DS_ENV_FIT_DEFAULT_HORIZON,
    DS_ENV_FIT_DEFAULT_SCALE,
    DS_ENV_FIT_GROUND_MAX,
    DS_ENV_FIT_GROUND_MIN,
    DS_ENV_FIT_HORIZON_MAX,
    DS_ENV_FIT_HORIZON_MIN,
    DS_ENV_FIT_LLM_TIMEOUT,
    DS_ENV_FIT_PREFERRED_MODEL,
    DS_ENV_FIT_PREFERRED_VENDOR,
    DS_ENV_FIT_SCALE_MAX,
    DS_ENV_FIT_SCALE_MIN,
)
from llm.llm_client_factory import get_available_models, get_llm_client
from utils.image_compressor import compress_local_image_to_base64

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = (
    "你是影视美术指导，负责把 3D 人偶对齐到 360 全景背景。"
    "图中彩色几何体人偶代表约 170 厘米高的成年站立者。"
    "只返回一个 JSON 对象，不要 Markdown 或其它文字。"
    "字段："
    "horizonY（米，0=照片地平线在脚边，1.5=平视，范围 0~2.5）；"
    "sceneScale（相对当前身高倍率，人偶像玩具则增大，像巨人则减小，范围 0.5~4）；"
    "groundY（米，人偶脚底相对 3D 地面。脚悬空未踩到可见地面则必须为负，例如 -0.8 到 -1.5；"
    "脚陷进地面则为正。务必让脚底落在可见地面/地板上，不要悬空）；"
    "reason（一句中文）。"
)

USER_TEXT_TMPL = (
    "当前 horizonY={horizon:.2f}，sceneScale={scale:.2f}，groundY={ground:.2f}。"
    "请检查：1) 人偶相对家具是否像玩具/巨人；2) 脚是否悬空。"
    "只返回："
    '{{"horizonY":1.5,"sceneScale":2.0,"groundY":-0.8,"reason":"..."}}'
)


def resolve_upload_path(image_url: str) -> Tuple[Optional[str], Optional[str]]:
    """把本站 upload url 解析为本地路径。失败返回 (None, error)。"""
    if not image_url or not str(image_url).strip():
        return None, "缺少图片 url"
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    upload_root = os.path.join(app_dir, "upload").replace("\\", "/")
    rel = str(image_url).strip()
    if "://" in rel:
        rel = urlparse(rel).path
    rel = rel.lstrip("/").replace("\\", "/")
    if "/upload/" in rel:
        rel = rel[rel.index("/upload/") + len("/upload/"):]
    elif rel.startswith("upload/"):
        rel = rel[len("upload/"):]
    local_path = os.path.normpath(os.path.join(upload_root, rel))
    if not local_path.replace("\\", "/").startswith(upload_root):
        return None, "非法的图片路径"
    if not os.path.isfile(local_path):
        return None, "图片文件不存在"
    return local_path, None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def parse_fit_json(content: str) -> Optional[Dict[str, Any]]:
    if not content:
        return None
    candidates = []
    m = _JSON_BLOCK_RE.search(content)
    if m:
        candidates.append(m.group(1))
    m = _FIRST_OBJ_RE.search(content)
    if m:
        candidates.append(m.group(0))
    candidates.append(content.strip())
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if "horizonY" not in obj and "sceneScale" not in obj and "groundY" not in obj:
            continue
        try:
            horizon = float(obj.get("horizonY", DS_ENV_FIT_DEFAULT_HORIZON))
            scale = float(obj.get("sceneScale", DS_ENV_FIT_DEFAULT_SCALE))
            ground = float(obj.get("groundY", DS_ENV_FIT_DEFAULT_GROUND))
        except (TypeError, ValueError):
            continue
        reason = str(obj.get("reason") or "").strip()[:80]
        return {
            "horizonY": round(_clamp(horizon, DS_ENV_FIT_HORIZON_MIN, DS_ENV_FIT_HORIZON_MAX), 2),
            "sceneScale": round(_clamp(scale, DS_ENV_FIT_SCALE_MIN, DS_ENV_FIT_SCALE_MAX), 2),
            "groundY": round(_clamp(ground, DS_ENV_FIT_GROUND_MIN, DS_ENV_FIT_GROUND_MAX), 2),
            "reason": reason,
        }
    return None


async def pick_vl_model(model: Optional[str] = None, vendor_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """选出已配置密钥的 VL 模型。没有则返回 None（调用方应降级为人工）。"""
    result = await get_available_models()
    models = [m for m in (result.get("models") or []) if m.get("supports_vl")]
    if not models:
        return None
    pref_vendor = (DS_ENV_FIT_PREFERRED_VENDOR or "volcengine").lower()
    pref_model = (DS_ENV_FIT_PREFERRED_MODEL or "doubao-seed-2-0-lite").lower()
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


async def fit_environment_from_image(
    image_url: str,
    auth_token: Optional[str] = None,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
    horizon_y: float = DS_ENV_FIT_DEFAULT_HORIZON,
    scene_scale: float = DS_ENV_FIT_DEFAULT_SCALE,
    ground_y: float = DS_ENV_FIT_DEFAULT_GROUND,
) -> Dict[str, Any]:
    """返回 {success, fallback?, horizonY?, sceneScale?, groundY?, reason?, error?}。"""
    local_path, path_err = resolve_upload_path(image_url)
    if path_err:
        return {"success": False, "fallback": "manual", "error": path_err}

    picked = await pick_vl_model(model=model, vendor_id=vendor_id)
    if not picked:
        return {
            "success": False,
            "fallback": "manual",
            "error": "未配置视觉模型，请手动调节地平线与场景比例",
        }

    use_model = picked.get("name") or model
    use_vendor_id = vendor_id if vendor_id is not None else picked.get("vendor_id")
    use_model_id = model_id if model_id is not None else picked.get("model_id")

    try:
        ok, data_url, err = await asyncio.wait_for(
            asyncio.to_thread(
                compress_local_image_to_base64,
                local_path,
                2.0,
                2_073_600,
            ),
            timeout=DS_ENV_FIT_COMPRESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"success": False, "fallback": "manual", "error": "预览图压缩超时，请手动调节"}
    if not ok or not data_url:
        return {"success": False, "fallback": "manual", "error": "预览图处理失败，请手动调节"}

    user_text = USER_TEXT_TMPL.format(horizon=horizon_y, scale=scene_scale, ground=ground_y)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ]

    client = await asyncio.to_thread(get_llm_client, use_model, use_vendor_id)
    call_kwargs = dict(
        model=use_model,
        messages=messages,
        temperature=0.2,
        max_tokens=300,
        auth_token=auth_token or None,
        vendor_id=use_vendor_id,
        model_id=use_model_id,
    )
    if "request_timeout" in inspect.signature(client.call_api).parameters:
        call_kwargs["request_timeout"] = DS_ENV_FIT_LLM_TIMEOUT
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(client.call_api, **call_kwargs),
            timeout=DS_ENV_FIT_LLM_TIMEOUT + 10,
        )
    except asyncio.TimeoutError:
        return {"success": False, "fallback": "manual", "error": "视觉模型超时，请手动调节地平线与场景比例"}
    except Exception as exc:
        logger.exception("导演台环境 VL 估参失败")
        return {"success": False, "fallback": "manual", "error": "视觉模型不可用，请手动调节地平线与场景比例"}

    content = ""
    try:
        content = response.choices[0].message.content if response and response.choices else ""
    except Exception:
        content = ""
    parsed = parse_fit_json(content or "")
    if not parsed:
        logger.warning("导演台环境 VL 返回无法解析: %s", (content or "")[:300])
        return {
            "success": False,
            "fallback": "manual",
            "error": "无法解析模型结果，请手动调节地平线与场景比例",
        }
    parsed["success"] = True
    parsed["model"] = use_model
    parsed["vendor_id"] = use_vendor_id
    return parsed
