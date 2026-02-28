"""
基于阿里云SDK的短信发送驱动（Legacy实现）
"""
import logging
from typing import Dict
from .base_sms_driver import BaseSmsDriver

logger = logging.getLogger(__name__)


class LegacySmsDriver(BaseSmsDriver):
    """基于阿里云SDK的短信发送驱动"""
    
    def __init__(self, config: Dict):
        """
        初始化阿里云短信驱动
        
        Args:
            config: 配置字典，应包含:
                - access_key_id: 阿里云AccessKey ID
                - access_key_secret: 阿里云AccessKey Secret
                - sign_name: 短信签名
                - template_code: 短信模板代码
                - region_id: 区域ID（可选，默认cn-hangzhou）
        """
        super().__init__(config)
        self.access_key_id = config.get('access_key_id')
        self.access_key_secret = config.get('access_key_secret')
        self.sign_name = config.get('sign_name')
        self.template_code = config.get('template_code')
        self.region_id = config.get('region_id', 'cn-hangzhou')
    
    def validate_config(self) -> bool:
        """验证配置是否完整"""
        required_fields = ['access_key_id', 'access_key_secret', 'sign_name', 'template_code']
        return all(self.config.get(field) for field in required_fields)
    
    def send_code(self, phone: str, code: str) -> Dict[str, any]:
        """
        通过阿里云SDK发送验证码短信
        
        Args:
            phone: 手机号
            code: 验证码
            
        Returns:
            {"success": bool, "message": str}
        """
        try:
            if not self.validate_config():
                logger.error("阿里云短信配置不完整")
                return {"success": False, "message": "短信配置不完整"}
            
            # 导入阿里云SDK
            from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
            from alibabacloud_tea_util import models as util_models
            
            # 创建客户端配置
            config = open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
                region_id=self.region_id
            )
            config.endpoint = f'dysmsapi.aliyuncs.com'
            
            # 创建客户端
            client = DysmsapiClient(config)
            
            # 构建请求
            send_sms_request = dysmsapi_models.SendSmsRequest(
                phone_numbers=phone,
                sign_name=self.sign_name,
                template_code=self.template_code,
                template_param=f'{{"code":"{code}"}}'
            )
            
            # 发送短信
            runtime = util_models.RuntimeOptions()
            response = client.send_sms_with_options(send_sms_request, runtime)
            
            if response.body.code == 'OK':
                logger.info(f"短信发送成功: {phone} 验证码：{code}")
                return {"success": True, "message": "验证码发送成功"}
            else:
                error_msg = f"{response.body.code} - {response.body.message}"
                logger.error(f"短信发送失败: {error_msg}")
                return {"success": False, "message": f"短信发送失败: {error_msg}"}
                
        except ImportError as e:
            logger.error(f"阿里云SDK未安装: {e}")
            return {"success": False, "message": "短信服务未配置"}
        except Exception as e:
            logger.error(f"发送短信失败: {e}")
            return {"success": False, "message": f"发送短信失败: {str(e)}"}
