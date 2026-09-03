"""deepseek-v4-flash-vision-exp 默认计价改为峰谷两档（与 deepseek-v4-flash 同价）

Revision ID: 20260901_ds_vision_peak_valley
Revises: 20260901_fix_ds_vision_data
Create Date: 2026-09-01

背景：no_120 / no_122 为 deepseek-v4-flash-vision-exp 插入的是 normal 单档
（in 40000 / out 20000 / cache 2000000，即 1/2/0.02 元/百万旧价），
而该模型计费应与 deepseek-v4-flash 一致（官方 2026-08-17 起峰谷定价）。
本迁移把 normal 档转为 peak 档并补插 off_peak 档，幂等：
已手动配置过峰谷档的库只补缺，不覆盖。

threshold 换算（POWER_YUAN=0.04, scale=1e6）：threshold = round(40000 / 单价(元/百万))
  peak:     in 13333 / out 4444 / cache 400000   (3.0 / 9.0 / 0.10 元/百万)
  off_peak: in 26667 / out 8889 / cache 800000   (1.5 / 4.5 / 0.05 元/百万)
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260901_ds_vision_peak_valley'
down_revision: Union[str, None] = '20260901_fix_ds_vision_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODEL_NAME = 'deepseek-v4-flash-vision-exp'

# 峰谷两档阈值（与 deepseek-v4-flash 官方峰谷价一致）
_PEAK_TIER = {'in_th': 13333, 'out_th': 4444, 'cache_th': 400000}
_OFF_PEAK_TIER = {'in_th': 26667, 'out_th': 8889, 'cache_th': 800000}

# 回滚用：no_120 原始 normal 单档（1/2/0.02 元/百万）
_LEGACY_NORMAL_TIER = {'in_th': 40000, 'out_th': 20000, 'cache_th': 2000000}


def _tier_exists(conn, period: str) -> bool:
    """该模型在官方 deepseek 供应商下是否已存在指定时段的无上限档"""
    row = conn.execute(text(
        """
        SELECT COUNT(*) FROM vendor_model vm
        JOIN vendor v ON v.id = vm.vendor_id
        JOIN model m ON m.id = vm.model_id
        WHERE v.vendor_name = 'deepseek' AND m.model_name = :model_name
          AND vm.raw_token_threshold IS NULL AND vm.time_period = :period
        """
    ), {'model_name': _MODEL_NAME, 'period': period}).fetchone()
    return bool(row) and int(row[0]) > 0


def upgrade() -> None:
    """升级：vision-exp 计价 normal 单档 -> peak + off_peak 峰谷两档（幂等）"""
    conn = op.get_bind()

    # 1. normal 档转为 peak 档并更新为峰时价（仅当 peak 档不存在，避免覆盖手动配置）
    if not _tier_exists(conn, 'peak'):
        result = conn.execute(text(
            """
            UPDATE vendor_model vm
            JOIN vendor v ON v.id = vm.vendor_id
            JOIN model m ON m.id = vm.model_id
            SET vm.time_period = 'peak',
                vm.input_token_threshold = :in_th,
                vm.out_token_threshold = :out_th,
                vm.cache_read_threshold = :cache_th
            WHERE v.vendor_name = 'deepseek' AND m.model_name = :model_name
              AND vm.time_period = 'normal' AND vm.raw_token_threshold IS NULL
            """
        ), {**_PEAK_TIER, 'model_name': _MODEL_NAME})
        updated = getattr(result, 'rowcount', 0) or 0
        if updated:
            logger.info(
                f"[Migration] deepseek/{_MODEL_NAME} normal 档转为 peak 档 "
                f"(in:{_PEAK_TIER['in_th']}, out:{_PEAK_TIER['out_th']}, cache:{_PEAK_TIER['cache_th']})"
            )

    # 2. 补插 off_peak 档（谷时价，幂等）
    if not _tier_exists(conn, 'off_peak'):
        conn.execute(text(
            """
            INSERT INTO vendor_model
              (vendor_id, model_id, input_token_threshold, out_token_threshold,
               cache_read_threshold, raw_token_threshold, commission_rate, time_period, created_at)
            SELECT v.id, m.id, :in_th, :out_th, :cache_th, NULL, 0, 'off_peak', NOW()
            FROM vendor v
            JOIN model m ON m.model_name = :model_name
            WHERE v.vendor_name = 'deepseek'
              AND NOT EXISTS (
                SELECT 1 FROM vendor_model vm
                WHERE vm.vendor_id = v.id AND vm.model_id = m.id
                  AND vm.raw_token_threshold IS NULL AND vm.time_period = 'off_peak'
              )
            """
        ), {**_OFF_PEAK_TIER, 'model_name': _MODEL_NAME})
        logger.info(
            f"[Migration] 补插 deepseek/{_MODEL_NAME} off_peak 档 "
            f"(in:{_OFF_PEAK_TIER['in_th']}, out:{_OFF_PEAK_TIER['out_th']}, cache:{_OFF_PEAK_TIER['cache_th']})"
        )

    # 3. 若 peak 档仍不存在（库里连 normal 档也没有的极端情况），补插 peak 档兜底
    if not _tier_exists(conn, 'peak'):
        conn.execute(text(
            """
            INSERT INTO vendor_model
              (vendor_id, model_id, input_token_threshold, out_token_threshold,
               cache_read_threshold, raw_token_threshold, commission_rate, time_period, created_at)
            SELECT v.id, m.id, :in_th, :out_th, :cache_th, NULL, 0, 'peak', NOW()
            FROM vendor v
            JOIN model m ON m.model_name = :model_name
            WHERE v.vendor_name = 'deepseek'
              AND NOT EXISTS (
                SELECT 1 FROM vendor_model vm
                WHERE vm.vendor_id = v.id AND vm.model_id = m.id
                  AND vm.raw_token_threshold IS NULL AND vm.time_period = 'peak'
              )
            """
        ), {**_PEAK_TIER, 'model_name': _MODEL_NAME})
        logger.info(f"[Migration] 补插 deepseek/{_MODEL_NAME} peak 档兜底")


def downgrade() -> None:
    """回滚：删除 vision-exp 峰谷两档，恢复 no_120 原始 normal 单档（旧价 1/2/0.02 元/百万）"""
    conn = op.get_bind()

    # 1. 删除 peak / off_peak 档
    conn.execute(text(
        """
        DELETE vm FROM vendor_model vm
        JOIN vendor v ON v.id = vm.vendor_id
        JOIN model m ON m.id = vm.model_id
        WHERE v.vendor_name = 'deepseek' AND m.model_name = :model_name
          AND vm.time_period IN ('peak', 'off_peak') AND vm.raw_token_threshold IS NULL
        """
    ), {'model_name': _MODEL_NAME})
    logger.info(f"[Migration] 已删除 deepseek/{_MODEL_NAME} 峰谷档位")

    # 2. 恢复 normal 单档（幂等：已存在则跳过）
    if not _tier_exists(conn, 'normal'):
        conn.execute(text(
            """
            INSERT INTO vendor_model
              (vendor_id, model_id, input_token_threshold, out_token_threshold,
               cache_read_threshold, raw_token_threshold, commission_rate, time_period, created_at)
            SELECT v.id, m.id, :in_th, :out_th, :cache_th, NULL, 0, 'normal', NOW()
            FROM vendor v
            JOIN model m ON m.model_name = :model_name
            WHERE v.vendor_name = 'deepseek'
              AND NOT EXISTS (
                SELECT 1 FROM vendor_model vm
                WHERE vm.vendor_id = v.id AND vm.model_id = m.id
                  AND vm.raw_token_threshold IS NULL AND vm.time_period = 'normal'
              )
            """
        ), {**_LEGACY_NORMAL_TIER, 'model_name': _MODEL_NAME})
        logger.info(f"[Migration] 已恢复 deepseek/{_MODEL_NAME} normal 档（no_120 原始价格）")
