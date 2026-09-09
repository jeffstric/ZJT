"""Agent 链路 LLM 调用的 max_tokens 动态计算。

背景：DB model.max_output_tokens 可能写入上下文窗口量级的数值（如
deepseek-v4-flash-vision-exp 为 384000），全量透传会使 输入+输出预留
超过模型上下文上限报 400（事故见
docs/backend/incidents/2026-09-09-asset-readiness-context-overflow.md）。
固定硬上限对小上下文模型仍可能超限，因此按"模型剩余上下文"动态收缩：

    max_tokens = min(DB 值, 静态上限, context_window - 估算输入 - 安全余量)

并兜底一个最小输出额度，保证上下文接近占满时模型仍能短回复（如 ask_user）。
ExpertAgent 与 PMAgent 两处调用点共用，避免逻辑分叉。
"""
import logging
from typing import Any, Optional

from config.constant import (
    AGENT_LLM_CONTEXT_SAFETY_MARGIN_TOKENS,
    AGENT_LLM_MAX_OUTPUT_TOKENS_CAP,
    AGENT_LLM_MIN_OUTPUT_TOKENS,
)

logger = logging.getLogger(__name__)

# 模型记录缺失 max_output_tokens 时的默认值
_DEFAULT_MAX_OUTPUT_TOKENS = 65536


def resolve_max_output_tokens(
    model: Optional[Any],
    estimated_input_tokens: int,
    agent_id: str = "",
) -> int:
    """计算本次 LLM 调用的 max_tokens（静态封顶 + 按剩余上下文动态收缩）。

    Args:
        model: model 表记录（需带 max_output_tokens / context_window 属性），可为 None
        estimated_input_tokens: 本次请求的估算输入 tokens（通常取上次 API 真实
            input_tokens 与本轮消息字符估算的较大值）
        agent_id: 调用方标识，仅用于日志
    """
    max_output_tokens = _DEFAULT_MAX_OUTPUT_TOKENS
    context_window = None
    if model is not None:
        if getattr(model, "max_output_tokens", None):
            max_output_tokens = model.max_output_tokens
        context_window = getattr(model, "context_window", None)

    # 静态上限：防 DB 写入上下文量级脏数据（只降不升）
    if max_output_tokens > AGENT_LLM_MAX_OUTPUT_TOKENS_CAP:
        logger.info(
            f"{agent_id}: max_output_tokens {max_output_tokens} 超过静态上限，"
            f"封顶为 {AGENT_LLM_MAX_OUTPUT_TOKENS_CAP}"
        )
        max_output_tokens = AGENT_LLM_MAX_OUTPUT_TOKENS_CAP

    # 动态收缩：按该模型剩余上下文收紧，保证 输入 + 输出预留 <= context_window
    if context_window and estimated_input_tokens > 0:
        remaining = context_window - estimated_input_tokens - AGENT_LLM_CONTEXT_SAFETY_MARGIN_TOKENS
        dynamic_cap = max(remaining, AGENT_LLM_MIN_OUTPUT_TOKENS)
        if dynamic_cap < max_output_tokens:
            logger.info(
                f"{agent_id}: 按剩余上下文动态收缩 max_tokens: "
                f"{max_output_tokens} -> {dynamic_cap} "
                f"(context_window={context_window}, estimated_input={estimated_input_tokens}, "
                f"margin={AGENT_LLM_CONTEXT_SAFETY_MARGIN_TOKENS})"
            )
            max_output_tokens = dynamic_cap

    return max_output_tokens
