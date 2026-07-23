"""
Script segment planner - 阶段一：模型语义分段规划。

见 docs/script/script_parser_incremental_split_design.md §6。
只决定「从哪里分段」，不生成角色/场景/道具/空间世界/分镜。
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from llm.llm_client_factory import get_llm_client
from config.constant import ScriptSplitConstants

logger = logging.getLogger(__name__)

_last_log_timestamp: Optional[datetime] = None


@dataclass
class SegmentPlanLogContext:
    """一次分段规划尝试的诊断日志关联信息。"""

    task_id: int
    plan_kind: str
    attempt: int
    timestamp: str
    prefix: str
    parse_error: Optional[str] = None


def create_plan_log_context(
    task_id: int,
    plan_kind: str,
    attempt: int,
) -> Optional[SegmentPlanLogContext]:
    """创建无文件 I/O 的日志上下文；关闭开关时返回 None。"""
    if not ScriptSplitConstants.PLANNER_DIAGNOSTIC_LOGGING_ENABLED:
        return None

    global _last_log_timestamp
    now = datetime.now()
    if _last_log_timestamp is not None and now <= _last_log_timestamp:
        now = _last_log_timestamp + timedelta(microseconds=1)
    _last_log_timestamp = now
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    prefix = (
        f"script_segment_planner_task_{task_id}_{plan_kind}_"
        f"{timestamp}_attempt_{attempt}"
    )
    return SegmentPlanLogContext(
        task_id=task_id,
        plan_kind=plan_kind,
        attempt=attempt,
        timestamp=timestamp,
        prefix=prefix,
    )


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _write_diagnostic_file(
    context: Optional[SegmentPlanLogContext],
    suffix: str,
    content: str,
) -> None:
    if context is None:
        return
    path = Path(ScriptSplitConstants.PLANNER_DIAGNOSTIC_LOG_DIR) / (
        f"{context.prefix}_{suffix}"
    )
    try:
        await asyncio.to_thread(_write_text_file, path, content)
    except Exception as exc:
        logger.warning("segment planner diagnostic log write failed: %s", exc)


async def _write_json_log(
    context: Optional[SegmentPlanLogContext],
    suffix: str,
    payload: Any,
) -> None:
    await _write_diagnostic_file(
        context,
        suffix,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


async def write_plan_validation_log(
    context: Optional[SegmentPlanLogContext],
    payload: Dict[str, Any],
) -> None:
    """写入编排层产生的业务校验结论。"""
    await _write_json_log(context, "05_validation.json", payload)


def build_planning_prompt(
    anchors: List[Dict[str, Any]],
    max_output_tokens: int = ScriptSplitConstants.SEGMENT_MAX_OUTPUT_TOKENS,
) -> str:
    """构建语义分段规划提示词。"""
    anchors_text = json.dumps(anchors, ensure_ascii=False, indent=2)
    return f"""你是一个剧本分段规划专家。下面是已经锚点化的完整剧本（按原文顺序排列的 block 列表）。
你的任务是把全部 block 划分为若干连续的**语义分段**，供后续逐段生成分镜。

【分段规则】
- 按场景/幕/地点/时间变化、完整叙事单元、对白轮次、动作—反应关系划分。
- 保持空间连续性与人物位置连续性。
- 不在一句对白、一个连续动作或关键转场中间切断。
- **严禁**用「每 N 个字符一段」或「每 N 个 block 一段」机械切割。
- 每个 segment 对应的原文字符总数不得超过 {ScriptSplitConstants.SEGMENT_MAX_SOURCE_CHARS}；
  请在不破坏对白、连续动作和关键转场的前提下选择语义边界。
- 优先保证语义完整，但避免把大量高复杂度 spatial_layout 内容堆在同一段导致输出超限。
- 单段预估输出 token 不应超过 {max_output_tokens}。

【输出格式】只输出纯 JSON，不要 markdown 标记，不要解释文字：
{{
  "schema_version": 1,
  "segments": [
    {{
      "segment_id": "seg_0001",
      "block_ids": ["block_0001", "block_0002"],
      "title": "该段简短标题",
      "summary": "该段发生了什么（一句话）",
      "continuity_notes": "结束时人物位置/空间状态（供下段参考）"
    }}
  ]
}}

【约束】
- segments 必须覆盖全部 block，每个 block 恰好属于一个 segment。
- segment 顺序必须与原文一致。
- block_ids 必须来自下方锚点列表，连续不跳越。
- segment_id 全局唯一，按顺序编号 seg_0001、seg_0002……

【锚点化剧本】
```json
{anchors_text}
```
"""


def _strip_markdown(content: str) -> str:
    """移除可能的 markdown 代码块标记。"""
    s = content.strip()
    if s.startswith("```json"):
        s = s[7:]
    if s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


async def plan_segments(
    anchors: List[Dict[str, Any]],
    model: str,
    auth_token: Optional[str],
    vendor_id: Optional[int],
    model_id: Optional[int],
    enable_thinking: bool = False,
    thinking_effort: str = "medium",
    temperature: float = 0.3,
    timeout_seconds: int = ScriptSplitConstants.LLM_TIMEOUT_SECONDS,
    feedback: Optional[str] = None,
    log_context: Optional[SegmentPlanLogContext] = None,
    prompt_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """调用模型生成语义分段计划。

    Returns:
        (plan, finish_reason): plan 解析失败时返回 ({}, finish_reason)。
        finish_reason 用于判断是否 MAX_TOKENS 截断。
    """
    prompt = prompt_override or build_planning_prompt(anchors)
    if feedback:
        prompt = f"{prompt}\n\n【上轮规划反馈，请修正】\n{feedback}\n\n请重新输出完整分段计划 JSON。"

    messages = [
        {"role": "user", "content": prompt},
    ]
    await _write_json_log(log_context, "01_anchors.json", anchors)
    await _write_diagnostic_file(log_context, "02_prompt.txt", prompt)
    llm_client = get_llm_client(model, vendor_id=vendor_id)

    async def _call():
        return await asyncio.to_thread(
            llm_client.call_api,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=ScriptSplitConstants.SEGMENT_MAX_OUTPUT_TOKENS,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id,
            enable_thinking=enable_thinking,
            thinking_effort=thinking_effort,
        )

    try:
        response = await asyncio.wait_for(_call(), timeout=timeout_seconds)
    except Exception:
        await _write_diagnostic_file(log_context, "03_raw_response.txt", "")
        raise
    finish_reason = None
    try:
        finish_reason = response.choices[0].finish_reason
    except Exception:
        pass
    content = response.choices[0].message.content if response.choices else ""
    await _write_diagnostic_file(log_context, "03_raw_response.txt", content)
    cleaned = _strip_markdown(content)
    try:
        plan = json.loads(cleaned)
        await _write_json_log(log_context, "04_parsed_plan.json", plan)
        return plan, finish_reason
    except json.JSONDecodeError as e:
        if log_context is not None:
            log_context.parse_error = str(e)
        logger.warning("segment plan JSON parse failed: %s", e)
        return {}, finish_reason


__all__ = [
    "SegmentPlanLogContext",
    "build_planning_prompt",
    "create_plan_log_context",
    "plan_segments",
    "write_plan_validation_log",
]
