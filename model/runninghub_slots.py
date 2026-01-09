"""
RunningHub Slots Model - 并发槽位管理
用于控制 RunningHub API 的并发请求数量，避免 TASK_QUEUE_MAXED 错误
"""
from typing import Optional
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging
import yaml
import os
from config_util import get_config_path

logger = logging.getLogger(__name__)

# 加载配置文件
config_path = get_config_path()
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 从配置文件读取最大槽位数量，默认为3
MAX_CONCURRENT_SLOTS = config.get("runninghub", {}).get("max_concurrent_slots", 3)


class RunningHubSlot:
    """RunningHub 槽位模型类"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_id = kwargs.get('task_id')
        self.task_table_id = kwargs.get('task_table_id')
        self.project_id = kwargs.get('project_id')
        self.task_type = kwargs.get('task_type')
        self.status = kwargs.get('status')
        self.acquired_at = kwargs.get('acquired_at')
        self.released_at = kwargs.get('released_at')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'task_table_id': self.task_table_id,
            'project_id': self.project_id,
            'task_type': self.task_type,
            'status': self.status,
            'acquired_at': self.acquired_at.isoformat() if self.acquired_at else None,
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class RunningHubSlotsModel:
    """RunningHub 槽位管理模型"""
    
    @staticmethod
    def count_active_slots() -> int:
        """
        统计当前活跃的槽位数量
        
        Returns:
            活跃槽位数量
        """
        sql = """
            SELECT COUNT(*) as count 
            FROM runninghub_slots 
            WHERE status = 1
        """
        try:
            result = execute_query(sql, fetch_one=True)
            count = result['count'] if result else 0
            logger.debug(f"Active RunningHub slots: {count}")
            return count
        except Exception as e:
            logger.error(f"Failed to count active slots: {e}")
            return 0
    
    @staticmethod
    def try_acquire_slot(task_table_id: int, task_id: int, task_type: int, max_slots: int = None) -> bool:
        """
        尝试获取槽位（带并发检查）
        
        Args:
            task_table_id: tasks表的主键id
            task_id: tasks表的task_id (对应 ai_tools.id)
            task_type: 任务类型 (10-LTX2.0, 11-Wan2.2)
            max_slots: 最大槽位数，默认从配置文件读取
        
        Returns:
            是否成功获取槽位
        """
        try:
            # 如果未指定 max_slots，使用配置文件中的值
            if max_slots is None:
                max_slots = MAX_CONCURRENT_SLOTS
            
            # 检查当前槽位数量
            current_count = RunningHubSlotsModel.count_active_slots()
            
            if current_count >= max_slots:
                logger.info(f"RunningHub slots full ({current_count}/{max_slots}), cannot acquire for task {task_id}")
                return False
            
            # 尝试插入槽位记录
            sql = """
                INSERT INTO runninghub_slots 
                (task_table_id, task_id, task_type, status)
                VALUES (%s, %s, %s, 1)
            """
            execute_insert(sql, (task_table_id, task_id, task_type))
            
            logger.info(f"Acquired RunningHub slot for task {task_id} (table_id: {task_table_id}), slots: {current_count + 1}/{max_slots}")
            return True
            
        except Exception as e:
            # 可能是唯一键冲突（已经获取过槽位）
            logger.warning(f"Failed to acquire slot for task {task_id}: {e}")
            return False
    
    @staticmethod
    def update_project_id(task_table_id: int, project_id: str) -> int:
        """
        更新槽位的 project_id（任务提交成功后）
        
        Args:
            task_table_id: tasks表的主键id
            project_id: RunningHub项目ID
        
        Returns:
            影响的行数
        """
        sql = """
            UPDATE runninghub_slots 
            SET project_id = %s
            WHERE task_table_id = %s AND status = 1
        """
        try:
            affected = execute_update(sql, (project_id, task_table_id))
            logger.info(f"Updated project_id for task_table_id {task_table_id}: {project_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update project_id for task_table_id {task_table_id}: {e}")
            return 0
    
    @staticmethod
    def release_slot_by_task_table_id(task_table_id: int) -> int:
        """
        通过 task_table_id 释放槽位
        
        Args:
            task_table_id: tasks表的主键id
        
        Returns:
            影响的行数
        """
        sql = """
            UPDATE runninghub_slots 
            SET status = 2, released_at = NOW()
            WHERE task_table_id = %s AND status = 1
        """
        try:
            affected = execute_update(sql, (task_table_id,))
            if affected > 0:
                logger.info(f"Released RunningHub slot for task_table_id {task_table_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to release slot for task_table_id {task_table_id}: {e}")
            return 0
    
    @staticmethod
    def release_slot_by_project_id(project_id: str) -> int:
        """
        通过 project_id 释放槽位
        
        Args:
            project_id: RunningHub项目ID
        
        Returns:
            影响的行数
        """
        sql = """
            UPDATE runninghub_slots 
            SET status = 2, released_at = NOW()
            WHERE project_id = %s AND status = 1
        """
        try:
            affected = execute_update(sql, (project_id,))
            if affected > 0:
                logger.info(f"Released RunningHub slot for project_id {project_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to release slot for project_id {project_id}: {e}")
            return 0
    
    @staticmethod
    def get_slot_by_task_table_id(task_table_id: int) -> Optional[RunningHubSlot]:
        """
        通过 task_table_id 获取槽位信息
        
        Args:
            task_table_id: tasks表的主键id
        
        Returns:
            RunningHubSlot 对象或 None
        """
        sql = """
            SELECT * FROM runninghub_slots 
            WHERE task_table_id = %s
        """
        try:
            result = execute_query(sql, (task_table_id,), fetch_one=True)
            if result:
                return RunningHubSlot(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get slot for task_table_id {task_table_id}: {e}")
            return None
    
    @staticmethod
    def cleanup_stale_slots(timeout_minutes: int = 60) -> int:
        """
        清理超时的槽位（超过指定时间仍未完成的任务）
        
        Args:
            timeout_minutes: 超时时间（分钟），默认60分钟
        
        Returns:
            清理的槽位数量
        """
        sql = """
            UPDATE runninghub_slots 
            SET status = 2, released_at = NOW()
            WHERE status = 1 
            AND acquired_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
        """
        try:
            affected = execute_update(sql, (timeout_minutes,))
            if affected > 0:
                logger.warning(f"Cleaned up {affected} stale RunningHub slots (timeout: {timeout_minutes}min)")
            return affected
        except Exception as e:
            logger.error(f"Failed to cleanup stale slots: {e}")
            return 0
