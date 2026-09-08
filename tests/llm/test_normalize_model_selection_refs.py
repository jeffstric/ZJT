"""normalize_model_selection_refs / coerce_model_id_or_none 归一化测试。

统一各入口的 model_id/vendor_id 归一化规则（2026-09-08 收敛，背景见
docs/backend/incidents/2026-09-06-script-split-composite-model-id.md）：
vendor 优先级 = 显式非默认 vendor > 复合串 vendor > 数值模型反查 > 默认值。
"""
import pytest

from llm.llm_client_factory import (
    coerce_model_id_or_none,
    normalize_model_selection_refs,
    resolve_composite_model_ref,
)


def _patch_composite(monkeypatch, vendor_id, model_id):
    monkeypatch.setattr(
        "llm.llm_client_factory.resolve_composite_model_ref",
        lambda ref: (vendor_id, model_id),
    )


def _patch_vendor_lookup(monkeypatch, vendor_id):
    monkeypatch.setattr(
        "model.vendor_model.VendorModelModel.get_vendor_id_by_model_id",
        lambda model_id: vendor_id,
    )


class TestNormalizeModelSelectionRefs:
    def test_numeric_ids_passthrough(self, monkeypatch):
        _patch_vendor_lookup(monkeypatch, 7)
        assert normalize_model_selection_refs(1011, 5) == (1011, 5)

    def test_numeric_string_coerced(self, monkeypatch):
        _patch_vendor_lookup(monkeypatch, 7)
        assert normalize_model_selection_refs("1011", "5") == (1011, 5)

    def test_composite_model_resolves(self, monkeypatch):
        _patch_composite(monkeypatch, 9, 1011)
        assert normalize_model_selection_refs("vllm:qwen3.8:27b", None) == (1011, 9)

    def test_composite_vendor_overrides_default_sentinel(self, monkeypatch):
        # 前端显式回传 vendor_id=1（默认值/未选择）+ 复合串：用复合串 vendor 修正
        # ——旧发布拆分入口的 falsy 判断在此场景不会修正（行为分叉根因）
        _patch_composite(monkeypatch, 9, 1011)
        assert normalize_model_selection_refs("vllm:qwen3.8:27b", 1) == (1011, 9)

    def test_explicit_non_default_vendor_kept_over_composite(self, monkeypatch):
        # 用户显式选择了非默认供应商：不覆盖（与两处旧入口行为一致）
        _patch_composite(monkeypatch, 9, 1011)
        assert normalize_model_selection_refs("vllm:qwen3.8:27b", 5) == (1011, 5)

    def test_default_vendor_corrected_from_model_lookup(self, monkeypatch):
        # vendor 未传：按数值模型反查修正（对应旧 parse-script 的 ==1 分支）
        _patch_vendor_lookup(monkeypatch, 9)
        assert normalize_model_selection_refs(1011, None) == (1011, 9)

    def test_invalid_vendor_falls_back_to_model_lookup(self, monkeypatch):
        _patch_vendor_lookup(monkeypatch, 7)
        assert normalize_model_selection_refs(1011, "abc") == (1011, 7)

    def test_unresolvable_composite_falls_back_to_default(self, monkeypatch):
        _patch_composite(monkeypatch, None, None)
        assert normalize_model_selection_refs("vllm:gone", None) == (None, 1)

    def test_all_missing_returns_defaults(self):
        assert normalize_model_selection_refs(None, None) == (None, 1)
        assert normalize_model_selection_refs("", "") == (None, 1)

    def test_vendor_lookup_db_error_uses_default(self, monkeypatch):
        def _boom(model_id):
            raise RuntimeError("db down")
        monkeypatch.setattr(
            "model.vendor_model.VendorModelModel.get_vendor_id_by_model_id", _boom
        )
        assert normalize_model_selection_refs(1011, None) == (1011, 1)


class TestCoerceModelIdOrNone:
    def test_numeric_values(self):
        assert coerce_model_id_or_none(1011) == 1011
        assert coerce_model_id_or_none("1011") == 1011

    def test_empty_returns_none(self):
        assert coerce_model_id_or_none(None) is None
        assert coerce_model_id_or_none("") is None

    def test_composite_resolves(self, monkeypatch):
        _patch_composite(monkeypatch, 9, 1011)
        assert coerce_model_id_or_none("vllm:qwen3.8:27b") == 1011

    def test_garbage_returns_none_without_raising(self, monkeypatch):
        # 裸 int() 在此输入会 ValueError 使接口 500；宽容归一返回 None
        monkeypatch.setattr(
            "llm.llm_client_factory.resolve_composite_model_ref",
            lambda ref: (None, None),
        )
        assert coerce_model_id_or_none("not-a-model") is None
