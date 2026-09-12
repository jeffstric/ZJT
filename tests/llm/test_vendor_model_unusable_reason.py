"""get_vendor_model_unusable_reason 显式路由前置校验测试。

背景（2026-09-12 线上事故）：火山账号未开通 deepseek-v4-flash，但
vendor_model 关联存在，前端把该路由当正常选项下发；任务创建后 LLM 调用
404（InvalidEndpointOrModel.NotFound），PM 循环吞错重试后任务仍被标
completed。新增入口前置校验：vendor_model 关联缺失 / 供应商凭据未配置
时返回原因供接口 400，把失败挡在任务创建之前。
"""

from llm.llm_client_factory import get_vendor_model_unusable_reason


class _FakeVendor:
    def __init__(self, vendor_id, vendor_name):
        self.id = vendor_id
        self.vendor_name = vendor_name


def _patch_vendor(monkeypatch, vendor):
    monkeypatch.setattr(
        "model.vendor.VendorDAO.get_by_id",
        lambda vendor_id: vendor if (vendor and vendor.id == vendor_id) else None,
    )


def _patch_association(monkeypatch, exists=True):
    monkeypatch.setattr(
        "model.vendor_model.VendorModelModel.get_by_vendor_model",
        lambda vendor_id, model_id: object() if exists else None,
    )


def _patch_credential(monkeypatch, configured):
    monkeypatch.setattr(
        "llm.llm_client_factory.is_vendor_configured",
        lambda vendor_name: configured,
    )


class TestGetVendorModelUnusableReason:
    def test_usable_route_passes(self, monkeypatch):
        _patch_vendor(monkeypatch, _FakeVendor(7, "deepseek"))
        _patch_association(monkeypatch, exists=True)
        _patch_credential(monkeypatch, configured=True)
        assert get_vendor_model_unusable_reason(7, 1005) is None

    def test_unknown_vendor_rejected(self, monkeypatch):
        _patch_vendor(monkeypatch, None)
        reason = get_vendor_model_unusable_reason(99, 1005)
        assert reason is not None and "99" in reason

    def test_missing_association_rejected(self, monkeypatch):
        _patch_vendor(monkeypatch, _FakeVendor(4, "volcengine"))
        _patch_association(monkeypatch, exists=False)
        reason = get_vendor_model_unusable_reason(4, 1005)
        assert reason is not None and "volcengine" in reason

    def test_unconfigured_credential_rejected(self, monkeypatch):
        _patch_vendor(monkeypatch, _FakeVendor(4, "volcengine"))
        _patch_association(monkeypatch, exists=True)
        _patch_credential(monkeypatch, configured=False)
        reason = get_vendor_model_unusable_reason(4, 1005)
        assert reason is not None and "API Key" in reason

    def test_non_numeric_vendor_id_passes_through(self, monkeypatch):
        # 非数值 vendor_id 不是显式路由（入口归一化职责），放行不校验
        assert get_vendor_model_unusable_reason(None, 1005) is None
        assert get_vendor_model_unusable_reason("", 1005) is None

    def test_non_numeric_model_id_passes_through(self, monkeypatch):
        _patch_vendor(monkeypatch, _FakeVendor(7, "deepseek"))
        assert get_vendor_model_unusable_reason(7, None) is None

    def test_lookup_error_passes_through(self, monkeypatch):
        # 校验自身异常不阻塞任务创建（与工厂路由容错口径一致）
        def _boom(*args, **kwargs):
            raise RuntimeError("db down")
        monkeypatch.setattr("model.vendor.VendorDAO.get_by_id", _boom)
        assert get_vendor_model_unusable_reason(7, 1005) is None
