"""
添加 implementation 字段到 ai_tools 表

用于记录任务实际使用的服务商实现
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.execute("""
        ALTER TABLE `ai_tools`
        ADD COLUMN `implementation` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '服务商实现ID，参考 DriverImplementationId'
    """)

def downgrade():
    op.execute("""
        ALTER TABLE `ai_tools`
        DROP COLUMN `implementation`
    """)
