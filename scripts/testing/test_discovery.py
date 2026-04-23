#!/usr/bin/env python3
"""
测试自动发现模块

基于 glob 模式自动发现测试文件，替代硬编码的测试文件列表。
"""
import os
import glob
from typing import List, Dict

# 项目根目录
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
TESTS_DIR = os.path.join(project_root, 'tests')

# 分类 -> 子目录列表 (相对于 tests/ 目录)
# 每个分类直接遍历该目录下所有 test_*.py 文件
CATEGORY_PATTERNS: Dict[str, List[str]] = {
    'crud': ['crud'],
    'cdn': ['cdn'],
    'utils': ['utils'],
    'config': ['config'],
    'drivers': ['drivers'],
    'driver_integration': ['driver_integration'],
    'auth': ['auth'],
    'reference_images': ['reference_images'],
    'stats': ['stats'],
    'llm': ['llm'],
    # 特殊：db_connection 不使用目录遍历
    'db_connection': [],
}


def discover_tests_by_category(category: str) -> List[str]:
    """
    根据分类自动发现测试模块。

    Args:
        category: 测试分类 (crud, cdn, utils, config, drivers, driver_integration, auth, reference_images, stats, db_connection)

    Returns:
        测试模块名称列表，如 ['tests.crud.test_ai_tools_crud', ...]
    """
    if category == 'db_connection':
        return ['tests.test_db_connection']

    if category not in CATEGORY_PATTERNS:
        raise ValueError(f"未知分类: {category}")

    patterns = CATEGORY_PATTERNS[category]
    discovered = []

    for subdir in patterns:
        search_path = os.path.join(TESTS_DIR, subdir, 'test_*.py')

        # 查找所有匹配的文件
        for filepath in glob.glob(search_path):
            if '__pycache__' in filepath or '__init__' in filepath:
                continue

            # 转换为模块路径（统一处理 Windows 反斜杠）
            rel_path = os.path.relpath(filepath, TESTS_DIR)
            module_parts = rel_path.replace('\\', '/').replace('/', '.').replace('.py', '')
            module_name = f'tests.{module_parts}'

            discovered.append(module_name)

    return sorted(set(discovered))


def get_all_categories() -> List[str]:
    """返回所有可用的测试分类"""
    return list(CATEGORY_PATTERNS.keys())


def get_category_display_name(category: str) -> str:
    """返回分类的可读名称"""
    display_names = {
        'crud': 'CRUD',
        'cdn': 'CDN',
        'utils': 'Utils',
        'config': 'Config',
        'drivers': 'Drivers',
        'driver_integration': 'Driver Integration',
        'auth': 'Auth',
        'reference_images': 'Reference Images',
        'stats': 'Stats',
        'llm': 'LLM',
        'db_connection': 'DB Connection',
    }
    return display_names.get(category, category)


if __name__ == '__main__':
    # 测试代码：打印所有分类的测试文件
    print("测试自动发现结果：\n")
    for cat in get_all_categories():
        modules = discover_tests_by_category(cat)
        print(f"[{cat}] ({len(modules)} 个)")
        for m in modules:
            print(f"  - {m}")
        print()
