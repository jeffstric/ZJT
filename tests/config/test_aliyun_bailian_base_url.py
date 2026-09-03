"""
normalize_aliyun_bailian_base_url 单元测试

覆盖：空值回退、存量带 /compatible-mode/v1 后缀的旧值剥离、
尾部带 / 与不带 /、两者叠加，分别验证大模型与多媒体两种模式。
"""
import unittest

from config.config_util import normalize_aliyun_bailian_base_url


class TestNormalizeAliyunBailianBaseUrlForLlm(unittest.TestCase):
    """for_llm=True：基础 URL + /compatible-mode/v1"""

    def test_empty_falls_back_to_default(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url(None, for_llm=True),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )
        self.assertEqual(
            normalize_aliyun_bailian_base_url('', for_llm=True),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )
        self.assertEqual(
            normalize_aliyun_bailian_base_url('   ', for_llm=True),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )

    def test_plain_base_url(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url('https://dashscope.aliyuncs.com', for_llm=True),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )

    def test_trailing_slash(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url('https://dashscope.aliyuncs.com/', for_llm=True),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )

    def test_legacy_value_with_suffix(self):
        """存量数据库中已带 /compatible-mode/v1 的旧值应保持幂等"""
        self.assertEqual(
            normalize_aliyun_bailian_base_url(
                'https://dashscope.aliyuncs.com/compatible-mode/v1', for_llm=True
            ),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )

    def test_legacy_value_with_suffix_and_trailing_slash(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url(
                'https://dashscope.aliyuncs.com/compatible-mode/v1/', for_llm=True
            ),
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )

    def test_custom_proxy_base_url(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url('https://proxy.example.com/', for_llm=True),
            'https://proxy.example.com/compatible-mode/v1',
        )


class TestNormalizeAliyunBailianBaseUrlForMedia(unittest.TestCase):
    """for_llm=False：基础 URL + /api/v1（DashScope 原生多媒体接口）"""

    def test_empty_falls_back_to_default(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url(None, for_llm=False),
            'https://dashscope.aliyuncs.com/api/v1',
        )

    def test_plain_base_url(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url('https://dashscope.aliyuncs.com', for_llm=False),
            'https://dashscope.aliyuncs.com/api/v1',
        )

    def test_trailing_slash(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url('https://dashscope.aliyuncs.com/', for_llm=False),
            'https://dashscope.aliyuncs.com/api/v1',
        )

    def test_legacy_value_with_suffix(self):
        """带 /compatible-mode/v1 的旧值用于多媒体时应剥离后再拼 /api/v1"""
        self.assertEqual(
            normalize_aliyun_bailian_base_url(
                'https://dashscope.aliyuncs.com/compatible-mode/v1', for_llm=False
            ),
            'https://dashscope.aliyuncs.com/api/v1',
        )

    def test_legacy_value_with_suffix_and_trailing_slash(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url(
                'https://dashscope.aliyuncs.com/compatible-mode/v1/', for_llm=False
            ),
            'https://dashscope.aliyuncs.com/api/v1',
        )

    def test_custom_proxy_base_url(self):
        self.assertEqual(
            normalize_aliyun_bailian_base_url('https://proxy.example.com/', for_llm=False),
            'https://proxy.example.com/api/v1',
        )


if __name__ == '__main__':
    unittest.main()
