# -*- coding: utf-8 -*-
"""正文核心信息点提炼：用 VL 网关的模型做纯文本要点提炼。

抓取完成后自动执行（best-effort），产出 key_points 列表注入 Agent 上下文
（ArticleContent.to_llm_summary 的 script_requirements 硬指令）——
解决 Agent 写脚本"拿到正文却写出空泛 prompt"的质量问题：
不依赖 Agent 自觉，把正文核心信息结构化地递到它面前。
"""

import asyncio
import inspect
import logging
from typing import List

from config.constant import (
    IMAGE_DESCRIBE_FETCH_TIMEOUT,
    IMAGE_DESCRIBE_LLM_TIMEOUT,
    IMAGE_DESCRIBE_PREFERRED_MODEL,
    IMAGE_DESCRIBE_PREFERRED_VENDOR,
)

logger = logging.getLogger(__name__)

# LLM 客户端初始化超时（与 vl_gateway.VL_GATEWAY_CLIENT_INIT_TIMEOUT 同量级）
_CLIENT_INIT_TIMEOUT = 15

_EXTRACT_SYSTEM_PROMPT = (
    "你是营销内容策划，负责从公众号/小红书文章中提炼核心信息点。"
    "只返回 JSON 数组（3~5 个字符串元素），不要任何解释、Markdown 代码块标记。"
    "\n每个元素是一个具体的、可转译为画面的信息点，要求：\n"
    "1) 优先选取文的干货/技巧/独特卖点（含关键细节，如方法名、数字），而非泛泛主题；\n"
    "2) 每条 15~40 字，中文；\n"
    "3) 按正文出现顺序排列。"
)


def _parse_points(content: str) -> List[str]:
    """容错解析 LLM 返回的 JSON 数组（容忍 ```json 包裹与尾逗号）。"""
    import json
    import re

    text = (content or "").strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([\]])", r"\1", m.group(0))
        try:
            arr = json.loads(cleaned)
        except json.JSONDecodeError:
            return []
    if not isinstance(arr, list):
        return []
    points = [str(p).strip() for p in arr if p and str(p).strip()]
    return points[:5]


async def extract_key_points(text: str, title: str = "") -> List[str]:
    """正文 → 核心信息点列表（3~5 条）。失败返回空列表（不阻断抓取主流程）。"""
    if not text or len(text) < 50:
        return []

    try:
        from llm.llm_client_factory import get_llm_client
        from services.vl_gateway import pick_vl_model
    except Exception:
        logger.warning("[article_fetch] LLM 客户端不可用，跳过要点提炼")
        return []

    try:
        picked = await asyncio.wait_for(
            pick_vl_model(
                IMAGE_DESCRIBE_PREFERRED_VENDOR,
                IMAGE_DESCRIBE_PREFERRED_MODEL,
                model=None,
                vendor_id=None,
            ),
            timeout=IMAGE_DESCRIBE_FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return []
    if not picked:
        return []

    use_model = picked.get("name") or IMAGE_DESCRIBE_PREFERRED_MODEL
    user_text = f"文章标题：{title}\n\n正文：\n{text[:6000]}"

    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
    try:
        client = await asyncio.wait_for(
            asyncio.to_thread(get_llm_client, use_model, picked.get("vendor_id")),
            timeout=_CLIENT_INIT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return []
    except Exception as e:
        logger.warning("[article_fetch] LLM 客户端初始化失败: %s", e)
        return []

    call_kwargs = dict(
        model=use_model,
        messages=messages,
        temperature=0.3,
        max_tokens=500,
    )
    if "request_timeout" in inspect.signature(client.call_api).parameters:
        call_kwargs["request_timeout"] = IMAGE_DESCRIBE_LLM_TIMEOUT
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(client.call_api, **call_kwargs),
            timeout=IMAGE_DESCRIBE_LLM_TIMEOUT + 10,
        )
        content = response.choices[0].message.content if response and response.choices else ""
    except asyncio.TimeoutError:
        logger.warning("[article_fetch] 要点提炼超时（跳过）")
        return []
    except Exception as e:
        logger.warning("[article_fetch] 要点提炼失败（跳过）: %s", e)
        return []

    points = _parse_points(content)
    if points:
        logger.info("[article_fetch] 要点提炼: %d 条", len(points))
    return points
