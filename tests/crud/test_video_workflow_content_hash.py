"""
compute_content_hash 单元测试（无数据库依赖）。

服务端权威内容哈希是上传去重门与 PUT CAS（X-Base-Hash）的基础：
- 同一库存内容任意时刻计算结果必须稳定（MySQL json 列会做存储规范化，
  因此哈希必须对解析后的 Python 对象做规范化序列化计算）；
- 内容（含 PUT 可写的 style/default_world_id/workflow_ratio 等标量字段）
  任一变化都必须改变哈希。
"""
import unittest

from model.video_workflow import (
    VideoWorkflow, compute_content_hash, content_hashes_for_cas,
)


class TestComputeContentHash(unittest.TestCase):

    def test_dict_and_str_workflow_data_same_hash(self):
        """workflow_data 无论是 dict 还是 JSON 字符串，解析后哈希一致"""
        wd = {'b': 1, 'a': {'y': [1, 2], 'x': '中文'}}
        wf_dict = VideoWorkflow(workflow_data=wd)
        wf_str = VideoWorkflow(workflow_data='{"a": {"x": "中文", "y": [1, 2]}, "b": 1}')
        self.assertEqual(compute_content_hash(wf_dict), compute_content_hash(wf_str))

    def test_key_order_insensitive(self):
        """MySQL json 列会规范化 key 顺序，哈希须对 key 顺序不敏感"""
        wf1 = VideoWorkflow(workflow_data={'x': 1, 'y': 2})
        wf2 = VideoWorkflow(workflow_data={'y': 2, 'x': 1})
        self.assertEqual(compute_content_hash(wf1), compute_content_hash(wf2))

    def test_stable_across_calls(self):
        wf = VideoWorkflow(workflow_data={'nodes': [{'id': 1}]}, style='写实')
        self.assertEqual(compute_content_hash(wf), compute_content_hash(wf))

    def test_content_change_changes_hash(self):
        base = dict(workflow_data={'nodes': [{'id': 1}]}, style='写实',
                    default_world_id=7, workflow_ratio='16:9')
        h = compute_content_hash(VideoWorkflow(**base))
        variants = [
            dict(base, workflow_data={'nodes': [{'id': 2}]}),
            dict(base, style='动漫'),
            dict(base, style_reference_image='https://x/ref.png'),
            dict(base, default_world_id=8),
            dict(base, workflow_ratio='9:16'),
        ]
        for v in variants:
            self.assertNotEqual(h, compute_content_hash(VideoWorkflow(**v)), msg=str(v))

    def test_none_and_broken_workflow_data(self):
        """新建空工作流 / 损坏 JSON 不抛异常且可区分"""
        h_none = compute_content_hash(VideoWorkflow(workflow_data=None))
        h_broken = compute_content_hash(VideoWorkflow(workflow_data='{broken'))
        h_empty = compute_content_hash(VideoWorkflow(workflow_data={}))
        self.assertTrue(h_none and h_broken and h_empty)
        self.assertNotEqual(h_none, h_empty)

    def test_none_scalar_fields_distinguished_from_values(self):
        """default_world_id None 与具体值的哈希不同（None 序列化为 'None'）"""
        h1 = compute_content_hash(VideoWorkflow(workflow_data={}, default_world_id=None))
        h2 = compute_content_hash(VideoWorkflow(workflow_data={}, default_world_id=1))
        self.assertNotEqual(h1, h2)

    def test_pre_parsed_workflow_data_same_hash(self):
        """调用方传入已解析 dict 与自行从 str 解析结果一致（避免大 JSON 二次解析的优化不得改口径）"""
        wd = {'nodes': [{'id': 1, 'pos': {'x': 0.5}}], 'version': 'v2'}
        wf_str = VideoWorkflow(workflow_data='{"version": "v2", "nodes": [{"id": 1, "pos": {"x": 0.5}}]}',
                               style='写实', workflow_ratio='16:9')
        self.assertEqual(compute_content_hash(wf_str), compute_content_hash(wf_str, wd))

    def test_pre_parsed_none_falls_back_to_workflow_field(self):
        """workflow_data=None 缺省时从 workflow.workflow_data 取值（向后兼容）"""
        wf = VideoWorkflow(workflow_data={'a': 1})
        self.assertEqual(compute_content_hash(wf), compute_content_hash(wf, None))

    def test_viewport_excluded_from_hash(self):
        """viewport（panX/panY/zoom）是各端本地视图状态，不参与内容哈希：
        不同用户缩放/平移不同，参与会导致「内容没变仅视角不同」也互相 CAS 409"""
        h1 = compute_content_hash(VideoWorkflow(
            workflow_data={'nodes': [{'id': 1}], 'viewport': {'panX': 0, 'panY': 0, 'zoom': 1}}))
        h2 = compute_content_hash(VideoWorkflow(
            workflow_data={'nodes': [{'id': 1}], 'viewport': {'panX': 120.5, 'panY': -30, 'zoom': 0.8}}))
        h3 = compute_content_hash(VideoWorkflow(
            workflow_data={'nodes': [{'id': 1}]}))
        self.assertEqual(h1, h2)
        self.assertEqual(h1, h3)

    def test_non_viewport_change_still_changes_hash(self):
        """剔除 viewport 不得影响其他字段的敏感性"""
        base = {'nodes': [{'id': 1}], 'viewport': {'zoom': 1}}
        h = compute_content_hash(VideoWorkflow(workflow_data=base))
        changed = compute_content_hash(VideoWorkflow(
            workflow_data={'nodes': [{'id': 2}], 'viewport': {'zoom': 1}}))
        self.assertNotEqual(h, changed)


class TestContentHashesForCas(unittest.TestCase):
    """基线过期时：合成后哈希不变 → 不当 409；内容变了 → 仍冲突。"""

    def test_same_content_partial_put_incoming_equals_current(self):
        wf = VideoWorkflow(
            workflow_data={'nodes': [{'id': 1}]},
            style='写实',
            default_world_id=7,
            workflow_ratio='16:9',
        )
        current, incoming = content_hashes_for_cas(wf, {'style': '写实'})
        self.assertEqual(current, incoming)
        current2, incoming2 = content_hashes_for_cas(wf, {'default_world_id': 7})
        self.assertEqual(current2, incoming2)

    def test_viewport_only_change_incoming_equals_current(self):
        wf = VideoWorkflow(
            workflow_data={'nodes': [{'id': 1}], 'viewport': {'panX': 0, 'zoom': 1}})
        current, incoming = content_hashes_for_cas(wf, {
            'workflow_data': {'nodes': [{'id': 1}], 'viewport': {'panX': 80, 'zoom': 0.5}},
        })
        self.assertEqual(current, incoming)

    def test_real_content_change_incoming_differs(self):
        wf = VideoWorkflow(workflow_data={'nodes': [{'id': 1}]}, style='写实')
        current, incoming = content_hashes_for_cas(wf, {'style': '动漫'})
        self.assertNotEqual(current, incoming)
        current2, incoming2 = content_hashes_for_cas(wf, {
            'workflow_data': {'nodes': [{'id': 2}]},
        })
        self.assertNotEqual(current2, incoming2)

    def test_empty_update_fields_incoming_equals_current(self):
        wf = VideoWorkflow(workflow_data={'a': 1}, style='写实')
        current, incoming = content_hashes_for_cas(wf, {})
        self.assertEqual(current, incoming)
        current2, incoming2 = content_hashes_for_cas(wf, None)
        self.assertEqual(current2, incoming2)


if __name__ == '__main__':
    unittest.main()
