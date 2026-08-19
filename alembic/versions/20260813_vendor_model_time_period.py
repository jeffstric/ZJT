"""vendor_model 增加 time_period 字段（峰谷计费）+ 官方 DeepSeek 峰谷档位初始化

Revision ID: 20260813_vm_period
Revises: 20260812_merge_heads
Create Date: 2026-08-13

变更内容：
1. vendor_model 新增 time_period ENUM('normal','peak','off_peak') NOT NULL DEFAULT 'normal'
   - normal: 不分峰谷（现有模型默认值，完全向后兼容）
   - peak:    高峰时段（北京时间 9:00-12:00、14:00-18:00）
   - off_peak: 空闲时段（其余时间）
2. 为官方 deepseek 供应商的 deepseek-v4-flash / deepseek-v4-pro 初始化峰谷两档，
   使 DeepSeek 官方 2026-08-17 峰谷定价自动生效。
   - 扣费时按 token_log.created_at 判断时段，命中对应档；其余模型维持 normal 不受影响。

threshold 换算（POWER_YUAN=0.04, scale=1e6）：threshold = round(40000 / 单价(元/百万))
  flash peak:     in 13333 / out 4444 / cache 400000   (3.0 / 9.0 / 0.10 元/百万)
  flash off_peak: in 26667 / out 8889 / cache 800000   (1.5 / 4.5 / 0.05 元/百万)
  pro peak:       in 4444  / out 1481 / cache 133333   (9.0 / 27.0 / 0.30 元/百万)
  pro off_peak:   in 8889  / out 2963 / cache 266667   (4.5 / 13.5 / 0.15 元/百万)
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260813_vm_period'
down_revision: Union[str, None] = '20260812_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 官方 deepseek 峰谷档位：(model_name, period, in_th, out_th, cache_th)
_DEEPSEEK_PEAK_VALLEY_TIERS = [
    ('deepseek-v4-flash', 'peak',     13333, 4444, 400000),
    ('deepseek-v4-flash', 'off_peak', 26667, 8889, 800000),
    ('deepseek-v4-pro',   'peak',     4444,  1481, 133333),
    ('deepseek-v4-pro',   'off_peak', 8889,  2963, 266667),
]


def upgrade() -> None:
    """升级：加 time_period 字段 + 初始化官方 DeepSeek 峰谷档位"""
    conn = op.get_bind()

    # 1. 新增 time_period 字段（MySQL 5.7 兼容写法：先检查列是否存在）
    col_exists = conn.execute(text(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vendor_model' "
        "AND COLUMN_NAME = 'time_period'"
    )).fetchone()
    if not col_exists or int(col_exists[0]) == 0:
        conn.execute(text(
            "ALTER TABLE `vendor_model` "
            "ADD COLUMN `time_period` ENUM('normal','peak','off_peak') "
            "NOT NULL DEFAULT 'normal' COMMENT '计费时段：normal=不分峰谷, peak=高峰, off_peak=空闲' "
            "AFTER `commission_rate`"
        ))
        logger.info("[Migration] vendor_model 新增 time_period 字段")
    else:
        logger.info("[Migration] vendor_model.time_period 字段已存在，跳过")

    # 2. 为官方 deepseek 初始化峰谷档位（幂等：已存在则跳过，不影响自定义配置）
    for model_name, period, in_th, out_th, cache_th in _DEEPSEEK_PEAK_VALLEY_TIERS:
        result = conn.execute(text(
            """
            INSERT INTO vendor_model
              (vendor_id, model_id, input_token_threshold, out_token_threshold,
               cache_read_threshold, raw_token_threshold, commission_rate, time_period, created_at)
            SELECT v.id, m.id, :in_th, :out_th, :cache_th, NULL, 0, :period, NOW()
            FROM vendor v
            JOIN model m ON m.model_name = :model_name
            WHERE v.vendor_name = 'deepseek'
              AND NOT EXISTS (
                SELECT 1 FROM vendor_model vm
                WHERE vm.vendor_id = v.id AND vm.model_id = m.id
                  AND vm.raw_token_threshold IS NULL AND vm.time_period = :period
              )
            """
        ), {
            'in_th': in_th, 'out_th': out_th, 'cache_th': cache_th,
            'period': period, 'model_name': model_name,
        })
        inserted = getattr(result, 'rowcount', 0) or 0
        if inserted:
            logger.info(
                f"[Migration] 插入 deepseek/{model_name} {period} 档 "
                f"(in:{in_th}, out:{out_th}, cache:{cache_th})"
            )


def downgrade() -> None:
    """回滚：删除本次迁移插入的官方 DeepSeek 峰谷档位，并移除 time_period 字段"""
    conn = op.get_bind()

    # 1. 删除 upgrade 插入的官方 deepseek 峰谷档位（仅 peak/off_peak，保留原有 normal 档）
    conn.execute(text(
        """
        DELETE vm FROM vendor_model vm
        JOIN vendor v ON v.id = vm.vendor_id
        JOIN model m ON m.id = vm.model_id
        WHERE v.vendor_name = 'deepseek'
          AND m.model_name IN ('deepseek-v4-flash', 'deepseek-v4-pro')
          AND vm.time_period IN ('peak', 'off_peak')
          AND vm.raw_token_threshold IS NULL
        """
    ))
    logger.info("[Migration] 已回滚官方 deepseek 峰谷档位")

    # 2. 移除 time_period 字段
    col_exists = conn.execute(text(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vendor_model' "
        "AND COLUMN_NAME = 'time_period'"
    )).fetchone()
    if col_exists and int(col_exists[0]) > 0:
        conn.execute(text("ALTER TABLE `vendor_model` DROP COLUMN `time_period`"))
        logger.info("[Migration] 已移除 vendor_model.time_period 字段")
