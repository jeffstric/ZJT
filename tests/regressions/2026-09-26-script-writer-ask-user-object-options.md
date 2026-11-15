---
id: 2026-09-26-script-writer-ask-user-object-options
patch:
tests:
  - tests/script_writer_core/test_ask_user_options_normalization.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

模型给「向用户提问」传了对象形式的选项，而不是纯字符串。提问卡片渲染失败，用户看不到可点的选项。

## 代码大概在哪

- 选项归一化和 `_handle_ask_user`，测试在 `tests/script_writer_core/test_ask_user_options_normalization.py`

## 怎么操作、怎样算没修好

还没有改坏补丁。对象选项、不可解析选项、纯字符串都要能走通，不能把对象原样丢给前端。

## 永久测试

- `tests/script_writer_core/test_ask_user_options_normalization.py`
