"""
网络相关工具函数
"""
from urllib.parse import urlparse


def is_private_ip(host: str) -> bool:
    """
    判断 host 是否为私有/回环地址（本机或局域网，公网通常无法路由）。

    命中条件：`localhost` / `::1`、`127.x.x.x`、`10.x.x.x`、`192.168.x.x`、
    `172.16~172.31.x.x`。

    ⚠️ 注意：本函数**只按 IP/回环名判断**，不会做 DNS 解析。因此：
    - **公网域名一律返回 False**，哪怕该域名实际指向当前服务器
      （如 `zjt_dev.perseids.cn` 解析到本机，这里仍判 False）；
    - 想判断「这个 URL 是不是本服务自己的文件」请用
      `extract_local_path_from_url`（按 `/upload/` 前缀），而非本函数。

    Args:
        host: 主机名或 IP 地址（不含 scheme/port）

    Returns:
        bool: 是否为私有/回环地址
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
    判断 URL 是否指向本机/局域网地址（公网无法访问），即 host 是否为私有/回环 IP。

    内部转调 `is_private_ip`，命中 `localhost`/`127.x`/`10.x`/`192.168.x`/`172.16~31.x`
    才返回 True。

    ⚠️ **常见误用警告（重要）**：本函数**只认私有 IP，不认公网域名**。哪怕 URL 的域名
    实际指向当前服务器（如 `http://zjt_dev.perseids.cn/upload/...`），本函数仍返回 **False**。
    因此**不要用本函数来决定「这个 URL 能不能当本地文件直接读」**——否则本服务自己上传的、
    用公网域名访问的文件会被误判为「外网 URL」而触发不必要的回环下载
    （grok 驱动曾因此把本服务 `/upload/` 文件下载了一遍）。

    正确做法：判断「是否本服务文件、能否映射为本地路径」请用
    `utils.media_mapping_util.extract_local_path_from_url`（按 `/upload/` 前缀，与域名无关），
    拿到相对路径后 `os.path.join(get_project_root(), rel)` + `os.path.exists` 校验。

    适用场景：本函数适合判断「这个 URL 公网能否访问到」（用于「需不需要上传到公网图床」
    这类决策），不适合判断「这个 URL 是不是本机已有文件」。

    Args:
        url: URL 字符串

    Returns:
        bool: 是否指向本机/局域网（私有/回环 IP）；非 URL 或公网域名返回 False。
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
    判断字符串是否为「本地文件路径」（即**不是** http/https URL）。

    判定非常窄：只要**不是**以 `http://` / `https://` 开头，就视为本地文件路径（返回 True）。
    因此相对路径、绝对路径都会返回 True。

    ⚠️ 注意边界：
    - `data:image/...;base64,...` 这类 data URI 不以 http/https 开头 → 本函数返回 True，
      但它**不是**磁盘文件路径，调用方需另行用 `path.startswith("data:")` 排除；
    - `ftp://`、`file://` 等其它 scheme 也不以 http/https 开头 → 同样返回 True，需调用方自行甄别；
    - 返回 True **不代表文件一定存在**，仅表示「形态上是路径而非 http(s) URL」。

    Args:
        path: 文件路径或 URL

    Returns:
        bool: 是否为本地文件路径（非 http/https URL）
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
    判断 path 是否为「公网无法直接访问、需要上传图床」的源：本地文件路径 或 本机/局域网 URL。

    - 非 http/https 字符串 → 视为本地文件路径，返回 True；
    - http/https URL → 转调 `is_local_or_private_url`，仅当 host 为私有/回环 IP 才返回 True。

    ⚠️ 继承 `is_local_or_private_url` 的局限：**公网域名一律返回 False**，哪怕该域名指向
    当前服务器（如 `http://zjt_dev.perseids.cn/upload/...`）。因此本函数判定为 False 的 URL
    **并不一定真的在公网**——可能只是本服务用公网域名访问自己的文件。判断「能否映射为本地
    文件」请用 `extract_local_path_from_url`，详见 `is_local_or_private_url` 的警告。

    Args:
        path: 文件路径或 URL

    Returns:
        bool: 是否为本地文件路径或本机/局域网 URL（即需要上传到公网图床才能被外部访问）。
    """
    if not path:
        return False

    # 如果以 http:// 或 https:// 开头，检查是否为局域网地址
    if path.startswith("http://") or path.startswith("https://"):
        return is_local_or_private_url(path)

    # 非URL视为本地文件路径
    return True


def get_local_ip() -> str:
    """
    获取本机对外的 IP 地址

    Returns:
        str: 本机 IP 地址
    """
    import socket

    try:
        # 连接外部 DNS 服务器来获取本机 IP
        # 这是一种常见的获取本机对外 IP 的方法
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        try:
            # 不需要真正连接，只是获取本机到目标的路由
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        try:
            # 备用方法：获取主机名对应的 IP
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            return ip
        except Exception:
            return "unknown"
