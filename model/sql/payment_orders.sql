-- 支付订单表
-- Payment Orders Table
-- 用于存储支付订单信息
CREATE TABLE IF NOT EXISTS `payment_orders` (
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