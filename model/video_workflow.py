"""
Video Workflow Model - Database operations for video_workflow table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from config.constant import Edition
import logging
import json

logger = logging.getLogger(__name__)


class VideoWorkflow:
    """Video Workflow model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.cover_image = kwargs.get('cover_image')
        self.user_id = kwargs.get('user_id')
        self.status = kwargs.get('status')
        self.workflow_data = kwargs.get('workflow_data')
        self.style = kwargs.get('style')
        self.style_reference_image = kwargs.get('style_reference_image')
        self.default_world_id = kwargs.get('default_world_id')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        workflow_data = self.workflow_data
        if isinstance(workflow_data, str):
            try:
                workflow_data = json.loads(workflow_data)
            except:
                pass
        
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'cover_image': self.cover_image,
            'user_id': self.user_id,
            'status': self.status,
            'workflow_data': workflow_data,
            'style': self.style,
            'style_reference_image': self.style_reference_image,
            'default_world_id': self.default_world_id,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class VideoWorkflowModel:
    """Video Workflow database operations"""
    
    @staticmethod
    def create(
        name: str,
        user_id: int,
        description: Optional[str] = None,
        cover_image: Optional[str] = None,
        status: int = 1,
        workflow_data: Optional[Dict] = None,
        style: Optional[str] = None,
        style_reference_image: Optional[str] = None,
        default_world_id: Optional[int] = None
    ) -> int:
        """
        Create a new video workflow record
        
        Args:
            name: Workflow name
            user_id: User ID
            description: Workflow description (optional)
            cover_image: Cover image URL (optional)
            status: Status (0-disabled, 1-enabled, 2-draft, default: 1)
            workflow_data: Workflow configuration data (optional)
            style: Style name (optional)
            style_reference_image: Style reference image URL (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO video_workflow 
            (name, user_id, description, cover_image, status, workflow_data, style, style_reference_image, default_world_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        workflow_data_str = json.dumps(workflow_data) if workflow_data else None
        params = (name, user_id, description, cover_image, status, workflow_data_str, style, style_reference_image, default_world_id)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created video workflow record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create video workflow record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[VideoWorkflow]:
        """
        Get video workflow record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            VideoWorkflow object or None
        """
        sql = "SELECT * FROM video_workflow WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return VideoWorkflow(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get video workflow record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def list_by_user(
        user_id: int,
        page: int = 1,
        page_size: int = 10,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        status: Optional[int] = None,
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get video workflow records list by user ID with pagination
        
        Args:
            user_id: User ID
            page: Page number (starting from 1)
            page_size: Number of records per page (default: 10)
            order_by: Order by field (create_time, update_time, id, name)
            order_direction: Order direction (ASC, DESC)
            status: Status filter (0-disabled, 1-enabled, 2-draft)
            keyword: Search keyword for name
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        # Validate order_by and order_direction to prevent SQL injection
        valid_order_fields = ['id', 'create_time', 'update_time', 'name']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        # Build WHERE clause
        where_conditions = []
        params = []
        
        # 商业版才按 user_id 过滤
        if Edition.is_enterprise():
            where_conditions.append("user_id = %s")
            params.append(user_id)
        
        if status is not None:
            where_conditions.append("status = %s")
            params.append(status)
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # Get total count
        count_sql = f"SELECT COUNT(*) as total FROM video_workflow WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        # Get paginated data (exclude workflow_data to reduce memory usage)
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT id, name, description, cover_image, user_id, status, style, style_reference_image, create_time, update_time 
            FROM video_workflow 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            workflows = [VideoWorkflow(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': workflows
            }
        except Exception as e:
            logger.error(f"Failed to list video workflows for user {user_id}: {e}")
            raise
    
    @staticmethod
    def list_all(
        page: int = 1,
        page_size: int = 10,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        status: Optional[int] = None,
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all video workflow records with pagination (admin use)
        
        Args:
            page: Page number (starting from 1)
            page_size: Number of records per page (default: 10)
            order_by: Order by field (create_time, update_time, id, name)
            order_direction: Order direction (ASC, DESC)
            status: Status filter
            keyword: Search keyword for name
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        valid_order_fields = ['id', 'create_time', 'update_time', 'name']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        where_conditions = []
        params = []
        
        if status is not None:
            where_conditions.append("status = %s")
            params.append(status)
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        count_sql = f"SELECT COUNT(*) as total FROM video_workflow WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        # Exclude workflow_data to reduce memory usage
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT id, name, description, cover_image, user_id, status, style, style_reference_image, create_time, update_time 
            FROM video_workflow 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            workflows = [VideoWorkflow(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': workflows
            }
        except Exception as e:
            logger.error(f"Failed to list all video workflows: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update video workflow record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (name, description, cover_image, status, workflow_data, style, style_reference_image)
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['name', 'description', 'cover_image', 'status', 'workflow_data', 'style', 'style_reference_image', 'default_world_id']
        
        update_fields = []
        params = []
        
        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'workflow_data' and isinstance(value, dict):
                    value = json.dumps(value)
                update_fields.append(f"{field} = %s")
                params.append(value)
        
        if not update_fields:
            logger.warning("No valid fields to update")
            return 0
        
        params.append(record_id)
        sql = f"UPDATE video_workflow SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated video workflow record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update video workflow record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete video workflow record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM video_workflow WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted video workflow record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete video workflow record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete_by_user(user_id: int) -> int:
        """
        Delete all video workflow records for a user
        
        Args:
            user_id: User ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM video_workflow WHERE user_id = %s"
        
        try:
            affected_rows = execute_update(sql, (user_id,))
            logger.info(f"Deleted video workflow records for user {user_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete video workflow records for user {user_id}: {e}")
            raise
    
    # ==================== 管理员方法 ====================
    
    @staticmethod
    def count_active_recent_days(days: int = 3) -> int:
        """
        统计最近N天有更新的工作流数量
        
        Args:
            days: 天数（默认3天）
        
        Returns:
            活跃工作流数量
        """
        sql = """
            SELECT COUNT(*) as count FROM video_workflow 
            WHERE update_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
        """
        try:
            result = execute_query(sql, (days,), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count active workflows in recent {days} days: {e}")
            raise
