"""LLM 客户端安全审核日志隐私测试。"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from llm.base_llm_client import BaseLLMClient
from llm.gemini_client import GeminiClient
from llm.ollama_client import OllamaClient
from llm.openai_base_client import OpenAIBaseClient


REQUEST_SECRET = "AUDIT_SOURCE_SECRET_9f4c"
RESPONSE_SECRET = "AUDIT_RESPONSE_SECRET_73ba"
REASONING_SECRET = "AUDIT_REASONING_SECRET_d2e1"
TOOL_ARGUMENT_SECRET = "AUDIT_TOOL_ARGUMENT_SECRET_81c7"
ERROR_BODY_SECRET = "AUDIT_ERROR_BODY_SECRET_a6d3"


class _OpenAIClientForTest(OpenAIBaseClient):
    def _refresh_config(self):
        self.api_key = "sk-super-secret-test-key"
        self.base_url = "http://localhost:8080"
        self.vendor_name = "privacy-test"
        self.thinking_mode = None


def _logged_text(*mocks: MagicMock) -> str:
    return "\n".join(str(call) for mock in mocks for call in mock.mock_calls)


def _openai_completion():
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="audit_tool", arguments=TOOL_ARGUMENT_SECRET),
    )
    message = SimpleNamespace(
        content=RESPONSE_SECRET,
        reasoning_content=REASONING_SECRET,
        tool_calls=[tool_call],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=None,
    )


def _configure_ollama(client: OllamaClient) -> None:
    client.enabled = True
    client.base_url = "http://localhost:11434"
    client.temperature = 0.7
    client.top_p = 0.8
    client.top_k = 20
    client.min_p = 0.0
    client.presence_penalty = 1.5
    client.repetition_penalty = 1.0
    client.enable_thinking = False


def test_call_api_signatures_expose_backward_compatible_privacy_flag():
    for client_type in (BaseLLMClient, OpenAIBaseClient, GeminiClient, OllamaClient):
        parameter = inspect.signature(client_type.call_api).parameters["suppress_payload_logging"]
        assert parameter.default is False


def test_token_usage_error_details_are_suppressed_for_private_calls():
    app_logger = MagicMock()
    with (
        patch("llm.base_llm_client.logger", app_logger),
        patch(
            "llm.base_llm_client.make_perseids_request",
            return_value=(False, ERROR_BODY_SECRET, None),
        ),
    ):
        _OpenAIClientForTest()._log_token_usage(
            {"input_token": 1, "output_token": 1, "total_token": 2},
            "auth-token",
            1,
            1,
            suppress_error_details=True,
        )

    logged = _logged_text(app_logger)
    assert ERROR_BODY_SECRET not in logged
    assert "增加 token 日志失败" in logged


def test_openai_suppressed_logging_omits_payload_response_reasoning_and_tool_args():
    llm_logger = MagicMock()
    app_logger = MagicMock()
    sdk_client = MagicMock()
    sdk_client.chat.completions.create.return_value = _openai_completion()

    with (
        patch("llm.openai_base_client._get_llm_logger", return_value=llm_logger),
        patch("llm.openai_base_client.logger", app_logger),
        patch("llm.openai_base_client.OpenAI", return_value=sdk_client),
    ):
        _OpenAIClientForTest().call_api(
            "test-model",
            messages=[{"role": "user", "content": REQUEST_SECRET}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "audit_tool",
                    "description": REQUEST_SECRET,
                    "parameters": {"type": "object"},
                },
            }],
            suppress_payload_logging=True,
        )

    logged = _logged_text(llm_logger, app_logger)
    for secret in (REQUEST_SECRET, RESPONSE_SECRET, REASONING_SECRET, TOOL_ARGUMENT_SECRET):
        assert secret not in logged
    assert "API request payload" not in logged
    assert "Content length" in logged
    assert "Tool calls count" in logged


def test_openai_suppressed_logging_omits_exception_body():
    llm_logger = MagicMock()
    app_logger = MagicMock()
    sdk_client = MagicMock()
    sdk_client.chat.completions.create.side_effect = RuntimeError(ERROR_BODY_SECRET)

    with (
        patch("llm.openai_base_client._get_llm_logger", return_value=llm_logger),
        patch("llm.openai_base_client.logger", app_logger),
        patch("llm.openai_base_client.OpenAI", return_value=sdk_client),
        pytest.raises(RuntimeError),
    ):
        _OpenAIClientForTest().call_api(
            "test-model",
            messages=[{"role": "user", "content": REQUEST_SECRET}],
            suppress_payload_logging=True,
        )

    logged = _logged_text(llm_logger, app_logger)
    assert REQUEST_SECRET not in logged
    assert ERROR_BODY_SECRET not in logged
    assert "error_type=%s" in logged
    assert "RuntimeError" in logged


def test_ollama_suppressed_logging_omits_payload_response_reasoning_and_tool_args():
    llm_logger = MagicMock()
    app_logger = MagicMock()
    sdk_client = MagicMock()
    sdk_client.chat.completions.create.return_value = _openai_completion()

    with (
        patch.object(OllamaClient, "_refresh_config"),
        patch("llm.ollama_client._get_llm_logger", return_value=llm_logger),
        patch("llm.ollama_client.logger", app_logger),
        patch("llm.ollama_client.OpenAI", return_value=sdk_client),
    ):
        client = OllamaClient()
        _configure_ollama(client)
        client.call_api(
            "ollama:test-model",
            messages=[{"role": "user", "content": REQUEST_SECRET}],
            suppress_payload_logging=True,
        )

    logged = _logged_text(llm_logger, app_logger)
    for secret in (REQUEST_SECRET, RESPONSE_SECRET, REASONING_SECRET, TOOL_ARGUMENT_SECRET):
        assert secret not in logged
    assert "API request payload" not in logged
    assert "Content length" in logged


def test_ollama_suppressed_logging_omits_exception_body():
    llm_logger = MagicMock()
    app_logger = MagicMock()
    sdk_client = MagicMock()
    sdk_client.chat.completions.create.side_effect = RuntimeError(ERROR_BODY_SECRET)

    with (
        patch.object(OllamaClient, "_refresh_config"),
        patch("llm.ollama_client._get_llm_logger", return_value=llm_logger),
        patch("llm.ollama_client.logger", app_logger),
        patch("llm.ollama_client.OpenAI", return_value=sdk_client),
    ):
        client = OllamaClient()
        _configure_ollama(client)
        with pytest.raises(RuntimeError):
            client.call_api(
                "ollama:test-model",
                messages=[{"role": "user", "content": REQUEST_SECRET}],
                suppress_payload_logging=True,
            )

    logged = _logged_text(llm_logger, app_logger)
    assert REQUEST_SECRET not in logged
    assert ERROR_BODY_SECRET not in logged
    assert "error_type=%s" in logged
    assert "RuntimeError" in logged


def _gemini_response_json():
    return {
        "candidates": [{
            "content": {
                # 即使上游把密感文本塞进原本应为枚举的元数据字段，也不应记录。
                "role": REQUEST_SECRET,
                "parts": [
                    {"text": RESPONSE_SECRET},
                    {
                        "functionCall": {
                            "name": "audit_tool",
                            "args": {"secret": TOOL_ARGUMENT_SECRET},
                        },
                        "thoughtSignature": REASONING_SECRET,
                    },
                ],
            },
            "finishReason": REASONING_SECRET,
        }],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }


def test_gemini_suppressed_logging_omits_payload_response_tool_args_and_print():
    llm_logger = MagicMock()
    app_logger = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = _gemini_response_json()

    with (
        patch.object(GeminiClient, "_refresh_config"),
        patch.object(GeminiClient, "_build_url", return_value="http://localhost/generate"),
        patch("llm.gemini_client.llm_logger", llm_logger),
        patch("llm.gemini_client.logger", app_logger),
        patch("llm.gemini_client.requests.post", return_value=response),
        patch("builtins.print") as mock_print,
    ):
        client = GeminiClient()
        client.api_key = "gemini-super-secret-key"
        client.base_url = "http://localhost"
        client.call_api(
            "gemini-test",
            messages=[{"role": "user", "content": REQUEST_SECRET}],
            suppress_payload_logging=True,
        )

    logged = _logged_text(llm_logger, app_logger)
    for secret in (REQUEST_SECRET, RESPONSE_SECRET, REASONING_SECRET, TOOL_ARGUMENT_SECRET):
        assert secret not in logged
    assert "API request payload" not in logged
    assert "Part[0] (text" in logged
    mock_print.assert_not_called()


def test_gemini_suppressed_logging_omits_error_response_and_exception_body():
    llm_logger = MagicMock()
    app_logger = MagicMock()
    response = MagicMock(status_code=500)
    response.content = ERROR_BODY_SECRET.encode("utf-8")
    response.text = ERROR_BODY_SECRET
    response.raise_for_status.side_effect = RuntimeError(ERROR_BODY_SECRET)

    with (
        patch.object(GeminiClient, "_refresh_config"),
        patch.object(GeminiClient, "_build_url", return_value="http://localhost/generate"),
        patch("llm.gemini_client.llm_logger", llm_logger),
        patch("llm.gemini_client.logger", app_logger),
        patch("llm.gemini_client.requests.post", return_value=response),
    ):
        client = GeminiClient()
        client.api_key = "gemini-super-secret-key"
        client.base_url = "http://localhost"
        with pytest.raises(RuntimeError):
            client.call_api(
                "gemini-test",
                messages=[{"role": "user", "content": REQUEST_SECRET}],
                suppress_payload_logging=True,
            )

    logged = _logged_text(llm_logger, app_logger)
    assert REQUEST_SECRET not in logged
    assert ERROR_BODY_SECRET not in logged
    assert "body_length=" in logged
    assert "error_type=%s" in logged
    assert "RuntimeError" in logged
