"""
网络相关工具函数
"""
from urllib.parse import urlparse


def is_private_ip(host: str) -> bool:
    """
    判断是否为私有/局域网IP地址

    Args:
        host: 主机名或IP地址

    Returns:
        bool: 是否为私有地址
    """
    if not host:
        return False

    host_lower = host.lower()

    # localhost 和 IPv6 loopback
    if host_lower in ("localhost", "::1"):
        return True

    # 127.x.x.x (loopback段)
    if host.startswith("127."):
        return True

    # 10.x.x.x (A类私有网络)
    if host.startswith("10."):
        return True

    # 192.168.x.x (C类私有网络)
    if host.startswith("192.168."):
        return True

    # 172.16.x.x - 172.31.x.x (B类私有网络)
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second_octet = int(parts[1])
                if 16 <= second_octet <= 31:
                    return True
            except ValueError:
                pass

    return False


def is_local_or_private_url(url: str) -> bool:
    """
    判断URL是否指向本地或局域网地址（外网无法访问）

    Args:
        url: URL字符串

    Returns:
        bool: 是否为本地/局域网URL
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return is_private_ip(host)
    except Exception:
        return False


def is_local_file_path(path: str) -> bool:
    """
    判断是否为本地文件路径（非URL）

    Args:
        path: 文件路径或URL

    Returns:
        bool: 是否为本地文件路径
    """
    if not path:
        return False

    # 如果以 http:// 或 https:// 开头，则为URL，不是本地文件
    if path.startswith("http://") or path.startswith("https://"):
        return False

    # 非URL视为本地文件路径
    return True


def is_local_path(path: str) -> bool:
    """
    判断是否为本地文件路径或局域网URL（外网无法访问）

    Args:
        path: 文件路径或URL

    Returns:
        bool: 是否为本地路径或局域网地址，需要上传到图床
    """
    if not path:
        return False

    # 如果以 http:// 或 https:// 开头，检查是否为局域网地址
    if path.startswith("http://") or path.startswith("https://"):
        return is_local_or_private_url(path)

    # 非URL视为本地文件路径
    return True
