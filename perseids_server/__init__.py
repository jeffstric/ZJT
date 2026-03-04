"""
Perseids Server - 认证与算力管理子模块

从Go项目迁移的Python实现，作为业务逻辑层集成到主项目。
"""

__version__ = "0.1.0"

from .services.auth_service import AuthService
from .services.computing_power_service import ComputingPowerService
from .services.verify_code_service import VerifyCodeService

__all__ = [
    'AuthService',
    'ComputingPowerService',
    'VerifyCodeService',
]
