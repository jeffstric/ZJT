"""create_agent_tasks_and_messages_tables

Revision ID: 20260406_agent_tasks
Revises: 20260401_add_api_token_idx
Create Date: 2026-04-06 11:00:00.000000+08:00

Create agent_tasks and agent_task_messages tables for cross-process task sharing
Supports gunicorn multi-worker mode by storing tasks and SSE messages in database
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260406_agent_tasks'
down_revision: Union[str, None] = '20260401_add_api_token_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent_tasks and agent_task_messages tables"""
    # Create agent_tasks table
    op.execute("""
        CREATE TABLE `agent_tasks` (
          `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Primary key',
          `task_id` VARCHAR(64) NOT NULL COMMENT 'UUID task identifier',
          `session_id` VARCHAR(64) NOT NULL COMMENT 'Associated session ID',
          `user_id` VARCHAR(64) NOT NULL COMMENT 'User ID',
          `world_id` VARCHAR(64) NOT NULL COMMENT 'World ID',
          `user_message` LONGTEXT COMMENT 'User message content',
          `auth_token` VARCHAR(512) DEFAULT NULL COMMENT 'Authentication token',
          `vendor_id` INT DEFAULT NULL COMMENT 'Vendor ID',
          `model_id` INT DEFAULT NULL COMMENT 'Model ID',
          `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'Task status: pending/running/waiting_human/completed/failed/cancelled',
          `progress` FLOAT NOT NULL DEFAULT 0 COMMENT 'Task progress 0-1',
          `current_step` VARCHAR(255) DEFAULT '' COMMENT 'Current step description',
          `result` LONGTEXT DEFAULT NULL COMMENT 'Task result (JSON)',
          `error` TEXT DEFAULT NULL COMMENT 'Error message if failed',
          `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Task creation time',
          `started_at` DATETIME DEFAULT NULL COMMENT 'Task start time',
          `completed_at` DATETIME DEFAULT NULL COMMENT 'Task completion time',
          UNIQUE KEY `uk_task_id` (`task_id`),
          KEY `idx_session_id` (`session_id`),
          KEY `idx_user_world` (`user_id`, `world_id`),
          KEY `idx_status` (`status`),
          KEY `idx_created_at` (`created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent tasks for cross-process sharing'
    """)
    print("[Migration] Created agent_tasks table")

    # Create agent_task_messages table
    op.execute("""
        CREATE TABLE `agent_task_messages` (
          `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Primary key, used for ordering',
          `task_id` VARCHAR(64) NOT NULL COMMENT 'Associated task ID',
          `message_type` VARCHAR(32) NOT NULL DEFAULT 'message' COMMENT 'Message type: message/progress/done/error/status/heartbeat/connected',
          `content` LONGTEXT NOT NULL COMMENT 'Message content (JSON)',
          `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Message creation time',
          KEY `idx_task_id` (`task_id`),
          KEY `idx_task_id_id` (`task_id`, `id`),
          KEY `idx_created_at` (`created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent task messages for SSE streaming'
    """)
    print("[Migration] Created agent_task_messages table")


def downgrade() -> None:
    """Drop agent_tasks and agent_task_messages tables"""
    op.execute("DROP TABLE IF EXISTS `agent_task_messages`")
    print("[Migration] Dropped agent_task_messages table")

    op.execute("DROP TABLE IF EXISTS `agent_tasks`")
    print("[Migration] Dropped agent_tasks table")
