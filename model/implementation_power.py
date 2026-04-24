"""
Implementation Power Config Model - 实现方算力配置（支持管理员热更新）
"""
import logging
from typing import Dict, Any, List, Optional, Union
from model.database import execute_query, execute_insert, execute_update
from sqlalchemy.sql import text
from config.unified_config import ALL_IMPLEMENTATIONS
from config.config_util import get_config_value
import json

logger = logging.getLogger(__name__)


class ImplementationPower:
    """实现方算力配置 Model 类"""

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
        """Convert to dictionary"""
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


class ImplementationPowerModel:
    """实现方算力配置数据库操作（支持管理员热更新，无需重启服务）

    注意：从 2026-03-23 起，使用 (implementation_name, driver_key) 复合唯一键来定位记录。
    同一个 implementation_name 可能对应多个 driver_key（即同一个实现方可用于多种任务）。
    """

    @staticmethod
    def _parse_power_config(power_config: Any) -> Dict[str, Any]:
        """
        解析 power_config JSON 字段

        Args:
            power_config: 数据库中的 power_config 值（可能是字符串或字典）

        Returns:
            解析后的字典，格式如 {"5": 38, "10": 70, "modifiers": {...}} 或 {"fixed": 100}
        """
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
    def get_power(
        implementation_name: str,
        driver_key: str,
        duration: Optional[int] = None
    ) -> Optional[int]:
        """
        获取实现方算力（从数据库读取，支持热更新）

        Args:
            implementation_name: 实现方名称（如 gemini_duomi_v1）
            driver_key: DriverKey（如 GEMINI_IMAGE_EDIT）
            duration: 时长（秒），None 表示固定算力

        Returns:
            算力值，如果数据库无配置则返回 None（由调用方使用代码默认值）
        """
        sql = """
            SELECT power_config FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            LIMIT 1
        """
        try:
            result = execute_query(sql, (implementation_name, driver_key), fetch_one=True)
            if result:
                power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))
                if duration is None:
                    # 获取固定算力
                    return power_config.get('fixed')
                else:
                    # 获取指定时长的算力
                    return power_config.get(str(duration))
            return None
        except Exception as e:
            logger.error(f"Failed to get implementation power for {implementation_name}/{driver_key}: {e}")
            return None

    @staticmethod
    def get_all_powers_for_implementation(
        implementation_name: str,
        driver_key: str
    ) -> Dict[Optional[int], int]:
        """
        获取某实现方的所有算力配置（按时长分组）

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey

        Returns:
            Dict[duration, computing_power]，duration 为 None 表示固定算力
        """
        sql = """
            SELECT power_config FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            LIMIT 1
        """
        params = (implementation_name, driver_key)

        try:
            result = execute_query(sql, params, fetch_one=True)
            if result:
                power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))

                result_dict = {}

                # 检查是否有固定算力
                if 'fixed' in power_config:
                    result_dict[None] = power_config['fixed']

                # 添加按时长的算力
                for key, value in power_config.items():
                    if key != 'fixed':
                        try:
                            result_dict[int(key)] = value
                        except ValueError:
                            logger.warning(f"Invalid duration key: {key}")
                            continue

                return result_dict
            return {}
        except Exception as e:
            logger.error(f"Failed to get all powers for {implementation_name}/{driver_key}: {e}")
            return {}

    @staticmethod
    def get_modifiers(
        implementation_name: str,
        driver_key: str
    ) -> Dict[str, Dict[str, float]]:
        """
        获取某实现方的算力修饰符配置

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey

        Returns:
            算力修饰符配置，格式如 {"image_mode": {"first_last_with_tail": 1.5, ...}, ...}
        """
        sql = """
            SELECT power_config FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            LIMIT 1
        """
        params = (implementation_name, driver_key)

        try:
            result = execute_query(sql, params, fetch_one=True)
            if result:
                power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))
                # 从 power_config 中提取 modifiers 字段
                if 'modifiers' in power_config and isinstance(power_config['modifiers'], dict):
                    return power_config['modifiers']
            return {}
        except Exception as e:
            logger.error(f"Failed to get modifiers for {implementation_name}/{driver_key}: {e}")
            return {}

    @staticmethod
    def set_power(
        implementation_name: str,
        computing_power: int,
        driver_key: str,
        duration: Optional[int] = None,
        updated_by: Optional[int] = None
    ) -> int:
        """
        设置实现方算力（管理员操作，立即生效）

        Args:
            implementation_name: 实现方名称
            computing_power: 算力值
            driver_key: DriverKey（必填）
            duration: 时长（秒），None 表示固定算力
            updated_by: 操作人 ID

        Returns:
            影响的行数
        """
        if not driver_key:
            raise ValueError("driver_key is required")

        # 先获取现有配置（使用复合键）
        sql = """
            SELECT power_config FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            LIMIT 1
        """
        try:
            result = execute_query(sql, (implementation_name, driver_key), fetch_one=True)

            # 解析现有配置
            power_config = {}
            if result:
                power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))

            # 更新指定时长的算力
            if duration is None:
                power_config['fixed'] = computing_power
            else:
                power_config[str(duration)] = computing_power

            # 将配置转为 JSON 字符串
            power_config_json = json.dumps(power_config)

            # 如果没有记录，需要先插入
            if not result:
                insert_sql = """
                    INSERT INTO implementation_power_config
                    (implementation_name, driver_key, power_config, updated_by)
                    VALUES (%s, %s, %s, %s)
                """
                execute_insert(insert_sql, (implementation_name, driver_key, power_config_json, updated_by))
                logger.info(f"Inserted new implementation power config: {implementation_name}/{driver_key}, duration={duration}, power={computing_power}")
                return 1

            # 更新数据库（使用复合键）
            update_sql = """
                UPDATE implementation_power_config
                SET power_config = %s, updated_by = %s, updated_at = NOW()
                WHERE implementation_name = %s AND driver_key = %s
            """
            affected = execute_update(update_sql, (power_config_json, updated_by, implementation_name, driver_key))

            if affected > 0:
                logger.info(f"Updated implementation power: {implementation_name}/{driver_key}, duration={duration}, power={computing_power}")

            return affected
        except Exception as e:
            logger.error(f"Failed to set implementation power for {implementation_name}/{driver_key}: {e}")
            raise

    @staticmethod
    def delete_power(
        implementation_name: str,
        driver_key: str,
        duration: Optional[int] = None
    ) -> int:
        """
        删除实现方算力配置（回退到代码默认值）

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey
            duration: 时长（秒），None 表示固定算力

        Returns:
            受影响的行数
        """
        # 先获取现有配置（使用复合键）
        sql = """
            SELECT power_config FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            LIMIT 1
        """
        try:
            result = execute_query(sql, (implementation_name, driver_key), fetch_one=True)

            if not result:
                return 0

            # 解析现有配置
            power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))

            # 删除指定时长的算力
            if duration is None:
                power_config.pop('fixed', None)
            else:
                power_config.pop(str(duration), None)

            # 如果配置为空，删除整条记录；否则更新
            if not power_config:
                delete_sql = """
                    DELETE FROM implementation_power_config
                    WHERE implementation_name = %s AND driver_key = %s
                """
                affected = execute_update(delete_sql, (implementation_name, driver_key))
            else:
                power_config_json = json.dumps(power_config)
                update_sql = """
                    UPDATE implementation_power_config
                    SET power_config = %s, updated_at = NOW()
                    WHERE implementation_name = %s AND driver_key = %s
                """
                affected = execute_update(update_sql, (power_config_json, implementation_name, driver_key))

            logger.info(f"Deleted implementation power: {implementation_name}/{driver_key}, duration={duration}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete implementation power for {implementation_name}/{driver_key}: {e}")
            raise

    @staticmethod
    def get_all_powers() -> List[Dict[str, Any]]:
        """
        获取所有实现方的算力配置（管理员用）

        Returns:
            所有实现方算力配置列表
        """
        sql = """
            SELECT id, implementation_name, driver_key, site_number, power_config,
                   enabled, sort_order, display_name, updated_by, created_at, updated_at
            FROM implementation_power_config
            ORDER BY driver_key, sort_order, implementation_name
        """
        try:
            results = execute_query(sql, fetch_all=True)
            return [ImplementationPower(**r).to_dict() for r in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get all implementation powers: {e}")
            return []

    @staticmethod
    def get_power_with_source(
        implementation_name: str,
        driver_key: str,
        duration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        获取实现方算力（包含来源信息）

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey
            duration: 时长

        Returns:
            {
                'computing_power': int,
                'source': 'database' | 'code_default',
                'duration': int | None
            }
        """
        db_power = ImplementationPowerModel.get_power(implementation_name, driver_key, duration)
        if db_power is not None:
            return {
                'computing_power': db_power,
                'source': 'database',
                'duration': duration
            }
        return {
            'computing_power': None,  # 需要调用方从代码默认值获取
            'source': 'code_default',
            'duration': duration
        }

    # ==================== 实现方配置（启用/禁用）相关方法 ====================

    @staticmethod
    def get_display_name(implementation_name: str, site_number: Optional[int] = None) -> str:
        """
        智能生成实现方显示名称

        优先级：
        1. 如果是聚合站点且有 site_number，从系统配置读取 api_aggregator.site_{site_number}.name
        2. 否则从 ALL_IMPLEMENTATIONS 配置中读取 display_name
        3. 最后使用实现方名称作为后备

        Args:
            implementation_name: 实现方名称
            site_number: 站点编号（仅聚合站点有值）

        Returns:
            显示名称
        """
        # 1. 聚合站点：从系统配置读取名称
        if site_number is not None:
            try:
                site_name = get_config_value('api_aggregator', f'site_{site_number}', 'name')
                logger.info(f"Site {site_number} config name: {site_name} for {implementation_name}")
                if site_name:
                    logger.debug(f"Using site config name for {implementation_name}: {site_name}")
                    return site_name
                else:
                    logger.warning(f"Site {site_number} name config is empty for {implementation_name}")
            except Exception as e:
                logger.error(f"Failed to get site config for {implementation_name}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        # 2. 从 ALL_IMPLEMENTATIONS 配置读取
        if implementation_name in ALL_IMPLEMENTATIONS:
            impl_config = ALL_IMPLEMENTATIONS[implementation_name]
            display_name = impl_config.get('display_name')
            if display_name:
                logger.debug(f"Using ALL_IMPLEMENTATIONS display_name for {implementation_name}: {display_name}")
                return display_name

        # 3. 后备方案：使用实现方名称
        logger.debug(f"Using fallback name for {implementation_name}")
        return implementation_name

    @staticmethod
    def get_config(
        implementation_name: str,
        driver_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取实现方配置（启用状态、显示名称、算力配置等）

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey

        Returns:
            配置字典，包含 enabled, display_name, sort_order, driver_key, power_config 等，如果无配置返回 None
        """
        sql = """
            SELECT enabled, sort_order, site_number, driver_key, power_config, display_name, updated_by, updated_at
            FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            LIMIT 1
        """
        params = (implementation_name, driver_key)

        try:
            result = execute_query(sql, params, fetch_one=True)
            if result:
                # 如果数据库没有 display_name，智能生成
                display_name = result.get('display_name')
                if not display_name:
                    site_number = result.get('site_number')
                    display_name = ImplementationPowerModel.get_display_name(implementation_name, site_number)

                # 解析 power_config
                power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))

                return {
                    'enabled': result.get('enabled'),
                    'display_name': display_name,
                    'sort_order': result.get('sort_order', 0),
                    'site_number': result.get('site_number'),
                    'driver_key': result.get('driver_key'),
                    'power_config': power_config,
                    'updated_by': result.get('updated_by'),
                    'updated_at': result.get('updated_at')
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get implementation config for {implementation_name}/{driver_key}: {e}")
            return None

    @staticmethod
    def is_enabled(
        implementation_name: str,
        driver_key: str
    ) -> bool:
        """
        检查实现方是否启用

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey

        Returns:
            True 如果启用，False 如果禁用或无配置（无配置默认启用）
        """
        sql = """
            SELECT enabled FROM implementation_power_config
            WHERE implementation_name = %s AND driver_key = %s
            AND enabled IS NOT NULL
            LIMIT 1
        """
        params = (implementation_name, driver_key)

        try:
            result = execute_query(sql, params, fetch_one=True)
            if result is not None:
                return bool(result.get('enabled', True))
            # 无配置默认启用
            return True
        except Exception as e:
            logger.error(f"Failed to check enabled status for {implementation_name}/{driver_key}: {e}")
            # 出错时默认启用
            return True

    @staticmethod
    def set_config(
        implementation_name: str,
        driver_key: str,
        enabled: Optional[bool] = None,
        sort_order: Optional[Union[int, float]] = None,
        display_name: Optional[str] = None,
        updated_by: Optional[int] = None
    ) -> bool:
        """
        设置实现方配置（启用状态、排序顺序、显示名称等）

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey（必填，用于复合唯一键）
            enabled: 是否启用
            sort_order: 排序顺序
            display_name: 显示名称
            updated_by: 操作人 ID

        Returns:
            是否成功
        """
        if not driver_key:
            raise ValueError("driver_key is required")

        # 获取修改前的值（用于审计日志）
        old_config = ImplementationPowerModel.get_config(implementation_name, driver_key)
        old_enabled = old_config.get('enabled') if old_config else None

        # 构建更新语句
        update_parts = []
        params = []

        if enabled is not None:
            update_parts.append("enabled = %s")
            params.append(enabled)
        if sort_order is not None:
            update_parts.append("sort_order = %s")
            params.append(sort_order)
        if display_name is not None:
            update_parts.append("display_name = %s")
            params.append(display_name)

        if not update_parts:
            return False

        update_parts.append("updated_by = %s")
        update_parts.append("updated_at = NOW()")
        params.extend([updated_by, implementation_name, driver_key])

        sql = f"""
            UPDATE implementation_power_config
            SET {', '.join(update_parts)}
            WHERE implementation_name = %s AND driver_key = %s
        """

        try:
            affected = execute_update(sql, tuple(params))

            # 如果没有更新任何记录，说明记录不存在，需要插入
            if affected == 0:
                insert_sql = """
                    INSERT INTO implementation_power_config
                    (implementation_name, driver_key, enabled, sort_order, display_name, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """
                insert_params = [
                    implementation_name,
                    driver_key,
                    enabled if enabled is not None else 1,
                    sort_order if sort_order is not None else 999999.0,
                    display_name,
                    updated_by
                ]
                execute_insert(insert_sql, tuple(insert_params))
                affected = 1

            # 记录审计日志
            if enabled is not None and enabled != old_enabled:
                action = "启用" if enabled else "禁用"
                logger.info(
                    f"[AUDIT] Implementation config changed: "
                    f"implementation={implementation_name}, driver_key={driver_key}, "
                    f"action={action}, "
                    f"old_enabled={old_enabled}, "
                    f"new_enabled={enabled}, "
                    f"operator_id={updated_by}"
                )

            return affected > 0
        except Exception as e:
            logger.error(f"Failed to set implementation config for {implementation_name}/{driver_key}: {e}")
            raise

    @staticmethod
    def get_all_configs() -> List[Dict[str, Any]]:
        """
        获取所有实现方的配置（包含启用状态、算力配置等）

        Returns:
            所有实现方配置列表
        """
        sql = """
            SELECT implementation_name, enabled, sort_order, site_number, driver_key,
                   power_config, display_name, updated_by, updated_at
            FROM implementation_power_config
            ORDER BY driver_key, sort_order, implementation_name
        """
        try:
            results = execute_query(sql, fetch_all=True)
            configs = []

            for result in results:
                impl_name = result['implementation_name']

                # 如果数据库没有 display_name，智能生成
                display_name = result.get('display_name')
                if not display_name:
                    site_number = result.get('site_number')
                    display_name = ImplementationPowerModel.get_display_name(impl_name, site_number)

                # 解析 power_config
                power_config = ImplementationPowerModel._parse_power_config(result.get('power_config'))

                config = {
                    'implementation_name': impl_name,
                    'display_name': display_name,
                    'enabled': result.get('enabled'),
                    'sort_order': result.get('sort_order', 0),
                    'site_number': result.get('site_number'),
                    'driver_key': result.get('driver_key'),
                    'power_config': power_config,
                    'updated_by': result.get('updated_by'),
                    'updated_at': result.get('updated_at')
                }
                configs.append(config)

            return configs
        except Exception as e:
            logger.error(f"Failed to get all implementation configs: {e}")
            return []

    @staticmethod
    def ensure_config_exists(
        implementation_name: str,
        driver_key: str,
        display_name: str,
        default_enabled: bool = True
    ) -> None:
        """
        确保实现方配置存在（如果不存在则创建）

        Args:
            implementation_name: 实现方名称
            driver_key: DriverKey（必填）
            display_name: 显示名称
            default_enabled: 默认是否启用
        """
        if not driver_key:
            raise ValueError("driver_key is required")

        existing = ImplementationPowerModel.get_config(implementation_name, driver_key)
        if existing:
            return

        # 创建配置记录
        sql = """
            INSERT INTO implementation_power_config (implementation_name, driver_key, enabled, sort_order, display_name)
            VALUES (%s, %s, %s, 0, %s)
        """
        try:
            execute_insert(sql, (implementation_name, driver_key, default_enabled, display_name))
            logger.info(f"Created implementation config: {implementation_name}/{driver_key}")
        except Exception as e:
            logger.warning(f"Failed to ensure config for {implementation_name}/{driver_key}: {e}")


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `implementation_power_config` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增ID',
  `implementation_name` varchar(100) NOT NULL COMMENT '实现方名称',
  `driver_key` varchar(100) NOT NULL COMMENT 'DriverKey，用于分组排序',
  `site_number` int DEFAULT NULL COMMENT '聚合站点编号(1-5)，非聚合站点为NULL',
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
