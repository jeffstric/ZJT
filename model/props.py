from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
from .database import execute_query, execute_update, execute_insert
from config.constant import Edition

logger = logging.getLogger(__name__)


class Props:
    """Props model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.world_id = kwargs.get('world_id')
        self.name = kwargs.get('name')
        self.content = kwargs.get('content')
        self.reference_image = kwargs.get('reference_image')
        self.other_info = kwargs.get('other_info')
        self.user_id = kwargs.get('user_id')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'world_id': self.world_id,
            'name': self.name,
            'content': self.content,
            'reference_image': self.reference_image,
            'other_info': self.other_info,
            'user_id': self.user_id,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class PropsModel:
    """Props database operations"""
    
    @staticmethod
    def create(
        world_id: int,
        name: str,
        user_id: int,
        content: Optional[str] = None,
        reference_image: Optional[str] = None,
        other_info: Optional[str] = None
    ) -> int:
        """
        Create a new props record
        
        Args:
            world_id: World ID
            name: Props name
            user_id: User ID
            content: Props description (optional)
            reference_image: Reference image URL (optional)
            other_info: Other information (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO props 
            (world_id, name, user_id, content, reference_image, other_info)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (world_id, name, user_id, content, reference_image, other_info)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created props record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create props record: {e}")
            raise
    
    @staticmethod
    def get_by_id(props_id: int) -> Optional[Props]:
        """
        Get props record by ID
        
        Args:
            props_id: Props ID
        
        Returns:
            Props object or None if not found
        """
        sql = """
            SELECT id, world_id, name, content, reference_image, other_info, 
                   user_id, create_time, update_time
            FROM props
            WHERE id = %s
        """
        
        try:
            result = execute_query(sql, (props_id,), fetch_one=True)
            if result:
                return Props(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get props by ID {props_id}: {e}")
            raise
    
    @staticmethod
    def list_by_world(
        world_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        order_by: str = 'create_time',
        order_direction: str = 'DESC'
    ) -> Dict[str, Any]:
        """
        Get props list by world ID with pagination
        
        Args:
            world_id: World ID
            page: Page number (starting from 1)
            page_size: Number of records per page
            keyword: Search keyword for name or content (optional)
            order_by: Field to order by (default: create_time)
            order_direction: Order direction (ASC or DESC, default: DESC)
        
        Returns:
            Dictionary containing total count, page info, and data list
        """
        allowed_order_fields = ['id', 'name', 'create_time', 'update_time']
        if order_by not in allowed_order_fields:
            order_by = 'create_time'
        
        if order_direction.upper() not in ['ASC', 'DESC']:
            order_direction = 'DESC'
        
        offset = (page - 1) * page_size
        
        where_clause = "WHERE world_id = %s"
        params = [world_id]
        
        if keyword:
            where_clause += " AND (name LIKE %s OR content LIKE %s)"
            keyword_pattern = f"%{keyword}%"
            params.extend([keyword_pattern, keyword_pattern])
        
        count_sql = f"SELECT COUNT(*) as total FROM props {where_clause}"
        
        try:
            count_result = execute_query(count_sql, tuple(params), fetch_one=True)
            total = count_result['total'] if count_result else 0
            
            data_sql = f"""
                SELECT id, world_id, name, content, reference_image, other_info,
                       user_id, create_time, update_time
                FROM props
                {where_clause}
                ORDER BY {order_by} {order_direction}
                LIMIT %s OFFSET %s
            """
            params.extend([page_size, offset])
            
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            props_list = [Props(**row).to_dict() for row in results] if results else []
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': props_list
            }
        except Exception as e:
            logger.error(f"Failed to list props for world {world_id}: {e}")
            raise
    
    @staticmethod
    def update(
        props_id: int,
        name: Optional[str] = None,
        content: Optional[str] = None,
        reference_image: Optional[str] = None,
        other_info: Optional[str] = None
    ) -> int:
        """
        Update props record
        
        Args:
            props_id: Props ID
            name: Props name (optional)
            content: Props description (optional)
            reference_image: Reference image URL (optional)
            other_info: Other information (optional)
        
        Returns:
            Number of affected rows
        """
        update_fields = []
        params = []
        
        if name is not None:
            update_fields.append("name = %s")
            params.append(name)
        
        if content is not None:
            update_fields.append("content = %s")
            params.append(content)
        
        if reference_image is not None:
            update_fields.append("reference_image = %s")
            params.append(reference_image)
        
        if other_info is not None:
            update_fields.append("other_info = %s")
            params.append(other_info)
        
        if user_id is not None:
            update_fields.append("user_id = %s")
            params.append(user_id)
        
        if not update_fields:
            logger.warning(f"No fields to update for props {props_id}")
            return 0
        
        params.append(props_id)
        sql = f"""
            UPDATE props
            SET {', '.join(update_fields)}
            WHERE id = %s
        """
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update props {props_id}: {e}")
            raise
    
    @staticmethod
    def delete(props_id: int) -> int:
        """
        Delete props record
        
        Args:
            props_id: Props ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM props WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (props_id,))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete props {props_id}: {e}")
            raise
    
    @staticmethod
    def count_by_world(world_id: int) -> int:
        """
        Count props records by world ID
        
        Args:
            world_id: World ID
        
        Returns:
            Number of props records
        """
        sql = "SELECT COUNT(*) as total FROM props WHERE world_id = %s"
        
        try:
            results = execute_query(sql, (world_id,))
            return results[0]['total'] if results else 0
        except Exception as e:
            logger.error(f"Failed to count props for world {world_id}: {e}")
            raise
    
    @staticmethod
    def get_by_name(world_id: int, name: str) -> Optional[Props]:
        """
        Get props record by world ID and name
        
        Args:
            world_id: World ID
            name: Props name
        
        Returns:
            Props object or None if not found
        """
        sql = """
            SELECT id, world_id, name, content, reference_image, other_info,
                   user_id, create_time, update_time
            FROM props
            WHERE world_id = %s AND name = %s
        """
        
        try:
            results = execute_query(sql, (world_id, name))
            if results and len(results) > 0:
                return Props(**results[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get props by name '{name}' in world {world_id}: {e}")
            raise
