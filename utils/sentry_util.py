"""
Sentry 错误监控工具类
提供统一的错误报警和性能监控功能
"""
import os
import logging
import yaml
from typing import Dict, Any, Optional
from enum import Enum
from config_util import get_config_path

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """报警级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class SentryUtil:
    """
    Sentry 工具类
    提供错误监控、性能追踪和报警功能
    """
    
    _initialized = False
    _enabled = False
    
    @classmethod
    def init_from_env(cls):
        """
        从配置文件初始化 Sentry
        
        配置文件路径由 config_util.get_config_path() 获取
        配置项：
            sentry.dsn: Sentry DSN URL（必需）
            sentry.environment: 环境名称，默认 "production"
        """
        sentry_dsn = None
        environment = "production"
        
        try:
            config_path = get_config_path()
            
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as file:
                    config = yaml.safe_load(file)
                    
                    # 从配置文件读取 sentry 配置
                    if config and "sentry" in config:
                        sentry_config = config["sentry"]
                        sentry_dsn = sentry_config.get("dsn")
                        environment = sentry_config.get("environment", "production")
            else:
                logger.warning(f"Configuration file not found: {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load Sentry config from file: {e}")
        
        # 初始化
        cls.init(
            dsn=sentry_dsn,
            environment=environment
        )
        
        # 输出初始化状态
        if cls.is_enabled():
            logger.info(f"✓ Sentry initialized (environment={environment})")
        else:
            logger.warning("✗ Sentry disabled (SENTRY_DSN not configured)")
    
    @classmethod
    def init(cls, dsn: Optional[str] = None, environment: str = "production"):
        """
        初始化 Sentry SDK
        
        Args:
            dsn: Sentry DSN URL，如果为 None 则从环境变量 SENTRY_DSN 读取
            environment: 环境名称，如 "production", "staging", "development"
        """
        if cls._initialized:
            logger.warning("Sentry already initialized")
            return
        
        # 从环境变量或参数获取 DSN
        sentry_dsn = dsn or os.getenv("SENTRY_DSN")
        
        if not sentry_dsn:
            logger.warning("Sentry DSN not provided, Sentry will be disabled")
            cls._enabled = False
            cls._initialized = True
            return
        
        try:
            import sentry_sdk
            
            # 初始化 Sentry（不启用自动日志捕获）
            sentry_sdk.init(
                dsn=sentry_dsn,
                environment=environment,
                # 禁用所有自动集成，只保留手动调用
                default_integrations=False,
                # 在发送前过滤敏感信息
                before_send=cls._before_send,
            )
            
            cls._enabled = True
            cls._initialized = True
            logger.info(f"Sentry initialized successfully (environment={environment})")
            
        except ImportError:
            logger.error("sentry-sdk not installed, please run: pip install sentry-sdk")
            cls._enabled = False
            cls._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Sentry: {str(e)}")
            cls._enabled = False
            cls._initialized = True
    
    @staticmethod
    def _before_send(event, hint):
        """
        在发送事件前处理，可用于过滤敏感信息
        
        Args:
            event: Sentry 事件
            hint: 提示信息
        
        Returns:
            处理后的事件，返回 None 则不发送
        """
        # 可以在这里过滤敏感信息
        # 例如：移除请求中的密码、token 等
        return event
    
    @classmethod
    def is_enabled(cls) -> bool:
        """
        检查 Sentry 是否已启用
        
        Returns:
            bool: 是否已启用
        """
        return cls._enabled
    
    @classmethod
    def capture_exception(cls, exception: Exception, **kwargs):
        """
        捕获异常并发送到 Sentry
        
        Args:
            exception: 异常对象
            **kwargs: 额外的上下文信息
        """
        if not cls._enabled:
            return
        
        try:
            import sentry_sdk
            
            # 设置额外的上下文
            if kwargs:
                with sentry_sdk.push_scope() as scope:
                    for key, value in kwargs.items():
                        scope.set_context(key, value)
                    sentry_sdk.capture_exception(exception)
            else:
                sentry_sdk.capture_exception(exception)
                
        except Exception as e:
            logger.error(f"Failed to capture exception in Sentry: {str(e)}")
    
    @classmethod
    def capture_message(cls, message: str, level: AlertLevel = AlertLevel.INFO, 
                       tags: Optional[Dict[str, str]] = None,
                       context: Optional[Dict[str, Any]] = None):
        """
        发送消息到 Sentry
        
        Args:
            message: 消息内容
            level: 消息级别
            tags: 标签字典，用于分类和过滤
            context: 上下文信息
        """
        if not cls._enabled:
            return
        
        try:
            import sentry_sdk
            
            with sentry_sdk.push_scope() as scope:
                # 设置标签
                if tags:
                    for key, value in tags.items():
                        scope.set_tag(key, value)
                
                # 设置上下文
                if context:
                    for key, value in context.items():
                        scope.set_context(key, value)
                
                # 发送消息
                sentry_sdk.capture_message(message, level=level.value)
                
        except Exception as e:
            logger.error(f"Failed to capture message in Sentry: {str(e)}")
    
    @classmethod
    def send_alert(cls, alert_type: str, message: str, 
                   level: AlertLevel = AlertLevel.ERROR,
                   context: Optional[Dict[str, Any]] = None):
        """
        发送报警信息到 Sentry
        
        Args:
            alert_type: 报警类型，如 "INVALID_RESPONSE_FORMAT", "UNEXPECTED_EXCEPTION"
            message: 报警消息
            level: 报警级别
            context: 上下文信息
        
        Example:
            SentryUtil.send_alert(
                alert_type="INVALID_RESPONSE_FORMAT",
                message="Sora2 API响应格式错误",
                context={
                    "api": "create_image_to_video",
                    "response": {...},
                    "task_id": 123
                }
            )
        """
        if not cls._enabled:
            logger.error(f"[ALERT] {alert_type}: {message}")
            if context:
                logger.error(f"[ALERT_CONTEXT] {context}")
            return
        
        try:
            import sentry_sdk
            
            with sentry_sdk.push_scope() as scope:
                # 设置标签
                scope.set_tag("alert_type", alert_type)
                scope.set_tag("alert", "true")
                
                # 设置上下文
                if context:
                    scope.set_context("alert_context", context)
                
                # 发送消息
                sentry_sdk.capture_message(
                    f"[{alert_type}] {message}",
                    level=level.value
                )
                
            logger.info(f"Alert sent to Sentry: {alert_type}")
            
        except Exception as e:
            logger.error(f"Failed to send alert to Sentry: {str(e)}")
            # 降级到日志记录
            logger.error(f"[ALERT] {alert_type}: {message}")
            if context:
                logger.error(f"[ALERT_CONTEXT] {context}")
    
    @classmethod
    def set_user(cls, user_id: str, username: Optional[str] = None, 
                 email: Optional[str] = None, **kwargs):
        """
        设置当前用户信息
        
        Args:
            user_id: 用户ID
            username: 用户名（可选）
            email: 邮箱（可选）
            **kwargs: 其他用户属性
        """
        if not cls._enabled:
            return
        
        try:
            import sentry_sdk
            
            user_data = {"id": user_id}
            if username:
                user_data["username"] = username
            if email:
                user_data["email"] = email
            user_data.update(kwargs)
            
            sentry_sdk.set_user(user_data)
            
        except Exception as e:
            logger.error(f"Failed to set user in Sentry: {str(e)}")
    
    @classmethod
    def set_tag(cls, key: str, value: str):
        """
        设置标签
        
        Args:
            key: 标签键
            value: 标签值
        """
        if not cls._enabled:
            return
        
        try:
            import sentry_sdk
            sentry_sdk.set_tag(key, value)
        except Exception as e:
            logger.error(f"Failed to set tag in Sentry: {str(e)}")
    
    @classmethod
    def set_context(cls, key: str, value: Dict[str, Any]):
        """
        设置上下文信息
        
        Args:
            key: 上下文键
            value: 上下文值（字典）
        """
        if not cls._enabled:
            return
        
        try:
            import sentry_sdk
            sentry_sdk.set_context(key, value)
        except Exception as e:
            logger.error(f"Failed to set context in Sentry: {str(e)}")
    
    @classmethod
    def start_transaction(cls, name: str, op: str = "task"):
        """
        开始一个性能追踪事务
        
        Args:
            name: 事务名称
            op: 操作类型，如 "task", "http.request", "db.query"
        
        Returns:
            事务对象，需要在完成后调用 finish()
        
        Example:
            transaction = SentryUtil.start_transaction("video_generation", "task")
            try:
                # 执行任务
                pass
            finally:
                transaction.finish()
        """
        if not cls._enabled:
            return None
        
        try:
            import sentry_sdk
            return sentry_sdk.start_transaction(name=name, op=op)
        except Exception as e:
            logger.error(f"Failed to start transaction in Sentry: {str(e)}")
            return None
