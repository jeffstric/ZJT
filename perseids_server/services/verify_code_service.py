"""
VerifyCodeService 验证码服务 - 对应Go的handler/verify_sms.go
"""
from typing import Dict, Any
from datetime import datetime, timedelta
import random
import logging

from model.verify_codes import VerifyCodesModel
from utils.log_sanitizer import mask_email, mask_phone

from ..utils.validator import validate_phone, validate_email
from ..utils.sms_drivers import SmsDriverFactory
from ..utils.email_drivers import EmailDriverFactory

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
                # 短信发送失败时返回 failure，不让用户进入验证流程
                return {
                    "success": False,
                    "message": sms_result.get('message', '短信发送失败，请稍后重试'),
                    "expire_minutes": VerifyCodeService.CODE_EXPIRE_MINUTES,
                }
        
        logger.info(
            "验证码创建成功 - 手机号: %s, 类型: %s",
            mask_phone(phone),
            code_type,
        )
        
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
        
        logger.info(
            "验证码验证成功 - 手机号: %s, 类型: %s",
            mask_phone(phone),
            code_type,
        )
        
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

    # ==================== 邮箱验证码方法 ====================

    @staticmethod
    def create_email_verify_code(
        email: str,
        code_type: str = "register",
        send_email: bool = True
    ) -> Dict[str, Any]:
        """
        创建邮箱验证码并发送邮件
        
        Args:
            email: 收件邮箱地址
            code_type: 验证码类型（register/reset/login）
            send_email: 是否发送邮件（测试时可设为False）
            
        Returns:
            创建结果
        """
        # 验证邮箱格式
        if not validate_email(email):
            return {"success": False, "message": "无效的邮箱格式"}
        
        # 验证类型
        if code_type not in VerifyCodeService.VALID_TYPES:
            return {"success": False, "message": "无效的验证码类型"}
        
        # 生成验证码
        code = VerifyCodeService.generate_code(VerifyCodeService.CODE_LENGTH)
        expire_time = datetime.now() + timedelta(minutes=VerifyCodeService.CODE_EXPIRE_MINUTES)
        
        # 保存验证码
        VerifyCodesModel.create_for_email(email, code, code_type, expire_time)
        
        # 发送邮件
        if send_email:
            email_result = EmailDriverFactory.send_code(email, code)
            if not email_result.get('success'):
                logger.warning(f"验证码邮件发送失败: {email_result.get('message')}")
                return {
                    "success": False,
                    "message": email_result.get('message', '验证码邮件发送失败，请稍后重试'),
                    "expire_minutes": VerifyCodeService.CODE_EXPIRE_MINUTES,
                }
        
        logger.info(
            "邮箱验证码创建成功 - 邮箱: %s, 类型: %s",
            mask_email(email),
            code_type,
        )
        
        return {
            "success": True,
            "message": "验证码已发送至您的邮箱",
            "expire_minutes": VerifyCodeService.CODE_EXPIRE_MINUTES,
        }

    @staticmethod
    def verify_email_code(
        email: str,
        code: str,
        code_type: str = "register"
    ) -> Dict[str, Any]:
        """
        验证邮箱验证码
        
        Args:
            email: 邮箱地址
            code: 验证码
            code_type: 验证码类型
            
        Returns:
            验证结果
        """
        # 验证邮箱格式
        if not validate_email(email):
            return {"success": False, "message": "无效的邮箱格式"}
        
        # 验证类型
        if code_type not in VerifyCodeService.VALID_TYPES:
            return {"success": False, "message": "无效的验证码类型"}
        
        # 验证验证码
        if not VerifyCodesModel.verify_for_email(email, code, code_type):
            return {"success": False, "message": "验证码不正确或已过期"}
        
        # 标记验证码为已使用
        VerifyCodesModel.mark_used_for_email(email, code, code_type)
        
        logger.info(
            "邮箱验证码验证成功 - 邮箱: %s, 类型: %s",
            mask_email(email),
            code_type,
        )
        
        return {"success": True, "message": "验证成功"}
