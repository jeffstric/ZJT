"""Pytest 全局夹具。

为单元测试预置最小配置缓存，避免导入 llm/script_parser 等模块时因缺 config_dev.yml 报错。
真实运行环境由 config_dev.yml 提供，此处只在测试期注入空配置 stub。
"""
import os
import sys

# 确保项目根目录在 sys.path，便于 tests 直接 import 业务模块
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _stub_config_cache():
    """预置最小配置缓存，满足导入链对 database/perseids 配置的存在性检查。

    单元测试不真正连接数据库，只需让模块级 get_config_value 不抛错。
    真实环境由 config_dev.yml 提供完整配置。
    """
    try:
        from config import config_util
        from config.config_util import get_config_path
        _stub = {
            "database": {"host": "localhost", "port": 3306,
                         "user": "test", "password": "test", "database": "test"},
            "llm": {},
            "edition": {"mode": "community"},
        }
        for fname in (get_config_path(), "config_dev.yml", "config.yaml"):
            config_util._config_cache[fname] = _stub
    except Exception:
        pass


_stub_config_cache()
