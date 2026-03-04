# 新建测试会话

创建一个新的测试会话。

**⚠️ 必读**: 参考 `.claude/skills/test-workflow.md` 了解会话管理规范。

## 执行步骤

1. 检查 `test_todo_list.json` 是否存在
   - 如果不存在，先运行 `python merge_test_cases.py` 合并测试用例
   - 等待合并完成后继续
2. 读取 `test_todo_list.json` 模板文件
3. 生成时间戳：`YYYYMMDD_HHMMSS` 格式
4. 创建 `test_sessions/session_{timestamp}.json`
5. 输出新会话文件路径

## 文件命名

```
test_sessions/session_20251220_170300.json
```

## 注意

- `test_todo_list.json` 是模板，永远不修改
- 所有测试进度保存在会话文件中

$ARGUMENTS
