"""add_props_unique_constraint

Revision ID: 20260311_props_unique
Revises: 20260303_ref_images
Create Date: 2026-03-11 17:30:00.000000+08:00

为 props、character、location 表添加 (world_id, name) 唯一约束，防止同一世界下名称重复
解决并发提交导致的重复创建问题
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260311_props_unique'
down_revision: Union[str, None] = '20260303_ref_images'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_duplicate_names(table_name: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"""
            SELECT id, world_id, name
            FROM `{table_name}`
            ORDER BY world_id, name, id
            """
        )
    ).mappings().all()

    used_names = {}
    duplicate_count = {}

    for row in rows:
        world_id = row['world_id']
        original_name = row['name']

        if world_id not in used_names:
            used_names[world_id] = set()
            duplicate_count[world_id] = {}

        used_names[world_id].add(original_name)

    for row in rows:
        row_id = row['id']
        world_id = row['world_id']
        original_name = row['name']
        world_key = world_id

        world_used_names = used_names[world_key]
        world_duplicate_count = duplicate_count[world_key]

        if original_name not in world_duplicate_count:
            world_duplicate_count[original_name] = 0
            continue

        suffix_index = world_duplicate_count[original_name] + 1
        new_name = f"{original_name}_{suffix_index}"
        while new_name in world_used_names:
            suffix_index += 1
            new_name = f"{original_name}_{suffix_index}"

        bind.execute(
            sa.text(
                f"""
                UPDATE `{table_name}`
                SET name = :new_name
                WHERE id = :row_id
                """
            ),
            {
                'new_name': new_name,
                'row_id': row_id,
            }
        )

        world_duplicate_count[original_name] = suffix_index
        world_used_names.add(new_name)


def upgrade() -> None:
    """升级数据库：为 props、character、location 表添加唯一约束"""

    # === props 表 ===
    _rename_duplicate_names('props')
    # 添加 (world_id, name) 唯一约束
    op.execute("""
        ALTER TABLE `props` 
        ADD UNIQUE INDEX `uk_world_name` (`world_id`, `name`)
    """)

    # === character 表 ===
    _rename_duplicate_names('character')
    # 添加 (world_id, name) 唯一约束
    op.execute("""
        ALTER TABLE `character` 
        ADD UNIQUE INDEX `uk_world_name` (`world_id`, `name`)
    """)

    # === location 表 ===
    _rename_duplicate_names('location')
    # 添加 (world_id, name) 唯一约束
    op.execute("""
        ALTER TABLE `location` 
        ADD UNIQUE INDEX `uk_world_name` (`world_id`, `name`)
    """)


def downgrade() -> None:
    """回滚数据库：删除唯一约束"""

    op.execute("ALTER TABLE `props` DROP INDEX `uk_world_name`")
    op.execute("ALTER TABLE `character` DROP INDEX `uk_world_name`")
    op.execute("ALTER TABLE `location` DROP INDEX `uk_world_name`")
