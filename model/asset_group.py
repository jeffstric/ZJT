# -*- coding: utf-8 -*-
"""Asset Group Model - 资产库分组（目录）表。

分组目录对所有登录用户共享（需求：资产库允许别人看时，所有人的分组目录
都是共享的）。任何登录用户可创建分组；重命名/删除仅限创建者或管理员，
且组内仍有资产时拒绝删除（防止资产悬空）。
"""
import logging
from typing import Any, Dict, List, Optional

import pymysql

from config.constant import AssetLibraryConstants
from .database import execute_query, execute_update, execute_insert

logger = logging.getLogger(__name__)


class AssetGroup:
    """资产分组记录"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name')
        self.creator_user_id = kwargs.get('creator_user_id')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'creator_user_id': self.creator_user_id,
            'create_at': self.create_at.isoformat() if hasattr(self.create_at, 'isoformat') else self.create_at,
            'update_at': self.update_at.isoformat() if hasattr(self.update_at, 'isoformat') else self.update_at,
        }


class AssetGroupModel:
    """asset_group 表数据库操作"""

    @staticmethod
    def create(name: str, creator_user_id: int) -> int:
        """创建分组，返回分组 ID。重名抛 pymysql.IntegrityError。"""
        sql = """
            INSERT INTO asset_group (name, creator_user_id)
            VALUES (%s, %s)
        """
        try:
            return execute_insert(sql, (name, creator_user_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create asset group '{name}' by user {creator_user_id}: {e}")
            raise

    @staticmethod
    def get_by_id(group_id: int) -> Optional[AssetGroup]:
        """按主键获取分组"""
        sql = "SELECT * FROM asset_group WHERE id = %s"
        try:
            row = execute_query(sql, (group_id,), fetch_one=True)
            return AssetGroup(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get asset group {group_id}: {e}")
            raise

    @staticmethod
    def get_by_name(name: str) -> Optional[AssetGroup]:
        """按名称精确查找（重名校验）"""
        sql = "SELECT * FROM asset_group WHERE name = %s"
        try:
            row = execute_query(sql, (name,), fetch_one=True)
            return AssetGroup(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get asset group by name '{name}': {e}")
            raise

    @staticmethod
    def list_all() -> List[AssetGroup]:
        """列出全部分组（共享目录，按创建时间正序）"""
        sql = "SELECT * FROM asset_group ORDER BY create_at ASC, id ASC"
        try:
            rows = execute_query(sql, (), fetch_all=True)
            return [AssetGroup(**row) for row in rows] if rows else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list asset groups: {e}")
            raise

    @staticmethod
    def rename(group_id: int, name: str) -> int:
        """重命名分组"""
        sql = "UPDATE asset_group SET name = %s WHERE id = %s"
        try:
            return execute_update(sql, (name, group_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to rename asset group {group_id}: {e}")
            raise

    @staticmethod
    def delete(group_id: int) -> int:
        """删除分组记录（组内资产校验由服务层负责）"""
        sql = "DELETE FROM asset_group WHERE id = %s"
        try:
            return execute_update(sql, (group_id,))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to delete asset group {group_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `asset_group` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL COMMENT '分组名称（全局唯一，共享目录）',
  `creator_user_id` int NOT NULL COMMENT '创建者用户 ID',
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资产库分组（目录）表-全局共享';
"""

# 引用常量避免未使用告警（分组名长度约束在服务层校验）
_GROUP_NAME_MAX_LENGTH = AssetLibraryConstants.GROUP_NAME_MAX_LENGTH
