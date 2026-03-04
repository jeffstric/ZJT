"""
Model Model - Database operations for model table
对应Go的models/model.go
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class Model:
    """Model model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.model_name = kwargs.get('model_name')
        self.created_at = kwargs.get('created_at')
        self.note = kwargs.get('note')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'model_name': self.model_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'note': self.note,
        }


class ModelModel:
    """Model database operations"""
    
    @staticmethod
    def create(model_name: Optional[str] = None, note: Optional[str] = None) -> int:
        """创建模型"""
        sql = "INSERT INTO model (model_name, note) VALUES (%s, %s)"
        try:
            model_id = execute_insert(sql, (model_name, note))
            logger.info(f"Created model with ID: {model_id}")
            return model_id
        except Exception as e:
            logger.error(f"Failed to create model: {e}")
            raise
    
    @staticmethod
    def get_by_id(model_id: int) -> Optional[Model]:
        """根据ID获取模型"""
        sql = "SELECT id, model_name, created_at, note FROM model WHERE id = %s"
        try:
            result = execute_query(sql, (model_id,), fetch_one=True)
            if result:
                return Model(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get model by id {model_id}: {e}")
            raise
    
    @staticmethod
    def get_all(limit: int = 50, offset: int = 0) -> List[Model]:
        """
        获取所有模型（分页）
        对应Go的GetAllModels
        """
        sql = "SELECT id, model_name, created_at, note FROM model ORDER BY created_at DESC"
        params = []
        
        if limit > 0:
            sql += " LIMIT %s"
            params.append(limit)
            if offset > 0:
                sql += " OFFSET %s"
                params.append(offset)
        
        try:
            results = execute_query(sql, tuple(params) if params else None, fetch_all=True)
            return [Model(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get all models: {e}")
            raise
    
    @staticmethod
    def update(model_id: int, model_name: Optional[str] = None, note: Optional[str] = None) -> int:
        """更新模型"""
        sql = "UPDATE model SET model_name = %s, note = %s WHERE id = %s"
        try:
            return execute_update(sql, (model_name, note, model_id))
        except Exception as e:
            logger.error(f"Failed to update model {model_id}: {e}")
            raise
    
    @staticmethod
    def delete(model_id: int) -> int:
        """删除模型"""
        sql = "DELETE FROM model WHERE id = %s"
        try:
            return execute_update(sql, (model_id,))
        except Exception as e:
            logger.error(f"Failed to delete model {model_id}: {e}")
            raise
