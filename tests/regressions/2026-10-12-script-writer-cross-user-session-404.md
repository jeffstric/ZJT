---
id: 2026-10-12-script-writer-cross-user-session-404
patch: patches/2026-10-12-script-writer-cross-user-session-404.json
tests:
  - tests/api/test_sessions_endpoint_auth.py
  - auto_test/e2e/test_session.py
replay_tests:
  - tests/api/test_sessions_endpoint_auth.py::test_sessions_user_id_mismatch_rejected
feature_ids:
---

## 当时坏成什么样

会话接口没有按当前用户收口。别人的会话能被枚举或打开，该返回 404 的地方没有挡住。

## 代码大概在哪

- 会话列表和会话详情的属主校验
- `tests/api/test_sessions_endpoint_auth.py`
- `auto_test/e2e/test_session.py` 的 `test_session_list` 要带本人 `user_id`

## 怎么操作、怎样算没修好

改坏补丁把 `api/script_writer.py` `list_sessions()` 里「查询参数 user_id 与登录身份一致性校验」的整块删掉（`check_claimed_user_id` 调用与其事故背景注释一并移除）——回到当年「信任参数 user_id、把他人最新会话原样返回」的行为，跨用户枚举重新成为可能。

怎样算没修好：`tests/api/test_sessions_endpoint_auth.py::test_sessions_user_id_mismatch_rejected` 没红，即改坏没被抓住。该用例断言 user_id=2（他人）必须 403 且不触达数据库（`list_by_user` 被 patch 成 `pytest.fail`，改坏后真查库会双重失败）。同文件的 401/管理员/模型可省略用例锁住鉴权的其余面。

## 永久测试

- `tests/api/test_sessions_endpoint_auth.py`
- `auto_test/e2e/test_session.py`
