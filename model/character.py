"""
Character Model - Database operations for character table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging
import json

logger = logging.getLogger(__name__)


class Character:
    """Character model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.world_id = kwargs.get('world_id')
        self.name = kwargs.get('name')
        self.age = kwargs.get('age')
        self.identity = kwargs.get('identity')
        self.appearance = kwargs.get('appearance')
        self.personality = kwargs.get('personality')
        self.behavior = kwargs.get('behavior')
        self.other_info = kwargs.get('other_info')
        self.reference_image = kwargs.get('reference_image')
        self.default_voice = kwargs.get('default_voice')
        self.emotion_voices = kwargs.get('emotion_voices')
        self.sora_character = kwargs.get('sora_character')
        self.user_id = kwargs.get('user_id')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        emotion_voices = self.emotion_voices
        if isinstance(emotion_voices, str):
            try:
                emotion_voices = json.loads(emotion_voices)
            except:
                pass
        
        return {
            'id': self.id,
            'world_id': self.world_id,
            'name': self.name,
            'age': self.age,
            'identity': self.identity,
            'appearance': self.appearance,
            'personality': self.personality,
            'behavior': self.behavior,
            'other_info': self.other_info,
            'reference_image': self.reference_image,
            'default_voice': self.default_voice,
            'emotion_voices': emotion_voices,
            'sora_character': self.sora_character,
            'user_id': self.user_id,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class CharacterModel:
    """Character database operations"""
    
    @staticmethod
    def create(
        world_id: int,
        name: str,
        user_id: int,
        age: Optional[str] = None,
        identity: Optional[str] = None,
        appearance: Optional[str] = None,
        personality: Optional[str] = None,
        behavior: Optional[str] = None,
        other_info: Optional[str] = None,
        reference_image: Optional[str] = None,
        default_voice: Optional[str] = None,
        emotion_voices: Optional[Dict] = None,
        sora_character: Optional[str] = None
    ) -> int:
        """
        Create a new character record
        
        Args:
            world_id: World ID
            name: Character name
            user_id: User ID
            age: Age (optional)
            identity: Identity (optional)
            appearance: Appearance description (optional)
            personality: Personality traits (optional)
            behavior: Behavior (optional)
            other_info: Other information (optional)
            reference_image: Reference image path (optional)
            default_voice: Default voice file path (optional)
            emotion_voices: Emotion voices dict (optional)
            sora_character: Sora character ID (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO `character` 
            (world_id, name, age, identity, appearance, personality, behavior, other_info, 
             reference_image, default_voice, emotion_voices, sora_character, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        emotion_voices_str = json.dumps(emotion_voices) if emotion_voices else None
        params = (world_id, name, age, identity, appearance, personality, behavior, other_info, reference_image,
                 default_voice, emotion_voices_str, sora_character, user_id)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created character record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create character record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[Character]:
        """
        Get character record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Character object or None
        """
        sql = "SELECT * FROM `character` WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Character(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get character record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def list_by_world(
        world_id: int,
        page: int = 1,
        page_size: int = 10,
        order_by: str = 'create_time',
        order_direction: str = 'DESC',
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get character records list by world ID with pagination
        
        Args:
            world_id: World ID
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
        
        where_conditions = ["world_id = %s"]
        params = [world_id]
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions)
        
        count_sql = f"SELECT COUNT(*) as total FROM `character` WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM `character` 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            characters = [Character(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': characters
            }
        except Exception as e:
            logger.error(f"Failed to list characters for world {world_id}: {e}")
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
        Get character records list by user ID with pagination
        
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
        
        count_sql = f"SELECT COUNT(*) as total FROM `character` WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM `character` 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            characters = [Character(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': characters
            }
        except Exception as e:
            logger.error(f"Failed to list characters for user {user_id}: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update character record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['world_id', 'name', 'age', 'occupation', 'identity', 
                         'appearance', 'personality', 'behavior_habits', 'other_info',
                         'reference_image', 'default_voice', 'emotion_voices', 'sora_character']
        
        update_fields = []
        params = []
        
        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'emotion_voices' and isinstance(value, dict):
                    value = json.dumps(value)
                update_fields.append(f"{field} = %s")
                params.append(value)
        
        if not update_fields:
            logger.warning("No valid fields to update")
            return 0
        
        params.append(record_id)
        sql = f"UPDATE `character` SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated character record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update character record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete character record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM `character` WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted character record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete character record {record_id}: {e}")
            raise
