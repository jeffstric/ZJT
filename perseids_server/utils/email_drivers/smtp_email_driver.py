"""
基于SMTP的邮箱发送驱动
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict

from .base_email_driver import BaseEmailDriver
from utils.log_sanitizer import mask_email

logger = logging.getLogger(__name__)


class SmtpEmailDriver(BaseEmailDriver):
    """基于SMTP的邮箱发送驱动"""
    
    def __init__(self, config: Dict):
        """
        初始化SMTP邮件驱动
        
        Args:
            config: 配置字典，应包含:
                - smtp_host: SMTP服务器地址
                - smtp_port: SMTP服务器端口
                - smtp_user: SMTP用户名
                - smtp_password: SMTP密码
                - smtp_from: 发件人邮箱
                - use_tls: 是否使用TLS（默认True）
                - smtp_from_name: 发件人名称（可选）
        """
        super().__init__(config)
        self.smtp_host = config.get('smtp_host')
        self.smtp_port = config.get('smtp_port', 587)
        self.smtp_user = config.get('smtp_user')
        self.smtp_password = config.get('smtp_password')
        self.smtp_from = config.get('smtp_from')
        self.smtp_from_name = config.get('smtp_from_name', '')
        self.use_tls = config.get('use_tls', True)
    
    def validate_config(self) -> bool:
        """验证配置是否完整"""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_from)
    
    def send_code(self, email: str, code: str) -> Dict[str, any]:
        """
        通过SMTP发送验证码邮件
        
        Args:
            email: 收件邮箱地址
            code: 验证码
            
        Returns:
            {"success": bool, "message": str}
        """
        try:
            if not self.validate_config():
                logger.error("SMTP邮件配置不完整")
                return {"success": False, "message": "邮件服务配置不完整"}
            
            # 构建邮件内容
            msg = MIMEMultipart('alternative')
            from_name = self.smtp_from_name or '智剧通'
            msg['From'] = f"{from_name} <{self.smtp_from}>"
            msg['To'] = email
            msg['Subject'] = f"您的验证码：{code}"
            
            # HTML邮件模板
            html_content = f"""
            <html>
            <head>
                <meta charset="utf-8">
            </head>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #f8f9fa; border-radius: 8px; padding: 30px; text-align: center;">
                    <h2 style="color: #333; margin-bottom: 20px;">邮箱验证码</h2>
                    <div style="background: white; border: 2px solid #4CAF50; border-radius: 8px; padding: 20px; margin: 20px 0;">
                        <span style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #4CAF50;">{code}</span>
                    </div>
                    <p style="color: #666; font-size: 14px; margin-top: 20px;">
                        该验证码 <strong>5分钟</strong> 内有效，请勿泄露给他人。
                    </p>
                    <p style="color: #999; font-size: 12px; margin-top: 30px; border-top: 1px solid #eee; padding-top: 15px;">
                        如果您没有请求此验证码，请忽略此邮件。
                    </p>
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            
            # 发送邮件
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            
            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.smtp_from, [email], msg.as_string())
            server.quit()
            
            logger.info("验证码邮件发送成功: %s", mask_email(email))
            return {"success": True, "message": "验证码邮件发送成功"}
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP认证失败: {e}")
            return {"success": False, "message": "邮件服务认证失败"}
        except smtplib.SMTPException as e:
            logger.error(f"SMTP发送失败: {e}")
            return {"success": False, "message": f"邮件发送失败: {str(e)}"}
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return {"success": False, "message": f"发送邮件失败: {str(e)}"}
