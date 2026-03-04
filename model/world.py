"""
World Model - Database operations for world table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from config.constant import Edition
import logging

logger = logging.getLogger(__name__)


class World:
    """World model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.story_outline = kwargs.get('story_outline')
        self.visual_style = kwargs.get('visual_style')
        self.era_environment = kwargs.get('era_environment')
        self.color_language = kwargs.get('color_language')
        self.composition_preference = kwargs.get('composition_preference')
        self.user_id = kwargs.get('user_id')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'story_outline': self.story_outline,
            'visual_style': self.visual_style,
            'era_environment': self.era_environment,
            'color_language': self.color_language,
            'composition_preference': self.composition_preference,
            'user_id': self.user_id,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class WorldModel:
    """World database operations"""
    
    @staticmethod
    def create(
        name: str,
        user_id: int,
        description: Optional[str] = None,
        story_outline: Optional[str] = None,
        visual_style: Optional[str] = None,
        era_environment: Optional[str] = None,
        color_language: Optional[str] = None,
        composition_preference: Optional[str] = None
    ) -> int:
        """
        Create a new world record
        
        Args:
            name: World name
            user_id: User ID
            description: World description (optional)
            story_outline: Story outline (optional)
            visual_style: Visual style (optional)
            era_environment: Era environment (optional)
            color_language: Color language (optional)
            composition_preference: Composition preference (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO world 
            (name, user_id, description, story_outline, visual_style, era_environment, color_language, composition_preference)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (name, user_id, description, story_outline, visual_style, era_environment, color_language, composition_preference)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created world record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create world record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[World]:
        """
        Get world record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            World object or None
        """
        sql = "SELECT * FROM world WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return World(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get world record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def list_by_user(
        user_id: int,
        page: int = 1,
        page_size: int = 10,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get world records list by user ID with pagination
        
        Args:
            user_id: User ID
            page: Page number (starting from 1)
            page_size: Number of records per page (default: 10)
            order_by: Order by field (create_time, update_time, id, name)
            order_direction: Order direction (ASC, DESC)
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
        
        # 商业版才按 user_id 过滤
        if Edition.is_enterprise():
            where_conditions.append("user_id = %s")
            params.append(user_id)
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        count_sql = f"SELECT COUNT(*) as total FROM world WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM world 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            worlds = [World(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': worlds
            }
        except Exception as e:
            logger.error(f"Failed to list worlds for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_by_name(
        user_id: int,
        name: str
    ) -> Optional[World]:
        """
        Get a world by user and name (exact match)
        """
        sql = "SELECT * FROM world WHERE user_id = %s AND name = %s LIMIT 1"
        
        try:
            result = execute_query(sql, (user_id, name), fetch_one=True)
            if result:
                return World(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get world by name '{name}' for user {user_id}: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update world record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (name, description)
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['name', 'description', 'story_outline', 'visual_style', 'era_environment', 'color_language', 'composition_preference']
        
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
        sql = f"UPDATE world SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated world record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update world record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete world record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM world WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted world record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete world record {record_id}: {e}")
            raise
