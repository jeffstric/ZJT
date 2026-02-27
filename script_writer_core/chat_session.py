"""
ChatSession 类 - 聊天会话管理
负责管理单个聊天会话，包括 PM Agent 初始化、对话历史管理等
"""

import os
import logging
import litellm
from datetime import datetime
from typing import Optional

from script_writer_core.agents import TaskManager, PMAgent, ToolExecutor
from script_writer_core.file_manager import FileManager
from script_writer_core.file_operation_handler import FileOperationHandler

logger = logging.getLogger(__name__)


class ChatSession:
    """聊天会话管理类"""
    
    def __init__(
        self, 
        session_id: str,
        task_manager: TaskManager,
        file_manager: FileManager,
        tool_executor: ToolExecutor,
        agents_config: dict,
        system_prompt: Optional[str] = None,
        user_id: str = "1",
        world_id: str = "1",
        auth_token: str = "",
        model: Optional[str] = None,
        model_id: Optional[int] = None
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.world_id = world_id
        self.auth_token = auth_token
        
        # 初始化文件操作处理器（带权限控制和认证）
        self.file_handler = FileOperationHandler(user_id, world_id, auth_token, file_manager=file_manager)
        
        # 初始化 PM Agent（多智能体模式）
        logger.warning(f"[DEBUG] 开始初始化 PM Agent for session {session_id}")
        
        pm_config = agents_config.get("pm_agent", {})
        
        # 使用传入的 model 参数，如果没有则使用配置文件中的模型
        pm_model = model if model else pm_config.get("model", "gemini/gemini-3-pro-preview")
        logger.warning(f"[DEBUG] PM Agent 将使用模型: {pm_model}")
        
        self.pm_agent = PMAgent(
            model=pm_model,
            allowed_tools=pm_config.get("allowed_tools", ["skill", "request_human_verification"]),
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config,
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            max_consecutive_failures=pm_config.get("max_consecutive_failures", 3),
            max_total_failures=pm_config.get("max_total_failures", 7)
        )
        logger.warning(f"[DEBUG] PM Agent 初始化完成: {self.pm_agent.agent_id}")
        
        # 配置 LiteLLM
        self._setup_litellm()
        
        # 设置模型（默认使用 Gemini 3 Flash Preview）
        self.model = model or "gemini-3-flash-preview"
        self.model_id = model_id  # 存储模型ID
        
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
    
    def _setup_litellm(self):
        """配置 LiteLLM"""
        # 获取 Anthropic 配置
        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        anthropic_base_url = os.environ.get("ANTHROPIC_BASE_URL")
        
        # 获取 Jiekou.ai Gemini 配置
        jiekou_api_key = os.environ.get("JIEKOU_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        jiekou_base_url = os.environ.get("JIEKOU_BASE_URL") or os.environ.get("GOOGLE_GEMINI_BASE_URL")
        
        # 设置 LiteLLM 环境变量
        if anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key
        if anthropic_base_url:
            os.environ["ANTHROPIC_BASE_URL"] = anthropic_base_url
        if jiekou_api_key:
            os.environ["JIEKOU_API_KEY"] = jiekou_api_key
            os.environ["GOOGLE_API_KEY"] = jiekou_api_key
            os.environ["GEMINI_API_KEY"] = jiekou_api_key
        if jiekou_base_url:
            os.environ["JIEKOU_BASE_URL"] = jiekou_base_url
            os.environ["GOOGLE_GEMINI_BASE_URL"] = jiekou_base_url
            
        # 配置 LiteLLM 设置
        litellm.set_verbose = False  # 关闭详细日志
        litellm.drop_params = True   # 自动删除不支持的参数

    def get_history(self):
        """获取对话历史"""
        if self.pm_agent:
            return self.pm_agent.conversation_history
        return []
    
    def clear_history(self):
        """清空对话历史"""
        if self.pm_agent:
            self.pm_agent.clear_history()
        self.updated_at = datetime.now()
    
    def set_model(self, model: str, model_id: Optional[int] = None) -> bool:
        """
        切换 AI 模型
        
        Args:
            model: 模型名称
            model_id: 模型ID（可选）
        
        Returns:
            bool: 切换是否成功
        """
        self.model = model
        if model_id is not None:
            self.model_id = model_id
        
        # 同时更新 pm_agent 的模型，确保 API 调用使用正确的模型
        if hasattr(self, 'pm_agent') and self.pm_agent:
            self.pm_agent.model = model
            logger.info(f"Session {self.session_id}: 已更新 PM Agent 模型为 {model}")
        
        self.updated_at = datetime.now()
        return True
