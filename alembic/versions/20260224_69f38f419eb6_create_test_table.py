"""create_test_table

Revision ID: 69f38f419eb6
Revises: 
Create Date: 2026-02-24 10:33:45.710891+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69f38f419eb6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `alembic_test_table` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `name` VARCHAR(255) NOT NULL,
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Alembic 测试表'
    """)


def downgrade() -> None:
    """回滚数据库"""
    op.execute("DROP TABLE IF EXISTS `alembic_test_table`")
