---
id: 2026-06-29-sync-task-hang
patch: patches/2026-06-29-sync-task-hang.json
tests:
  - tests/task/test_sync_task_stale_recovery.py
  - tests/utils/test_image_upload_utils_timeout.py
  - tests/scripts/test_lint_blocking_calls.py
replay_tests:
  - tests/task/test_sync_task_stale_recovery.py::test_stale_whitelisted_future_triggers_pool_rebuild_and_refund
  - tests/task/test_sync_task_stale_recovery.py::test_stale_skips_rebuild_when_executor_not_running
  - tests/utils/test_image_upload_utils_timeout.py::test_upload_local_images_sync_returns_empty_on_timeout
  - tests/utils/test_image_upload_utils_timeout.py::test_upload_local_images_to_cdn_wraps_storage_upload_timeout
feature_ids:
---

## 当时坏成什么样

同步任务的 worker 卡死后，进程池槽位不释放。槽位满了，新任务不再发出外部请求，外部请求日志能空大约两小时。图床上传的 `future.result()` 没有超时，底层卡住时调用方会一直等。

## 代码大概在哪

- `task/sync_task_executor.py`
- `utils/image_upload_utils.py`
- `scripts/lint_blocking_calls.py`

## 怎么操作、怎样算没修好

改坏补丁动了三处，对应事故的两半：

1. `task/sync_task_executor.py` `check_results()`：删掉 `if not future.done():` 之后的两行 stale 检测分支入口，future 未完成时直接 `continue`——回到当年「卡死的 future 永远占着进程池槽位」的行为。
2. `utils/image_upload_utils.py` `_run_coro_sync()`：内层 `asyncio.run(asyncio.wait_for(coro, timeout=timeout))` 去掉 wait_for 包装，直接 `asyncio.run(coro)`——同步包装失去真超时，回到当年「调用方一直等」的行为。
3. `utils/image_upload_utils.py` `_upload_one_to_cdn()`：`asyncio.wait_for(storage.upload_file(...), timeout=IMAGE_UPLOAD_STORAGE_UPLOAD_TIMEOUT)` 去掉包装，直接 await——storage 上传失去总超时。

怎样算没修好：上面 `replay_tests` 里的四个用例任一没红，即对应那半的改坏没被抓住，测试防线是空的——stale 两个用例锁槽位回收（整池重建 + 退款终态），图床两个用例分别锁同步包装超时（快速返回空列表降级）和 storage 上传总超时（RuntimeError 含"超时"）。

## 永久测试

- `tests/task/test_sync_task_stale_recovery.py`
- `tests/utils/test_image_upload_utils_timeout.py`
- `tests/scripts/test_lint_blocking_calls.py`
