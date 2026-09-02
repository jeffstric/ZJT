"""内容审核错误友好提示工具单测（方案 A）。"""
from utils.content_moderation_error import (
    SOURCE_COPYRIGHT,
    SOURCE_GENERAL,
    SOURCE_OUTPUT,
    SOURCE_PROMPT,
    SOURCE_REFERENCE_IMAGE,
    build_user_error_from_api_error,
    classify_content_moderation,
    format_user_facing_moderation_error,
    is_content_moderation_user_message,
    rewrite_failure_reason_if_moderation,
    should_suggest_reduce_violation,
)


class TestGptImageModeration:
    def test_moderation_blocked_with_violence(self):
        info = classify_content_moderation(
            error_code="moderation_blocked",
            error_message=(
                "Your request was rejected by the safety system. "
                "safety_violations=[violence]. (request id: xxx)"
            ),
            error_type="image_generation_user_error",
        )
        assert info is not None
        assert info["source"] == SOURCE_GENERAL
        assert "violence" in info["violations"]
        assert "内容审核未通过" in info["friendly_message"]
        assert "暴力" in info["friendly_message"]

    def test_invalid_prompt_is_prompt_source(self):
        msg = format_user_facing_moderation_error(
            error_code="invalid_prompt",
            error_message="Your request was rejected by the safety system.",
            error_type="invalid_request_error",
        )
        assert msg is not None
        assert "提示词" in msg


class TestSeedreamModeration:
    def test_output_image_sensitive(self):
        msg = format_user_facing_moderation_error(
            error_code="OutputImageSensitiveContentDetected",
            error_message=(
                "The request failed because the output image may contain sensitive information."
            ),
        )
        assert msg is not None
        assert "生成结果" in msg or "敏感" in msg

    def test_input_image_sensitive(self):
        info = classify_content_moderation(
            error_code="InputImageSensitiveContentDetected",
            error_message="input image sensitive",
        )
        assert info is not None
        assert info["source"] == SOURCE_REFERENCE_IMAGE
        assert "参考图" in info["friendly_message"]

    def test_input_text_sensitive(self):
        info = classify_content_moderation(
            error_code="InputTextSensitiveContentDetected",
            error_message="input text sensitive",
        )
        assert info is not None
        assert info["source"] == SOURCE_PROMPT


class TestGeminiCustomerLogPatterns:
    def test_image_safety(self):
        msg = format_user_facing_moderation_error(
            error_code="channel:image_generation_failed",
            error_message=(
                "Gemini image generation blocked [IMAGE_SAFETY]: "
                "The generated image was blocked due to safety policy violation, "
                "please modify your prompt and try again (request id: xxx)"
            ),
            error_type="channel_error",
        )
        assert msg is not None
        assert msg.startswith("内容审核未通过")
        assert "生成结果" in msg or "安全" in msg

    def test_image_other_copyright(self):
        msg = format_user_facing_moderation_error(
            error_code="channel:image_generation_failed",
            error_message=(
                "Gemini image generation blocked [IMAGE_OTHER]: "
                "Image generation was stopped, often related to copyright or trademark concerns, "
                "please modify your prompt and try again (request id: xxx)"
            ),
            error_type="channel_error",
        )
        assert msg is not None
        assert "版权" in msg or "商标" in msg

    def test_image_prohibited_content(self):
        msg = format_user_facing_moderation_error(
            error_code="channel:image_generation_failed",
            error_message=(
                "Gemini image generation blocked [IMAGE_PROHIBITED_CONTENT]: "
                "The generated image contains prohibited content, "
                "please modify your prompt and try again (request id: xxx)"
            ),
            error_type="channel_error",
        )
        assert msg is not None
        assert "内容审核未通过" in msg

    def test_rewrite_gemini_raw_string(self):
        raw = (
            "任务提交失败: Gemini image generation blocked [IMAGE_SAFETY]: "
            "The generated image was blocked due to safety policy violation, "
            "please modify your prompt and try again (request id: 20260715174822474801412n1qjkk7s)"
        )
        rewritten = rewrite_failure_reason_if_moderation(raw)
        assert rewritten.startswith("内容审核未通过")


class TestDuomiAndGrokLogPatterns:
    """2026-08-01 ~ 2026-08-30 /nas/tmp/api_request_log/ 真实失败样本补充。"""

    def test_grok_content_security_audit(self):
        """Grok 渠道主违规话术（30 天 5000+ 次）。"""
        info = classify_content_moderation(
            error_message="Content security audit did not pass | 内容安全审查未通过",
        )
        assert info is not None
        assert info["source"] == SOURCE_GENERAL
        assert "内容审核未通过" in info["friendly_message"]

    def test_grok_english_only_content_security(self):
        """仅英文时（无中文话术）也应识别。"""
        info = classify_content_moderation(
            error_message="Content security audit did not pass",
        )
        assert info is not None

    def test_gemini_sensitive_words_detected(self):
        """duomi gemini 违禁词拒绝。"""
        info = classify_content_moderation(
            error_message="任务执行失败: sensitive_words_detected",
        )
        assert info is not None
        assert info["source"] == SOURCE_PROMPT
        assert "提示词" in info["friendly_message"]

    def test_gemini_generated_images_unsafe(self):
        """duomi gemini 输出侧 unsafe 拒绝。"""
        info = classify_content_moderation(
            error_message=(
                "The generated images appear to be unsafe. "
                "Try modifying the prompts or the seeds."
            ),
        )
        assert info is not None
        assert info["source"] == SOURCE_OUTPUT
        assert "生成结果" in info["friendly_message"]

    def test_gemini_prompt_considered_unsafe(self):
        """duomi gemini 提示词侧 unsafe 拒绝。"""
        info = classify_content_moderation(
            error_message=(
                "The provided prompt is considered unsafe and "
                "it cannot be used to generate content."
            ),
        )
        assert info is not None
        assert info["source"] == SOURCE_PROMPT
        assert "提示词" in info["friendly_message"]

    def test_gemini_blocked_candidate_stopped(self):
        """duomi gemini finish_reason:STOP 拦截。"""
        info = classify_content_moderation(
            error_message=(
                "任务执行失败: gemini blocked: finish_reason:STOP "
                "(candidate stopped before producing an image)"
            ),
        )
        assert info is not None
        assert info["source"] == SOURCE_PROMPT
        assert "提示词" in info["friendly_message"]

    def test_non_moderation_errors_unchanged(self):
        """繁忙/限额/基础设施类失败不得误判为内容审核。"""
        for raw in (
            "AI服务繁忙，请稍后重试",
            "抱歉，系统繁忙，请稍后重试",
            "图片大小超过 10MB",
            "Total reference images and elements cannot exceed 4, got 5.",
            "模型 grok-video-channel 并发上限(10)已达，请等待其他任务完成后重试",
            "无可用渠道",
            "APIKEY_TASK_NOT_FOUND",
            "The model load is too high, please try again later",
            "未知原因,可能是当前官方算力问题",
        ):
            assert rewrite_failure_reason_if_moderation(raw) == raw, raw


class TestRewriteAndBuild:
    def test_rewrite_raw_english_reason(self):
        raw = (
            "任务提交失败: Your request was rejected by the safety system. "
            "safety_violations=[violence]. (request id: 20260715212753274771513fAg1k3QO)"
        )
        rewritten = rewrite_failure_reason_if_moderation(raw)
        assert rewritten.startswith("内容审核未通过")
        assert "暴力" in rewritten

    def test_rewrite_api_error_bracket_code(self):
        raw = (
            "API 错误 [OutputImageSensitiveContentDetected]: "
            "The request failed because the output image may contain sensitive information."
        )
        rewritten = rewrite_failure_reason_if_moderation(raw)
        assert rewritten.startswith("内容审核未通过")

    def test_non_moderation_unchanged(self):
        raw = "网络连接异常，请稍后重试"
        assert rewrite_failure_reason_if_moderation(raw) == raw

    def test_build_from_error_dict(self):
        text = build_user_error_from_api_error(
            {
                "message": "Your request was rejected by the safety system. safety_violations=[sexual].",
                "type": "image_generation_user_error",
                "code": "moderation_blocked",
            }
        )
        assert "内容审核未通过" in text
        assert "色情" in text

    def test_build_non_moderation_keeps_prefix(self):
        text = build_user_error_from_api_error(
            {"message": "rate limit exceeded", "code": "rate_limit"},
            fallback_prefix="任务提交失败",
        )
        assert text.startswith("任务提交失败")

    def test_already_friendly_not_double_wrapped(self):
        friendly = "内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试"
        assert rewrite_failure_reason_if_moderation(friendly) == friendly
        assert is_content_moderation_user_message(friendly)

    def test_output_source_classification(self):
        info = classify_content_moderation(
            error_code="OutputImageSensitiveContentDetected",
            error_message="The request failed because the output image may contain sensitive information.",
        )
        assert info["source"] == SOURCE_OUTPUT


class TestReduceViolationHint:
    def test_prompt_suggests(self):
        assert should_suggest_reduce_violation(source=SOURCE_PROMPT) is True

    def test_reference_image_does_not(self):
        assert should_suggest_reduce_violation(source=SOURCE_REFERENCE_IMAGE) is False

    def test_message_reference_image(self):
        assert should_suggest_reduce_violation(
            message="内容审核未通过：参考图片包含敏感内容，请更换参考图后重试"
        ) is False
