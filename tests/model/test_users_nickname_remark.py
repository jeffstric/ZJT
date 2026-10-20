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


def test_get_display_names_uses_nickname_and_falls_back(monkeypatch):
    from model.users import UsersModel

    def fake_query(sql, params, fetch_all=False):
        assert "SELECT id, nickname FROM users WHERE id IN" in sql
        assert params == (14, 33, 8)
        assert fetch_all is True
        return [
            {"id": 14, "nickname": " 远方 "},
            {"id": 33, "nickname": ""},
            {"id": 8, "nickname": None},
        ]

    monkeypatch.setattr("model.users.execute_query", fake_query)
    names = UsersModel.get_display_names([14, "33", 33, 8, None, "bad"])
    assert names == {14: "远方", 33: "用户33", 8: "用户8"}


def test_find_ids_by_nickname_or_account_exact_then_like(monkeypatch):
    from model.users import UsersModel

    calls = []

    def fake_query(sql, params, fetch_all=False):
        calls.append((sql, params))
        if "nickname = %s" in sql:
            return []
        assert "nickname LIKE %s" in sql
        assert params[0] == "%小\\%明%"
        return [{"id": 33}]

    monkeypatch.setattr("model.users.execute_query", fake_query)
    assert UsersModel.find_ids_by_nickname_or_account("  小%明 ") == [33]
    assert len(calls) == 2


def test_find_ids_by_nickname_or_account_exact_skips_like(monkeypatch):
    from model.users import UsersModel

    def fake_query(sql, params, fetch_all=False):
        assert "LIKE" not in sql
        return [{"id": 14}]

    monkeypatch.setattr("model.users.execute_query", fake_query)
    assert UsersModel.find_ids_by_nickname_or_account("13800000000") == [14]


def test_find_ids_empty_skips_query(monkeypatch):
    from model.users import UsersModel

    def fail_query(*args, **kwargs):
        raise AssertionError("empty query must not hit the database")

    monkeypatch.setattr("model.users.execute_query", fail_query)
    assert UsersModel.find_ids_by_nickname_or_account("   ") == []


def test_get_display_names_empty_skips_query(monkeypatch):
    from model.users import UsersModel

    def fail_query(*args, **kwargs):
        raise AssertionError("empty ids must not query")

    monkeypatch.setattr("model.users.execute_query", fail_query)
    assert UsersModel.get_display_names([]) == {}
    assert UsersModel.get_display_names([None, "x"]) == {}


def test_generate_default_nickname_avoids_used_names():
    used = set()
    for _ in range(30):
        name = generate_default_nickname(used_names=used)
        assert name not in used
        used.add(name)
