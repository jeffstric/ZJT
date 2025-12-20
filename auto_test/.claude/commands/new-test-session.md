# 新建测试会话

创建一个新的测试会话。

**⚠️ 必读**: 参考 `.claude/skills/test-workflow.md` 了解会话管理规范。

## 执行步骤

1. 读取 `test_todo_list.json` 模板文件
2. 生成时间戳：`YYYYMMDD_HHMMSS` 格式
3. 创建 `test_sessions/session_{timestamp}.json`
4. 输出新会话文件路径

## 文件命名

```
test_sessions/session_20251220_170300.json
```

## 注意

- `test_todo_list.json` 是模板，永远不修改
- 所有测试进度保存在会话文件中

$ARGUMENTS
