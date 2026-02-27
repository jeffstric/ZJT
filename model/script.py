"""
Script Model - Database operations for script table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class Script:
    """Script model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.world_id = kwargs.get('world_id')
        self.user_id = kwargs.get('user_id')
        self.title = kwargs.get('title')
        self.episode_number = kwargs.get('episode_number')
        self.content = kwargs.get('content')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'world_id': self.world_id,
            'user_id': self.user_id,
            'title': self.title,
            'episode_number': self.episode_number,
            'content': self.content,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class ScriptModel:
    """Script database operations"""
    
    @staticmethod
    def create(
        world_id: int,
        user_id: int,
        title: str = '',
        episode_number: Optional[int] = None,
        content: Optional[str] = None
    ) -> int:
        """
        Create a new script record
        
        Args:
            world_id: World ID
            user_id: User ID
            title: Script title (default: '')
            episode_number: Episode number (optional)
            content: Script content (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO script 
            (world_id, user_id, title, episode_number, content)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = (world_id, user_id, title, episode_number, content)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created script record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create script record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[Script]:
        """
        Get script record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Script object or None
        """
        sql = "SELECT * FROM script WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Script(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get script record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def list_by_world(
        world_id: int,
        page: int = 1,
        page_size: int = 20,
        order_by: str = 'create_time',
        order_direction: str = 'DESC'
    ) -> Dict[str, Any]:
        """
        Get script records list by world ID with pagination
        
        Args:
            world_id: World ID
            page: Page number (starting from 1)
            page_size: Number of records per page
            order_by: Order by field (create_time, update_time, id, episode_number)
            order_direction: Order direction (ASC, DESC)
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        valid_order_fields = ['id', 'create_time', 'update_time', 'episode_number']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        where_clause = "world_id = %s"
        params = [world_id]
        
        count_sql = f"SELECT COUNT(*) as total FROM script WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM script 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            scripts = [Script(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': scripts
            }
        except Exception as e:
            logger.error(f"Failed to list scripts for world {world_id}: {e}")
            raise
    
    @staticmethod
    def list_by_user(
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        world_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get script records list by user ID with pagination
        
        Args:
            user_id: User ID
            page: Page number (starting from 1)
            page_size: Number of records per page
            order_by: Order by field (create_time, update_time, id, episode_number)
            order_direction: Order direction (ASC, DESC)
            world_id: Optional world ID filter
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        valid_order_fields = ['id', 'create_time', 'update_time', 'episode_number']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        where_conditions = ["user_id = %s"]
        params = [user_id]
        
        if world_id is not None:
            where_conditions.append("world_id = %s")
            params.append(world_id)
        
        where_clause = " AND ".join(where_conditions)
        
        count_sql = f"SELECT COUNT(*) as total FROM script WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM script 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            scripts = [Script(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': scripts
            }
        except Exception as e:
            logger.error(f"Failed to list scripts for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_by_episode(
        world_id: int,
        episode_number: int
    ) -> Optional[Script]:
        """
        Get script by world ID and episode number
        
        Args:
            world_id: World ID
            episode_number: Episode number
        
        Returns:
            Script object or None
        """
        sql = "SELECT * FROM script WHERE world_id = %s AND episode_number = %s LIMIT 1"
        
        try:
            result = execute_query(sql, (world_id, episode_number), fetch_one=True)
            if result:
                return Script(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get script by episode {episode_number} for world {world_id}: {e}")
            raise
    
    @staticmethod
    def get_by_title_and_world(
        title: str,
        world_id: int
    ) -> Optional[Script]:
        """
        Get script by title and world ID
        
        Args:
            title: Script title
            world_id: World ID
        
        Returns:
            Script object or None
        """
        sql = "SELECT * FROM script WHERE title = %s AND world_id = %s LIMIT 1"
        
        try:
            result = execute_query(sql, (title, world_id), fetch_one=True)
            if result:
                return Script(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get script by title '{title}' for world {world_id}: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update script record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (title, episode_number, content)
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['title', 'episode_number', 'content']
        
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
        sql = f"UPDATE script SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated script record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update script record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete script record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM script WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted script record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete script record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete_by_world(world_id: int) -> int:
        """
        Delete all script records for a world
        
        Args:
            world_id: World ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM script WHERE world_id = %s"
        
        try:
            affected_rows = execute_update(sql, (world_id,))
            logger.info(f"Deleted script records for world {world_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete script records for world {world_id}: {e}")
            raise
