"""LLM 客户端工厂：vllm:/ollama: 显式前缀优先于 vendor_id 的防御层测试。

事故 2026-09-04（docs/backend/incidents/2026-09-04-session-vendor-id.md）：
用户运行中把模型切到 vllm:qwen3.8:27b，运行中任务的 vendor_id 仍是旧
DeepSeek 厂商；当年写法 vendor_id 优先于前缀路由 → 本地模型名被透传给
DeepSeek API → 持续 400，连续 3 次失败后任务停止。

修复：get_client 检测 "vendor:模型名" 显式本地前缀（vllm:/ollama:），与
vendor_id 解析结果冲突时按前缀路由到本地服务并告警。注意 vendor_id 优先
语义不能整体取消（zjt_api 的 qwen3.5/3.6 依赖 vendor_id 区分），不冲突时
vendor_id 仍生效——本文件两条用例分别锁定。
"""

import os

os.environ.setdefault("comfyui_env", "unit")

from types import SimpleNamespace

from config.constant import LLMVendor
from llm.llm_client_factory import LLMClientFactory


class _StubClient:
    def __init__(self, tag):
        self.tag = tag


def _patch_vendor_lookup(monkeypatch, vendor_name):
    """把 VendorDAO.get_by_id 指向固定 vendor，模拟运行中任务的旧厂商。"""
    monkeypatch.setattr(
        "model.vendor.VendorDAO.get_by_id",
        lambda vendor_id: SimpleNamespace(vendor_name=vendor_name),
    )


def _patch_client_map(monkeypatch, vllm_client, deepseek_client):
    """覆盖 MAP 中两个供应商的 getter，避免真实客户端读配置。"""
    monkeypatch.setitem(LLMClientFactory._VENDOR_CLIENT_MAP, LLMVendor.VLLM, lambda: vllm_client)
    monkeypatch.setitem(LLMClientFactory._VENDOR_CLIENT_MAP, LLMVendor.DEEPSEEK, lambda: deepseek_client)


def test_vllm_prefix_wins_over_stale_vendor_id(monkeypatch):
    """本地前缀与运行中任务的旧 vendor_id 冲突时，必须按前缀路由到本地服务。

    改坏回「vendor_id 优先于前缀」（当年写法）时本用例红：
    vllm:qwen3.8:27b 会被路由到 DeepSeek 客户端，本地模型名透传 400。
    """
    vllm_client = _StubClient("vllm")
    deepseek_client = _StubClient("deepseek")
    _patch_vendor_lookup(monkeypatch, "deepseek")
    _patch_client_map(monkeypatch, vllm_client, deepseek_client)

    client = LLMClientFactory.get_client("vllm:qwen3.8:27b", vendor_id=7)

    assert client is vllm_client, (
        "vllm: 显式前缀被 vendor_id=7（deepseek）抢走路由——"
        "本地模型名将透传给云端 API，复现 2026-09-04 的持续 400"
    )


def test_vendor_id_still_routes_when_no_prefix_conflict(monkeypatch):
    """不冲突场景：vendor_id 优先语义必须保留（zjt_api 的 qwen3.5/3.6 靠它区分）。

    model 无本地前缀时，vendor_id 路由不受防御层影响。
    """
    deepseek_client = _StubClient("deepseek")
    _patch_vendor_lookup(monkeypatch, "deepseek")
    monkeypatch.setitem(LLMClientFactory._VENDOR_CLIENT_MAP, LLMVendor.DEEPSEEK, lambda: deepseek_client)

    client = LLMClientFactory.get_client("deepseek-v4-flash", vendor_id=7)

    assert client is deepseek_client
