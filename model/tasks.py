"""
Tasks Model - Database operations for tasks table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from config.constant import (
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED
)
import logging

logger = logging.getLogger(__name__)


class Task:
    """Task model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_type = kwargs.get('task_type')
        self.task_id = kwargs.get('task_id')
        self.try_count = kwargs.get('try_count', 0)
        self.status = kwargs.get('status', TASK_STATUS_QUEUED)
        self.next_trigger = kwargs.get('next_trigger')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'task_type': self.task_type,
            'task_id': self.task_id,
            'try_count': self.try_count,
            'status': self.status,
            'next_trigger': self.next_trigger.isoformat() if self.next_trigger else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class TasksModel:
    """Tasks database operations"""
    
    @staticmethod
    def create(
        task_type: str,
        task_id: int,
        try_count: int = 0,
        status: int = TASK_STATUS_QUEUED
    ) -> int:
        """
        Create a new task record
        
        Args:
            task_type: Task type
            task_id: Task ID
            try_count: Failure retry count (default: 0)
            status: Status (TASK_STATUS_QUEUED-队列中, TASK_STATUS_PROCESSING-处理中, TASK_STATUS_COMPLETED-处理完成, TASK_STATUS_FAILED-处理失败, default: TASK_STATUS_QUEUED)
            next_trigger: Next execution time (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO tasks 
            (task_type, task_id, try_count, status)
            VALUES (%s, %s, %s, %s)
        """
        params = (task_type, task_id, try_count, status)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created task record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create task record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[Task]:
        """
        Get task record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Task object or None
        """
        sql = "SELECT * FROM tasks WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Task(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get task record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def get_by_task_id(task_id: int) -> Optional[Task]:
        """
        Get task record by task ID
        
        Args:
            task_id: Task ID
        
        Returns:
            Task object or None
        """
        sql = "SELECT * FROM tasks WHERE task_id = %s"
        
        try:
            result = execute_query(sql, (task_id,), fetch_one=True)
            if result:
                return Task(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get task record by task_id {task_id}: {e}")
            raise
    
    @staticmethod
    def list_by_type(
        task_type: str,
        page: int = 1,
        page_size: int = 20,
        order_by: str = 'created_at',
        order_direction: str = 'DESC'
    ) -> Dict[str, Any]:
        """
        Get task records list by task type with pagination
        
        Args:
            task_type: Task type
            page: Page number (starting from 1)
            page_size: Number of records per page
            order_by: Order by field (created_at, updated_at, next_trigger, id)
            order_direction: Order direction (ASC, DESC)
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        valid_order_fields = ['id', 'created_at', 'updated_at', 'next_trigger']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'created_at'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        count_sql = "SELECT COUNT(*) as total FROM tasks WHERE task_type = %s"
        count_result = execute_query(count_sql, (task_type,), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM tasks 
            WHERE task_type = %s
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        try:
            results = execute_query(data_sql, (task_type, page_size, offset), fetch_all=True)
            tasks = [Task(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': tasks
            }
        except Exception as e:
            logger.error(f"Failed to list tasks for type {task_type}: {e}")
            raise
    
    @staticmethod
    def list_pending_tasks(limit: int = 100) -> List[Task]:
        """
        Get pending tasks that need to be executed (next_trigger <= now)
        
        Args:
            limit: Maximum number of tasks to return
        
        Returns:
            List of Task objects
        """
        sql = """
            SELECT * FROM tasks 
            WHERE next_trigger <= NOW()
            ORDER BY next_trigger ASC
            LIMIT %s
        """
        
        try:
            results = execute_query(sql, (limit,), fetch_all=True)
            tasks = [Task(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to list pending tasks: {e}")
            raise
    
    @staticmethod
    def list_by_type_and_status(
        task_type: str,
        status_list: List[int] = None
    ) -> List[Task]:
        """
        Get tasks by type and status list
        
        Args:
            task_type: Task type
            status_list: List of status values to filter (default: [TASK_STATUS_QUEUED, TASK_STATUS_PROCESSING])
        
        Returns:
            List of Task objects
        """
        if status_list is None:
            status_list = [TASK_STATUS_QUEUED, TASK_STATUS_PROCESSING]
        
        placeholders = ','.join(['%s'] * len(status_list))
        sql = f"""
            SELECT * FROM tasks 
            WHERE task_type = %s 
            AND status IN ({placeholders})
            AND next_trigger <= NOW()
            ORDER BY created_at ASC
        """
        
        params = [task_type] + status_list
        
        try:
            results = execute_query(sql, tuple(params), fetch_all=True)
            tasks = [Task(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to list tasks by type and status: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update task record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (task_type, task_id, try_count, status, next_trigger)
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['task_type', 'task_id', 'try_count', 'status', 'next_trigger']
        
        update_fields = []
        params = []
        
        for field, value in kwargs.items():
            if field in allowed_fields:
                update_fields.append(f"{field} = %s")
                params.append(value)
        
        if not update_fields:
            logger.warning("No valid fields to update")
            return 0
        
        params.append(record_id)
        sql = f"UPDATE tasks SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated task record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update task record {record_id}: {e}")
            raise
    
    @staticmethod
    def update_by_task_id(
        task_id: int,
        **kwargs
    ) -> int:
        """
        Update task record by task ID
        
        Args:
            task_id: Task ID
            **kwargs: Fields to update
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['task_type', 'try_count', 'status', 'next_trigger']
        
        update_fields = []
        params = []
        
        for field, value in kwargs.items():
            if field in allowed_fields:
                update_fields.append(f"{field} = %s")
                params.append(value)
        
        if not update_fields:
            logger.warning("No valid fields to update")
            return 0
        
        params.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(update_fields)} WHERE task_id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated task record with task_id {task_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update task record by task_id {task_id}: {e}")
            raise
    
    @staticmethod
    def increment_try_count(task_id: int) -> int:
        """
        Increment try_count for a task
        
        Args:
            task_id: Task ID
        
        Returns:
            Number of affected rows
        """
        sql = "UPDATE tasks SET try_count = try_count + 1 WHERE task_id = %s"
        
        try:
            affected_rows = execute_update(sql, (task_id,))
            logger.info(f"Incremented try_count for task {task_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to increment try_count for task {task_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete task record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM tasks WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted task record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete task record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete_by_task_id(task_id: int) -> int:
        """
        Delete task record by task ID
        
        Args:
            task_id: Task ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM tasks WHERE task_id = %s"
        
        try:
            affected_rows = execute_update(sql, (task_id,))
            logger.info(f"Deleted task record with task_id {task_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete task record by task_id {task_id}: {e}")
            raise
