"""resolve_composite_model_ref 复合模型标识还原测试。

本地服务模型（ollama/vllm）经 /api/models 下发的 id 是 "vendor:模型名" 复合串
（见 llm_client_factory._get_available_models_sync），历史版本前端会把它当作
model_id 回传（事故见 docs/backend/incidents/2026-09-06-script-split-composite-model-id.md）。
解析按首个冒号拆分，vendor/model/vendor_model 任一缺失即拒绝猜测返回 (None, None)。
"""

from llm.llm_client_factory import resolve_composite_model_ref


class _FakeVendor:
    def __init__(self, vendor_id, vendor_name):
        self.id = vendor_id
        self.vendor_name = vendor_name


class _FakeModel:
    def __init__(self, model_id, model_name):
        self.id = model_id
        self.model_name = model_name


def _patch_dao(monkeypatch, vendor, local_model, association=True):
    monkeypatch.setattr(
        "model.vendor.VendorDAO.get_by_name",
        lambda name: vendor if (vendor and vendor.vendor_name == name) else None,
    )
    monkeypatch.setattr(
        "model.model.ModelModel.get_by_name",
        lambda name: local_model if (local_model and local_model.model_name == name) else None,
    )
    if association:
        monkeypatch.setattr(
            "model.vendor_model.VendorModelModel.get_by_vendor_model",
            lambda vendor_id, model_id: object(),
        )
    else:
        monkeypatch.setattr(
            "model.vendor_model.VendorModelModel.get_by_vendor_model",
            lambda vendor_id, model_id: None,
        )


def test_resolves_vllm_composite_ref(monkeypatch):
    _patch_dao(
        monkeypatch,
        vendor=_FakeVendor(9, "vllm"),
        local_model=_FakeModel(1011, "qwen3.8:27b"),
    )

    assert resolve_composite_model_ref("vllm:qwen3.8:27b") == (9, 1011)


def test_splits_on_first_colon_for_ollama_style_model_name(monkeypatch):
    # ollama 模型名自身带冒号，只能按首个冒号拆分 vendor 与模型名
    _patch_dao(
        monkeypatch,
        vendor=_FakeVendor(3, "ollama"),
        local_model=_FakeModel(1000, "qwen3.6:35b-a3b"),
    )

    assert resolve_composite_model_ref("ollama:qwen3.6:35b-a3b") == (3, 1000)


def test_non_composite_ref_is_rejected(monkeypatch):
    # 纯数字/普通模型名不含冒号，不属于复合标识，调用方应走原有 int() 路径
    assert resolve_composite_model_ref("1011") == (None, None)
    assert resolve_composite_model_ref("deepseek-v4-flash") == (None, None)
    assert resolve_composite_model_ref("") == (None, None)
    assert resolve_composite_model_ref(None) == (None, None)


def test_unknown_vendor_or_model_is_rejected(monkeypatch):
    _patch_dao(monkeypatch, vendor=None, local_model=None)

    assert resolve_composite_model_ref("vllm:qwen3.8:27b") == (None, None)


def test_missing_vendor_model_association_is_rejected(monkeypatch):
    _patch_dao(
        monkeypatch,
        vendor=_FakeVendor(9, "vllm"),
        local_model=_FakeModel(1011, "qwen3.8:27b"),
        association=False,
    )

    assert resolve_composite_model_ref("vllm:qwen3.8:27b") == (None, None)


def test_db_error_is_swallowed(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("model.vendor.VendorDAO.get_by_name", _boom)

    assert resolve_composite_model_ref("vllm:qwen3.8:27b") == (None, None)
