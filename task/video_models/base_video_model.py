"""
视频生成模型抽象基类
所有视频生成模型都需要继承此基类并实现其抽象方法
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseVideoModel(ABC):
    """
    视频生成模型抽象基类
    
    所有视频生成模型必须继承此类并实现以下方法：
    - submit_task: 提交任务到外部API
    - check_status: 检查任务状态
    """
    
    def __init__(self, model_name: str, model_type: int):
        """
        初始化视频模型
        
        Args:
            model_name: 模型名称，如 "sora2", "ltx2", "wan22" 等
            model_type: 模型类型，对应 ai_tools 表的 type 字段
        """
        self.model_name = model_name
        self.model_type = model_type
        self.logger = logging.getLogger(f"{__name__}.{model_name}")
    
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
                    - error: 错误信息
                    - retry: 是否需要重试（可选，默认False）
        
        Example:
            {
                "success": True,
                "project_id": "task_123456"
            }
            或
            {
                "success": False,
                "error": "API调用失败",
                "retry": True
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
                - error: 错误信息（status为FAILED时提供）
        
        Example:
            {
                "status": "SUCCESS",
                "result_url": "https://example.com/video.mp4"
            }
            或
            {
                "status": "FAILED",
                "error": "视频生成失败"
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
            "model_name": self.model_name,
            "model_type": self.model_type
        }
    
    def __str__(self):
        return f"{self.__class__.__name__}(model_name={self.model_name}, model_type={self.model_type})"
    
    def __repr__(self):
        return self.__str__()
