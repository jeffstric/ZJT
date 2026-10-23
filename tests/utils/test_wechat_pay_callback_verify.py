"""
微信支付 V3 回调验签测试（审计 BUG-R2-S1-A3-H1 fail-closed 修复）

密钥文件缺失时必须拒绝回调（return False），不得 fail-open：
验签密钥缺失即无法确认通知来源，接受回调等于接受任意伪造的支付通知
（曾可在未入账的订单上直接入账算力）。同时覆盖正常验签路径
（正确签名通过 / 伪造签名拒绝），防止 fail-closed 改动误伤正常回调。
"""
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from utils.wechat_pay_util import WechatPayUtil


def _make_key_pair(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_file = tmp_path / "pub_key.pem"
    key_file.write_bytes(pub_pem)
    return private_key


def _sign(private_key, message: str) -> str:
    sig = private_key.sign(
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def _patch_key_dir(monkeypatch, tmp_path):
    """把验签密钥查找目录重定向到 tmp_path（serial=PUB_KEY_ID 走 pub_key.pem 分支）。

    os.path.join 为进程级共享对象，这里只定向密钥文件名，其余调用透传。
    """
    real_join = os.path.join

    def fake_join(*args):
        if args and args[-1] == "pub_key.pem":
            return str(tmp_path / "pub_key.pem")
        return real_join(*args)

    monkeypatch.setattr("utils.wechat_pay_util.os.path.join", fake_join)


def test_missing_key_file_rejected(monkeypatch):
    """密钥文件缺失 → 拒绝（fail-closed），绝不允许跳过验签放行。"""
    import builtins

    def _no_file(*args, **kwargs):
        raise FileNotFoundError(args[0] if args else "missing")

    monkeypatch.setattr(builtins, "open", _no_file)
    util = WechatPayUtil()
    assert util.verify_callback_signature("1", "n", b"{}", "sig", "PUB_KEY_ID_123") is False


def test_valid_signature_accepted(tmp_path, monkeypatch):
    private_key = _make_key_pair(tmp_path)
    _patch_key_dir(monkeypatch, tmp_path)
    verify_string = "1700000000\nnonce123\n{\"a\":1}\n"
    signature = _sign(private_key, verify_string)

    util = WechatPayUtil()
    ok = util.verify_callback_signature(
        "1700000000", "nonce123", b'{"a":1}', signature, "PUB_KEY_ID_123"
    )
    assert ok is True


def test_forged_signature_rejected(tmp_path, monkeypatch):
    _make_key_pair(tmp_path)  # 验签公钥
    _patch_key_dir(monkeypatch, tmp_path)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = _sign(other_key, "1700000000\nnonce123\n{\"a\":1}\n")

    util = WechatPayUtil()
    ok = util.verify_callback_signature(
        "1700000000", "nonce123", b'{"a":1}', forged, "PUB_KEY_ID_123"
    )
    assert ok is False


# ==================== 开发联调旁路（双开关，默认关闭） ====================

def _set_bypass(monkeypatch, test_mode=False, bypass=False, raise_error=False):
    def fake_get(*keys, default=None):
        if raise_error:
            raise RuntimeError("db down")
        if keys == ('test_mode', 'enabled'):
            return test_mode
        if keys == ('test_mode', 'wechat_pay_skip_callback_sign'):
            return bypass
        return default

    monkeypatch.setattr("config.config_util.get_dynamic_config_value", fake_get)


def _missing_key(monkeypatch):
    """让 open 抛 FileNotFoundError，模拟开发环境无平台公钥文件。"""
    import builtins

    def _no_file(*args, **kwargs):
        raise FileNotFoundError(args[0] if args else "missing")

    monkeypatch.setattr(builtins, "open", _no_file)


def test_dev_bypass_double_switch_allows_missing_key(monkeypatch):
    """双开关齐开 + 密钥缺失 → 放行（开发联调真实支付回调可入账）"""
    _set_bypass(monkeypatch, test_mode=True, bypass=True)
    _missing_key(monkeypatch)
    assert WechatPayUtil().verify_callback_signature(
        "1", "n", b"{}", "sig", "PUB_KEY_ID_1"
    ) is True


def test_dev_bypass_requires_both_switches(monkeypatch):
    """只开单个开关 → 仍拒绝（防生产误触单开关绕过验签）"""
    _missing_key(monkeypatch)
    _set_bypass(monkeypatch, test_mode=False, bypass=True)
    assert WechatPayUtil().verify_callback_signature(
        "1", "n", b"{}", "sig", "PUB_KEY_ID_1"
    ) is False
    _set_bypass(monkeypatch, test_mode=True, bypass=False)
    assert WechatPayUtil().verify_callback_signature(
        "1", "n", b"{}", "sig", "PUB_KEY_ID_1"
    ) is False


def test_dev_bypass_config_error_fails_closed(monkeypatch):
    """配置读取异常 → 按未开启处理（安全失败）"""
    _set_bypass(monkeypatch, raise_error=True)
    _missing_key(monkeypatch)
    assert WechatPayUtil().verify_callback_signature(
        "1", "n", b"{}", "sig", "PUB_KEY_ID_1"
    ) is False


def test_dev_bypass_never_overrides_wrong_signature(tmp_path, monkeypatch):
    """旁路只覆盖密钥缺失分支：密钥存在但签名错误仍拒绝（fail-closed 不变）"""
    _set_bypass(monkeypatch, test_mode=True, bypass=True)
    _patch_key_dir(monkeypatch, tmp_path)
    _make_key_pair(tmp_path)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = _sign(other_key, "1700000000\nnonce123\n{\"a\":1}\n")
    assert WechatPayUtil().verify_callback_signature(
        "1700000000", "nonce123", b'{"a":1}', forged, "PUB_KEY_ID_1"
    ) is False
