"""
AI Tools Model - Database operations for ai_tools table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from config.constant import (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_FAILED,
    AI_TOOL_STATUS_COMPLETED
)
import logging

logger = logging.getLogger(__name__)


class AITool:
    """AI Tool model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.prompt = kwargs.get('prompt')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
        self.image_path = kwargs.get('image_path')
        self.duration = kwargs.get('duration')
        self.ratio = kwargs.get('ratio')
        self.project_id = kwargs.get('project_id')
        self.transaction_id = kwargs.get('transaction_id')
        self.result_url = kwargs.get('result_url')
        self.user_id = kwargs.get('user_id')
        self.type = kwargs.get('type')
        self.status = kwargs.get('status')
        self.message = kwargs.get('message')
        self.image_size = kwargs.get('image_size')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'prompt': self.prompt,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None,
            'image_path': self.image_path,
            'duration': self.duration,
            'ratio': self.ratio,
            'project_id': self.project_id,
            'transaction_id': self.transaction_id,
            'result_url': self.result_url,
            'user_id': self.user_id,
            'type': self.type,
            'status': self.status,
            'message': self.message,
            'image_size': self.image_size
        }


class AIToolsModel:
    """AI Tools database operations"""
    
    @staticmethod
    def create(
        prompt: str,
        user_id: int,
        type: Optional[int] = None,
        image_path: Optional[str] = None,
        duration: Optional[int] = None,
        ratio: Optional[str] = None,
        project_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        result_url: Optional[str] = None,
        status: Optional[int] = AI_TOOL_STATUS_PENDING,
        message: Optional[str] = None,
        image_size: Optional[str] = None
    ) -> int:
        """
        Create a new AI tool record
        
        Args:
            prompt: Prompt text
            user_id: User ID
            type: Type (1-图片编辑, 2-AI视频生成, 3-图片生成视频, 4-图片高清)
            image_path: Image path (optional)
            duration: Video duration (optional)
            ratio: Video ratio (9:16, 16:9, 1:1, 3:4, 4:3)
            project_id: Project ID (optional)
            transaction_id: Transaction ID (optional)
            result_url: Result URL (optional)
            status: Status (AI_TOOL_STATUS_PENDING-未处理, AI_TOOL_STATUS_PROCESSING-正在处理, AI_TOOL_STATUS_FAILED-处理失败, AI_TOOL_STATUS_COMPLETED-处理完成, default: AI_TOOL_STATUS_PENDING)
            message: Error message (optional)
            image_size: Image size (1K, 2K, 4K) (optional)

        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO ai_tools 
            (prompt, user_id, type, image_path, duration, ratio, project_id, transaction_id, result_url, status, message, image_size)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (prompt, user_id, type, image_path, duration, ratio, project_id, transaction_id, result_url, status, message, image_size)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created AI tool record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create AI tool record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[AITool]:
        """
        Get AI tool record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            AITool object or None
        """
        sql = "SELECT * FROM ai_tools WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return AITool(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get AI tool record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def get_by_project_id(project_id: str) -> Optional[AITool]:
        """
        Get AI tool record by project ID
        
        Args:
            project_id: Project ID
        
        Returns:
            AITool object or None
        """
        sql = "SELECT * FROM ai_tools WHERE project_id = %s"
        
        try:
            result = execute_query(sql, (project_id,), fetch_one=True)
            if result:
                return AITool(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get AI tool record by project_id {project_id}: {e}")
            raise
     
    @staticmethod
    def list_by_user(
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        type: Optional[int] = None,
        type_list: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Get AI tool records list by user ID with pagination
        
        Args:
            user_id: User ID
            page: Page number (starting from 1)
            page_size: Number of records per page
            order_by: Order by field (create_time, update_time, id)
            order_direction: Order direction (ASC, DESC)
            type: Tool type filter (1-图片编辑, 2-AI视频生成, 3-图片生成视频, 4-图片高清放大)
            type_list: List of tool types to filter (alternative to type)
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        # Validate order_by and order_direction to prevent SQL injection
        valid_order_fields = ['id', 'create_time', 'update_time']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        # Build WHERE clause
        where_conditions = ["user_id = %s"]
        params = [user_id]
        
        if type_list is not None and len(type_list) > 0:
            # Use IN clause for multiple types
            placeholders = ','.join(['%s'] * len(type_list))
            where_conditions.append(f"type IN ({placeholders})")
            params.extend(type_list)
        elif type is not None:
            where_conditions.append("type = %s")
            params.append(type)
        
        where_clause = " AND ".join(where_conditions)
        
        # Get total count
        count_sql = f"SELECT COUNT(*) as total FROM ai_tools WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        # Get paginated data
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM ai_tools 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            tools = [AITool(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': tools
            }
        except Exception as e:
            logger.error(f"Failed to list AI tools for user {user_id}: {e}")
            raise
    
    @staticmethod
    def list_processing_by_user(user_id: int) -> List[AITool]:
        """
        Get all processing AI tool records by user ID (status = 1)
        
        Args:
            user_id: User ID
        
        Returns:
            List of AITool objects
        """
        sql = """
            SELECT * FROM ai_tools 
            WHERE user_id = %s AND status = %s
            ORDER BY create_time DESC
        """
        
        try:
            results = execute_query(sql, (user_id, AI_TOOL_STATUS_PROCESSING), fetch_all=True)
            tools = [AITool(**row) for row in results] if results else []
            return tools
        except Exception as e:
            logger.error(f"Failed to list processing AI tools for user {user_id}: {e}")
            raise
     
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update AI tool record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (prompt, type, image_path, duration, ratio, 
                     project_id, transaction_id, result_url, user_id, status, message, image_size)
        
        Returns:
            Number of affected rows
        """
        # Build update fields
        allowed_fields = [
            'prompt', 'type', 'image_path', 'duration', 'ratio',
            'project_id', 'transaction_id', 'result_url', 'user_id', 'status', 'message', 'image_size'
        ]
        
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
        sql = f"UPDATE ai_tools SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated AI tool record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update AI tool record {record_id}: {e}")
            raise
    
    @staticmethod
    def update_by_project_id(
        project_id: str,
        **kwargs
    ) -> int:
        """
        Update AI tool record by project ID
        
        Args:
            project_id: Project ID
            **kwargs: Fields to update
        
        Returns:
            Number of affected rows
        """
        allowed_fields = [
            'prompt', 'type', 'image_path', 'duration', 'ratio',
            'transaction_id', 'result_url', 'user_id', 'status', 'message', 'image_size'
        ]
        
        update_fields = []
        params = []
        
        for field, value in kwargs.items():
            if field in allowed_fields:
                update_fields.append(f"{field} = %s")
                params.append(value)
        
        if not update_fields:
            logger.warning("No valid fields to update")
            return 0
        
        params.append(project_id)
        sql = f"UPDATE ai_tools SET {', '.join(update_fields)} WHERE project_id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated AI tool record with project_id {project_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update AI tool record by project_id {project_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete AI tool record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM ai_tools WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted AI tool record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete AI tool record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete_by_user(user_id: int) -> int:
        """
        Delete all AI tool records for a user
        
        Args:
            user_id: User ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM ai_tools WHERE user_id = %s"
        
        try:
            affected_rows = execute_update(sql, (user_id,))
            logger.info(f"Deleted AI tool records for user {user_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete AI tool records for user {user_id}: {e}")
            raise
