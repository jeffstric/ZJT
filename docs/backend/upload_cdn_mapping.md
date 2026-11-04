# 上传素材接入 CDN mapping 方案

## 背景

生产带宽调查（2026-09，access.log 全量统计）发现：`/upload/` 请求中约 79% 已通过
`cdn_redirect_middleware` 302 到七牛 CDN，但仍有两类链路 **100% 本地直出**（从本机经
frp 隧道全量吐出，挤占 ECS 5~8.3Mbps 出带宽）：

| 链路 | 直出请求数 | 原因 |
|---|---|---|
| `/upload/workflow/{uid}/`（用户上传素材） | 20,339 | 上传接口保存文件后直接返回本地 URL，从不建 `media_file_mapping` |
| `/upload/tts/result_audio/`（TTS 配音结果） | 14,855 | `audio_task.py` 拼完 `result_url` 入库即结束，无 mapping 链路 |

## 改动内容

### 1. `model/media_file_mapping.py`

`MediaFileEntity` 新增枚举 `TTS = 7`（配音音频），`get_entity_name` / `from_entity_name`
同步补充。纯代码层枚举，无表结构变更，无需迁移。

### 2. `utils/media_mapping_util.py` 新增 `register_uploaded_file_mapping()`

上传素材落盘后的通用注册入口：

- 门控：`server.auto_upload_to_cdn` 关闭时直接返回 `None`（与既有链路一致）
- 查重：同 `local_path` 已有 mapping 则复用返回（防御性兜底）
- `MediaFileMappingModel.create(cloud_path=None)` → `CDNUtil.trigger_cdn_upload()`（模块级
  线程池 fire-and-forget，不阻塞调用方）
- **整体 try/except：任何失败只记 warning，绝不影响上传主流程**

### 3. `server.py` `_save_user_asset()`

workflow 素材写盘后用 `utils/media_mapping_util.upload_local_path()` 计算规范相对路径
（**相对项目根、带 `upload/` 前缀的 POSIX 路径**，如 `upload/workflow/12/xxx.png`），
注册 `entity_type=WORKFLOW`、`policy_code=NEVER_EXPIRE`（用户长期资产）。
该函数经 `asyncio.to_thread` 在工作线程执行，同步 DB 调用不阻塞事件循环。

> **路径前缀约定（事故教训）**：中间件查询（请求 path `lstrip("/")`）与
> `trigger_cdn_upload`（项目根拼接定位文件）都要求 `upload/` 前缀。曾因用 upload 根
> 做 `relpath` 基准导致前缀缺失，注册永不命中、CDN 上传定位不到文件，整条卸载链路
> 静默失效。该口径已收敛到 `upload_local_path()` 单一出口，
> `tests/cdn/test_upload_local_path.py` 用真实文件系统做三方约定回归。

### 4. `task/audio_task.py` TTS 结果

`result_url` 拼好后用 `extract_local_path_from_url()` 提取 `upload/tts/result_audio/xxx`
（`tts.upload_url` 配置为 `/upload/` 形式 URL 时才非空），以 `entity_type=TTS`、
`policy_code=NEVER_EXPIRE` 注册；async 上下文用 `asyncio.to_thread` 包裹。
source_id 记录 ai_audio 的 task_id。

> **部署前提（共享卷）**：配音音频由远端 TTS 服务落盘（`audio_task.py` 的
> `UPLOAD_DIR`），本服务须经共享卷/符号链接让 `<项目根>/upload/tts/result_audio/`
> 读到同一批文件，`trigger_cdn_upload` 才能上传成功。本地文件不存在时注册被跳过
> （避免产出 `cloud_path` 永远为 NULL 的死记录），日志输出
> `TTS 音频本地不可读...跳过 CDN 注册` 提示检查共享卷配置；播放仍走本地直出回退，
> 不影响配音任务。

### 5. `server.py` `/api/download` 本站 `/upload/` URL 改写为 CDN（2026-10）

**事故背景**：火山 TTS（`build_public_audio_url`）返回
`http://{server.host}/upload/tts/volcengine/xxx.mp3` 完整 URL。前端
`downloadWithAuth` 调 `/api/download` 时，该 URL 三个分支全不命中：
本地分支只认 `/upload/cache/` 相对路径、CDN 分支只认七牛域名，落入代理
下载分支后 httpx 默认不跟随 `cdn_redirect_middleware` 的 302，
`raise_for_status()` 直接抛 `Redirect response '302 Found'`——下载必败；
即使跟随，也是"服务器从七牛拉回全量字节再吐给浏览器"，违背本方案初衷。

**改动**：新增 `_rewrite_site_upload_url_to_cdn()`（server.py），在
`download_image` 入口处调用：

- 判定与中间件同款：path 以 `/upload/` 开头 + host 属于本站
  （`server.host` 或请求 Host 头，协议无关）+ mapping 存在且 `cloud_path`
  非空（DB 查询经 `asyncio.to_thread`，不阻塞事件循环）
- 命中则改写为 `https://{qiniu_long_term.cdn_domain}/{cloud_path}`，交给
  既有"CDN 重签名（attname 参与签名）→ 302 / format=json"分支，
  浏览器直连七牛下载（带 `Content-Disposition: attachment`），媒体流量不过本服务
- 未命中（未注册/上传未完成/非本站域名）原样返回，走原有本地/代理兜底；
  代理分支的 httpx 补 `follow_redirects=True`（`/api/download` 与
  `/api/proxy-image`），兜底路径遇 302 不再报错

测试：`tests/api/test_download_site_upload_url.py`（5 用例：改写后签名返回 /
cloud_path 作 key / 无映射走代理 / 非本站域名不查库 / 相对路径回归）。

### 6. 前端 `downloadWithAuth` 本站 `/upload/` 路径改走重签名通道（2026-10，develop_f1090）

**事故背景**：视频工作流图片节点，上传图点"下载"会跳转到标签页展示图片而非下载。
上传接口返回的本站绝对 URL（`http://{host}/upload/workflow/{uid}/x.jpg`）经
`unwrapMediaUrl` 归一为相对路径后命中 `<a download>` 直下分支；但
`cdn_redirect_middleware` 会把该请求 302 到跨域 CDN，浏览器对跨域重定向
丢弃 `download` 属性，直接导航展示。图片节点"生成结果"另有第二个问题：
结果名（"生成结果1"）无扩展名，CDN `attname` 原样透传，下载出的文件无后缀。

**改动**（`web/js/download_attachment.js`）：

- `/upload/` 开头的同源相对路径不再 `<a download>` 直下，统一改走
  `/api/download?format=json` 重签名通道（后端 `_rewrite_site_upload_url_to_cdn`
  改写 CDN 域名 + attname 强制附件下载）；其余同源相对路径（如 `/files/*.pdf`）
  保持直下不受影响
- 进 `/api/download` 的相对路径补全为绝对 URL（后端改写分支需要 netloc）；
  唯 `/upload/cache/` 保持相对路径——后端本地文件分支按该前缀识别，
  FileResponse 自带 attachment 头，映射缺失时省一次全量代理
- 新增 `ensureDownloadExtension(name, url, fallbackExt)` 并挂到 `window`：
  文件名无图片扩展名时依次从 URL 路径段提取、按 fallback（png）兜底。
  图片节点下载按钮已接入（`web/js/image_node.js`）

测试：`web/js/download_attachment.test.js`（9 用例，vitest：通道选择 5 +
扩展名兜底 4）。

### 7. 工作流素材前端直传七牛（2026-11，省服务器进出带宽 + 根治播放换源竞态）

**事故背景**（2026-11-02 线上调查）：multipart 上传返回 plain URL 后，
异步七牛上传约 2s 才置位 `cloud_path`，视频元素播放会话内经历
"本地 206（经 frp）→ 突然 302 到 CDN"的服务中换源，Chromium 媒体管线在该
窗口内加载失败后不自恢复，且前端 play()/error 全部静默吞错——用户看到
"上传成功但无法播放"。同时用户上传 18MB（frp 入）+ 服务器传七牛 18MB
（ECS 出，计费大头）双份带宽都花在了中转上。

**方案**（浏览器直传，服务器只做确认与落主副本）：

```
upload-token（token 绑定 key + fsizeLimit + insertOnly + returnBody，30min 过期）
  → 浏览器 XHR 直传七牛（进度可观测，不经服务器）
  → upload-confirm：七牛 stat 核实 → 签名 URL 流式回源下载到本地素材目录
    （临时文件 + 大小上限 + 魔数校验 + os.replace 原子落盘）
    → 落盘成功才插入 media_file_mapping（cloud_path 直接置位）
    → 返回与 multipart 同款的本站永久 URL（永不过期）
```

- **本地为主副本、CDN 为加速层**：用户要求"下载到本地后才入库"，保证
  `media_file_mapping.local_path` 永远有本地文件兜底（七牛丢文件/CDN 故障时
  plain URL 仍可本地直出），mapping 语义与 multipart 链路完全一致
- **竞态根治**：mapping 建立时 CDN 上已有文件，首个播放请求直接 302 命中，
  不存在"本地 206→302"中途换源窗口
- **带宽账**：服务器出带宽（上传七牛）18MB→0，frp 入（用户上传）18MB→0，
  服务器入（回源下载，云厂商入方向廉价）18MB
- **降级链**：`server.auto_upload_to_cdn=false` 时 token 返回
  `data.direct_upload=false`（reason=cdn_disabled），前端走原有 multipart；
  TIFF 同样降级（reason=tiff_unsupported，转码只能发生在回源下载后，key 已
  固定 .tif 会与转码产物脱节）；token/XHR/confirm 任一环节失败前端均静默
  降级 multipart（console.warn 留痕），旧服务端 404 亦自然降级（滚动发布兼容）

**改动**：

- `config/constant.py`：`WORKFLOW_DIRECT_UPLOAD_CONFIRM_TIMEOUT`（回源下载
  wait_for 硬上限 300s）、`WORKFLOW_DIRECT_DOWNLOAD_HTTP_TIMEOUT`（httpx 单次
  读空闲超时 60s——注意非总时长，线程不可取消只能靠它收敛）
- `utils/file_storage/`（**端点层面向接口，不绑定存储品牌**）：
  - `BaseFileStorage` 新增两个默认方法：`stat()`（返回 None）、
    `get_browser_upload_info(key, max_bytes, expires)`（返回 None = 该后端
    不支持浏览器直传，端点自动降级 multipart）。换 OSS/S3 等后端只需实现
    `get_browser_upload_info`（OSS PostObject / S3 presigned PUT），端点零改动
  - `QiniuFileStorage.get_browser_upload_info()`：颁发绑定 key + fsizeLimit +
    insertOnly + returnBody 的 form 直传凭证。insertOnly=1 禁止覆盖同一 key：
    confirm 成功后 `cdn_redirect_middleware` 按 cloud_path 302，不再重做魔数
    校验。七牛协议细节（UC 区域查询 URL、占位符语法、
    `DEFAULT_BROWSER_UPLOAD_HOST`）全部封装在本实现内
  - `QiniuFileStorage._resolve_browser_upload_host()`：构造参数 `upload_host`
    覆盖 → 七牛 UC `GET /v4/query` 按 `hosts[0].up.domains`（空则 `up.old`）
    解析上传域名（进程内按 (AK, bucket) 二元组缓存，同 AK 不同桶区域可能不同；
    非 2xx、旧版 `up.acc.main` 或没有域名时不写缓存）→ 默认华东
    `upload.qiniup.com`（UC 失败且桶不在华东时直传会 400，前端自动降级
    multipart 兜底；可用 `file_storage.{section}.upload_host` 配置固定，
    factory 透传构造）
  - `QiniuFileStorage.stat()`：BucketManager 核实文件存在/大小，防伪造 confirm
  - `factory.py`：透传 section 配置的 `upload_host`。`_load_config` 的 DB
    动态覆盖包含 `upload_host`，实例缓存键也包含它，只改直传域名会换新实例
- confirm 回源走七牛源站管理下载（`GET https://<ioHost>/getfile/<urlsafe_b64(bucket:key)>`，
  `Authorization: QBox <token_of_request>`）。io 域名用 `Region.get_io_host` 按 bucket 解析并缓存，
  不使用 `cdn_domain`，也不使用私有下载 URL。播放链接仍走 CDN。其他存储后端没有
  `get_origin_download_request` 时，confirm 仍用原来的下载 URL。源站域名解析或
  getfile 地址无效时 confirm 返回 502，不回退到 CDN 域名。
- 调度任务 `cleanup_orphan_workflow_uploads`（默认 6 小时）先把
  `upload/workflow/` 前缀、没有 `media_file_mapping`、且 putTime 早于 24 小时的对象
  挪到 `wait_delete/YYYY-MM-DD/<原 key>`，不覆盖已存在的目标。满 7 天后才按目录日期
  真正删除。单次列举上限 2000，挪走和删除各自上限 200。putTime 缺失、日期解析不了，
  或查询 mapping 失败的对象不动。移动失败时原文件留在原地。
- `server.py`：`POST /api/video-workflow/upload-token`（key=`upload/workflow/{uid}/...`
  绑定登录用户 + 扩展名白名单 + 大小预校验（含 size<=0 拒绝）+ `getattr`
  防御鸭子类型存储，同 world-upload-token 先例）、
  `POST /api/video-workflow/upload-confirm`（key 归属校验防跨用户/路径穿越、
  stat 核实、回源下载、幂等）、`_download_cdn_asset_to_local()`（同步实现，
  `asyncio.wait_for(loop.run_in_executor(专用线程池, ...))` 包裹；**confirm
  专用长寿线程池**隔离默认执行器——线程不可取消，慢速滴流下载存活超 wait_for
  不会拖累其他 to_thread；临时文件名带 uuid，同 key 并发 confirm 不互写）
- `utils/media_mapping_util.py`：`register_direct_uploaded_mapping()`——
  cloud_path 直接置位、不触发 `trigger_cdn_upload`、幂等复用
- `web/js/api.js`：`uploadFile()` 优先 `uploadFileDirectToCdn()`（token → XHR
  直传 → confirm），失败降级走原 multipart 路径；认证仍走 Authorization 头
  （红线14），上传凭证只进存储 form 体（直传协议要求）

测试：`tests/api/test_workflow_direct_upload.py`（18 用例：token 降级/颁发/
白名单/超限/非法 size/TIFF/不支持后端、confirm 跨用户/穿越/白名单/stat 缺失/
成功落盘注册/源站解析失败 502/幂等/超限）+ `tests/cdn/test_register_direct_uploaded_mapping.py`
（5 用例）+ `tests/utils/test_qiniu_storage.py`（直传信息颁发含 insertOnly/
基类默认 None/域名解析覆盖/UC v4 domains 缓存/domains 为空走 up.old/
旧版 up.acc.main 不解析且不缓存/UC 失败回退）。

## 生效链路

```
上传接口/TTS 完成 → 文件落盘 → register_uploaded_file_mapping
  → media_file_mapping 插入(status=active, cloud_path=NULL)
  → 线程池异步上传七牛(qiniu_long_term 桶) → update_cloud_path 回写
  → 用户访问 /upload/... → cdn_redirect_middleware 按 path hash 查到 mapping
    且 cloud_path 非空 → 302 到七牛签名 URL（不占 frp 带宽）
  → 前端点下载 /api/download?url=http://{server.host}/upload/...
    → _rewrite_site_upload_url_to_cdn 改写为七牛域名
    → 重签名(attname) → 302 / format=json redirect_url（不占 frp 带宽）
```

上传完成前的 PENDING 窗口内访问仍本地直出（与 `/upload/cache/` 既有行为一致）。

前端直传链路（CDN 开启时的新增通路，见第 7 节）无 PENDING 窗口：
confirm 返回时本地文件与 CDN 文件均已就绪，首个访问即 302 命中。

## 明确不接入的链路

- `/upload/temp/`：临时目录每天定时清理（保留 2 天），上 CDN 会造成"本地已删、
  七牛残留"的语义混乱
- `/upload/assert/`：静态引导图，体积小、低频访问

## 测试

`tests/cdn/test_register_uploaded_file_mapping.py`（8 个用例，全部 mock，无需 DB）：
开关门 / 正常注册 / 查重复用 / 空路径 / create 与 trigger 异常不阻断 / TTS 枚举 /
TTS URL 提取。运行：`python3 -m pytest tests/cdn/test_register_uploaded_file_mapping.py -v`。

## 运维注意

- `scripts/tools/upload_pending_cdn.py` 批次 B 会对 cloud_path 为空的记录重试上传，
  对 PENDING 中的新记录会与首次上传并发——七牛同 key 覆盖，幂等无害
- 回退：revert 本次提交即可，注册是纯增量行为，无存量数据影响
