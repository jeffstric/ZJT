"""
System Config History Model - Database operations for system_config_history table
系统配置修改历史表
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from .system_config import SystemConfigModel
from config.constant import CONFIG_KEY_MAX_LENGTH
import logging

logger = logging.getLogger(__name__)


class SystemConfigHistory:
    """SystemConfigHistory model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.config_id = kwargs.get('config_id')
        self.env = kwargs.get('env')
        self.config_key = kwargs.get('config_key')
        self.old_value = kwargs.get('old_value')
        self.new_value = kwargs.get('new_value')
        self.value_type = kwargs.get('value_type')
        self.is_sensitive = kwargs.get('is_sensitive', 0)
        self.updated_by = kwargs.get('updated_by')
        self.updated_at = kwargs.get('updated_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'config_id': self.config_id,
            'env': self.env,
            'config_key': self.config_key,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'value_type': self.value_type,
            'is_sensitive': self.is_sensitive,
            'updated_by': self.updated_by,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SystemConfigHistoryModel:
    """SystemConfigHistory database operations"""
    
    @staticmethod
    def create(
        config_id: int,
        env: str,
        config_key: str,
        old_value: str,
        new_value: str,
        value_type: str = 'string',
        is_sensitive: int = 0,
        updated_by: int = None
    ) -> int:
        """
        创建配置修改历史记录
        敏感配置会自动脱敏后存储
        """
        # 校验 config_key 长度
        if len(config_key) > CONFIG_KEY_MAX_LENGTH:
            raise ValueError(
                f"config_key 长度超过限制: {len(config_key)} > {CONFIG_KEY_MAX_LENGTH}, "
                f"key: {config_key}"
            )
        
        # 敏感配置需要脱敏
        if is_sensitive:
            old_value = SystemConfigModel.mask_sensitive_value(old_value)
            new_value = SystemConfigModel.mask_sensitive_value(new_value)
        
        sql = """
            INSERT INTO system_config_history 
            (config_id, env, config_key, old_value, new_value, value_type, is_sensitive, updated_by) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            history_id = execute_insert(sql, (
                config_id, env, config_key, old_value, new_value,
                value_type, is_sensitive, updated_by
            ))
            logger.info(f"Created system_config_history with ID: {history_id}, key: {config_key}")
            return history_id
        except Exception as e:
            logger.error(f"Failed to create system_config_history: {e}")
            raise
    
    @staticmethod
    def get_by_config_id(config_id: int, limit: int = 10) -> List[SystemConfigHistory]:
        """获取指定配置的修改历史"""
        sql = """
            SELECT id, config_id, env, config_key, old_value, new_value,
                   value_type, is_sensitive, updated_by, updated_at
            FROM system_config_history 
            WHERE config_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (config_id, limit), fetch_all=True)
            return [SystemConfigHistory(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get history for config_id {config_id}: {e}")
            raise
    
    @staticmethod
    def get_by_key(env: str, config_key: str, limit: int = 10) -> List[SystemConfigHistory]:
        """根据环境和配置键获取修改历史"""
        sql = """
            SELECT id, config_id, env, config_key, old_value, new_value,
                   value_type, is_sensitive, updated_by, updated_at
            FROM system_config_history 
            WHERE env = %s AND config_key = %s
            ORDER BY updated_at DESC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (env, config_key, limit), fetch_all=True)
            return [SystemConfigHistory(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get history for key {env}:{config_key}: {e}")
            raise
    
    @staticmethod
    def get_recent(env: str, limit: int = 50) -> List[SystemConfigHistory]:
        """获取指定环境的最近修改历史"""
        sql = """
            SELECT id, config_id, env, config_key, old_value, new_value,
                   value_type, is_sensitive, updated_by, updated_at
            FROM system_config_history 
            WHERE env = %s
            ORDER BY updated_at DESC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (env, limit), fetch_all=True)
            return [SystemConfigHistory(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get recent history for env {env}: {e}")
            raise
    
    @staticmethod
    def search(
        env: str,
        config_key: str = None,
        updated_by: int = None,
        page: int = 1,
        page_size: int = 50
    ) -> Dict[str, Any]:
        """搜索修改历史（分页）"""
        base_sql = "FROM system_config_history WHERE env = %s"
        params = [env]
        
        if config_key:
            base_sql += " AND config_key LIKE %s"
            params.append(f"%{config_key}%")
        
        if updated_by:
            base_sql += " AND updated_by = %s"
            params.append(updated_by)
        
        # 获取总数
        count_sql = f"SELECT COUNT(*) as total {base_sql}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        # 获取数据
        data_sql = f"""
            SELECT id, config_id, env, config_key, old_value, new_value,
                   value_type, is_sensitive, updated_by, updated_at
            {base_sql}
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, (page - 1) * page_size])
        results = execute_query(data_sql, tuple(params), fetch_all=True)
        
        histories = [SystemConfigHistory(**row) for row in results] if results else []
        
        return {
            'data': [h.to_dict() for h in histories],
            'total': total,
            'page': page,
            'page_size': page_size
        }
    
    @staticmethod
    def delete_by_config_id(config_id: int) -> int:
        """删除指定配置的所有历史记录"""
        sql = "DELETE FROM system_config_history WHERE config_id = %s"
        try:
            return execute_update(sql, (config_id,))
        except Exception as e:
            logger.error(f"Failed to delete history for config_id {config_id}: {e}")
            raise
