# 大世界文件导入：前端直传七牛 + 后端限速下载

## 背景

`script_writer.html` 的「导入世界数据」原本走 `POST /api/import-world`：前端用单次 `FormData` 把整个 zip 直接传给后端，后端在 `async def` 端点里 **同步** 调用 `file_manager.import_world(...)` 解包。当世界 zip 很大（含大量参考图/音频）时，同步解包会 **阻塞整个 FastAPI 事件循环**，期间所有其他接口都不响应——表现为「整个系统卡顿」。同时整个 zip 会被一次性 `await file.read()` 读进内存，造成内存峰值。

## 新方案总览

```
浏览器 ──①──> POST /api/world-upload-token        （后端颁发绑定 key 的短期上传 token）
   │
   └──②──> 七牛云上传域名（前端 XHR 直传 zip，带 upload.onprogress 进度）
                  │
浏览器 ──③──> POST /api/import-world-from-cloud   （提交 key，后端立即返回 job_id）
                  │
                  └── 后端 asyncio.create_task 后台跑：限速下载 zip → to_thread 解包
                          │
浏览器 ──④──> GET /api/world-import-status?job_id=xxx（轮询进度）
```

核心收益：
- **后端彻底不接触大文件的上传**：前端直传七牛，带宽/内存完全释放。
- **下载阶段限速**：后端从七牛拉取 zip 时按 `WORLD_IMPORT_DOWNLOAD_RATE_BPS` 限速，不打满服务器出口带宽。
- **解包不阻塞事件循环**：`file_manager.import_world` 用 `asyncio.to_thread` 丢线程池。
- **进度可见**：前端有进度条（上传百分比 / 下载百分比 / 解包中 / 完成）。

## 后端接口

### `POST /api/world-upload-token`
颁发前端直传七牛的上传 token。

- 权限：`script:create`
- 入参（form）：`world_id`、`filename`、`size`（可选）
- 返回：`{ success, upload_url, token, key, expires }`
  - `upload_url`：七牛上传区域域名（`config/constant.py` 的 `QINIU_UPLOAD_REGION_URL`，默认华东 `https://upload.qiniup.com`）
  - `token`：绑定 `key` 的短期上传凭证，有效期 `QINIU_DIRECT_UPLOAD_TOKEN_EXPIRES`（默认 1800s）
  - `key`：`world_import/<YYYY-MM-DD>/<HH>/<ts>_<uid>.zip`

### `POST /api/import-world-from-cloud`
基于七牛 key 触发大世界导入（异步后台任务）。

- 权限：`script:create`
- 入参（form）：`user_id`、`world_id`、`key`
- 并发保护：同时进行的导入任务超过 `WORLD_IMPORT_JOB_MAX_CONCURRENT`（默认 2）时返回 **429**。
- 返回：`{ success, job_id }`（立即返回，不阻塞）

### `GET /api/world-import-status`
查询导入任务进度（前端轮询）。

- 权限：`script:create`
- 入参（query）：`job_id`
- 返回：
  - 404：任务不存在或已过期（进程重启会丢失内存 job，前端应提示「任务丢失，请重试」）
  - 200：`{ success, job_id, status, stage, progress, message, result, error }`
    - `status` ∈ `pending / downloading / unpacking / done / failed`
    - `stage` 与 `status` 基本一致，用于前端文案
    - `progress`：0–100 百分比（下载阶段按已下载字节计算）

## 前端实现

- `web/js/script_writer.js` 的 `importWorldFromFile(file)` 重写为四步链路。
- `uploadWorldZipToQiniu()`：用 `XMLHttpRequest`（非 fetch，因为需要 `xhr.upload.onprogress`）直传七牛，form 字段为 `token / key / file`。
- `pollWorldImportStatus(jobId)`：每 1.5s 轮询 `/api/world-import-status`，直到 `done` 或 `failed`；404 抛「任务丢失」。
- 进度条 UI：`web/script_writer.html` 的 `#worldImportProgress`（位于文件 tabs 下方），样式见 `web/css/script_writer.css` 的 `.world-import-progress*`。

## 相关常量（`config/constant.py`）

| 常量 | 默认值 | 说明 |
|---|---|---|
| `QINIU_UPLOAD_REGION_URL` | `https://upload.qiniup.com` | 七牛上传区域域名（按 bucket 区域修改） |
| `QINIU_DIRECT_UPLOAD_TOKEN_EXPIRES` | `1800` | 直传 token 有效期（秒） |
| `WORLD_IMPORT_KEY_PREFIX` | `world_import` | 直传 key 前缀，便于清理 |
| `WORLD_IMPORT_DOWNLOAD_RATE_BPS` | `20 * 1024 * 1024` | 限速下载速率上限（字节/秒，默认 20 MB/s） |
| `WORLD_IMPORT_DOWNLOAD_CHUNK_BYTES` | `256 * 1024` | 限速下载单 chunk 大小 |
| `WORLD_IMPORT_DOWNLOAD_TIMEOUT` | `1800` | 限速下载总超时（秒，`asyncio.wait_for` 保护） |
| `WORLD_IMPORT_PROGRESS_STEP` | `5` | 进度刷新粒度（百分比） |
| `WORLD_IMPORT_JOB_TTL` | `3600` | 内存 job 保留时长（秒） |
| `WORLD_IMPORT_JOB_CLEANUP_INTERVAL` | `300` | job 清理协程轮询间隔（秒） |
| `WORLD_IMPORT_JOB_MAX_CONCURRENT` | `2` | 同时进行的导入任务上限 |

## 非阻塞 / 超时红线合规

遵守 `AGENTS.md` 规则 1 / 9 / 10：

- 所有 web 接口均为非阻塞：`import_world_from_cloud` 立即返回 `job_id`，下载与解包在后台协程进行。
- 后台协程中所有同步函数（`file_manager.import_world`、`os.unlink`）均用 `asyncio.to_thread` 包裹，不阻塞事件循环。
- 下载流式逐 chunk 写盘 + `asyncio.sleep` 限速，整体受 `asyncio.wait_for(timeout=WORLD_IMPORT_DOWNLOAD_TIMEOUT)` 保护。
- 临时文件用 `try/finally`（及 except 分支）清理，失败也保证不残留。
- 未使用 `concurrent.futures.Future.result()` 或 `with ThreadPoolExecutor()`，不触发 R4/R6。

## 兼容性

- `GET /api/export-world` **未改动**。
- 旧的 `POST /api/import-world` **保留作为小文件兜底**，但已修复事件循环阻塞：
  - `await file.read()` 改为流式分块（1 MB/chunk）写临时文件；
  - `file_manager.import_world(...)` 用 `asyncio.to_thread` 包裹；
  - `os.unlink` 用 `asyncio.to_thread` 包裹。
- 当前世界 zip 一般走新的直传链路；如七牛配置缺失或前端不支持，可回退旧链路。

## 七牛区域说明

`QINIU_UPLOAD_REGION_URL` 默认为华东 `https://upload.qiniup.com`。如 bucket 位于其他区域，请按 [七牛区域域名文档](https://developer.qiniu.com/kodo/1671/region-endpoint-fq) 修改 `config/constant.py`，或改为 DB 动态配置（经 `get_dynamic_config_value` 读取）。

## 进程重启行为

job 状态仅存内存（`api/script_writer.py` 的 `_world_import_jobs` 字典）。进程重启后，进行中的任务会丢失，前端轮询将拿到 404，按「任务丢失，请重试」提示用户。如需进程重启后可恢复，后续可落 DB 表（届时按 `AGENTS.md` 规则 7 补 alembic 迁移）。
