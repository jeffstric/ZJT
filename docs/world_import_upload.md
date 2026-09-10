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
  - 404：`job_id` 不是合法 uuid、对应 job 文件不存在、或已超过 `WORLD_IMPORT_JOB_TTL` 被清理（前端提示「导入任务不存在或已过期，请重试」）
  - 200：`{ success, job_id, status, stage, progress, message, result, error }`
    - `status` ∈ `pending / downloading / unpacking / done / failed`
    - `stage` 与 `status` 基本一致，用于前端文案
    - `progress`：0–100 百分比（下载阶段按已下载字节计算）

## 前端实现

- `web/js/script_writer.js` 的 `importWorldFromFile(file)` 重写为四步链路。
- `uploadWorldZipToQiniu()`：用 `XMLHttpRequest`（非 fetch，因为需要 `xhr.upload.onprogress`）直传七牛，form 字段为 `token / key / file`。
- `pollWorldImportStatus(jobId)`：每 1.5s 轮询 `/api/world-import-status`，直到 `done` 或 `failed`；404 抛「导入任务不存在或已过期，请重试」。
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
| `WORLD_IMPORT_JOB_DIR_NAME` | `world_import_jobs` | job 状态文件目录名（位于项目根 `temp/` 下，多 worker 共享） |
| `WORLD_IMPORT_JOB_READ_RETRIES` | `3` | 读 job 文件撞上原子替换瞬间时的重试次数 |
| `WORLD_IMPORT_JOB_READ_RETRY_INTERVAL` | `0.02` | 上述重试间隔（秒） |
| `WORLD_IMPORT_JOB_TTL` | `3600` | job 文件保留时长（秒）；超过该时长未更新的 active job 也不再计入并发上限 |
| `WORLD_IMPORT_JOB_CLEANUP_INTERVAL` | `300` | job 清理协程轮询间隔（秒） |
| `WORLD_IMPORT_JOB_MAX_CONCURRENT` | `2` | 同时进行的导入任务上限（跨 worker 统计） |
| `WORLD_IMPORT_MAX_TOTAL_UNCOMPRESSED_BYTES` | `2 * 1024 * 1024 * 1024` | zip 解压总量上限（2 GB），超过直接拒绝导入（防 zip 炸弹） |
| `WORLD_IMPORT_MAX_ENTRY_UNCOMPRESSED_BYTES` | `512 * 1024 * 1024` | 单 entry 未压缩大小上限（512 MB），超过直接拒绝导入 |

## Zip Slip 防护（2026-09 安全修复）

`file_manager.import_world` 曾存在 Zip Slip 任意路径写入漏洞（安全审计 P0）：zip entry 名携带 `../` 时可越过目标目录写任意文件（图片/音频通道内容任意二进制，JSON 通道内容任意 JSON 文本），叠加 `/upload` StaticFiles 直出可造成存储型 XSS。现有防护：

1. **user_id / world_id 校验**：导入入口用 `_is_safe_path_component` 拒绝含 `/`、`\`、`..`、绝对路径、Windows 盘符前缀的分量（在创建任何目录之前拦截）。
2. **entry 文件名校验**：图片 / 音频通道经 `_safe_zip_entry_file` 校验目标文件名——拒绝空名、目录名（`/` 结尾）、反斜杠分隔（zip 规范分隔符为 `/`，出现 `\` 一律拒绝）、绝对路径、含 `..` 段、盘符前缀；并通过 `realpath + commonpath` 做最终边界校验（参照 `api/storyboard.py` 的实现）。
3. **JSON 通道收敛**：entry 文件名先 `os.path.basename()` 截断目录部分，再走同一校验；`characters/../evil.json` 会被收敛写入 `characters/evil.json`，不会逃逸。
4. **zip 炸弹防护**：解包前按 zip 声明的未压缩大小预检——总量超 `WORLD_IMPORT_MAX_TOTAL_UNCOMPRESSED_BYTES` 或单 entry 超 `WORLD_IMPORT_MAX_ENTRY_UNCOMPRESSED_BYTES` 直接拒绝导入。

被拦截的 entry 会记入返回结果 `result["errors"]`（含"非法文件路径"字样），其余合法内容继续正常导入。

单测：`tests/utils/test_file_manager_zip_slip.py`（三条通道穿越用例、反斜杠变体、`user_id`/`world_id` 注入、zip 炸弹上限、正常导入回归）。

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

## job 状态存储：共享文件而非进程内存（多 worker 事故复盘）

### 事故现象（2026-09-08）

用户在 `script-writer` 页面导入世界 zip，后端两次都成功解包（日志 `世界导入完成 ... 'errors': []`，文件已落到 `files/script_writer/<user>/<world>/`），但前端进度条跑到一半报「导入任务已丢失（服务可能重启过），请重试」。access.log 轨迹：

```
POST /api/import-world-from-cloud            200
GET  /api/world-import-status?job_id=e4de…   200
GET  /api/world-import-status?job_id=e4de…   200
GET  /api/world-import-status?job_id=e4de…   200
GET  /api/world-import-status?job_id=e4de…   404   ← 前端据此报失败
```

### 根因

job 状态原本是 `api/script_writer.py` 模块级字典 `_world_import_jobs`，**只存在于创建它的那个进程的内存里**。而服务用 gunicorn 多 worker 部署（`-w 4` / `-w 10`），每个请求由操作系统随机分给某个 worker：`POST` 落到 worker A 后 job 只在 A 的内存里，随后的 `GET` 轮询一旦落到 worker B/C/D 就查不到，返回 404。轮询恰好落回 A 就 200，落到别处就 404——这正是上面「先 200 后 404」的轨迹。用户误以为失败又导了一次，第二次的同名文件覆盖了第一次的。

### 现方案

job 状态落盘到 `<项目根>/temp/world_import_jobs/<job_id>.json`（目录名 `WORLD_IMPORT_JOB_DIR_NAME`），所有 worker 读写同一目录：

- **单写者**：每个 job 只有创建它的后台协程写入；写入先落 `<job_id>.json.tmp` 再 `os.replace()` 原子替换，读者永远读到完整 JSON（`os.replace` 在 Windows 上同样原子覆盖）。
- **读容错**：读到半截 JSON / Windows `PermissionError` 时按 `WORLD_IMPORT_JOB_READ_RETRIES` × `WORLD_IMPORT_JOB_READ_RETRY_INTERVAL` 短暂重试，仍失败返回 None（前端拿 404，重试即可）。
- **安全**：`job_id` 来自 query 参数，只接受能被 `uuid.UUID()` 解析的值并归一化为标准 36 字符文件名，杜绝 `../` 拼路径读取目录外文件。
- **并发上限跨 worker 生效**：`_count_active_world_import_jobs` 扫描目录统计；`updated_at` 超过 `WORLD_IMPORT_JOB_TTL` 仍为 active 的视为宿主进程已死的僵尸，不占名额。
- **清理**：每个 worker 首次创建 job 时惰性启动清理协程，按文件 mtime 删除超过 TTL 的 `.json` 及写入中断残留的 `.json.tmp`；不同 worker 的清理协程抢先删除同一文件时忽略 `FileNotFoundError`。
- **所有文件 IO 均在 `asyncio.to_thread` 中执行**，不阻塞事件循环（AGENTS.md 规则 1）。
- 该目录**不受** `media_cache.cleanup_temp_dir` 影响：它只清理 `upload/temp/` 下按 `YYYYMMDD` 命名的子目录，与项目根 `temp/` 是两个路径。

进程重启后 job 文件仍在，前端不会再拿到 404；但进行中的 job 不会被续跑，前端看到的是最后一次落盘的进度（重启后的导入需用户重新发起）。

单测：`tests/api/test_world_import_job_store.py`（含「独立 Python 进程写入、本进程能读到」的跨 worker 用例，以及路径穿越、TTL 清理、并发计数）。
