# -*- coding: utf-8 -*-
"""Asset Permission Member Model - 资产库指定成员权限表。

view_permission/edit_permission 为 specified 时，记录哪些用户被指定。
同一用户对同一资产可同时持有 view 与 edit 两条记录。
"""
import logging
from typing import Any, Dict, List, Set

import pymysql

from config.constant import AssetLibraryConstants
from .database import execute_query, execute_update, execute_insert

logger = logging.getLogger(__name__)


class AssetPermissionMemberModel:
    """asset_permission_member 表数据库操作"""

    @staticmethod
    def replace_for_asset(asset_id: int, perm_type: str, user_ids: List[int]) -> None:
        """整组覆盖某资产的指定成员列表（先删后插）。user_ids 去重剔除属主。"""
        valid_ids = sorted({int(uid) for uid in user_ids if uid})
        try:
            execute_update(
                "DELETE FROM asset_permission_member WHERE asset_id = %s AND perm_type = %s",
                (asset_id, perm_type),
            )
            if not valid_ids:
                return
            sql = """
                INSERT INTO asset_permission_member (asset_id, user_id, perm_type)
                VALUES (%s, %s, %s)
            """
            for uid in valid_ids:
                execute_insert(sql, (asset_id, uid, perm_type))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to replace permission members for asset {asset_id} ({perm_type}): {e}")
            raise

    @staticmethod
    def delete_for_asset(asset_id: int) -> None:
        """删除资产的全部成员记录（资产被清除时）"""
        try:
            execute_update("DELETE FROM asset_permission_member WHERE asset_id = %s", (asset_id,))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to delete permission members for asset {asset_id}: {e}")
            raise

    @staticmethod
    def list_by_asset(asset_id: int) -> List[Dict[str, Any]]:
        """列出资产的全部指定成员记录"""
        sql = "SELECT * FROM asset_permission_member WHERE asset_id = %s"
        try:
            return execute_query(sql, (asset_id,), fetch_all=True) or []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list permission members for asset {asset_id}: {e}")
            raise

    @staticmethod
    def map_by_assets(asset_ids: List[int]) -> Dict[int, Dict[str, List[int]]]:
        """批量取资产的指定成员映射：{asset_id: {view: [uid], edit: [uid]}}"""
        if not asset_ids:
            return {}
        placeholders = ','.join(['%s'] * len(asset_ids))
        sql = f"""
            SELECT asset_id, user_id, perm_type FROM asset_permission_member
            WHERE asset_id IN ({placeholders})
        """
        try:
            rows = execute_query(sql, tuple(asset_ids), fetch_all=True) or []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to map permission members for assets {asset_ids}: {e}")
            raise
        result: Dict[int, Dict[str, List[int]]] = {}
        for row in rows:
            asset_id = int(row['asset_id'])
            perm_type = str(row['perm_type'])
            bucket = result.setdefault(asset_id, {'view': [], 'edit': []})
            if perm_type in bucket:
                bucket[perm_type].append(int(row['user_id']))
        return result

    @staticmethod
    def find_accessible_asset_ids(user_id: int, asset_ids: List[int]) -> Set[int]:
        """在给定资产中筛选出该用户被指定了 view 或 edit 权限的资产 ID 集合。"""
        if not asset_ids:
            return set()
        placeholders = ','.join(['%s'] * len(asset_ids))
        sql = f"""
            SELECT DISTINCT asset_id FROM asset_permission_member
            WHERE user_id = %s AND asset_id IN ({placeholders})
        """
        try:
            rows = execute_query(sql, tuple([user_id] + list(asset_ids)), fetch_all=True) or []
            return {int(r['asset_id']) for r in rows}
        except pymysql.MySQLError as e:
            logger.error(f"Failed to find accessible assets for user {user_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `asset_permission_member` (
  `id` int NOT NULL AUTO_INCREMENT,
  `asset_id` int NOT NULL COMMENT '资产 asset_library.id',
  `user_id` int NOT NULL COMMENT '被指定成员用户 ID',
  `perm_type` varchar(10) NOT NULL COMMENT '权限类型：view(可看)/edit(可编辑)',
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_asset_user_perm` (`asset_id`,`user_id`,`perm_type`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资产库指定成员权限表';
"""

# 引用常量避免未使用告警（权限类型合法性在服务层校验）
_PERM_TYPE_CHOICES = AssetLibraryConstants.PERM_TYPE_CHOICES
