"""
Token工具函数 - 对应Go的utils/token.go
"""
import hashlib
import secrets
import time
from typing import Optional

import bcrypt


def generate_token(user_id: int, device_uuid: Optional[str] = None) -> str:
    """
    生成用户token
    
    Args:
        user_id: 用户ID
        device_uuid: 设备UUID
        
    Returns:
        生成的token字符串
    """
    timestamp = str(int(time.time() * 1000))
    random_str = secrets.token_hex(16)
    device_part = device_uuid or ""
    
    raw_string = f"{user_id}:{timestamp}:{random_str}:{device_part}"
    token = hashlib.sha256(raw_string.encode()).hexdigest()
    
    return token


def hash_password(password: str) -> str:
    """
    对密码进行哈希处理
    
    Args:
        password: 原始密码
        
    Returns:
        哈希后的密码
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed_password: str) -> bool:
    """
    验证密码是否正确
    
    Args:
        password: 原始密码
        hashed_password: 哈希后的密码
        
    Returns:
        密码是否匹配
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False


def generate_secret_key() -> str:
    """
    生成32字节的随机密钥（用于用户secret_key）
    
    Returns:
        十六进制格式的密钥字符串
    """
    return secrets.token_hex(32)
