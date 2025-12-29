"""
Location Model - Database operations for location table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class Location:
    """Location model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.world_id = kwargs.get('world_id')
        self.name = kwargs.get('name')
        self.parent_id = kwargs.get('parent_id')
        self.reference_image = kwargs.get('reference_image')
        self.description = kwargs.get('description')
        self.user_id = kwargs.get('user_id')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'world_id': self.world_id,
            'name': self.name,
            'parent_id': self.parent_id,
            'reference_image': self.reference_image,
            'description': self.description,
            'user_id': self.user_id,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class LocationModel:
    """Location database operations"""
    
    @staticmethod
    def create(
        world_id: int,
        name: str,
        user_id: int,
        parent_id: Optional[int] = None,
        reference_image: Optional[str] = None,
        description: Optional[str] = None
    ) -> int:
        """
        Create a new location record
        
        Args:
            world_id: World ID
            name: Location name
            user_id: User ID
            parent_id: Parent location ID (optional)
            reference_image: Reference image path (optional)
            description: Location description (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO location 
            (world_id, name, user_id, parent_id, reference_image, description)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (world_id, name, user_id, parent_id, reference_image, description)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created location record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create location record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[Location]:
        """
        Get location record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Location object or None
        """
        sql = "SELECT * FROM location WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Location(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get location record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def list_by_world(
        world_id: int,
        page: int = 1,
        page_size: int = 10,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        keyword: Optional[str] = None,
        parent_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get location records list by world ID with pagination
        
        Args:
            world_id: World ID
            page: Page number (starting from 1)
            page_size: Number of records per page (default: 10)
            order_by: Order by field (create_time, update_time, id, name)
            order_direction: Order direction (ASC, DESC)
            keyword: Search keyword for name
            parent_id: Filter by parent location ID (None for root locations)
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        valid_order_fields = ['id', 'create_time', 'update_time', 'name']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        where_conditions = ["world_id = %s"]
        params = [world_id]
        
        if parent_id is not None:
            where_conditions.append("parent_id = %s")
            params.append(parent_id)
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions)
        
        count_sql = f"SELECT COUNT(*) as total FROM location WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM location 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            locations = [Location(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': locations
            }
        except Exception as e:
            logger.error(f"Failed to list locations for world {world_id}: {e}")
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
        Get location records list by user ID with pagination
        
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
        
        where_conditions = ["user_id = %s"]
        params = [user_id]
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions)
        
        count_sql = f"SELECT COUNT(*) as total FROM location WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM location 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            locations = [Location(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': locations
            }
        except Exception as e:
            logger.error(f"Failed to list locations for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_children(parent_id: int) -> List[Location]:
        """
        Get all child locations of a parent location
        
        Args:
            parent_id: Parent location ID
        
        Returns:
            List of Location objects
        """
        sql = "SELECT * FROM location WHERE parent_id = %s ORDER BY name"
        
        try:
            results = execute_query(sql, (parent_id,), fetch_all=True)
            return [Location(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get children for location {parent_id}: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update location record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (world_id, name, parent_id, reference_image, description)
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['world_id', 'name', 'parent_id', 'reference_image', 'description']
        
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
        sql = f"UPDATE location SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated location record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update location record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete location record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM location WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted location record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete location record {record_id}: {e}")
            raise
    
    @staticmethod
    def get_tree_by_world(world_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get location tree structure by world ID with optional limit
        
        Args:
            world_id: World ID
            limit: Maximum number of locations to return (prioritizes top-level, then level 1, etc.)
        
        Returns:
            List of location dictionaries with nested children
        """
        try:
            # Get all locations for the world, ordered by level (top-level first)
            sql = "SELECT * FROM location WHERE world_id = %s ORDER BY COALESCE(parent_id, 0), id"
            results = execute_query(sql, (world_id,), fetch_all=True)
            
            if not results:
                return []
            
            # Convert to Location objects
            all_locations = [Location(**row) for row in results]
            
            # Apply limit if specified - prioritize by level
            if limit is not None and len(all_locations) > limit:
                # Group by level
                level_groups = {}
                for loc in all_locations:
                    level = 0
                    # Calculate level by counting parent chain
                    temp_loc = loc
                    parent_map = {l.id: l for l in all_locations}
                    while temp_loc.parent_id is not None and temp_loc.parent_id in parent_map:
                        level += 1
                        temp_loc = parent_map[temp_loc.parent_id]
                    
                    if level not in level_groups:
                        level_groups[level] = []
                    level_groups[level].append(loc)
                
                # Select locations level by level until limit is reached
                selected_locations = []
                selected_ids = set()
                
                for level in sorted(level_groups.keys()):
                    for loc in level_groups[level]:
                        if len(selected_locations) >= limit:
                            break
                        # Include if parent is included or if it's top-level
                        if loc.parent_id is None or loc.parent_id in selected_ids:
                            selected_locations.append(loc)
                            selected_ids.add(loc.id)
                    if len(selected_locations) >= limit:
                        break
                
                all_locations = selected_locations
            
            # Build tree structure with only necessary fields
            location_map = {}
            for loc in all_locations:
                location_map[loc.id] = {
                    'id': loc.id,
                    'name': loc.name,
                    'parent_id': loc.parent_id,
                    'description': loc.description,
                    'children': []
                }
            
            # Build parent-child relationships
            root_locations = []
            for loc in all_locations:
                loc_dict = location_map[loc.id]
                if loc.parent_id is None:
                    root_locations.append(loc_dict)
                elif loc.parent_id in location_map:
                    location_map[loc.parent_id]['children'].append(loc_dict)
            
            return root_locations
            
        except Exception as e:
            logger.error(f"Failed to get location tree for world {world_id}: {e}")
            raise
