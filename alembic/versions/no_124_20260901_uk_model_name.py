"""model 表新增 model_name 唯一索引（失败不阻断服务：仅告警并跳过）

Revision ID: 20260901_uk_model_name
Revises: 20260901_fix_ds_vision_data
Create Date: 2026-09-01

背景：model.model_name 无唯一索引，INSERT ... ON DUPLICATE KEY UPDATE 的去重不生效（只有 id 主键，每次自增新 id 不会触发冲突），
重复执行数据迁移会插入同名重复行（dev3 实测复现：deepseek-v4-flash-vision-exp 被插入两行）。
本迁移为 model_name 加唯一索引，从 schema 层面杜绝同名模型重复行。

⚠️ 容错要求：若加索引失败（如存量数据存在同名重复行导致 1062 Duplicate entry），
只记录告警并跳过，绝不抛异常 —— 启动时 run_migrations() 失败会阻断整个服务，
此处按产品要求"加索引失败不阻断服务"。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260901_uk_model_name'
down_revision: Union[str, None] = '20260901_fix_ds_vision_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 model.model_name 加唯一索引；失败（如存量重复数据）时仅告警跳过，不阻断启动。

    背景：model_name 无唯一索引导致数据迁移重放产生同名重复行。
    若存量库存在同名重复数据，CREATE UNIQUE INDEX 会报 1062——
    此时记录告警并跳过，保证 run_migrations() 不抛异常、服务正常启动。
    """
    conn = op.get_bind()

    # 1. 已存在则跳过（幂等）
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'model'
          AND INDEX_NAME = 'uk_model_name'
    """)).scalar()
    if exists:
        logger.info("[Migration] uk_model_name 已存在，跳过")
        return

    # 2. 加唯一索引；失败（如存量重复数据 1062）仅告警，不阻断服务启动
    try:
        conn.execute(text("""
            CREATE UNIQUE INDEX `uk_model_name` ON `model` (`model_name`)
        """))
        logger.info("[Migration] Added unique index uk_model_name on model(model_name)")
    except Exception as exc:
        logger.warning(
            "[Migration] 创建 uk_model_name 唯一索引失败，已跳过（不影响服务启动）: %s。"
            "请清理 model 表同名重复数据后手工补建。", exc
        )


def downgrade() -> None:
    """移除唯一索引（不存在则忽略）"""
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'model'
          AND INDEX_NAME = 'uk_model_name'
    """)).scalar()
    if not exists:
        return
    conn.execute(text("DROP INDEX `uk_model_name` ON `model`"))
    logger.info("[Migration] Dropped unique index uk_model_name")
