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
