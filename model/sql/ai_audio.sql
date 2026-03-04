-- AI 音频表
-- AI Audio Table
-- 用于存储 AI 生成的音频信息
CREATE TABLE IF NOT EXISTS `ai_audio` (
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