-- 修改角色表字段：合并职业和身份，添加行为习惯和其他信息字段
-- 执行时间：2025-12-24 15:07

-- 删除occupation字段
ALTER TABLE `character` DROP COLUMN `occupation`;

-- 修改identity字段的注释，使其表示身份/职业
ALTER TABLE `character` MODIFY COLUMN `identity` VARCHAR(100) COMMENT '身份/职业';

-- 添加行为习惯字段
ALTER TABLE `character` ADD COLUMN `behavior` TEXT COMMENT '行为习惯' AFTER `personality`;

-- 添加其他信息字段
ALTER TABLE `character` ADD COLUMN `other_info` TEXT COMMENT '其他信息' AFTER `behavior`;
