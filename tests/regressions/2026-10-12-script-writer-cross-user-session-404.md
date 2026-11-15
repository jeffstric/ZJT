---
id: 2026-10-12-script-writer-cross-user-session-404
patch:
tests:
  - tests/api/test_sessions_endpoint_auth.py
  - auto_test/e2e/test_session.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

会话接口没有按当前用户收口。别人的会话能被枚举或打开，该返回 404 的地方没有挡住。

## 代码大概在哪

- 会话列表和会话详情的属主校验
- `tests/api/test_sessions_endpoint_auth.py`
- `auto_test/e2e/test_session.py` 的 `test_session_list` 要带本人 `user_id`

## 怎么操作、怎样算没修好

还没有改坏补丁。未登录 401，别人的会话不能被列出来或打开。

## 永久测试

- `tests/api/test_sessions_endpoint_auth.py`
- `auto_test/e2e/test_session.py`
