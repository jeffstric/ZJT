# -*- coding: utf-8 -*-
"""User Group Model - 用户分组表。

管理员在后台创建分组并把用户归入分组（单组制：users.group_id 一个用户
最多属于一个组，NULL=未分组）。分组仅用于后台管理与报表统计，不影响
用户登录与权限。删除分组时在同事务内把组内用户 group_id 置 NULL，
用户自动回到未分组。
"""
import logging
from typing import Any, Dict, List, Optional

import pymysql

from .database import (
    execute_query,
    execute_update,
    execute_insert,
    transaction,
    execute_update_in_transaction,
)

logger = logging.getLogger(__name__)


class UserGroup:
    """用户分组记录"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name')
        self.remark = kwargs.get('remark')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'remark': self.remark,
            'create_at': self.create_at.isoformat() if hasattr(self.create_at, 'isoformat') else self.create_at,
            'update_at': self.update_at.isoformat() if hasattr(self.update_at, 'isoformat') else self.update_at,
        }


class UserGroupModel:
    """user_group 表数据库操作"""

    @staticmethod
    def create(name: str, remark: Optional[str] = None) -> int:
        """创建分组，返回分组 ID。重名抛 pymysql.IntegrityError。"""
        sql = """
            INSERT INTO user_group (name, remark)
            VALUES (%s, %s)
        """
        try:
            return execute_insert(sql, (name, remark))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create user group '{name}': {e}")
            raise

    @staticmethod
    def get_by_id(group_id: int) -> Optional[UserGroup]:
        """按主键获取分组"""
        sql = "SELECT * FROM user_group WHERE id = %s"
        try:
            row = execute_query(sql, (group_id,), fetch_one=True)
            return UserGroup(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get user group {group_id}: {e}")
            raise

    @staticmethod
    def get_by_name(name: str) -> Optional[UserGroup]:
        """按名称精确查找（重名校验）"""
        sql = "SELECT * FROM user_group WHERE name = %s"
        try:
            row = execute_query(sql, (name,), fetch_one=True)
            return UserGroup(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get user group by name '{name}': {e}")
            raise

    @staticmethod
    def list_all() -> List[Dict[str, Any]]:
        """列出全部分组（含成员数），按创建时间正序"""
        sql = """
            SELECT
                g.id,
                g.name,
                g.remark,
                g.create_at,
                g.update_at,
                COUNT(u.id) AS member_count
            FROM user_group g
            LEFT JOIN users u ON u.group_id = g.id
            GROUP BY g.id, g.name, g.remark, g.create_at, g.update_at
            ORDER BY g.create_at ASC, g.id ASC
        """
        try:
            rows = execute_query(sql, (), fetch_all=True)
            return rows or []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list user groups: {e}")
            raise

    @staticmethod
    def update(group_id: int, name: Optional[str] = None, remark: Optional[str] = None) -> int:
        """更新分组名称/备注。传 None 表示不修改对应字段。"""
        sets: List[str] = []
        params: List[Any] = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if remark is not None:
            sets.append("remark = %s")
            params.append(remark)
        if not sets:
            return 0
        sql = f"UPDATE user_group SET {', '.join(sets)} WHERE id = %s"
        params.append(group_id)
        try:
            return execute_update(sql, tuple(params))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update user group {group_id}: {e}")
            raise

    @staticmethod
    def delete(group_id: int) -> int:
        """删除分组：同事务内先把组内用户 group_id 置 NULL（用户回到未分组）"""
        with transaction() as conn:
            execute_update_in_transaction(
                conn,
                "UPDATE users SET group_id = NULL WHERE group_id = %s",
                (group_id,),
            )
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_group WHERE id = %s", (group_id,))
            return cursor.rowcount

    @staticmethod
    def list_members(group_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """分页列出分组内用户（含管理员备注/昵称，display_name 后端层组装）"""
        offset = (max(page, 1) - 1) * max(page_size, 1)
        count_sql = "SELECT COUNT(*) AS total FROM users WHERE group_id = %s"
        data_sql = """
            SELECT
                u.id AS user_id,
                u.phone,
                u.email,
                u.nickname,
                u.remark,
                u.status,
                u.created_at
            FROM users u
            WHERE u.group_id = %s
            ORDER BY u.id ASC
            LIMIT %s OFFSET %s
        """
        try:
            total_row = execute_query(count_sql, (group_id,), fetch_one=True)
            total = int(total_row['total']) if total_row else 0
            rows = execute_query(data_sql, (group_id, max(page_size, 1), offset), fetch_all=True) or []
            return {'total': total, 'page': page, 'page_size': page_size, 'data': rows}
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list members of user group {group_id}: {e}")
            raise

    @staticmethod
    def set_user_group(user_id: int, group_id: Optional[int]) -> int:
        """把用户归入分组；group_id 为 None 表示移出分组（回到未分组）"""
        sql = "UPDATE users SET group_id = %s WHERE id = %s"
        try:
            return execute_update(sql, (group_id, user_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to set group of user {user_id} to {group_id}: {e}")
            raise

    @staticmethod
    def clear_group_for_users(user_ids: List[int]) -> int:
        """批量移出分组（预留批量操作用）"""
        if not user_ids:
            return 0
        placeholders = ', '.join(['%s'] * len(user_ids))
        sql = f"UPDATE users SET group_id = NULL WHERE id IN ({placeholders})"
        try:
            return execute_update(sql, tuple(user_ids))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to clear group for users {user_ids}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `user_group` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '分组名称',
  `remark` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '分组备注',
  `create_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_name` (`name`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户分组（管理员创建）';
"""
