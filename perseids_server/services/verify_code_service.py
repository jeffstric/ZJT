"""
VerifyCodeService 验证码服务 - 对应Go的handler/verify_sms.go
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import random
import logging

from model.verify_codes import VerifyCodesModel

from ..utils.validator import validate_phone
from ..utils.sms_drivers import SmsDriverFactory

logger = logging.getLogger(__name__)


class VerifyCodeService:
    """验证码服务 - 创建、验证验证码"""
    
    # 常量
    CODE_LENGTH = 6  # 验证码长度
    CODE_EXPIRE_MINUTES = 5  # 验证码过期时间（分钟）
    VALID_TYPES = ("register", "login", "reset_password", "get_serial", "update_serial")  # 有效的验证码类型
    
    @staticmethod
    def generate_code(length: int = 6) -> str:
        """生成随机验证码"""
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])
    
    @staticmethod
    def create_verify_code(
        phone: str,
        code_type: str = "register",
        send_sms: bool = True
    ) -> Dict[str, Any]:
        """
        创建验证码并发送短信
        
        Args:
            phone: 手机号
            code_type: 验证码类型（register/reset/login）
            send_sms: 是否发送短信（测试时可设为False）
            
        Returns:
            创建结果
        """
        # 验证手机号格式
        if not validate_phone(phone):
            return {"success": False, "message": "无效的手机号格式"}
        
        # 验证类型
        if code_type not in VerifyCodeService.VALID_TYPES:
            return {"success": False, "message": "无效的验证码类型"}
        
        # 生成验证码
        code = VerifyCodeService.generate_code(VerifyCodeService.CODE_LENGTH)
        expire_time = datetime.now() + timedelta(minutes=VerifyCodeService.CODE_EXPIRE_MINUTES)
        
        # 保存验证码
        VerifyCodesModel.create(phone, code, code_type, expire_time)
        
        # 发送短信
        if send_sms:
            sms_result = SmsDriverFactory.send_code(phone, code)
            if not sms_result.get('success'):
                logger.warning(f"短信发送失败: {sms_result.get('message')}")
                # 短信发送失败不影响验证码创建，但返回提示
                return {
                    "success": True,
                    "message": "验证码已创建，但短信发送失败",
                    "expire_minutes": VerifyCodeService.CODE_EXPIRE_MINUTES,
                }
        
        logger.info(f"验证码创建成功 - 手机号: {phone}, 类型: {code_type}")
        
        return {
            "success": True,
            "message": "验证码已发送",
            "expire_minutes": VerifyCodeService.CODE_EXPIRE_MINUTES,
        }
    
    @staticmethod
    def verify_code(
        phone: str,
        code: str,
        code_type: str = "register"
    ) -> Dict[str, Any]:
        """
        验证验证码
        
        Args:
            phone: 手机号
            code: 验证码
            code_type: 验证码类型
            
        Returns:
            验证结果
        """
        # 验证手机号格式
        if not validate_phone(phone):
            return {"success": False, "message": "无效的手机号格式"}
        
        # 验证类型
        if code_type not in VerifyCodeService.VALID_TYPES:
            return {"success": False, "message": "无效的验证码类型"}
        
        # 验证验证码
        if not VerifyCodesModel.verify(phone, code, code_type):
            return {"success": False, "message": "验证码不正确或已过期"}
        
        # 标记验证码为已使用
        VerifyCodesModel.mark_used(phone, code, code_type)
        
        logger.info(f"验证码验证成功 - 手机号: {phone}, 类型: {code_type}")
        
        return {"success": True, "message": "验证成功"}
    
    @staticmethod
    def delete_expired_codes() -> Dict[str, Any]:
        """
        删除过期的验证码
        
        Returns:
            删除结果
        """
        deleted_count = VerifyCodesModel.delete_expired()
        
        logger.info(f"删除过期验证码: {deleted_count}条")
        
        return {
            "success": True,
            "message": f"已删除 {deleted_count} 条过期验证码",
            "deleted_count": deleted_count,
        }
