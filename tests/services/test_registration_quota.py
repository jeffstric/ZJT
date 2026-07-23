"""注册配额公共门面的社区版行为测试。

门面契约：``check_allowed(total_count)``，计数由调用方（AuthService）
传入，门面自身不读数据库，因此本测试无需 mock 数据库层。
"""
import pytest

from config.constant import COMMUNITY_MAX_REGISTERED_USERS
from services import registration_quota


@pytest.fixture(autouse=True)
def reset_provider():
    registration_quota.reset_provider()
    yield
    registration_quota.reset_provider()


def test_community_allows_below_limit():
    allowed, msg = registration_quota.check_allowed(COMMUNITY_MAX_REGISTERED_USERS - 1)
    assert allowed is True
    assert msg == ""


def test_community_blocks_at_limit():
    allowed, msg = registration_quota.check_allowed(COMMUNITY_MAX_REGISTERED_USERS)
    assert allowed is False
    assert str(COMMUNITY_MAX_REGISTERED_USERS) in msg


def test_community_blocks_above_limit():
    allowed, msg = registration_quota.check_allowed(COMMUNITY_MAX_REGISTERED_USERS + 5)
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

        def check_allowed(self, total_count: int):
            return True, ""

    registration_quota.register_provider(_AllowAll())
    assert registration_quota.is_available() is True
    assert registration_quota.check_allowed(COMMUNITY_MAX_REGISTERED_USERS + 100) == (True, "")

    registration_quota.reset_provider()
    assert registration_quota.is_available() is False
    allowed, _ = registration_quota.check_allowed(COMMUNITY_MAX_REGISTERED_USERS)
    assert allowed is False
