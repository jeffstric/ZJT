"""月度订阅（微信委托代扣）：新建签约关系表 wx_papay_contracts 与订阅订单表 subscription_orders

Revision ID: 20260909_wx_papay_subscription
Revises: 20260911_character_source_field
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260911_wx_papay_subscription'
down_revision: Union[str, None] = '20260911_character_source_field'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建月度订阅两张表：微信委托代扣签约关系表 + 订阅订单表"""
    conn = op.get_bind()

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `wx_papay_contracts` (
          `id` int NOT NULL AUTO_INCREMENT,
          `contract_code` varchar(64) NOT NULL COMMENT '商户侧签约协议号(唯一)',
          `contract_id` varchar(64) DEFAULT NULL COMMENT '微信委托代扣协议ID(签约成功后回填)',
          `plan_template_id` varchar(64) NOT NULL COMMENT '微信商户平台协议模板ID',
          `user_id` int NOT NULL COMMENT '用户ID',
          `openid` varchar(128) DEFAULT NULL COMMENT '签约用户openid',
          `subscription_plan_id` int NOT NULL COMMENT '本地订阅套餐ID',
          `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-签约中 1-已签约 2-已解约',
          `request_serial` bigint DEFAULT NULL COMMENT '签约请求序列号',
          `signed_at` datetime DEFAULT NULL COMMENT '签约成功时间',
          `terminated_at` datetime DEFAULT NULL COMMENT '解约时间',
          `termination_mode` tinyint DEFAULT NULL COMMENT '解约方式 2-用户 3-商户API 4-商户平台 5-注销 7-客服',
          `termination_remark` varchar(512) DEFAULT NULL COMMENT '解约原因备注',
          `current_period_start` datetime DEFAULT NULL COMMENT '当前周期开始(本期扣款成功时间)',
          `current_period_end` datetime DEFAULT NULL COMMENT '当前周期结束(会员有效期至)',
          `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
          `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_contract_code` (`contract_code`),
          KEY `idx_contract_id` (`contract_id`),
          KEY `idx_user_status` (`user_id`,`status`),
          KEY `idx_status_period_end` (`status`,`current_period_end`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='微信委托代扣签约关系表(月度订阅)'
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `subscription_orders` (
          `id` int NOT NULL AUTO_INCREMENT,
          `order_id` varchar(64) NOT NULL COMMENT '商户订单号(SUB_前缀)',
          `contract_code` varchar(64) NOT NULL COMMENT '关联签约协议号',
          `user_id` int NOT NULL COMMENT '用户ID',
          `subscription_plan_id` int NOT NULL COMMENT '本地订阅套餐ID',
          `period_index` int NOT NULL DEFAULT 1 COMMENT '第几期(1=首期签约支付)',
          `amount` decimal(10,2) NOT NULL COMMENT '本期扣款金额(元)',
          `computing_power` int NOT NULL COMMENT '本期发放算力',
          `period_start` datetime DEFAULT NULL COMMENT '本期覆盖周期开始(上一期结束日)',
          `period_end` datetime DEFAULT NULL COMMENT '本期覆盖周期结束',
          `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-待支付/待扣款 1-已支付 2-扣款失败 3-已关闭 4-已受理待确认',
          `transaction_id` varchar(64) DEFAULT NULL COMMENT '微信支付订单号',
          `err_code` varchar(64) DEFAULT NULL COMMENT '最近一次失败错误码',
          `err_msg` varchar(255) DEFAULT NULL COMMENT '最近一次失败描述',
          `prenotify_sent_at` datetime DEFAULT NULL COMMENT '预扣费通知下发时间',
          `next_retry_at` datetime DEFAULT NULL COMMENT '下次扣款重试时间',
          `retry_count` int NOT NULL DEFAULT 0 COMMENT '已重试次数',
          `paid_at` datetime DEFAULT NULL COMMENT '支付完成时间',
          `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
          `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_order_id` (`order_id`),
          KEY `idx_contract_period` (`contract_code`,`period_index`),
          KEY `idx_user_id` (`user_id`),
          KEY `idx_status_retry` (`status`,`next_retry_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='月度订阅订单表(每周期一条)'
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS `subscription_orders`"))
    conn.execute(text("DROP TABLE IF EXISTS `wx_papay_contracts`"))
