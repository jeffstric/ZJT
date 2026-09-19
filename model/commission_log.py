"""
CommissionLog Model - Database operations for commission_log table
邀请佣金明细表（用户佣金账本，单一数据源）

设计要点（纯账本式）：
- 不维护聚合余额字段，所有余额/金额由本表聚合得出，避免多进程并发覆盖。
- 每笔佣金一条记录，靠 transaction_id 唯一键保证抽佣幂等。
- status + withdraw_no 组合表达状态：
    status=0 AND withdraw_no IS NULL     -> 可用（可参与提现）
    status=0 AND withdraw_no IS NOT NULL -> 冻结中（已发起提现、待审核）
    status=1                              -> 已提现（已打款）
    status=2                              -> 已冲正（退款预留）
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_insert
import logging

logger = logging.getLogger(__name__)


def _mask_phone(phone) -> Optional[str]:
    """手机号脱敏（138****0000），用于佣金明细展示"""
    if not phone:
        return None
    p = str(phone)
    return p[:3] + '****' + p[-4:] if len(p) >= 7 else p


class CommissionLog:
    """CommissionLog model class - 邀请佣金明细（账本）"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.inviter_id = kwargs.get('inviter_id')
        self.invitee_id = kwargs.get('invitee_id')
        self.order_id = kwargs.get('order_id')
        self.transaction_id = kwargs.get('transaction_id')
        self.package_id = kwargs.get('package_id')
        self.order_amount = kwargs.get('order_amount')
        self.commission_rate = kwargs.get('commission_rate')
        self.commission_amount = kwargs.get('commission_amount')
        self.granted_computing_power = kwargs.get('granted_computing_power')
        self.withdraw_no = kwargs.get('withdraw_no')
        self.status = kwargs.get('status', 0)
        self.note = kwargs.get('note')
        self.create_at = kwargs.get('create_at')
        self.invitee_phone = kwargs.get('invitee_phone')  # JOIN users 得到（明细展示用）

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'inviter_id': self.inviter_id,
            'invitee_id': self.invitee_id,
            'order_id': self.order_id,
            'transaction_id': self.transaction_id,
            'package_id': self.package_id,
            'order_amount': float(self.order_amount) if self.order_amount is not None else None,
            'commission_rate': float(self.commission_rate) if self.commission_rate is not None else None,
            'commission_amount': float(self.commission_amount) if self.commission_amount is not None else None,
            'granted_computing_power': self.granted_computing_power,
            'withdraw_no': self.withdraw_no,
            'status': self.status,
            'note': self.note,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'invitee_phone': _mask_phone(self.invitee_phone),
        }


class CommissionLogModel:
    """CommissionLog database operations"""

    # status
    STATUS_AVAILABLE = 0   # 可用（未提现）
    STATUS_WITHDRAWN = 1   # 已提现
    STATUS_REVERSED = 2    # 已冲正（退款预留）

    @staticmethod
    def create(
        inviter_id: int,
        invitee_id: int,
        order_id: str,
        transaction_id: str,
        package_id: int,
        order_amount,
        commission_rate,
        commission_amount,
        granted_computing_power: int,
        note: Optional[str] = None
    ) -> int:
        """
        创建一条佣金明细（账本追加）

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO commission_log
            (inviter_id, invitee_id, order_id, transaction_id, package_id,
             order_amount, commission_rate, commission_amount, granted_computing_power,
             status, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            log_id = execute_insert(sql, (
                inviter_id, invitee_id, order_id, transaction_id, package_id,
                order_amount, commission_rate, commission_amount, granted_computing_power,
                CommissionLogModel.STATUS_AVAILABLE, note
            ))
            logger.info(
                f"Created commission log: inviter={inviter_id}, invitee={invitee_id}, "
                f"tx={transaction_id}, amount={commission_amount}"
            )
            return log_id
        except Exception as e:
            logger.error(f"Failed to create commission log (tx={transaction_id}): {e}")
            raise

    @staticmethod
    def check_transaction_exists(transaction_id: str) -> bool:
        """检查 transaction_id 是否已存在（抽佣幂等性检查）"""
        sql = "SELECT COUNT(*) as count FROM commission_log WHERE transaction_id = %s"
        try:
            result = execute_query(sql, (transaction_id,), fetch_one=True)
            return result['count'] > 0 if result else False
        except Exception as e:
            logger.error(f"Failed to check commission transaction exists: {e}")
            raise

    @staticmethod
    def get_by_transaction_id(transaction_id: str) -> Optional[CommissionLog]:
        """根据 transaction_id 获取佣金明细（幂等命中时回放 granted 用）"""
        sql = "SELECT * FROM commission_log WHERE transaction_id = %s"
        try:
            result = execute_query(sql, (transaction_id,), fetch_one=True)
            return CommissionLog(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get commission log by transaction_id {transaction_id}: {e}")
            raise

    # ---------------- 聚合查询（余额/金额由账本算出） ----------------

    @staticmethod
    def _sum(inviter_id: int, status_clause: str) -> float:
        sql = f"""
            SELECT COALESCE(SUM(commission_amount), 0) AS total
            FROM commission_log
            WHERE inviter_id = %s AND {status_clause}
        """
        try:
            result = execute_query(sql, (inviter_id,), fetch_one=True)
            return float(result['total']) if result else 0.0
        except Exception as e:
            logger.error(f"Failed to sum commission for inviter {inviter_id}: {e}")
            raise

    @staticmethod
    def sum_available(inviter_id: int) -> float:
        """可提现余额（status=0 且未关联提现单；订阅来源需满 30 天冻结期）"""
        return CommissionLogModel._sum(
            inviter_id,
            "status = 0 AND withdraw_no IS NULL "
            "AND (package_id < 100 OR create_at <= NOW() - INTERVAL 30 DAY)"
        )

    @staticmethod
    def sum_subscription_freezing(inviter_id: int) -> float:
        """月付（订阅）佣金冻结中：已产生但未满 30 天提现冻结期"""
        return CommissionLogModel._sum(
            inviter_id,
            "status = 0 AND withdraw_no IS NULL "
            "AND package_id >= 100 AND create_at > NOW() - INTERVAL 30 DAY"
        )

    @staticmethod
    def sum_frozen(inviter_id: int) -> float:
        """冻结中（status=0 且已关联提现单，待审核）"""
        return CommissionLogModel._sum(inviter_id, "status = 0 AND withdraw_no IS NOT NULL")

    @staticmethod
    def sum_withdrawn(inviter_id: int) -> float:
        """已提现（status=1）"""
        return CommissionLogModel._sum(inviter_id, "status = 1")

    @staticmethod
    def sum_total(inviter_id: int) -> float:
        """累计佣金（status IN (0,1)，不含冲正）"""
        return CommissionLogModel._sum(inviter_id, "status IN (0, 1)")

    @staticmethod
    def sum_by_withdraw_no(withdraw_no: str) -> float:
        """某提现单关联的佣金总额（提现单不存金额，由此聚合）"""
        sql = "SELECT COALESCE(SUM(commission_amount), 0) AS total FROM commission_log WHERE withdraw_no = %s"
        try:
            result = execute_query(sql, (withdraw_no,), fetch_one=True)
            return float(result['total']) if result else 0.0
        except Exception as e:
            logger.error(f"Failed to sum commission by withdraw_no {withdraw_no}: {e}")
            raise

    @staticmethod
    def list_by_inviter(inviter_id: int, limit: int = 20, offset: int = 0) -> List[CommissionLog]:
        """根据邀请人ID分页获取佣金明细（JOIN users 带出被邀请人手机号）"""
        sql = """
            SELECT cl.*, u.phone AS invitee_phone
            FROM commission_log cl
            LEFT JOIN users u ON cl.invitee_id = u.id
            WHERE cl.inviter_id = %s
            ORDER BY cl.create_at DESC
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (inviter_id, limit, offset), fetch_all=True)
            return [CommissionLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list commission logs for inviter {inviter_id}: {e}")
            raise

    @staticmethod
    def count_by_inviter(inviter_id: int) -> int:
        """统计邀请人的佣金明细总数"""
        sql = "SELECT COUNT(*) as count FROM commission_log WHERE inviter_id = %s"
        try:
            result = execute_query(sql, (inviter_id,), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count commission logs for inviter {inviter_id}: {e}")
            raise

    # ---------------- 提现流程（事务内操作，接收 conn） ----------------

    @staticmethod
    def lock_available_for_update(conn, inviter_id: int) -> List[Dict[str, Any]]:
        """
        在事务内锁定并返回该邀请人当前全部可用佣金记录（FOR UPDATE）。
        用于全额提现申请：锁住可用记录，串行化并发提现申请。
        """
        sql = """
            SELECT id, commission_amount FROM commission_log
            WHERE inviter_id = %s AND status = 0 AND withdraw_no IS NULL
              AND (package_id < 100 OR create_at <= NOW() - INTERVAL 30 DAY)
            ORDER BY id ASC
            FOR UPDATE
        """
        cursor = conn.cursor()
        cursor.execute(sql, (inviter_id,))
        return list(cursor.fetchall())

    @staticmethod
    def attach_withdraw(conn, ids: List[int], withdraw_no: str) -> int:
        """将一批可用记录关联到提现单（冻结：置 withdraw_no）"""
        if not ids:
            return 0
        placeholders = ','.join(['%s'] * len(ids))
        sql = f"""
            UPDATE commission_log SET withdraw_no = %s
            WHERE id IN ({placeholders}) AND status = 0 AND withdraw_no IS NULL
        """
        params = [withdraw_no] + list(ids)
        cursor = conn.cursor()
        return cursor.execute(sql, tuple(params))

    @staticmethod
    def confirm_withdrawn(conn, withdraw_no: str) -> int:
        """提现单审核通过：关联记录 status -> 1（已提现）"""
        sql = "UPDATE commission_log SET status = 1 WHERE withdraw_no = %s AND status = 0"
        cursor = conn.cursor()
        return cursor.execute(sql, (withdraw_no,))

    @staticmethod
    def release_withdraw(conn, withdraw_no: str) -> int:
        """提现单驳回：关联记录解冻（withdraw_no 置空，回到可用）"""
        sql = "UPDATE commission_log SET withdraw_no = NULL WHERE withdraw_no = %s AND status = 0"
        cursor = conn.cursor()
        return cursor.execute(sql, (withdraw_no,))


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `commission_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `inviter_id` int NOT NULL COMMENT '邀请人(佣金归属)ID',
  `invitee_id` int NOT NULL COMMENT '被邀请人(付款方)ID',
  `order_id` varchar(64) NOT NULL COMMENT '触发抽佣的订单号',
  `transaction_id` varchar(64) NOT NULL COMMENT '微信交易号(幂等键)',
  `package_id` int NOT NULL COMMENT '套餐ID',
  `order_amount` decimal(10,2) NOT NULL COMMENT '订单实付金额(元)',
  `commission_rate` decimal(5,4) NOT NULL COMMENT '本单抽佣比例快照',
  `commission_amount` decimal(10,2) NOT NULL COMMENT '本单佣金(元)',
  `granted_computing_power` int NOT NULL COMMENT '被邀请人到账算力(打折后)',
  `withdraw_no` varchar(64) DEFAULT NULL COMMENT '关联的提现单号；NULL=未提现',
  `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-可用(未提现) 1-已提现 2-已冲正',
  `note` varchar(500) DEFAULT NULL,
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_transaction_id` (`transaction_id`),
  KEY `idx_inviter_status` (`inviter_id`,`status`),
  KEY `idx_invitee` (`invitee_id`),
  KEY `idx_withdraw_no` (`withdraw_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='邀请佣金明细表(用户佣金账本)';
"""
