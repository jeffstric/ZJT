"""用户模块与核心模型条目（实现方绑定）的数据访问层。

一条绑定表示：把已激活用户模块的某个 operation 能力，注册为某个核心任务条目
（UnifiedTaskConfig）的一个可选实现方。绑定仅在模块处于 enabled+active 时生效，
模块禁用/隔离后绑定自动失效（查询时 JOIN 过滤，不做状态同步）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from model.database import execute_query, execute_update, transaction
from model.user_modules import UserModuleStatus

from config.constant import USER_MODULE_IMPL_ID_BASE

logger = logging.getLogger(__name__)


@dataclass
class UserModuleTaskBindingEntity:
    id: int
    module_id: str
    operation: str
    task_id: int
    implementation_id: int
    implementation_name: str
    display_name: str
    # JOIN user_module 带出的模块侧状态（用于界面展示绑定是否生效）
    module_name: Optional[str] = None
    module_effective: bool = False
    create_at: Any = None
    update_at: Any = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "UserModuleTaskBindingEntity":
        return cls(
            id=row["id"],
            module_id=row["module_id"],
            operation=row["operation"],
            task_id=int(row["task_id"]),
            implementation_id=int(row["implementation_id"]),
            implementation_name=row["implementation_name"],
            display_name=row.get("display_name") or "",
            module_name=row.get("module_name"),
            module_effective=bool(row.get("module_effective")),
            create_at=row.get("create_at"),
            update_at=row.get("update_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "module_id": self.module_id,
            "operation": self.operation,
            "task_id": self.task_id,
            "implementation_id": self.implementation_id,
            "implementation_name": self.implementation_name,
            "display_name": self.display_name,
            "module_name": self.module_name,
            "module_effective": self.module_effective,
            "create_at": self.create_at.isoformat() if self.create_at else None,
            "update_at": self.update_at.isoformat() if self.update_at else None,
        }


class UserModuleTaskBindingModel:
    """user_module_task_binding 表的数据访问方法。

    注意：execute_query 使用 pymysql 的 pyformat 参数风格，SQL 中所有 ``%`` 都是
    占位符；本类 SQL 的字面量一律不使用 ``%`` 字符（含 'active' 常量内联）。
    """

    _BASE_SELECT = """
        SELECT b.*, m.name AS module_name,
               (m.enabled = 1 AND m.status = 'active' AND m.active_release_id IS NOT NULL) AS module_effective
        FROM user_module_task_binding b
        LEFT JOIN user_module m ON m.module_id = b.module_id
    """

    @staticmethod
    def create(
        module_id: str,
        operation: str,
        task_id: int,
        implementation_id: int,
        implementation_name: str,
        display_name: str = "",
    ) -> int:
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_module_task_binding
                    (module_id, operation, task_id, implementation_id, implementation_name, display_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (module_id, operation, task_id, implementation_id, implementation_name, display_name),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def delete(binding_id: int) -> bool:
        affected = execute_update(
            "DELETE FROM user_module_task_binding WHERE id = %s LIMIT 1",
            (binding_id,),
        )
        return bool(affected)

    @staticmethod
    def get_by_id(binding_id: int) -> Optional[UserModuleTaskBindingEntity]:
        row = execute_query(
            UserModuleTaskBindingModel._BASE_SELECT + " WHERE b.id = %s LIMIT 1",
            (binding_id,),
            fetch_one=True,
        )
        return UserModuleTaskBindingEntity.from_row(row) if row else None

    @staticmethod
    def list_by_module(module_id: str) -> List[UserModuleTaskBindingEntity]:
        rows = execute_query(
            UserModuleTaskBindingModel._BASE_SELECT + " WHERE b.module_id = %s ORDER BY b.id",
            (module_id,),
            fetch_all=True,
        ) or []
        return [UserModuleTaskBindingEntity.from_row(row) for row in rows]

    @staticmethod
    def find_duplicate(module_id: str, operation: str, task_id: int) -> Optional[UserModuleTaskBindingEntity]:
        row = execute_query(
            UserModuleTaskBindingModel._BASE_SELECT
            + " WHERE b.module_id = %s AND b.operation = %s AND b.task_id = %s LIMIT 1",
            (module_id, operation, task_id),
            fetch_one=True,
        )
        return UserModuleTaskBindingEntity.from_row(row) if row else None

    @staticmethod
    def list_effective() -> List[UserModuleTaskBindingEntity]:
        """列出当前生效的绑定：模块 enabled 且 status=active 且已有激活 Release。"""
        rows = execute_query(
            UserModuleTaskBindingModel._BASE_SELECT
            + """
            WHERE m.enabled = 1 AND m.status = 'active' AND m.active_release_id IS NOT NULL
            ORDER BY b.id
            """,
            fetch_all=True,
        ) or []
        return [UserModuleTaskBindingEntity.from_row(row) for row in rows]

    @staticmethod
    def next_implementation_id() -> int:
        """从 USER_MODULE_IMPL_ID_BASE 起分配最小未占用的实现方数字 ID。

        绑定表行数与核心实现方数量同量级（几十条），全量读取后内存求最小空位即可。
        ID 不回收：删除绑定后其 ID 保持占用，避免历史 ai_tools.implementation 引用被复用。
        """
        rows = execute_query(
            "SELECT implementation_id FROM user_module_task_binding WHERE implementation_id >= %s",
            (USER_MODULE_IMPL_ID_BASE,),
            fetch_all=True,
        ) or []
        used = {int(row["implementation_id"]) for row in rows}
        candidate = USER_MODULE_IMPL_ID_BASE
        while candidate in used:
            candidate += 1
        return candidate


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `user_module_task_binding` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `module_id` VARCHAR(128) NOT NULL,
  `operation` VARCHAR(64) NOT NULL,
  `task_id` INT UNSIGNED NOT NULL,
  `implementation_id` INT UNSIGNED NOT NULL,
  `implementation_name` VARCHAR(256) NOT NULL,
  `display_name` VARCHAR(256) NOT NULL DEFAULT '',
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_module_binding_impl_id` (`implementation_id`),
  UNIQUE KEY `uk_user_module_binding_impl_name` (`implementation_name`),
  UNIQUE KEY `uk_user_module_binding_unique` (`module_id`, `operation`, `task_id`),
  KEY `idx_user_module_binding_module` (`module_id`),
  KEY `idx_user_module_binding_task` (`task_id`),
  CONSTRAINT `fk_user_module_binding_module` FOREIGN KEY (`module_id`)
    REFERENCES `user_module` (`module_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
