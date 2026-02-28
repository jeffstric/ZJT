"""
短信发送驱动抽象基类
"""
from abc import ABC, abstractmethod
from typing import Dict


class BaseSmsDriver(ABC):
    """短信发送驱动抽象基类"""
    
    def __init__(self, config: Dict):
        """
        初始化驱动
        
        Args:
            config: 驱动配置字典
        """
        self.config = config
    
    @abstractmethod
    def send_code(self, phone: str, code: str) -> Dict[str, any]:
        """
        发送验证码短信
        
        Args:
            phone: 手机号
            code: 验证码
            
        Returns:
            {"success": bool, "message": str}
        """
        pass
    
    def validate_config(self) -> bool:
        """
        验证配置是否完整
        
        Returns:
            配置是否有效
        """
        return True
