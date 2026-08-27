"""
MiniMax H3 提示词优化 Pipeline 驱动。

在正式提交 RunningHub 前，把用户原文改写成 I2VA / FL2VA / Ref2VA 规范。
直接完成步骤，不创建 async_task；LLM 失败时回退原文，不阻断出片。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

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
    "You rewrite MiniMax H3 video prompts. Write the final prompt in English, except "
    "dialogue, lyrics inside <d>, and visible on-screen text: those must stay in their "
    "original language verbatim with an accurate language tag (e.g. [Chinese]) — never "
    "translate them. Do not add explanations or markdown fences."
)


class H3PromptOptimizePipelineDriver(BasePipelineDriver):
    """MiniMax H3 I2VA/FL2VA/Ref2VA 提示词优化。"""

    def __init__(self):
        super().__init__("h3_prompt_optimize")

    async def execute(self, step: PipelineStep, ai_tool: AITool) -> Dict[str, Any]:
        params = step.get_params_dict()
        original = str(params.get("original_prompt") if params.get("original_prompt") is not None else (ai_tool.prompt or ""))
        variant = params.get("variant")
        if not variant:
            # 兼容无 variant 的旧步骤：按任务类型兜底判定（参考生视频 → Ref2VA）
            task_key = None
            ai_tool_type = getattr(ai_tool, "type", None)
            if ai_tool_type:
                from config.unified_config import UnifiedConfigRegistry
                _cfg = UnifiedConfigRegistry.get_by_id(ai_tool_type)
                task_key = _cfg.key if _cfg else None
            variant = resolve_h3_prompt_variant(ai_tool, task_key=task_key) or H3_PROMPT_OPTIMIZE_VARIANT_I2VA
        try:
            duration = float(params.get("duration") if params.get("duration") is not None else (ai_tool.duration or 5))
        except (TypeError, ValueError):
            duration = 5.0

        optimized, fallback, error = await self._optimize(original, variant, duration, params)
        result_data = {
            "original_prompt": original,
            "optimized_prompt": optimized,
            "variant": variant,
            "fallback": fallback,
            "error": error,
        }
        # 直接写回，避免阶段完成先把任务打回 PENDING、apply_results 尚未执行就提交。
        # 同步写库放线程池执行，避免阻塞事件循环
        try:
            from model import AIToolsModel
            extra = merge_h3_prompt_extra_config(
                getattr(ai_tool, "extra_config", None),
                original_prompt=original,
                optimized_prompt=optimized,
                variant=variant,
                fallback=fallback,
            )
            await asyncio.to_thread(
                AIToolsModel.update,
                ai_tool.id,
                prompt=optimized,
                extra_config=extra,
            )
        except Exception as exc:
            self.logger.warning("Failed to persist H3 optimized prompt on ai_tool %s: %s", ai_tool.id, exc)
        return {
            "success": True,
            "result_data": result_data,
        }

    async def _optimize(self, original: str, variant: str, duration: float, step_params: Dict[str, Any]) -> Tuple[str, bool, Optional[str]]:
        last_error = None
        for _ in range(2):
            try:
                raw = await self._call_llm(original, variant, duration, step_params)
                cleaned = strip_prompt_fences(raw)
                if validate_h3_optimized_prompt(cleaned, variant):
                    return cleaned, False, None
                last_error = "optimized prompt failed structure check"
            except Exception as exc:
                last_error = str(exc)
                self.logger.warning("H3 prompt optimize attempt failed: %s", exc)
        self.logger.warning("H3 prompt optimize fallback to original: %s", last_error)
        return original, True, last_error

    async def _call_llm(self, original: str, variant: str, duration: float, step_params: Dict[str, Any]) -> str:
        # 模型解析内部有同步查库（get_dynamic_config_value / VendorDAO.get_by_id），
        # 放线程池执行，避免阻塞事件循环
        model, vendor_id = await asyncio.to_thread(self.resolve_h3_optimize_model, step_params)
        if not model:
            # 所有候选模型均未配置 api_key：直接抛错，由 _optimize 回退原文，避免必败空跑。
            raise RuntimeError("no llm configured for H3 prompt optimize (all candidates missing api_key)")

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": build_h3_optimize_user_message(
                original, variant, duration, ref_counts=step_params.get("ref_counts")
            )},
        ]

        def _invoke():
            # get_llm_client 内含同步查库（vendor_id 路由），与 LLM 调用同在 worker 线程执行
            from llm.llm_client_factory import get_llm_client
            llm_client = get_llm_client(model, vendor_id=vendor_id)
            # request_timeout 与外层 wait_for 对齐，避免超时后底层 httpx 线程残留空跑。
            return llm_client.call_api(
                model=model,
                messages=messages,
                temperature=H3_PROMPT_OPTIMIZE_TEMPERATURE,
                max_tokens=H3_PROMPT_OPTIMIZE_MAX_TOKENS,
                request_timeout=H3_PROMPT_OPTIMIZE_TIMEOUT,
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

    @staticmethod
    def resolve_h3_optimize_model(step_params: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[int]]:
        """按优先级返回首个已配置密钥的 (model, vendor_id)，全未配置返回 (None, None)。

        优先级：
          1. step.params.chat_model + chat_vendor_id（storyboard 用户在该故事板选的对话模型）
          2. pipeline.h3_prompt_optimize_model + h3_prompt_optimize_vendor_id（全局配置，默认 DeepSeek）
          3. JIEKOU 在线模型 gemini-3.5-flash（最终兜底，走 JIEKOU/google key；
             原第三级为剧本拆分默认模型，2026-08 该默认切 deepseek-v4-flash 后与第 2 级重复、
             会被 seen 去重失效，故改独立在线模型保留"deepseek 未配置时仍有可用 LLM"的兜底能力）

        每步用 is_llm_client_configured 校验 api_key，避免对未配置供应商发起必败调用。
        """
        from llm.llm_client_factory import get_llm_client, is_llm_client_configured

        candidates: List[Tuple[Optional[str], Optional[int]]] = []

        # 1. storyboard 用户个性化选择
        chat_model = str((step_params or {}).get("chat_model") or "").strip()
        if chat_model:
            raw_vid = (step_params or {}).get("chat_vendor_id")
            try:
                chat_vid = int(raw_vid) if raw_vid not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                chat_vid = None
            candidates.append((chat_model, chat_vid))

        # 2. pipeline 全局配置
        cfg_model = str(get_dynamic_config_value(
            "pipeline", "h3_prompt_optimize_model", default=LLMModel.DEEPSEEK_V4_FLASH
        ) or LLMModel.DEEPSEEK_V4_FLASH).strip()
        cfg_vendor_raw = get_dynamic_config_value("pipeline", "h3_prompt_optimize_vendor_id", default=0)
        try:
            cfg_vendor_id = int(cfg_vendor_raw) if cfg_vendor_raw not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            cfg_vendor_id = None
        candidates.append((cfg_model, cfg_vendor_id))

        # 3. JIEKOU 在线模型最终兜底（见 docstring：不能复用剧本拆分默认模型，会与第 2 级去重）
        candidates.append((LLMModel.GEMINI_3_5_FLASH, None))

        seen = set()
        for cand_model, cand_vendor_id in candidates:
            if not cand_model or cand_model in seen:
                continue
            seen.add(cand_model)
            try:
                if is_llm_client_configured(get_llm_client(cand_model, vendor_id=cand_vendor_id)):
                    return cand_model, cand_vendor_id
            except Exception:
                continue
        return None, None
