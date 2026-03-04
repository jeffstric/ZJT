"""
验证工具函数
"""
import re


def validate_phone(phone: str) -> bool:
    """
    验证手机号格式是否正确
    
    Args:
        phone: 手机号
        
    Returns:
        是否为有效的手机号格式
    """
    if not phone:
        return False
    
    pattern = r'^1[3-9]\d{9}$'
    return bool(re.match(pattern, phone))


def validate_password(password: str) -> tuple[bool, str]:
    """
    验证密码强度
    
    Args:
        password: 密码
        
    Returns:
        (是否有效, 错误信息)
    """
    if not password:
        return False, "密码不能为空"
    
    if len(password) < 6:
        return False, "密码长度不能少于6位"
    
    if len(password) > 32:
        return False, "密码长度不能超过32位"
    
    return True, ""


def validate_verify_code(code: str) -> bool:
    """
    验证验证码格式
    
    Args:
        code: 验证码
        
    Returns:
        是否为有效的验证码格式
    """
    if not code:
        return False
    
    pattern = r'^\d{4,6}$'
    return bool(re.match(pattern, code))
