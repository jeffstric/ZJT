"""LLM 欠费熔断（_enforce_arrears_breaker）单元测试

背景：token 计费是后付费（task/token_task.py 扣减无下限），长任务可把余额
扣穿为负。熔断在每次付费 LLM 调用前检查余额，低于阈值拒绝发起调用。
"""
import pytest

from llm.base_llm_client import (
    BaseLLMClient,
    InsufficientPowerForLLMCallError,
)
import llm.base_llm_client as base_llm_client_module
from config.unified_config import LLM_ARREARS_BREAKER_THRESHOLD


class _DummyClient(BaseLLMClient):
    """仅用于测试熔断方法的最小实现"""

    def call_api(self, *args, **kwargs):  # pragma: no cover - 不会被调用
        raise NotImplementedError


@pytest.fixture
def client():
    return _DummyClient()


def _patch_check(monkeypatch, success, response_data, message=""):
    calls = []

    def fake_request(endpoint=None, data=None, method='POST', headers=None):
        calls.append(endpoint)
        return success, message, response_data

    monkeypatch.setattr(base_llm_client_module, "make_perseids_request", fake_request)
    return calls


def test_breaker_blocks_when_balance_below_threshold(client, monkeypatch):
    _patch_check(monkeypatch, True, {"computing_power": 0})
    with pytest.raises(InsufficientPowerForLLMCallError) as exc:
        client._enforce_arrears_breaker("token-1", vendor_id=7, model_id=1006)
    assert exc.value.computing_power == 0
    assert exc.value.threshold == LLM_ARREARS_BREAKER_THRESHOLD
    assert "算力不足" in str(exc.value)


def test_breaker_allows_when_balance_sufficient(client, monkeypatch):
    calls = _patch_check(monkeypatch, True, {"computing_power": 87})
    client._enforce_arrears_breaker("token-1", vendor_id=7, model_id=1006)
    assert calls == ["user/check_computing_power"]


def test_breaker_skips_without_auth_token(client, monkeypatch):
    calls = _patch_check(monkeypatch, True, {"computing_power": 0})
    client._enforce_arrears_breaker(None, vendor_id=7, model_id=1006)
    assert calls == []


def test_breaker_skips_without_billing_ids(client, monkeypatch):
    calls = _patch_check(monkeypatch, True, {"computing_power": 0})
    client._enforce_arrears_breaker("token-1", vendor_id=None, model_id=None)
    assert calls == []


def test_breaker_fails_open_on_check_error(client, monkeypatch):
    _patch_check(monkeypatch, False, {}, message="余额服务故障")
    client._enforce_arrears_breaker("token-1", vendor_id=7, model_id=1006)


def test_breaker_fails_open_on_exception(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(base_llm_client_module, "make_perseids_request", boom)
    client._enforce_arrears_breaker("token-1", vendor_id=7, model_id=1006)
