"""修复 deepseek-v4-flash-vision-exp 数据丢失（幂等重放 no_120 的数据迁移）

Revision ID: 20260901_fix_ds_vision_data
Revises: 20260901_vidu_q3_power
Create Date: 2026-09-01

背景：部分环境的库曾被 stamp / 基线导入"戳版"到 20260830_ds_vision 之后，
但 no_120（原 20260830_add_deepseek_v4_flash_vision_exp）的数据迁移未真正执行，
导致 model / vendor_model 表缺失 deepseek-v4-flash-vision-exp 行，
画风识别等 VL 场景报「无可用视觉模型」。
本迁移幂等重放那两条 INSERT：已正常执行的库自动跳过，丢失数据的库补齐。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260901_fix_ds_vision_data'
down_revision: Union[str, None] = '20260901_vidu_q3_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """幂等补回 deepseek-v4-flash-vision-exp 模型与计费配置。

    注意：``model.model_name`` 上没有唯一索引，``ON DUPLICATE KEY UPDATE``
    不会触发（no_120 的写法在重复执行时会插入重复行），此处一律改用
    ``NOT EXISTS`` 守卫，保证任意次数重放都不产生重复行。
    """
    conn = op.get_bind()

    # 1. 添加 deepseek-v4-flash-vision-exp 模型（VL 模型，支持图片理解）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        SELECT 'deepseek-v4-flash-vision-exp', 1000000, 1, 384000, 1, 1, NOW(), 'DeepSeek V4 Flash Vision 实验版，支持图片理解，价格与 deepseek-v4-flash 相同'
        WHERE NOT EXISTS (
            SELECT 1 FROM `model` WHERE model_name = 'deepseek-v4-flash-vision-exp'
        )
    """))
    logger.info("[Migration] Ensured deepseek-v4-flash-vision-exp model exists")

    # 2. 计费配置：价格与 deepseek-v4-flash 一致
    # 输入1元/百万, 缓存命中0.02元/百万, 输出2元/百万
    # threshold = 0.04 × 10^6 / 单价(元/百万token)
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 40000, 20000, 2000000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'deepseek' AND m.model_name = 'deepseek-v4-flash-vision-exp'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Ensured deepseek-v4-flash-vision-exp billing: input=40000, out=20000, cache=2000000, raw_threshold=NULL")


def downgrade() -> None:
    """数据修复类迁移：不回滚，避免误删已补齐的数据"""
    pass
