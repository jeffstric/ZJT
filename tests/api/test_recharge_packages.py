"""算力充值套餐列表。

0.1 元 / 99 算力首充福利（package_id=5）已下线，未首充和已首充用户都不可见、不可新购。
9.9 元算力包（package_id=1）保持可购。
"""
import pytest
from fastapi.testclient import TestClient

from config.constant import RECHARGE_PACKAGES, Commission


@pytest.fixture
def client(monkeypatch):
    import server

    monkeypatch.setattr(
        'model.user_tokens.UserTokensModel.get_user_id_by_token',
        staticmethod(lambda token: 1 if token == 'valid-token' else None),
    )
    return TestClient(server.app)


def _set_first_recharge(monkeypatch, value: bool):
    """控制首充判定结果；佣金到账查询走降级分支（回退套餐面值，不影响断言）"""
    import server

    async def fake_has(auth_token: str) -> bool:
        return value

    async def fake_perseids(endpoint=None, **kw):
        if endpoint == 'commission/recharge_grants':
            return False, '降级', {}
        return True, 'ok', {}

    monkeypatch.setattr(server, '_has_completed_first_recharge', fake_has)
    monkeypatch.setattr(server, 'async_make_perseids_request', fake_perseids)


def test_first_time_user_does_not_see_retired_promo(client, monkeypatch):
    _set_first_recharge(monkeypatch, False)
    resp = client.get('/api/recharge/packages', headers={'Authorization': 'Bearer valid-token'})
    assert resp.status_code == 200
    ids = [p['package_id'] for p in resp.json()['packages']]
    assert Commission.FIRST_RECHARGE_PACKAGE_ID not in ids
    assert 1 in ids


def test_recharged_user_still_sees_9_9_package(client, monkeypatch):
    """9.9 算力包（package_id=1）对已首充用户仍然可见；0.1 元福利包已下线"""
    _set_first_recharge(monkeypatch, True)
    resp = client.get('/api/recharge/packages', headers={'Authorization': 'Bearer valid-token'})
    assert resp.status_code == 200
    ids = [p['package_id'] for p in resp.json()['packages']]
    assert Commission.FIRST_RECHARGE_PACKAGE_ID not in ids
    assert 1 in ids


def test_first_recharge_package_removed_from_catalog():
    assert Commission.FIRST_RECHARGE_PACKAGE_ID == 5
    assert all(p['package_id'] != Commission.FIRST_RECHARGE_PACKAGE_ID for p in RECHARGE_PACKAGES)


def test_trial_package_9_9_unchanged():
    pkg = next(p for p in RECHARGE_PACKAGES if p['package_id'] == 1)
    assert pkg['price'] == 9.9
    assert pkg['computing_power'] == 88


def test_first_recharge_package_not_in_commission_tiers():
    """首充福利包不定义抽佣档位 → settle 走『档位未定义→不抽佣全额到账』分支"""
    assert Commission.FIRST_RECHARGE_PACKAGE_ID not in Commission.COMMISSION_TIERS
