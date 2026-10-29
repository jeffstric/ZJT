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
    H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
    H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
    LLMModel,
)
from model import AITool, PipelineStep
from task.pipeline_drivers.base_pipeline_driver import BasePipelineDriver
from task.pipeline_drivers.h3_prompt_optimize_util import (
    build_h3_optimize_user_content,
    collect_h3_optimize_image_data_urls,
    has_quoted_dialogue,
    merge_h3_prompt_extra_config,
    parse_h3_optimize_kfref_output,
    resolve_h3_prompt_variant,
    strip_leading_json_object,
    strip_prompt_fences,
    validate_h3_optimized_prompt,
)

_SYSTEM_PROMPT = (
    "You rewrite MiniMax H3 video prompts. Write the final prompt in English, except "
    "dialogue and lyrics inside <d> and visible on-screen text: those must stay in "
    "their original language verbatim — never translate them. <d> holds only content "
    "that is actually spoken or sung; visible on-screen text (signs, backdrops, "
    "banners, subtitles) is quoted in English double quotes inside the description, "
    "never inside <d>. Do not add explanations or markdown fences."
)


def _model_supports_vl(model_name: str) -> bool:
    """model 表是否标记为视觉模型（supports_vl=1 且 enabled=1）。

    多模态调用的候选过滤：把图片发给纯文本模型会 400 或被静默忽略
    （图片丢失后 LLM 继续凭文字臆测外观，等于白改）。查库失败按 False
    处理——宁可退纯文本，不把图发给能力未知的模型。
    """
    try:
        from model.model import ModelModel
        record = ModelModel.get_by_name(model_name)
        return bool(record and int(getattr(record, "supports_vl", 0) or 0) == 1)
    except Exception:
        return False


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

        # 收集参考图（本地映射 + 压缩为 base64；同步 IO 放线程池）。任一张失败
        # 整体返回 []，回退纯文本优化（现状行为），不阻断出片。
        image_data_urls = await asyncio.to_thread(
            collect_h3_optimize_image_data_urls, ai_tool, variant
        )
        if image_data_urls:
            self.logger.info(
                "H3 prompt optimize injecting %d reference image(s) for ai_tool %s",
                len(image_data_urls), getattr(ai_tool, "id", "?"),
            )

        optimized, fallback, error, dialogue_flag = await self._optimize(
            original, variant, duration, params, image_data_urls
        )
        result_data = {
            "original_prompt": original,
            "optimized_prompt": optimized,
            "variant": variant,
            "fallback": fallback,
            "has_dialogue": dialogue_flag,
            "used_reference_images": len(image_data_urls),
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
                has_dialogue=dialogue_flag,
                used_reference_images=len(image_data_urls),
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

    async def _optimize(
        self,
        original: str,
        variant: str,
        duration: float,
        step_params: Dict[str, Any],
        image_data_urls: Optional[List[str]] = None,
    ) -> Tuple[str, bool, Optional[str], Optional[bool]]:
        """返回 (optimized, fallback, error, has_dialogue)。

        KFRef 与 Ref2VA 走首行 JSON 头协议：台词有无由 LLM 语义判断并随输出
        返回（引号正则会把背景板文字等可见文字误判成台词，语义判断才能区分，
        dev3 案例 ai_tool 1815）。判无台词时开 forbid_audio_refs /
        forbid_dialogue（结果不得出现任何 <audio 引用与 <d> 台词）：无对白
        镜头的音频会被上游拒绝（「无法识别的说话内容」）或当成成片声音，
        幻觉台词会让角色凭空开口说话。
        其余变体（I2VA/FL2VA）维持纯文本输出，has_dialogue 恒为 None，
        无台词判定回退原文正则。
        """
        uses_dialogue_header = variant in (
            H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
            H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
        )
        last_error = None
        # 语义判断与文本优化解耦：结构校验失败回退原文时，JSON 头里已解析出的
        # has_dialogue 保留返回（驱动据此清音频），否则回退场景会丢掉语义判断、
        # 落回正则兜底被可见文字误判（dev3 案例 ai_tool 1816）。
        last_flag: Optional[bool] = None
        for _ in range(2):
            try:
                raw = await self._call_llm(original, variant, duration, step_params, image_data_urls)
                has_dialogue: Optional[bool] = None
                if uses_dialogue_header:
                    cleaned, has_dialogue = parse_h3_optimize_kfref_output(raw)
                    if cleaned is None:
                        last_error = "output missing dialogue header"
                        continue
                else:
                    # I2VA/FL2VA 无 JSON 头协议，防御性剥离模型偶发自发的
                    # 判断性 JSON 前缀（Ref2VA/KFRef 的首行 JSON 头走上方正规解析）
                    cleaned = strip_leading_json_object(strip_prompt_fences(raw))
                if isinstance(has_dialogue, bool):
                    last_flag = has_dialogue
                # 无台词判定：LLM 语义标记优先（KFRef/Ref2VA），I2VA/FL2VA 与
                # 头缺失场景用原文正则兜底（正则已排除背景板等可见文字形态）。
                no_dialogue = (
                    (has_dialogue is False)
                    if isinstance(has_dialogue, bool)
                    else not has_quoted_dialogue(original)
                )
                if validate_h3_optimized_prompt(
                    cleaned,
                    variant,
                    keyframe_slots=step_params.get("keyframe_slots"),
                    duration=duration,
                    forbid_audio_refs=no_dialogue,
                    forbid_dialogue=no_dialogue,
                ):
                    return cleaned, False, None, has_dialogue
                last_error = "optimized prompt failed structure check"
            except Exception as exc:
                last_error = str(exc)
                self.logger.warning("H3 prompt optimize attempt failed: %s", exc)
        self.logger.warning("H3 prompt optimize fallback to original: %s", last_error)
        return original, True, last_error, last_flag

    async def _call_llm(
        self,
        original: str,
        variant: str,
        duration: float,
        step_params: Dict[str, Any],
        image_data_urls: Optional[List[str]] = None,
    ) -> str:
        images = [str(url) for url in (image_data_urls or []) if url]
        # 模型解析内部有同步查库（get_dynamic_config_value / VendorDAO.get_by_id），
        # 放线程池执行，避免阻塞事件循环。有图时先按 VL 能力过滤（supports_vl=1），
        # 无可用 VL 模型再按原口径解析并丢弃图片退纯文本——未跑 no_159 迁移的
        # 环境行为与现状一致。
        model, vendor_id = await asyncio.to_thread(
            self.resolve_h3_optimize_model, step_params, bool(images)
        )
        if not model and images:
            images = []
            model, vendor_id = await asyncio.to_thread(
                self.resolve_h3_optimize_model, step_params, False
            )
        if not model:
            # 所有候选模型均未配置 api_key：直接抛错，由 _optimize 回退原文，避免必败空跑。
            raise RuntimeError("no llm configured for H3 prompt optimize (all candidates missing api_key)")

        system_prompt = _SYSTEM_PROMPT
        if variant in (H3_PROMPT_OPTIMIZE_VARIANT_KF_REF, H3_PROMPT_OPTIMIZE_VARIANT_REF2VA):
            # KFRef/Ref2VA 输出协议：首行 JSON 头（台词语义判断）+ 原样正文，代码强校验格式
            system_prompt = (
                _SYSTEM_PROMPT
                + " Your first output line must be exactly "
                '{\\"has_dialogue\\": true} or {\\"has_dialogue\\": false} — '
                "true only if the source prompt explicitly contains lines spoken or sung "
                "by a character — visible on-screen text (signs, backdrops, banners) does "
                "not count — followed by one blank line, then the final prompt."
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_h3_optimize_user_content(
                original,
                variant,
                duration,
                ref_counts=step_params.get("ref_counts"),
                keyframe_slots=step_params.get("keyframe_slots"),
                image_prompt_note=str(step_params.get("image_prompt_note") or ""),
                image_data_urls=images,
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
    def resolve_h3_optimize_model(
        step_params: Optional[Dict[str, Any]], require_vl: bool = False
    ) -> Tuple[Optional[str], Optional[int]]:
        """按优先级返回首个已配置密钥的 (model, vendor_id)，全未配置返回 (None, None)。

        优先级：
          1. step.params.chat_model + chat_vendor_id（storyboard 用户在该故事板选的对话模型）
          2. pipeline.h3_prompt_optimize_model + h3_prompt_optimize_vendor_id（全局配置，默认 DeepSeek）
          3. JIEKOU 在线模型 gemini-3.5-flash（最终兜底，走 JIEKOU/google key；
             原第三级为剧本拆分默认模型，2026-08 该默认切 deepseek-v4-flash 后与第 2 级重复、
             会被 seen 去重失效，故改独立在线模型保留"deepseek 未配置时仍有可用 LLM"的兜底能力）

        每步用 is_llm_client_configured 校验 api_key，避免对未配置供应商发起必败调用。
        require_vl=True 时额外要求 model 表 supports_vl=1 且启用（no_159 迁移把
        deepseek-v4-flash 置为 VL）：多模态调用防止把图片发给纯文本模型
        （400 或静默忽略图片继续臆测）。纯文本口径（require_vl=False）优先级不变。
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
                if require_vl and not _model_supports_vl(cand_model):
                    continue
                if is_llm_client_configured(get_llm_client(cand_model, vendor_id=cand_vendor_id)):
                    return cand_model, cand_vendor_id
            except Exception:
                continue
        return None, None
