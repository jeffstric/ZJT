---
id: 2026-09-29-expired-reference-404
patch: patches/2026-09-29-expired-reference-404.json
tests:
  - tests/drivers/test_gpt_image_expired_reference.py
replay_tests:
  - tests/drivers/test_gpt_image_expired_reference.py::TestPrepareImageFile404::test_404_raises_image_expired
  - tests/drivers/test_gpt_image_expired_reference.py::TestDownloadImageAsBase64404::test_404_raises_image_expired
feature_ids:
---

## 当时坏成什么样

参考图 404/410（upload/cache 定期清理后资产仍引用旧 URL）被报成服务异常：走 `Unexpected exception` 分支触发 Sentry UNEXPECTED_EXCEPTION 系统告警，用户看到「服务异常，请联系技术支持」，重试必然失败。

## 代码大概在哪

- `task/visual_drivers/gpt_image_common_v1_driver.py` 的 `_prepare_image_file`（multipart 路径）与 `_download_image_as_base64`（base64 路径）
- 测试在 `tests/drivers/test_gpt_image_expired_reference.py`

## 改坏补丁动了哪几行

改坏补丁把两条下载路径里「404/410 → 抛 `ImageExpiredError`」的判断整段删掉，改回当年直接 `response.raise_for_status()` 的写法——404 重新变成 HTTPError，走通用异常分支误触 Sentry、用户看到笼统服务异常。两条路径（multipart / base64）各自一个 replace。

## 怎样算没修好

`TestPrepareImageFile404::test_404_raises_image_expired` 和 `TestDownloadImageAsBase64404::test_404_raises_image_expired` 任一没红，即对应路径的改坏没被抓住。`test_500_still_raises_http_error` 在改坏下仍绿，证明 5xx 的原语义未被顺手改变。
