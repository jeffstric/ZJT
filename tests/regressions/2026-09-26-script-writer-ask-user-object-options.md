---
id: 2026-09-26-script-writer-ask-user-object-options
patch: patches/2026-09-26-script-writer-ask-user-object-options.json
tests:
  - tests/script_writer_core/test_ask_user_options_normalization.py
replay_tests:
  - tests/script_writer_core/test_ask_user_options_normalization.py::test_object_options_stored_as_strings
  - tests/script_writer_core/test_ask_user_options_normalization.py::test_unparseable_options_return_error_without_verification
feature_ids:
---

## 当时坏成什么样

模型给「向用户提问」传了对象形式的选项，而不是纯字符串。提问卡片渲染失败，用户看不到可点的选项。

## 代码大概在哪

- 选项归一化和 `_handle_ask_user`，测试在 `tests/script_writer_core/test_ask_user_options_normalization.py`

## 怎么操作、怎样算没修好

改坏补丁把 `script_writer_core/agents/ask_user_mixin.py` `_handle_ask_user()` 里的 `options = _normalize_ask_options(options)` 调用改回当年「只校验非空列表、不校验元素类型」的写法——对象选项原样入库 `agent_verifications.options` 并下发前端，回到 `[object Object]` 渲染失败的行为。

怎样算没修好：`test_object_options_stored_as_strings`（对象选项入库前必须归一化为文案）和 `test_unparseable_options_return_error_without_verification`（完全不可解析必须报错、不创建验证）任一没红，即改坏没被抓住，测试防线是空的。

## 永久测试

- `tests/script_writer_core/test_ask_user_options_normalization.py`
