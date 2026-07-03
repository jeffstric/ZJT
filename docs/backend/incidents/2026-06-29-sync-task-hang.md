# 2026-06-29 SyncTask 卡死事故记录

## 现象

线上 `api_requests.log` 出现约 2 小时无外部驱动请求日志：

```text
2026-06-29 15:06:23,793 - api_requests - INFO - ========== API 请求结束 ==========
2026-06-29 17:07:25,046 - api_requests - INFO - ========== API 请求开始 ==========
```

该日志来自 `task/visual_drivers/base_video_driver.py::_request()`，表示外部驱动 HTTP 调用日志，不等同于 FastAPI 访问日志。

## 推断根因

`SyncTaskExecutor` 原先只在 `future.done()` 后清理 `_futures`。如果同步 worker 卡死，future 长期不完成，会永久占用进程池槽位。槽位耗尽后，新同步任务无法继续发起外部请求，表现为外部 API 请求日志长时间空窗。

图床上传也存在类似风险：同步 wrapper 使用局部 `ThreadPoolExecutor` 后直接 `future.result()`，没有 timeout；如果底层 SDK 或网络卡住，调用线程会一直等待。

## 修复项

- SyncTask submit 保存 implementation、提交时间、任务类型等元数据。
- stale timeout 使用白名单制，默认不 kill。
- Seedream 配置 stale timeout；Seedance 等提交后轮询任务不进入 SyncTask stale 白名单。
- stale timeout 触发后释放 future/worker，标记 pool broken，并走统一失败处理。
- 孤儿恢复先 `force_release_task(..., refund=False)`，再重置数据库状态，避免退款后继续重试。
- 图床上传增加 storage 总超时和 sync wrapper 真超时。
- CI 新增阻塞调用 lint，禁止无 timeout 的 `Future.result()` 和 `with ThreadPoolExecutor()` 假超时写法。
- `AGENTS.md`、`.windsurfrules`、`.claude/CLAUDE.md`、根级 `CLAUDE.md` 同步超时红线。

## 验证项

- `tests/task/test_sync_task_stale_recovery.py`
- `tests/utils/test_image_upload_utils_timeout.py`
- `tests/scripts/test_lint_blocking_calls.py`
- `python scripts/lint_blocking_calls.py --allow-file scripts/lint_blocking_calls_allowlist.txt`

## 回滚

若 stale kill 行为异常，可临时配置：

```yaml
sync_task:
  stale_detection_enabled: false
```

该开关只关闭 stale kill，不回滚 submit 返回值检查、图床超时、异常退避和 CI lint。
