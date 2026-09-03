"""
项目路径工具模块
提供统一的项目根目录获取和验证功能，以及上传路径管理
"""

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse


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


# ============================================================
# 上传路径工具函数
# ============================================================


def get_upload_dir() -> str:
    """
    获取上传根目录的绝对路径（项目根目录下的 upload/）

    Returns:
        str: 上传根目录绝对路径
    """
    from config.constant import UploadPathConstants
    return get_project_path(UploadPathConstants.UPLOAD_ROOT)


def get_upload_subdir(*parts: str, ensure: bool = True) -> str:
    """
    获取上传目录下指定子目录的绝对路径

    Args:
        *parts: 子目录路径段，例如 ("temp", "20250501") 或 ("image_to_video", "123", "20250501")
        ensure: 是否自动创建目录（默认 True）

    Returns:
        str: 子目录的绝对路径
    """
    subdir = os.path.join(get_upload_dir(), *parts)
    if ensure:
        os.makedirs(subdir, exist_ok=True)
    return subdir


def get_upload_temp_dir(date_str: str = None) -> str:
    """
    获取临时上传目录（按日期分组）。
    该目录每天会被定时清理（由 media_cache.cleanup_temp_dir 执行，默认保留 2 天）。

    Args:
        date_str: 日期字符串，格式 YYYYMMDD，默认当天

    Returns:
        str: 临时目录绝对路径，如 /project/upload/temp/20250501
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    from config.constant import UploadPathConstants
    return get_upload_subdir(UploadPathConstants.TEMP_DIR, date_str)


class UploadFilenameInfo(NamedTuple):
    """上传文件名信息"""
    filename: str    # 完整文件名，如 "media_20250501_143025_a1b2c3d4.png"
    timestamp: str   # 时间戳部分，如 "20250501_143025"
    unique_id: str   # UUID 部分，如 "a1b2c3d4"


def generate_upload_filename(
    prefix: str = "upload",
    extension: str = "",
    unique_id_len: int = 8
) -> UploadFilenameInfo:
    """
    生成上传文件的唯一文件名

    Args:
        prefix: 文件名前缀，例如 "upload"、"media"、"workflow"
        extension: 文件扩展名（含点号），例如 ".png"、".mp4"；为空时默认 ".bin"
        unique_id_len: UUID 截取长度，默认 8

    Returns:
        UploadFilenameInfo: 包含 filename, timestamp, unique_id 的命名元组
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:unique_id_len]
    ext = extension if extension else ".bin"
    filename = f"{prefix}_{timestamp}_{unique_id}{ext}"
    return UploadFilenameInfo(filename=filename, timestamp=timestamp, unique_id=unique_id)


def build_upload_url(*relative_parts: str, host: str = "") -> str:
    """
    构建上传文件的可访问 URL

    Args:
        *relative_parts: 相对于 upload/ 目录的路径段
        host: 服务器主机地址（含协议），例如 "https://example.com"

    Returns:
        str: 完整的文件访问 URL

    Examples:
        build_upload_url("temp", "20250501", "upload_xxx.png", host="https://example.com")
        # -> "https://example.com/upload/temp/20250501/upload_xxx.png"
    """
    relative_path = "/".join(part.strip("/") for part in relative_parts)
    base = host.rstrip("/") if host else ""
    return f"{base}/upload/{relative_path}"


def resolve_upload_url_to_local_path(url_or_relative_path: str) -> str:
    """
    将上传文件的 URL 或相对路径解析为本地文件系统绝对路径

    仅做路径转换，不验证文件是否存在。

    Args:
        url_or_relative_path: 完整 URL（如 https://host/upload/temp/x.png）
                              或以 /upload/ 开头的路径（如 /upload/temp/x.png）
                              或相对于 upload/ 的路径（如 temp/x.png）

    Returns:
        str: 本地文件系统绝对路径
    """
    if not isinstance(url_or_relative_path, str) or not url_or_relative_path.strip():
        raise ValueError("上传路径不能为空")
    path = url_or_relative_path.strip()

    # 处理完整 URL：提取路径部分
    if "://" in path:
        parsed = urlparse(path)
        path = parsed.path

    path = unquote(path)
    if "\\" in path:
        raise ValueError("非法的上传路径")

    # 移除 /upload/ 前缀
    if path.startswith("/upload/"):
        path = path[8:]
    elif path.startswith("upload/"):
        path = path[7:]

    # 路径必须是 upload 根目录下的普通相对路径，禁止绝对路径和 dot segment。
    if path.startswith("/"):
        raise ValueError("非法的上传路径")
    parts = [part for part in path.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ValueError("非法的上传路径")

    upload_root = Path(get_upload_dir()).resolve()
    candidate = upload_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError("非法的上传路径") from exc
    return str(candidate)


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
