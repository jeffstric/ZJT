"""add compose jobs

新建 compose_jobs 表：数字人分段生成的纯编排器。
每段仍是标准 ai_tools(type=35) + tasks(generate_video)，独立计费/退费；
compose_jobs 只持有有序段 id 列表、编排状态与最终拼接结果，不碰计费。

Revision ID: 20261021_add_compose_jobs
Revises: 20261021_add_script_extract_task
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261021_add_compose_jobs'
down_revision: Union[str, None] = '20261021_add_script_extract_task'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建 compose_jobs 表（幂等）。"""
    conn = op.get_bind()
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `compose_jobs` (
          `id` int NOT NULL AUTO_INCREMENT,
          `user_id` int NOT NULL COMMENT '用户 ID',
          `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-待拼接 1-拼接中 2-完成 -1-失败',
          `segment_ai_tool_ids` text COMMENT '有序段 ai_tools.id JSON 数组',
          `params` text COMMENT '编排参数快照：prompt/ratio/max_edge 等 JSON',
          `result_url` text COMMENT '拼接后的成片地址',
          `media_mapping_id` int DEFAULT NULL COMMENT 'media_file_mapping.id（CDN）',
          `concat_attempts` tinyint NOT NULL DEFAULT 0 COMMENT '连续拼接失败次数（确定性失败快速熔断）',
          `message` varchar(500) DEFAULT NULL COMMENT '状态说明 / 失败原因',
          `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`id`),
          KEY `idx_user_status_create` (`user_id`,`status`,`create_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数字人分段拼接编排任务表'
    """))
    logger.info("[Migration] Created table compose_jobs")


def downgrade() -> None:
    """回滚：删除 compose_jobs 表。"""
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS `compose_jobs`"))
    logger.info("[Migration] Dropped table compose_jobs")
