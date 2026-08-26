"""
ChatSession 类 - 聊天会话管理
负责管理单个聊天会话，包括 PM Agent 初始化、对话历史管理等
"""

import os
import logging
import litellm
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from script_writer_core.agents import TaskManager, PMAgent, MarketingPMAgent, ToolExecutor
from script_writer_core.file_manager import FileManager
from script_writer_core.file_operation_handler import FileOperationHandler
from script_writer_core.skill_loader import SkillLoader

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = str(Path(__file__).parent.parent)


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
        model_id: Optional[int] = None,
        text_to_image_model_id: Optional[int] = None,
        session_type: int = 1
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.world_id = world_id
        self.auth_token = auth_token
        self.text_to_image_model_id = text_to_image_model_id
        self.session_type = session_type

        # 初始化文件操作处理器（带权限控制和认证）
        self.file_handler = FileOperationHandler(user_id, world_id, auth_token, file_manager=file_manager)

        # 根据 session_type 选择不同的配置
        pm_config = agents_config.get("pm_agent", {})

        if session_type == 2:  # 营销智能体
            logger.info(f"[ChatSession] 初始化营销智能体 session {session_id}")

            # 从 agents/skills/marketing-pm/SKILL.md 加载提示词，并替换 {{SOP_INDEX}}
            from agents.skill_loader import SopLoader
            marketing_skill_loader = SkillLoader(skills_dir=os.path.join(PROJECT_ROOT, 'agents', 'skills'))
            sop_loader = SopLoader(os.path.join(PROJECT_ROOT, 'agents', 'skills', 'marketing-pm', 'sops'))

            # 加载 SKILL.md 内容，替换 {{SOP_INDEX}} 为自动扫描的 SOP 索引表
            raw_skill_prompt = marketing_skill_loader.get_skill_prompt('marketing-pm')
            pm_base_prompt = sop_loader.load_skill_with_index(raw_skill_prompt) if raw_skill_prompt else None

            # 无斜杠形式：DeepSeek 客户端不剥离 'deepseek/' 前缀，工厂按前缀路由到 DEEPSEEK 供应商
            pm_model = model if model else 'deepseek-v4-flash'
            pm_allowed_tools = ['call_agent', 'ask_user', 'load_sop']
            pm_skill_names = []  # 提示词已通过 base_prompt 注入，不再由 PMAgent 重复加载
            skip_env_context = True
        else:  # 剧本智能体（默认）
            logger.info(f"[ChatSession] 初始化剧本智能体 session {session_id}")

            # 为剧本智能体初始化 SOP 加载器，将工作流拆分为按需加载的 SOP
            from agents.skill_loader import SopLoader
            sop_loader = SopLoader(os.path.join(PROJECT_ROOT, 'script_writer_core', 'skills', 'script-orchestrator', 'sops'))

            # 加载 SKILL.md 内容，替换 {{SOP_INDEX}} 为自动扫描的 SOP 索引表
            script_skill_loader = SkillLoader(user_id=int(user_id) if user_id else None)
            raw_skill_prompt = script_skill_loader.get_skill_prompt('script-orchestrator')
            pm_base_prompt = sop_loader.load_skill_with_index(raw_skill_prompt) if raw_skill_prompt else None

            marketing_skill_loader = None
            pm_model = model if model else pm_config.get("model", "gemini/gemini-3-pro-preview")
            pm_allowed_tools = pm_config.get("allowed_tools", ["call_agent", "ask_user", "load_sop"])
            pm_skill_names = []  # 提示词已通过 base_prompt 注入（含 SOP 索引），不再由 PMAgent 重复加载
            skip_env_context = True

        logger.info(f"[ChatSession] PM Agent 将使用模型: {pm_model}")

        # 根据 model_id 获取模型的上下文窗口配置
        context_window = None
        if model_id is not None:
            try:
                from model.model import ModelModel
                model_entity = ModelModel.get_by_id(int(model_id))
                if model_entity:
                    context_window = model_entity.context_window
                    logger.info(f"[ChatSession] Loaded context_window={context_window} for model_id={model_id}")
            except Exception as e:
                logger.warning(f"[ChatSession] Failed to load context_window for model_id={model_id}: {e}")

        # 根据 session_type 创建不同的 PM Agent
        if session_type == 2:  # 营销智能体
            self.pm_agent = MarketingPMAgent(
                model=pm_model,
                allowed_tools=pm_allowed_tools,
                task_manager=task_manager,
                file_manager=file_manager,
                tool_executor=tool_executor,
                agents_config=agents_config,
                user_id=user_id,
                world_id=world_id,
                auth_token=auth_token,
                base_prompt=pm_base_prompt,
                sop_loader=sop_loader,
                skill_loader=marketing_skill_loader,
                max_consecutive_failures=pm_config.get("max_consecutive_failures", 3),
                max_total_failures=pm_config.get("max_total_failures", 7),
                context_window=context_window,
            )
        else:  # 剧本智能体（默认）
            self.pm_agent = PMAgent(
                model=pm_model,
                allowed_tools=pm_allowed_tools,
                task_manager=task_manager,
                file_manager=file_manager,
                tool_executor=tool_executor,
                agents_config=agents_config,
                user_id=user_id,
                world_id=world_id,
                auth_token=auth_token,
                max_consecutive_failures=pm_config.get("max_consecutive_failures", 3),
                max_total_failures=pm_config.get("max_total_failures", 7),
                context_window=context_window,
                base_prompt=pm_base_prompt,
                skill_loader=marketing_skill_loader,
                sop_loader=sop_loader,
                skill_names=pm_skill_names,
                skip_env_context=skip_env_context
            )
        logger.info(f"[ChatSession] PM Agent 初始化完成: {self.pm_agent.agent_id}")

        # 配置 LiteLLM
        self._setup_litellm()

        # 设置模型（默认使用 DeepSeek V4 Flash；原 Gemini 3 Flash Preview 已下线）
        self.model = model or "deepseek-v4-flash"
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
            self.pm_agent._ask_fail_count = 0  # 重置 ask_user 连续失败计数
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

    def compress_history(self, task) -> Dict[str, Any]:
        """
        手动压缩对话历史

        Args:
            task: 当前任务对象，包含模型配置信息

        Returns:
            Dict: 压缩结果
        """
        if not self.pm_agent:
            return {
                "success": False,
                "error": "PM Agent 未初始化"
            }

        try:
            result = self.pm_agent.force_compress(task)
            self.updated_at = datetime.now()
            return result
        except Exception as e:
            logger.error(f"压缩对话历史失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
