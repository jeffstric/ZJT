"""
大模型分段计费「代码默认档位」目录。

用途：
- 管理后台「还原默认档位」时，按 (vendor_name, model_name) 覆盖写回 vendor_model
- 与迁移脚本中的初始/调价意图对齐；后续改官方价时请同步维护本文件

单位约定：
- 成本单价使用 元/百万 token（input/out/cache_yuan_per_m）
- 也可直接写 input/out/cache_token_threshold（每 N token 扣 1 算力）；与单价二选一，优先阈值
- commission_rate：抽成 0~1，默认 0
- raw_token_threshold：分段上界；None 表示无上限兜底档
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 每条：vendor_name + model_name + tiers[]
# tiers 字段：
#   raw_token_threshold: Optional[int]
#   input_yuan_per_m / out_yuan_per_m / cache_yuan_per_m  或
#   input_token_threshold / out_token_threshold / cache_read_threshold
#   commission_rate: float = 0
DEFAULT_VENDOR_MODEL_BILLING: List[Dict[str, Any]] = [
    # ---------- DeepSeek 官方 ----------
    {
        "vendor_name": "deepseek",
        "model_name": "deepseek-v4-flash",
        "note": "DeepSeek 官方：输入1/输出2/缓存0.02 元/百万",
        "tiers": [
            {
                "raw_token_threshold": None,
                "input_yuan_per_m": 1.0,
                "out_yuan_per_m": 2.0,
                "cache_yuan_per_m": 0.02,
                "commission_rate": 0.0,
            },
        ],
    },
    {
        "vendor_name": "deepseek",
        "model_name": "deepseek-v4-pro",
        "note": "DeepSeek 官方降价后：输入3/输出6/缓存0.025 元/百万",
        "tiers": [
            {
                "raw_token_threshold": None,
                "input_yuan_per_m": 3.0,
                "out_yuan_per_m": 6.0,
                "cache_yuan_per_m": 0.025,
                "commission_rate": 0.0,
            },
        ],
    },
    # ---------- zjt_api 挂载 DeepSeek（与官方同步调价）----------
    {
        "vendor_name": "zjt_api",
        "model_name": "deepseek-v4-flash",
        "note": "zjt_api / deepseek-v4-flash",
        "tiers": [
            {
                "raw_token_threshold": None,
                "input_yuan_per_m": 1.0,
                "out_yuan_per_m": 2.0,
                "cache_yuan_per_m": 0.02,
                "commission_rate": 0.0,
            },
        ],
    },
    {
        "vendor_name": "zjt_api",
        "model_name": "deepseek-v4-pro",
        "note": "zjt_api / deepseek-v4-pro（降价后）",
        "tiers": [
            {
                "raw_token_threshold": None,
                "input_yuan_per_m": 3.0,
                "out_yuan_per_m": 6.0,
                "cache_yuan_per_m": 0.025,
                "commission_rate": 0.0,
            },
        ],
    },
    # ---------- 火山引擎 DeepSeek ----------
    {
        "vendor_name": "volcengine",
        "model_name": "deepseek-v4-flash",
        "note": "火山方舟：0.001/0.002/0.0002 元/千 → 1/2/0.2 元/百万",
        "tiers": [
            {
                "raw_token_threshold": None,
                "input_yuan_per_m": 1.0,
                "out_yuan_per_m": 2.0,
                "cache_yuan_per_m": 0.2,
                "commission_rate": 0.0,
            },
        ],
    },
    {
        "vendor_name": "volcengine",
        "model_name": "deepseek-v4-pro",
        "note": "火山方舟：0.012/0.024/0.001 元/千 → 12/24/1 元/百万",
        "tiers": [
            {
                "raw_token_threshold": None,
                "input_yuan_per_m": 12.0,
                "out_yuan_per_m": 24.0,
                "cache_yuan_per_m": 1.0,
                "commission_rate": 0.0,
            },
        ],
    },
    # ---------- 阿里云 Qwen 分段 ----------
    {
        "vendor_name": "aliyun",
        "model_name": "qwen3.5-plus",
        "note": "qwen3.5-plus 三段计费",
        "tiers": [
            {
                "raw_token_threshold": 128000,
                "input_token_threshold": 50000,
                "out_token_threshold": 8334,
                "cache_read_threshold": 500000,
                "commission_rate": 0.0,
            },
            {
                "raw_token_threshold": 256000,
                "input_token_threshold": 20000,
                "out_token_threshold": 3334,
                "cache_read_threshold": 200000,
                "commission_rate": 0.0,
            },
            {
                "raw_token_threshold": None,
                "input_token_threshold": 10000,
                "out_token_threshold": 1667,
                "cache_read_threshold": 100000,
                "commission_rate": 0.0,
            },
        ],
    },
    {
        "vendor_name": "aliyun",
        "model_name": "qwen3.6-plus",
        "note": "qwen3.6-plus 两段计费",
        "tiers": [
            {
                "raw_token_threshold": 256000,
                "input_token_threshold": 20000,
                "out_token_threshold": 3334,
                "cache_read_threshold": 200000,
                "commission_rate": 0.0,
            },
            {
                "raw_token_threshold": None,
                "input_token_threshold": 5000,
                "out_token_threshold": 834,
                "cache_read_threshold": 50000,
                "commission_rate": 0.0,
            },
        ],
    },
]


def _index() -> Dict[Tuple[str, str], Dict[str, Any]]:
    idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in DEFAULT_VENDOR_MODEL_BILLING:
        key = (str(item["vendor_name"]), str(item["model_name"]))
        idx[key] = item
    return idx


_INDEX = None


def _get_index() -> Dict[Tuple[str, str], Dict[str, Any]]:
    global _INDEX
    if _INDEX is None:
        _INDEX = _index()
    return _INDEX


def list_defaults_for_model(model_name: str) -> List[Dict[str, Any]]:
    """返回某模型在所有供应商下的默认档位定义（深拷贝结构）。"""
    name = (model_name or "").strip()
    return [
        {
            "vendor_name": item["vendor_name"],
            "model_name": item["model_name"],
            "note": item.get("note") or "",
            "tiers": [dict(t) for t in (item.get("tiers") or [])],
        }
        for item in DEFAULT_VENDOR_MODEL_BILLING
        if item.get("model_name") == name
    ]


def get_default_for_vendor_model(vendor_name: str, model_name: str) -> Optional[Dict[str, Any]]:
    item = _get_index().get((vendor_name, model_name))
    if not item:
        return None
    return {
        "vendor_name": item["vendor_name"],
        "model_name": item["model_name"],
        "note": item.get("note") or "",
        "tiers": [dict(t) for t in (item.get("tiers") or [])],
    }


def list_default_vendor_names_for_model(model_name: str) -> List[str]:
    return [d["vendor_name"] for d in list_defaults_for_model(model_name)]


def has_defaults_for_model(model_name: str) -> bool:
    return bool(list_defaults_for_model(model_name))
