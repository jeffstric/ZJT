"""
视频生成驱动抽象基类
所有视频生成驱动都需要继承此基类并实现其抽象方法
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
import os
import json
import traceback
from datetime import datetime
import requests
from .exceptions import DriverConfigError

logger = logging.getLogger(__name__)


def _setup_api_logger():
    """设置 API 请求日志记录器"""
    api_logger = logging.getLogger("api_requests")
    if not api_logger.handlers:
        # 确保 logs 目录存在
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)

        # 创建文件处理器
        file_handler = logging.FileHandler(
            os.path.join(log_dir, "api_requests.log"),
            encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)

        # 设置日志格式
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        api_logger.addHandler(file_handler)
        api_logger.setLevel(logging.INFO)

    return api_logger


# 初始化 API 日志记录器
api_logger = _setup_api_logger()


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
    
    def _request(self, url: str, method: str = "POST", json: dict = None, headers: dict = None, **kwargs) -> dict:
        """
        统一 HTTP 请求方法。所有外部 API 调用都通过此方法。
        请求和响应会记录到 logs/api_requests.log

        Args:
            url: 请求URL
            method: HTTP方法，默认POST
            json: 请求体（JSON格式）
            headers: 请求头

        Returns:
            dict: API响应的JSON数据

        Raises:
            requests.RequestException: 请求失败时抛出
        """
        # 记录请求日志
        request_time = datetime.now().isoformat()
        api_logger.info(f"========== API 请求开始 ==========")
        api_logger.info(f"Driver: {self.driver_name}")
        api_logger.info(f"Time: {request_time}")
        api_logger.info(f"Method: {method}")
        api_logger.info(f"URL: {url}")
        api_logger.info(f"Headers: {self._mask_sensitive_headers(headers)}")
        api_logger.info(f"Payload: {self._mask_sensitive_payload(json)}")

        try:
            response = requests.request(method, url, json=json, headers=headers, **kwargs)
            response_time = datetime.now().isoformat()

            # 记录响应日志
            api_logger.info(f"Response Time: {response_time}")
            api_logger.info(f"Status Code: {response.status_code}")
            api_logger.info(f"Response Headers: {dict(response.headers)}")

            try:
                result = response.json()
                api_logger.info(f"Response Body: {result}")
            except:
                result = {}
                api_logger.info(f"Response Body (raw): {response.text[:1000]}")

            api_logger.info(f"========== API 请求结束 ==========")

            response.raise_for_status()
            return result

        except Exception as e:
            api_logger.error(f"Request Error: {str(e)}")
            api_logger.error(f"Traceback: {traceback.format_exc()}")
            api_logger.info(f"========== API 请求失败 ==========")
            raise

    def _mask_sensitive_headers(self, headers: dict) -> dict:
        """脱敏请求头中的敏感信息"""
        if not headers:
            return {}
        masked = headers.copy()
        for key in masked:
            if key.lower() in ["authorization", "x-api-key", "api-key"]:
                value = masked[key]
                if len(value) > 20:
                    masked[key] = value[:10] + "***" + value[-4:]
                else:
                    masked[key] = "***"
        return masked

    def _mask_sensitive_payload(self, payload: dict) -> dict:
        """脱敏请求体中的敏感信息（递归处理嵌套字典）"""
        if not payload:
            return {}

        sensitive_keys = ["apikey", "api_key", "secret", "password", "token", "key"]
        masked = {}
        for key, value in payload.items():
            if key.lower() in sensitive_keys:
                str_value = str(value)
                if len(str_value) > 10:
                    masked[key] = str_value[:4] + "***" + str_value[-4:]
                else:
                    masked[key] = "***"
            elif isinstance(value, dict):
                masked[key] = self._mask_sensitive_payload(value)
            elif isinstance(value, list):
                masked[key] = [self._mask_sensitive_payload(item) if isinstance(item, dict) else item for item in value]
            else:
                masked[key] = value
        return masked
    
    @abstractmethod
    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建任务的完整请求参数
        
        Args:
            ai_tool: AITool 对象
        
        Returns:
            Dict[str, Any]: 请求参数字典
                - url: 请求URL
                - method: HTTP方法（通常为POST）
                - json: 请求体（JSON格式）
                - headers: 请求头
        
        Example:
            {
                "url": "https://api.example.com/v1/videos/generations",
                "method": "POST",
                "json": {
                    "model": "sora-2-temporary",
                    "prompt": "测试提示词",
                    "aspect_ratio": "9:16"
                },
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer xxx"
                }
            }
        """
        pass
    
    @abstractmethod
    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的完整请求参数
        
        Args:
            project_id: 外部API返回的任务ID
        
        Returns:
            Dict[str, Any]: 请求参数字典
                - url: 请求URL
                - method: HTTP方法（GET或POST）
                - json: 请求体（可选，仅POST时需要）
                - headers: 请求头
        
        Example (GET):
            {
                "url": "https://api.example.com/v1/videos/tasks/task_123",
                "method": "GET",
                "headers": {
                    "Authorization": "Bearer xxx"
                }
            }
        
        Example (POST):
            {
                "url": "https://api.example.com/task/status",
                "method": "POST",
                "json": {
                    "apiKey": "xxx",
                    "taskId": "task_123"
                },
                "headers": {
                    "Content-Type": "application/json"
                }
            }
        """
        pass
    
    def _validate_required(self, configs: Dict[str, str]) -> None:
        """
        验证必要配置是否存在
        
        Args:
            configs: 配置字典，格式为 {"配置名称": 配置值}
        
        Raises:
            DriverConfigError: 当有配置缺失时抛出
        
        Example:
            self._validate_required({
                "Duomi API Token": self._token,
                "RunningHub API Key": self._api_key,
            })
        """
        missing = [name for name, value in configs.items() if not value]
        if missing:
            raise DriverConfigError(self.driver_name, missing)
    
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
