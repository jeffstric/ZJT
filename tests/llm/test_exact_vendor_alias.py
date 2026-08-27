"""LLM 精确供应商路由的别名兼容测试。

历史数据中 Gemini 供应商（LLMVendor.JIEKOU）可能被命名为 google；
安全审核的 fail-closed 精确路由需要该别名才能命中 Gemini 客户端。
"""

from llm.llm_client_factory import LLMClientFactory
from config.constant import LLMVendor


def test_exact_vendor_route_accepts_google_alias():
    client = LLMClientFactory.get_client_for_exact_vendor("google")
    assert client is not None


def test_exact_vendor_route_accepts_canonical_names():
    client = LLMClientFactory.get_client_for_exact_vendor(LLMVendor.JIEKOU)
    assert client is not None


def test_exact_vendor_route_rejects_unknown_vendor():
    import pytest

    with pytest.raises(ValueError):
        LLMClientFactory.get_client_for_exact_vendor("unknown_vendor_x")
