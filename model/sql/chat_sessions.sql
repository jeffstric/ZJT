-- 聊天会话表
-- 用于支持多 worker 进程间会话共享
CREATE TABLE IF NOT EXISTS `chat_sessions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Primary key',
  `session_id` VARCHAR(36) NOT NULL COMMENT 'UUID session identifier',
  `user_id` VARCHAR(50) NOT NULL COMMENT 'User ID',
  `world_id` VARCHAR(50) NOT NULL COMMENT 'World ID',
  `auth_token` VARCHAR(500) DEFAULT NULL COMMENT 'Authentication token',
  `model` VARCHAR(100) NOT NULL DEFAULT 'gemini-3-flash-preview' COMMENT 'AI model name',
  `model_id` INT DEFAULT NULL COMMENT 'Model ID from vendor',
  `conversation_history` LONGTEXT NOT NULL COMMENT 'Serialized conversation history (JSON array)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Session creation time',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update time',
  `expires_at` DATETIME DEFAULT NULL COMMENT 'Session expiration time (NULL = never expires)',
  `total_input_tokens` INT NOT NULL DEFAULT 0 COMMENT 'Total input tokens used',
  `total_output_tokens` INT NOT NULL DEFAULT 0 COMMENT 'Total output tokens used',
  `total_cache_creation_tokens` INT NOT NULL DEFAULT 0 COMMENT 'Total cache creation tokens',
  `total_cache_read_tokens` INT NOT NULL DEFAULT 0 COMMENT 'Total cache read tokens',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Whether session is active (1=active, 0=inactive)',
  UNIQUE KEY `uk_session_id` (`session_id`),
  KEY `idx_user_world` (`user_id`, `world_id`),
  KEY `idx_expires_at` (`expires_at`),
  KEY `idx_updated_at` (`updated_at`),
  KEY `idx_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Chat session storage for multi-worker process support';
