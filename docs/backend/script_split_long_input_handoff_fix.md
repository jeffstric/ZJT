# 剧本拆分智能体"没有提供导入剧本"修复

## 背景

用户反馈：`web/script_writer.html` 的剧本智能体在执行"拆分小说/剧本"工作流时，**经常**出现拆分智能体（`novel-episode-splitter`）反馈"没有提供导入剧本"，导致拆分流程无法进行。

经调查，这是一个 **跨智能体上下文断裂** 问题，根因在"长剧本（>5000 字）如何从 用户 → orchestrator(PM) → splitter 传递"这条链路上。

## 根因分析

### 关键机制：超过 5000 字的输入会被"文件化"

`script_writer_core/agents/task_manager.py` 的 `process_long_input()` 是入口闸门：

- 用户输入 ≤ 5000 字：原样透传给 PM
- 用户输入 > 5000 字：截取前 4000 字 + 后 1000 字作为预览，**完整内容落盘**为 `user_long_input/<filename>.txt`，并在消息中注入"文件名"提示。完整内容必须通过 `get_long_user_input(name=文件名)` 工具读取。

也就是说，用户粘贴一部几万字的小说时，**orchestrator(PM) 自己看到的也只是截断后的预览 + 文件名提示**。

### 三个沟通断点

| 断点 | 位置 | 问题 |
|------|------|------|
| **1. SOP 模板** | `sop-split-script.md` | 调用 splitter 的 task_description 模板里写的是字面占位符 `[剧本内容]`，但 PM 在长文本场景下根本没有完整剧本可填 |
| **2. 历史透传** | `pm_agent.py:_handle_agent_call` | 传给子智能体的 `conversation_history` 只提取了 `ask_user` 的问答（`_extract_ask_user_qa`），**不包含含文件名提示的那条 user 消息**，splitter 既看不到剧本也看不到文件名 |
| **3. 文件名安全** | `task_manager.py:process_long_input` | 旧文件名格式 `HH:MM:SS.txt` 的冒号在 Windows 上是非法字符（违反 AGENTS.md 第6条跨平台要求），且精度仅到秒易碰撞 |

splitter 虽然有 `get_long_user_input` 工具权限（`agents_config.json` 已配置），且其 SKILL 也知道"超过 5000 字必须用该工具"，**但它拿不到 `name` 参数（文件名）**，所以陷入死循环或直接报错。

### 为什么是"经常"而不是"总是"

长度触发的条件性 bug：
- 剧本 ≤ 5000 字 → 原样透传 → 正常
- 剧本 > 5000 字 → 文件化 + 文件名传递链断裂 → 报错

大部分真实小说/剧本都远超 5000 字，所以表现为"经常"。

## 修复方案

三处协同修改，缺一不可：

### 修复点 1：PM 自动透传长文本文件名（根因修复）

**文件**：`script_writer_core/agents/pm_agent.py`

在 `_handle_agent_call` 中，调用子智能体前自动扫描 PM 的 `conversation_history`，提取所有长文本文件名，并注入子智能体的：

1. **task_description**（最可靠，LLM 一定会读到）
2. **conversation_history**（双保险）

新增两个方法：

- `_extract_long_input_filenames()`：用正则从历史消息中提取文件名，按出现顺序去重。正则兼容新旧两种文件名格式：
  ```python
  _LONG_INPUT_FILENAME_PATTERNS = [
      re.compile(r'-\s*文件名[：:]\s*([^\s\n]+\.txt)'),                    # "- 文件名：xxx.txt"
      re.compile(r'get_long_user_input\(\s*name\s*=\s*["\']([^"\']+\.txt)["\']'),  # 'get_long_user_input(name="xxx.txt")'
  ]
  ```
- `_build_long_input_hint(filenames)`：构造给子智能体的明确指令，例如：
  ```
  【长文本剧本文件提示】
  用户提供的剧本内容较长（超过5000字），完整内容已保存为文件，请务必读取后再处理：
  - 请立即调用 get_long_user_input(name="longinput_7_1_...txt") 读取完整剧本内容
  注意：上面截断的内容只是预览，拆分/分析必须基于 get_long_user_input 读取到的完整内容。
  ```

**为什么用代码而不是只靠 SOP**：即便 SOP 写了占位符，PM 在长文本场景下也"填不出"文件名（它自己只有预览），所以必须从代码层面（扫描历史消息）保证文件名一定能被提取并透传。SOP 作为防御性双保险。

### 修复点 2：SOP 模板加固（防御性）

**文件**：`script_writer_core/skills/script-orchestrator/sops/sop-split-script.md`

- 步骤 1（确认拆分需求）增加"**必须先识别长文本剧本文件名**"的强制规则
- 步骤 2（调用 splitter）的 task_description 拆分为两种模式：
  - **长文本模式**（>5000 字）：明确指示调用 `get_long_user_input(name="文件名")`，禁止传截断预览或字面占位符
  - **短文本模式**（≤5000 字）：保留原 `[剧本内容]` 占位符

### 修复点 3：文件名跨平台安全化

**文件**：
- `script_writer_core/agents/task_manager.py`：文件名生成逻辑
- `script_writer_core/mcp_tool.py`：`get_long_user_input` 工具的参数描述

旧格式 → 新格式：

```
旧: 14:57:23.txt                                    ← 冒号在 Windows 非法，精度仅到秒易碰撞
新: longinput_7_1_20260727_145723_123456_ab12cd.txt  ← 含 user/world 隔离 + 微秒 + uuid，跨平台安全
```

**向后兼容**：`get_long_user_input` 工具按完整文件名匹配读取，新格式正常工作；`_extract_long_input_filenames` 的正则用 `[^\s\n]+\.txt` 通配，**新旧文件名都能匹配**，已有历史数据不受影响。

## 数据流（修复后）

```
用户粘贴 >5000 字剧本
    ↓
task_manager.process_long_input()
    ├─ 完整内容落盘 → user_long_input/longinput_xxx.txt
    └─ PM 收到：截断预览 + "文件名：longinput_xxx.txt" 提示
    ↓
PM (orchestrator) 决定拆分，调用 call_agent(AgentName="novel-episode-splitter", ...)
    ↓
pm_agent._handle_agent_call():
    ├─ _extract_long_input_filenames() 扫描历史 → 提取 ["longinput_xxx.txt"]
    ├─ _build_long_input_hint() 构造读取指令
    └─ 注入子智能体的 task_description + conversation_history  ← 【修复点1】
    ↓
novel-episode-splitter 收到含文件名的明确指令
    ↓
splitter 调用 get_long_user_input(name="longinput_xxx.txt") → 读到完整剧本
    ↓
正常拆分 ✅
```

## 验证

- ✅ 三文件语法验证（`ast.parse`）
- ✅ lint 检查 `scripts/lint_blocking_calls.py` 通过（exit 0，无 R4/R6 红线违例）
- ✅ 端到端验证：`process_long_input` 生成新格式文件名 → pm_agent 正则正确提取 → 跨平台安全（无非法字符）
- ✅ 向后兼容：旧格式文件名 `14:57:23.txt` 仍能被正则匹配和工具读取

## 涉及文件

| 文件 | 改动 |
|------|------|
| `script_writer_core/agents/pm_agent.py` | 新增 `import re`、`_extract_long_input_filenames()`、`_build_long_input_hint()`；`_handle_agent_call` 注入文件名 |
| `script_writer_core/agents/task_manager.py` | `process_long_input` 文件名跨平台安全化 |
| `script_writer_core/mcp_tool.py` | `get_long_user_input` 工具参数描述更新 |
| `script_writer_core/skills/script-orchestrator/sops/sop-split-script.md` | 步骤1/2 增加长文本文件名识别与透传规则 |
