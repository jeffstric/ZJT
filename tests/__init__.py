"""
Tests package
"""
import os
import sys

# unittest loader 不会执行 conftest.py，这里同样把项目根目录加入 sys.path，
# 保证 tests 子包里的用例可以直接 import 业务模块（如 enterprise.*）。
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
