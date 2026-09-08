"""模型标识数值化 + 路由兜底测试。

/api/models 的 id 字段已统一为数值库 ID 字符串（不再对本地服务供应商下发
"vendor:模型名" 复合串，见 docs/backend/incidents/2026-09-06-script-split-
composite-model-id.md 的 2026-09-08 治理章节）。调用方不传 vendor_id 且模型名
无前缀时，get_client 按库反查 vendor_model 兜底路由。
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from llm import llm_client_factory as f
from llm.llm_client_factory import (
    LLMClientFactory,
    _get_available_models_sync,
)

get_client = LLMClientFactory.get_client


def _vendor(id, name):
    return SimpleNamespace(id=id, vendor_name=name)


def _model(id, name):
    return SimpleNamespace(
        id=id, model_name=name, supports_tools=1, enabled=1,
        context_window=8192, supports_thinking=0, supports_vl=0, note='',
    )


def _patch_models_env(monkeypatch, vendors, vendor_models, models_by_id):
    """mock 掉 _get_available_models_sync 的全部查库依赖"""
    monkeypatch.setattr(
        "model.vendor.VendorDAO.get_all", lambda: vendors
    )
    monkeypatch.setattr(
        "model.vendor_model.VendorModelModel.get_all", lambda: vendor_models
    )
    monkeypatch.setattr(
        "model.model.ModelModel.get_by_id",
        lambda model_id: models_by_id.get(model_id),
    )
    # get_dynamic_config_value 返回 truthy：所有 vendor 视为已配置
    monkeypatch.setattr(
        "config.config_util.get_dynamic_config_value",
        lambda *keys, default='': 'configured',
    )
    monkeypatch.setattr(
        "model.vendor_model.VendorModelModel.get_by_vendor_model_for_billing",
        lambda **kwargs: None,
    )


class TestAvailableModelsNumericId:
    def test_local_service_vendor_id_is_numeric_too(self, monkeypatch):
        """本地服务供应商（vllm）模型的 id 也不再是复合串，与云供应商统一为数值串"""
        _patch_models_env(
            monkeypatch,
            vendors=[_vendor(9, 'vllm')],
            vendor_models=[SimpleNamespace(model_id=1011, vendor_id=9)],
            models_by_id={1011: _model(1011, 'qwen3.8:27b')},
        )

        result = _get_available_models_sync()
        models = result['models']
        assert len(models) == 1
        assert models[0]['id'] == '1011'
        assert models[0]['model_id'] == 1011
        assert models[0]['vendor_id'] == 9
        # 复合串彻底消失
        assert ':' not in models[0]['id']

    def test_cloud_vendor_id_unchanged(self, monkeypatch):
        _patch_models_env(
            monkeypatch,
            vendors=[_vendor(2, 'deepseek')],
            vendor_models=[SimpleNamespace(model_id=5, vendor_id=2)],
            models_by_id={5: _model(5, 'deepseek-v4-flash')},
        )

        models = _get_available_models_sync()['models']
        assert models[0]['id'] == '5'


class TestVendorByModelDbFallback:
    def test_prefix_miss_falls_back_to_db_lookup(self, monkeypatch):
        """无前缀约定的模型名 + 调用方未传 vendor_id：按库反查 vendor_model 路由到 vllm 客户端"""
        monkeypatch.setattr(
            "model.model.ModelModel.get_by_name",
            lambda name: _model(1011, name) if name == 'my-private-model' else None,
        )
        monkeypatch.setattr(
            "model.vendor_model.VendorModelModel.get_vendor_id_by_model_id",
            lambda model_id: 9,
        )
        monkeypatch.setattr(
            "model.vendor.VendorDAO.get_by_id",
            lambda vendor_id: _vendor(9, 'vllm') if vendor_id == 9 else None,
        )

        client = get_client('my-private-model')
        assert type(client).__name__ == 'VLLMClient'

    def test_prefix_match_skips_db_lookup(self, monkeypatch):
        """有前缀约定的模型（deepseek 等）仍走前缀路由，不触发查库"""
        def _boom(*args, **kwargs):
            raise AssertionError('不应触发查库反查')
        monkeypatch.setattr("model.model.ModelModel.get_by_name", _boom)

        client = get_client('deepseek-v4-flash')
        assert type(client).__name__ == 'DeepSeekOpenAIClient'

    def test_db_lookup_failure_keeps_default_route(self, monkeypatch):
        """反查异常/未命中时保持历史默认路由（JIEKOU/gemini），不抛错"""
        monkeypatch.setattr(
            "model.model.ModelModel.get_by_name",
            lambda name: None,
        )

        client = get_client('totally-unknown-model')
        assert type(client).__name__ == 'GeminiClient'


class TestCompositeRefWarning:
    def test_composite_ref_hit_logs_warning(self, monkeypatch, caplog):
        """兼容层命中历史复合串时告警（观察存量清零进度）"""
        from llm.llm_client_factory import resolve_composite_model_ref

        monkeypatch.setattr(
            "model.vendor.VendorDAO.get_by_name",
            lambda name: _vendor(9, name),
        )
        monkeypatch.setattr(
            "model.model.ModelModel.get_by_name",
            lambda name: _model(1011, name),
        )
        monkeypatch.setattr(
            "model.vendor_model.VendorModelModel.get_by_vendor_model",
            lambda v, m: object(),
        )

        import logging
        with caplog.at_level(logging.WARNING, logger='llm.llm_client_factory'):
            resolve_composite_model_ref('vllm:qwen3.8:27b')
        assert any('复合串' in r.message for r in caplog.records)

    def test_non_composite_ref_no_warning(self, monkeypatch, caplog):
        from llm.llm_client_factory import resolve_composite_model_ref

        import logging
        with caplog.at_level(logging.WARNING, logger='llm.llm_client_factory'):
            assert resolve_composite_model_ref('1011') == (None, None)
        assert not any('复合串' in r.message for r in caplog.records)
