# -*- coding: utf-8 -*-
"""
火山引擎 HMAC-SHA256 V4 签名器单元测试

纯计算无副作用：固定时间与参数锁定签名实现（签名细节需与火山官方
联调校准，本测试防止实现被误改）。已知向量验证思路：
- 同一输入签名确定性一致
- 不同 body / 不同时间 → 不同签名
- Authorization 头与 X-Date 格式断言
"""
import unittest
from datetime import datetime, timezone

from utils.volcengine_signer import sign_request

_AK = "AK_TEST_123"
_SK = "SK_TEST_456"
_REGION = "cn-beijing"
_SERVICE = "ark"
_FIXED_NOW = datetime(2026, 10, 26, 8, 30, 0, tzinfo=timezone.utc)


def _sign(body=b'{"Name": "g1"}', now=_FIXED_NOW, path="/v1/api/assets/",
          query=None, headers=None, method="POST"):
    return sign_request(
        method=method,
        host="ark.cn-beijing.volces.com",
        path=path,
        query=query if query is not None else {"Action": "CreateAssetGroup", "Version": "2024-01-01"},
        headers=headers if headers is not None else {"Content-Type": "application/json"},
        body=body,
        access_key=_AK,
        secret_key=_SK,
        region=_REGION,
        service=_SERVICE,
        now=now,
    )


class TestSignRequest(unittest.TestCase):
    """签名输出结构与确定性"""

    def test_deterministic(self):
        """固定时间/参数：两次签名完全一致"""
        self.assertEqual(_sign(), _sign())

    def test_authorization_format(self):
        """Authorization 头：算法 + Credential scope + SignedHeaders + 64 位十六进制签名"""
        result = _sign()
        auth = result["Authorization"]
        self.assertTrue(auth.startswith("HMAC-SHA256 Credential=AK_TEST_123/"))
        self.assertIn("/20261026/cn-beijing/ark/request", auth)
        self.assertIn("SignedHeaders=content-type;host;x-date", auth)
        signature = auth.rsplit("Signature=", 1)[1]
        self.assertEqual(len(signature), 64)
        self.assertEqual(signature, signature.lower())  # 纯十六进制小写

    def test_x_date_format(self):
        result = _sign()
        self.assertEqual(result["X-Date"], "20261026T083000Z")

    def test_different_body_differs(self):
        self.assertNotEqual(
            _sign(body=b'{"Name": "g1"}')["Authorization"],
            _sign(body=b'{"Name": "g2"}')["Authorization"],
        )

    def test_different_time_differs(self):
        other_time = datetime(2026, 10, 27, 8, 30, 0, tzinfo=timezone.utc)
        self.assertNotEqual(
            _sign()["Authorization"],
            _sign(now=other_time)["Authorization"],
        )

    def test_different_secret_key_differs(self):
        result_a = _sign()
        result_b = sign_request(
            method="POST",
            host="ark.cn-beijing.volces.com",
            path="/v1/api/assets/",
            query={"Action": "CreateAssetGroup", "Version": "2024-01-01"},
            headers={"Content-Type": "application/json"},
            body=b'{"Name": "g1"}',
            access_key=_AK,
            secret_key="SK_OTHER",
            region=_REGION,
            service=_SERVICE,
            now=_FIXED_NOW,
        )
        self.assertNotEqual(result_a["Authorization"], result_b["Authorization"])

    def test_empty_body_signable(self):
        """空请求体（如 ListAssetGroups 无参查询）可正常签名"""
        result = _sign(body=b"")
        self.assertIn("Signature=", result["Authorization"])

    def test_query_sorted_in_canonical(self):
        """查询串按参数名字典序进入规范请求（Action/Version 乱序传入不影响）"""
        ordered = _sign(query={"Action": "GetAsset", "Version": "2024-01-01"})
        shuffled = _sign(query={"Version": "2024-01-01", "Action": "GetAsset"})
        self.assertEqual(ordered, shuffled)

    def test_missing_credentials_raise(self):
        with self.assertRaises(ValueError):
            sign_request(
                method="POST", host="h", path="/", query=None,
                headers={}, body=b"", access_key="", secret_key=_SK,
                region=_REGION, service=_SERVICE, now=_FIXED_NOW,
            )
        with self.assertRaises(ValueError):
            sign_request(
                method="POST", host="h", path="/", query=None,
                headers={}, body=b"", access_key=_AK, secret_key="",
                region=_REGION, service=_SERVICE, now=_FIXED_NOW,
            )


if __name__ == '__main__':
    unittest.main()
