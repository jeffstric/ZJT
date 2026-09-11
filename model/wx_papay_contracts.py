"""
WxPapayContracts Model - 微信委托代扣签约关系表（月度订阅）
一个用户同一时间只允许一条生效中的签约记录
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

from config.constant import WxContractStatus

logger = logging.getLogger(__name__)


class WxPapayContract:
    """委托代扣签约关系实体"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.contract_code = kwargs.get('contract_code')
        self.contract_id = kwargs.get('contract_id')
        self.plan_template_id = kwargs.get('plan_template_id')
        self.user_id = kwargs.get('user_id')
        self.openid = kwargs.get('openid')
        self.subscription_plan_id = kwargs.get('subscription_plan_id')
        self.status = kwargs.get('status', WxContractStatus.PENDING)
        self.request_serial = kwargs.get('request_serial')
        self.signed_at = kwargs.get('signed_at')
        self.terminated_at = kwargs.get('terminated_at')
        self.termination_mode = kwargs.get('termination_mode')
        self.termination_remark = kwargs.get('termination_remark')
        self.current_period_start = kwargs.get('current_period_start')
        self.current_period_end = kwargs.get('current_period_end')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'contract_code': self.contract_code,
            'contract_id': self.contract_id,
            'user_id': self.user_id,
            'openid': self.openid,
            'subscription_plan_id': self.subscription_plan_id,
            'status': self.status,
            'signed_at': self.signed_at.isoformat() if self.signed_at else None,
            'terminated_at': self.terminated_at.isoformat() if self.terminated_at else None,
            'termination_mode': self.termination_mode,
            'termination_remark': self.termination_remark,
            'current_period_start': self.current_period_start.isoformat() if self.current_period_start else None,
            'current_period_end': self.current_period_end.isoformat() if self.current_period_end else None,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }


class WxPapayContractsModel:
    """委托代扣签约关系数据库操作"""

    @staticmethod
    def create(
        contract_code: str,
        user_id: int,
        subscription_plan_id: int,
        plan_template_id: str,
        request_serial: int,
        openid: Optional[str] = None,
        status: int = WxContractStatus.PENDING,
    ) -> int:
        """创建签约记录（支付中签约下发时，状态=签约中）"""
        sql = """
            INSERT INTO wx_papay_contracts
            (contract_code, contract_id, plan_template_id, user_id, openid,
             subscription_plan_id, status, request_serial, create_at, update_at)
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """
        try:
            record_id = execute_insert(sql, (
                contract_code, plan_template_id, user_id, openid,
                subscription_plan_id, status, request_serial,
            ))
            logger.info(f"Created papay contract: code={contract_code}, user={user_id}, record_id={record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create papay contract {contract_code}: {e}")
            raise

    @staticmethod
    def get_by_contract_code(contract_code: str) -> Optional[WxPapayContract]:
        sql = "SELECT * FROM wx_papay_contracts WHERE contract_code = %s"
        try:
            result = execute_query(sql, (contract_code,), fetch_one=True)
            return WxPapayContract(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get contract by code {contract_code}: {e}")
            raise

    @staticmethod
    def get_by_contract_id(contract_id: str) -> Optional[WxPapayContract]:
        sql = "SELECT * FROM wx_papay_contracts WHERE contract_id = %s"
        try:
            result = execute_query(sql, (contract_id,), fetch_one=True)
            return WxPapayContract(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get contract by wechat id {contract_id}: {e}")
            raise

    @staticmethod
    def get_active_by_user(user_id: int) -> Optional[WxPapayContract]:
        """取用户当前生效（签约中/已签约）的签约记录，无则 None"""
        sql = """
            SELECT * FROM wx_papay_contracts
            WHERE user_id = %s AND status IN (%s, %s)
            ORDER BY id DESC LIMIT 1
        """
        try:
            result = execute_query(sql, (
                user_id, WxContractStatus.PENDING, WxContractStatus.ACTIVE,
            ), fetch_one=True)
            return WxPapayContract(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get active contract for user {user_id}: {e}")
            raise

    @staticmethod
    def get_latest_by_user(user_id: int) -> Optional[WxPapayContract]:
        """取用户最近一条签约记录（任意状态，用于展示订阅状态）"""
        sql = "SELECT * FROM wx_papay_contracts WHERE user_id = %s ORDER BY id DESC LIMIT 1"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return WxPapayContract(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get latest contract for user {user_id}: {e}")
            raise

    @staticmethod
    def mark_signed(contract_code: str, contract_id: str, openid: Optional[str] = None) -> int:
        """签约成功回调：写入微信协议ID，状态置为已签约"""
        sql = """
            UPDATE wx_papay_contracts
            SET status = %s, contract_id = %s, signed_at = NOW(), update_at = NOW(),
                openid = COALESCE(%s, openid)
            WHERE contract_code = %s
        """
        try:
            affected = execute_update(sql, (
                WxContractStatus.ACTIVE, contract_id, openid, contract_code,
            ))
            logger.info(f"Contract {contract_code} signed as {contract_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to mark contract signed {contract_code}: {e}")
            raise

    @staticmethod
    def mark_terminated(
        contract_code: str,
        termination_mode: Optional[int] = None,
        termination_remark: Optional[str] = None,
    ) -> int:
        """解约（API确认或微信回调），幂等"""
        sql = """
            UPDATE wx_papay_contracts
            SET status = %s, terminated_at = NOW(),
                termination_mode = COALESCE(%s, termination_mode),
                termination_remark = COALESCE(%s, termination_remark),
                update_at = NOW()
            WHERE contract_code = %s AND status != %s
        """
        try:
            affected = execute_update(sql, (
                WxContractStatus.TERMINATED, termination_mode, termination_remark,
                contract_code, WxContractStatus.TERMINATED,
            ))
            logger.info(f"Contract {contract_code} terminated (mode={termination_mode})")
            return affected
        except Exception as e:
            logger.error(f"Failed to mark contract terminated {contract_code}: {e}")
            raise

    @staticmethod
    def update_period(contract_code: str, period_start: 'datetime', period_end: 'datetime') -> int:
        """扣款成功后更新当前周期（会员有效期）"""
        sql = """
            UPDATE wx_papay_contracts
            SET current_period_start = %s, current_period_end = %s, update_at = NOW()
            WHERE contract_code = %s
        """
        try:
            return execute_update(sql, (period_start, period_end, contract_code))
        except Exception as e:
            logger.error(f"Failed to update period for {contract_code}: {e}")
            raise

    @staticmethod
    def get_renewal_due_contracts(lead_days: int) -> List[WxPapayContract]:
        """取需要处理续期的已签约合约：当前周期在提前量窗口内到期"""
        sql = """
            SELECT * FROM wx_papay_contracts
            WHERE status = %s
              AND current_period_end IS NOT NULL
              AND current_period_end > NOW()
              AND current_period_end <= DATE_ADD(NOW(), INTERVAL %s DAY)
            ORDER BY current_period_end ASC
        """
        try:
            results = execute_query(sql, (
                WxContractStatus.ACTIVE, lead_days,
            ), fetch_all=True)
            return [WxPapayContract(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get renewal due contracts: {e}")
            raise


CREATE_TABLE_SQL = """
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='微信委托代扣签约关系表(月度订阅)';
"""
