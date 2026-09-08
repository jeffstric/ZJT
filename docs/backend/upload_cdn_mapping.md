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

## 生效链路

```
上传接口/TTS 完成 → 文件落盘 → register_uploaded_file_mapping
  → media_file_mapping 插入(status=active, cloud_path=NULL)
  → 线程池异步上传七牛(qiniu_long_term 桶) → update_cloud_path 回写
  → 用户访问 /upload/... → cdn_redirect_middleware 按 path hash 查到 mapping
    且 cloud_path 非空 → 302 到七牛签名 URL（不占 frp 带宽）
```

上传完成前的 PENDING 窗口内访问仍本地直出（与 `/upload/cache/` 既有行为一致）。

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
