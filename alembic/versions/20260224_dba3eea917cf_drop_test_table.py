"""drop_test_table

Revision ID: dba3eea917cf
Revises: 69f38f419eb6
Create Date: 2026-02-24 10:34:03.381456+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dba3eea917cf'
down_revision: Union[str, None] = '69f38f419eb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库"""
    op.execute("DROP TABLE IF EXISTS `alembic_test_table`")


def downgrade() -> None:
    """回滚数据库"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `alembic_test_table` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `name` VARCHAR(255) NOT NULL,
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Alembic 测试表'
    """)
