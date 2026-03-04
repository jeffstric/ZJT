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

**简短状态**：
```
📊 当前测试状态
━━━━━━━━━━━━━━━━
✅ auth - 已完成
🔄 workflow_list - 进行中  
⏳ workflow_editor - 待测试
⏳ node_operations - 待测试

总进度: 2/4 (50%)
```

**详细报告**：生成 HTML 文件
```python
python generate_report.py
```

$ARGUMENTS
