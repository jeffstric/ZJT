"""
VendorModel Model - 供应商模型配置表
对应Go的models/vendor_model.go
"""
from typing import Optional, List
from datetime import datetime
from model.database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class VendorModel:
    """供应商模型配置实体"""
    
    def __init__(
        self,
        id: int = 0,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
        input_token_threshold: Optional[int] = None,
        output_token_threshold: Optional[int] = None,
        cache_read_threshold: Optional[int] = None
    ):
        self.id = id
        self.vendor_id = vendor_id
        self.model_id = model_id
        self.created_at = created_at
        self.input_token_threshold = input_token_threshold
        self.output_token_threshold = output_token_threshold
        self.cache_read_threshold = cache_read_threshold


class VendorModelModel:
    """供应商模型配置数据库操作"""
    
    @staticmethod
    def create(
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        input_threshold: Optional[int] = None,
        output_threshold: Optional[int] = None,
        cache_read_threshold: Optional[int] = None
    ) -> int:
        """创建供应商模型配置"""
        sql = """INSERT INTO vendor_model 
               (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold) 
               VALUES (%s, %s, %s, %s, %s)"""
        try:
            return execute_insert(sql, (vendor_id, model_id, input_threshold, output_threshold, cache_read_threshold))
        except Exception as e:
            logger.error(f"Failed to create vendor model: {e}")
            raise
    
    @staticmethod
    def get_by_vendor_model(vendor_id: int, model_id: int) -> Optional[VendorModel]:
        """根据vendor_id和model_id获取配置"""
        sql = """SELECT id, vendor_id, model_id, created_at, 
               input_token_threshold, out_token_threshold as output_token_threshold, cache_read_threshold 
               FROM vendor_model WHERE vendor_id = %s AND model_id = %s"""
        try:
            row = execute_query(sql, (vendor_id, model_id), fetch_one=True)
            if not row:
                return None
            return VendorModel(
                id=row['id'],
                vendor_id=row['vendor_id'],
                model_id=row['model_id'],
                created_at=row['created_at'],
                input_token_threshold=row['input_token_threshold'],
                output_token_threshold=row['output_token_threshold'],
                cache_read_threshold=row['cache_read_threshold']
            )
        except Exception as e:
            logger.error(f"Failed to get vendor model (vendor:{vendor_id}, model:{model_id}): {e}")
            raise
    
    @staticmethod
    def get_all(limit: int = 0, offset: int = 0) -> List[VendorModel]:
        """获取所有供应商模型配置"""
        sql = """SELECT id, vendor_id, model_id, created_at, 
               input_token_threshold, out_token_threshold as output_token_threshold, cache_read_threshold 
               FROM vendor_model ORDER BY created_at DESC"""
        params = []
        if limit > 0:
            sql += " LIMIT %s"
            params.append(limit)
            if offset > 0:
                sql += " OFFSET %s"
                params.append(offset)
        
        try:
            rows = execute_query(sql, tuple(params) if params else None, fetch_all=True)
            return [
                VendorModel(
                    id=row['id'],
                    vendor_id=row['vendor_id'],
                    model_id=row['model_id'],
                    created_at=row['created_at'],
                    input_token_threshold=row['input_token_threshold'],
                    output_token_threshold=row['output_token_threshold'],
                    cache_read_threshold=row['cache_read_threshold']
                )
                for row in rows
            ] if rows else []
        except Exception as e:
            logger.error(f"Failed to get all vendor models: {e}")
            raise
    
    @staticmethod
    def update_thresholds(
        id: int,
        input_threshold: Optional[int] = None,
        output_threshold: Optional[int] = None,
        cache_read_threshold: Optional[int] = None
    ) -> bool:
        """更新阈值配置"""
        sql = """UPDATE vendor_model 
               SET input_token_threshold = %s, out_token_threshold = %s, cache_read_threshold = %s 
               WHERE id = %s"""
        try:
            rows = execute_update(sql, (input_threshold, output_threshold, cache_read_threshold, id))
            return rows > 0
        except Exception as e:
            logger.error(f"Failed to update vendor model thresholds: {e}")
            raise
    
    @staticmethod
    def delete(id: int) -> bool:
        """删除供应商模型配置"""
        sql = "DELETE FROM vendor_model WHERE id = %s"
        try:
            rows = execute_update(sql, (id,))
            return rows > 0
        except Exception as e:
            logger.error(f"Failed to delete vendor model: {e}")
            raise
