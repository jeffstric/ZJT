import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from script_writer_core.file_manager import FileManager

logger = logging.getLogger(__name__)


class ExpertHistoryManager:
    """Expert 历史记录管理器 - 复用 FileManager 路径管理"""
    
    def __init__(self, file_manager: FileManager, user_id: str, world_id: str):
        self.file_manager = file_manager
        self.user_id = user_id
        self.world_id = world_id
        
        self.base_path = self.file_manager._get_user_world_path(user_id, world_id)
        
        self.history_dir = self.base_path / "agent_history"
        self.expert_sessions_dir = self.history_dir / "expert_sessions"
        self.pm_summaries_dir = self.history_dir / "pm_summaries"
        
        self._ensure_directories()
    
    def _ensure_directories(self):
        """确保目录存在"""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.expert_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.pm_summaries_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"History directories ensured for user {self.user_id}, world {self.world_id}")
    
    def save_expert_session(
        self,
        skill_name: str,
        session_id: str,
        task: Dict[str, Any],
        execution: Dict[str, Any],
        conversation_history: List[Dict[str, Any]],
        summary: Optional[Dict[str, Any]] = None
    ) -> Path:
        """保存 Expert 会话历史"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{skill_name}_{timestamp}_{session_id[:8]}.json"
        filepath = self.expert_sessions_dir / filename
        
        session_data = {
            "metadata": {
                "skill_name": skill_name,
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "user_id": self.user_id,
                "world_id": self.world_id
            },
            "task": task,
            "execution": execution,
            "conversation_history": conversation_history,
            "summary": summary
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved expert session to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save expert session: {e}", exc_info=True)
            raise
    
    def save_pm_summary(
        self,
        session_id: str,
        task_summaries: List[Dict[str, Any]],
        overall_result: Dict[str, Any]
    ) -> Path:
        """保存 PM 会话摘要"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"session_{timestamp}_{session_id[:8]}.json"
        filepath = self.pm_summaries_dir / filename
        
        summary_data = {
            "metadata": {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "user_id": self.user_id,
                "world_id": self.world_id
            },
            "task_summaries": task_summaries,
            "overall_result": overall_result
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(summary_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved PM summary to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save PM summary: {e}", exc_info=True)
            raise
    
    def get_recent_expert_sessions(
        self, 
        skill_name: Optional[str] = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取最近的 Expert 会话"""
        sessions = []
        
        try:
            pattern = f"{skill_name}_*.json" if skill_name else "*.json"
            files = sorted(
                self.expert_sessions_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )[:limit]
            
            for filepath in files:
                with open(filepath, 'r', encoding='utf-8') as f:
                    sessions.append(json.load(f))
            
            logger.info(f"Retrieved {len(sessions)} recent expert sessions")
            return sessions
        except Exception as e:
            logger.error(f"Failed to get recent expert sessions: {e}", exc_info=True)
            return []
    
    def get_recent_pm_summaries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的 PM 摘要"""
        summaries = []
        
        try:
            files = sorted(
                self.pm_summaries_dir.glob("session_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )[:limit]
            
            for filepath in files:
                with open(filepath, 'r', encoding='utf-8') as f:
                    summaries.append(json.load(f))
            
            logger.info(f"Retrieved {len(summaries)} recent PM summaries")
            return summaries
        except Exception as e:
            logger.error(f"Failed to get recent PM summaries: {e}", exc_info=True)
            return []
