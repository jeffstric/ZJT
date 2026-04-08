"""create location_multi_angle_tasks table

Revision ID: 20260407_000000
Revises: 20260402_multi_ref
Create Date: 2026-04-07

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260407_000000'
down_revision = '20260402_multi_ref'
branch_labels = None
depends_on = None


def upgrade():
    """创建 location_multi_angle_tasks 表"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `location_multi_angle_tasks` (
          `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
          `task_key` varchar(255) NOT NULL COMMENT '任务唯一键',
          `location_name` varchar(255) NOT NULL COMMENT '场景名称',
          `user_id` varchar(50) NOT NULL COMMENT '用户ID',
          `world_id` varchar(50) NOT NULL COMMENT '世界观ID',
          `main_image` varchar(1000) NOT NULL COMMENT '主参考图URL',
          `description` varchar(2000) DEFAULT NULL COMMENT '场景描述',
          `angles` json NOT NULL COMMENT '需要生成的角度列表',
          `model` varchar(100) DEFAULT NULL COMMENT '使用的模型',
          `auth_token` varchar(500) DEFAULT NULL COMMENT '认证令牌',
          `ai_tool_task_id` int DEFAULT NULL COMMENT '关联的AI工具任务ID',
          `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中, 1-处理中, 2-完成, -1-失败）',
          `current_angle_index` int DEFAULT '0' COMMENT '当前处理的视角索引',
          `generated_images` json DEFAULT NULL COMMENT '已生成的图片列表',
          `error_message` text COMMENT '错误信息',
          `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
          `failed_at` datetime DEFAULT NULL COMMENT '失败时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_task_key` (`task_key`),
          KEY `idx_status` (`status`),
          KEY `idx_user_world` (`user_id`, `world_id`),
          KEY `idx_created_at` (`created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='场景多角度生图任务表'
    """)


def downgrade():
    """删除 location_multi_angle_tasks 表"""
    op.execute("DROP TABLE IF EXISTS `location_multi_angle_tasks`")
