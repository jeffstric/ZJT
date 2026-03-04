import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base_agent import BaseAgent
from .history_manager import ExpertHistoryManager
from llm.gemini_client import get_gemini_client
from script_writer_core.file_manager import FileManager
from script_writer_core.skill_loader import SkillLoader

logger = logging.getLogger(__name__)


class ExpertAgent(BaseAgent):
    """专家智能体 - 执行具体任务"""
    
    def __init__(
        self,
        skill_names: List[str],
        model: str,
        allowed_tools: List[str],
        context_from_pm: str,
        file_manager: FileManager,
        user_id: str,
        world_id: str,
        auth_token: str,
        tool_executor: Any,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None
    ):
        # 使用第一个技能名称作为主要标识
        primary_skill = skill_names[0] if skill_names else "unknown"
        agent_id = f"expert_{primary_skill}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 使用公共的 Gemini 客户端
        self.gemini_client = get_gemini_client()
        
        # 初始化技能加载器
        self.skill_loader = SkillLoader()
        
        system_prompt = self._build_system_prompt(skill_names, context_from_pm)
        
        super().__init__(
            agent_id=agent_id,
            skill_names=skill_names,
            model=model,
            allowed_tools=allowed_tools,
            system_prompt=system_prompt
        )
        
        self.context = context_from_pm
        self.file_manager = file_manager
        self.user_id = user_id
        self.world_id = world_id
        self.auth_token = auth_token
        self.tool_executor = tool_executor
        self.vendor_id = vendor_id
        self.model_id = model_id
        
        self.history_manager = ExpertHistoryManager(
            file_manager=file_manager,
            user_id=user_id,
            world_id=world_id
        )
        
        self.tool_calls_made: List[Dict[str, Any]] = []
        self.outputs: List[Any] = []
    
    def _build_system_prompt(self, skill_names: List[str], context: str) -> str:
        """构建系统提示"""
        # 构建基础提示
        skills_str = "、".join(skill_names)
        base_prompt = f"""你是一个专业的专家智能体，具备以下技能：{skills_str}

**PM 提供的上下文**：
{context}

**注意事项**：
1. 严格按照技能指导和任务要求执行
2. 使用工具时确保参数正确
3. 遇到问题及时报告
4. 完成后提供详细的执行总结
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
            skills_section = "\n\n" + "="*60 + "\n**你的技能指导**\n" + "="*60 + "\n\n"
            for skill_name, skill_prompt in skill_prompts:
                skills_section += f"\n### 技能：{skill_name}\n\n{skill_prompt}\n\n{'-'*60}\n"
            return base_prompt + skills_section
        else:
            return base_prompt
    
    def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """执行具体任务"""
        session_id = task.get("session_id", "unknown")
        task_description = task.get("description", "")
        conversation_history = task.get("conversation_history", [])
        
        logger.info(f"{self.agent_id}: Starting task execution - {task_description}")
        
        try:
            # 如果提供了对话历史，先添加到历史记录中
            if conversation_history:
                for msg in conversation_history:
                    role = msg.get("role")
                    content = msg.get("content")
                    if role and content:
                        self.add_to_history(role, content)
            
            self.add_to_history("user", task_description)

            result = self._run_task_loop(task_description)
            
            self._save_session_history(
                session_id=session_id,
                task=task,
                result=result,
                status="success"
            )
            
            logger.info(f"{self.agent_id}: Task completed successfully")
            return {
                "success": True,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"{self.agent_id}: Task failed - {e}", exc_info=True)
            
            self._save_session_history(
                session_id=session_id,
                task=task,
                result=None,
                status="failed",
                error=str(e)
            )
            
            return {
                "success": False,
                "error": str(e)
            }
    
    def _run_task_loop(self, task_description: str, max_iterations: int = 10) -> str:
        """运行任务循环"""
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                # 使用公共的 Gemini 客户端调用 API
                response = self.gemini_client.call_api(
                    model=self.model,
                    messages=self._format_messages_for_api(),
                    tools=self._get_tool_definitions(),
                    temperature=1,
                    auth_token=self.auth_token,
                    vendor_id=self.vendor_id,
                    model_id=self.model_id
                )
                
                message = response.choices[0].message
                
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    self._handle_tool_calls(message)
                else:
                    content = message.content or ""
                    self.add_to_history("assistant", content)
                    logger.info(f"{self.agent_id}: Task completed with response")
                    return content
                    
            except Exception as e:
                logger.error(f"{self.agent_id}: Error in task loop - {e}", exc_info=True)
                raise
        
        logger.warning(f"{self.agent_id}: Max iterations reached")
        return "任务执行达到最大迭代次数，可能未完全完成"
    
    def _handle_tool_calls(self, message):
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
            tool_args = json.loads(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
            
            self.tool_calls_made.append({
                "tool": tool_name,
                "args": tool_args,
                "timestamp": datetime.now().isoformat()
            })
            
            result = self._execute_tool(tool_name, tool_args)
            
            self.outputs.append(result)
            
            self.add_to_history("tool", {
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": str(result)
            })
    
    def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具调用"""
        if tool_name not in self.allowed_tools:
            error_msg = f"工具 {tool_name} 不在允许列表中"
            logger.warning(f"{self.agent_id}: {error_msg}")
            return {"error": error_msg}
        
        try:
            result = self.tool_executor.execute_tool(
                tool_name=tool_name,
                tool_args=tool_args,
                user_id=self.user_id,
                world_id=self.world_id,
                auth_token=self.auth_token
            )
            logger.info(f"{self.agent_id}: Tool {tool_name} executed successfully")
            return result
        except Exception as e:
            error_msg = f"工具执行失败: {str(e)}"
            logger.error(f"{self.agent_id}: {error_msg}", exc_info=True)
            return {"error": error_msg}
    
    def _format_messages_for_api(self) -> List[Dict[str, Any]]:
        """格式化消息用于 API 调用"""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        for msg in self.conversation_history:
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": content.get("tool_call_id"),
                    "name": content.get("name"),
                    "content": content.get("content")
                })
            elif role == "assistant" and isinstance(content, dict) and "tool_calls" in content:
                assistant_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": content["tool_calls"]
                }
                
                # 如果有 thought_signature，也要传递给 API（Gemini 3 要求）
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
        return self.tool_executor.get_tool_definitions(self.allowed_tools)
    
    def _save_session_history(
        self,
        session_id: str,
        task: Dict[str, Any],
        result: Optional[str],
        status: str,
        error: Optional[str] = None
    ):
        """保存会话历史"""
        try:
            execution = {
                "status": status,
                "tool_calls": self.tool_calls_made,
                "outputs": self.outputs,
                "result": result,
                "error": error
            }
            
            self.history_manager.save_expert_session(
                skill_name=self.skill_name,
                session_id=session_id,
                task=task,
                execution=execution,
                conversation_history=self.conversation_history,
                summary=None
            )
        except Exception as e:
            logger.error(f"{self.agent_id}: Failed to save session history - {e}", exc_info=True)
