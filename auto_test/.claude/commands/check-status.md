# 检查测试状态

检查当前测试进度和状态。

**⚠️ 必读**: 参考 `.claude/skills/test-workflow.md` 了解文件职责。

## 执行步骤

1. 查找 `test_sessions/` 目录中最新的会话文件
2. 如果没有会话文件，提示用户先运行 `/new-test-session`
3. 统计各模块的测试通过情况
4. 列出未通过的测试项
5. 给出下一步建议

## 输出格式

```
=== 测试状态报告 ===
会话文件: test_sessions/session_20251220_170300.json

模块: auth (用户认证)
  ✅ auth_001 用户登录功能
  ❌ auth_002 用户登出功能

模块: workflow_list (工作流列表)
  ❌ list_001 访问工作流列表页
  ...

总进度: 5/20 (25%)
下一个待测试: auth_002
```

$ARGUMENTS
