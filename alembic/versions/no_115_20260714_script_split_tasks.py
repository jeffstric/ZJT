"""Create script_split_task/segment tables and add storyboard_scene split source fields

Revision ID: 20260714_script_split
Revises: 20260713_scene_audio_embed
Create Date: 2026-07-14

支持剧本分段拆分与断点续传（见 docs/script/script_parser_incremental_split_design.md）：
1. 新建 script_split_task：根任务表，承载分段计划、进度、租约(worker_id/lease_until)和最终结果。
2. 新建 script_split_segment：分段检查点表，每段一条，段成功后立即持久化。
3. storyboard_scene 增加 script_split_task_id + source_shot_key 及唯一索引，
   保证故事板发布中断恢复时的幂等去重。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# 注意：revision 字符串长度必须 ≤ 32 字符（alembic_version.version_num 为 varchar(32)）
revision: str = '20260714_script_split'
down_revision: Union[str, None] = '20260713_scene_audio_embed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def _index_exists(conn, table: str, index: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
    ), {"table": table})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()

    # ---- 1. script_split_task ----
    if not _table_exists(conn, "script_split_task"):
        conn.execute(text("""
            CREATE TABLE `script_split_task` (
                `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                `user_id` INT UNSIGNED NOT NULL COMMENT '创建人',
                `source_type` VARCHAR(32) NOT NULL COMMENT '来源 video_workflow/storyboard/cli',
                `source_id` INT UNSIGNED DEFAULT NULL COMMENT '来源 id（workflow id / storyboard id）',
                `source_node_key` VARCHAR(128) DEFAULT NULL COMMENT '视频工作流节点 key（恢复用）',
                `active_key` VARCHAR(128) DEFAULT NULL COMMENT '幂等键(user+source+sha256+config)；终态置 NULL',
                `script_sha256` VARCHAR(64) NOT NULL COMMENT '剧本内容 sha256',
                `script_content` MEDIUMTEXT NOT NULL COMMENT '原始剧本全文',
                `request_config` JSON DEFAULT NULL COMMENT '拆分请求参数(model/language/world_id 等)',
                `status` VARCHAR(32) NOT NULL DEFAULT 'queued' COMMENT '任务状态，见 ScriptSplitConstants',
                `phase` VARCHAR(64) DEFAULT NULL COMMENT '当前阶段细分（segment_generation 等）',
                `progress` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '进度 0-100',
                `plan_revision` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '语义再分段版本，上界 PLAN_MAX_REVISIONS',
                `segment_plan_json` JSON DEFAULT NULL COMMENT '阶段一分段计划(锚点+segments)',
                `current_segment_index` INT UNSIGNED DEFAULT NULL COMMENT '当前处理段序号(1-based)',
                `total_segment_count` INT UNSIGNED DEFAULT NULL COMMENT '总段数',
                `completed_segment_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已完成段数',
                `accepted_registry_json` JSON DEFAULT NULL COMMENT '已接受的全局资产注册表(characters/locations/props/spatial_world)',
                `continuity_state_json` JSON DEFAULT NULL COMMENT '上一段结束时的空间连续性状态',
                `final_result_json` JSON DEFAULT NULL COMMENT '合并后的最终 parsed_data',
                `last_error_code` VARCHAR(64) DEFAULT NULL COMMENT '最近错误码',
                `last_error_message` TEXT DEFAULT NULL COMMENT '最近错误信息',
                `auth_token` VARCHAR(512) DEFAULT NULL COMMENT '用户 token(记费用)，不输出到日志/响应',
                `cancel_requested` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '协作式取消标记',
                `worker_id` VARCHAR(64) DEFAULT NULL COMMENT '领取的 worker(hostname-pid)',
                `lease_until` DATETIME DEFAULT NULL COMMENT '租约到期时间，过期可被回收',
                `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                `completed_at` DATETIME DEFAULT NULL COMMENT '进入终态时间',
                UNIQUE KEY `uk_script_split_active_key` (`active_key`),
                INDEX `idx_script_split_user` (`user_id`),
                INDEX `idx_script_split_source` (`source_type`, `source_id`),
                INDEX `idx_script_split_status_lease` (`status`, `lease_until`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本分段拆分根任务表';
        """))
        logger.info("[Migration] Created table script_split_task")
    else:
        logger.info("[Migration] script_split_task 已存在，跳过")

    # ---- 2. script_split_segment ----
    if not _table_exists(conn, "script_split_segment"):
        conn.execute(text("""
            CREATE TABLE `script_split_segment` (
                `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                `task_id` INT UNSIGNED NOT NULL COMMENT '所属根任务 id',
                `segment_index` INT UNSIGNED NOT NULL COMMENT '段序号(1-based)，与原文顺序一致',
                `segment_id` VARCHAR(64) NOT NULL COMMENT '模型规划的 segment_id（如 seg_0003）',
                `source_block_ids` JSON NOT NULL COMMENT '本段覆盖的锚点 block_id 列表',
                `source_content` MEDIUMTEXT NOT NULL COMMENT '本段对应原文（拼接的 block content）',
                `source_sha256` VARCHAR(64) NOT NULL COMMENT '本段原文 sha256',
                `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'pending/generating/completed/failed',
                `attempt_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '同边界重试次数（上界 SEGMENT_MAX_RETRIES）',
                `raw_response` LONGTEXT DEFAULT NULL COMMENT '模型原始响应（调试用）',
                `parsed_result_json` JSON DEFAULT NULL COMMENT '通过校验后的段级 parsed_data',
                `validation_errors` JSON DEFAULT NULL COMMENT '失败时的结构化错误列表',
                `continuity_in_json` JSON DEFAULT NULL COMMENT '本段开始时的空间连续性状态',
                `continuity_out_json` JSON DEFAULT NULL COMMENT '本段结束时的空间连续性状态',
                `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                `completed_at` DATETIME DEFAULT NULL COMMENT '段完成时间',
                UNIQUE KEY `uk_script_split_seg_index` (`task_id`, `segment_index`),
                UNIQUE KEY `uk_script_split_seg_id` (`task_id`, `segment_id`),
                INDEX `idx_script_split_seg_status` (`task_id`, `status`),
                FOREIGN KEY (`task_id`) REFERENCES `script_split_task`(`id`) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本分段拆分检查点表';
        """))
        logger.info("[Migration] Created table script_split_segment")
    else:
        logger.info("[Migration] script_split_segment 已存在，跳过")

    # ---- 3. storyboard_scene 幂等字段 ----
    if not _column_exists(conn, "storyboard_scene", "script_split_task_id"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "ADD COLUMN `script_split_task_id` BIGINT UNSIGNED DEFAULT NULL "
            "COMMENT '剧本分段拆分任务 id（发布幂等，NULL=非拆分来源）' AFTER `last_modified_user_id`"
        ))
        logger.info("[Migration] Added column storyboard_scene.script_split_task_id")
    else:
        logger.info("[Migration] storyboard_scene.script_split_task_id 已存在，跳过")

    if not _column_exists(conn, "storyboard_scene", "source_shot_key"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "ADD COLUMN `source_shot_key` VARCHAR(128) DEFAULT NULL "
            "COMMENT '拆分任务内稳定 shot 标识（发布幂等去重）' AFTER `script_split_task_id`"
        ))
        logger.info("[Migration] Added column storyboard_scene.source_shot_key")
    else:
        logger.info("[Migration] storyboard_scene.source_shot_key 已存在，跳过")

    # 唯一索引保证发布重试不重复创建 scene。
    # MySQL 允许多个 NULL（非拆分来源的 scene 两字段均为 NULL，互不冲突）。
    if not _index_exists(conn, "storyboard_scene", "uk_storyboard_scene_split_source"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "ADD UNIQUE KEY `uk_storyboard_scene_split_source` "
            "(`script_split_task_id`, `source_shot_key`)"
        ))
        logger.info("[Migration] Added unique index uk_storyboard_scene_split_source")
    else:
        logger.info("[Migration] uk_storyboard_scene_split_source 已存在，跳过")


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(conn, "storyboard_scene", "uk_storyboard_scene_split_source"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "DROP INDEX `uk_storyboard_scene_split_source`"
        ))
        logger.info("[Migration] Dropped index uk_storyboard_scene_split_source")

    if _column_exists(conn, "storyboard_scene", "source_shot_key"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` DROP COLUMN `source_shot_key`"
        ))
        logger.info("[Migration] Dropped column storyboard_scene.source_shot_key")

    if _column_exists(conn, "storyboard_scene", "script_split_task_id"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` DROP COLUMN `script_split_task_id`"
        ))
        logger.info("[Migration] Dropped column storyboard_scene.script_split_task_id")

    if _table_exists(conn, "script_split_segment"):
        conn.execute(text("DROP TABLE IF EXISTS `script_split_segment`"))
        logger.info("[Migration] Dropped table script_split_segment")

    if _table_exists(conn, "script_split_task"):
        conn.execute(text("DROP TABLE IF EXISTS `script_split_task`"))
        logger.info("[Migration] Dropped table script_split_task")
