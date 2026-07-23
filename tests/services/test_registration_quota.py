"""注册配额公共门面的社区版行为测试。"""
from unittest.mock import patch

import pytest

from config.constant import COMMUNITY_MAX_REGISTERED_USERS
from services import registration_quota


@pytest.fixture(autouse=True)
def reset_provider():
    registration_quota.reset_provider()
    yield
    registration_quota.reset_provider()


def _patch_user_count(count: int):
    return patch('model.users.UsersModel.get_total_count', return_value=count)


def test_community_allows_below_limit():
    with _patch_user_count(COMMUNITY_MAX_REGISTERED_USERS - 1):
        allowed, msg = registration_quota.check_allowed()
    assert allowed is True
    assert msg == ""


def test_community_blocks_at_limit():
    with _patch_user_count(COMMUNITY_MAX_REGISTERED_USERS):
        allowed, msg = registration_quota.check_allowed()
    assert allowed is False
    assert str(COMMUNITY_MAX_REGISTERED_USERS) in msg


def test_community_blocks_above_limit():
    with _patch_user_count(COMMUNITY_MAX_REGISTERED_USERS + 5):
        allowed, msg = registration_quota.check_allowed()
    assert allowed is False


def test_default_provider_is_unavailable():
    assert registration_quota.is_available() is False


def test_register_provider_requires_available_flag():
    with pytest.raises(ValueError):
        registration_quota.register_provider(
            registration_quota.CommunityRegistrationQuotaProvider()
        )


def test_register_provider_delegates_and_reset_restores():
    class _AllowAll:
        available = True

        def check_allowed(self):
            return True, ""

    registration_quota.register_provider(_AllowAll())
    assert registration_quota.is_available() is True
    with _patch_user_count(COMMUNITY_MAX_REGISTERED_USERS + 100):
        assert registration_quota.check_allowed() == (True, "")

    registration_quota.reset_provider()
    assert registration_quota.is_available() is False
    with _patch_user_count(COMMUNITY_MAX_REGISTERED_USERS):
        allowed, _ = registration_quota.check_allowed()
        assert allowed is False
