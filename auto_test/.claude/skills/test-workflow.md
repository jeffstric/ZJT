# 测试工作流规范

## 多智能体架构

本项目支持两种运行模式：

### 模式 1: 单智能体 + 外部脚本
```
run_all_tests.ps1 → 循环调用 claude /run-test
```

### 模式 2: 多智能体协作（推荐）
```
/orchestrator (项目经理)
    ├── Task: /test-module auth
    ├── Task: /test-module workflow_list
    ├── Task: /test-module workflow_editor
    └── Task: /test-module node_operations
```

**项目经理智能体** (`/orchestrator`):
- 读取进度，调度任务
- 为每个模块创建 Task
- 等待结果，更新进度

**测试工程师智能体** (`/test-module {模块ID}`):
- 执行指定模块的测试
- 更新会话文件和进度
- 返回测试结果

## ⚠️ 上下文管理模式

**重要**: 为避免上下文溢出，每个**模块**完成后结束当前会话，由用户重新运行命令继续。

### 执行规则

1. 每次运行只测试**一个模块**
2. 模块内的 features 持续执行，不询问用户
3. 当前模块所有 features 完成后：
   - 更新 `test_progress.json` 中该模块状态为 `completed`
   - 更新 `current_module_index` 指向下一个模块
   - **结束会话**，输出"模块 XXX 测试完成，请重新运行 /run-test 继续下一模块"
4. 用户重新运行 `/run-test`，智能体读取进度，从新模块开始（全新上下文）

### 进度文件

`test_progress.json` 记录当前进度：
```json
{
  "current_module_index": 0,
  "modules": [
    { "id": "auth", "status": "pending" },
    { "id": "workflow_list", "status": "pending" }
  ]
}
```

## 文件职责

| 文件 | 用途 | 是否修改 |
|------|------|---------|
| `test_todo_list.json` | 主测试清单模板 | ❌ 不修改 |
| `test_config.json` | 配置文件（凭证、URL） | ❌ 只读取 |
| `test_progress.json` | 模块进度索引 | ✅ 模块完成后更新 |
| `test_sessions/session_*.json` | 当前测试会话 | ✅ 执行测试时修改这个 |

## 核心规则

### 1. 永远不要直接修改 `test_todo_list.json`

`test_todo_list.json` 是模板文件，保持所有 `pass: false` 状态，用于创建新会话。

### 2. 测试流程

```
┌─────────────────────────────────────────────────────────┐
│  1. 读取 test_config.json 获取配置                       │
├─────────────────────────────────────────────────────────┤
│  2. 检查 test_sessions/ 目录是否有未完成的会话            │
│     - 如果有：继续使用该会话文件                          │
│     - 如果没有：从 test_todo_list.json 复制创建新会话     │
├─────────────────────────────────────────────────────────┤
│  3. 在会话文件中找到第一个 pass: false 的测试项           │
├─────────────────────────────────────────────────────────┤
│  4. 执行测试步骤                                         │
├─────────────────────────────────────────────────────────┤
│  5. 【立即】将通过的步骤 pass 改为 true（修改会话文件）    │
├─────────────────────────────────────────────────────────┤
│  6. 继续下一个步骤，循环执行                              │
└─────────────────────────────────────────────────────────┘
```

### 3. 会话文件命名规则

```
test_sessions/session_YYYYMMDD_HHMMSS.json
```

示例：`test_sessions/session_20251220_170300.json`

### 4. 查找当前会话

```python
# 伪代码
sessions = list_files("test_sessions/*.json")
if sessions:
    current_session = sessions[-1]  # 最新的会话
else:
    current_session = create_new_session()
```

### 5. 创建新会话

1. 读取 `test_todo_list.json` 全部内容
2. 生成时间戳文件名
3. 写入 `test_sessions/session_{timestamp}.json`
4. 返回新会话文件路径

## 状态更新规则

### 步骤级别
每个 test_step 执行成功后，**立即**修改会话文件：
```json
{ "step": 1, "pass": false }  →  { "step": 1, "pass": true }
```

### Feature 级别
当一个 feature 的所有 test_steps 都是 `pass: true` 时，将该 feature 的 `pass` 也改为 `true`

### Module 级别
当一个 module 的所有 features 都是 `pass: true` 时，该模块测试完成

## 变量替换规则

测试清单中的 `${config.xxx}` 变量需要从 `test_config.json` 读取并替换：

| 变量 | 来源 |
|------|------|
| `${config.base_url}` | test_config.json → base_url |
| `${config.credentials.phone}` | test_config.json → credentials.phone |
| `${config.credentials.password}` | test_config.json → credentials.password |
| `${config.test_assets.test_image}` | test_config.json → test_assets.test_image |

## 错误处理

1. 步骤失败时，记录错误信息到会话文件的 `error` 字段
2. 跳过当前 feature，继续下一个 feature
3. 不要因为一个失败就停止整个测试
