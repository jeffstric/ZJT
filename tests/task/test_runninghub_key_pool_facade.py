"""RunningHub 密钥池公共门面边界测试。"""
import asyncio
from unittest.mock import patch

import pytest

from task import runninghub_key_pool
from utils.enterprise_loader import EnterpriseLoader


@pytest.fixture(autouse=True)
def reset_key_pool_provider():
    runninghub_key_pool.reset_provider()
    yield
    runninghub_key_pool.reset_provider()


def test_community_provider_is_always_single_key():
    with patch.object(
        runninghub_key_pool,
        'get_dynamic_config_value',
        return_value='global-key',
    ):
        assert runninghub_key_pool.is_available() is False
        assert runninghub_key_pool.acquire_key() is None
        assert runninghub_key_pool.get_key_index_for_slot(123, 'task') == 0
        assert runninghub_key_pool.get_key_by_index(0) == 'global-key'
        assert runninghub_key_pool.get_key_by_index(1) == ''
        assert runninghub_key_pool.refresh_circuits() == 0


def test_community_management_is_unavailable():
    with pytest.raises(runninghub_key_pool.RunningHubKeyPoolUnavailableError):
        asyncio.run(runninghub_key_pool.get_pool_overview_async())


def test_enterprise_mode_without_package_does_not_enable_provider():
    loader = EnterpriseLoader()
    with patch('utils.enterprise_loader.get_config_value', return_value='enterprise'), \
            patch('utils.enterprise_loader.os.path.isdir', return_value=False):
        assert loader.discover() is False
    assert runninghub_key_pool.is_available() is False
    assert runninghub_key_pool.acquire_key() is None


def test_community_mode_does_not_load_existing_enterprise_directory():
    loader = EnterpriseLoader()
    with patch('utils.enterprise_loader.get_config_value', return_value='community'), \
            patch('utils.enterprise_loader.os.path.isdir') as isdir:
        assert loader.discover() is False
        isdir.assert_not_called()


def test_registered_provider_controls_capability():
    class FakeProvider:
        available = True

        def acquire_key(self):
            return 2, 'enterprise-key', 3

        def get_key_by_index(self, index):
            return 'enterprise-key'

        def get_key_index_for_slot(self, task_id, source):
            return 2

        def report_success(self, index):
            return None

        def report_failure(self, index, reason=''):
            return None

        def refresh_circuits(self):
            return 0

    runninghub_key_pool.register_provider(FakeProvider())

    assert runninghub_key_pool.is_available() is True
    assert runninghub_key_pool.acquire_key() == (2, 'enterprise-key', 3)
    assert asyncio.run(runninghub_key_pool.acquire_key_async()) == (
        2, 'enterprise-key', 3
    )


def test_failed_enterprise_registration_restores_community_provider():
    class Provider:
        available = True

    class BrokenEnterpriseModule:
        @staticmethod
        def register(app):
            runninghub_key_pool.register_provider(Provider())
            raise RuntimeError('register failed')

    loader = EnterpriseLoader()
    with patch(
        'utils.enterprise_loader.importlib.import_module',
        return_value=BrokenEnterpriseModule,
    ):
        loader.load(app=object())

    assert loader.loaded is False
    assert runninghub_key_pool.is_available() is False
    assert runninghub_key_pool.acquire_key() is None
