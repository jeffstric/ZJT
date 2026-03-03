-- MySQL dump 10.13  Distrib 8.0.45, for Linux (x86_64)
--
-- Host: localhost    Database: voice_replace_debug2
-- ------------------------------------------------------
-- Server version	8.0.45-0ubuntu0.22.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

CREATE DATABASE IF NOT EXISTS zjt DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

use zjt;


--
-- Table structure for table `ai_audio`
--

DROP TABLE IF EXISTS `ai_audio`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_audio` (
  `id` int NOT NULL AUTO_INCREMENT,
  `text` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '生成文本',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `ref_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '样板音频',
  `emo_ref_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '情感样板音频',
  `transaction_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '交易id',
  `result_url` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '结果地址',
  `user_id` int DEFAULT NULL COMMENT '用户id',
  `emo_text` varchar(255) DEFAULT NULL COMMENT '情感描述文本',
  `emo_weight` double DEFAULT NULL COMMENT '情感权重',
  `emo_vec` varchar(255) DEFAULT NULL COMMENT '情感向量控制',
  `emo_control_method` tinyint DEFAULT NULL COMMENT '情感控制方式: 0-与音色参考音频相同, 1-使用情感参考音频, 2-使用情感向量控制, 3-使用情感描述文本控制',
  `status` tinyint DEFAULT NULL COMMENT '状态: 0-未处理, 1-正在处理, -1-处理失败, 2-处理完成',
  `message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '错误信息',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ai_tools`
--

DROP TABLE IF EXISTS `ai_tools`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_tools` (
  `id` int NOT NULL AUTO_INCREMENT,
  `prompt` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '提示词',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `image_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '图片路径',
  `duration` tinyint DEFAULT NULL COMMENT '时长',
  `ratio` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '视频模式（9:16, 16:9, 1:1 ,3:4, 4:3）',
  `project_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '任务id',
  `transaction_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '交易id',
  `result_url` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '结果地址',
  `user_id` int DEFAULT NULL COMMENT '用户id',
  `type` tinyint DEFAULT NULL COMMENT '类型（1-图片编辑，2-ai视频生成，3-图片生成视频，4-图片高清）',
  `status` tinyint DEFAULT NULL COMMENT '状态: 0-未处理, 1-正在处理, -1-处理失败, 2-处理完成',
  `message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '错误信息',
  `image_size` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '图片尺寸（1k,2k.4k）',
  `completed_time` datetime DEFAULT NULL COMMENT '完成时间',
  `extra_config` text COMMENT '额外配置（JSON格式）',
  PRIMARY KEY (`id`),
  KEY `idx_user_id_type_create_time` (`user_id`,`type`,`create_time`),
  KEY `idx_user_id_create_time` (`user_id`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `alembic_version`
--

DROP TABLE IF EXISTS `alembic_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

-- 插入 alembic 基线版本号（初始迁移版本，后续迁移会自动执行）
INSERT INTO `alembic_version` (`version_num`) VALUES ('69f38f419eb6');

--
-- Table structure for table `character`
--

DROP TABLE IF EXISTS `character`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `character` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `world_id` int unsigned NOT NULL COMMENT '所属世界ID',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '角色姓名',
  `age` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '年龄',
  `identity` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '身份/职业',
  `appearance` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '外貌描述',
  `personality` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '性格特征',
  `behavior` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '行为习惯',
  `other_info` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '其他信息',
  `reference_image` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '参考图片地址',
  `default_voice` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '默认声音文件路径',
  `emotion_voices` json DEFAULT NULL COMMENT '感情色彩声音(JSON格式)',
  `sora_character` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sora角色卡任务ID',
  `user_id` int unsigned NOT NULL COMMENT '创建者用户ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_world_id` (`world_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_name` (`name`),
  KEY `idx_create_time` (`create_time`),
  CONSTRAINT `fk_character_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `location`
--

DROP TABLE IF EXISTS `location`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `location` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `world_id` int unsigned NOT NULL COMMENT '所属世界ID',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '地点名称',
  `parent_id` int unsigned DEFAULT NULL COMMENT '父级地点ID',
  `reference_image` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '参考图片',
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '地点描述',
  `user_id` int unsigned NOT NULL COMMENT '创建者用户ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_world_id` (`world_id`),
  KEY `idx_parent_id` (`parent_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_name` (`name`),
  KEY `idx_create_time` (`create_time`),
  CONSTRAINT `fk_location_parent` FOREIGN KEY (`parent_id`) REFERENCES `location` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_location_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='场景地点表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `payment_orders`
--

DROP TABLE IF EXISTS `payment_orders`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `payment_orders` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` varchar(64) NOT NULL COMMENT '商户订单号',
  `user_id` int NOT NULL COMMENT '用户ID',
  `package_id` int NOT NULL COMMENT '套餐ID',
  `computing_power` int NOT NULL COMMENT '算力值',
  `price` decimal(10,2) NOT NULL COMMENT '支付金额',
  `platform` varchar(16) NOT NULL DEFAULT 'wechat' COMMENT '支付平台',
  `payment_type` varchar(16) NOT NULL COMMENT '支付类型',
  `status` tinyint NOT NULL DEFAULT '0' COMMENT '订单状态',
  `transaction_id` varchar(64) DEFAULT NULL COMMENT '微信支付交易号',
  `paid_at` datetime DEFAULT NULL COMMENT '支付时间',
  `created_at` datetime NOT NULL COMMENT '创建时间',
  `updated_at` datetime NOT NULL COMMENT '更新时间',
  `payment_ip` varchar(50) DEFAULT NULL COMMENT '支付IP地址',
  `note` text COMMENT '备注信息',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_id` (`order_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_platform` (`platform`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='支付订单表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `props`
--

DROP TABLE IF EXISTS `props`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `props` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `world_id` int unsigned NOT NULL COMMENT '所属世界ID',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '道具名称',
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '道具描述',
  `reference_image` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '参考图片',
  `other_info` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '其他信息',
  `user_id` int unsigned NOT NULL COMMENT '创建者用户ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_world_id` (`world_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_name` (`name`),
  KEY `idx_create_time` (`create_time`),
  CONSTRAINT `fk_props_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='道具表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `runninghub_slots`
--

DROP TABLE IF EXISTS `runninghub_slots`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `runninghub_slots` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `task_id` int unsigned NOT NULL COMMENT 'tasks表的task_id (ai_tools.id)',
  `task_table_id` int unsigned NOT NULL COMMENT 'tasks表的主键id',
  `project_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'RunningHub项目ID（提交后才有）',
  `task_type` tinyint NOT NULL COMMENT '任务类型(10-LTX2.0, 11-Wan2.2)',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态: 1-槽位占用中, 2-已释放',
  `acquired_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '槽位获取时间',
  `released_at` datetime DEFAULT NULL COMMENT '槽位释放时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_table_id` (`task_table_id`),
  KEY `idx_status_task_type` (`status`,`task_type`),
  KEY `idx_task_id` (`task_id`),
  KEY `idx_project_id` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RunningHub并发槽位管理表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `script`
--

DROP TABLE IF EXISTS `script`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `script` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `world_id` int unsigned NOT NULL COMMENT '所属世界ID',
  `user_id` int unsigned NOT NULL COMMENT '创建者用户ID',
  `title` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '剧本标题',
  `episode_number` int DEFAULT NULL COMMENT '计划第几集',
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '剧本内容',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_world_id` (`world_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_episode_number` (`episode_number`),
  KEY `idx_create_time` (`create_time`),
  CONSTRAINT `fk_script_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `tasks`
--

DROP TABLE IF EXISTS `tasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tasks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `task_type` varchar(50) NOT NULL COMMENT '任务类型',
  `task_id` int NOT NULL COMMENT '任务ID',
  `try_count` int DEFAULT '0' COMMENT '失败尝试次数',
  `next_trigger` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '下一次执行时间',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
  `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中，1-处理中，2-处理完成，-1-处理失败）',
  PRIMARY KEY (`id`),
  KEY `idx_tasks_task_id` (`task_id`),
  KEY `idx_tasks_task_type` (`task_type`,`status`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='任务表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `video_workflow`
--

DROP TABLE IF EXISTS `video_workflow`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `video_workflow` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '工作流名称',
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '工作流描述',
  `cover_image` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '封面图片URL',
  `user_id` int unsigned NOT NULL COMMENT '创建者用户ID',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态: 0-禁用, 1-启用, 2-草稿',
  `workflow_data` json DEFAULT NULL COMMENT '工作流配置数据(JSON格式)',
  `style` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '画风',
  `style_reference_image` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '画风参考图URL',
  `default_world_id` int unsigned DEFAULT NULL COMMENT '默认世界ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_status` (`status`),
  KEY `idx_create_time` (`create_time`),
  KEY `idx_default_world_id` (`default_world_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='视频工作流表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `world`
--

DROP TABLE IF EXISTS `world`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `world` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '世界名称',
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '世界描述',
  `story_outline` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '故事大纲',
  `visual_style` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '画面风格',
  `era_environment` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '时代环境',
  `color_language` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '色彩语言',
  `composition_preference` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '构图倾向',
  `user_id` int unsigned NOT NULL COMMENT '创建者用户ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='世界表';


DROP TABLE IF EXISTS `computing_power`;
CREATE TABLE `computing_power`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `user_id` int(0) NOT NULL,
  `computing_power` int(0) NOT NULL DEFAULT 0,
  `expiration_time` datetime(0) NULL DEFAULT NULL,
  `created_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` datetime(0) NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP(0),
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `user_id`(`user_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for computing_power_log
-- ----------------------------
DROP TABLE IF EXISTS `computing_power_log`;
CREATE TABLE `computing_power_log`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `computing_power` int(0) NULL DEFAULT NULL,
  `behavior` enum('increase','deduct') CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  `user_id` int(0) NOT NULL,
  `created_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `note` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `transaction_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `from` int(0) NULL DEFAULT NULL,
  `to` int(0) NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_user_created`(`user_id`, `created_at`) USING BTREE,
  INDEX `idx_behavior_created`(`behavior`, `created_at`) USING BTREE,
  INDEX `idx_user_behavior_note`(`user_id`, `behavior`, `note`(100)) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for login_logs
-- ----------------------------
DROP TABLE IF EXISTS `login_logs`;
CREATE TABLE `login_logs`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `user_id` int(0) NOT NULL,
  `login_time` datetime(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  `ip_address` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `user_agent` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `status` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `user_id`(`user_id`) USING BTREE,
  CONSTRAINT `login_logs_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for token_history
-- ----------------------------
DROP TABLE IF EXISTS `token_history`;
CREATE TABLE `token_history`  (
  `id` bigint(0) NOT NULL,
  `user_tokens_id` int(0) NULL DEFAULT NULL,
  `user_token` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `created_at` timestamp(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `time_index` int(0) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_created_at`(`created_at`) USING BTREE,
  INDEX `idx_user_tokens_id`(`user_tokens_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for token_log
-- ----------------------------
DROP TABLE IF EXISTS `token_log`;
CREATE TABLE `token_log`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `input_token` int(0) NULL DEFAULT NULL COMMENT '输入token',
  `output_token` int(0) NULL DEFAULT NULL COMMENT '输出token',
  `cache_read` int(0) NULL DEFAULT NULL COMMENT '缓存读取',
  `cache_creation` int(0) NULL DEFAULT NULL COMMENT '缓存创建',
  `vendor_id` int(0) NULL DEFAULT NULL COMMENT '供应商id',
  `model_id` int(0) NULL DEFAULT NULL COMMENT '模型id',
  `user_id` int(0) NOT NULL COMMENT '用户id',
  `created_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `note` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `status` tinyint(0) NULL DEFAULT 0 COMMENT '状态（0-未扣除，1-已处理）',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_token_log_status_created`(`status`, `created_at`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for uncalculated_token
-- ----------------------------
DROP TABLE IF EXISTS `uncalculated_token`;
CREATE TABLE `uncalculated_token`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `user_id` int(0) NOT NULL COMMENT '用户id',
  `uncalculated_input_token` int(0) NULL DEFAULT NULL COMMENT '未计算输入token',
  `uncalculated_output_token` int(0) NULL DEFAULT NULL COMMENT '未计算输出token',
  `uncalculated_cache_read` int(0) NULL DEFAULT NULL COMMENT '未计算缓存读取',
  `created_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `user_id`(`user_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '未计算token表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for user_tokens
-- ----------------------------
DROP TABLE IF EXISTS `user_tokens`;
CREATE TABLE `user_tokens`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `user_id` int(0) NOT NULL,
  `token` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `created_at` timestamp(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `expire_time` timestamp(0) NOT NULL,
  `device_uuid` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `idx_token`(`token`) USING BTREE,
  INDEX `idx_user_id`(`user_id`) USING BTREE,
  INDEX `idx_expire_time`(`expire_time`) USING BTREE,
  INDEX `idx_device_uuid`(`device_uuid`) USING BTREE,
  CONSTRAINT `user_tokens_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `phone` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` tinyint(0) NOT NULL DEFAULT 1 COMMENT '用户状态：1-正常，0-禁用',
  `created_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0) ON UPDATE CURRENT_TIMESTAMP(0),
  `serial_number` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '序列号',
  `secret_key` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `role` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '角色',
  `terms_agreed` tinyint(0) NOT NULL DEFAULT 0 COMMENT '同意条款（0-不同意，1-同意）',
  `invite_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '邀请码',
  `inviter_id` int(0) NULL DEFAULT NULL COMMENT '邀请人id',
  `first_recharge` tinyint(0) NULL DEFAULT 0 COMMENT '是否首次充值',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `idx_phone`(`phone`) USING BTREE,
  UNIQUE INDEX `idx_serial_number`(`serial_number`) USING BTREE,
  INDEX `invite_code`(`invite_code`) USING BTREE,
  INDEX `inviter_id`(`inviter_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for model
-- ----------------------------
DROP TABLE IF EXISTS `model`;
CREATE TABLE `model`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `model_name` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '模型名称',
  `created_at` datetime(0) NULL DEFAULT NULL,
  `note` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '其他信息',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '模型表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of model
-- ----------------------------
INSERT INTO `model` VALUES (1, 'gemini-3-flash-preview', '2026-01-22 14:14:32', NULL);
INSERT INTO `model` VALUES (2, 'gemini-3-pro-preview', '2026-01-22 14:14:34', NULL);

-- ----------------------------
-- Table structure for vendor
-- ----------------------------
DROP TABLE IF EXISTS `vendor`;
CREATE TABLE `vendor`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `vendor_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '供应商名称',
  `created_at` datetime(0) NULL DEFAULT NULL,
  `note` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '其他信息',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '供应商表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of vendor
-- ----------------------------
INSERT INTO `vendor` VALUES (1, 'jiekou', '2026-01-22 14:11:28', NULL);

-- ----------------------------
-- Table structure for vendor_model
-- ----------------------------
DROP TABLE IF EXISTS `vendor_model`;
CREATE TABLE `vendor_model`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `vendor_id` int(0) NULL DEFAULT NULL COMMENT '供应商id',
  `model_id` int(0) NULL DEFAULT NULL COMMENT '模型id',
  `created_at` datetime(0) NULL DEFAULT NULL,
  `input_token_threshold` int(0) NULL DEFAULT NULL COMMENT '输入token阈值',
  `out_token_threshold` int(0) NULL DEFAULT NULL COMMENT '输出token阈值',
  `cache_read_threshold` int(0) NULL DEFAULT NULL COMMENT '缓存读取阈值',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `vendor_id_model_id`(`vendor_id`, `model_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of vendor_model
-- ----------------------------
INSERT INTO `vendor_model` VALUES (1, 1, 1, '2026-01-22 14:16:46', 11000, 1800, 112000);
INSERT INTO `vendor_model` VALUES (2, 1, 2, '2026-01-22 14:16:49', 1500, 340, 15000);

-- ----------------------------
-- Table structure for verify_codes
-- ----------------------------
DROP TABLE IF EXISTS `verify_codes`;
CREATE TABLE `verify_codes`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `phone` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `code` varchar(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `type` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `created_at` timestamp(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `expire_time` timestamp(0) NOT NULL,
  `used` tinyint(1) NULL DEFAULT 0,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_phone_type`(`phone`, `type`) USING BTREE,
  INDEX `idx_expire_time`(`expire_time`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;

/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-02-24 11:17:21
