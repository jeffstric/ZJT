import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base_agent import BaseAgent, InsufficientComputingPowerError, check_computing_power_sync
from .expert_agent import ExpertAgent
from .ask_user_mixin import AskUserMixin
from .summarizer import ConversationSummarizer
from .task_manager import TaskManager, AgentTask
from .tool_definitions import ASK_USER_TOOL_DEFINITION, LOAD_SOP_TOOL_DEFINITION
from llm.llm_client_factory import get_llm_client
from script_writer_core.file_manager import FileManager
from script_writer_core.skill_loader import SkillLoader
from agents.skill_loader import SopLoader
from model.model import ModelModel
import json
import uuid

logger = logging.getLogger(__name__)


def _get_session_storage():
    """延迟导入 session_storage 以避免循环导入"""
    from api.script_writer import session_storage
    return session_storage


class PMAgent(BaseAgent, AskUserMixin):
    """项目经理智能体 - 负责任务拆分、派发、验证、协调"""

    def __init__(
        self,
        model: str,
        allowed_tools: List[str],
        task_manager: TaskManager,
        file_manager: FileManager,
        tool_executor: Any,
        agents_config: Dict[str, Any],
        user_id: str,
        world_id: str,
        auth_token: str,
        max_consecutive_failures: int = 3,
        max_total_failures: int = 7,
        context_window: Optional[int] = None,
        base_prompt: Optional[str] = None,
        skill_loader: Optional[SkillLoader] = None,
        sop_loader: Optional[SopLoader] = None,
        skill_names: Optional[List[str]] = None,
        skip_env_context: bool = False
    ):
        agent_id = "pm_agent"

        # 初始化技能加载器（支持用户级自定义 skill）
        self.skill_loader = skill_loader or SkillLoader(user_id=int(user_id) if user_id else None)

        # 从配置文件获取技能名称列表
        pm_skill_names = skill_names or agents_config.get("pm_agent", {}).get("skills", ["script-orchestrator"])

        # 保存自定义 base_prompt（用于 _build_system_prompt）
        self._custom_base_prompt = base_prompt
        self.sop_loader = sop_loader

        # 构建基础 system prompt
        base_system_prompt = self._build_system_prompt(pm_skill_names)

        # 保存 file_manager 和其他属性
        self.task_manager = task_manager
        self.file_manager = file_manager
        self.tool_executor = tool_executor
        self.agents_config = agents_config
        self.allowed_expert_types = agents_config.get("pm_agent", {}).get("allowed_expert_types")
        self.user_id = user_id
        self.world_id = world_id
        self.auth_token = auth_token

        # 获取环境上下文并构建增强的 system prompt（只在初始化时执行一次）
        if skip_env_context:
            enhanced_system_prompt = base_system_prompt
        else:
            # 使用摘要模式，只返回前200字符，避免初始化时加载过多内容
            env_context = self.file_manager.get_context_for_ai(user_id, world_id, summary_only=True)

            # 如果环境上下文超过5万字，进行截断
            max_chars = 5000
            if len(env_context) > max_chars:
                logger.info(f"{agent_id}: Environment context exceeds {max_chars} chars ({len(env_context)}), truncating...")
                env_context = self._truncate_environment_context(env_context, user_id, world_id, max_chars)

            # 构建增强的 system prompt（包含环境上下文）
            enhanced_system_prompt = (
                f"{base_system_prompt}\n\n"
                f"{'='*60}\n"
                f"# 【重要】当前项目已有的环境内容\n\n"
                f"**注意**：以下是项目中已经存在的所有内容，包括世界设定、剧本、角色、场景、道具。\n"
                f"在制定创作计划时，你必须：\n"
                f"1. 仔细阅读已有的剧本内容，了解故事进展\n"
                f"2. 确保新内容与现有角色、场景、道具保持一致\n"
                f"3. 续集剧本要承接已有剧情，保持连贯性\n\n"
                f"{'='*60}\n\n"
                f"{env_context}\n\n"
                f"{'='*60}\n"
                f"以上是已有内容。请基于这些信息进行创作规划。\n"
                f"{'='*60}"
            )

        if skip_env_context:
            logger.info(f"{agent_id}: Built system prompt without environment context (total: {len(enhanced_system_prompt)} chars)")
        else:
            logger.info(f"{agent_id}: Built enhanced system prompt with environment context ({len(env_context)} chars, total: {len(enhanced_system_prompt)} chars)")

        super().__init__(
            agent_id=agent_id,
            skill_names=pm_skill_names,
            model=model,
            allowed_tools=allowed_tools,
            system_prompt=enhanced_system_prompt
        )

        self.task_queue: List[Dict[str, Any]] = []
        self.completed_tasks: List[Dict[str, Any]] = []
        self.current_task: Optional[Dict[str, Any]] = None
        self.current_expert: Optional[ExpertAgent] = None
        self.execution_lock = False

        self.consecutive_failures = 0
        self.total_failures = 0
        self.max_consecutive_failures = max_consecutive_failures
        self.max_total_failures = max_total_failures
        self.context_window = context_window
        self.last_api_input_tokens = 0
        # 暂时没有对 内容进行压缩
        self.summarizer = ConversationSummarizer()

        # 将 system 提示词添加到对话历史（用于日志记录）
        self.add_to_history("system", self.system_prompt)
        logger.info(f"{self.agent_id}: Added system prompt to conversation_history (length: {len(self.system_prompt)} chars)")
        logger.info(f"{self.agent_id}: conversation_history now has {len(self.conversation_history)} messages")

    def _build_system_prompt(self, skill_names: List[str]) -> str:
        """构建系统提示"""
        base_prompt = self._custom_base_prompt or """你是剧本架构师（Script Orchestrator），负责协调专家智能体完成剧本创作。

**核心原则**：
- 你是协调者，不是内容创作者
- 严禁直接编写剧本、角色卡、场景描述、道具信息等内容
- 所有内容创作必须通过调用对应的专家智能体完成

**可用工具**：
1. call_agent(AgentName, task_description): 调用专家智能体执行任务
2. ask_user(question, options, context): 向用户提问并等待回答

**约束**：
- 任务必须串行执行，一次只能调用一个专家
- 连续失败3次或累计失败7次时必须停止并报告
- 绝不直接生成剧本内容，必须通过 call_agent 调用专家
- 向用户提问时必须使用 ask_user 工具，禁止以纯文本方式提问（纯文本提问用户无法收到交互弹框）
"""

        # 加载所有技能内容
        skill_prompts = []
        for skill_name in skill_names:
            skill_prompt = self.skill_loader.get_skill_prompt(skill_name)
            if skill_prompt:
                logger.info(f"Successfully loaded {skill_name} skill content ({len(skill_prompt)} chars)")
                skill_prompts.append((skill_name, skill_prompt))
            else:
                logger.warning(f"Failed to load {skill_name} skill, skipping")

        # 如果成功加载技能内容，则附加到提示词中
        if skill_prompts:
            skills_section = "\n\n" + "="*60 + "\n**你的核心技能**\n" + "="*60 + "\n\n"
            for skill_name, skill_prompt in skill_prompts:
                skills_section += f"\n### 技能：{skill_name}\n\n{skill_prompt}\n\n{'-'*60}\n"
            return base_prompt + skills_section
        else:
            return base_prompt

    def execute(self, task: AgentTask, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行主任务"""
        logger.info(f"{self.agent_id}: Starting execution for task {task.task_id}")

        # 设置 task_id，供 AskUserMixin 使用
        self.task_id = task.task_id

        # 设置逐条消息持久化上下文。__init__ 阶段 recorder 还未绑定 session，
        # system prompt 和工具定义需要在任务开始时补写到 chat_messages。
        self._session_id = task.session_id
        self._task_id = task.task_id
        self._vendor_id = task.vendor_id
        self._agent_scope = "pm"
        try:
            from script_writer_core.conversation_recorder import ConversationRecorder
            self._conversation_recorder = ConversationRecorder()
        except Exception as e:
            logger.error(f"{self.agent_id}: Failed to initialize ConversationRecorder: {e}")
            self._conversation_recorder = None

        # 保存当前任务的语言设置
        self.current_language = task.language
        logger.info(f"{self.agent_id}: Language set to '{task.language}' (current_language={self.current_language})")

        if self._conversation_recorder and self._session_id:
            try:
                system_content = self.system_prompt
                if self.current_language and self.current_language != 'zh-CN':
                    from config.constant import LANGUAGE_INSTRUCTIONS
                    lang_instruction = LANGUAGE_INSTRUCTIONS.get(self.current_language, '')
                    if lang_instruction:
                        system_content += lang_instruction

                self._conversation_recorder.append_message(
                    session_id=self._session_id,
                    role="system",
                    content=system_content,
                    message_type="system_prompt",
                    visibility="llm",
                    agent_scope="pm",
                    source="system",
                )
                logger.info(f"{self.agent_id}: Persisted system prompt to DB ({len(system_content)} chars)")
            except Exception as e:
                logger.error(f"{self.agent_id}: Failed to persist system prompt to DB: {e}")

            try:
                tool_defs = self._get_tool_definitions()
                if tool_defs:
                    self._conversation_recorder.append_message(
                        session_id=self._session_id,
                        role="system",
                        content={"tools": tool_defs},
                        message_type="tool_definitions",
                        visibility="internal",
                        agent_scope="pm",
                        source="system",
                    )
                    logger.info(f"{self.agent_id}: Persisted tool_definitions to DB ({len(tool_defs)} tools)")
            except Exception as e:
                logger.error(f"{self.agent_id}: Failed to persist tool_definitions to DB: {e}")

        # 重置失败计数器，确保每个新任务独立（避免算力不足停止后残留计数导致新任务立即失败）
        self.consecutive_failures = 0
        self.total_failures = 0

        try:
            # 添加用户消息到历史（图片、视频、音频以文字标签形式注入，不需要 base64）
            combined_parts = []
            if task.image_urls:
                for i, image_url in enumerate(task.image_urls):
                    thumb = ""
                    if task.thumbnail_urls and i < len(task.thumbnail_urls) and task.thumbnail_urls[i]:
                        thumb = f" thumb: {task.thumbnail_urls[i]}"
                    combined_parts.append(f"[图片{i + 1}]（URL: {image_url}{thumb}）")
            if task.video_urls:
                for i, video_url in enumerate(task.video_urls):
                    combined_parts.append(f"[视频{i + 1}]（URL: {video_url}）")
            if task.audio_urls:
                for i, audio_url in enumerate(task.audio_urls):
                    combined_parts.append(f"[音频{i + 1}]（URL: {audio_url}）")
            if combined_parts:
                combined = "\n".join(combined_parts) + "\n\n" + task.user_message
                self.add_to_history(
                    "user",
                    combined,
                    extra_meta={"idempotency_key": f"task:{task.task_id}:user:initial"}
                )
            else:
                self.add_to_history(
                    "user",
                    task.user_message,
                    extra_meta={"idempotency_key": f"task:{task.task_id}:user:initial"}
                )

            # 执行 PM 循环
            result = self._run_pm_loop(task, session_data)

            logger.info(f"{self.agent_id}: Execution completed")
            return {
                "success": True,
                "result": result,
                "completed_tasks": self.completed_tasks
            }

        except Exception as e:
            logger.error(f"{self.agent_id}: Execution failed - {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "completed_tasks": self.completed_tasks
            }

    def _run_pm_loop(self, task: AgentTask, session_data: Dict[str, Any], max_iterations: int = 50) -> str:
        """运行 PM 主循环"""
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            should_stop, reason = self.should_stop()
            if should_stop:
                logger.info(f"{self.agent_id}: Stopping - {reason}")
                self.task_manager.push_message(task.task_id, 'message', {
                    'role': 'assistant',
                    'content': f"任务执行停止: {reason}"
                })
                return f"任务执行停止: {reason}"

            # 检查算力是否充足
            try:
                check_computing_power_sync(self.auth_token, self.agent_id)
            except InsufficientComputingPowerError as e:
                logger.warning(f"{self.agent_id}: 算力不足，停止任务 - {e.message}")
                self.task_manager.push_message(task.task_id, 'message', {
                    'role': 'assistant',
                    'content': f"任务执行停止: {e.message}"
                })
                return f"任务执行停止: {e.message}"

            logger.info(f"{self.agent_id}: PM Loop iteration {iteration}/{max_iterations}")

            self.task_manager.push_message(task.task_id, 'progress', {
                'progress': iteration / max_iterations,
                'step': f"执行中 ({iteration}/{max_iterations})"
            })

            try:
                # 在构建 API 消息前检查是否需要压缩上下文
                if self._should_compress():
                    logger.warning(f"{self.agent_id}: 上下文窗口使用率超过90%，触发历史压缩")
                    self._compress_conversation_history(task)
                    # 向前端发送压缩事件通知
                    self.task_manager.push_message(task.task_id, 'context_compression', {
                        'compressed': True,
                        'reason': '上下文窗口使用率超过90%',
                        'history_count': len(self.conversation_history)
                    })

                # 构建消息列表（使用初始化时已包含环境上下文的 system_prompt）
                messages = self._build_messages_for_api()

                # 获取工具定义，优先使用 LLMContextBuilder 从 DB 恢复的 tool_definitions
                if hasattr(self, '_current_llm_context') and self._current_llm_context and self._current_llm_context.tools:
                    tool_definitions = self._current_llm_context.tools
                else:
                    tool_definitions = self._get_tool_definitions()

                # 从数据库获取模型的最大输出 token 数
                max_output_tokens = 65536  # 默认值
                try:
                    if task.model_id:
                        model = ModelModel.get_by_id(task.model_id)
                        if model and model.max_output_tokens:
                            max_output_tokens = model.max_output_tokens
                            logger.info(f"{self.agent_id}: Using model max_output_tokens: {max_output_tokens}")
                except Exception as e:
                    logger.warning(f"{self.agent_id}: Failed to get model info for max_output_tokens: {e}")

                # 使用 LLM 客户端工厂获取对应模型的客户端并调用 API
                # 传入 vendor_id 确保正确路由到目标供应商（如 zjt_api）
                history_len = len(self.conversation_history)  # 记录调用前的历史长度，用于异常时截断
                response = get_llm_client(self.model, vendor_id=task.vendor_id).call_api(
                    model=self.model,
                    messages=messages,
                    tools=tool_definitions,
                    temperature=1,
                    max_tokens=max_output_tokens,
                    auth_token=task.auth_token,
                    vendor_id=task.vendor_id,
                    model_id=task.model_id,
                    enable_thinking=task.enable_thinking,
                    thinking_effort=task.thinking_effort,
                    agent_id=self.agent_id,
                    agent_scope="pm"
                )

                # 更新最后一次 API 调用的真实 input token 数，用于后续压缩判断
                if response.usage:
                    self.last_api_input_tokens = response.usage.get("input_token", 0) or response.usage.get("prompt_tokens", 0) or 0
                    logger.info(f"{self.agent_id}: 本次 API input_tokens={self.last_api_input_tokens}")

                message = response.choices[0].message

                if hasattr(message, 'tool_calls') and message.tool_calls:
                    self._handle_tool_calls(message, task, session_data)
                else:
                    content = message.content or ""
                    reasoning_content = getattr(message, 'reasoning_content', None)
                    if reasoning_content:
                        history_content = {"text": content, "reasoning_content": reasoning_content}
                    else:
                        history_content = content
                    logger.info(f"{self.agent_id}: Adding assistant response to history (length: {len(content)} chars, has_reasoning={reasoning_content is not None})")
                    self.add_to_history("assistant", history_content)
                    logger.info(f"{self.agent_id}: conversation_history now has {len(self.conversation_history)} messages")

                    logger.warning(f"[DUPLICATE-DEBUG] About to push PM message: task_id={task.task_id}, content_preview={content[:100]}...")
                    self.task_manager.push_message(task.task_id, 'message', {
                        'role': 'assistant',
                        'content': content
                    })

                    logger.info(f"{self.agent_id}: PM completed with response")
                    return content

            except InsufficientComputingPowerError as e:
                # 截断历史，移除不完整的 tool_calls 消息（防止重试时 LLM 报错）
                logger.info(f"{self.agent_id}: 截断不完整的历史，从 {len(self.conversation_history)} 恢复到 {history_len}")
                self.conversation_history = self.conversation_history[:history_len]
                logger.warning(f"{self.agent_id}: 算力不足 - {e.message}")
                self.task_manager.push_message(task.task_id, 'message', {
                    'role': 'assistant',
                    'content': f"任务执行停止: {e.message}"
                })
                return f"任务执行停止: {e.message}"
            except Exception as e:
                # 截断历史，移除可能不完整的 tool_calls/tool 消息（防止重试时 LLM 报错）
                if len(self.conversation_history) > history_len:
                    logger.info(f"{self.agent_id}: 截断不完整的历史，从 {len(self.conversation_history)} 恢复到 {history_len}")
                    self.conversation_history = self.conversation_history[:history_len]
                logger.error(f"{self.agent_id}: Error in PM loop - {e}", exc_info=True)
                self.total_failures += 1
                self.consecutive_failures += 1

                self.task_manager.push_message(task.task_id, 'error', {
                    'error': str(e)
                })

        logger.warning(f"{self.agent_id}: Max iterations reached")
        return "任务执行达到最大迭代次数"

    def _handle_tool_calls(self, message, task: AgentTask, session_data: Dict[str, Any]):
        """处理工具调用"""
        tool_calls = message.tool_calls

        # 向前端推送工具调用事件，实时显示正在调用的函数
        tool_names = [tc.function.name for tc in tool_calls]
        self.task_manager.push_message(task.task_id, 'tool_call', {
            'tool_names': tool_names,
            'count': len(tool_calls)
        })

        # 构建历史记录条目，包含 tool_calls
        history_entry = {
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in tool_calls
            ]
        }

        # 提取 thought_signature（如果存在）
        # 根据 Gemini 文档：并行函数调用时，只有第一个函数调用包含 thought_signature
        if hasattr(message, 'thought_signature') and message.thought_signature:
            history_entry["thought_signature"] = message.thought_signature

        # 提取 reasoning_content（如果存在）
        # DeepSeek 等推理模型要求在后续请求中回传 reasoning_content
        # 注意：即使 reasoning_content 为空字符串或 None 也要保留，服务端要求原样回传
        if hasattr(message, 'reasoning_content'):
            history_entry["reasoning_content"] = message.reasoning_content

        self.add_to_history("assistant", history_entry)

        deferred_user_inputs = []
        # ⚠️ deferred 机制：专家输出和用户输入延迟到所有 tool_calls 执行完毕后才注入历史
        # 顺序：所有 tool 消息 → 专家输出 → 用户输入（确保 LLM 看到正确的上下文顺序）
        deferred_expert_outputs = []  # 专家输出延迟添加，确保在所有 tool 消息之后

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
            except json.JSONDecodeError as e:
                logger.error(f"{self.agent_id}: Failed to parse tool arguments for {tool_name}: {e}")
                logger.error(f"{self.agent_id}: Raw arguments: {tool_call.function.arguments[:500]}")
                error_msg = f"JSON参数解析失败: {str(e)}。请检查参数格式，确保所有字符串中的引号和特殊字符已正确转义。"
                result = {"error": error_msg}
                self.add_to_history("tool", {
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })
                continue

            result = self._execute_tool(tool_name, tool_args, task, session_data)

            # call_agent 工具：收集专家输出，延迟添加到历史（确保在 tool 消息之后）
            if tool_name == "call_agent" and isinstance(result, dict) and result.get("success"):
                expert_output = result.get("result", "")
                if expert_output:
                    deferred_expert_outputs.append(expert_output)

            # ask_user 工具：在 tool 回答之前，将问题写入历史（保证顺序正确）
            verification_id_for_answer = None
            if tool_name == "ask_user" and isinstance(result, dict) and "_verification_meta" in result:
                meta = result.pop("_verification_meta")
                verification_id_for_answer = meta.get("verification_id")
                for attr, key in (
                    ("image_urls", "image_urls"),
                    ("video_urls", "video_urls"),
                    ("audio_urls", "audio_urls"),
                    ("thumbnail_urls", "thumbnail_urls"),
                ):
                    incoming_urls = result.get(key) or []
                    if incoming_urls:
                        existing_urls = list(getattr(task, attr, None) or [])
                        for url in incoming_urls:
                            if isinstance(url, str) and url and url not in existing_urls:
                                existing_urls.append(url)
                        setattr(task, attr, existing_urls)
                agent_name = self._get_agent_display_name()
                self.add_to_history("verification", {
                    "verification_id": verification_id_for_answer,
                    "title": f"{agent_name} 向您提问",
                    "description": meta["question"],
                    "options": meta["options"]
                })
                user_input = result.get("user_input", "")
                if user_input:
                    deferred_user_inputs.append((user_input, verification_id_for_answer))

            tool_history_entry = {
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(result, ensure_ascii=False)
            }

            self.add_to_history("tool", tool_history_entry)

        # 将用户的回答作为 user 消息写入历史，放在所有 tool 消息之后
        # 避免在 assistant(tool_calls) 和 tool 之间插入 user 消息导致 API 报错
        for item in deferred_user_inputs:
            if isinstance(item, tuple):
                user_input, verification_id = item
                self.add_to_history("user", user_input, extra_meta={"verification_id": verification_id})
            else:
                self.add_to_history("user", item)

        # 将专家输出作为 assistant 消息写入历史，确保刷新后能恢复显示
        # 顺序：assistant(tool_calls) -> tool -> user(如有) -> assistant(专家输出)
        for expert_output in deferred_expert_outputs:
            self.add_to_history("assistant", expert_output, extra_meta={"visibility": "llm"})

    def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        task: AgentTask,
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行工具调用"""
        if tool_name not in self.allowed_tools:
            return {"error": f"工具 {tool_name} 不在允许列表中"}

        try:
            if tool_name == "call_agent":
                return self._handle_agent_call(tool_args, task, session_data)
            elif tool_name == "ask_user":
                return self._handle_ask_user(tool_args)
            elif tool_name == "load_sop":
                return self._handle_load_sop(tool_args)
            else:
                # Delegate to tool_executor for non-PM specific tools
                return self.tool_executor.execute_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    user_id=self.user_id,
                    world_id=self.world_id,
                    auth_token=self.auth_token,
                    language=getattr(self, 'current_language', 'zh-CN'),
                    model=self.model,
                    vendor_id=task.vendor_id,
                )
        except InsufficientComputingPowerError:
            raise
        except Exception as e:
            logger.error(f"{self.agent_id}: Tool execution failed - {e}", exc_info=True)
            self.total_failures += 1
            self.consecutive_failures += 1
            return {"error": str(e)}

    def _handle_load_sop(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理 load_sop 工具调用 - 加载 SOP 完整流程内容"""
        sop_name = tool_args.get("sop_name")
        if not sop_name:
            return {"error": "缺少 sop_name 参数"}

        if not self.sop_loader:
            return {"error": "SOP 加载器未初始化"}

        sop_content = self.sop_loader.get_sop_content(sop_name)
        if not sop_content:
            available = self.sop_loader.list_sops()
            return {"error": f"SOP '{sop_name}' 不存在。可用的 SOP: {available}"}

        logger.info(f"{self.agent_id}: 已加载 SOP '{sop_name}' ({len(sop_content)} 字符)")
        return {"success": True, "sop_name": sop_name, "content": sop_content}

    def _handle_agent_call(
        self,
        tool_args: Dict[str, Any],
        task: AgentTask,
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理 call_agent 工具调用 - 调用专家智能体执行任务"""
        skill_name = tool_args.get("AgentName")

        if not skill_name:
            return {"error": "缺少 AgentName 参数"}

        if skill_name not in self.agents_config["expert_agents"]:
            return {"error": f"未知的专家技能: {skill_name}"}

        if not self._is_expert_allowed(skill_name):
            allowed_types = ", ".join(self.allowed_expert_types or [])
            return {
                "error": (
                    f"不允许调用专家 {skill_name}。"
                    f"当前 PM 仅允许调用类型: {allowed_types or '未限制'}"
                )
            }

        logger.info(f"{self.agent_id}: Dispatching task to expert {skill_name}")

        self.task_manager.push_message(task.task_id, 'progress', {
            'step': f"正在调用专家 {skill_name} 执行任务..."
        })

        expert_config = self.agents_config["expert_agents"][skill_name]

        # 构建包含完整环境内容的上下文
        context = self._build_context_for_expert(skill_name, task.user_id, task.world_id)

        # 获取技能列表
        skill_names = expert_config["skills"]

        # 使用用户选择的模型（self.model）而非配置文件中的硬编码模型
        # 这样当用户切换模型时，Expert Agent 也会使用新模型
        expert_model = self.model if self.model else expert_config["model"]
        logger.info(f"{self.agent_id}: Expert {skill_name} 使用模型: {expert_model}")

        expert = ExpertAgent(
            skill_names=skill_names,
            model=expert_model,
            allowed_tools=expert_config["allowed_tools"],
            context_from_pm=context,
            file_manager=self.file_manager,
            user_id=task.user_id,
            world_id=task.world_id,
            auth_token=task.auth_token,
            tool_executor=self.tool_executor,
            vendor_id=task.vendor_id,
            model_id=task.model_id,
            enable_thinking=task.enable_thinking,
            thinking_effort=task.thinking_effort,
            task_manager=self.task_manager,
            task_id=task.task_id,
            max_iterations=expert_config.get("max_iterations", 10),
            language=task.language,
            max_consecutive_no_progress=expert_config.get("max_consecutive_no_progress", 3),
            max_consecutive_errors=expert_config.get("max_consecutive_errors", 3),
            max_total_errors=expert_config.get("max_total_errors", 7)
        )

        # 合并 LLM 提供的 conversation_history 和 PM 已有的 ask_user 交互
        # 避免 Expert 重复提问已被 PM 回答过的问题
        llm_history = tool_args.get("conversation_history", [])
        pm_ask_user_history = self._extract_ask_user_qa()
        merged_history = llm_history + pm_ask_user_history

        # 自动提取当前任务中的媒体 URL，注入到专家上下文
        image_urls_for_expert = task.image_urls or []
        audio_urls_for_expert = task.audio_urls or []
        video_urls_for_expert = task.video_urls or []


        # 长文本剧本文件名透传（修复：拆分智能体反馈"没有提供导入剧本"的根因）
        # 当用户粘贴 >5000 字剧本时，完整内容已落盘为 user_long_input/<filename>.txt，
        # 子智能体必须拿到文件名才能通过 get_long_user_input 读取完整内容。
        long_input_filenames = self._extract_long_input_filenames()
        long_input_hint = self._build_long_input_hint(long_input_filenames)
        task_description_raw = tool_args.get("task_description", "执行任务")
        if long_input_hint:
            # 同时注入 task_description（确保 LLM 一定读到）和 conversation_history（双保险）
            task_description_for_expert = f"{task_description_raw}\n\n{long_input_hint}"
            merged_history = merged_history + [
                {"role": "user", "content": long_input_hint}
            ]
            logger.info(f"{self.agent_id}: Injected long input filenames {long_input_filenames} into expert '{skill_name}'")
        else:
            task_description_for_expert = task_description_raw

        expert_task = {
            "session_id": task.task_id,
            "pm_session_id": task.session_id,
            "pm_task_id": task.task_id,
            "description": task_description_for_expert,
            "pm_context": context,
            "conversation_history": merged_history,
            "image_urls": image_urls_for_expert,
            "audio_urls": audio_urls_for_expert,
            "video_urls": video_urls_for_expert
        }

        result = expert.execute_task(expert_task)

        if result.get("success"):
            logger.info(f"{self.agent_id}: Expert {skill_name} succeeded")
            self.consecutive_failures = 0

            # 推送生成任务的 project_ids 到前端，前端自动轮询
            project_ids = result.get("project_ids", [])
            if project_ids:
                # 根据技能类型区分事件
                if skill_name == "marketing-video":
                    event_type = 'video_task_submitted'
                    event_message = f'已提交 {len(project_ids)} 个视频生成任务'
                else:
                    event_type = 'image_task_submitted'
                    event_message = f'已提交 {len(project_ids)} 个图片生成任务'
                self.task_manager.push_message(task.task_id, event_type, {
                    'project_ids': project_ids,
                    'message': event_message
                })
                # 同时保存 project_ids 到对话历史，支持页面刷新后恢复
                self._save_pending_task_to_history(task.session_id, event_type, project_ids)

            self.completed_tasks.append({
                "skill": skill_name,
                "result": result,
                "timestamp": datetime.now().isoformat()
            })

            # Expert output must be visible immediately. The frontend keeps a
            # content-based dedupe guard, so a later PM response with identical
            # text will not render as a second bubble.
            expert_response = result.get('result', '')
            if expert_response:
                self.task_manager.push_message(task.task_id, 'message', {
                    'role': 'assistant',
                    'content': expert_response
                })
            else:
                self.task_manager.push_message(task.task_id, 'message', {
                    'role': 'assistant',
                    'content': f"专家 {skill_name} 执行完成"
                })
        else:
            self.total_failures += 1
            self.consecutive_failures += 1

            # 即使 Expert 失败，如果已提交生成任务，仍通知前端轮询
            project_ids = result.get("project_ids", [])
            if project_ids:
                if skill_name == "marketing-video":
                    event_type = 'video_task_submitted'
                    event_message = f'已提交 {len(project_ids)} 个视频生成任务'
                else:
                    event_type = 'image_task_submitted'
                    event_message = f'已提交 {len(project_ids)} 个图片生成任务'
                self.task_manager.push_message(task.task_id, event_type, {
                    'project_ids': project_ids,
                    'message': event_message
                })
                # 同时保存 project_ids 到对话历史，支持页面刷新后恢复
                self._save_pending_task_to_history(task.session_id, event_type, project_ids)

            self.task_manager.push_message(task.task_id, 'message', {
                'role': 'assistant',
                'content': f"专家 {skill_name} 执行失败: {result.get('error', '未知错误')}"
            })

            logger.warning(f"{self.agent_id}: Expert {skill_name} failed")

        return result

    def _save_pending_task_to_history(self, session_id: str, event_type: str, project_ids: list):
        """将待处理的图片/视频任务标记保存到 chat_messages 表，支持页面刷新后恢复"""
        try:
            from model.chat_messages import ChatMessagesModel

            content = f'__PENDING_TASK__:{event_type}:{json.dumps(project_ids)}'
            idempotency_key = f'pending:{session_id}:{event_type}:{",".join(str(pid) for pid in sorted(project_ids))}'

            ChatMessagesModel.create(
                message_id=f'pending_{uuid.uuid4().hex[:12]}',
                session_id=session_id,
                role='assistant',
                message_type='pending_task',
                content=content,
                idempotency_key=idempotency_key,
                source='pm_agent',
                agent_scope='pm',
                context_state='active',
                visibility='ui',
            )

            # 使缓存失效，确保下次加载时从数据库读取最新数据
            try:
                _get_session_storage().invalidate_cache(session_id)
            except Exception as cache_err:
                logger.warning(f"{self.agent_id}: 清除会话缓存失败: {cache_err}")
        except Exception as e:
            logger.warning(f"{self.agent_id}: 保存 pending task 标记到 chat_messages 失败: {e}")

    def _build_context_for_expert(self, skill_name: str, user_id: str = "0", world_id: str = "0") -> str:
        """为专家构建上下文，包含所有环境内容"""
        context_parts = [
            f"**技能**: {skill_name}"
        ]

        # 检查专家配置中的 summary_only 设置
        summary_only = False
        if skill_name in self.agents_config.get("expert_agents", {}):
            expert_config = self.agents_config["expert_agents"][skill_name]
            summary_only = expert_config.get("summary_only", False)
            logger.info(f"{self.agent_id}: Agent '{skill_name}' summary_only={summary_only}")

        # 使用 FileManager 的方法获取环境上下文
        # 根据配置决定是否使用摘要模式
        env_context = self.file_manager.get_context_for_ai(user_id, world_id, summary_only=summary_only)
        context_parts.append(env_context)

        full_context = "\n".join(context_parts)

        # 如果超过1万字，进行智能截断
        max_chars = 10000
        if len(full_context) > max_chars:
            logger.warning(f"{self.agent_id}: Context exceeds {max_chars} chars ({len(full_context)}), truncating...")
            full_context = self._truncate_context(full_context, user_id, world_id, max_chars)

        return full_context

    def _extract_ask_user_qa(self) -> List[Dict[str, Any]]:
        """从 PM 的 conversation_history 中提取 ask_user 交互，转换为 user/assistant 格式

        用于传递给 Expert Agent，避免重复提问已回答过的问题。
        """
        qa_pairs = []
        history = self.conversation_history

        for i, msg in enumerate(history):
            if msg.get("role") == "tool":
                content = msg.get("content", {})
                name = content.get("name") if isinstance(content, dict) else None
                if name != "ask_user":
                    continue

                # 解析用户回答
                try:
                    result_str = content.get("content", "{}")
                    result = json.loads(result_str) if isinstance(result_str, str) else result_str
                except (json.JSONDecodeError, TypeError):
                    continue

                user_input = result.get("user_input", "")
                message = result.get("message", "")
                if not user_input:
                    continue

                # 回溯找到对应的 assistant 消息（包含 tool_calls），提取问题文本
                question_text = message or f"用户已回答: {user_input}"
                for j in range(i - 1, -1, -1):
                    prev = history[j]
                    if prev.get("role") == "assistant":
                        prev_content = prev.get("content")
                        if isinstance(prev_content, dict) and "tool_calls" in prev_content:
                            for tc in prev_content["tool_calls"]:
                                if tc.get("function", {}).get("name") == "ask_user":
                                    try:
                                        tc_args = json.loads(tc["function"]["arguments"])
                                        question_text = tc_args.get("question", question_text)
                                    except (json.JSONDecodeError, KeyError):
                                        pass
                        break

                qa_pairs.append({"role": "assistant", "content": question_text})
                qa_pairs.append({"role": "user", "content": user_input})

        if qa_pairs:
            logger.info(f"{self.agent_id}: Extracted {len(qa_pairs) // 2} ask_user Q&A pairs for expert")

        return qa_pairs

    # 长文本文件名提取正则：匹配 process_long_input 生成的系统提示中的文件名
    # 示例提示行："- 文件名：14:57:23.txt" 或 'get_long_user_input(name="14:57:23.txt")'
    # 兼容新旧两种文件名格式（旧 HH:MM:SS.txt / 新 longinput_xxx.txt）
    _LONG_INPUT_FILENAME_PATTERNS = [
        re.compile(r'-\s*文件名[：:]\s*([^\s\n]+\.txt)'),
        re.compile(r'get_long_user_input\(\s*name\s*=\s*["\']([^"\']+\.txt)["\']'),
    ]

    def _extract_long_input_filenames(self) -> List[str]:
        """从 PM 的 conversation_history 中提取所有长文本输入的文件名。

        当用户粘贴超过 5000 字的剧本时，task_manager.process_long_input 会把完整
        内容落盘为 user_long_input/<filename>.txt，并向 PM 注入一条带"文件名"提示
        的 user 消息。子智能体（如 novel-episode-splitter）需要这个文件名才能通过
        get_long_user_input 工具读取完整剧本，否则会出现"没有提供导入剧本"。

        本方法扫描历史中所有 user / assistant 消息，按出现顺序提取文件名并去重，
        确保即便 PM 没有把文件名写进 task_description，子智能体也能拿到。
        """
        filenames: List[str] = []
        seen = set()
        history = self.conversation_history

        for msg in history:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content")
            if not isinstance(content, str) or not content:
                continue
            for pattern in self._LONG_INPUT_FILENAME_PATTERNS:
                for match in pattern.finditer(content):
                    fname = match.group(1).strip()
                    if fname and fname not in seen:
                        seen.add(fname)
                        filenames.append(fname)

        if filenames:
            logger.info(f"{self.agent_id}: Extracted long input filenames for expert: {filenames}")
        return filenames

    def _build_long_input_hint(self, filenames: List[str]) -> str:
        """根据文件名列表构造给子智能体的长文本读取指令。"""
        if not filenames:
            return ""
        lines = [
            "【长文本剧本文件提示】",
            "用户提供的剧本内容较长（超过5000字），完整内容已保存为文件，请务必读取后再处理：",
        ]
        for fname in filenames:
            lines.append(f'- 请立即调用 get_long_user_input(name="{fname}") 读取完整剧本内容')
        lines.append("注意：上面截断的内容只是预览，拆分/分析必须基于 get_long_user_input 读取到的完整内容。")
        return "\n".join(lines)

    def _truncate_environment_context(self, env_context: str, user_id: str, world_id: str, max_chars: int) -> str:
        """截断环境上下文"""
        return self._truncate_context(env_context, user_id, world_id, max_chars)

    def _truncate_context(self, full_context: str, user_id: str, world_id: str, max_chars: int) -> str:
        """截断上下文，保留前25000和后25000个字符
        ⚠️ 命名陷阱：参数 max_chars 控制是否触发截断，但实际截断大小由 half_size=25000 决定
        例如 max_chars=10000 时，即使 len=15000 也会截断为 50000 字符（前25000+后25000）
        """
        if len(full_context) <= max_chars:
            return full_context

        # 保留前25000和后25000个字符
        half_size = 25000
        truncated = (
            full_context[:half_size] +
            f"\n\n[... 省略中间 {len(full_context) - 2*half_size} 个字符 ...]\n\n" +
            full_context[-half_size:]
        )

        return truncated

    def _get_context_window(self) -> Optional[int]:
        """获取上下文窗口大小，优先使用配置值，否则按模型名推断默认值"""
        if self.context_window is not None:
            return self.context_window
        model_lower = self.model.lower() if self.model else ""
        if "gemini-3-pro" in model_lower:
            return 2097152
        if "gemini" in model_lower:
            return 1048576
        if "claude" in model_lower:
            return 200000
        if "qwen" in model_lower:
            return 131072
        if "gpt-4o" in model_lower or "gpt-4" in model_lower:
            return 128000
        return None

    def _estimate_current_tokens(self, extra_buffer: int = 2000) -> int:
        """估算当前上下文 token 数：上次真实 input_token + 本次新增消息的字符估算 + 缓冲"""
        messages = self._build_messages_for_api()
        # 极简字符估算：每 3 个字符约 1 个 token（对中英混合偏保守）
        char_count = sum(len(str(m.get("content", ""))) for m in messages)
        delta = char_count // 3
        return self.last_api_input_tokens + delta + extra_buffer

    def _should_compress(self) -> bool:
        """判断是否需要触发上下文压缩"""
        context_window = self._get_context_window()
        if not context_window:
            return False
        current_tokens = self._estimate_current_tokens()
        return current_tokens / context_window >= 0.90

    def force_compress(self, task: AgentTask) -> Dict[str, Any]:
        """
        手动触发上下文压缩（公开接口）

        Args:
            task: 当前任务对象，包含模型配置信息

        Returns:
            Dict: 压缩结果，包含 before_count, after_count, summary 等信息
        """
        from config.constant import SessionHistoryConstants

        original_count = len(self.conversation_history)
        count_from_db = False
        if self._session_id:
            try:
                from model.chat_messages import ChatMessagesModel
                original_count = len(ChatMessagesModel.list_active_for_context(self._session_id, agent_scope='pm'))
                count_from_db = True
            except Exception as e:
                logger.warning(f"{self.agent_id}: Failed to count DB history before compression: {e}")

        # 检查是否有足够消息可压缩
        if original_count <= SessionHistoryConstants.MIN_HISTORY_MESSAGES:
            return {
                "success": False,
                "error": f"历史消息数量过少（{original_count}），无需压缩",
                "before_count": original_count,
                "after_count": original_count
            }

        # 执行压缩，获取摘要内容
        summary_text = self._compress_conversation_history(task)

        new_count = len(self.conversation_history)
        if count_from_db:
            try:
                from model.chat_messages import ChatMessagesModel
                new_count = len(ChatMessagesModel.list_active_for_context(self._session_id, agent_scope='pm'))
            except Exception as e:
                logger.warning(f"{self.agent_id}: Failed to count DB history after compression: {e}")

        return {
            "success": True,
            "before_count": original_count,
            "after_count": new_count,
            "reduced": original_count - new_count,
            "summary": summary_text or ""
        }

    def _compress_conversation_history(self, task: AgentTask) -> str:
        """压缩对话历史：优先压缩 chat_messages，兜底压缩内存历史。"""
        if self._session_id:
            try:
                return self._compress_via_db(task)
            except Exception as e:
                logger.error(f"{self.agent_id}: DB compression failed, falling back to memory: {e}")

        return self._compress_via_memory(task)

    def _compress_via_db(self, task: AgentTask) -> str:
        """基于 chat_messages 的 DB 历史压缩。"""
        from config.constant import SessionHistoryConstants
        from model.chat_messages import ChatMessagesModel

        all_active = ChatMessagesModel.list_active_for_context(self._session_id, agent_scope='pm')
        normal_msgs = [
            msg for msg in all_active
            if msg.message_type not in ('system_prompt', 'tool_definitions')
        ]

        keep_count = SessionHistoryConstants.MIN_HISTORY_MESSAGES
        if len(normal_msgs) <= keep_count:
            logger.info(f"{self.agent_id}: DB active messages too few ({len(normal_msgs)}), skip compression")
            return ""

        desired_start = len(normal_msgs) - keep_count
        safe_start = self._find_safe_preserve_start_db(normal_msgs, desired_start)
        compressible = normal_msgs[:safe_start]
        preserved = normal_msgs[safe_start:]

        if not compressible:
            return ""

        logger.warning(
            f"{self.agent_id}: Triggering DB history compression. "
            f"compressible={len(compressible)}, preserved={len(preserved)}"
        )

        expert_conversation = [
            {"role": msg.role, "content": msg.content}
            for msg in compressible
        ]

        pm_context = self._build_context_for_expert("script-orchestrator", self.user_id, self.world_id)
        summary = self.summarizer.summarize(
            pm_context=pm_context,
            expert_conversation=expert_conversation,
            expert_name="script-orchestrator",
            model=self.model,
            vendor_id=task.vendor_id,
            auth_token=task.auth_token,
            model_id=task.model_id,
            enable_thinking=task.enable_thinking,
            thinking_effort=task.thinking_effort
        )
        summary_text = summary.get("summary", "")
        if not summary_text:
            summary_text = f"[上下文摘要] 任务: {summary.get('task', '')}; 状态: {summary.get('status', '')}"

        summary_uuid = f"sum_{uuid.uuid4().hex[:12]}"
        parent_summary_ids = [m.generated_summary_id for m in compressible if m.generated_summary_id]

        if not self._conversation_recorder:
            from script_writer_core.conversation_recorder import ConversationRecorder
            self._conversation_recorder = ConversationRecorder()

        summary_entity = self._conversation_recorder.append_message(
            session_id=self._session_id,
            role="system",
            content={
                "text": f"[历史对话已压缩] {summary_text}",
                "parent_summary_ids": parent_summary_ids,
            },
            message_type="context_summary",
            visibility="llm",
            context_state="active",
            generated_summary_id=summary_uuid,
            agent_scope="pm",
            task_id=task.task_id,
            agent_id=self.agent_id,
            source="compression",
        )

        ChatMessagesModel.update_context_state(
            message_ids=[m.id for m in compressible],
            context_state="summarized",
            covered_by_summary_id=summary_uuid,
        )

        try:
            from model.chat_history_summaries import ChatHistorySummariesModel
            ChatHistorySummariesModel.create(
                summary_id=summary_uuid,
                session_id=self._session_id,
                summary_message_id=summary_entity.id if summary_entity else None,
                summary_text=summary_text,
                from_message_id=compressible[0].id if compressible else None,
                to_message_id=compressible[-1].id if compressible else None,
                summary_level=1,
                parent_summary_ids=parent_summary_ids,
                raw_message_count=len(compressible),
                model_id=task.model_id,
                vendor_id=task.vendor_id,
            )
        except Exception as e:
            logger.warning(f"{self.agent_id}: Failed to create chat history summary record: {e}")

        logger.info(f"{self.agent_id}: DB compression done, {len(compressible)} messages summarized as {summary_uuid}")
        return summary_text

    def _compress_via_memory(self, task: AgentTask) -> str:
        """压缩内存 conversation_history（无 DB 会话时兜底）。"""
        from config.constant import SessionHistoryConstants

        history = self.conversation_history
        if len(history) <= SessionHistoryConstants.MIN_HISTORY_MESSAGES:
            logger.warning(f"{self.agent_id}: 历史消息数量过少（{len(history)}），跳过压缩")
            return ""

        # 保留 system 消息和最近 MIN_HISTORY_MESSAGES 条消息
        system_msgs = [msg for msg in history if msg.get("role") == "system"]
        other_msgs = [msg for msg in history if msg.get("role") != "system"]
        keep_count = SessionHistoryConstants.MIN_HISTORY_MESSAGES
        # 找到安全的保留起始索引，避免拆分 tool_calls/tool 消息组
        desired_start = len(other_msgs) - keep_count
        safe_start = self._find_safe_preserve_start(other_msgs, desired_start)
        preserved = other_msgs[safe_start:]
        compressible = other_msgs[:safe_start]

        if not compressible:
            return ""

        logger.warning(
            f"{self.agent_id}: 上下文窗口使用率超过90%，触发压缩。"
            f"可压缩消息数: {len(compressible)}, 保留消息数: {len(preserved)}"
        )

        # 主策略：使用 summarizer 生成摘要（使用当前对话的模型）
        try:
            pm_context = self._build_context_for_expert("script-orchestrator", self.user_id, self.world_id)
            summary = self.summarizer.summarize(
                pm_context=pm_context,
                expert_conversation=compressible,
                expert_name="script-orchestrator",
                model=self.model,
                vendor_id=task.vendor_id,
                auth_token=task.auth_token,
                model_id=task.model_id,
                enable_thinking=task.enable_thinking,
                thinking_effort=task.thinking_effort
            )
            summary_text = summary.get("summary", "")
            if not summary_text:
                summary_text = f"[上下文摘要] 任务: {summary.get('task', '')}; 状态: {summary.get('status', '')}"
            compressed_msg = {
                "role": "assistant",
                "content": f"[历史对话已压缩] {summary_text}",
                "timestamp": datetime.now().isoformat()
            }
            new_history = system_msgs + [compressed_msg] + preserved

            # 有效性检查：压缩后消息数必须显著减少（至少减少 MIN_HISTORY_MESSAGES 条）
            min_reduction = SessionHistoryConstants.MIN_HISTORY_MESSAGES
            if len(new_history) > len(history) - min_reduction:
                raise ValueError(
                    f"压缩无效：消息数从 {len(history)} 降至 {len(new_history)}，"
                    f"仅减少 {len(history) - len(new_history)} 条，未达到阈值 {min_reduction}"
                )

            self.conversation_history = new_history
            logger.info(
                f"{self.agent_id}: 使用 summarizer 压缩成功，"
                f"历史消息从 {len(history)} 降至 {len(self.conversation_history)} "
                f"(减少 {len(history) - len(self.conversation_history)} 条)"
            )
            return summary_text
        except Exception as e:
            logger.error(f"{self.agent_id}: summarizer 压缩失败，回退到滑动窗口截断: {e}")
            # 兜底策略：滑动窗口截断，只保留最近的 MAX_HISTORY_MESSAGES 条
            max_msgs = SessionHistoryConstants.MAX_HISTORY_MESSAGES
            if len(history) > max_msgs:
                # 找到安全的截断起始索引，避免拆分 tool_calls/tool 消息组
                desired_start = len(history) - max_msgs
                safe_start = self._find_safe_preserve_start(history, desired_start)
                kept = history[safe_start:]
            else:
                kept = history
            self.conversation_history = kept
            logger.info(f"{self.agent_id}: 滑动窗口截断后，历史消息降至 {len(self.conversation_history)}")
            return f"[滑动窗口截断] 保留最近 {len(self.conversation_history)} 条消息"

    @staticmethod
    def _find_safe_preserve_start_db(msgs: List, desired_start: int) -> int:
        """找到 DB 消息安全保留起点，避免拆分 tool_call/tool_result 组。"""
        start = desired_start

        while start > 0 and start < len(msgs):
            msg = msgs[start]
            if msg.message_type in ('tool_result', 'verification_request', 'verification_answer'):
                start -= 1
            else:
                break

        while start > 0 and start < len(msgs):
            tail_msg = msgs[start - 1]
            if tail_msg.message_type == 'tool_call':
                start += 1
            else:
                break

        return start

    @staticmethod
    def _find_safe_preserve_start(msgs: List[Dict[str, Any]], desired_start: int) -> int:
        """找到安全的保留起始索引，确保不会将 tool 消息与其前置的 assistant(tool_calls) 拆分。

        从 desired_start 向前搜索，如果 desired_start 指向的是 tool 消息，
        则继续向前直到找到对应的 assistant(tool_calls) 消息。

        Args:
            msgs: 消息列表（不含 system 消息）
            desired_start: 期望的起始索引

        Returns:
            安全的起始索引（<= desired_start）
        """
        start = desired_start
        while start > 0:
            msg = msgs[start]
            role = msg.get("role")
            content = msg.get("content")
            # 如果当前位置是 tool 消息，说明前面还有对应的 assistant(tool_calls)，继续向前
            if role == "tool":
                start -= 1
            # 如果是 verification 消息（ask_user 产生的），也继续向前
            elif role == "verification":
                start -= 1
            else:
                break
        return start

    def _is_deepseek_model(self) -> bool:
        """判断当前模型是否为 DeepSeek 模型"""
        return 'deepseek' in (self.model or '').lower()

    def _build_messages_for_api(self) -> List[Dict[str, Any]]:
        """构建用于 API 调用的消息列表

        使用初始化时已经包含环境上下文的 self.system_prompt
        优先从 chat_messages 数据库构建，失败时回退到内存构建。
        """
        if self._session_id:
            try:
                from script_writer_core.llm_context_builder import LLMContextBuilder
                self._current_llm_context = LLMContextBuilder().build(
                    session_id=self._session_id,
                    model=self.model,
                    vendor_id=getattr(self, '_vendor_id', None)
                )
                return self._current_llm_context.messages
            except Exception as e:
                logger.error(f"{self.agent_id}: LLMContextBuilder failed, falling back to memory: {e}")
                self._current_llm_context = None
        else:
            self._current_llm_context = None

        return self._build_messages_from_memory()

    def _build_messages_from_memory(self) -> List[Dict[str, Any]]:
        """从内存 conversation_history 构建消息列表（降级路径）"""
        messages = []

        # 1. 添加 system 消息（已在 __init__ 中包含环境上下文）
        system_content = self.system_prompt
        # 追加语言指令（非中文时）
        if hasattr(self, 'current_language') and self.current_language != 'zh-CN':
            from config.constant import LANGUAGE_INSTRUCTIONS
            lang_instruction = LANGUAGE_INSTRUCTIONS.get(self.current_language, '')
            if lang_instruction:
                system_content += lang_instruction
                logger.info(f"{self.agent_id}: Appended language instruction for '{self.current_language}' ({len(lang_instruction)} chars)")
            else:
                logger.warning(f"{self.agent_id}: No language instruction found for '{self.current_language}'")
        messages.append({
            "role": "system",
            "content": system_content
        })

        # 判断是否为 DeepSeek 模型，如果是则需要为历史 assistant 消息补充 reasoning_content
        is_deepseek = self._is_deepseek_model()

        # 2. 添加对话历史中的消息
        for idx, msg in enumerate(self.conversation_history):
            role = msg.get("role")
            content = msg.get("content")

            # 跳过 system 消息（已在上面处理）
            if role == "system":
                continue

            # 跳过 verification 消息（仅供前端展示，不发给 LLM）
            if role == "verification":
                continue

            if role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": content.get("tool_call_id") if isinstance(content, dict) else None,
                    "name": content.get("name") if isinstance(content, dict) else "unknown",
                    "content": content.get("content") if isinstance(content, dict) else str(content)
                })
            elif role == "assistant" and isinstance(content, dict) and "tool_calls" in content:
                # 构建 assistant 消息，包含 tool_calls 和 thought_signature
                assistant_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": content["tool_calls"]
                }

                # 如果有 thought_signature，也要传递给 API
                if "thought_signature" in content:
                    assistant_msg["thought_signature"] = content["thought_signature"]

                # 如果有 reasoning_content，也要传递给 API
                if "reasoning_content" in content:
                    assistant_msg["reasoning_content"] = content["reasoning_content"]
                elif is_deepseek:
                    # DeepSeek 要求回传 reasoning_content，历史记录中没有时补充空字符串
                    assistant_msg["reasoning_content"] = ""

                messages.append(assistant_msg)
            elif role == "assistant" and isinstance(content, dict) and "reasoning_content" in content:
                # 纯文本 assistant 消息但包含 reasoning_content（DeepSeek 推理模型要求回传）
                assistant_msg = {
                    "role": "assistant",
                    "content": content.get("text", ""),
                    "reasoning_content": content["reasoning_content"]
                }
                messages.append(assistant_msg)
            elif role == "assistant" and is_deepseek:
                # DeepSeek 模型下，普通 assistant 消息也需要补充 reasoning_content
                assistant_msg = {
                    "role": "assistant",
                    "content": content if isinstance(content, str) else str(content),
                    "reasoning_content": ""
                }
                messages.append(assistant_msg)
            elif role == "user" and isinstance(content, list):
                # 多模态消息（包含图片）
                messages.append({
                    "role": "user",
                    "content": content
                })
            else:
                messages.append({
                    "role": role,
                    "content": content if isinstance(content, str) else str(content)
                })

        # 3. 为非中文语言注入用户消息提示（双重保险）
        if hasattr(self, 'current_language') and self.current_language != 'zh-CN':
            # 找到最后一条 user 消息，追加语言提示
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user" and isinstance(messages[i].get("content"), str):
                    messages[i]["content"] += f"\n\n[Please respond in English]"
                    break

        # 4. 防御性清理：移除没有前置 assistant(tool_calls) 的孤立 tool 消息
        sanitized = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool":
                # 向前查找最近的非 tool 消息，确认是 assistant(tool_calls)
                has_preceding_tool_calls = False
                for j in range(len(sanitized) - 1, -1, -1):
                    if sanitized[j].get("role") == "tool":
                        continue
                    if sanitized[j].get("role") == "assistant" and sanitized[j].get("tool_calls"):
                        has_preceding_tool_calls = True
                    break
                if not has_preceding_tool_calls:
                    logger.warning(f"{self.agent_id}: 移除孤立的 tool 消息（缺少前置 tool_calls）: name={msg.get('name')}")
                    continue
            sanitized.append(msg)

        return sanitized

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取工具定义"""
        allowed_experts = self._get_allowed_expert_names()
        # 1. 核心 PM 工具定义
        pm_tools = [
            {
                "type": "function",
                "function": {
                    "name": "call_agent",
                    "description": "调用指定的专家智能体执行任务。每个专家智能体都有特定的技能和工具，可以完成特定领域的任务。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "AgentName": {
                                "type": "string",
                                "enum": allowed_experts,
                                "description": "要调用的专家智能体名称（如 story-writer, character-creator 等）"
                            },
                            "task_description": {
                                "type": "string",
                                "description": "分配给该智能体的具体任务描述"
                            },
                            "conversation_history": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "role": {
                                            "type": "string",
                                            "enum": ["user", "assistant"],
                                            "description": "消息角色"
                                        },
                                        "content": {
                                            "type": "string",
                                            "description": "消息内容"
                                        }
                                    },
                                    "required": ["role", "content"]
                                },
                                "description": "可选的对话历史记录（不包括system消息），仅包含用户(user)和助手(assistant)之间的多轮对话。专家智能体会基于这些历史对话来理解上下文并执行任务。注意：system提示词会自动处理，无需在此传递。"
                            }
                        },
                        "required": ["AgentName"]
                    }
                }
            }
        ]

        # 2. 获取 allowed_tools 中的其他工具
        core_tool_names = ["call_agent", "ask_user", "load_sop"]
        other_allowed_tools = [t for t in self.allowed_tools if t not in core_tool_names]

        if other_allowed_tools:
            other_tool_definitions = self.tool_executor.get_tool_definitions(other_allowed_tools)
            pm_tools.extend(other_tool_definitions)

        # 3. 添加 ask_user 工具定义（PM 可直接向用户提问）
        if "ask_user" in self.allowed_tools:
            pm_tools.append(ASK_USER_TOOL_DEFINITION)

        # 4. 添加 load_sop 工具定义（PM 可加载 SOP 流程内容）
        if "load_sop" in self.allowed_tools:
            pm_tools.append(LOAD_SOP_TOOL_DEFINITION)

        return pm_tools

    def _get_allowed_expert_names(self) -> List[str]:
        """根据当前 PM 允许的 expert_type 返回可调用专家列表。"""
        expert_agents = self.agents_config.get("expert_agents", {})
        if not self.allowed_expert_types:
            return list(expert_agents.keys())

        allowed_types = set(self.allowed_expert_types)
        allowed = sorted(
            name
            for name, config in expert_agents.items()
            if config.get("expert_type") in allowed_types
        )
        if "admin" in allowed_types and not self._is_admin_user():
            allowed = [name for name in allowed if expert_agents[name].get("expert_type") != "admin"]
        return allowed

    def _is_admin_user(self) -> bool:
        cached = getattr(self, "_admin_user_cache", None)
        if cached is not None:
            return cached
        try:
            from model.users import UsersModel

            user = UsersModel.get_by_id(int(self.user_id))
            result = bool(user and user.role == "admin")
        except Exception:
            logger.exception("%s: 无法校验管理员专家权限", self.agent_id)
            result = False
        self._admin_user_cache = result
        return result

    def _is_expert_allowed(self, skill_name: str) -> bool:
        """校验当前 PM 是否允许调用指定专家。"""
        if not self.allowed_expert_types:
            return True

        expert_config = self.agents_config.get("expert_agents", {}).get(skill_name, {})
        expert_type = expert_config.get("expert_type")
        if expert_type == "admin" and not self._is_admin_user():
            return False
        return expert_type in set(self.allowed_expert_types)

    def should_stop(self) -> tuple[bool, str]:
        """检查是否需要停止"""
        if self.consecutive_failures >= self.max_consecutive_failures:
            return True, f"连续失败{self.max_consecutive_failures}次"
        if self.total_failures >= self.max_total_failures:
            return True, f"累计失败{self.max_total_failures}次"
        return False, ""
