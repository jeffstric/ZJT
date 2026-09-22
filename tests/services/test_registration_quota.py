"""激活用户数配额公共门面的社区版行为测试。

门面契约：``check_allowed(active_count)``（users.status=1 计数），由调用方
（AuthService / 管理员启用接口）传入，门面自身不读数据库，因此本测试
无需 mock 数据库层。
"""
import pytest

from config.constant import COMMUNITY_MAX_ACTIVE_USERS
from services import registration_quota


@pytest.fixture(autouse=True)
def reset_provider():
    registration_quota.reset_provider()
    yield
    registration_quota.reset_provider()


def test_community_allows_below_limit():
    allowed, msg = registration_quota.check_allowed(COMMUNITY_MAX_ACTIVE_USERS - 1)
    assert allowed is True
    assert msg == ""


def test_community_blocks_at_limit():
    allowed, msg = registration_quota.check_allowed(COMMUNITY_MAX_ACTIVE_USERS)
    assert allowed is False
    assert str(COMMUNITY_MAX_ACTIVE_USERS) in msg
    assert "激活用户" in msg


def test_community_blocks_above_limit():
    allowed, msg = registration_quota.check_allowed(COMMUNITY_MAX_ACTIVE_USERS + 5)
    assert allowed is False


def test_default_provider_is_unavailable():
    assert registration_quota.is_available() is False


def test_community_max_active_users_is_one():
    # 开源版仅支持 1 个激活用户（商业版分档见 enterprise 侧测试）。
    assert COMMUNITY_MAX_ACTIVE_USERS == 1


def test_register_provider_requires_available_flag():
    with pytest.raises(ValueError):
        registration_quota.register_provider(
            registration_quota.CommunityRegistrationQuotaProvider()
        )


def test_register_provider_delegates_and_reset_restores():
    class _AllowAll:
        available = True

        def check_allowed(self, active_count: int):
            return True, ""

        def get_max_active_users(self):
            return None

    registration_quota.register_provider(_AllowAll())
    assert registration_quota.is_available() is True
    assert registration_quota.check_allowed(COMMUNITY_MAX_ACTIVE_USERS + 100) == (True, "")
    # 上限查询委托给注入的 Provider（None 表示不限）。
    assert registration_quota.get_max_active_users() is None

    registration_quota.reset_provider()
    assert registration_quota.is_available() is False
    allowed, _ = registration_quota.check_allowed(COMMUNITY_MAX_ACTIVE_USERS)
    assert allowed is False
    assert registration_quota.get_max_active_users() == COMMUNITY_MAX_ACTIVE_USERS


def test_get_max_active_users_falls_back_for_legacy_provider():
    # 未实现 get_max_active_users 的 Provider（旧测试 fake）不应导致报错，
    # 门面回退 None（旧商业 Provider 语义为"不限"），否则商业版会误报超限。
    class _Legacy:
        available = True

        def check_allowed(self, active_count: int):
            return True, ""

    registration_quota.register_provider(_Legacy())
    assert registration_quota.get_max_active_users() is None
