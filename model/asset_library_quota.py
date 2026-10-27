# -*- coding: utf-8 -*-
"""Asset Library Quota Model - 用户资产库容量配额表。

资产文件不受存储容量限制、不被清理任务删除；但每个用户加入资产库时按
file_size 累加 used_bytes，管理员通过 quota_bytes 逐人控制上限（0=不限）。
预留/释放使用条件 UPDATE 原子完成，无事务依赖。
"""
import logging
from typing import Any, Dict, Optional

import pymysql

from config.constant import AssetLibraryConstants
from .database import execute_query, execute_update, execute_insert

logger = logging.getLogger(__name__)


class AssetLibraryQuotaModel:
    """asset_library_quota 表数据库操作"""

    @staticmethod
    def ensure_for_user(user_id: int, default_quota: Optional[int] = None) -> None:
        """确保用户配额行存在（不存在则按默认配额插入；已存在不覆盖管理员设置）"""
        quota = default_quota if default_quota is not None else AssetLibraryConstants.DEFAULT_QUOTA_BYTES
        sql = """
            INSERT IGNORE INTO asset_library_quota (user_id, quota_bytes)
            VALUES (%s, %s)
        """
        try:
            execute_update(sql, (user_id, quota))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to ensure quota row for user {user_id}: {e}")
            raise

    @staticmethod
    def get_by_user(user_id: int) -> Optional[Dict[str, Any]]:
        """读取用户配额行（不存在时自动初始化默认配额）"""
        AssetLibraryQuotaModel.ensure_for_user(user_id)
        sql = "SELECT * FROM asset_library_quota WHERE user_id = %s"
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            if not row:
                return None
            return {
                'user_id': int(row['user_id']),
                'quota_bytes': int(row['quota_bytes'] or 0),
                'used_bytes': int(row['used_bytes'] or 0),
                'enabled': bool(row.get('enabled', 0)) if isinstance(row, dict) else False,
            }
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get quota for user {user_id}: {e}")
            raise

    @staticmethod
    def is_enabled(user_id: int) -> bool:
        """读取逐用户使用权限开关（allow_all_users 关闭时生效）。"""
        sql = "SELECT enabled FROM asset_library_quota WHERE user_id = %s"
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            return bool(row and row.get('enabled', 0))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to read asset permission for user {user_id}: {e}")
            raise

    @staticmethod
    def set_enabled(user_id: int, enabled: bool) -> None:
        """管理员设置逐用户使用权限开关（行不存在时先建）。"""
        AssetLibraryQuotaModel.ensure_for_user(user_id)
        sql = "UPDATE asset_library_quota SET enabled = %s WHERE user_id = %s"
        try:
            execute_update(sql, (1 if enabled else 0, user_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to set asset permission for user {user_id}: {e}")
            raise

    @staticmethod
    def try_reserve(user_id: int, size_bytes: int) -> bool:
        """原子预留容量：超额返回 False（quota_bytes=0 表示不限制）。"""
        sql = """
            UPDATE asset_library_quota
            SET used_bytes = used_bytes + %s
            WHERE user_id = %s
              AND (quota_bytes = 0 OR used_bytes + %s <= quota_bytes)
        """
        try:
            affected = execute_update(sql, (size_bytes, user_id, size_bytes))
            return affected > 0
        except pymysql.MySQLError as e:
            logger.error(f"Failed to reserve {size_bytes} bytes for user {user_id}: {e}")
            raise

    @staticmethod
    def release(user_id: int, size_bytes: int) -> None:
        """释放容量（文件清除后减少对应记录；GREATEST 防负数）"""
        sql = """
            UPDATE asset_library_quota
            SET used_bytes = GREATEST(used_bytes - %s, 0)
            WHERE user_id = %s
        """
        try:
            execute_update(sql, (size_bytes, user_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to release {size_bytes} bytes for user {user_id}: {e}")
            raise

    @staticmethod
    def set_quota(user_id: int, quota_bytes: int) -> int:
        """管理员设置用户配额上限（0=不限；ensure 先建行）"""
        AssetLibraryQuotaModel.ensure_for_user(user_id)
        sql = "UPDATE asset_library_quota SET quota_bytes = %s WHERE user_id = %s"
        try:
            return execute_update(sql, (quota_bytes, user_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to set quota {quota_bytes} for user {user_id}: {e}")
            raise

    @staticmethod
    def recount_used(user_id: int) -> int:
        """按 asset_library 实际 SUM 重算 used_bytes（对账/修复），返回新值。"""
        from .asset_library import AssetLibraryModel
        total = AssetLibraryModel.sum_size_by_user(user_id)
        sql = "UPDATE asset_library_quota SET used_bytes = %s WHERE user_id = %s"
        try:
            AssetLibraryQuotaModel.ensure_for_user(user_id)
            execute_update(sql, (total, user_id))
            return total
        except pymysql.MySQLError as e:
            logger.error(f"Failed to recount used bytes for user {user_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `asset_library_quota` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL COMMENT '用户 ID',
  `quota_bytes` bigint NOT NULL DEFAULT 2147483648 COMMENT '资产库容量上限（字节，0=不限制，默认 2GB）',
  `used_bytes` bigint NOT NULL DEFAULT 0 COMMENT '已用资产库容量（字节，随加入/清除增减）',
  `enabled` tinyint NOT NULL DEFAULT 0 COMMENT '是否允许使用资产库（allow_all_users 关闭时逐用户生效）',
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户资产库容量配额表';
"""
