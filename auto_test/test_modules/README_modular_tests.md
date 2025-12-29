# 模块化测试用例结构说明

## 概述

为了避免 `test_todo_list.json` 文件过大（310KB+）导致智能体 token 快速消耗，测试用例已拆分为多个模块文件。
所有的测试用例都是给 智能体参考的端到端测试用例，请确保测试用例是否符合端到端测试的逻辑。已知会使用playwright-mcp作为测试工具。

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
└── merge_test_cases.py       # 合并脚本
```

## 工作流程

### 1. 首次设置或重置测试

**只在以下情况运行合并脚本**：
- 首次设置环境（`test_todo_list.json` 不存在）
- 修改了测试用例后，需要应用更改
- 测试全部完成，需要重置进度重新开始

```bash
# 合并所有模块为 test_todo_list.json
python merge_test_cases.py
```

⚠️ **警告**：合并会覆盖 `test_todo_list.json`，所有测试进度会丢失！

### 2. 修改测试用例

**直接编辑模块文件**：
```bash
# 编辑单个模块
vim test_modules/auth.json
```

**等待测试完成后再合并**，否则会丢失进度。

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


## 注意事项

1. **test_todo_list.json 是自动生成的**
   - 不要直接编辑此文件（除非要重新拆分）
   - 修改应在 `test_modules/` 目录中的模块文件进行

2. **启动测试前必须合并**
   - `test_navigator.py` 仍然读取 `test_todo_list.json`
   - 运行 `python merge_test_cases.py` 生成最新版本

3. **remark 字段的作用**
   - 供测试工程师记录测试细节和发现
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


## 脚本说明

### merge_test_cases.py
- 将所有模块文件合并为 test_todo_list.json
- 测试启动前必须运行
