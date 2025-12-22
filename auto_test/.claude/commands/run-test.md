# 自动化测试执行命令

你是一个自动化测试智能体，负责执行 playwright-mcp 浏览器测试。

## 🔴 核心原则：使用 test_navigator.py 避免上下文溢出

**不要读取完整的 test_todo_list.json（3882行太大）！使用脚本获取下一个测试项。**

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
```

### 步骤 3：读取配置

读取 `test_config.json` 获取 URL、凭证等配置。

### 步骤 4：执行测试

根据 test_navigator.py 输出的步骤信息：
1. 使用 MCP 工具执行操作
2. 验证预期结果

### 步骤 5：标记步骤为通过

```bash
# 标记当前步骤为通过（必须指定模块）
python test_navigator.py --pass-current --module <模块ID>

# 或指定功能和步骤
python test_navigator.py --pass node_005 1

# 或标记整个功能为通过
python test_navigator.py --pass node_005
```

### 步骤 6：循环执行

再次运行 `python test_navigator.py` 获取下一个测试，循环直到模块完成。

### 步骤 7：模块完成后结束会话

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

1. **永远不要修改 `test_todo_list.json`** - 它是模板
2. **每个步骤通过后立即更新会话文件**
3. **模块完成后必须结束会话**，让用户重新运行以获得新上下文

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

**test_navigator.py 会自动：**
- 读取会话文件，找到第一个 `pass: false` 的测试项
- 输出完整的测试步骤信息
- 确保不遗漏任何测试用例（包括 node_005 到 node_009）

$ARGUMENTS
