# 模块化测试用例结构说明

## 概述

为了避免 `test_todo_list.json` 文件过大（310KB+）导致智能体 token 快速消耗，测试用例已拆分为多个模块文件。

## 目录结构

```
auto_test/
├── test_modules/              # 模块化测试用例目录
│   ├── index.json            # 模块索引文件
│   ├── auth.json             # 用户认证模块 (6.6 KB)
│   ├── workflow_list.json    # 工作流列表模块 (17.3 KB)
│   ├── workflow_editor.json  # 工作流编辑器模块 (74.6 KB)
│   ├── node_operations.json  # 节点操作模块 (36.9 KB)
│   ├── error_handling.json   # 错误处理模块 (11.2 KB)
│   ├── timeline.json         # 视频时间轴模块 (37.7 KB)
│   ├── shot_frame_video.json # 镜头节点生成视频模块 (25.7 KB)
│   ├── world_management.json # 世界管理模块 (8.0 KB)
│   ├── character_management.json # 角色管理模块 (33.0 KB)
│   ├── location_management.json  # 场景管理模块 (7.5 KB)
│   └── shot_frame_first_frame.json # 分镜节点首帧模块 (15.9 KB)
├── test_todo_list.json       # 合并后的完整测试清单（自动生成）
├── split_test_cases.py       # 拆分脚本
├── merge_test_cases.py       # 合并脚本
├── fix_invalid_mcp_tools.py  # 修复无效 MCP 工具脚本
└── test_validation_report.txt # 验证报告
```

## 工作流程

### 1. 修改测试用例

**直接编辑模块文件**（推荐）：
```bash
# 编辑单个模块
vim test_modules/auth.json
```

**或编辑完整文件后重新拆分**：
```bash
# 编辑完整文件
vim test_todo_list.json

# 重新拆分
python split_test_cases.py
```

### 2. 启动测试前合并

测试启动时自动合并所有模块文件：
```bash
# 合并所有模块为 test_todo_list.json
python merge_test_cases.py
```

### 3. 验证测试用例

检查测试用例是否适合 playwright-mcp 端到端测试：
```bash
# 拆分时会自动验证
python split_test_cases.py

# 查看验证报告
cat test_validation_report.txt
```

### 4. 修复已知问题

为无效的 MCP 工具调用添加 remark 标记：
```bash
python fix_invalid_mcp_tools.py
```

## 验证发现的问题

### 无效的 MCP 工具（15个问题）

以下 MCP 工具在 playwright-mcp 中不存在，已在相关步骤的 `remark` 字段中标记：

1. **mcp1_browser_drag** (6处)
   - 建议：使用 `mcp1_browser_evaluate` 执行 JavaScript 拖拽代码
   - 涉及模块：workflow_editor, timeline, shot_frame_first_frame

2. **mcp1_browser_console_messages** (4处)
   - 建议：使用 `mcp1_browser_evaluate` 或 `mcp1_browser_network_requests`
   - 涉及模块：workflow_editor, shot_frame_video, character_management

3. **mcp1_browser_reload** (1处)
   - 建议：使用 `mcp1_browser_navigate` 重新访问页面
   - 涉及模块：node_operations

4. **mcp1_browser_press_key** (1处)
   - 建议：使用 `mcp1_browser_evaluate` 触发键盘事件
   - 涉及模块：timeline

5. **mcp1_browser_hover** (1处)
   - 建议：使用 `mcp1_browser_evaluate` 触发 mouseover 事件
   - 涉及模块：timeline

### 不适合端到端测试的操作（1个问题）

- **character_006 步骤6**：验证角色卡ID从数据库加载成功
  - 问题：涉及数据库操作，不适合纯端到端测试
  - 建议：通过 UI 操作验证或调整测试策略

### 缺少验证点（1个问题）

- **character_010 步骤2**：缺少 expected_result 或 verify 字段
  - 建议：补充预期结果

## 可用的 MCP 工具

Playwright MCP 支持的工具列表：

- `mcp1_browser_navigate` - 导航到 URL
- `mcp1_browser_snapshot` - 获取页面快照
- `mcp1_browser_click` - 点击元素
- `mcp1_browser_type` - 输入文本
- `mcp1_browser_fill_form` - 填写表单
- `mcp1_browser_select_option` - 选择下拉选项
- `mcp1_browser_file_upload` - 上传文件
- `mcp1_browser_wait_for` - 等待元素/文本出现
- `mcp1_browser_evaluate` - 执行 JavaScript
- `mcp1_browser_network_requests` - 检查网络请求
- `mcp1_browser_close` - 关闭浏览器
- `mcp1_browser_run_code` - 运行代码

## 优势

### Token 消耗优化
- **原文件**：310 KB，一次性加载消耗大量 token
- **模块文件**：最大 74.6 KB（workflow_editor），按需加载
- **节省**：智能体只需加载当前测试的模块，token 消耗减少 70%+

### 维护性提升
- 模块独立，修改影响范围小
- 便于并行开发和测试
- 易于版本控制和代码审查

### 自动验证
- 拆分时自动检查 MCP 工具有效性
- 识别不适合端到端测试的操作
- 生成详细的验证报告

## 注意事项

1. **test_todo_list.json 是自动生成的**
   - 不要直接编辑此文件（除非要重新拆分）
   - 修改应在 `test_modules/` 目录中的模块文件进行

2. **启动测试前必须合并**
   - `test_navigator.py` 仍然读取 `test_todo_list.json`
   - 运行 `python merge_test_cases.py` 生成最新版本

3. **remark 字段的作用**
   - 记录测试细节和发现
   - 标记已知问题和替代方案
   - 不要删除自动添加的问题标记

## 集成到现有工作流

### 更新 setup_test_env.py

在环境初始化时自动合并测试用例：

```python
# 在 setup_test_env.py 中添加
print_info("合并测试用例...")
subprocess.run([sys.executable, "merge_test_cases.py"], check=True)
print_ok("测试用例已合并")
```

### 更新 test_navigator.py

test_navigator.py 无需修改，继续使用合并后的 test_todo_list.json。

### Git 管理建议

```bash
# 提交模块文件
git add test_modules/

# 忽略合并后的文件（可选）
echo "test_todo_list.json" >> .gitignore

# 或者两者都提交（推荐）
git add test_modules/ test_todo_list.json
```

## 脚本说明

### split_test_cases.py
- 将 test_todo_list.json 拆分为多个模块文件
- 自动验证测试用例的合理性
- 生成验证报告

### merge_test_cases.py
- 将所有模块文件合并为 test_todo_list.json
- 测试启动前必须运行

### fix_invalid_mcp_tools.py
- 为无效的 MCP 工具调用添加 remark 标记
- 提供替代方案建议
- 标记不适合端到端测试的操作
