# -*- coding: utf-8 -*-
"""
SeedanceAssetClient 单元测试（Seedance 素材 Action 接口，供应商无关协议 + 按组工厂）
纯单元测试，不依赖数据库，mock requests.post 与动态配置
"""
import unittest
from unittest.mock import patch, MagicMock

import utils.seedance_asset_client as asset_client_mod
from utils.seedance_asset_client import (
    SeedanceAssetClient,
    SeedanceAssetError,
    create_seedance_asset_client,
    ASSET_STATUS_ACTIVE,
    ASSET_STATUS_FAILED,
    ASSET_STATUS_PROCESSING,
)


def _make_client(api_key='test_platform_token', base_url='https://asset.example.com'):
    """创建客户端实例（显式传参的纯协议构造）"""
    return SeedanceAssetClient(api_key=api_key, base_url=base_url)


def _mock_response(status_code=200, json_data=None, raise_json=False):
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data if json_data is not None else {}
    return resp


class TestClientInit(unittest.TestCase):
    """纯协议构造与工厂按组解析"""

    def test_explicit_params(self):
        client = _make_client()
        self.assertEqual(client.base_url, 'https://asset.example.com')
        self.assertEqual(client.api_key, 'test_platform_token')

    def test_base_url_trailing_slash_stripped(self):
        client = _make_client(base_url='https://example.com/')
        self.assertEqual(client.base_url, 'https://example.com')

    def test_missing_params_raise(self):
        with self.assertRaises(SeedanceAssetError):
            SeedanceAssetClient(api_key='', base_url='https://x')
        with self.assertRaises(SeedanceAssetError):
            SeedanceAssetClient(api_key='k', base_url='')

    @patch.object(asset_client_mod, 'get_dynamic_config_value')
    def test_factory_group_config_resolution(self, mock_config):
        """工厂按组解析：asset_base_url / asset_api_key 优先"""
        def side_effect(*keys, default=None):
            key_map = {
                ('gateway_a', 'asset_base_url'): 'https://asset.gateway-a.com',
                ('gateway_a', 'asset_api_key'): 'asset-token',
                ('gateway_a', 'base_url'): 'https://video.gateway-a.com',
                ('gateway_a', 'api_key'): 'video-token',
            }
            return key_map.get(keys, default)
        mock_config.side_effect = side_effect
        client = create_seedance_asset_client('gateway_a')
        self.assertEqual(client.base_url, 'https://asset.gateway-a.com')
        self.assertEqual(client.api_key, 'asset-token')

    @patch.object(asset_client_mod, 'get_dynamic_config_value')
    def test_factory_fallback_to_video_base_url_and_api_key(self, mock_config):
        """同址网关免配：未配 asset_* 时回落 base_url / api_key"""
        def side_effect(*keys, default=None):
            key_map = {
                ('gateway_b', 'base_url'): 'https://same-host.gateway-b.com',
                ('gateway_b', 'api_key'): 'sk-shared',
            }
            return key_map.get(keys, default)
        mock_config.side_effect = side_effect
        client = create_seedance_asset_client('gateway_b')
        self.assertEqual(client.base_url, 'https://same-host.gateway-b.com')
        self.assertEqual(client.api_key, 'sk-shared')

    @patch.object(asset_client_mod, 'get_dynamic_config_value')
    def test_factory_missing_base_url_raises(self, mock_config):
        mock_config.side_effect = lambda *keys, default=None: default
        with self.assertRaises(SeedanceAssetError) as ctx:
            create_seedance_asset_client('gateway_c')
        self.assertIn('asset_base_url', str(ctx.exception))

    @patch.object(asset_client_mod, 'get_dynamic_config_value')
    def test_factory_missing_api_key_raises(self, mock_config):
        def side_effect(*keys, default=None):
            if keys == ('gateway_d', 'base_url'):
                return 'https://gateway-d.com'
            return default
        mock_config.side_effect = side_effect
        with self.assertRaises(SeedanceAssetError) as ctx:
            create_seedance_asset_client('gateway_d')
        self.assertIn('Token', str(ctx.exception))


class TestCallAction(unittest.TestCase):
    """_call_action 请求构造与错误解析"""

    def setUp(self):
        self.client = _make_client()

    @patch.object(asset_client_mod.requests, 'post')
    def test_request_construction(self, mock_post):
        """请求构造：URL、query 参数、Bearer 头、大驼峰请求体"""
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {"RequestId": "req-1", "Action": "CreateAsset"},
            "Result": {"Id": "asset-1", "Status": "Processing"},
        })
        self.client.create_asset(
            url='https://example.com/cat.png', asset_type='Image', name='cat'
        )
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], 'https://asset.example.com/v1/api/assets/')
        self.assertEqual(kwargs['params'], {'Action': 'CreateAsset', 'Version': '2024-01-01'})
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test_platform_token')
        self.assertEqual(
            kwargs['json'],
            {'URL': 'https://example.com/cat.png', 'AssetType': 'Image', 'Name': 'cat'},
        )

    @patch.object(asset_client_mod.requests, 'post')
    def test_success_returns_result(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {"RequestId": "req-2"},
            "Result": {"Id": "asset-2", "Status": "Active"},
        })
        result = self.client.get_asset('asset-2')
        self.assertEqual(result, {"Id": "asset-2", "Status": "Active"})
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body, {"Id": "asset-2"})

    @patch.object(asset_client_mod.requests, 'post')
    def test_platform_envelope_error(self, mock_post):
        """平台信封错误：{code, message}"""
        mock_post.return_value = _mock_response(
            status_code=400, json_data={"code": 1, "message": "unsupported action"}
        )
        with self.assertRaises(SeedanceAssetError) as ctx:
            self.client.list_assets()
        self.assertEqual(ctx.exception.message, 'unsupported action')
        self.assertEqual(ctx.exception.http_status, 400)

    @patch.object(asset_client_mod.requests, 'post')
    def test_official_not_found_error(self, mock_post):
        """官方错误结构：ResponseMetadata.Error（含 RequestId）"""
        mock_post.return_value = _mock_response(
            status_code=404,
            json_data={
                "ResponseMetadata": {
                    "RequestId": "req-404",
                    "Error": {
                        "Code": "NotFound.asset_id",
                        "Message": "The specified asset asset-x is not found.",
                    },
                }
            },
        )
        with self.assertRaises(SeedanceAssetError) as ctx:
            self.client.delete_asset('asset-x')
        self.assertEqual(ctx.exception.code, 'NotFound.asset_id')
        self.assertEqual(ctx.exception.http_status, 404)
        self.assertIn('RequestId: req-404', ctx.exception.message)

    @patch.object(asset_client_mod.requests, 'post')
    def test_non_json_response(self, mock_post):
        mock_post.return_value = _mock_response(status_code=502, raise_json=True)
        with self.assertRaises(SeedanceAssetError) as ctx:
            self.client.get_asset('asset-1')
        self.assertEqual(ctx.exception.http_status, 502)

    @patch.object(asset_client_mod.requests, 'post')
    def test_network_error(self, mock_post):
        import requests as _requests
        mock_post.side_effect = _requests.exceptions.ConnectionError("boom")
        with self.assertRaises(SeedanceAssetError):
            self.client.get_asset('asset-1')

    @patch.object(asset_client_mod.requests, 'post')
    def test_2xx_with_official_error_structure(self, mock_post):
        """2xx 但带官方 Error 结构的防御分支"""
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {
                "RequestId": "req-3",
                "Error": {"Code": "SomeError", "Message": "官方错误"},
            }
        })
        with self.assertRaises(SeedanceAssetError) as ctx:
            self.client.get_asset('asset-1')
        self.assertEqual(ctx.exception.code, 'SomeError')


class TestActionMethods(unittest.TestCase):
    """各 Action 方法的请求体构造"""

    def setUp(self):
        self.client = _make_client()

    @patch.object(asset_client_mod.requests, 'post')
    def test_create_asset_with_group(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {"Id": "a", "Status": "Processing"}
        })
        self.client.create_asset(
            url='https://example.com/v.mp4', asset_type='Video',
            group_id='group-1', moderation={"Level": "high"},
        )
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body['GroupId'], 'group-1')
        self.assertEqual(body['Moderation'], {"Level": "high"})

    @patch.object(asset_client_mod.requests, 'post')
    def test_list_assets_params(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {"Items": [], "TotalCount": 0}
        })
        self.client.list_assets(group_ids=['g1', 'g2'], page=2, page_size=10)
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body, {"GroupIds": ["g1", "g2"], "Page": 2, "PageSize": 10})
        self.assertEqual(
            mock_post.call_args.kwargs['params']['Action'], 'ListAssets'
        )

    @patch.object(asset_client_mod.requests, 'post')
    def test_empty_body_actions(self, mock_post):
        """无请求体 Action 传 {}"""
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": []
        })
        self.client.list_asset_groups()
        self.assertEqual(mock_post.call_args.kwargs['json'], {})
        self.assertEqual(
            mock_post.call_args.kwargs['params']['Action'], 'ListAssetGroups'
        )

    @patch.object(asset_client_mod.requests, 'post')
    def test_visual_validate_actions(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {"BytedToken": "bt-1"}
        })
        self.client.create_visual_validate_session('https://cb.example.com/cb')
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body, {"CallbackURL": "https://cb.example.com/cb"})

        self.client.get_visual_validate_result('bt-1')
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body, {"BytedToken": "bt-1"})

    @patch.object(asset_client_mod.requests, 'post')
    def test_update_asset_group_partial(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {}
        })
        self.client.update_asset_group('g1', description='new desc')
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body, {"Id": "g1", "Description": "new desc"})


class TestWaitAssetActive(unittest.TestCase):
    """轮询等待素材 Active"""

    def setUp(self):
        self.client = _make_client()

    @patch.object(asset_client_mod.requests, 'post')
    def test_immediate_active(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {"Id": "a1", "Status": ASSET_STATUS_ACTIVE}
        })
        result = self.client.wait_asset_active('a1', timeout=5, poll_interval=0)
        self.assertEqual(result['Status'], ASSET_STATUS_ACTIVE)
        self.assertEqual(mock_post.call_count, 1)

    @patch.object(asset_client_mod.requests, 'post')
    def test_processing_then_active(self, mock_post):
        """Processing → Active 两轮轮询"""
        statuses = [
            _mock_response(json_data={
                "ResponseMetadata": {}, "Result": {"Id": "a1", "Status": ASSET_STATUS_PROCESSING}
            }),
            _mock_response(json_data={
                "ResponseMetadata": {}, "Result": {"Id": "a1", "Status": ASSET_STATUS_ACTIVE}
            }),
        ]
        mock_post.side_effect = statuses
        result = self.client.wait_asset_active('a1', timeout=5, poll_interval=0)
        self.assertEqual(result['Status'], ASSET_STATUS_ACTIVE)
        self.assertEqual(mock_post.call_count, 2)

    @patch.object(asset_client_mod.requests, 'post')
    def test_failed_status_raises(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {"Id": "a1", "Status": ASSET_STATUS_FAILED}
        })
        with self.assertRaises(SeedanceAssetError) as ctx:
            self.client.wait_asset_active('a1', timeout=5, poll_interval=0)
        self.assertEqual(ctx.exception.code, 'AssetFailed')

    @patch.object(asset_client_mod.requests, 'post')
    def test_timeout_raises(self, mock_post):
        mock_post.return_value = _mock_response(json_data={
            "ResponseMetadata": {}, "Result": {"Id": "a1", "Status": ASSET_STATUS_PROCESSING}
        })
        with patch.object(asset_client_mod.time, 'sleep') as mock_sleep, \
                patch.object(asset_client_mod.time, 'time', side_effect=[0, 100, 200]):
            with self.assertRaises(SeedanceAssetError) as ctx:
                self.client.wait_asset_active('a1', timeout=5, poll_interval=0)
            self.assertEqual(ctx.exception.code, 'AssetWaitTimeout')


if __name__ == '__main__':
    unittest.main()
