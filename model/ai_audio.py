"""
AI Audio Model - Database operations for ai_audio table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from config.constant import (
    AI_AUDIO_STATUS_PENDING,
    AI_AUDIO_STATUS_PROCESSING,
    AI_AUDIO_STATUS_FAILED,
    AI_AUDIO_STATUS_COMPLETED
)
import logging

logger = logging.getLogger(__name__)


class AIAudio:
    """AI Audio model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.text = kwargs.get('text')
        self.create_time = kwargs.get('create_time')
        self.update_time = kwargs.get('update_time')
        self.ref_path = kwargs.get('ref_path')
        self.emo_ref_path = kwargs.get('emo_ref_path')
        self.transaction_id = kwargs.get('transaction_id')
        self.result_url = kwargs.get('result_url')
        self.user_id = kwargs.get('user_id')
        self.emo_text = kwargs.get('emo_text')
        self.emo_weight = kwargs.get('emo_weight')
        self.emo_vec = kwargs.get('emo_vec')
        self.emo_control_method = kwargs.get('emo_control_method')
        self.status = kwargs.get('status')
        self.message = kwargs.get('message')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'text': self.text,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None,
            'ref_path': self.ref_path,
            'emo_ref_path': self.emo_ref_path,
            'transaction_id': self.transaction_id,
            'result_url': self.result_url,
            'user_id': self.user_id,
            'emo_text': self.emo_text,
            'emo_weight': self.emo_weight,
            'emo_vec': self.emo_vec,
            'emo_control_method': self.emo_control_method,
            'status': self.status,
            'message': self.message
        }


class AIAudioModel:
    """AI Audio database operations"""
    
    @staticmethod
    def create(
        text: str,
        user_id: int,
        ref_path: Optional[str] = None,
        emo_ref_path: Optional[str] = None,
        transaction_id: Optional[str] = None,
        result_url: Optional[str] = None,
        emo_text: Optional[str] = None,
        emo_weight: Optional[float] = None,
        emo_vec: Optional[str] = None,
        emo_control_method: Optional[int] = None,
        status: Optional[int] = AI_AUDIO_STATUS_PENDING,
        message: Optional[str] = None
    ) -> int:
        """
        Create a new AI audio record
        
        Args:
            text: Generation text
            user_id: User ID
            ref_path: Reference audio path (optional)
            emo_ref_path: Emotion reference audio path (optional)
            transaction_id: Transaction ID (optional)
            result_url: Result URL (optional)
            emo_text: Emotion description text (optional)
            emo_weight: Emotion weight (optional)
            emo_vec: Emotion vector control (optional)
            emo_control_method: Emotion control method (0-same as voice reference, 1-use emotion reference, 2-use emotion vector, 3-use emotion text, optional)
            status: Status (AI_AUDIO_STATUS_PENDING-未处理, AI_AUDIO_STATUS_PROCESSING-处理中, AI_AUDIO_STATUS_FAILED-处理失败, AI_AUDIO_STATUS_COMPLETED-处理完成, default: AI_AUDIO_STATUS_PENDING)
            message: Error message (optional)
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO ai_audio 
            (text, user_id, ref_path, emo_ref_path, transaction_id, result_url, 
             emo_text, emo_weight, emo_vec, emo_control_method, status, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (text, user_id, ref_path, emo_ref_path, transaction_id, result_url,
                  emo_text, emo_weight, emo_vec, emo_control_method, status, message)
        
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created AI audio record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create AI audio record: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[AIAudio]:
        """
        Get AI audio record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            AIAudio object or None
        """
        sql = "SELECT * FROM ai_audio WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return AIAudio(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get AI audio record by ID {record_id}: {e}")
            raise
    
    @staticmethod
    def get_by_user_id(
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        order_by: str = 'create_time',
        order_direction: str = 'DESC'
    ) -> Dict[str, Any]:
        """
        Get AI audio records list by user ID with pagination
        
        Args:
            user_id: User ID
            page: Page number (starting from 1)
            page_size: Number of records per page
            order_by: Order by field (create_time, update_time, id)
            order_direction: Order direction (ASC, DESC)
        
        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        valid_order_fields = ['id', 'create_time', 'update_time']
        valid_directions = ['ASC', 'DESC']
        
        if order_by not in valid_order_fields:
            order_by = 'create_time'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'
        
        count_sql = "SELECT COUNT(*) as total FROM ai_audio WHERE user_id = %s"
        count_result = execute_query(count_sql, (user_id,), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM ai_audio 
            WHERE user_id = %s
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        
        try:
            results = execute_query(data_sql, (user_id, page_size, offset), fetch_all=True)
            audios = [AIAudio(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': audios
            }
        except Exception as e:
            logger.error(f"Failed to list AI audio records for user {user_id}: {e}")
            raise
    
    @staticmethod
    def list_by_status(
        status: int,
        limit: int = 100
    ) -> List[AIAudio]:
        """
        Get AI audio records by status
        
        Args:
            status: Status value
            limit: Maximum number of records to return
        
        Returns:
            List of AIAudio objects
        """
        sql = """
            SELECT * FROM ai_audio 
            WHERE status = %s
            ORDER BY create_time ASC
            LIMIT %s
        """
        
        try:
            results = execute_query(sql, (status, limit), fetch_all=True)
            audios = [AIAudio(**row) for row in results] if results else []
            return audios
        except Exception as e:
            logger.error(f"Failed to list AI audio records by status {status}: {e}")
            raise
    
    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update AI audio record
        
        Args:
            record_id: Record ID
            **kwargs: Fields to update (text, ref_path, emo_ref_path, transaction_id, 
                     result_url, emo_text, emo_weight, emo_vec, emo_control_method, 
                     status, message)
        
        Returns:
            Number of affected rows
        """
        allowed_fields = [
            'text', 'ref_path', 'emo_ref_path', 'transaction_id', 'result_url',
            'emo_text', 'emo_weight', 'emo_vec', 'emo_control_method', 'status', 'message'
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
        sql = f"UPDATE ai_audio SET {', '.join(update_fields)} WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated AI audio record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update AI audio record {record_id}: {e}")
            raise
    
    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete AI audio record by ID
        
        Args:
            record_id: Record ID
        
        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM ai_audio WHERE id = %s"
        
        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted AI audio record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete AI audio record {record_id}: {e}")
            raise
