"""cleanup_runninghub_slots

Revision ID: 20260318_cleanup_slots
Revises: 20260311_props_unique
Create Date: 2026-03-18 10:00:00.000000+08:00

清理卡住的 runninghub_slots 槽位记录
由于之前的 bug，任务完成后槽位未被正确释放，导致槽位泄漏
此 migration 将释放所有活跃状态的槽位
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260318_cleanup_slots'
down_revision: Union[str, None] = '20260311_props_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """清理卡住的 runninghub_slots 槽位"""
    bind = op.get_bind()

    # 1. 先统计需要清理的槽位数量
    result = bind.execute(
        sa.text("""
            SELECT COUNT(*) as count
            FROM runninghub_slots
            WHERE status = 1
        """)
    ).fetchone()

    stuck_count = result[0] if result else 0

    if stuck_count > 0:
        # 2. 记录日志：显示将要清理的槽位详情
        details = bind.execute(
            sa.text("""
                SELECT id, task_table_id, task_id, project_id, task_type, acquired_at
                FROM runninghub_slots
                WHERE status = 1
            """)
        ).fetchall()

        print(f"[Migration] Found {stuck_count} stuck RunningHub slots to cleanup:")
        for row in details:
            print(f"  - id={row[0]}, task_table_id={row[1]}, project_id={row[3]}, acquired_at={row[5]}")

        # 3. 释放所有卡住的槽位
        bind.execute(
            sa.text("""
                UPDATE runninghub_slots
                SET status = 2, released_at = NOW()
                WHERE status = 1
            """)
        )

        print(f"[Migration] Successfully released {stuck_count} stuck RunningHub slots")
    else:
        print("[Migration] No stuck RunningHub slots found, nothing to cleanup")


def downgrade() -> None:
    """回滚：此 migration 是一次性数据清理，不需要回滚操作"""
    print("[Migration] downgrade: cleanup_runninghub_slots is a one-time data fix, no rollback needed")
