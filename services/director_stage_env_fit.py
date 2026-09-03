# -*- coding: utf-8 -*-
"""导演台全景环境尺度对齐：用已接入的 VL 模型估计 horizonY / sceneScale。

模型挑选 / 图片压缩 / VL 调用由 services/vl_gateway.py 共享网关提供，
本模块保留：用户隔离的图片路径安全解析（develop 加固版语义）与估参业务解析。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from config.constant import (
    DS_ENV_FIT_ALLOWED_IMAGE_EXTENSIONS,
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
    VL_GATEWAY_DB_TIMEOUT,
)
from services.vl_gateway import (
    call_vl,
    image_url_to_base64,
    pick_vl_model as _gateway_pick_vl_model,
)
from utils.project_path import get_upload_dir

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


def resolve_upload_path(
    image_url: str,
    user_id: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """把本站 upload URL 安全解析到当前用户的工作流目录。"""
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
    if local_path.suffix.lower() not in DS_ENV_FIT_ALLOWED_IMAGE_EXTENSIONS:
        return None, "不支持的图片格式"
    if not local_path.is_file():
        return None, "图片文件不存在"
    return str(local_path), None


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
    """选出已配置密钥的 VL 模型（偏好见 DS_ENV_FIT_* 常量）。没有则返回 None。"""
    return await asyncio.wait_for(
        _gateway_pick_vl_model(
            DS_ENV_FIT_PREFERRED_VENDOR,
            DS_ENV_FIT_PREFERRED_MODEL,
            model=model,
            vendor_id=vendor_id,
        ),
        timeout=VL_GATEWAY_DB_TIMEOUT,
    )


async def fit_environment_from_image(
    image_url: str,
    user_id: Optional[int] = None,
    auth_token: Optional[str] = None,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
    horizon_y: float = DS_ENV_FIT_DEFAULT_HORIZON,
    scene_scale: float = DS_ENV_FIT_DEFAULT_SCALE,
    ground_y: float = DS_ENV_FIT_DEFAULT_GROUND,
) -> Dict[str, Any]:
    """返回 {success, fallback?, horizonY?, sceneScale?, groundY?, reason?, error?}。"""
    # 用户隔离的安全路径解析（限制在 upload/workflow/{user_id}/ 内）
    local_path, path_err = resolve_upload_path(image_url, user_id=user_id)
    if path_err:
        return {"success": False, "fallback": "manual", "error": path_err}

    try:
        picked = await asyncio.wait_for(
            pick_vl_model(model=model, vendor_id=vendor_id),
            timeout=VL_GATEWAY_DB_TIMEOUT + 5,
        )
    except asyncio.TimeoutError:
        return {"success": False, "fallback": "manual", "error": "视觉模型列表查询超时，请手动调节地平线与场景比例"}
    if not picked:
        return {
            "success": False,
            "fallback": "manual",
            "error": "未配置视觉模型，请手动调节地平线与场景比例",
        }

    use_model = picked.get("name") or model
    use_vendor_id = vendor_id if vendor_id is not None else picked.get("vendor_id")
    use_model_id = model_id if model_id is not None else picked.get("model_id")

    # 已完成用户隔离解析的本地路径直通压缩（env_fit 仅支持本站图，不走远程）
    try:
        ok, data_url, err = await asyncio.wait_for(
            image_url_to_base64(
                compress_timeout=DS_ENV_FIT_COMPRESS_TIMEOUT,
                allow_remote=False,
                local_path=local_path,
            ),
            timeout=DS_ENV_FIT_COMPRESS_TIMEOUT + 5,
        )
    except asyncio.TimeoutError:
        return {"success": False, "fallback": "manual", "error": "预览图压缩超时，请手动调节"}
    if not ok or not data_url:
        if err and "超时" in str(err):
            return {"success": False, "fallback": "manual", "error": "预览图压缩超时，请手动调节"}
        return {"success": False, "fallback": "manual", "error": str(err or "预览图处理失败，请手动调节")}

    user_text = USER_TEXT_TMPL.format(horizon=horizon_y, scale=scene_scale, ground=ground_y)

    try:
        ok, content, err = await asyncio.wait_for(
            call_vl(
                SYSTEM_PROMPT,
                user_text,
                data_url,
                model=use_model,
                llm_timeout=DS_ENV_FIT_LLM_TIMEOUT,
                vendor_id=use_vendor_id,
                model_id=use_model_id,
                auth_token=auth_token,
                temperature=0.2,
                max_tokens=300,
            ),
            timeout=DS_ENV_FIT_LLM_TIMEOUT + 15,
        )
    except asyncio.TimeoutError:
        return {"success": False, "fallback": "manual", "error": "视觉模型超时，请手动调节地平线与场景比例"}
    if not ok:
        if err and "超时" in str(err):
            return {"success": False, "fallback": "manual", "error": "视觉模型超时，请手动调节地平线与场景比例"}
        logger.warning("导演台环境 VL 估参失败: %s", err)
        return {"success": False, "fallback": "manual", "error": "视觉模型不可用，请手动调节地平线与场景比例"}

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
