# -*- coding: utf-8 -*-
"""故事板 3D 预览「对话改机位」：单轮 LLM 参数提取服务。

用户在分镜 3D 空间预览弹窗内用自然语言描述机位调整（如「把机位移到
赵志高正面稍高处」），本模块把当前机位 + 空间对象坐标 + 指令交给文本
LLM，解析出新的机位参数 JSON（eye/target/fov + reason）。落库不在此
处：前端拿到参数后应用预览并写回 three_scene_code 的 setCamera 行
（three.js 代码是机位唯一真源，见 docs/storyboard/spatial_3d_preview_design.md）。

调用模式仿 services/director_stage_env_fit.py（单轮提取 + JSON 解析 +
clamp + 失败降级）；文本模型经 llm/llm_client_factory 获取，全部阻塞
调用经 asyncio.to_thread 包装（非阻塞红线）。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional

from config.constant import (
    SB_CAMERA_CHAT_EYE_Y_MAX,
    SB_CAMERA_CHAT_EYE_Y_MIN,
    SB_CAMERA_CHAT_FOV_DEFAULT,
    SB_CAMERA_CHAT_FOV_MAX,
    SB_CAMERA_CHAT_FOV_MIN,
    SB_CAMERA_CHAT_LLM_TIMEOUT,
    SB_CAMERA_CHAT_MAX_ENTITIES,
    SB_CAMERA_CHAT_MAX_MESSAGE_CHARS,
    SB_CAMERA_CHAT_MAX_TOKENS,
    SB_CAMERA_CHAT_POS_ABS_MAX,
    SB_CAMERA_CHAT_TARGET_Y_MAX,
    SB_CAMERA_CHAT_TARGET_Y_MIN,
    SB_CAMERA_CHAT_TEMPERATURE,
)
from llm.llm_client_factory import get_llm_client

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = (
    "你是短剧分镜的摄影指导，负责根据导演指令调整虚拟机位。"
    "场景是 three.js Y-up 米制坐标系：地面 y=0，角色人偶高约 1.5（头部 y≈1.1），"
    "x/z 为地面平面坐标。你会收到当前机位（eye 相机位置 / target 注视点 / fov 视场角）"
    "和场景对象清单（角色/道具/场景体块及坐标）。"
    "按指令计算一个新机位，只返回一个 JSON 对象，不要 Markdown 或其它文字。字段："
    'eye:[x,y,z] 相机位置；target:[x,y,z] 注视点（通常对准被摄对象躯干 y≈0.8~1.2）；'
    "fov: 视场角 15~120（近景小、全景大）；reason: 一句中文说明调整意图。"
    "常规机位：平视 eye.y≈1.2~1.7；仰拍 eye.y 低于被摄对象；俯拍 eye.y≈3~6；"
    "距离按景别：特写≈1~2 米、近景≈2~3.5 米、中景≈3.5~6 米、全景≈6~10 米。"
)


def build_camera_chat_messages(
    message: str,
    current_camera: Any,
    entities: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """组装单轮消息：当前机位 + 对象清单 + 用户指令。"""
    if not isinstance(current_camera, dict):
        current_camera = {}
    def _fmt(p: Any) -> str:
        """兼容 [x,y,z] 数组与 {x,y,z} 对象两种机位点格式。"""
        if isinstance(p, dict):
            vals = [p.get('x', 0), p.get('y', 0), p.get('z', 0)]
        elif isinstance(p, (list, tuple)) and len(p) >= 3:
            vals = p[:3]
        else:
            vals = (0, 0, 0)
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                nums.append(0.0)
        return f"[{nums[0]:.2f}, {nums[1]:.2f}, {nums[2]:.2f}]"

    eye = current_camera.get('eye') or {}
    target = current_camera.get('target') or {}
    lines = [
        f"当前机位：eye={_fmt(eye)} target={_fmt(target)} fov={current_camera.get('fov', SB_CAMERA_CHAT_FOV_DEFAULT)}",
    ]
    clean_entities = (entities or [])[:SB_CAMERA_CHAT_MAX_ENTITIES]
    if clean_entities:
        obj_lines = []
        for entity in clean_entities:
            kind = str(entity.get("kind") or "actor")
            facing = entity.get("facing")
            facing_note = f" 朝向{facing}°" if isinstance(facing, (int, float)) else ""
            obj_lines.append(
                f"- {entity.get('name', '?')}（{kind}）x={entity.get('x', 0):.2f}, z={entity.get('z', 0):.2f}{facing_note}"
            )
        lines.append("场景对象清单：\n" + "\n".join(obj_lines))
    instruction = str(message or "").strip()[:SB_CAMERA_CHAT_MAX_MESSAGE_CHARS]
    lines.append(f"导演指令：{instruction}")
    lines.append('只返回：{"eye":[0,1.5,4.2],"target":[0,1.0,0],"fov":50,"reason":"..."}')
    return [{"role": "user", "content": "\n\n".join(lines)}]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp_component(value: float, key: str) -> float:
    if key == "y_eye":
        return _clamp(value, SB_CAMERA_CHAT_EYE_Y_MIN, SB_CAMERA_CHAT_EYE_Y_MAX)
    if key == "y_target":
        return _clamp(value, SB_CAMERA_CHAT_TARGET_Y_MIN, SB_CAMERA_CHAT_TARGET_Y_MAX)
    return _clamp(value, -SB_CAMERA_CHAT_POS_ABS_MAX, SB_CAMERA_CHAT_POS_ABS_MAX)


def _parse_point(raw: Any, y_key: str, default_y: float) -> Optional[Dict[str, float]]:
    # 兼容 [x,y,z] 数组与 {x,y,z} 对象两种格式（LLM 偶尔返回对象）
    if isinstance(raw, dict):
        raw = [raw.get('x'), raw.get('y'), raw.get('z')]
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        x, y, z = (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError):
        return None
    if not all(map(lambda v: v == v and abs(v) != float("inf"), (x, y, z))):
        return None
    return {"x": round(_clamp_component(x, "xz"), 2), "y": round(_clamp_component(y, y_key), 2), "z": round(_clamp_component(z, "xz"), 2)}


def parse_camera_json(content: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出提取机位 JSON；解析失败返回 None（调用方降级提示）。"""
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
        eye = _parse_point(obj.get("eye"), "y_eye", 1.5)
        target = _parse_point(obj.get("target"), "y_target", 1.0)
        if not eye or not target:
            continue
        try:
            fov = float(obj.get("fov", SB_CAMERA_CHAT_FOV_DEFAULT))
        except (TypeError, ValueError):
            fov = SB_CAMERA_CHAT_FOV_DEFAULT
        if fov != fov or fov == float("inf"):
            fov = SB_CAMERA_CHAT_FOV_DEFAULT
        return {
            "eye": eye,
            "target": target,
            "fov": round(_clamp(fov, SB_CAMERA_CHAT_FOV_MIN, SB_CAMERA_CHAT_FOV_MAX), 1),
            "reason": str(obj.get("reason") or "").strip()[:120],
        }
    return None


async def parse_camera_instruction(
    message: str,
    current_camera: Dict[str, Any],
    entities: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """返回 {success, camera?{eye,target,fov}, reason?, model?, error?}。"""
    use_model = str(model or "").strip()
    if not use_model:
        return {"success": False, "error": "缺少模型，请先在故事板选择对话模型"}
    messages = build_camera_chat_messages(message, current_camera, entities)

    try:
        client = await asyncio.wait_for(
            asyncio.to_thread(get_llm_client, use_model, vendor_id),
            timeout=SB_CAMERA_CHAT_LLM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "模型客户端初始化超时，请重试"}

    call_kwargs: Dict[str, Any] = dict(
        model=use_model,
        messages=messages,
        temperature=SB_CAMERA_CHAT_TEMPERATURE,
        max_tokens=SB_CAMERA_CHAT_MAX_TOKENS,
        auth_token=auth_token or None,
        vendor_id=vendor_id,
        model_id=model_id,
    )
    if "request_timeout" in inspect.signature(client.call_api).parameters:
        call_kwargs["request_timeout"] = SB_CAMERA_CHAT_LLM_TIMEOUT
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(client.call_api, **call_kwargs),
            timeout=SB_CAMERA_CHAT_LLM_TIMEOUT + 15,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "模型响应超时，请重试或手动调整机位"}
    except Exception as exc:  # 上游 SDK 异常统一降级，不打断预览
        logger.warning("故事板机位对话 LLM 调用失败: %s", exc)
        return {"success": False, "error": "模型调用失败，请重试或手动调整机位"}

    content = ""
    if isinstance(response, str):
        content = response
    elif getattr(response, "choices", None):
        # call_api 返回 OpenAI 风格响应对象（见 services/smart_insert_service.py 同款解析）
        content = response.choices[0].message.content or ""
    parsed = parse_camera_json(content)
    if not parsed:
        logger.warning("故事板机位对话 LLM 返回无法解析: %s", (content or "")[:300])
        return {"success": False, "error": "无法解析模型结果，请换个说法或手动调整机位"}
    parsed["success"] = True
    parsed["model"] = use_model
    return parsed
