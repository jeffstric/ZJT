"""
Voice Model - Database operations for voice table
音色库数据模型（包含公共音色和用户私有音色）
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class Voice:
    """Voice model class (public voice when user_id=0, private voice when user_id>0)"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id', 0)
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.audio_url = kwargs.get('audio_url')
        self.gender = kwargs.get('gender')
        self.language = kwargs.get('language')
        self.sort_order = kwargs.get('sort_order', 0)
        self.is_active = kwargs.get('is_active', 1)
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'audio_url': self.audio_url,
            'gender': self.gender,
            'language': self.language,
            'sort_order': self.sort_order,
            'is_active': self.is_active,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class VoiceModel:
    """Voice database operations"""
    
    @staticmethod
    def create(
        name: str,
        audio_url: str,
        user_id: int = 0,
        description: Optional[str] = None,
        gender: Optional[str] = None,
        language: Optional[str] = None,
        sort_order: int = 0,
        is_active: int = 1
    ) -> int:
        """
        Create a new voice record
        
        Args:
            name: Voice name
            audio_url: Audio file URL
            user_id: User ID (0 for public voice, >0 for private voice)
            description: Voice description (optional)
            gender: Gender (optional, e.g., 'male', 'female', 'child')
            language: Language code (optional, e.g., 'zh', 'en', 'ja')
            sort_order: Sort order (default: 0)
            is_active: Is active flag (default: 1)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO voice 
            (user_id, name, description, audio_url, gender, language, sort_order, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (user_id, name, description, audio_url, gender, language, sort_order, is_active)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created voice record with ID: {record_id}, user_id: {user_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create voice record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[Voice]:
        """
        Get voice record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Voice object or None
        """
        sql = "SELECT * FROM voice WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Voice(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get voice record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def list_all(
        page: int = 1,
        page_size: int = 50,
        user_id: Optional[int] = None,
        gender: Optional[str] = None,
        language: Optional[str] = None,
        only_active: bool = True,
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get voice records list with pagination and filtering
        
        Args:
            page: Page number (starting from 1)
            page_size: Number of records per page (default: 50)
            user_id: Filter by user_id (0 for public, >0 for specific user, None for all)
            gender: Filter by gender (optional)
            language: Filter by language (optional)
            only_active: Only return active records (default: True)
            keyword: Search keyword for name (optional)
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        where_conditions = []
        params = []
        
        if only_active:
            where_conditions.append("is_active = 1")
        
        if user_id is not None:
            where_conditions.append("user_id = %s")
            params.append(user_id)
        
        if gender:
            where_conditions.append("gender = %s")
            params.append(gender)
        
        if language:
            where_conditions.append("language = %s")
            params.append(language)
        
        if keyword:
            where_conditions.append("name LIKE %s")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        count_sql = f"SELECT COUNT(*) as total FROM voice WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM voice 
            WHERE {where_clause}
            ORDER BY sort_order ASC, id ASC
            LIMIT %s OFFSET %s
        """
        
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            voices = [Voice(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': voices
            }
        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update voice record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update
        
        Returns:
            Number of affected rows
        """
        allowed_fields = ['user_id', 'name', 'description', 'audio_url', 
                         'gender', 'language', 'sort_order', 'is_active']
        
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
        sql = f"UPDATE voice SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated voice record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update voice record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete voice record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM voice WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted voice record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete voice record {record_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `ai_audio` (
  `id` int NOT NULL AUTO_INCREMENT,
  `text` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '生成文本',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `ref_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '样板音频',
  `emo_ref_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '情感样板音频',
  `transaction_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '交易id',
  `result_url` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '结果地址',
  `user_id` int DEFAULT NULL COMMENT '用户id',
  `emo_text` varchar(255) DEFAULT NULL COMMENT '情感描述文本',
  `emo_weight` double DEFAULT NULL COMMENT '情感权重',
  `emo_vec` varchar(255) DEFAULT NULL COMMENT '情感向量控制',
  `emo_control_method` tinyint DEFAULT NULL COMMENT '情感控制方式',
  `status` tinyint DEFAULT NULL COMMENT '状态: 0-未处理, 1-正在处理, -1-处理失败, 2-处理完成',
  `message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '错误信息',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""
