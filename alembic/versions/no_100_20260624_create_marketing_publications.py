"""Create marketing publications table

Revision ID: 20260624_marketing_publications
Revises: 20260618_seed_img_mask
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260624_marketing_publications'
down_revision: Union[str, None] = '20260618_seed_img_mask'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS `marketing_publications` (
          `id` int NOT NULL AUTO_INCREMENT,
          `ai_tool_id` int NOT NULL COMMENT '关联 ai_tools.id',
          `owner_user_id` int NOT NULL COMMENT '发布用户ID',
          `media_type` varchar(20) NOT NULL COMMENT 'image/video',
          `title` varchar(255) NOT NULL COMMENT '公开标题',
          `description` text DEFAULT NULL COMMENT '公开描述',
          `tags_json` text DEFAULT NULL COMMENT '标签 JSON',
          `result_url` text DEFAULT NULL COMMENT '长期结果文件 URL',
          `cover_url` text DEFAULT NULL COMMENT '长期封面 URL',
          `prompt_snapshot` text DEFAULT NULL COMMENT '发布时提示词快照',
          `params_snapshot_json` mediumtext DEFAULT NULL COMMENT '做同款参数快照 JSON',
          `status` varchar(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected/hidden/cancelled',
          `reviewer_user_id` int DEFAULT NULL COMMENT '审核管理员ID',
          `review_note` text DEFAULT NULL COMMENT '审核备注',
          `submitted_at` datetime DEFAULT NULL,
          `reviewed_at` datetime DEFAULT NULL,
          `published_at` datetime DEFAULT NULL,
          `like_count` int NOT NULL DEFAULT 0,
          `remix_count` int NOT NULL DEFAULT 0,
          `sort_weight` int NOT NULL DEFAULT 0,
          `created_at` datetime DEFAULT NULL,
          `updated_at` datetime DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `idx_ai_tool_id` (`ai_tool_id`),
          KEY `idx_owner_status` (`owner_user_id`,`status`,`created_at`),
          KEY `idx_public_feed` (`status`,`media_type`,`sort_weight`,`published_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    logger.info("[Migration] Created marketing_publications table")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `marketing_publications`")
    logger.info("[Migration] Dropped marketing_publications table")
