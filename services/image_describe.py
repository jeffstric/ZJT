# -*- coding: utf-8 -*-
"""图片描述：用已接入的 VL 模型为任意图片生成场景描述提示词。

视频工作流画布使用：360 全景节点连入图片节点且图片自身无提示词时，
调用本服务识图生成描述，填入全景节点提示词（不覆盖用户已输入内容）。

模型挑选 / 图片获取 / VL 调用由 services/vl_gateway.py 共享网关提供，
本模块只保留业务提示词与描述清洗。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Optional

from config.constant import (
    IMAGE_DESCRIBE_COMPRESS_TIMEOUT,
    IMAGE_DESCRIBE_FETCH_TIMEOUT,
    IMAGE_DESCRIBE_LLM_TIMEOUT,
    IMAGE_DESCRIBE_PREFERRED_MODEL,
    IMAGE_DESCRIBE_PREFERRED_VENDOR,
)
from services.vl_gateway import call_vl, image_url_to_base64, pick_vl_model

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 500

SYSTEM_PROMPT = (
    "你是影视概念设计师，负责看图写出可直接用于生成 360° 全景环境图的场景描述。"
    "只返回一段中文描述文字，不要 JSON、Markdown、标题、序号或任何解释。"
    "\n"
    "要求：\n"
    "1) 描述画面中的环境本身：地点类型、空间布局、四周有什么、地面材质、"
    "光线与氛围、时间与天气。\n"
    "2) 适合环绕视角：假设观察者站在画面中心环顾四周，描述应涵盖可见环境而非单一构图。\n"
    "3) 若画面以人物/物体为主体，把环境作为描述重点，人物只作点缀（如「一位旅人站在湖边」）。\n"
    "4) 40~120 字，一段话，使用逗号/顿号分隔的关键描述，不写「图中可见」「这张图」等措辞。\n"
    "5) 不描述：画框、构图、镜头、文字水印、多宫格。"
)

USER_TEXT = (
    "请看这张图片，写出用于生成同场景 360° 全景环境图的中文场景描述。"
    "只返回描述文字本身。"
)


def _clean_description(content: str) -> str:
    """容错清洗模型回复：去代码块包裹/引号/首尾空白，截断到上限。"""
    if not content:
        return ""
    text = content.strip()
    # 去掉可能的 markdown 代码块包裹
    m = re.search(r"```(?:\w+)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 去掉成对引号包裹
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'「”":
        text = text[1:-1].strip()
    # 多段压成一段（全景提示词是单段描述）
    text = re.sub(r"\s*\n+\s*", "，", text)
    return text[:MAX_DESCRIPTION_CHARS].strip()


async def describe_image(
    image_url: str,
    user_id: Optional[int] = None,
    auth_token: Optional[str] = None,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
) -> Dict[str, Any]:
    """任意图片 → VL 生成场景描述。

    user_id 用于本站图片的用户目录隔离（与 env_fit 加固版语义一致）；
    远程 http(s) URL 不受目录限制（allow_remote=True 时由调用方自行权衡）。
    返回 {success, description?, model?, vendor_id?, error?}。
    """
    if not image_url or not str(image_url).strip():
        return {"success": False, "error": "缺少图片 url"}

    try:
        picked = await asyncio.wait_for(
            pick_vl_model(
                IMAGE_DESCRIBE_PREFERRED_VENDOR,
                IMAGE_DESCRIBE_PREFERRED_MODEL,
                model=model,
                vendor_id=vendor_id,
            ),
            timeout=IMAGE_DESCRIBE_FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "视觉模型列表查询超时，请稍后重试或手动输入描述"}
    if not picked:
        return {"success": False, "error": "未配置可用的视觉模型，无法识图生成描述"}

    use_model = picked.get("name") or model
    use_vendor_id = vendor_id if vendor_id is not None else picked.get("vendor_id")
    use_model_id = model_id if model_id is not None else picked.get("model_id")

    try:
        ok, data_url, err = await asyncio.wait_for(
            image_url_to_base64(
                str(image_url).strip(),
                compress_timeout=IMAGE_DESCRIBE_COMPRESS_TIMEOUT,
                allow_remote=True,
                remote_timeout=IMAGE_DESCRIBE_FETCH_TIMEOUT,
                user_id=user_id,
            ),
            timeout=IMAGE_DESCRIBE_FETCH_TIMEOUT + 5,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "图片获取超时，请稍后重试或手动输入描述"}
    if not ok or not data_url:
        return {"success": False, "error": f"图片处理失败: {err or '未知错误'}"}

    try:
        ok, content, err = await asyncio.wait_for(
            call_vl(
                SYSTEM_PROMPT,
                USER_TEXT,
                data_url,
                model=use_model,
                llm_timeout=IMAGE_DESCRIBE_LLM_TIMEOUT,
                vendor_id=use_vendor_id,
                model_id=use_model_id,
                auth_token=auth_token,
                temperature=0.3,
                max_tokens=300,
            ),
            timeout=IMAGE_DESCRIBE_LLM_TIMEOUT + 15,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "视觉模型识图超时，请稍后重试或手动输入描述"}
    if not ok:
        error = str(err or "识图生成描述失败")
        if "超时" in error:
            error = "视觉模型识图超时，请稍后重试或手动输入描述"
        return {"success": False, "error": error}

    description = _clean_description(content or "")
    if not description:
        logger.warning("VL 图片描述返回无法解析: %s", (content or "")[:300])
        return {"success": False, "error": "无法解析识图结果，请手动输入描述"}

    return {
        "success": True,
        "description": description,
        "model": use_model,
        "vendor_id": use_vendor_id,
    }
