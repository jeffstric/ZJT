from datetime import datetime
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class BaseAgent:
    """智能体基类"""
    
    def __init__(
        self, 
        agent_id: str, 
        skill_names: List[str], 
        model: str, 
        allowed_tools: List[str], 
        system_prompt: str
    ):
        self.agent_id = agent_id
        self.skill_names = skill_names
        # 保留 skill_name 用于向后兼容（使用第一个技能）
        self.skill_name = skill_names[0] if skill_names else "unknown"
        self.model = model
        self.allowed_tools = allowed_tools
        self.system_prompt = system_prompt
        self.conversation_history: List[Dict[str, Any]] = []
        self.created_at = datetime.now()
        
        logger.info(f"Initialized {self.__class__.__name__} - ID: {agent_id}, Skills: {', '.join(skill_names)}")
    
    def send_message(self, message: str, **kwargs) -> Dict[str, Any]:
        """发送消息并获取响应"""
        raise NotImplementedError("Subclasses must implement send_message()")
    
    def handle_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理工具调用"""
        if tool_name not in self.allowed_tools:
            error_msg = f"工具 {tool_name} 不在允许列表中"
            logger.warning(f"{self.agent_id}: {error_msg}")
            return {"error": error_msg}
        
        return self._execute_tool(tool_name, tool_args)
    
    def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具调用 - 由子类实现具体逻辑"""
        raise NotImplementedError("Subclasses must implement _execute_tool()")
    
    def add_to_history(self, role: str, content: Any):
        """添加消息到对话历史"""
        logger.debug(f"{self.agent_id}: add_to_history called - role={role}, content type={type(content).__name__}")
        
        if role == "tool":
            logger.info(f"{self.agent_id}: Adding TOOL message to conversation_history:")
            logger.info(f"{self.agent_id}:   - content type: {type(content).__name__}")
            if isinstance(content, dict):
                logger.info(f"{self.agent_id}:   - content keys: {list(content.keys())}")
                logger.info(f"{self.agent_id}:   - content: {content}")
            else:
                logger.warning(f"{self.agent_id}:   - WARNING: content is not dict, it's {type(content).__name__}: {content}")
        
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        logger.debug(f"{self.agent_id}: conversation_history now has {len(self.conversation_history)} messages")
    
    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        logger.info(f"{self.agent_id}: 对话历史已清空")
    
    def get_history_summary(self) -> str:
        """获取对话历史摘要"""
        return f"对话轮次: {len(self.conversation_history)}, 创建时间: {self.created_at}"
