"""微信委托代扣 V2 回调验签测试（审计 BUG-R2-S2-A1-H1 fail-closed 修复）。

api_v2_key 未配置时必须拒绝（return False）：V2 XML 回调无加密层，验签是
唯一来源认证——fail-open 状态下伪造 SUCCESS/FAILURE 回调可免费入账算力、
复活已解约合约，且 FAILURE→SUCCESS(新 transaction_id) 循环可无限重复入账。
密钥回归未配置的典型路径：Docker 容器重建时 in-container config 被模板
重新生成而 MySQL 卷保留订单数据。同时覆盖正常验签路径防误伤。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.wx_papay_util import WxPapayUtil

V2_KEY = "1234567890abcdef1234567890abcdef"


def _util(key=V2_KEY):
    return WxPapayUtil(
        app_id="wx-app", mch_id="mch", api_v2_key=key, plan_template_id="tpl"
    )


def test_missing_v2_key_rejects_callback():
    """api_v2_key 未配置 → 拒绝一切回调（fail-closed），不再跳过验签放行"""
    util = _util(key="")
    assert util.verify_v2_sign({"out_trade_no": "X", "sign": "ANY"}) is False
    assert util.verify_v2_sign({}) is False


def test_missing_sign_rejected():
    assert _util().verify_v2_sign({"out_trade_no": "X"}) is False


def test_correct_sign_accepted():
    params = {"out_trade_no": "SUB_1", "result_code": "SUCCESS"}
    params["sign"] = _util()._sign_v2(params)
    assert _util().verify_v2_sign(params) is True


def test_forged_sign_rejected():
    params = {"out_trade_no": "SUB_1", "result_code": "SUCCESS"}
    forged = dict(params)
    forged["sign"] = "DEADBEEF"  # 攻击者自造签名（无密钥）
    assert _util().verify_v2_sign(forged) is False


# ==================== 开发联调旁路（显式确认串，默认留空关闭） ====================

PHRASE = "DEV-OK-I-KNOW-THE-RISK"


def _set_bypass(monkeypatch, value="", raise_error=False):
    def fake_get(*keys, default=None):
        if raise_error:
            raise RuntimeError("db down")
        if keys == ('pay', 'wxpay', 'dev_skip_callback_sign'):
            return value
        return default

    monkeypatch.setattr("config.config_util.get_dynamic_config_value", fake_get)


def test_dev_bypass_confirm_phrase_allows_missing_key(monkeypatch):
    """配置精确等于确认串 + api_v2_key 未配置 → 放行（开发联调订阅回调可入账）"""
    _set_bypass(monkeypatch, value=PHRASE)
    assert _util(key="").verify_v2_sign({"out_trade_no": "X", "sign": "ANY"}) is True


def test_dev_bypass_rejects_casual_values(monkeypatch):
    """随手值（true/1/错串/空）→ 仍拒绝（显式声明式开关，防管理台误配置）"""
    for casual in ("", "true", "1", "yes", "dev-ok", PHRASE.lower(), PHRASE + " "):
        _set_bypass(monkeypatch, value=casual)
        assert _util(key="").verify_v2_sign({"out_trade_no": "X", "sign": "ANY"}) is False, (
            f"值 {casual!r} 不得放行"
        )


def test_dev_bypass_config_error_fails_closed(monkeypatch):
    """配置读取异常 → 按未开启处理（安全失败）"""
    _set_bypass(monkeypatch, raise_error=True)
    assert _util(key="").verify_v2_sign({"out_trade_no": "X", "sign": "ANY"}) is False


def test_dev_bypass_never_overrides_wrong_sign(monkeypatch):
    """旁路只覆盖密钥缺失分支：api_v2_key 在但签名错误仍拒绝"""
    _set_bypass(monkeypatch, value=PHRASE)
    params = {"out_trade_no": "SUB_1", "result_code": "SUCCESS"}
    forged = dict(params)
    forged["sign"] = "DEADBEEF"
    assert _util().verify_v2_sign(forged) is False
