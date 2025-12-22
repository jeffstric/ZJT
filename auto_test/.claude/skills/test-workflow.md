# 测试工作流规范

## 🔧 核心工具：test_navigator.py

**使用 Python 脚本获取下一个测试项和标记完成，避免上下文溢出！**

```bash
# 查看所有模块进度
python test_navigator.py --list

# 查看整体进度统计
python test_navigator.py --status

# 获取下一个待测试项（全局）
python test_navigator.py

# 获取指定模块的下一个测试
python test_navigator.py --module node_operations

# 查看某个功能的详细步骤
python test_navigator.py --feature node_005

# ⭐ 标记当前步骤为通过（必须指定模块）
python test_navigator.py --pass-current --module node_operations

# ⭐ 标记指定功能的某个步骤为通过
python test_navigator.py --pass node_005 1

# ⭐ 标记指定功能的所有步骤为通过
python test_navigator.py --pass node_005
```

## ⚠️ 上下文管理模式（防止容量爆掉）

**重要**: 为避免上下文溢出，每完成**一个功能**后必须结束当前会话！

**❌ 严格禁止**: 
- 不允许在测试未完成时提前标记为完成！
- 不允许在一个会话中测试多个功能！

### 会话粒度规则

```
⚠️ 每个功能 = 一个会话
⚠️ 功能完成后立即结束会话，启动新智能体继续
```

**示例：**
- node_005 测试完成 → 结束会话 → 新智能体测试 node_006
- auth_001 测试完成 → 结束会话 → 新智能体测试 auth_002

### 执行规则

1. 每次运行只测试**一个功能**（不是模块！）
2. 使用 `python test_navigator.py --module <ID>` 获取当前功能
3. 完成该功能的所有步骤后**立即结束会话**
4. 用户重新运行命令，新智能体继续下一个功能
5. **不要读取完整的 test_todo_list.json**（太大）
6. **使用 test_navigator.py** 获取精确的下一个测试步骤

## 文件职责

| 文件 | 用途 | 是否修改 |
|------|------|---------|
| `test_todo_list.json` | 主测试清单模板 | ❌ 不修改，不要读取（太大） |
| `test_navigator.py` | 测试导航脚本 | ❌ 只执行，获取下一个测试 |
| `test_config.json` | 配置文件（凭证、URL） | ❌ 只读取 |
| `test_sessions/session_*.json` | 当前测试会话 | ✅ 执行测试时修改这个 |

## 核心规则

### 1. 永远不要直接修改 `test_todo_list.json`

`test_todo_list.json` 是模板文件，保持所有 `pass: false` 状态，用于创建新会话。

### 2. 测试流程（使用 test_navigator.py）

```
┌─────────────────────────────────────────────────────────┐
│  1. 运行 python test_navigator.py --module <ID>         │
│     获取当前功能的待测试步骤                              │
├─────────────────────────────────────────────────────────┤
│  2. 执行该功能的所有测试步骤                              │
│     - 使用 MCP 工具执行操作                              │
│     - 验证预期结果                                       │
│     - 每完成一步就标记 pass: true                        │
├─────────────────────────────────────────────────────────┤
│  3. 功能的所有步骤完成后，标记功能为完成                   │
├─────────────────────────────────────────────────────────┤
│  4. ⚠️ 立即结束会话！不要继续测试下一个功能               │
├─────────────────────────────────────────────────────────┤
│  5. 用户重新运行命令，新智能体继续下一个功能               │
└─────────────────────────────────────────────────────────┘
```

**⚠️ 每个功能完成后必须结束会话，避免上下文溢出！**

### 3. 会话文件命名规则

```
test_sessions/session_YYYYMMDD_HHMMSS.json
```

示例：`test_sessions/session_20251220_170300.json`

### 4. 查找当前会话

**使用 test_navigator.py 自动处理**，脚本会：
1. 自动查找最新的会话文件
2. 如果没有会话，提示创建新会话
3. 输出当前待测试项的完整信息

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
