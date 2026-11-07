"""aigc explicit opt out log

Revision ID: 20261108_aigc_explicit_opt_out_l
Revises: 20261104_uk_power_log_txn
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261108_aigc_explicit_opt_out_l'
down_revision: Union[str, None] = '20261104_uk_power_log_txn'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 AIGC 显式标识关闭申请留痕表（标识办法第9条，留存 >= 6 个月）"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `aigc_explicit_opt_out_log` (
            `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
            `user_id` INT DEFAULT NULL COMMENT '申请用户ID（第9条：提供对象信息留痕）',
            `ai_tool_id` BIGINT DEFAULT NULL COMMENT '关联任务ID（ai_tools.id）',
            `produce_id` VARCHAR(128) DEFAULT NULL COMMENT '内容编号（隐式标识 ProduceID）',
            `content_type` VARCHAR(32) DEFAULT NULL COMMENT '内容类型 video/image/audio',
            `request_source` VARCHAR(64) DEFAULT NULL COMMENT '申请来源（chat_result_card/compose_default/api）',
            `ip` VARCHAR(64) DEFAULT NULL COMMENT '申请时客户端IP',
            `user_agent` VARCHAR(512) DEFAULT NULL COMMENT '申请时 User-Agent',
            `detail` TEXT DEFAULT NULL COMMENT '扩展信息 JSON',
            `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            PRIMARY KEY (`id`),
            KEY `idx_aigc_optout_user` (`user_id`),
            KEY `idx_aigc_optout_ai_tool` (`ai_tool_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AIGC显式标识关闭申请留痕（标识办法第9条，留存>=6个月）'
    """)
    logger.info("[Migration] created table aigc_explicit_opt_out_log")


def downgrade() -> None:
    """回滚：删除留痕表"""
    op.execute("DROP TABLE IF EXISTS `aigc_explicit_opt_out_log`")
    logger.info("[Migration] dropped table aigc_explicit_opt_out_log")
