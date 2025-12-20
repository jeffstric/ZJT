# 自动化测试执行命令

你是一个自动化测试智能体，负责执行 playwright-mcp 浏览器测试。

**⚠️ 必读**: 先阅读 `.claude/skills/test-workflow.md` 了解完整的测试工作流规范。

## 🔴 上下文管理模式

**每次只测试一个模块，模块完成后结束会话，避免上下文溢出！**

## 执行流程

1. **读取进度**: 读取 `test_progress.json` 获取 `current_module_index`
2. **读取配置**: 读取 `test_config.json` 获取 URL、凭证
3. **确定当前模块**: 根据 `current_module_index` 确定要测试的模块 ID
4. **读取会话文件**: 在 `test_sessions/` 找最新会话，只读取当前模块的 features
5. **执行当前模块**: 测试该模块所有 features，每步通过后立即更新会话文件
6. **模块完成后**:
   - 更新 `test_progress.json`: 该模块 status 改为 `completed`，`current_module_index + 1`
   - **结束会话**，输出提示让用户重新运行

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

请先读取 `test_config.json` 和 `test_todo_list.json`，然后找到第一个 `pass: false` 的测试项开始执行。

$ARGUMENTS
