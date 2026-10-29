# -*- coding: utf-8 -*-
"""Asset Library Model - 资产库表。

用户把 marketing_agent / video_workflow / storyboard 中生成的图片加入资产库
（后期扩展视频/音频）。资产文件永久存放在 upload/asset_library/ 下，
不受媒体缓存清理策略影响；按用户维度由 asset_library_quota 记录已用容量。

⚠️ 资产不允许普通用户删除（需求红线）；管理员清除走服务层
AssetLibraryService.purge_asset（删文件 + 删记录 + 释放配额）。
"""
import logging
from typing import Any, Dict, List, Optional

import pymysql

from config.constant import AssetLibraryConstants
from .database import execute_query, execute_update, execute_insert

logger = logging.getLogger(__name__)


class AssetItem:
    """资产记录"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.group_id = kwargs.get('group_id')
        self.asset_type = kwargs.get('asset_type', AssetLibraryConstants.ASSET_TYPE_IMAGE)
        self.name = kwargs.get('name')
        self.source_url = kwargs.get('source_url')
        self.file_path = kwargs.get('file_path')
        self.file_size = int(kwargs.get('file_size') or 0)
        self.view_permission = kwargs.get('view_permission', AssetLibraryConstants.PERMISSION_PRIVATE)
        self.edit_permission = kwargs.get('edit_permission', AssetLibraryConstants.PERMISSION_PRIVATE)
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    @property
    def file_url(self) -> str:
        """本地静态访问地址（/upload 静态挂载）"""
        return f"/upload/{self.file_path}" if self.file_path else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'group_id': self.group_id,
            'asset_type': self.asset_type,
            'name': self.name,
            'source_url': self.source_url,
            'file_path': self.file_path,
            'file_url': self.file_url,
            'file_size': self.file_size,
            'view_permission': self.view_permission,
            'edit_permission': self.edit_permission,
            'create_at': self.create_at.isoformat() if hasattr(self.create_at, 'isoformat') else self.create_at,
            'update_at': self.update_at.isoformat() if hasattr(self.update_at, 'isoformat') else self.update_at,
        }


class AssetLibraryModel:
    """asset_library 表数据库操作（可见性 JOIN 查询在服务层组装）"""

    @staticmethod
    def create(user_id: int, group_id: Optional[int], asset_type: str, name: str,
               source_url: str, file_path: str, file_size: int,
               view_permission: str, edit_permission: str) -> int:
        """创建资产记录，返回资产 ID"""
        sql = """
            INSERT INTO asset_library
                (user_id, group_id, asset_type, name, source_url, file_path,
                 file_size, view_permission, edit_permission)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            return execute_insert(sql, (
                user_id, group_id, asset_type, name, source_url, file_path,
                file_size, view_permission, edit_permission,
            ))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create asset for user {user_id}: {e}")
            raise

    @staticmethod
    def get_by_id(asset_id: int) -> Optional[AssetItem]:
        """按主键获取资产"""
        sql = "SELECT * FROM asset_library WHERE id = %s"
        try:
            row = execute_query(sql, (asset_id,), fetch_one=True)
            return AssetItem(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get asset {asset_id}: {e}")
            raise

    @staticmethod
    def update(asset_id: int, **fields: Any) -> int:
        """更新资产字段（白名单：名称/分组/权限设置）。

        group_id 允许显式传 None（移回未分组，SQL 写 NULL）；其余字段
        None 视为"未提供"跳过。
        """
        allowed = ('name', 'group_id', 'view_permission', 'edit_permission')
        sets, params = [], []
        for key in allowed:
            if key not in fields:
                continue
            value = fields[key]
            if value is None and key != 'group_id':
                continue
            sets.append(f"{key} = %s")
            params.append(value)
        if not sets:
            return 0
        params.append(asset_id)
        sql = f"UPDATE asset_library SET {', '.join(sets)} WHERE id = %s"
        try:
            return execute_update(sql, tuple(params))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update asset {asset_id}: {e}")
            raise

    @staticmethod
    def delete(asset_id: int) -> int:
        """删除资产记录（仅服务层 purge 流程调用：管理员清除）"""
        sql = "DELETE FROM asset_library WHERE id = %s"
        try:
            return execute_update(sql, (asset_id,))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to delete asset {asset_id}: {e}")
            raise

    @staticmethod
    def count_by_group(group_ids: List[int]) -> Dict[int, int]:
        """统计每个分组的资产总数（管理侧/删除守卫用）。

        必须带 GROUP BY：无 GROUP BY 的聚合在 MySQL 返回单行 (NULL, 0)，
        空组会被误读成"有一条 group_id=NULL 的记录"导致 int(None) 崩溃。
        """
        if not group_ids:
            return {}
        placeholders = ','.join(['%s'] * len(group_ids))
        sql = f"SELECT group_id, COUNT(*) AS cnt FROM asset_library WHERE group_id IN ({placeholders}) GROUP BY group_id"
        try:
            rows = execute_query(sql, tuple(group_ids), fetch_all=True)
            return {int(r['group_id']): int(r['cnt']) for r in rows} if rows else {}
        except pymysql.MySQLError as e:
            logger.error(f"Failed to count assets by group {group_ids}: {e}")
            raise

    @staticmethod
    def count_by_user(user_id: int) -> int:
        """统计用户资产总数（管理端分页用）"""
        sql = "SELECT COUNT(*) AS cnt FROM asset_library WHERE user_id = %s"
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            return int(row['cnt']) if row else 0
        except pymysql.MySQLError as e:
            logger.error(f"Failed to count assets for user {user_id}: {e}")
            raise

    @staticmethod
    def sum_size_by_user(user_id: int) -> int:
        """统计用户资产占用总字节数（配额对账用）"""
        sql = "SELECT COALESCE(SUM(file_size), 0) AS total FROM asset_library WHERE user_id = %s"
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            return int(row['total']) if row else 0
        except pymysql.MySQLError as e:
            logger.error(f"Failed to sum asset size for user {user_id}: {e}")
            raise

    @staticmethod
    def list_by_user(user_id: int, limit: int = 200, offset: int = 0) -> List[AssetItem]:
        """按用户列出资产（管理员清除列表用）"""
        sql = """
            SELECT * FROM asset_library
            WHERE user_id = %s
            ORDER BY create_at DESC, id DESC
            LIMIT %s OFFSET %s
        """
        try:
            rows = execute_query(sql, (user_id, limit, offset), fetch_all=True)
            return [AssetItem(**row) for row in rows] if rows else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list assets for user {user_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `asset_library` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL COMMENT '添加者用户 ID（容量计入该用户）',
  `group_id` int DEFAULT NULL COMMENT '资产分组 asset_group.id（NULL=未分组）',
  `asset_type` varchar(20) NOT NULL DEFAULT 'image' COMMENT '资产类型：image（预留 video/audio）',
  `name` varchar(200) NOT NULL COMMENT '资产名称',
  `source_url` text COMMENT '原始生成地址（溯源用）',
  `file_path` varchar(500) NOT NULL COMMENT '本地存储路径（相对 upload 目录，如 asset_library/1/xxx.png）',
  `file_size` bigint NOT NULL DEFAULT 0 COMMENT '文件字节数（配额统计口径）',
  `view_permission` varchar(20) NOT NULL DEFAULT 'private' COMMENT '查看权限：private/specified/public',
  `edit_permission` varchar(20) NOT NULL DEFAULT 'private' COMMENT '编辑权限：private/specified/public',
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_create` (`user_id`,`create_at`),
  KEY `idx_group` (`group_id`),
  KEY `idx_group_create` (`group_id`,`create_at`),
  KEY `idx_type` (`asset_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资产库表-用户收藏的生成产物，永久存放';
"""
