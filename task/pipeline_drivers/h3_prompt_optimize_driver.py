"""
MiniMax H3 提示词优化 Pipeline 驱动。

在正式提交 RunningHub 前，把用户原文改写成 I2VA / FL2VA 规范。
直接完成步骤，不创建 async_task；LLM 失败时回退原文，不阻断出片。
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

from config.config_util import get_dynamic_config_value
from config.constant import (
    H3_PROMPT_OPTIMIZE_MAX_TOKENS,
    H3_PROMPT_OPTIMIZE_TEMPERATURE,
    H3_PROMPT_OPTIMIZE_TIMEOUT,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
    LLMModel,
)
from model import AITool, PipelineStep
from task.pipeline_drivers.base_pipeline_driver import BasePipelineDriver
from task.pipeline_drivers.h3_prompt_optimize_util import (
    build_h3_optimize_user_message,
    merge_h3_prompt_extra_config,
    resolve_h3_prompt_variant,
    strip_prompt_fences,
    validate_h3_optimized_prompt,
)

_SYSTEM_PROMPT = (
    "You rewrite MiniMax H3 video prompts. Output only the final English prompt. "
    "Do not add explanations or markdown fences."
)


class H3PromptOptimizePipelineDriver(BasePipelineDriver):
    """MiniMax H3 I2VA/FL2VA 提示词优化。"""

    def __init__(self):
        super().__init__("h3_prompt_optimize")

    async def execute(self, step: PipelineStep, ai_tool: AITool) -> Dict[str, Any]:
        params = step.get_params_dict()
        original = str(params.get("original_prompt") if params.get("original_prompt") is not None else (ai_tool.prompt or ""))
        variant = params.get("variant") or resolve_h3_prompt_variant(ai_tool) or H3_PROMPT_OPTIMIZE_VARIANT_I2VA
        try:
            duration = float(params.get("duration") if params.get("duration") is not None else (ai_tool.duration or 5))
        except (TypeError, ValueError):
            duration = 5.0

        optimized, fallback, error = await self._optimize(original, variant, duration)
        result_data = {
            "original_prompt": original,
            "optimized_prompt": optimized,
            "variant": variant,
            "fallback": fallback,
            "error": error,
        }
        # 直接写回，避免阶段完成先把任务打回 PENDING、apply_results 尚未执行就提交。
        try:
            from model import AIToolsModel
            AIToolsModel.update(
                ai_tool.id,
                prompt=optimized,
                extra_config=merge_h3_prompt_extra_config(
                    getattr(ai_tool, "extra_config", None),
                    original_prompt=original,
                    optimized_prompt=optimized,
                    variant=variant,
                    fallback=fallback,
                ),
            )
        except Exception as exc:
            self.logger.warning("Failed to persist H3 optimized prompt on ai_tool %s: %s", ai_tool.id, exc)
        return {
            "success": True,
            "result_data": result_data,
        }

    async def _optimize(self, original: str, variant: str, duration: float) -> Tuple[str, bool, Optional[str]]:
        last_error = None
        for _ in range(2):
            try:
                raw = await self._call_llm(original, variant, duration)
                cleaned = strip_prompt_fences(raw)
                if validate_h3_optimized_prompt(cleaned, variant):
                    return cleaned, False, None
                last_error = "optimized prompt failed structure check"
            except Exception as exc:
                last_error = str(exc)
                self.logger.warning("H3 prompt optimize attempt failed: %s", exc)
        self.logger.warning("H3 prompt optimize fallback to original: %s", last_error)
        return original, True, last_error

    async def _call_llm(self, original: str, variant: str, duration: float) -> str:
        from llm.llm_client_factory import get_llm_client

        model = str(get_dynamic_config_value(
            "pipeline", "h3_prompt_optimize_model", default=LLMModel.DEEPSEEK_V4_FLASH
        ) or LLMModel.DEEPSEEK_V4_FLASH).strip()
        vendor_raw = get_dynamic_config_value("pipeline", "h3_prompt_optimize_vendor_id", default=0)
        try:
            vendor_id = int(vendor_raw) if vendor_raw not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            vendor_id = None

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": build_h3_optimize_user_message(original, variant, duration)},
        ]
        llm_client = get_llm_client(model, vendor_id=vendor_id)

        def _invoke():
            return llm_client.call_api(
                model=model,
                messages=messages,
                temperature=H3_PROMPT_OPTIMIZE_TEMPERATURE,
                max_tokens=H3_PROMPT_OPTIMIZE_MAX_TOKENS,
            )

        response = await asyncio.wait_for(
            asyncio.to_thread(_invoke),
            timeout=H3_PROMPT_OPTIMIZE_TIMEOUT,
        )
        if not response or not getattr(response, "choices", None):
            raise RuntimeError("LLM returned empty response")
        content = response.choices[0].message.content
        if not content or not str(content).strip():
            raise RuntimeError("LLM returned empty content")
        return str(content)
