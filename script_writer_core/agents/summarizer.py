import json
import logging
from typing import Dict, List, Any
from litellm import completion

logger = logging.getLogger(__name__)


class ConversationSummarizer:
    """对话精简器 - 负责压缩 PM 和 Expert 的沟通内容"""
    
    def __init__(self, model: str = "gemini/gemini-2.5-flash"):
        self.model = model
        self.summary_prompt = """你是一个专业的对话精简助手。

你的任务是将 PM（项目经理）和 Expert（专家）之间的对话内容压缩为简洁的摘要。

**精简原则**：
1. 保留关键决策和结论
2. 保留重要的文件操作（创建了什么、修改了什么）
3. 保留失败信息和错误原因
4. 删除冗余的问答和重复内容
5. 删除系统提示和工具调用的技术细节

**输出格式**：
```json
{
    "task": "任务简述",
    "expert": "执行的专家名称",
    "status": "success/failed/partial",
    "key_outputs": ["输出1", "输出2"],
    "decisions": ["决策1", "决策2"],
    "issues": ["问题1"],
    "summary": "一句话总结"
}
```

请严格按照JSON格式输出，不要添加其他内容。"""
    
    def summarize(
        self, 
        pm_context: str, 
        expert_conversation: List[Dict[str, Any]],
        expert_name: str
    ) -> Dict[str, Any]:
        """精简 PM 和 Expert 的对话"""
        try:
            conversation_text = self._format_conversation(expert_conversation)
            
            messages = [
                {"role": "system", "content": self.summary_prompt},
                {"role": "user", "content": f"""PM 上下文：
{pm_context}

Expert ({expert_name}) 对话记录：
{conversation_text}

请精简以上对话内容。"""}
            ]
            
            response = completion(
                model=self.model,
                messages=messages,
                temperature=0.3
            )
            
            content = response.choices[0].message.content.strip()
            
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            summary = json.loads(content)
            
            logger.info(f"Successfully summarized conversation for expert {expert_name}")
            return summary
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse summary JSON: {e}")
            return self._create_fallback_summary(expert_name, "failed", str(e))
        except Exception as e:
            logger.error(f"Failed to summarize conversation: {e}", exc_info=True)
            return self._create_fallback_summary(expert_name, "failed", str(e))
    
    def _format_conversation(self, conversation: List[Dict[str, Any]]) -> str:
        """格式化对话记录为文本"""
        lines = []
        for msg in conversation:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if isinstance(content, str):
                lines.append(f"[{role}]: {content[:500]}")
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if "text" in part:
                            lines.append(f"[{role}]: {part['text'][:500]}")
                        elif "tool_use" in part or "toolUse" in part:
                            tool_info = part.get("tool_use") or part.get("toolUse")
                            tool_name = tool_info.get("name", "unknown")
                            lines.append(f"[{role}]: 调用工具 {tool_name}")
        
        return "\n".join(lines)
    
    def _create_fallback_summary(
        self, 
        expert_name: str, 
        status: str, 
        error: str = ""
    ) -> Dict[str, Any]:
        """创建备用摘要"""
        return {
            "task": "未知任务",
            "expert": expert_name,
            "status": status,
            "key_outputs": [],
            "decisions": [],
            "issues": [error] if error else [],
            "summary": f"{expert_name} 执行结果: {status}"
        }
