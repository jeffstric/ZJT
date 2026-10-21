"""add script extract task

新建 script_extract_task 表：剧本提取节点（video_workflow）的异步任务状态
从内存注册表迁移到数据库，修复 gunicorn 多 worker 部署下任务状态 404
（POST 与轮询 GET 落到不同进程导致内存注册表不一致）以及服务重启任务失联。

Revision ID: 20261021_add_script_extract_task
Revises: 20261016_fix_preset_voice_type_n
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261021_add_script_extract_task'
down_revision: Union[str, None] = '20261016_fix_preset_voice_type_n'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建 script_extract_task 表（幂等）。"""
    conn = op.get_bind()
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `script_extract_task` (
          `task_id` varchar(64) NOT NULL COMMENT '任务ID（uuid hex）',
          `user_id` int NOT NULL COMMENT '用户 ID',
          `status` varchar(20) NOT NULL DEFAULT 'running' COMMENT '任务状态：running/success/failed',
          `stage` varchar(20) NOT NULL DEFAULT 'frames' COMMENT '当前阶段：frames/audio/asr/llm/done',
          `progress` json DEFAULT NULL COMMENT '进度明细（如 ASR 分段完成数）',
          `error` text COMMENT '错误信息',
          `result` json DEFAULT NULL COMMENT '提取结果（剧本 + 元信息）',
          `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`task_id`),
          KEY `idx_user_status` (`user_id`, `status`),
          KEY `idx_updated_at` (`updated_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本提取任务表（跨进程共享状态）'
    """))
    logger.info("[Migration] Created table script_extract_task")


def downgrade() -> None:
    """回滚：删除 script_extract_task 表。"""
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS `script_extract_task`"))
    logger.info("[Migration] Dropped table script_extract_task")
