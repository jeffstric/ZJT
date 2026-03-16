"""
项目路径工具模块
提供统一的项目根目录获取和验证功能
"""

import os
import sys
from pathlib import Path


def get_project_root():
    """
    获取项目根目录
    
    通过当前文件位置向上查找项目根目录，并验证根目录的正确性
    
    Returns:
        str: 项目根目录的绝对路径
        
    Raises:
        RuntimeError: 如果无法确定项目根目录或验证失败
    """
    # 获取当前调用栈的文件路径
    # 从调用者的文件位置开始查找
    frame = sys._getframe(1)
    caller_file = frame.f_globals.get('__file__')
    
    if not caller_file:
        # 如果无法获取调用者文件，使用当前文件
        current_file = os.path.abspath(__file__)
    else:
        current_file = os.path.abspath(caller_file)
    
    current_dir = os.path.dirname(current_file)
    
    # 向上查找项目根目录
    project_root = current_dir
    max_depth = 10  # 防止无限循环
    
    for _ in range(max_depth):
        # 验证当前目录是否为项目根目录
        if _is_project_root(project_root):
            return project_root
        
        # 向上一级目录
        parent_dir = os.path.dirname(project_root)
        if parent_dir == project_root:  # 已到达系统根目录
            break
        project_root = parent_dir
    
    raise RuntimeError(f"无法确定项目根目录。当前文件: {current_file}")


def _is_project_root(directory):
    """
    验证目录是否为项目根目录
    
    Args:
        directory: 要验证的目录路径
        
    Returns:
        bool: 是否为项目根目录
    """
    # 检查是否存在关键的项目文件
    key_files = ['server.py', 'requirements.txt', 'pyproject.toml']
    
    # 至少要包含 server.py
    if not os.path.exists(os.path.join(directory, 'server.py')):
        return False
    
    # 还需要包含其他关键文件中的至少一个
    for key_file in key_files[1:]:
        if os.path.exists(os.path.join(directory, key_file)):
            return True
    
    return False


def validate_project_root(project_root):
    """
    验证项目根目录的正确性
    
    Args:
        project_root: 项目根目录路径
        
    Raises:
        RuntimeError: 如果验证失败
    """
    if not os.path.exists(project_root):
        raise RuntimeError(f"项目根目录不存在: {project_root}")
    
    if not os.path.isdir(project_root):
        raise RuntimeError(f"项目根目录不是目录: {project_root}")
    
    # 验证关键文件存在
    server_py = os.path.join(project_root, 'server.py')
    if not os.path.exists(server_py):
        raise RuntimeError(f"项目根目录验证失败：找不到 server.py 文件在 {project_root}")
    
    # 验证其他关键文件
    key_files = ['requirements.txt', 'pyproject.toml', 'config.example.yml']
    found_key_files = []
    
    for key_file in key_files:
        if os.path.exists(os.path.join(project_root, key_file)):
            found_key_files.append(key_file)
    
    if not found_key_files:
        raise RuntimeError(f"项目根目录验证失败：找不到任何关键配置文件在 {project_root}")


def get_project_path(relative_path=""):
    """
    获取项目根目录下的相对路径
    
    Args:
        relative_path: 相对于项目根目录的路径
        
    Returns:
        str: 完整的绝对路径
    """
    project_root = get_project_root()
    return os.path.join(project_root, relative_path)


def ensure_project_root():
    """
    确保项目根目录在 Python 路径中
    """
    project_root = get_project_root()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    return project_root


# 向后兼容的函数
def get_app_dir():
    """
    向后兼容：获取项目根目录
    
    Returns:
        str: 项目根目录路径
    """
    return get_project_root()


if __name__ == "__main__":
    # 测试代码
    try:
        root = get_project_root()
        print(f"项目根目录: {root}")
        validate_project_root(root)
        print("✅ 项目根目录验证通过")
        
        # 测试路径获取
        test_paths = [
            "files",
            "config", 
            "logs",
            "server.py"
        ]
        
        print("\n测试路径:")
        for path in test_paths:
            full_path = get_project_path(path)
            exists = os.path.exists(full_path)
            status = "✅" if exists else "❌"
            print(f"{status} {path} -> {full_path}")
            
    except Exception as e:
        print(f"❌ 错误: {e}")
