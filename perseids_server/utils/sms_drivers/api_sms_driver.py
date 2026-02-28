"""
基于HTTP API的短信发送驱动
"""
import logging
import httpx
from typing import Dict
from .base_sms_driver import BaseSmsDriver

logger = logging.getLogger(__name__)


class ApiSmsDriver(BaseSmsDriver):
    """基于HTTP API的短信发送驱动"""
    
    def __init__(self, config: Dict):
        """
        初始化API短信驱动
        
        Args:
            config: 配置字典，应包含:
                - api_url: 短信API接口地址（必需）
                - method: 请求方法（可选，默认POST）
        """
        super().__init__(config)
        self.api_url = config.get('api_url')
        self.method = config.get('method', 'POST').upper()
    
    def validate_config(self) -> bool:
        """验证配置是否完整"""
        return bool(self.api_url)
    
    def send_code(self, phone: str, code: str) -> Dict[str, any]:
        """
        通过HTTP API发送验证码短信
        
        Args:
            phone: 手机号
            code: 验证码
            
        Returns:
            {"success": bool, "message": str}
        """
        try:
            if not self.validate_config():
                logger.error("API短信配置不完整：缺少api_url")
                return {"success": False, "message": "短信配置不完整"}
            
            # 构建请求参数
            params = {
                "phone": phone,
                "code": code
            }
            
            # 发送HTTP请求
            with httpx.Client(timeout=10) as client:
                if self.method == 'POST':
                    response = client.post(
                        self.api_url,
                        json=params
                    )
                elif self.method == 'GET':
                    response = client.get(
                        self.api_url,
                        params=params
                    )
                else:
                    logger.error(f"不支持的HTTP方法: {self.method}")
                    return {"success": False, "message": f"不支持的HTTP方法: {self.method}"}
            
            # 解析响应
            try:
                result = response.json()
            except Exception:
                # 如果响应不是JSON格式
                logger.error(f"API响应格式错误，状态码: {response.status_code}")
                return {"success": False, "message": "API响应格式错误"}
            
            # 根据HTTP状态码处理响应
            if response.status_code == 200:
                # 成功响应
                success = result.get('success', False)
                message = result.get('message', '验证码发送成功')
                
                if success:
                    logger.info(f"短信发送成功: {phone} 验证码：{code}")
                    return {"success": True, "message": message}
                else:
                    logger.error(f"短信发送失败: {message}")
                    return {"success": False, "message": message}
                    
            elif response.status_code == 400:
                # 参数错误或手机号格式错误
                message = result.get('message', '请求参数错误')
                logger.error(f"请求参数错误: {message}")
                return {"success": False, "message": message}
                
            elif response.status_code == 429:
                # 请求频率限制
                message = result.get('message', '请求过于频繁，请稍后再试')
                logger.warning(f"请求频率限制: {message}")
                return {"success": False, "message": message}
                
            elif response.status_code == 500:
                # 服务器内部错误
                message = result.get('message', '服务器内部错误')
                logger.error(f"服务器错误: {message}")
                return {"success": False, "message": message}
                
            else:
                # 其他未知错误
                message = result.get('message', f'未知错误 (HTTP {response.status_code})')
                logger.error(f"短信发送失败: {message}")
                return {"success": False, "message": message}
                
        except httpx.TimeoutException:
            logger.error(f"短信发送超时: {self.api_url}")
            return {"success": False, "message": "短信发送超时"}
        except Exception as e:
            logger.error(f"发送短信失败: {e}")
            return {"success": False, "message": f"发送短信失败: {str(e)}"}
