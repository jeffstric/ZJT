# 自动化测试执行命令

你是一个自动化测试智能体，负责执行 playwright-mcp 浏览器测试。

## 🔴 核心原则：使用 test_navigator.py 避免上下文溢出

**不要读取 test_modules/ 目录下的测试用例文件！使用脚本获取下一个测试项。**

## 执行流程

### 步骤 1：查看测试进度

```bash
python test_navigator.py --status
```

### 步骤 2：获取下一个待测试项

```bash
# 全局下一个测试
python test_navigator.py

# 或指定模块
python test_navigator.py --module node_operations

# 跳过已处理的测试（只显示未处理的）
python test_navigator.py --skip-processed
```

### 步骤 3：读取配置

读取 `test_config.json` 获取 URL、凭证等配置。

### 步骤 4：执行测试

根据 test_navigator.py 输出的步骤信息：
1. 使用 MCP 工具执行操作
2. 验证预期结果

### 步骤 5：标记步骤状态

**⭐ 新功能：支持 pass 和 is_processed 双字段标记**

每个测试步骤都有两个状态字段：
- `pass`: 测试是否通过（true/false）
- `is_processed`: 是否已处理（true/false）- 即使测试失败也可以标记为已处理
- `remark`: 备注信息，记录测试过程中的细节和观察结果

#### 5.1 单个步骤标记

```bash
# 标记单个步骤为通过且已处理（必须提供备注）
python test_navigator.py --mark auth_001 1 --set-pass true --set-processed true --remark "登录界面显示正常，所有元素加载完成，用户信息正确显示"

# 标记单个步骤为失败但已处理（跳过该步骤）
python test_navigator.py --mark auth_001 1 --set-pass false --set-processed true --remark "登录按钮无响应，已确认为已知bug"
```

#### 5.2 整个功能统一标记

```bash
# 标记整个功能的所有步骤为相同状态（批量操作，系统会记录警告）
python test_navigator.py --mark auth_001 --set-pass true --set-processed true --remark "完整测试了所有9个步骤，登录流程正常，token验证通过"

# 标记整个功能为失败但已处理
python test_navigator.py --mark auth_001 --set-pass false --set-processed true --remark "功能存在多个bug，已记录详细问题清单"
```

#### 5.3 批量混合标记（新功能）

**适用场景**：当需要将部分步骤标记为成功，部分步骤标记为失败时使用。

```bash
# 批量混合标记：步骤1-3成功，步骤4-6失败
python test_navigator.py --mark-batch auth_001 --batch-config '{
  "remark": "登录功能测试：前3步正常，后3步存在问题",
  "steps": [
    {"step": 1, "pass": true, "processed": true, "remark": "首页加载正常，响应时间2秒"},
    {"step": 2, "pass": true, "processed": true, "remark": "登录按钮点击成功，模态框显示"},
    {"step": 3, "pass": true, "processed": true, "remark": "表单填写完成，验证通过"},
    {"step": 4, "pass": false, "processed": true, "remark": "登录请求失败，返回500错误"},
    {"step": 5, "pass": false, "processed": true, "remark": "页面未跳转，仍在登录页"},
    {"step": 6, "pass": false, "processed": true, "remark": "localStorage中无token信息"}
  ]
}'
```

**JSON配置说明**：
- `remark`: 必填，整体备注信息
- `steps`: 步骤配置数组
  - `step`: 步骤号
  - `pass`: 是否通过（true/false）
  - `processed`: 是否已处理（true/false）
  - `remark`: 可选，步骤级备注（优先于整体备注）

**⚠️ Windows PowerShell 注意事项**：
如果在 Windows PowerShell 中遇到 JSON 解析错误，建议：
1. 使用 WSL（Windows Subsystem for Linux）
2. 或将 JSON 保存为文件，然后读取文件内容

**字段说明：**
- `--set-pass`: 必填，设置测试是否通过（true/false）
- `--set-processed`: 必填，设置是否已处理（true/false）
- `--remark`: **必填**，添加备注信息（防止测试工程师走捷径）

**使用场景：**
- 测试通过：`--set-pass true --set-processed true`
- 测试失败但已确认：`--set-pass false --set-processed true`（跳过该测试）
- 测试未完成：`--set-pass false --set-processed false`（待后续处理）

**备注字段的作用：**
- **必填要求**：防止测试工程师走捷径，确保真实执行测试
- 记录测试过程中的具体发现和观察结果
- 保存重要的测试细节（如界面状态、响应时间、API响应等）
- 为后续测试和问题排查提供参考
- 便于生成详细的测试报告
- **审计追踪**：所有标记操作都会记录时间戳，便于调查测试质量

### 步骤 6：功能完成后立即结束会话

**⚠️ 每个功能 = 一个会话，避免上下文溢出！**

当前功能的所有步骤完成后：
1. 确认该功能所有步骤都标记为 `is_processed: true`
2. **立即结束会话**
3. 用户重新运行命令，新智能体继续下一个功能

**❌ 禁止在一个会话中测试多个功能！**

### 步骤 7：验证模块(module)完成

**重要：在结束会话前，必须验证模块是否真正完成！**

**❌ 严格禁止**: 不允许提前标记模块完成！必须先完成所有测试步骤。

阅读 `.claude/skills/module-completion-check.md` 并执行验证：

```bash
# 1. 检查模块状态
python test_navigator.py --list

# 2. 验证无待测试项
python test_navigator.py --module <模块ID>

# 3. 确认步骤完成率为 100%
```

**只有在步骤显示 X/X（100%）时才能结束会话！**

**禁止行为示例：**
- ❌ "这个测试很复杂，我先标记模块完成"
- ❌ "大部分测试都通过了，先标记完成"
- ❌ "剩下的应该会通过，先标记完成"

### 步骤 8：模块完成后结束会话

输出完成信息，让用户重新运行继续下一模块。

### URL 拼接规则

**测试模式**时，根据 URL 是否已有参数决定使用 `?` 还是 `&`：

| 原始 URL | 拼接后 |
|----------|--------|
| `${base_url}/page` | `${base_url}/page?test=1` |
| `${base_url}/page?id=1` | `${base_url}/page?id=1&test=1` |

**判断逻辑**：
- URL 包含 `?` → 追加 `&test=1`
- URL 不包含 `?` → 追加 `?test=1`

**真实模式**：URL 保持不变

## 核心规则

1. **永远不要修改 `test_todo_list.json`** - 它是模板，所有修改都在会话文件中
2. **每个步骤完成后立即标记状态** - 使用 `--mark` 或 `--mark-batch` 命令更新会话文件
3. **正确使用双字段标记**：
   - 测试通过：`--set-pass true --set-processed true`
   - 测试失败但已确认：`--set-pass false --set-processed true`
4. **选择合适的标记方式**：
   - 单个步骤：使用 `--mark feature_id step_num`
   - 整个功能统一状态：使用 `--mark feature_id`
   - 部分成功部分失败：使用 `--mark-batch feature_id --batch-config`
5. **使用 `--skip-processed` 跳过已处理的测试** - 避免重复测试
6. **模块完成后必须结束会话**，让项目经理智能体 重新运行以获得新上下文
7. **必须为每个步骤添加备注** - 记录测试细节，提高测试质量，防止走捷径

## 标记操作最佳实践

### 何时使用批量混合标记
- 测试过程中发现部分步骤成功，部分步骤失败
- 需要详细记录每个步骤的具体测试结果
- 避免多次单独标记操作

### 备注质量要求
- 至少5个字符，建议20个字符以上
- 包含具体的测试结果和观察
- 记录重要的技术细节（响应时间、状态码、界面状态等）
- 失败步骤必须说明失败原因

### 审计和追踪
- 所有标记操作都会记录时间戳
- 批量操作会被特别标识和记录
- 系统会生成操作日志便于质量审查

## 备注字段使用指南

**什么时候应该添加备注：**
- 界面显示异常但测试仍通过时
- 发现性能问题（如加载缓慢）时
- 测试步骤有特殊操作或发现时
- 需要记录具体的测试数据或结果时

**备注内容示例：**
- "界面加载正常，响应时间约2秒，所有元素显示完整"
- "登录成功，跳转到工作流列表页面，用户信息显示正确"
- "视频上传完成，预览显示正常，文件大小验证通过"
- "API请求返回正确，数据格式符合预期，状态码200"
- "测试通过，但发现按钮样式略有偏移，功能正常"

**⚠️ 重要提醒：备注现在是必填项！**
- 系统会强制检查备注内容，不能为空或过短（少于5个字符）
- 批量标记操作会被特别记录，包含时间戳和操作日志
- 所有标记操作都会记录 `marked_at` 和 `marked_by` 字段
- 批量混合标记会被特别标识为 `batch_operation: true`
- 这些措施是为了防止测试工程师走捷径，确保测试质量

## 模块完成时的操作

1. 更新 `test_progress.json`:
   - 当前模块 status 改为 `completed`
   - `current_module_index` 加 1
2. 输出完成信息后**立即结束**，不要继续操作

```
✅ 模块 [模块名] 测试完成！
进度: 1/4 模块已完成
```

## 自动化运行

用户可以运行 `run_all_tests.ps1` 脚本自动执行所有模块：
```powershell
./run_all_tests.ps1
```
脚本会循环调用 claude，每个模块在独立上下文中运行。

## MCP 工具映射

```
mcp1_browser_navigate - 导航到URL
mcp1_browser_click - 点击元素
mcp1_browser_type - 输入文本
mcp1_browser_snapshot - 获取页面快照（用于找元素 ref）
mcp1_browser_fill_form - 填写表单
mcp1_browser_select_option - 选择下拉选项
mcp1_browser_file_upload - 上传文件
mcp1_browser_wait_for - 等待元素/文本出现
mcp1_browser_evaluate - 执行 JavaScript
mcp1_browser_network_requests - 检查网络请求
```

## 开始执行

**⚠️ 重要：使用 test_navigator.py 确保不遗漏测试用例**

```bash
# 1. 先查看整体进度
python test_navigator.py --status

# 2. 获取下一个待测试项
python test_navigator.py

# 3. 或指定模块测试
python test_navigator.py --module <模块ID>
```

**注意**：不要在测试过程中运行 `merge_test_cases.py`，这会覆盖已有的测试进度！

**test_navigator.py 会自动：**
- 找到第一个 `pass: false` 且 `is_processed: false` 的测试项
- 输出完整的测试步骤信息（包括 `[PROCESSED]` 状态标记）
- 确保不遗漏任何测试用例
- 支持为每个步骤添加 `remark` 备注字段
- 支持 `--skip-processed` 参数跳过已处理的测试

**项目工程师须知：**
- 测试清单中每个步骤都有 `remark` 字段
- 测试智能体可以在标记步骤通过时添加备注
- 备注信息会保存在会话文件中，用于测试报告生成

$ARGUMENTS
