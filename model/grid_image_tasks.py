"""
Grid Image Tasks Model - Database operations for grid_image_tasks table
宫格生图任务模型 - 支持多进程环境下的任务状态共享
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class GridImageTaskStatus:
    """宫格生图任务状态常量"""
    QUEUED = 0          # 队列中
    PROCESSING = 1      # 处理中
    COMPLETED = 2       # 完成
    FAILED = -1         # 失败
    TIMEOUT = -2        # 超时
    CANCELLED = -3      # 取消
    DOWNLOAD_FAILED = -4  # 下载失败


class GridImageTask:
    """Grid Image Task model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_key = kwargs.get('task_key')
        self.project_id = kwargs.get('project_id')
        self.item_type = kwargs.get('item_type')
        self.item_name = kwargs.get('item_name')
        self.user_id = kwargs.get('user_id')
        self.world_id = kwargs.get('world_id')
        self.comfyui_base_url = kwargs.get('comfyui_base_url')
        self.auth_token = kwargs.get('auth_token')
        self.status = kwargs.get('status', GridImageTaskStatus.QUEUED)
        self.try_count = kwargs.get('try_count', 0)
        self.max_attempts = kwargs.get('max_attempts', 60)
        self.error_message = kwargs.get('error_message')
        self.result_url = kwargs.get('result_url')
        self.local_file_path = kwargs.get('local_file_path')
        self.update_success = kwargs.get('update_success', 0)
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.completed_at = kwargs.get('completed_at')
        self.failed_at = kwargs.get('failed_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'task_key': self.task_key,
            'project_id': self.project_id,
            'item_type': self.item_type,
            'item_name': self.item_name,
            'user_id': self.user_id,
            'world_id': self.world_id,
            'status': self.status,
            'try_count': self.try_count,
            'max_attempts': self.max_attempts,
            'error_message': self.error_message,
            'result_url': self.result_url,
            'local_file_path': self.local_file_path,
            'update_success': self.update_success,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None
        }


class GridImageTasksModel:
    """Grid Image Tasks database operations"""
    
    @staticmethod
    def create(
        task_key: str,
        project_id: str,
        item_type: int,
        item_name: str,
        user_id: str,
        world_id: str,
        comfyui_base_url: str,
        auth_token: str,
        max_attempts: int = 60
    ) -> int:
        """
        创建新的宫格生图任务
        
        Args:
            task_key: 任务唯一键
            project_id: ComfyUI project_id
            item_type: 项目类型
            item_name: 项目名称
            user_id: 用户ID
            world_id: 世界观ID
            comfyui_base_url: ComfyUI服务地址
            auth_token: 认证令牌
            max_attempts: 最大尝试次数
        
        Returns:
            插入的记录ID
        
        Raises:
            Exception: 如果任务已存在（UNIQUE KEY冲突）
        """
        sql = """
            INSERT INTO grid_image_tasks 
            (task_key, project_id, item_type, item_name, user_id, world_id, 
             comfyui_base_url, auth_token, status, max_attempts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            task_key, project_id, item_type, item_name, user_id, world_id,
            comfyui_base_url, auth_token, GridImageTaskStatus.QUEUED, max_attempts
        )
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created grid image task: {task_key}, record_id: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create grid image task {task_key}: {e}")
            raise
    
    @staticmethod
    def get_by_task_key(task_key: str) -> Optional[GridImageTask]:
        """
        根据task_key获取任务
        
        Args:
            task_key: 任务唯一键
        
        Returns:
            GridImageTask对象或None
        """
        sql = "SELECT * FROM grid_image_tasks WHERE task_key = %s"
        
        try:
            result = execute_query(sql, (task_key,), fetch_one=True)
            if result:
                return GridImageTask(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get grid image task by task_key {task_key}: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[GridImageTask]:
        """
        根据ID获取任务
        
        Args:
            record_id: 记录ID
        
        Returns:
            GridImageTask对象或None
        """
        sql = "SELECT * FROM grid_image_tasks WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return GridImageTask(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get grid image task by id {record_id}: {e}")
            raise
    
    @staticmethod
    def get_pending_tasks(limit: int = 100) -> List[GridImageTask]:
        """
        获取待处理的任务（状态为QUEUED或PROCESSING）
        
        Args:
            limit: 最大返回数量
        
        Returns:
            GridImageTask对象列表
        """
        sql = """
            SELECT * FROM grid_image_tasks 
            WHERE status IN (%s, %s)
            ORDER BY created_at ASC
            LIMIT %s
        """
        
        try:
            results = execute_query(
                sql, 
                (GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING, limit),
                fetch_all=True
            )
            tasks = [GridImageTask(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to get pending grid image tasks: {e}")
            raise
    
    @staticmethod
    def get_user_tasks(user_id: str, world_id: str = None, limit: int = 50) -> List[GridImageTask]:
        """
        获取用户的任务列表
        
        Args:
            user_id: 用户ID
            world_id: 世界观ID（可选）
            limit: 最大返回数量
        
        Returns:
            GridImageTask对象列表
        """
        if world_id:
            sql = """
                SELECT * FROM grid_image_tasks 
                WHERE user_id = %s AND world_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (user_id, world_id, limit)
        else:
            sql = """
                SELECT * FROM grid_image_tasks 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (user_id, limit)
        
        try:
            results = execute_query(sql, params, fetch_all=True)
            tasks = [GridImageTask(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to get user grid image tasks: {e}")
            raise
    
    @staticmethod
    def update_status(
        task_key: str,
        status: int,
        error_message: str = None,
        result_url: str = None,
        local_file_path: str = None,
        update_success: int = None
    ) -> int:
        """
        更新任务状态
        
        Args:
            task_key: 任务唯一键
            status: 新状态
            error_message: 错误信息（可选）
            result_url: 结果URL（可选）
            local_file_path: 本地文件路径（可选）
            update_success: 是否成功更新到item（可选）
        
        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]
        
        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)
        
        if result_url is not None:
            update_fields.append("result_url = %s")
            params.append(result_url)
        
        if local_file_path is not None:
            update_fields.append("local_file_path = %s")
            params.append(local_file_path)
        
        if update_success is not None:
            update_fields.append("update_success = %s")
            params.append(update_success)
        
        # 根据状态设置完成/失败时间
        if status == GridImageTaskStatus.COMPLETED:
            update_fields.append("completed_at = NOW()")
        elif status in [GridImageTaskStatus.FAILED, GridImageTaskStatus.TIMEOUT, 
                       GridImageTaskStatus.DOWNLOAD_FAILED]:
            update_fields.append("failed_at = NOW()")
        
        params.append(task_key)
        sql = f"UPDATE grid_image_tasks SET {', '.join(update_fields)} WHERE task_key = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated grid image task {task_key} status to {status}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update grid image task {task_key}: {e}")
            raise
    
    @staticmethod
    def increment_try_count(task_key: str) -> int:
        """
        增加任务尝试次数
        
        Args:
            task_key: 任务唯一键
        
        Returns:
            影响的行数
        """
        sql = "UPDATE grid_image_tasks SET try_count = try_count + 1 WHERE task_key = %s"
        
        try:
            affected_rows = execute_update(sql, (task_key,))
            logger.info(f"Incremented try_count for task {task_key}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to increment try_count for task {task_key}: {e}")
            raise
    
    @staticmethod
    def delete_by_task_key(task_key: str) -> int:
        """
        删除任务
        
        Args:
            task_key: 任务唯一键
        
        Returns:
            影响的行数
        """
        sql = "DELETE FROM grid_image_tasks WHERE task_key = %s"
        
        try:
            affected_rows = execute_update(sql, (task_key,))
            logger.info(f"Deleted grid image task {task_key}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete grid image task {task_key}: {e}")
            raise
    
    @staticmethod
    def cleanup_old_tasks(days: int = 7) -> int:
        """
        清理旧任务（已完成或失败的任务）
        
        Args:
            days: 保留天数
        
        Returns:
            删除的行数
        """
        sql = """
            DELETE FROM grid_image_tasks 
            WHERE status IN (%s, %s, %s, %s, %s)
            AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        """
        params = (
            GridImageTaskStatus.COMPLETED,
            GridImageTaskStatus.FAILED,
            GridImageTaskStatus.TIMEOUT,
            GridImageTaskStatus.CANCELLED,
            GridImageTaskStatus.DOWNLOAD_FAILED,
            days
        )
        
        try:
            affected_rows = execute_update(sql, params)
            if affected_rows > 0:
                logger.info(f"Cleaned up {affected_rows} old grid image tasks (older than {days} days)")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to cleanup old grid image tasks: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `grid_image_tasks` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `task_key` varchar(255) NOT NULL COMMENT '任务唯一键 (格式: item_type_item_name)',
  `project_id` varchar(100) NOT NULL COMMENT 'ComfyUI project_id',
  `item_type` tinyint NOT NULL COMMENT '项目类型 (1=character, 2=location, 3=props, 4=character_grid, 5=location_grid, 6=prop_grid)',
  `item_name` varchar(255) NOT NULL COMMENT '项目名称（宫格任务为逗号分隔的多个名称）',
  `user_id` varchar(50) NOT NULL COMMENT '用户ID',
  `world_id` varchar(50) NOT NULL COMMENT '世界观ID',
  `comfyui_base_url` varchar(500) NOT NULL COMMENT 'ComfyUI服务地址',
  `auth_token` varchar(500) NOT NULL COMMENT '认证令牌',
  `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中, 1-处理中, 2-完成, -1-失败, -2-超时, -3-取消, -4-下载失败）',
  `try_count` int DEFAULT '0' COMMENT '尝试次数',
  `max_attempts` int DEFAULT '60' COMMENT '最大尝试次数',
  `error_message` text COMMENT '错误信息',
  `result_url` varchar(1000) DEFAULT NULL COMMENT '结果图片URL',
  `local_file_path` varchar(1000) DEFAULT NULL COMMENT '本地文件路径',
  `update_success` tinyint DEFAULT '0' COMMENT '是否成功更新到item (0-否, 1-是)',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
  `failed_at` datetime DEFAULT NULL COMMENT '失败时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_key` (`task_key`),
  KEY `idx_status` (`status`),
  KEY `idx_user_world` (`user_id`,`world_id`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='宫格生图任务表';
"""
