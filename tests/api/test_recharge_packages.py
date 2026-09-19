"""算力充值套餐首充解绑（2026-09-19）的单测。

背景：算力包（原体验包）9.9（package_id=1）曾被当作首充福利包（已首充用户不可见/不可购），
现常规化为任意时刻可充；首充福利由新套餐 package_id=5（0.1 元 / 99 算力）承载。

覆盖：
- 未首充用户：可见全部套餐（含 0.1 元首充福利包与 9.9 算力包（原体验包））
- 已首充用户：仅过滤首充福利包（package_id=5），9.9 算力包（原体验包，package_id=1）仍可见（核心回归点）
- 常量一致性：FIRST_RECHARGE_PACKAGE_ID 指向 0.1 元/99 算力套餐且存在于 RECHARGE_PACKAGES
- 佣金档位：首充福利包不定义 COMMISSION_TIERS 档位（settle 走「档位未定义→不抽佣全额」分支）
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


def test_first_time_user_sees_all_packages(client, monkeypatch):
    _set_first_recharge(monkeypatch, False)
    resp = client.get('/api/recharge/packages', headers={'Authorization': 'Bearer valid-token'})
    assert resp.status_code == 200
    ids = [p['package_id'] for p in resp.json()['packages']]
    assert Commission.FIRST_RECHARGE_PACKAGE_ID in ids
    assert 1 in ids


def test_recharged_user_still_sees_9_9_package(client, monkeypatch):
    """核心回归：已首充用户看不到 0.1 元福利包，但 9.9 算力包（原体验包，package_id=1）必须可见"""
    _set_first_recharge(monkeypatch, True)
    resp = client.get('/api/recharge/packages', headers={'Authorization': 'Bearer valid-token'})
    assert resp.status_code == 200
    ids = [p['package_id'] for p in resp.json()['packages']]
    assert Commission.FIRST_RECHARGE_PACKAGE_ID not in ids
    assert 1 in ids


def test_first_recharge_constants_consistent():
    pkg = next(
        p for p in RECHARGE_PACKAGES
        if p['package_id'] == Commission.FIRST_RECHARGE_PACKAGE_ID
    )
    assert pkg['price'] == 0.1
    assert pkg['computing_power'] == 99


def test_trial_package_9_9_unchanged():
    pkg = next(p for p in RECHARGE_PACKAGES if p['package_id'] == 1)
    assert pkg['price'] == 9.9
    assert pkg['computing_power'] == 88


def test_first_recharge_package_not_in_commission_tiers():
    """首充福利包不定义抽佣档位 → settle 走『档位未定义→不抽佣全额到账』分支"""
    assert Commission.FIRST_RECHARGE_PACKAGE_ID not in Commission.COMMISSION_TIERS
