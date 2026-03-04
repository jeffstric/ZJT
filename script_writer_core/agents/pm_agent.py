import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base_agent import BaseAgent
from .expert_agent import ExpertAgent
from .summarizer import ConversationSummarizer
from .task_manager import TaskManager, AgentTask
from llm.gemini_client import get_gemini_client
from script_writer_core.file_manager import FileManager
from script_writer_core.skill_loader import SkillLoader
import json

logger = logging.getLogger(__name__)


class PMAgent(BaseAgent):
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
        max_total_failures: int = 7
    ):
        agent_id = f"pm_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 使用公共的 Gemini 客户端
        self.gemini_client = get_gemini_client()

        # 初始化技能加载器
        self.skill_loader = SkillLoader()

        # 从配置文件获取技能名称列表
        pm_skill_names = agents_config.get("pm_agent", {}).get("skills", ["script-orchestrator"])

        # 构建基础 system prompt
        base_system_prompt = self._build_system_prompt(pm_skill_names)

        # 保存 file_manager 和其他属性
        self.task_manager = task_manager
        self.file_manager = file_manager
        self.tool_executor = tool_executor
        self.agents_config = agents_config
        self.user_id = user_id
        self.world_id = world_id
        self.auth_token = auth_token

        # 获取环境上下文并构建增强的 system prompt（只在初始化时执行一次）
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
        # 暂时没有对 内容进行压缩
        self.summarizer = ConversationSummarizer()
        
        # 将 system 提示词添加到对话历史（用于日志记录）
        self.add_to_history("system", self.system_prompt)
        logger.info(f"{self.agent_id}: Added system prompt to conversation_history (length: {len(self.system_prompt)} chars)")
        logger.info(f"{self.agent_id}: conversation_history now has {len(self.conversation_history)} messages")
    
    def _build_system_prompt(self, skill_names: List[str]) -> str:
        """构建系统提示"""
        base_prompt = """你是剧本架构师（Script Orchestrator），负责协调专家智能体完成剧本创作。

**核心原则**：
- 你是协调者，不是内容创作者
- 严禁直接编写剧本、角色卡、场景描述、道具信息等内容
- 所有内容创作必须通过调用对应的专家智能体完成

**可用工具**：
1. call_agent(AgentName, task_description): 调用专家智能体执行任务
2. request_human_verification(...): 请求人工验证确认

**约束**：
- 任务必须串行执行，一次只能调用一个专家
- 连续失败3次或累计失败7次时必须停止并报告
- 绝不直接生成剧本内容，必须通过 call_agent 调用专家
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
        
        try:
            # 添加用户消息到历史
            self.add_to_history("user", task.user_message)

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
                task.message_queue.put({
                    "type": "message",
                    "role": "assistant",
                    "content": f"任务执行停止: {reason}"
                })
                return f"任务执行停止: {reason}"
            
            logger.info(f"{self.agent_id}: PM Loop iteration {iteration}/{max_iterations}")
            
            task.message_queue.put({
                "type": "progress",
                "progress": iteration / max_iterations,
                "step": f"执行中 ({iteration}/{max_iterations})"
            })
            
            try:
                # 构建消息列表（使用初始化时已包含环境上下文的 system_prompt）
                messages = self._build_messages_for_api()

                # 获取工具定义
                tool_definitions = self._get_tool_definitions()

                # 使用公共的 Gemini 客户端调用 API
                response = self.gemini_client.call_api(
                    model=self.model,
                    messages=messages,
                    tools=tool_definitions,
                    temperature=1,
                    auth_token=task.auth_token,
                    vendor_id=task.vendor_id,
                    model_id=task.model_id
                )
                
                message = response.choices[0].message
                
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    self._handle_tool_calls(message, task, session_data)
                else:
                    content = message.content or ""
                    self.add_to_history("assistant", content)
                    
                    task.message_queue.put({
                        "type": "message",
                        "role": "assistant",
                        "content": content
                    })
                    
                    logger.info(f"{self.agent_id}: PM completed with response")
                    return content
                    
            except Exception as e:
                logger.error(f"{self.agent_id}: Error in PM loop - {e}", exc_info=True)
                self.total_failures += 1
                self.consecutive_failures += 1
                
                task.message_queue.put({
                    "type": "error",
                    "error": str(e)
                })
        
        logger.warning(f"{self.agent_id}: Max iterations reached")
        return "任务执行达到最大迭代次数"

    def _handle_tool_calls(self, message, task: AgentTask, session_data: Dict[str, Any]):
        """处理工具调用"""
        tool_calls = message.tool_calls
        
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
        
        self.add_to_history("assistant", history_entry)
        
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
            except:
                tool_args = {}

            result = self._execute_tool(tool_name, tool_args, task, session_data)

            tool_history_entry = {
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(result, ensure_ascii=False)
            }

            self.add_to_history("tool", tool_history_entry)
    
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
            elif tool_name == "request_human_verification":
                return self._handle_verification_request(tool_args, task)
            else:
                # Delegate to tool_executor for non-PM specific tools
                return self.tool_executor.execute_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    user_id=self.user_id,
                    world_id=self.world_id,
                    auth_token=self.auth_token
                )
        except Exception as e:
            logger.error(f"{self.agent_id}: Tool execution failed - {e}", exc_info=True)
            self.total_failures += 1
            self.consecutive_failures += 1
            return {"error": str(e)}
    
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
        
        logger.info(f"{self.agent_id}: Dispatching task to expert {skill_name}")
        
        task.message_queue.put({
            "type": "message",
            "role": "assistant",
            "content": f"正在调用专家 {skill_name} 执行任务..."
        })
        
        expert_config = self.agents_config["expert_agents"][skill_name]

        # 构建包含完整环境内容的上下文
        context = self._build_context_for_expert(skill_name, task.user_id, task.world_id)

        # 获取技能列表
        skill_names = expert_config["skills"]

        expert = ExpertAgent(
            skill_names=skill_names,
            model=expert_config["model"],
            allowed_tools=expert_config["allowed_tools"],
            context_from_pm=context,
            file_manager=self.file_manager,
            user_id=task.user_id,
            world_id=task.world_id,
            auth_token=task.auth_token,
            tool_executor=self.tool_executor,
            vendor_id=task.vendor_id,
            model_id=task.model_id
        )

        expert_task = {
            "session_id": task.task_id,
            "description": tool_args.get("task_description", "执行任务"),
            "pm_context": context,
            "conversation_history": tool_args.get("conversation_history", [])
        }

        result = expert.execute_task(expert_task)
        
        if result.get("success"):
            logger.info(f"{self.agent_id}: Expert {skill_name} succeeded")
            self.consecutive_failures = 0
            
            self.completed_tasks.append({
                "skill": skill_name,
                "result": result,
                "timestamp": datetime.now().isoformat()
            })

            # 发送 expert 的完整响应内容到前端
            expert_response = result.get('result', '')
            if expert_response:
                task.message_queue.put({
                    "type": "message",
                    "role": "assistant",
                    "content": expert_response
                })
            else:
                # 如果没有响应内容，发送摘要
                message_content = f"专家 {skill_name} 执行完成"
                task.message_queue.put({
                    "type": "message",
                    "role": "assistant",
                    "content": message_content
                })
        else:
            self.total_failures += 1
            self.consecutive_failures += 1
            
            task.message_queue.put({
                "type": "message",
                "role": "assistant",
                "content": f"专家 {skill_name} 执行失败: {result.get('error', '未知错误')}"
            })
            
            logger.warning(f"{self.agent_id}: Expert {skill_name} failed")
        
        return result
    
    def _handle_verification_request(
        self,
        tool_args: Dict[str, Any],
        task: AgentTask
    ) -> Dict[str, Any]:
        """处理人工验证请求"""
        verification_type = tool_args.get("verification_type")
        title = tool_args.get("title")
        description = tool_args.get("description")
        options = tool_args.get("options", [])
        context = tool_args.get("context", {})
        
        if not all([verification_type, title, description]):
            return {"error": "缺少必要参数"}
        
        logger.info(f"{self.agent_id}: Creating verification request")
        
        verification = self.task_manager.create_verification(
            task_id=task.task_id,
            verification_type=verification_type,
            title=title,
            description=description,
            options=options,
            context=context
        )
        
        result = self.task_manager.wait_for_verification(verification, timeout=300)
        
        logger.info(f"{self.agent_id}: Verification result: {result}")
        return result
    
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
    
    def _truncate_environment_context(self, env_context: str, user_id: str, world_id: str, max_chars: int) -> str:
        """截断环境上下文"""
        return self._truncate_context(env_context, user_id, world_id, max_chars)
    
    def _truncate_context(self, full_context: str, user_id: str, world_id: str, max_chars: int) -> str:
        """截断上下文，保留前25000和后25000个字符"""
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
    
    def _build_messages_for_api(self) -> List[Dict[str, Any]]:
        """构建用于 API 调用的消息列表
        
        使用初始化时已经包含环境上下文的 self.system_prompt
        """
        messages = []
        
        # 1. 添加 system 消息（已在 __init__ 中包含环境上下文）
        messages.append({
            "role": "system",
            "content": self.system_prompt
        })
        
        # 2. 添加对话历史中的消息
        for idx, msg in enumerate(self.conversation_history):
            role = msg.get("role")
            content = msg.get("content")
            
            # 跳过 system 消息（已在上面处理）
            if role == "system":
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
                
                messages.append(assistant_msg)
            else:
                messages.append({
                    "role": role,
                    "content": content if isinstance(content, str) else str(content)
                })
        
        return messages
    
    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取工具定义"""
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
                                "enum": list(self.agents_config["expert_agents"].keys()),
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
        core_tool_names = ["call_agent"]
        other_allowed_tools = [t for t in self.allowed_tools if t not in core_tool_names]

        if other_allowed_tools:
            other_tool_definitions = self.tool_executor.get_tool_definitions(other_allowed_tools)
            pm_tools.extend(other_tool_definitions)
            
        return pm_tools
    
    def should_stop(self) -> tuple[bool, str]:
        """检查是否需要停止"""
        if self.consecutive_failures >= self.max_consecutive_failures:
            return True, f"连续失败{self.max_consecutive_failures}次"
        if self.total_failures >= self.max_total_failures:
            return True, f"累计失败{self.max_total_failures}次"
        return False, ""
