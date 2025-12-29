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

# ⭐ 标记当前步骤为通过并添加备注
python test_navigator.py --pass-current --module node_operations --remark "界面显示正常，功能测试通过"

# ⭐ 标记指定功能的某个步骤为通过
python test_navigator.py --pass node_005 1

# ⭐ 标记指定步骤为通过并添加备注
python test_navigator.py --pass node_005 1 --remark "节点创建成功，所有字段显示正确"

# ⭐ 标记指定功能的所有步骤为通过
python test_navigator.py --pass node_005

# ⭐ 标记整个功能为通过并添加备注
python test_navigator.py --pass node_005 --remark "所有测试步骤完成，功能运行正常"
```

## 智能体分工模式

**测试工程师**：每完成一个功能后立即停止，返回结果给项目经理
**项目经理**：持续运行，调度下一个功能，直到所有测试完成或卡住

**重要提醒：**
- 测试清单中每个步骤都有 `remark` 字段
- 测试智能体应该充分利用备注功能记录测试细节
- 项目工程师可以通过备注了解测试过程中的具体发现

### 测试工程师规则

```
测试工程师：完成一个功能 → 立即停止 → 返回结果
项目经理：收到结果 → 调度下一个功能 → 继续循环
```

**示例：**
- 测试工程师完成 node_005 → 停止并返回结果
- 项目经理收到结果 → 创建新任务测试 node_006
- 测试工程师完成 node_006 → 停止并返回结果
- ...直到所有功能完成

### 测试工程师执行规则

1. 每次运行只测试**一个功能**（不是模块！）
2. 使用 `python test_navigator.py --feature <功能ID>` 获取功能详情
3. 完成该功能的所有步骤后**立即停止**
4. **项目经理会自动调度下一个功能**
5. **不要读取完整的 test_todo_list.json**（太大）
6. **使用 test_navigator.py** 获取精确的下一个测试步骤
7. **建议为每个步骤添加备注** - 记录测试细节和发现

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
│  1. 运行 python test_navigator.py --feature <功能ID>     │
│     获取当前功能的待测试步骤                              │
├─────────────────────────────────────────────────────────┤
│  2. 执行该功能的所有测试步骤                              │
│     - 使用 MCP 工具执行操作                              │
│     - 验证预期结果                                       │
│     - 每完成一步就标记 pass: true                        │
├─────────────────────────────────────────────────────────┤
│  3. 功能的所有步骤完成后，标记功能为完成                   │
├─────────────────────────────────────────────────────────┤
│  4. 立即停止！返回结果给项目经理                          │
├─────────────────────────────────────────────────────────┤
│  5. 项目经理会自动调度下一个功能                          │
└─────────────────────────────────────────────────────────┘
```

**测试工程师：功能完成后立即停止，项目经理会继续调度！**

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
{ "step": 1, "pass": false, "remark": "" }  →  { "step": 1, "pass": true, "remark": "测试通过，界面显示正常" }
```

**备注字段说明：**
- 每个测试步骤都有 `remark` 字段用于记录测试细节
- 测试智能体可以在标记步骤通过时添加备注信息
- 备注内容应包含具体的测试发现和观察结果

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
4. 失败的步骤也可以在 `remark` 字段中记录失败原因和具体现象

## 备注字段最佳实践

**何时添加备注：**
- 测试步骤有特殊发现或异常现象
- 界面响应时间异常（过快或过慢）
- 发现潜在的用户体验问题
- 测试数据或结果需要记录
- 步骤执行过程中的重要观察

**备注内容示例：**
- "页面加载时间约3秒，响应正常"
- "按钮点击后立即响应，无延迟"
- "模态框弹出位置略偏右，但功能正常"
- "API返回数据格式正确，包含预期字段"
- "文件上传成功，预览图片清晰"
