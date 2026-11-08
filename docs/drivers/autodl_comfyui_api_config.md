# AutoDL.Art ComfyUI 工作流 API 配置

## 概述

AutoDL.Art（autodl.art）将 ComfyUI 工作流包装为 HTTP API 对外提供推理服务。智剧通已接入其**配置管理层**（管理后台可配置密钥），首个目标工作流为 **H3 多图多音频生视频(升级画质)**（`minimax_h3_zm_u24`），驱动对接后续接入。

- **官方 API 文档**: https://autodl.art/docs/comfyui_api/
- **工作流广场**: https://www.autodl.art/large-model/comfyui
- **架构定位**: 供应商 `autodl`（暂未加入 `TaskProvider` 枚举，驱动实现时补充）

## 调查结论（2026-11-07 实测）

### API 端点（两步异步任务模式）

| 步骤 | 方法 | URL |
|------|------|-----|
| 提交任务 | POST | `https://autodl.art/api/v1/comfyui/comfyui_workflow/{workflow_id}` |
| 查询任务 | GET | `https://autodl.art/api/v1/comfyui/comfyui_workflow/result/{task_id}` |

### 认证

- Header: `Authorization: <Token>`（裸 token，非 Bearer 前缀格式）+ `Content-Type: application/json`
- **Token 获取**: 登录 https://autodl.art/large-model/tokens （令牌管理）→ 创建令牌 → **分组必须选 `ComfyUI`**
- autodl.art 与 autodl.com 账号通用（同属视拓云）

### minimax_h3_zm_u24 工作流参数

| 参数 | 说明 |
|------|------|
| `prompt` | 必填，1-20000 字符 |
| `duration` | 选填，整数 1-15 秒，默认 5 |
| `resolution` | 选填：`480p竖` / `768p竖` / `480p横` / `768p横` / `480p(1:1)` / `768p(1:1)`，默认 768p竖 |
| `ref_image_0` | 必填，图片公网 URL（JPG/PNG/WebP） |
| `ref_image_1` ~ `ref_image_8` | 选填，最多 9 张参考图 |
| `ref_audio_0` ~ `ref_audio_2` | 选填，最多 3 段音频（MP3/WAV/FLAC） |
| `seed` | 选填，整数 |

### 响应与状态机

- 提交返回：`data.task_id`，状态 `QUEUED`
- 查询返回：`data.status` ∈ `QUEUED / RUNNING / SUCCESS / FAILED`，`duration`（秒）为任务耗时
- SUCCESS 后 `data.results[]` 返回 `[{url, type: "video", file_type: "mp4", output_type}]`
- ⚠️ **结果 URL 有效期很短，SUCCESS 后必须立即下载转存**（与 RunningHub COS URL 短效同坑）

### 价格（按视频秒数计费，2026-11-07 口径）

| 分辨率 | 高峰(08:00-24:00) | 空闲(00:00-08:00) |
|--------|-------------------|-------------------|
| 480p | ￥0.040/秒 | ￥0.030/秒 |
| 768p | ￥0.050/秒 | ￥0.040/秒 |

> 平台公告：2026-10-16 起 H3 系列 API 涨价 1 分/秒；2026-11-12 起 GPU 价格将调整，价格口径可能变动，计费接入时做成可配置。
>
> **11-15s 档开放记录（2026-11-08）**：`duration=15` 实测出片 15.08s（1344×768，生成 ~570s），算力按 `ceil(时长×1.375)` 扩到 15s=21 点；仅 AutoDL 实现开放（RunningHub webapp 同段有 OOM 风险），提交接口 `ai_app_run_image` 按实现级 `supported_durations` 校验拦截。

### 关键约束

1. **平台无公开文件上传 API**——参考图/音频只收公网 URL。智剧通素材在七牛 CDN 有公网 URL 可直接传；需保证 autodl 服务端拉取期间 URL 可访问。
2. **无回调推送，只能轮询**——驱动内禁止官方示例式的 requests 同步死循环等待；本项目驱动跑在 sync_task_executor 子进程池/scheduler（非 FastAPI 事件循环），采用平台既有模式：同步 `BaseVideoDriver._request`（requests，带超时）+ 调度器周期回调 `check_status` 轮询（项目规则 1 约束的是 Web 接口不得阻塞事件循环，驱动不在事件循环内）。

## 智剧通侧配置

### 配置键（system_config 热更新 + config.yml 双通道）

| 配置键 | 类型 | 敏感 | 说明 |
|--------|------|------|------|
| `autodl.api_key` | string | 是 | AutoDL.Art ComfyUI API Token（分组 ComfyUI） |
| `autodl.base_url` | string | 否 | API 基础 URL，默认 `https://autodl.art` |

### 涉及文件

| 文件 | 改动 |
|------|------|
| `config.example.yml` | `autodl:` 配置段模板 |
| `config/default_configs.py` | `DEFAULT_CONFIGS` 两个键（`quick_config: True`，api_key 另标 `user_module_grantable: True` → 自动生成密钥规范名 `AUTODL_API_KEY`） |
| `web/js/admin.js` | `PROVIDER_DEFINITIONS` 增加 `autodl_video` 卡片（多媒体分类，displayOrder 22） |
| `web/i18n/locales/{zh-CN,en}/admin.json` | 供应商文案 |

> 注：管理后台 `web/admin.html` 的快速配置弹窗由 `PROVIDER_DEFINITIONS` 通用渲染，无需改动。

### 配置方式（三选一）

1. **管理后台快速配置**：系统设置 → 快速配置 → 多媒体 → AutoDL.Art 卡片，填入 Token 保存（写 system_config，热生效）。
2. **管理后台系统配置**：`/config/init` 初始化后直接搜 `autodl.` 编辑。
3. **本地 config.yml**：`autodl.api_key` 段（服务启动时作为默认值，system_config 优先）。

## 后续待办（驱动对接）—— ✅ 2026-11-07 已完成并实测通过

- [x] `minimax_h3_zm_u24`（参考生）+ `minimax_h3_lightx2v`（首尾帧）驱动 → [minimax_h3_autodl_v1_driver.md](minimax_h3_autodl_v1_driver.md)
- [x] `TaskProvider.AUTODL = 'autodl'`
- [x] `DriverImplementation` ID 108/109 注册，挂载到 `minimax_h3_reference_to_video` / `minimax_h3_image_to_video` 任务（`required_config_keys=['autodl.api_key']`）
- [x] 结果 URL 短效处理：SUCCESS 后由 download_queue 立即下载转存（既有机制）
- [x] 算力计费档位：`MINIMAX_H3_AUTODL_768P_COMPUTING_POWER`（高峰价口径）
- [x] 480P 倍率按 autodl 成本比 0.8 在实现级 `power_modifiers` 代码固化（不再依赖上线后手改 DB）
- [x] 输入契约能力校验：`validate_input_compatibility` 钩子（首尾帧双必填/无参考视频槽），重试候选选择时自动跳过不兼容实现
- [x] 真实 Token 联调：参考生（图片参考+音色音轨）与首尾帧（首尾约束+横竖分辨率）全链路通过，详见驱动文档实测记录
- [x] 配置段已加入 `config_prod.base.yaml` / `config_dev.base.yml` / `config_unit.base.yml`（存量部署升级可由「初始化配置」导入）
