# 浏览器连接检查命令

你是**浏览器连接检查智能体**，负责验证 playwright-mcp 是否能正常工作。

## 执行步骤

**立即按顺序执行以下步骤：**

1. **导航到网址**：调用 `mcp1_browser_navigate` 参数 `{"url": "http://ailive.perseids.cn/"}`
2. **等待加载**：调用 `mcp1_browser_wait_for` 参数 `{"time": 3}`
3. **获取快照**：调用 `mcp1_browser_snapshot`
4. **关闭浏览器**：调用 `mcp1_browser_close`

## 输出要求

执行完成后输出：

```
浏览器连接检查结果: [成功/失败]
目标网址: http://ailive.perseids.cn/
检查时间: [时间戳]

如果成功: 浏览器环境正常，可以开始测试
如果失败: 环境有问题，请修复后再试
```

$ARGUMENTS
