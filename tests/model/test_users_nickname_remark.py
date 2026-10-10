"""users 模型昵称/备注相关纯函数测试（不连数据库）。

覆盖：User.to_dict 的 display_name 兜底、remark 不进 to_dict（防用户侧泄漏）、
config.constant.generate_default_nickname 的格式与去重行为。
"""

from config.constant import (
    NICKNAME_ADJECTIVES,
    NICKNAME_ANIMALS,
    generate_default_nickname,
)
from model.users import User


def _make_user(**kwargs):
    return User(id=kwargs.pop('id', 42), **kwargs)


def test_to_dict_display_name_uses_nickname():
    user = _make_user(nickname="小明")
    assert user.to_dict()['display_name'] == "小明"
    assert user.to_dict()['nickname'] == "小明"


def test_to_dict_display_name_falls_back_to_user_id():
    # nickname 为 NULL（存量/异常路径）时兜底为"用户{id}"
    user = _make_user(nickname=None)
    data = user.to_dict()
    assert data['nickname'] is None
    assert data['display_name'] == "用户42"


def test_to_dict_excludes_remark():
    # remark 是管理员专属字段，绝不能随 to_dict 泄漏到用户侧接口
    user = _make_user(nickname="小明", remark="内部备注")
    assert 'remark' not in user.to_dict()


def test_generate_default_nickname_format():
    for _ in range(50):
        name = generate_default_nickname()
        assert 4 <= len(name) <= 30
        assert any(name.startswith(adj) for adj in NICKNAME_ADJECTIVES)
        assert any(name.endswith(animal) for animal in NICKNAME_ANIMALS)
        # 昵称末尾不带数字（产品要求：重复无碍，不追加数字后缀）
        assert not name[-1].isdigit()


def test_generate_default_nickname_avoids_used_names():
    used = set()
    for _ in range(30):
        name = generate_default_nickname(used_names=used)
        assert name not in used
        used.add(name)
