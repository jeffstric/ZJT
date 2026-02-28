"""
短信发送驱动工厂类
"""
import logging
from typing import Optional
from config.config_util import get_config_value
from .base_sms_driver import BaseSmsDriver
from .legacy_sms_driver import LegacySmsDriver
from .api_sms_driver import ApiSmsDriver

logger = logging.getLogger(__name__)


class SmsDriverFactory:
    """短信发送驱动工厂类"""
    
    # 驱动类型映射
    DRIVER_MAP = {
        'legacy': LegacySmsDriver,
        'perseids': ApiSmsDriver,  # 别名
    }
    
    _instance: Optional[BaseSmsDriver] = None
    _current_agent: Optional[str] = None
    
    @classmethod
    def get_driver(cls) -> Optional[BaseSmsDriver]:
        """
        获取短信发送驱动实例（单例模式）
        
        根据配置文件中的 active_driver 自动选择对应的驱动
        
        Returns:
            短信驱动实例，如果配置不存在或无效则返回None
        """
        # 如果已有实例，直接返回
        if cls._instance is not None:
            return cls._instance
        
        try:
            # 从配置文件读取短信配置
            sms_config = get_config_value('sms', default={})
            agents = sms_config.get('agents', {})
            
            # 获取全局active_driver配置
            active_driver = sms_config.get('active_driver')
            if not active_driver:
                logger.error("未配置 active_driver，请在配置文件中设置 sms.active_driver")
                return None
            
            driver_type = active_driver
            logger.info(f"使用全局驱动配置: {driver_type}")
            
            # 查找匹配该驱动类型的agent配置
            matched_agent = None
            agent_config = None
            for agent_name, agent_cfg in agents.items():
                if agent_cfg.get('driver', '').lower() == driver_type.lower():
                    matched_agent = agent_name
                    agent_config = agent_cfg
                    logger.info(f"自动选择agent: {matched_agent}")
                    break
            
            if not matched_agent:
                logger.error(f"未找到驱动类型为 {driver_type} 的agent配置")
                return None
            
            # 获取驱动类
            driver_class = cls.DRIVER_MAP.get(driver_type.lower())
            if not driver_class:
                logger.error(f"不支持的短信驱动类型: {driver_type}")
                return None
            
            # 创建驱动实例
            cls._instance = driver_class(agent_config)
            cls._current_agent = matched_agent
            
            logger.info(f"创建短信驱动成功: agent={matched_agent}, driver={driver_type}")
            return cls._instance
            
        except Exception as e:
            logger.error(f"创建短信驱动失败: {e}")
            return None
    
    @classmethod
    def send_code(cls, phone: str, code: str) -> dict:
        """
        发送验证码（便捷方法）
        
        Args:
            phone: 手机号
            code: 验证码
            
        Returns:
            {"success": bool, "message": str}
        """
        driver = cls.get_driver()
        if not driver:
            return {"success": False, "message": "未找到短信驱动"}
        
        return driver.send_code(phone, code)
