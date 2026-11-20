import json
from types import SimpleNamespace

import pytest

from llm.llm_client_factory import LLMClientFactory
from model.model import ModelModel
from model.vendor import VendorDAO
from model.vendor_model import VendorModelModel
from services.user_module_review_service import (
    SYSTEM_PROMPT,
    ReviewModelRouteError,
    UserModuleReviewService,
    resolve_strict_review_client,
)


def test_review_prompt_rejects_silent_runtime_failures():
    assert "UnboundLocalError" in SYSTEM_PROMPT
    assert "return_exceptions=True" in SYSTEM_PROMPT
    assert "DriverError" in SYSTEM_PROMPT
    assert "必须 reject" in SYSTEM_PROMPT


MODEL = "deepseek-v4-pro"
MODEL_ID = 12
VENDOR_ID = 7


def _patch_valid_route(monkeypatch, *, vendor_name="deepseek"):
    monkeypatch.setattr(
        ModelModel,
        "get_by_id",
        lambda requested_id: SimpleNamespace(
            id=requested_id,
            model_name=MODEL,
            enabled=1,
        ),
    )
    monkeypatch.setattr(
        VendorModelModel,
        "get_by_vendor_model",
        lambda requested_vendor_id, requested_model_id: SimpleNamespace(
            vendor_id=requested_vendor_id,
            model_id=requested_model_id,
        ),
    )
    monkeypatch.setattr(
        VendorDAO,
        "get_by_id",
        lambda requested_id: SimpleNamespace(
            id=requested_id,
            vendor_name=vendor_name,
        ),
    )


def _forbid_compatible_factory(monkeypatch):
    def forbidden(cls, *args, **kwargs):
        raise AssertionError("安全审核不得调用带回退逻辑的普通 LLM 工厂")

    monkeypatch.setattr(LLMClientFactory, "get_client", classmethod(forbidden))


def test_strict_review_resolver_uses_exact_vendor_and_never_compatible_factory(monkeypatch):
    _patch_valid_route(monkeypatch)
    _forbid_compatible_factory(monkeypatch)
    expected_client = object()
    monkeypatch.setitem(
        LLMClientFactory._VENDOR_CLIENT_MAP,
        "deepseek",
        lambda: expected_client,
    )

    client = resolve_strict_review_client(
        model=MODEL,
        model_id=MODEL_ID,
        vendor_id=VENDOR_ID,
    )

    assert client is expected_client


def test_strict_review_resolver_rejects_missing_vendor_without_fallback(monkeypatch):
    _patch_valid_route(monkeypatch)
    _forbid_compatible_factory(monkeypatch)
    monkeypatch.setattr(VendorDAO, "get_by_id", lambda _vendor_id: None)

    with pytest.raises(ReviewModelRouteError, match="供应商不存在"):
        resolve_strict_review_client(
            model=MODEL,
            model_id=MODEL_ID,
            vendor_id=VENDOR_ID,
        )


def test_strict_review_resolver_rejects_vendor_query_failure_without_fallback(monkeypatch):
    _patch_valid_route(monkeypatch)
    _forbid_compatible_factory(monkeypatch)

    def query_failed(_vendor_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(VendorDAO, "get_by_id", query_failed)

    with pytest.raises(ReviewModelRouteError, match="路由查询失败"):
        resolve_strict_review_client(
            model=MODEL,
            model_id=MODEL_ID,
            vendor_id=VENDOR_ID,
        )


def test_strict_review_resolver_rejects_unknown_vendor_name_without_gemini_fallback(monkeypatch):
    _patch_valid_route(monkeypatch, vendor_name="unknown-review-vendor")
    _forbid_compatible_factory(monkeypatch)

    with pytest.raises(ReviewModelRouteError, match="供应商类型不受支持"):
        resolve_strict_review_client(
            model=MODEL,
            model_id=MODEL_ID,
            vendor_id=VENDOR_ID,
        )


def test_strict_review_resolver_rejects_model_name_mismatch(monkeypatch):
    _patch_valid_route(monkeypatch)
    monkeypatch.setattr(
        ModelModel,
        "get_by_id",
        lambda requested_id: SimpleNamespace(
            id=requested_id,
            model_name="different-model",
            enabled=1,
        ),
    )

    with pytest.raises(ReviewModelRouteError, match="review_target 不一致"):
        resolve_strict_review_client(
            model=MODEL,
            model_id=MODEL_ID,
            vendor_id=VENDOR_ID,
        )


def test_strict_review_resolver_rejects_mismatched_vendor_model_relation(monkeypatch):
    _patch_valid_route(monkeypatch)
    monkeypatch.setattr(
        VendorModelModel,
        "get_by_vendor_model",
        lambda _vendor_id, _model_id: SimpleNamespace(
            vendor_id=VENDOR_ID + 1,
            model_id=MODEL_ID,
        ),
    )

    with pytest.raises(ReviewModelRouteError, match="供应商关联.*review_target 不一致"):
        resolve_strict_review_client(
            model=MODEL,
            model_id=MODEL_ID,
            vendor_id=VENDOR_ID,
        )


def test_review_service_uses_strict_resolver_with_complete_target(monkeypatch):
    seen = {}

    class FakeWorkspace:
        def prepare_review_snapshot(self, generation_id, *, max_code_chars):
            return {
                "manifest": {"module_id": "demo.strict-review"},
                "code": "class Driver:\n    pass\n",
            }

    class FakeClient:
        def call_api(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "verdict": "approve",
                                    "risk_level": "low",
                                    "summary": "未发现风险",
                                    "findings": [],
                                }
                            )
                        )
                    )
                ]
            )

    def fake_strict_resolver(*, model, model_id, vendor_id):
        seen.update(model=model, model_id=model_id, vendor_id=vendor_id)
        return FakeClient()

    monkeypatch.setattr(
        "services.user_module_review_service.resolve_strict_review_client",
        fake_strict_resolver,
    )

    report = UserModuleReviewService(FakeWorkspace()).review(
        "generation-1",
        model=MODEL,
        model_id=MODEL_ID,
        vendor_id=VENDOR_ID,
        auth_token="test-token",
    )

    assert seen == {"model": MODEL, "model_id": MODEL_ID, "vendor_id": VENDOR_ID}
    assert report["status"] == "completed"
    assert report["model"] == MODEL
