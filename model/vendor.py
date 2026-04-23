"""
Vendor Model - 供应商表
"""
from typing import Optional, List
from datetime import datetime
from model.database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class Vendor:
    """供应商实体"""

    def __init__(
        self,
        id: int = 0,
        vendor_name: Optional[str] = None,
        created_at: Optional[datetime] = None,
        note: Optional[str] = None
    ):
        self.id = id
        self.vendor_name = vendor_name
        self.created_at = created_at
        self.note = note

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'vendor_name': self.vendor_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'note': self.note
        }


class VendorDAO:
    """供应商数据访问层"""

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS `vendor` (
        `id` int NOT NULL AUTO_INCREMENT,
        `vendor_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '供应商名称',
        `created_at` datetime DEFAULT NULL,
        `note` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '其他信息',
        PRIMARY KEY (`id`) USING BTREE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='供应商表'
    """

    @staticmethod
    def create(vendor_name: str, note: Optional[str] = None) -> int:
        """
        创建供应商

        Args:
            vendor_name: 供应商名称
            note: 备注

        Returns:
            新创建的供应商ID
        """
        sql = """
            INSERT INTO vendor (vendor_name, created_at, note)
            VALUES (%s, NOW(), %s)
        """
        return execute_insert(sql, (vendor_name, note))

    @staticmethod
    def get_by_id(vendor_id: int) -> Optional[Vendor]:
        """
        根据ID获取供应商

        Args:
            vendor_id: 供应商ID

        Returns:
            供应商实体或None
        """
        sql = """
            SELECT id, vendor_name, created_at, note
            FROM vendor
            WHERE id = %s
        """
        row = execute_query(sql, (vendor_id,), fetch_one=True)
        if not row:
            return None

        return Vendor(
            id=row['id'],
            vendor_name=row['vendor_name'],
            created_at=row['created_at'],
            note=row['note']
        )

    @staticmethod
    def get_all() -> List[Vendor]:
        """
        获取所有供应商

        Returns:
            供应商列表
        """
        sql = """
            SELECT id, vendor_name, created_at, note
            FROM vendor
            ORDER BY id
        """
        rows = execute_query(sql, fetch_all=True)
        if not rows:
            return []
        return [
            Vendor(
                id=row['id'],
                vendor_name=row['vendor_name'],
                created_at=row['created_at'],
                note=row['note']
            )
            for row in rows
        ]

    @staticmethod
    def update(vendor_id: int, vendor_name: Optional[str] = None, note: Optional[str] = None) -> int:
        """
        更新供应商

        Args:
            vendor_id: 供应商ID
            vendor_name: 供应商名称
            note: 备注

        Returns:
            受影响的行数
        """
        updates = []
        params = []

        if vendor_name is not None:
            updates.append("vendor_name = %s")
            params.append(vendor_name)
        if note is not None:
            updates.append("note = %s")
            params.append(note)

        if not updates:
            return 0

        params.append(vendor_id)
        sql = f"UPDATE vendor SET {', '.join(updates)} WHERE id = %s"
        return execute_update(sql, tuple(params))

    @staticmethod
    def delete(vendor_id: int) -> int:
        """
        删除供应商

        Args:
            vendor_id: 供应商ID

        Returns:
            受影响的行数
        """
        sql = "DELETE FROM vendor WHERE id = %s"
        return execute_update(sql, (vendor_id,))
