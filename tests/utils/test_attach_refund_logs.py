"""扣减日志配对失败退回流水。"""
import unittest

from utils.computing_power import (
    REFUND_TXN_PREFIX,
    attach_refund_to_deduct_logs,
    collect_refund_txn_ids_for_deduct_logs,
)


class TestCollectRefundTxnIds(unittest.TestCase):
    def test_collects_refund_keys_for_deduct(self):
        logs = [
            {"behavior": "deduct", "transaction_id": "abc-123"},
            {"behavior": "increase", "transaction_id": "refund-abc-123"},
        ]
        self.assertEqual(
            collect_refund_txn_ids_for_deduct_logs(logs),
            [f"{REFUND_TXN_PREFIX}abc-123"],
        )

    def test_skips_refund_and_diff_rows(self):
        logs = [
            {"behavior": "deduct", "transaction_id": "refund-already"},
            {"behavior": "increase", "transaction_id": "diff-refund-x"},
            {"behavior": "deduct", "transaction_id": "diff-charge-y"},
            {"behavior": "deduct", "transaction_id": None},
        ]
        self.assertEqual(collect_refund_txn_ids_for_deduct_logs(logs), [])

    def test_dedupes(self):
        logs = [
            {"behavior": "deduct", "transaction_id": "same"},
            {"behavior": "deduct", "transaction_id": "same"},
        ]
        self.assertEqual(
            collect_refund_txn_ids_for_deduct_logs(logs),
            [f"{REFUND_TXN_PREFIX}same"],
        )


class TestAttachRefundToDeductLogs(unittest.TestCase):
    def test_attaches_matching_refund(self):
        logs = [
            {"behavior": "deduct", "transaction_id": "abc-123", "computing_power": 16},
            {"behavior": "increase", "transaction_id": "refund-abc-123", "computing_power": 16},
        ]
        refund_map = {
            "refund-abc-123": {"transaction_id": "refund-abc-123", "computing_power": 16},
        }
        attach_refund_to_deduct_logs(logs, refund_map)
        self.assertEqual(
            logs[0]["refund"],
            {"transaction_id": "refund-abc-123", "computing_power": 16},
        )
        self.assertNotIn("refund", logs[1])

    def test_no_map_leaves_logs(self):
        logs = [{"behavior": "deduct", "transaction_id": "abc-123"}]
        attach_refund_to_deduct_logs(logs, {})
        self.assertNotIn("refund", logs[0])

    def test_does_not_attach_to_refund_row(self):
        logs = [{"behavior": "deduct", "transaction_id": "refund-abc-123"}]
        refund_map = {
            "refund-refund-abc-123": {"transaction_id": "refund-refund-abc-123", "computing_power": 1},
            "refund-abc-123": {"transaction_id": "refund-abc-123", "computing_power": 16},
        }
        attach_refund_to_deduct_logs(logs, refund_map)
        self.assertNotIn("refund", logs[0])


if __name__ == "__main__":
    unittest.main()
