"""Change implementation_power_config unique key to composite key

Revision ID: 20260323_impl_power_composite
Revises: 20260321_merge_power_config
Create Date: 2026-03-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = '20260323_impl_power_composite'
down_revision = '20260321_merge_power_config'
branch_labels = None
depends_on = None


def upgrade():
    """修改 implementation_power_config 表的唯一约束：
    - 移除 implementation_name 的 UNIQUE 约束（如果存在）
    - 添加 (implementation_name, driver_key) 复合唯一索引

    这样同一个 implementation_name 可以对应多个 driver_key
    """

    logger.info("开始修改 implementation_power_config 表的唯一约束...")

    conn = op.get_bind()

    # 1. 获取现有索引
    result = conn.execute(text("""
        SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'implementation_power_config'
        AND INDEX_NAME = 'implementation_name'
    """))
    existing_indexes = [row[0] for row in result]

    # 2. 删除现有的 implementation_name 唯一索引（如果存在）
    if 'implementation_name' in existing_indexes:
        conn.execute(text("""
            ALTER TABLE implementation_power_config
            DROP INDEX implementation_name
        """))
        logger.info("已删除 implementation_name 的 UNIQUE 约束")
    else:
        logger.info("implementation_name 索引不存在，跳过删除")

    # 3. 检查 idx_impl_name 是否存在
    result = conn.execute(text("""
        SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'implementation_power_config'
        AND INDEX_NAME = 'idx_impl_name'
    """))
    if not result.fetchone():
        # 添加普通索引（非唯一）用于单独查询 implementation_name
        conn.execute(text("""
            CREATE INDEX idx_impl_name ON implementation_power_config (implementation_name)
        """))
        logger.info("已创建 implementation_name 普通索引")
    else:
        logger.info("idx_impl_name 索引已存在，跳过创建")

    # 4. 检查复合唯一索引是否存在
    result = conn.execute(text("""
        SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'implementation_power_config'
        AND INDEX_NAME = 'uk_impl_driver'
    """))
    if not result.fetchone():
        # 添加 (implementation_name, driver_key) 复合唯一索引
        conn.execute(text("""
            ALTER TABLE implementation_power_config
            ADD UNIQUE INDEX uk_impl_driver (implementation_name, driver_key)
        """))
        logger.info("已创建 (implementation_name, driver_key) 复合唯一索引")
    else:
        logger.info("uk_impl_driver 复合唯一索引已存在，跳过创建")

    logger.info("implementation_power_config 表结构修改完成")


def downgrade():
    """回滚：恢复原来的单一唯一约束"""

    logger.info("开始回滚 implementation_power_config 表的唯一约束...")

    conn = op.get_bind()

    # 1. 删除复合唯一索引（如果存在）
    result = conn.execute(text("""
        SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'implementation_power_config'
        AND INDEX_NAME = 'uk_impl_driver'
    """))
    if result.fetchone():
        conn.execute(text("""
            ALTER TABLE implementation_power_config
            DROP INDEX uk_impl_driver
        """))
        logger.info("已删除复合唯一索引")

    # 2. 删除普通索引（如果存在）
    result = conn.execute(text("""
        SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'implementation_power_config'
        AND INDEX_NAME = 'idx_impl_name'
    """))
    if result.fetchone():
        conn.execute(text("""
            DROP INDEX idx_impl_name ON implementation_power_config
        """))
        logger.info("已删除普通索引")

    # 3. 恢复 implementation_name 的 UNIQUE 约束（如果不存在）
    result = conn.execute(text("""
        SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'implementation_power_config'
        AND INDEX_NAME = 'implementation_name'
    """))
    if not result.fetchone():
        conn.execute(text("""
            ALTER TABLE implementation_power_config
            ADD UNIQUE INDEX implementation_name (implementation_name)
        """))
        logger.info("已恢复 implementation_name 的 UNIQUE 约束")

    logger.info("回滚完成")
