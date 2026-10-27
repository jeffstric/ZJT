# 2026-09-26 剧本写手 ask_user 选项渲染 [object Object] 事故

## 现象

用户（user 1244，world 1781「奇迹大陆」）在 `script_writer.html` 中收到的「故事写手 向您提问」卡片，选项按钮全部显示 `[object Object]`，无法作答。数据库佐证（`agent_verifications`）：

```text
21:40:28 ask_user「连续生成60集，请选择生成方式」 options=对象数组 → timeout
21:45:32 ask_user（同题重试）             options=对象数组 → timeout
21:45:42 ask_user（第三次，options 为字符串数组）→ approved
```

对象形如 `[{"label": "确认连续生成", "description": "按要求逐集创作…"}, …]`。

## 影响

- 用户两次无法作答，各等待 5 分钟超时，每次超时后再消耗一次 5–7 万输入 token 的 LLM 调用重试（约 5 算力直接浪费）。
- 叠加同日「用户离场后批量任务持续扣费」问题（见下方关联），该会话当日共扣 239 算力，22:24 余额归零任务中断。

## 根因

工具 schema 要求 `options` 为 string 数组（`tool_definitions.py` `ASK_USER_TOOL_DEFINITION`），但整条链路无人校验元素类型：

1. 模型（deepseek-v4-flash）违反 schema，把选项写成 `{"label": …, "description": …}` 对象数组；
2. `expert_agent.py` 对 tool arguments 只做 `json.loads`，`task_manager.py` 的 dataclass 注解 `options: List[str]` 运行期不生效；
3. `ask_user_mixin._handle_ask_user` 只校验「非空列表」，不校验元素类型，对象原样入库（`agent_verifications.options`）并下发；
4. 前端 `script_writer.js` 两处渲染直接 `escapeHtml(opt)`，`escape.js` 内部 `String(value)` → `[object Object]`；点击提交还会把原始对象塞进 `user_input`。

## 修复

- 后端（根修复，覆盖所有前端）：`ask_user_mixin.py` 新增模块级 `_normalize_ask_options()`，在 `_handle_ask_user` 提取参数后归一化——字符串/数字直接转文案，对象按 `label→option→text→value→name→title→content` 优先级提取文案，取不到的元素丢弃；归一化后为空（如 JSON 字符串无法解析、全是未知结构）返回指导性错误让模型按正确格式重试；兼容整体被塞进字符串的 JSON 数组。
- 前端（纵深防御，`web/js/script_writer.js`）：新增 `normalizeAskOption()`，历史消息与实时卡片两处渲染、以及选项点击提交（`submitVerificationAnswer`）统一先归一化，提取不到文案的按钮直接跳过。
- 测试：`tests/script_writer_core/test_ask_user_options_normalization.py`（归一化助手单测 + 走 `_handle_ask_user` 全路径的对象选项/不可解析/纯字符串用例）。
- 事故与修复同步：本文件。

## 关联问题（同日同会话，另行处理）

`ask_user` 超时不计入 `ASK_USER_MAX_CONSECUTIVE_FAILS`（`ask_user_mixin.py` 超时分支不累加），无人应答时「提问→300s 超时→LLM 重试→再提问」可无限循环，每轮 1–2 算力。该遗留风险已在 2026-09-01 算力确认门事故（`2026-09-01-script-writer-power-confirm-loop.md`）中记录。已实现「单次任务算力消耗上限」机制：达到用户可配置的累加上限自动暂停任务，`ask_user` 超限后立即返回不再进入 5 分钟等待，详见 `docs/backend/script_writer_power_budget.md`。
