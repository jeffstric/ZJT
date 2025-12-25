-- 修复 ai_tools 表的索引顺序
-- 将 create_time 字段从索引的第一位移到最后一位，提高查询效率
-- 
-- 原索引: idx_create_time_user_id_type (create_time, user_id, type)
-- 新索引: idx_user_id_type_create_time (user_id, type, create_time)
--
-- 优化原因：
-- 1. user_id 是等值查询条件，选择性高，应该放在最前面
-- 2. type 是过滤条件，放在中间
-- 3. create_time 用于排序，放在最后
-- 这样可以更好地支持 WHERE user_id = ? AND type = ? ORDER BY create_time DESC 的查询

-- 删除旧的索引
-- 注意：原索引名称包含反引号，需要使用正确的语法删除
ALTER TABLE `ai_tools` DROP INDEX ```create_time``, ``user_id``, ``type```;

-- 创建新的索引，将 create_time 放在最后
ALTER TABLE `ai_tools` ADD INDEX `idx_user_id_type_create_time` (`user_id`, `type`, `create_time`);

-- 添加额外的索引以支持其他查询模式
-- 支持只按 user_id 查询的场景
ALTER TABLE `ai_tools` ADD INDEX `idx_user_id_create_time` (`user_id`, `create_time`);
