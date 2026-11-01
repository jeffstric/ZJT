"""storyboard batch job limit config

新增故事板批量生图调度器每轮推进的活跃批次上限配置
storyboard.batch_scheduler_job_limit（默认 10，热更新生效）。

背景：高峰期活跃批次超过调度上限（原硬编码 BATCH_SCHEDULER_JOB_LIMIT=10）时，
按创建时间排在后面的批次会持续饥饿（用户表现为故事板图片一直不生成）。
该上限改为管理后台「系统配置」可调（config/default_configs.py 同步注册）。

种入策略：对 system_config 表中已存在的每个 env 幂等插入一行默认值，
保证部署后管理后台立即可见可编辑（不依赖管理员手动点「初始化配置」按钮）。

Revision ID: 20261101_storyboard_batch_job_li
Revises: 20261029_enable_ds_v4_flash_vl
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261101_storyboard_batch_job_li'
down_revision: Union[str, None] = '20261029_enable_ds_v4_flash_vl'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONFIG_KEY = 'storyboard.batch_scheduler_job_limit'

# 与 config/default_configs.py 中同名配置的 description 保持一致
CONFIG_DESCRIPTION = (
    '故事板批量生图调度器每轮推进的活跃批次上限（按创建时间取最老 N 个）。'
    '高峰期活跃批次超过该值时，新发起的批次会排队等待（界面表现为一直不出图），'
    '可适当调大缓解排队。热更新生效（约 30 秒内），无需重启服务。'
    '默认 10，合法范围 1-200'
)


def upgrade() -> None:
    """对已存在的每个 env 幂等种入配置行（不存在才插入，已有值不覆盖）。"""
    conn = op.get_bind()
    result = conn.execute(text(f"""
        INSERT INTO system_config
            (env, config_key, config_value, value_type, description,
             editable, is_sensitive, created_at, updated_at)
        SELECT e.env, :config_key, '10', 'int', :description, 1, 0, NOW(), NOW()
        FROM (SELECT DISTINCT env FROM system_config) e
        WHERE NOT EXISTS (
            SELECT 1 FROM system_config sc
            WHERE sc.env = e.env AND sc.config_key = :config_key
        )
    """), {"config_key": CONFIG_KEY, "description": CONFIG_DESCRIPTION})
    if result.rowcount:
        logger.info("seeded %s rows for %s", result.rowcount, CONFIG_KEY)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text("DELETE FROM system_config WHERE config_key = :config_key"),
        {"config_key": CONFIG_KEY},
    )
