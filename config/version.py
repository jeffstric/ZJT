"""
系统版本号管理
版本号定义在 pyproject.toml 中，此处提供读取方法
"""
from pathlib import Path

_cached_version = None


def get_app_version() -> str:
    """
    获取应用版本号
    优先从 pyproject.toml 读取，缓存结果以提高性能
    """
    global _cached_version
    if _cached_version is not None:
        return _cached_version

    # 尝试从 pyproject.toml 读取
    try:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            content = pyproject_path.read_text(encoding='utf-8')
            # 简单解析，避免引入 toml 依赖
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('version'):
                    # version = "1.0.2"
                    _cached_version = line.split('=')[1].strip().strip('"').strip("'")
                    return _cached_version
    except Exception:
        pass

    # 默认版本号
    _cached_version = "1.0.0"
    return _cached_version
