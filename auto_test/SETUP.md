# 环境配置指南

本文档介绍如何配置 Claude Code 和 playwright-mcp 扩展来运行自动化测试。

## 前置要求

- Node.js 24及以上
- npm 或 pnpm
- Claude Code（已安装并登录）
- Claude Code Router

## 安装 Claude Code Router

Claude Code Router 允许你使用其他大模型（如 DeepSeek）来替代 Anthropic 官方 API。

### 步骤 1：安装 Claude Code Router

```powershell
npm install -g @musistudio/claude-code-router
```

### 步骤 2：配置 config.json

创建配置文件 `~/.claude-code-router/config.json`：

```json
{
  "LOG": false,
  "LOG_LEVEL": "debug",
  "CLAUDE_PATH": "",
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "",
  "API_TIMEOUT_MS": "600000",
  "PROXY_URL": "",
  "transformers": [],
  "Providers": [
    {
      "name": "deepseek",
      "api_base_url": "https://api.deepseek.com/chat/completions",
      "api_key": "sk-xxxx",
      "models": [
        "deepseek-chat",
        "deepseek-reasoner"
      ],
      "transformer": {
        "use": [
          "deepseek"
        ]
      }
    }
  ],
  "StatusLine": {
    "enabled": false,
    "currentStyle": "default",
    "default": {
      "modules": []
    },
    "powerline": {
      "modules": []
    }
  },
  "Router": {
    "default": "deepseek,deepseek-chat",
    "background": "deepseek,deepseek-chat",
    "think": "deepseek,deepseek-chat",
    "longContext": "deepseek,deepseek-chat",
    "longContextThreshold": 60000,
    "webSearch": "",
    "image": ""
  },
  "CUSTOM_ROUTER_PATH": ""
}
```

> ⚠️ 请将 `api_key` 替换为你的 DeepSeek API Key

### 步骤 3：启动 Claude Code

使用 Router 启动 Claude Code：

```powershell
ccr code
```

修改配置后需要重启服务：

```powershell
ccr restart
```

### 可选：使用 UI 管理配置

```powershell
ccr ui
```

这会打开一个 Web 界面来管理配置。

---

## 安装 playwright-mcp

### ⚠️ 重要：必须全局安装

**playwright-mcp 只有在全局环境安装时才能正常启动浏览器。**

### 步骤 1：全局安装 playwright-mcp

```powershell
npm install -g @anthropic/mcp-playwright
```


### 步骤 2：确保已经安装chrome浏览器

如果没有安装，可以用以下命令安装
```powershell
npx playwright install
```

这会安装 Chromium、Firefox 和 WebKit 浏览器。

如果只需要 Chromium：

```powershell
npx playwright install chromium
```

### 步骤 3：配置 Claude Code MCP

在 Claude Code 中添加 MCP 服务器配置。

#### 方法 1：通过 Claude Code 命令

```
claude mcp add --scope user playwright -- npx @playwright/mcp@latest
```


### 步骤 4：验证安装

重启 Claude Code，然后运行：

```
/mcp
```

应该能看到 `playwright` 服务器状态为 `connected`。

## 常见问题

### 问题 1：MCP 服务器连接失败

**症状**：`1 MCP server failed`

**解决方案**：
1. 确保全局安装了 playwright-mcp
2. 确保安装了浏览器：`npx playwright install`
3. 重启 Claude Code

### 问题 2：浏览器启动失败

**症状**：`browser not found` 或 `executable doesn't exist`

**解决方案**：
```powershell
npx playwright install chromium --with-deps
```


## 测试配置

安装完成后，复制配置文件模板：

```powershell
cd auto_test
cp test_config.example.json test_config.json
```

编辑 `test_config.json`，填写：
- `base_url`: 被测试服务器地址
- `credentials.primary.phone`: 主测试账号手机号
- `credentials.primary.password`: 主测试账号密码
- `credentials.secondary.phone`: 副测试账号手机号（用于权限测试）
- `credentials.secondary.password`: 副测试账号密码

## 运行测试

```
/run-test
```

或使用项目经理模式：

```
/orchestrator
```

## 参考链接

- [Claude Code Router](https://github.com/musistudio/claude-code-router)
- [Playwright MCP](https://github.com/microsoft/playwright-mcp)
- [Playwright 官方文档](https://playwright.dev/)
- [Claude Code 文档](https://docs.anthropic.com/claude-code)
- [DeepSeek API](https://platform.deepseek.com/)
