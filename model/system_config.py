"""
System Config Model - Database operations for system_config table
系统配置表，支持动态配置热更新
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from config.constant import CONFIG_KEY_MAX_LENGTH
import logging
import json

logger = logging.getLogger(__name__)


class SystemConfig:
    """SystemConfig model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.env = kwargs.get('env', 'dev')
        self.config_key = kwargs.get('config_key')
        self.config_value = kwargs.get('config_value')
        self.value_type = kwargs.get('value_type', 'string')
        self.description = kwargs.get('description')
        self.editable = kwargs.get('editable', 1)
        self.is_sensitive = kwargs.get('is_sensitive', 0)
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.updated_by = kwargs.get('updated_by')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'env': self.env,
            'config_key': self.config_key,
            'config_value': self.get_typed_value(),
            'value_type': self.value_type,
            'description': self.description,
            'editable': self.editable,
            'is_sensitive': self.is_sensitive,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by': self.updated_by,
        }
    
    def get_typed_value(self) -> Any:
        """根据 value_type 返回类型化的值"""
        if self.config_value is None:
            return None
        
        try:
            if self.value_type == 'int':
                return int(self.config_value)
            elif self.value_type == 'float':
                return float(self.config_value)
            elif self.value_type == 'bool':
                return self.config_value.lower() in ('true', '1', 'yes')
            elif self.value_type == 'json':
                return json.loads(self.config_value)
            else:
                return self.config_value
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to convert config value {self.config_key}: {e}")
            return self.config_value
    
    def get_display_value(self) -> str:
        """获取用于显示的值（敏感配置脱敏）"""
        if not self.is_sensitive or not self.config_value:
            return self.config_value
        return SystemConfigModel.mask_sensitive_value(self.config_value)


class SystemConfigModel:
    """SystemConfig database operations"""
    
    @staticmethod
    def mask_sensitive_value(value: str) -> str:
        """
        敏感值脱敏
        规则：保留前4位 + **** + 后4位
        长度 <= 8 时显示 ********
        """
        if not value:
            return value
        if len(value) <= 8:
            return '********'
        return value[:4] + '****' + value[-4:]
    
    @staticmethod
    def create(
        env: str,
        config_key: str,
        config_value: str,
        value_type: str = 'string',
        description: str = None,
        editable: int = 1,
        is_sensitive: int = 0,
        updated_by: int = None
    ) -> int:
        """创建配置项"""
        # 校验 config_key 长度
        if len(config_key) > CONFIG_KEY_MAX_LENGTH:
            raise ValueError(
                f"config_key 长度超过限制: {len(config_key)} > {CONFIG_KEY_MAX_LENGTH}, "
                f"key: {config_key}"
            )
        
        sql = """
            INSERT INTO system_config 
            (env, config_key, config_value, value_type, description, editable, is_sensitive, updated_by) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            config_id = execute_insert(sql, (
                env, config_key, config_value, value_type,
                description, editable, is_sensitive, updated_by
            ))
            logger.info(f"Created system_config with ID: {config_id}, key: {config_key}")
            return config_id
        except Exception as e:
            logger.error(f"Failed to create system_config: {e}")
            raise
    
    @staticmethod
    def get_by_id(config_id: int) -> Optional[SystemConfig]:
        """根据 ID 获取配置"""
        sql = """
            SELECT id, env, config_key, config_value, value_type, description,
                   editable, is_sensitive, created_at, updated_at, updated_by
            FROM system_config WHERE id = %s
        """
        try:
            result = execute_query(sql, (config_id,), fetch_one=True)
            if result:
                return SystemConfig(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get system_config by id {config_id}: {e}")
            raise
    
    @staticmethod
    def get_by_key(env: str, config_key: str) -> Optional[SystemConfig]:
        """根据环境和配置键获取配置"""
        sql = """
            SELECT id, env, config_key, config_value, value_type, description,
                   editable, is_sensitive, created_at, updated_at, updated_by
            FROM system_config WHERE env = %s AND config_key = %s
        """
        try:
            result = execute_query(sql, (env, config_key), fetch_one=True)
            if result:
                return SystemConfig(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get system_config by key {env}:{config_key}: {e}")
            raise
    
    @staticmethod
    def get_all_by_env(env: str, editable_only: bool = False) -> List[SystemConfig]:
        """获取指定环境的所有配置"""
        sql = """
            SELECT id, env, config_key, config_value, value_type, description,
                   editable, is_sensitive, created_at, updated_at, updated_by
            FROM system_config WHERE env = %s
        """
        params = [env]
        
        if editable_only:
            sql += " AND editable = 1"
        
        sql += " ORDER BY config_key"
        
        try:
            results = execute_query(sql, tuple(params), fetch_all=True)
            return [SystemConfig(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get all system_config for env {env}: {e}")
            raise
    
    @staticmethod
    def update_value(
        config_id: int,
        config_value: str,
        updated_by: int = None
    ) -> int:
        """更新配置值"""
        sql = "UPDATE system_config SET config_value = %s, updated_by = %s WHERE id = %s"
        try:
            return execute_update(sql, (config_value, updated_by, config_id))
        except Exception as e:
            logger.error(f"Failed to update system_config {config_id}: {e}")
            raise
    
    @staticmethod
    def upsert(
        env: str,
        config_key: str,
        config_value: str,
        value_type: str = 'string',
        description: str = None,
        editable: int = 1,
        is_sensitive: int = 0,
        updated_by: int = None
    ) -> int:
        """插入或更新配置（如果存在则更新）"""
        existing = SystemConfigModel.get_by_key(env, config_key)
        if existing:
            SystemConfigModel.update_value(existing.id, config_value, updated_by)
            return existing.id
        else:
            return SystemConfigModel.create(
                env=env,
                config_key=config_key,
                config_value=config_value,
                value_type=value_type,
                description=description,
                editable=editable,
                is_sensitive=is_sensitive,
                updated_by=updated_by
            )
    
    @staticmethod
    def delete(config_id: int) -> int:
        """删除配置"""
        sql = "DELETE FROM system_config WHERE id = %s"
        try:
            return execute_update(sql, (config_id,))
        except Exception as e:
            logger.error(f"Failed to delete system_config {config_id}: {e}")
            raise
    
    @staticmethod
    def list_by_prefix(env: str, prefix: str) -> List[SystemConfig]:
        """根据前缀获取配置列表（如 task_queue.*）"""
        sql = """
            SELECT id, env, config_key, config_value, value_type, description,
                   editable, is_sensitive, created_at, updated_at, updated_by
            FROM system_config 
            WHERE env = %s AND config_key LIKE %s
            ORDER BY config_key
        """
        try:
            results = execute_query(sql, (env, f"{prefix}%"), fetch_all=True)
            return [SystemConfig(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list system_config by prefix {prefix}: {e}")
            raise
    
    @staticmethod
    def search(
        env: str,
        keyword: str = None,
        page: int = 1,
        page_size: int = 50
    ) -> Dict[str, Any]:
        """搜索配置（分页）"""
        base_sql = "FROM system_config WHERE env = %s"
        params = [env]
        
        if keyword:
            base_sql += " AND (config_key LIKE %s OR description LIKE %s)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        
        # 获取总数
        count_sql = f"SELECT COUNT(*) as total {base_sql}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        # 获取数据
        data_sql = f"""
            SELECT id, env, config_key, config_value, value_type, description,
                   editable, is_sensitive, created_at, updated_at, updated_by
            {base_sql}
            ORDER BY config_key
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, (page - 1) * page_size])
        results = execute_query(data_sql, tuple(params), fetch_all=True)
        
        configs = [SystemConfig(**row) for row in results] if results else []
        
        return {
            'data': [c.to_dict() for c in configs],
            'total': total,
            'page': page,
            'page_size': page_size
        }
