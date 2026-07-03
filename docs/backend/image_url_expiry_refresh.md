# 图床签名 URL 过期自动恢复方案

## 背景

用户做图片编辑、视频生成时，输入图片以**图床签名 URL** 存于 `ai_tool.image_path` 等字段——七牛云私有 bucket 链接，形如：

```
http://zjtcdn.perseids.cn/upload/cache/2026-06-30/xxx.png?e=<过期时间戳>&token=<AccessKey>:<签名>
```

有效期约 1 天 / 28h。用户隔了一段时间才提交任务，URL 已过期；驱动把这个过期 URL **原样传给下游服务**（RunningHub / 火山 / 多米 / Grok …），下游拉取返回 **401**，任务失败。

根因：所有驱动在把图片 URL 交给下游前，都**没有做过期防护**——`ensure_public_urls` 对外网 URL 原样透传；RunningHub 上传失败静默降级继续用过期 URL。

## 目标

在所有驱动把图片 URL 交给下游/网络前，统一确保它「新鲜可访问」，根治 401。

## 核心原则

1. **自有图床永不抛异常**：`zjtcdn.perseids.cn` 等是我们自己的七牛 CDN（有 secret_key）。即便签名过期，也能通过「重签名」或「`/upload/` 本地映射」恢复，**永远不会**因图床问题让任务失败。
2. **只有第三方图床过期才抛异常**：第三方 URL 我们拿不到 secret 无法重签、下载转存同样 401，无计可施时提示用户重新上传。
3. **临期判断用主动探测**（不靠解析 URL 参数）：对所有图床通用准确。

## 核心函数 `ensure_fresh_image_url`

位置：`utils/image_upload_utils.py`（含 `_sync` 同步包装）。

决策树（始终返回 str）：

| URL 类型 | 处理 | 是否抛异常 |
|---|---|---|
| 空 / 本地路径 | 原样返回 | 否 |
| **自有 CDN**（`CDNUtil.is_cdn_url` 命中） | `refresh_cdn_signed_url` 重签名（零成本，纯本地 HMAC；失败降级返回原 URL） | **否** |
| **第三方 URL** | 主动探测（Range GET 1 字节） | 探测 401/403 → 抛 `ImageExpiredError` |
| | `2xx` 原样返回；`404/5xx/网络错误` 降级原样返回 | 否 |

`ImageExpiredError` 定义于 `task/visual_drivers/exceptions.py`，仅第三方过期场景抛出。

### 为何用主动探测而非解析 URL 参数

七牛签名 URL 用 `?e=&token=`，但阿里云 OSS 用 `?Expires=&Signature=`，AWS S3 用 `?X-Amz-Date=&X-Amz-Expires=`，腾讯云 COS 又是另一套——靠参数名猜不可靠。主动探测（Range GET 1 字节看响应码）对所有图床通用：主流对象存储签名过期都返回 401/403，准确反映「此刻 URL 能否访问」。

### 探测性能保护

- **超时短**：`IMAGE_URL_PROBE_TOTAL_TIMEOUT=3s` + `connect=2s`。过期 URL 会立即返回 401（不等超时）；只有「不可达」(DNS/连接失败) 才卡满 connect。
- **A 类多图并发**：`upload_local_images_to_cdn` 用 `asyncio.gather` + `Semaphore(IMAGE_URL_PROBE_CONCURRENCY=5)`，N 张图最坏 ≈ ⌈N/5⌉×3s（10 张 ≈ 6s），不会串行累积卡住定时脚本。
- **自有 CDN 不探测**：直接重签名，零网络请求。

## 五个接入点（覆盖全部 22 个视觉驱动 + 音视频参考输入）

| # | 接入点 | 文件 | 覆盖驱动 |
|---|---|---|---|
| A | `upload_local_images_to_cdn` 外网透传分支（并发） | `utils/image_upload_utils.py` | kling/sora2/veo3/gemini/grok_duomi/vidu/happy_horse/gpt_image_duomi **+ 音视频参考** |
| B | `resolve_url_to_local_file` 下载前刷新 | `utils/image_upload_utils.py` | seedance/seedream（volcengine）、ltx2_3 取尺寸 |
| C | `RunningHubFileStorage.upload_file` 下载前刷新 | `utils/file_storage/runninghub_storage.py` | ltx2_3/ltx2/wan22/digital_human×2/qwen_multi_angle |
| D | `_prepare_image_file`/`_prepare_image_data` 下载前刷新 | `task/visual_drivers/gpt_image_common_v1_driver.py` | gpt_image_common 全部 site 子类 |
| E | `_build_image_payload` 入口刷新 | `task/visual_drivers/grok_common_v1_driver.py` | grok_common |

## `/upload/` 本地映射兜底（自有图床第二重保障）

`extract_local_path_from_url`（`utils/media_mapping_util.py`）按 `/upload/` 前缀提取本地相对路径，**与域名无关**。`zjtcdn` 的 URL 路径以 `/upload/` 开头，能映射到本地文件。

在 A/B/C/D 接入点的下载链路追加此兜底：当自有 CDN 重签名失败（配置缺失/七牛故障）时，仍能读到本地副本，**任务不抛异常、不失败**。

## RunningHub 静默降级 bug 修复

原 5 个 RunningHub 驱动图片 `upload_file` 失败时只 `warning`，继续用原始过期 URL → 下游 401 假象。改为分层失败：

- **图片过期**（`ImageExpiredError`，在下载前由 `ensure_fresh_image_url` 抛出）→ `submit_task` 捕获，返回 `error_type=USER` + 「请重新上传」友好提示。
- **其他上传失败**（`raise RuntimeError`）→ `submit_task` 走 `SYSTEM` 错误。

涉及驱动：`ltx2_3` / `ltx2` / `wan22` / `qwen_multi_angle` / `digital_human_ltx2_3_voice`。参照 `digital_human_runninghub_v1_driver`（原本已正确 `raise`）。

## 新增常量（`config/constant.py`）

```python
IMAGE_URL_PROBE_TOTAL_TIMEOUT = 3       # 第三方URL探测总超时
IMAGE_URL_PROBE_CONNECT_TIMEOUT = 2     # 探测连接超时（不可达快速失败）
IMAGE_URL_PROBE_CONCURRENCY = 5         # A类多图探测并发上限
IMAGE_URL_REFRESH_SYNC_WRAPPER_TIMEOUT = 200  # 刷新同步包装超时
```

## 降级策略（永不阻断主流程的"确定可用"分支外都降级返回原 URL）

- 自有 CDN 重签名失败 → 返回原 URL（下载链路有本地映射兜底）。
- 第三方探测 `404/5xx/网络错误` → 返回原 URL（不确定，交下游尝试）。
- `_sync` 包装超时 → 返回原 URL（不抛超时）。
- 仅「第三方探测 401/403」这一**确定无法恢复**的情况抛 `ImageExpiredError`。

## 运维注意

线上 `file_storage.qiniu_long_term` 需配置完整（`access_key`/`secret_key`/`bucket_name`/`cdn_domain`，其中 `cdn_domain` 应为 `zjtcdn.perseids.cn`），以启用自有 CDN 重签名。配置缺失时，自有图床回退到 `/upload/` 本地映射兜底，仍可工作但多一次本地读取。

## 范围说明

- A 类（透传型，11 个驱动）与 volcengine 系列的 `ImageExpiredError` 当前走各自 `submit_task` 的通用 `except Exception`（返回 SYSTEM「服务异常」，日志/报警含「图片过期」信息）。RunningHub 5 个 + gpt_image_common + grok_common 已有「请重新上传」友好提示。其余驱动的友好提示可作为后续增强。
- 核心问题（图床过期导致下游 401 假象）已在所有驱动解决：自有图床恢复，第三方过期明确失败。
