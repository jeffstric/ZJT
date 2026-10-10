"""has_generated_result 判重 LIKE 边界测试。

事故：'%' + pid + '\\_%' 缺前导边界，%757\\_% 会命中 ".../1757_1698.mp4"
（已连库实测），pid 互为数字后缀时会话误判 duplicate=true，前端跳过落库，
已付费生成结果永久丢失。修复：与前端 contentHasGeneratedTaskId 对齐为
/{pid}_ 与 %2F{pid}_ 双前导边界形态，并对入口 project_ids 强转 int。
"""
import re
from unittest.mock import patch

from model.chat_messages import ChatMessagesModel


def _like_to_regex(like_param: str) -> re.Pattern:
    """把 MySQL LIKE 参数（% 通配、\\_ 转义下划线）翻译成等价正则，离线验证语义。"""
    out, i = [], 0
    while i < len(like_param):
        ch = like_param[i]
        if ch == "\\" and i + 1 < len(like_param):
            out.append(re.escape(like_param[i + 1]))
            i += 2
            continue
        if ch == "%":
            out.append(".*")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def _captured(fake):
    sql, params = fake.call_args.args
    return sql, params


def test_like_params_carry_leading_boundaries():
    with patch("model.chat_messages.execute_query", return_value={"cnt": 0}) as fake:
        ChatMessagesModel.has_generated_result("s1", [757])
    sql, params = _captured(fake)
    id_patterns = [p for p in params[3:]]
    assert '%data-publish-tool-id="757"%' in id_patterns
    assert "%/757\\_%" in id_patterns
    assert "%2F757\\_%" in id_patterns
    # 旧的"裸前缀"形态必须消失（它命中 1757_xxx）
    assert "%757\\_%" not in id_patterns


def test_no_substring_false_positive_between_pids():
    """757 不误中 1757_ / 91254_ 的内容；/757_ 与 %2F757_ 正常命中。"""
    with patch("model.chat_messages.execute_query", return_value={"cnt": 0}) as fake:
        ChatMessagesModel.has_generated_result("s1", [757])
    _, params = _captured(fake)
    media_patterns = [p for p in params[3:] if not p.startswith("%data-")]

    hit = lambda content: any(_like_to_regex(p).match(content) for p in media_patterns)
    # 误配场景（修复前 %757\_% 全部命中）
    assert not hit("https://cdn.x.com/upload/1757_1698.mp4")
    assert not hit("https://cdn.x.com/upload/cache/9757_1.png")
    # 正确命中场景
    assert hit("https://cdn.x.com/upload/757_1698.mp4")
    assert hit("https://cdn.x.com/upload%2F757_1698.mp4")


def test_project_ids_coerced_to_int_and_invalid_skipped():
    with patch("model.chat_messages.execute_query", return_value={"cnt": 0}) as fake:
        ChatMessagesModel.has_generated_result("s1", ["1254", 91254])
    _, params = _captured(fake)
    id_patterns = [p for p in params[3:]]
    # 数字字符串归一化成 int 再拼接，形态一致
    assert "%/1254\\_%" in id_patterns
    assert "%/91254\\_%" in id_patterns
    # 91254 的边界形态不会命中裸 1254 内容
    pat_1254 = [p for p in id_patterns if "1254" in p and "91254" not in p]
    assert not any(
        _like_to_regex(p).match("https://cdn.x.com/upload/91254_1.png")
        for p in pat_1254
    )


def test_all_invalid_ids_short_circuits_without_db():
    with patch(
        "model.chat_messages.execute_query", return_value={"cnt": 0}
    ) as fake:
        assert ChatMessagesModel.has_generated_result("s1", ["abc", None]) is False
    fake.assert_not_called()


def test_empty_inputs_return_false():
    assert ChatMessagesModel.has_generated_result("", [1]) is False
    assert ChatMessagesModel.has_generated_result("s1", []) is False
