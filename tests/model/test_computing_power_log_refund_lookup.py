"""ComputingPowerLogModel 批量查询失败退回流水。"""
import unittest
from unittest.mock import patch

from model.computing_power_log import ComputingPowerLogModel


class TestGetIncreaseLogsByTransactionIds(unittest.TestCase):
    def test_empty_ids_returns_empty(self):
        self.assertEqual(
            ComputingPowerLogModel.get_increase_logs_by_transaction_ids(1, []),
            {},
        )

    @patch("model.computing_power_log.execute_query")
    def test_maps_rows(self, mock_query):
        mock_query.return_value = [
            {"transaction_id": "refund-abc", "computing_power": 16},
            {"transaction_id": "refund-def", "computing_power": None},
        ]
        result = ComputingPowerLogModel.get_increase_logs_by_transaction_ids(
            9, ["refund-abc", "refund-def"]
        )
        self.assertEqual(
            result["refund-abc"],
            {"transaction_id": "refund-abc", "computing_power": 16},
        )
        self.assertEqual(result["refund-def"]["computing_power"], 0)
        sql = mock_query.call_args[0][0]
        self.assertIn("IN (%s, %s)", sql.replace("\n", " "))
        self.assertEqual(mock_query.call_args[0][1], (9, "refund-abc", "refund-def"))


if __name__ == "__main__":
    unittest.main()
