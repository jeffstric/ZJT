# 视频工作流自动化测试项目

这是一个基于 playwright-mcp 的智能体浏览器自动化测试项目。

## 项目结构

```
auto_test/
├── CLAUDE.md                    # 本文件 - Claude Code 项目说明
├── test_config.example.json     # 配置文件模板（可提交到git）
├── test_config.json             # 实际配置文件（不提交到git，包含敏感信息）
├── test_todo_list.json          # 测试清单模板（不要修改！）
├── test_sessions/               # 测试会话记录目录（测试进度保存在这里）
└── .claude/
    ├── skills/                  # 技能规范
    │   └── test-workflow.md     # ⭐ 测试工作流规范（必读）
    └── commands/                # 自定义命令
        ├── run-test.md          # 执行测试
        ├── new-test-session.md  # 新建测试会话
        └── check-status.md      # 检查测试状态
```

## ⚠️ 重要规则

**开始任何测试操作前，必须先阅读 `.claude/skills/test-workflow.md`**

核心原则：
1. `test_todo_list.json` 是模板，**永远不要修改**
2. 所有测试进度保存在 `test_sessions/session_*.json`
3. 每个步骤通过后**立即**更新会话文件

## 配置文件说明

**重要**: 在开始测试前，必须先配置 `test_config.json`

### 获取配置信息

1. 复制 `test_config.example.json` 为 `test_config.json`
2. 填写以下信息：
   - `base_url`: 被测试服务器地址（如 http://localhost:8000）
   - `credentials.phone`: 测试账号手机号
   - `credentials.password`: 测试账号密码
   - `test_assets.test_image`: 测试用图片路径

### 配置文件格式

```json
{
  "base_url": "http://localhost:8000",
  "test_mode_param": "?test=1",
  "credentials": {
    "phone": "13800138000",
    "password": "your_password"
  },
  "test_assets": {
    "test_image": "/path/to/test_image.jpg"
  },
  "timeouts": {
    "page_load": 10,
    "api_response": 5,
    "file_upload": 15
  }
}
```

## 测试执行流程

### 1. 读取配置
每次测试前，先读取 `test_config.json` 获取：
- 服务器地址
- 登录凭证
- 测试资源路径

### 2. 执行测试
按照 `test_todo_list.json` 中的步骤执行：
- 使用 `mcp1_browser_snapshot` 获取页面元素的 ref
- 使用对应的 MCP 工具执行操作
- 验证预期结果

### 3. 更新状态
测试通过后，将 `pass` 字段更新为 `true`

## 可用命令

在 Claude Code 中使用以下命令：

- `/run-test` - 开始执行测试
- `/new-test-session` - 创建新的测试会话
- `/check-status` - 查看当前测试进度

## MCP 工具使用说明

### 获取元素 ref

```
1. 先调用 mcp1_browser_snapshot 获取页面快照
2. 从快照中找到目标元素的 ref 值
3. 使用该 ref 值调用 click/type 等操作
```

### 常用工具

| 工具 | 用途 |
|------|------|
| `mcp1_browser_navigate` | 导航到指定 URL |
| `mcp1_browser_snapshot` | 获取页面快照和元素 ref |
| `mcp1_browser_click` | 点击元素 |
| `mcp1_browser_type` | 输入文本 |
| `mcp1_browser_fill_form` | 填写表单 |
| `mcp1_browser_wait_for` | 等待文本出现 |
| `mcp1_browser_evaluate` | 执行 JavaScript |

## 测试优先级

- **P0**: 核心功能，必须通过
- **P1**: 重要功能，应该通过
- **P2**: 次要功能，可选通过

## 故障排除

### 找不到元素
- 确保先调用 `mcp1_browser_snapshot` 获取最新的页面状态
- 检查元素是否在可视区域内
- 等待页面加载完成

### 登录失败
- 检查 `test_config.json` 中的凭证是否正确
- 确认服务器正在运行

### 超时错误
- 增加 `timeouts` 配置中的时间
- 检查网络连接
