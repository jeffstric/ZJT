"""
Implementation Power Config Model - 实现方算力配置表模型

对应数据库表: implementation_power_config
"""
import logging
from typing import Dict, Any, List, Optional
from model.database import execute_query, execute_insert, execute_update
from sqlalchemy.sql import text
import json

logger = logging.getLogger(__name__)


class ImplementationPowerConfig:
    """实现方算力配置数据模型"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.implementation_name = kwargs.get('implementation_name')
        self.driver_key = kwargs.get('driver_key')
        self.site_number = kwargs.get('site_number')
        self.power_config = kwargs.get('power_config')
        self.sort_order = kwargs.get('sort_order')
        self.enabled = kwargs.get('enabled')
        self.display_name = kwargs.get('display_name')
        self.updated_by = kwargs.get('updated_by')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'implementation_name': self.implementation_name,
            'driver_key': self.driver_key,
            'site_number': self.site_number,
            'power_config': self.power_config,
            'sort_order': self.sort_order,
            'enabled': self.enabled,
            'display_name': self.display_name,
            'updated_by': self.updated_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# 表结构定义 SQL
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `implementation_power_config` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增ID',
  `implementation_name` varchar(100) NOT NULL COMMENT '实现方名称',
  `driver_key` varchar(100) NOT NULL COMMENT 'DriverKey，用于分组排序',
  `site_number` int DEFAULT NULL COMMENT '聚合站点编号(0-5)，非聚合站点为NULL',
  `power_config` json DEFAULT NULL COMMENT '算力配置JSON，格式: {"5": 38, "10": 70} 或 {"fixed": 100}',
  `sort_order` float NOT NULL DEFAULT '999999' COMMENT '排序顺序',
  `enabled` tinyint(1) DEFAULT '1' COMMENT '是否启用(1=启用,0=禁用)',
  `display_name` varchar(200) DEFAULT NULL COMMENT '显示名称',
  `updated_by` int DEFAULT NULL COMMENT '更新人ID',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_impl_driver` (`implementation_name`,`driver_key`),
  KEY `idx_driver_key_sort_order` (`driver_key`,`sort_order`),
  KEY `idx_implementation_name` (`implementation_name`),
  KEY `idx_impl_name` (`implementation_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='实现方配置表';
"""


class ImplementationPowerConfigModel:
    """实现方算力配置数据库操作"""

    TABLE_NAME = 'implementation_power_config'

    @staticmethod
    def _parse_power_config(power_config: Any) -> Dict[str, Any]:
        """解析 power_config JSON 字段"""
        if not power_config:
            return {}
        if isinstance(power_config, str):
            try:
                return json.loads(power_config)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse power_config: {power_config}")
                return {}
        if isinstance(power_config, dict):
            return power_config
        return {}

    @staticmethod
    def get_by_id(config_id: int) -> Optional[ImplementationPowerConfig]:
        """根据 ID 获取配置"""
        sql = f"""
            SELECT * FROM {ImplementationPowerConfigModel.TABLE_NAME}
            WHERE id = %s
        """
        try:
            result = execute_query(sql, (config_id,), fetch_one=True)
            if result:
                return ImplementationPowerConfig(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get config by id {config_id}: {e}")
            return None

    @staticmethod
    def get_by_implementation_and_driver(
        implementation_name: str,
        driver_key: str
    ) -> Optional[ImplementationPowerConfig]:
        """根据实现方名称和 driver_key 获取配置"""
        sql = f"""
            SELECT * FROM {ImplementationPowerConfigModel.TABLE_NAME}
            WHERE implementation_name = %s AND driver_key = %s
        """
        try:
            result = execute_query(sql, (implementation_name, driver_key), fetch_one=True)
            if result:
                return ImplementationPowerConfig(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get config for {implementation_name}/{driver_key}: {e}")
            return None

    @staticmethod
    def get_all() -> List[ImplementationPowerConfig]:
        """获取所有配置"""
        sql = f"""
            SELECT * FROM {ImplementationPowerConfigModel.TABLE_NAME}
            ORDER BY driver_key, sort_order, implementation_name
        """
        try:
            results = execute_query(sql, fetch_all=True)
            return [ImplementationPowerConfig(**r) for r in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get all configs: {e}")
            return []

    @staticmethod
    def create(
        implementation_name: str,
        driver_key: str,
        site_number: Optional[int] = None,
        power_config: Optional[Dict[str, Any]] = None,
        sort_order: float = 999999.0,
        enabled: bool = True,
        display_name: Optional[str] = None,
        updated_by: Optional[int] = None
    ) -> int:
        """创建配置记录"""
        sql = f"""
            INSERT INTO {ImplementationPowerConfigModel.TABLE_NAME}
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, display_name, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            power_config_json = json.dumps(power_config) if power_config else None
            config_id = execute_insert(
                sql,
                (implementation_name, driver_key, site_number, power_config_json, sort_order, enabled, display_name, updated_by)
            )
            logger.info(f"Created implementation_power_config: {implementation_name}/{driver_key}")
            return config_id
        except Exception as e:
            logger.error(f"Failed to create config for {implementation_name}/{driver_key}: {e}")
            raise

    @staticmethod
    def update(
        config_id: int,
        power_config: Optional[Dict[str, Any]] = None,
        sort_order: Optional[float] = None,
        enabled: Optional[bool] = None,
        display_name: Optional[str] = None,
        updated_by: Optional[int] = None
    ) -> bool:
        """更新配置记录"""
        fields = []
        values = []

        if power_config is not None:
            fields.append("power_config = %s")
            values.append(json.dumps(power_config))
        if sort_order is not None:
            fields.append("sort_order = %s")
            values.append(sort_order)
        if enabled is not None:
            fields.append("enabled = %s")
            values.append(enabled)
        if display_name is not None:
            fields.append("display_name = %s")
            values.append(display_name)
        if updated_by is not None:
            fields.append("updated_by = %s")
            values.append(updated_by)

        if not fields:
            return False

        sql = f"""
            UPDATE {ImplementationPowerConfigModel.TABLE_NAME}
            SET {', '.join(fields)}
            WHERE id = %s
        """
        values.append(config_id)

        try:
            affected = execute_update(sql, tuple(values))
            return affected > 0
        except Exception as e:
            logger.error(f"Failed to update config {config_id}: {e}")
            return False

    @staticmethod
    def delete(config_id: int) -> bool:
        """删除配置记录"""
        sql = f"""
            DELETE FROM {ImplementationPowerConfigModel.TABLE_NAME}
            WHERE id = %s
        """
        try:
            affected = execute_update(sql, (config_id,))
            return affected > 0
        except Exception as e:
            logger.error(f"Failed to delete config {config_id}: {e}")
            return False
