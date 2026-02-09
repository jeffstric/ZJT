"""
视频生成驱动抽象基类
所有视频生成驱动都需要继承此基类并实现其抽象方法
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseVideoDriver(ABC):
    """
    视频生成驱动抽象基类
    
    所有视频生成驱动必须继承此类并实现以下方法：
    - submit_task: 提交任务到外部API
    - check_status: 检查任务状态
    """
    
    def __init__(self, driver_name: str, driver_type: int):
        """
        初始化视频驱动
        
        Args:
            driver_name: 模型名称，如 "sora2", "ltx2", "wan22" 等
            driver_type: 模型类型，对应 ai_tools 表的 type 字段
        """
        self.driver_name = driver_name
        self.driver_type = driver_type
        self.logger = logging.getLogger(f"{__name__}.{driver_name}")
    
    @abstractmethod
    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交任务到外部API
        
        Args:
            ai_tool: AITool 对象，包含任务所需的所有参数
                - prompt: 提示词
                - image_path: 图片路径（可选）
                - ratio: 视频比例
                - duration: 视频时长
                - 其他模型特定参数
        
        Returns:
            Dict[str, Any]: 返回结果字典
                成功时包含:
                    - success: True
                    - project_id: 外部API返回的任务ID
                    - message: 成功信息（可选）
                失败时包含:
                    - success: False
                    - error: 错误信息（用户可见的友好提示）
                    - error_type: 错误类型，"USER" 或 "SYSTEM"
                        - "USER": 用户可见的错误（如参数错误、业务逻辑错误）
                        - "SYSTEM": 系统级错误（如API格式错误、系统异常）
                    - error_detail: 详细错误信息（仅 error_type="SYSTEM" 时提供，用于内部排查）
                    - retry: 是否需要重试（可选，默认False）
        
        Example:
            成功:
            {
                "success": True,
                "project_id": "task_123456"
            }
            
            用户错误:
            {
                "success": False,
                "error": "网络连接异常，请稍后重试",
                "error_type": "USER",
                "retry": True
            }
            
            系统错误:
            {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": "API响应格式错误: 缺少id字段",
                "retry": False
            }
        """
        pass
    
    @abstractmethod
    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查任务状态
        
        Args:
            project_id: 外部API返回的任务ID
        
        Returns:
            Dict[str, Any]: 返回结果字典
                - status: 任务状态
                    - "RUNNING": 处理中
                    - "SUCCESS": 成功
                    - "FAILED": 失败
                - result_url: 结果视频URL（status为SUCCESS时必须提供）
                - error: 错误信息（status为FAILED时提供，用户可见的友好提示）
                - error_type: 错误类型（status为FAILED时提供），"USER" 或 "SYSTEM"
                    - "USER": 用户可见的错误（如业务逻辑错误）
                    - "SYSTEM": 系统级错误（如API格式错误、系统异常）
                - error_detail: 详细错误信息（仅 error_type="SYSTEM" 时提供，用于内部排查）
        
        Example:
            成功:
            {
                "status": "SUCCESS",
                "result_url": "https://example.com/video.mp4"
            }
            
            处理中:
            {
                "status": "RUNNING"
            }
            
            用户错误:
            {
                "status": "FAILED",
                "error": "图片包含真人，无法处理",
                "error_type": "USER"
            }
            
            系统错误:
            {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": "API响应格式错误: 缺少data字段"
            }
        """
        pass
    
    def validate_parameters(self, ai_tool) -> tuple[bool, Optional[str]]:
        """
        验证任务参数是否有效
        
        Args:
            ai_tool: AITool 对象
        
        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)
        
        Note:
            子类可以重写此方法以实现特定的参数验证逻辑
        """
        # 基础验证：检查必需参数
        if not ai_tool.prompt and not ai_tool.image_path:
            return False, "缺少提示词或图片"
        
        return True, None
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        获取模型信息
        
        Returns:
            Dict[str, Any]: 模型信息字典
        """
        return {
            "driver_name": self.driver_name,
            "driver_type": self.driver_type
        }
    
    def __str__(self):
        return f"{self.__class__.__name__}(driver_name={self.driver_name}, driver_type={self.driver_type})"
    
    def __repr__(self):
        return self.__str__()
