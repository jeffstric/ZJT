# -*- coding: utf-8 -*-
"""
火山引擎 HMAC-SHA256 V4 请求签名（标准库实现，无第三方依赖）

对齐 volcengine 官方 SDK（volcengine-go-sdk signer/v4，AWS SigV4 变体）的签名算法：
- CanonicalRequest = Method \n CanonicalURI \n CanonicalQueryString \n CanonicalHeaders
  \n SignedHeaders \n Hex(SHA256(Payload))
- StringToSign = HMAC-SHA256 \n X-Date \n CredentialScope \n Hex(SHA256(CanonicalRequest))
- CredentialScope = <YYYYMMDD>/<Region>/<Service>/request
- 签名密钥派生：kDate → kRegion → kService → kSigning（逐级 HMAC-SHA256）
- Authorization = HMAC-SHA256 Credential=<ak>/<scope>, SignedHeaders=...,
  Signature=<hex>

签名头集合固定为 content-type;host;x-date（对齐官方 SDK 对 JSON RPC 请求的
签名惯例；SignedHeaders 至少须含 host 与 x-date，见火山签名方法文档）。

用于 Seedance 素材 Action 接口直连火山方舟的鉴权（网关 Bearer 形态见
utils/seedance_asset_client.py）。本模块纯计算无副作用，可安全单测。
"""
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional
from urllib.parse import quote

# 签名算法标识（火山 V4 与 AWS SigV4 的差异点之一）
_SIGN_ALGORITHM = "HMAC-SHA256"
# 签名密钥派生末级标识（火山固定为 "request"）
_SIGN_TERMINATOR = "request"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _uri_encode(value: str) -> str:
    """URL 编码（保留未保留字符，对齐签名规范的 uriencode）"""
    return quote(value, safe="~-._")


def _canonical_uri(path: str) -> str:
    return quote(path or "/", safe="/~-._")


def _canonical_query(query: Optional[Mapping[str, str]]) -> str:
    """查询串按参数名字典序排序并分别 URI 编码（值为空也要编码为 key=""）"""
    if not query:
        return ""
    pairs = sorted(query.items(), key=lambda kv: kv[0])
    return "&".join(f"{_uri_encode(str(k))}={_uri_encode(str(v))}" for k, v in pairs)


def _canonical_headers(signed_headers: Dict[str, str]) -> str:
    """signed_headers 按名排序、值去首尾空白，行尾补 \\n（CanonicalHeaders 规范）"""
    lines = [f"{name}:{value.strip()}" for name, value in sorted(signed_headers.items())]
    return "\n".join(lines) + "\n"


def sign_request(
    method: str,
    host: str,
    path: str,
    query: Optional[Mapping[str, str]],
    headers: Mapping[str, str],
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    """
    计算火山 V4 签名，返回需附加到请求的头（X-Date / Authorization）。

    Args:
        method: HTTP 方法（POST/GET...）
        host: 请求主机（含端口，如 ark.cn-beijing.volces.com）
        path: 请求路径（如 /v1/api/assets/）
        query: 查询参数（Action/Version 等；None 视为无查询串）
        headers: 原始请求头（至少含 Content-Type；Host 由 host 参数补齐）
        body: 请求体原始字节（签名用其 SHA256）
        access_key / secret_key: 火山 AK/SK
        region / service: 签名 scope（直连火山素材库为 cn-beijing / ark）
        now: 签名时间（可注入以便单测；缺省取当前 UTC 时间）

    Returns:
        {"X-Date": ..., "Authorization": ...}
    """
    if not access_key or not secret_key:
        raise ValueError("火山签名需显式提供 access_key 与 secret_key")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    x_date = moment.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = moment.strftime("%Y%m%d")

    # 参与签名的头：host + x-date + content-type（headers 里可能缺 content-type，缺省不参与）
    signed_headers: Dict[str, str] = {"host": host.strip(), "x-date": x_date}
    for name, value in headers.items():
        lower = name.lower()
        if lower == "content-type":
            signed_headers[lower] = value
    signed_headers_str = ";".join(sorted(signed_headers))

    canonical_request = "\n".join([
        method.upper(),
        _canonical_uri(path),
        _canonical_query(query),
        _canonical_headers(signed_headers),
        signed_headers_str,
        _sha256_hex(body or b""),
    ])

    credential_scope = f"{date_stamp}/{region}/{service}/{_SIGN_TERMINATOR}"
    string_to_sign = "\n".join([
        _SIGN_ALGORITHM,
        x_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    k_date = _hmac_sha256(secret_key.encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, _SIGN_TERMINATOR)
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{_SIGN_ALGORITHM} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )
    return {"X-Date": x_date, "Authorization": authorization}
