-- 道具表
-- Props Table
-- 用于存储道具信息
CREATE TABLE IF NOT EXISTS `props` (
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