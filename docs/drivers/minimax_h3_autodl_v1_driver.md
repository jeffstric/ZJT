# MiniMax H3 AutoDL.Art 驱动（参考生 zm_u24 + 首尾帧 lightx2v）

## 概述

通过 AutoDL.Art ComfyUI 工作流 API 调用 **MiniMax H3** 生成视频，一个驱动文件覆盖两个工作流（同一套两步异步协议，差异只在素材槽位）：

| 工作流 | workflow_id | 实现方 | 挂载任务 |
|--------|-------------|--------|----------|
| H3多图多音频生视频(升级画质) | `minimax_h3_zm_u24` | `minimax_h3_reference_autodl_v1`（ID 108） | `minimax_h3_reference_to_video`（参考生，type 37） |
| H3首尾帧生视频 | `minimax_h3_lightx2v` | `minimax_h3_first_last_autodl_v1`（ID 109，**代码级默认关闭**） | `minimax_h3_image_to_video`（首尾帧，type 34） |

`minimax_h3_first_last_autodl_v1` 的 `ImplementationConfig.enabled=False`。上游要求 `first_frame` 和 `last_frame` 都必填，只有首帧会失败。这是代码级硬禁用，数据库 `implementation_power_config.enabled` 不能把它重新打开。首尾帧任务继续用 RunningHub 实现方。参考生 `minimax_h3_reference_autodl_v1` 不受影响。

- **驱动文件**: `task/visual_drivers/minimax_h3_autodl_v1_driver.py`
- **供应商**: `TaskProvider.AUTODL`（实现方级 provider；任务级 provider 仍为 RUNNINGHUB，autodl 作为可切换实现方，模式同 Seedance 多网关）
- **配置键**: `autodl.api_key`（必填）/ `autodl.base_url`（默认 `https://autodl.art`）

> ⚠️ **实现方级 provider 必须显式标注**（`ImplementationConfig.provider=TaskProvider.AUTODL`）：
> 两个实现方挂在 RunningHub 供应商的任务类型（34/37）下，运行时密钥注入/槽位/熔断
> 上报按**实现方级** provider 判定（`is_runninghub_task`）。曾按任务类型判定导致
> RunningHub 池密钥覆盖 `autodl.api_key`、上游 401（事故 ai_tools 13439/13440，
> 2026-11-08 修复，详见 [runninghub_concurrency_control.md](../backend/runninghub_concurrency_control.md)）。

## API 协议

两步异步（详见 [autodl_comfyui_api_config.md](autodl_comfyui_api_config.md)）：

1. `POST {base_url}/api/v1/comfyui/comfyui_workflow/{workflow_id}` → `data.task_id`
2. `GET {base_url}/api/v1/comfyui/comfyui_workflow/result/{task_id}` → `data.status` + `data.results[].url`

- 认证：`Authorization` 头放**裸 Token**（无 Bearer 前缀），Token 在 autodl.art 令牌管理创建、分组必须选 ComfyUI
- 状态机（大小写归一）：`QUEUED/RUNNING/PENDING` → 轮询；`SUCCESS/completed` → 取 `results[0].url`；`FAILED/ERROR/CANCELLED` → 失败；未知状态不判死继续轮询
- ⚠️ **结果 URL 短时效**：SUCCESS 后由 download_queue 立即下载转存
- 查询 404 按 RUNNING 处理（上游任务传播延迟），任务过期检查负责终态兜底

## 素材槽位

### 参考生（zm_u24）

| 参数 | 来源 | 说明 |
|------|------|------|
| `ref_image_0`~`ref_image_8` | `ai_tool.reference_images`（≤9 张） | 本地/局域网图经 `compress_and_upload_image_sync` 转七牛公网 URL |
| `ref_audio_0`~`ref_audio_2` | `ai_tool.audio_path`（逗号分隔，≤3 段） | 经 `upload_media_to_cdn_sync` 转公网 URL；**无对白镜头自动跳过**（口径同 RunningHub 参考生驱动） |
| `prompt` | extra_config.h3_prompt_optimize 优先 | 无对白时剥除「参考音频说明」句 |
| （参考视频） | `ai_tool.video_path` | **工作流无视频槽**：`validate_input_compatibility` 判不兼容（重试不切到本实现）；若管理员把默认实现切到 AutoDL 仍会丢弃，warning 留痕 |

### 首尾帧（lightx2v）

| 参数 | 来源 | 说明 |
|------|------|------|
| `first_frame` | `ai_tool.image_path` 首图 | 必填 |
| `last_frame` | `ai_tool.image_path` 次图 | **必填**（上游强校验）。2026-11-08 三重实测证实：仅首帧提交报"缺少必填参数：last_frame"（事故 13442）；直接探测 `first_frame` 单独同报错、`ref_image_0` 报"未定义的参数"——曾据 zm_u24（参考生，槽位 `ref_image_0`、无尾帧概念）单图测试误判"尾帧可选"并短暂放开，已回滚。上游放开后可再支持；单首帧任务经兼容钩子自动落回 RunningHub 实现 |
| （音频） | `ai_tool.audio_path` | 工作流无音频槽，忽略 |

### 输入契约能力校验（validate_input_compatibility）

同一任务的实现方素材槽位能力不同，`select_before_finish_retry_candidate` 选备用实现时会调用驱动钩子过滤不兼容候选（见 `BaseVideoDriver.validate_input_compatibility`）：

| 实现 | 判不兼容的条件 |
|------|----------------|
| 首尾帧 lightx2v | 任务有首帧但无尾帧（单首帧 RunningHub 可跑、lightx2v 上游报缺参） |
| 参考生 zm_u24 | 任务带参考视频（RunningHub 可传视频、AutoDL 无视频槽会静默丢） |

`extra_config` 为非法 JSON、数组或 `null` 时，`parse_image_mode` 回退默认首尾帧模式，钩子仍按 `image_path` 判断尾帧，提交不再因 `list.get` 抛 `AttributeError`。钩子自身的其它异常不当成兼容：候选选择会跳过该实现。空白 `video_path` 视为无参考视频。

⚠️ 管理员手动把任务默认实现切到 AutoDL 不经过此校验：切流前须确认存量提交带齐尾帧/无参考视频依赖。

### 共用字段

- `duration`：钳制 1-15；**11-15s 档 2026-11-08 已实测开放**（15s 成片实测 15.08s、1344×768，生成耗时 ~570s），仅对 AutoDL 实现开放——任务级基线仍 4-10，偏好 AutoDL 的用户前端自动扩到 4-15（`get_frontend_config` 偏好替换）；RunningHub webapp 11-15s 有显存 OOM 风险不开放，其驱动对越界时长防御性钳制回 4-10
- `resolution`：画质段（平台 `480P`→`480p`、`720P`→`768p`）+ 方向后缀（竖屏 9:16/3:4/2:3→`竖`，横屏 16:9/4:3/3:2/21:9→`横`，`1:1`→`(1:1)`），如 `768p竖`
  - ⚠️ 仅 9:16/16:9/1:1 原生匹配；4:3/3:2/21:9/3:4/2:3 按方向归并，**成片实际比例与所选不一致**（如 16:9 档实测 1344×768，4:3 也进同一横档），归并时打 warning 日志可溯源

## 算力

`MINIMAX_H3_AUTODL_768P_COMPUTING_POWER = {4: 5, 5: 7, 6: 8, 7: 9, 8: 10, 9: 12, 10: 13, 11: 14, 12: 15, 13: 17, 14: 18, 15: 19}`

- 2026-11-09 三家贴本重定价：按**高峰价** 768p 0.05 元/秒计算 `ceil(时长×0.05/0.04)`（去掉原 1.1 毛利系数，毛利 0~4%），空闲时段（00:00-08:00，0.04/0.03 元/秒）为利润冗余
- 480P 倍率：autodl 480p/768p 实际成本比为 **0.8**（=0.040/0.050 精确成本比，≠ 任务级 RunningHub 0.42），已在两个实现的 `ImplementationConfig.power_modifiers` 代码级固化（`MINIMAX_H3_AUTODL_480P_PRICE_MULTIPLIER = 0.8`，例：5s 480P = ceil(7×0.8) = 6 点），DB implementation_power 可再覆盖

## 错误处理

| 场景 | 处理 |
|------|------|
| 提交 4xx 带 msg（参数错/Token 无效） | USER 错误不重试 |
| 提交 429 | USER 错误 + `retry: True` |
| 网络/超时 | USER 错误 + `retry: True` |
| 响应格式异常 | SYSTEM + Sentry 报警 |
| 查询业务错误（code≠Success） | SYSTEM FAILED（任务不存在等非用户问题） |
| 查询 429/404/**5xx** | 保持 RUNNING 继续轮询（5xx 为上游临时故障，判死会误退款且上游可能仍在跑计费；任务过期检查兜底终态） |
| 首尾帧缺首帧/尾帧 / 参考生无图 | USER 错误（提示补充素材） |

## 测试

```bash
pytest tests/drivers/test_minimax_h3_autodl_v1_driver.py -v
```

覆盖：素材槽位映射（图/音频/截断/无对白跳过）、分辨率×比例矩阵、首尾帧双必填校验、时长钳制、提交成功/业务错误/429/网络错误、轮询各状态（含小写 completed、404 不判死）、响应校验函数。

## 真实联调记录（2026-11-07 ✅ 全通过）

用真实 Token（admin 快速配置落库）实测两条工作流：

| 工作流 | 耗时 | 成片 | 验证点 |
|--------|------|------|--------|
| zm_u24 参考生（2 卡通角色图 + 1 音色 mp3，对白 prompt） | ~230s | 768p竖 5.17s，2.98MB | 图片参考生效（洋葱/土豆角色特征高还原）；AAC 130kbps 音轨生成（音色待人工听辨） |
| lightx2v 首尾帧（苹果首尾图对） | ~180s | 1344x768 横 5.17s，2.42MB | 首尾帧约束生效（首帧/尾帧≈输入图）；16:9→768p横 映射正确 |

**实测经验**：
1. **提示词必须与参考图一致**——H3 语义遵循强于图片参考：参考图是卡通角色、prompt 写"女人"时成片直接生成真人（图片未违背但被弱化）。写"那个洋葱头卡通角色(参考图1)"后还原度即正常。
2. 七牛签名 CDN URL（http/https 均可，2h 有效）autodl 服务端可拉取；成片为 TOS 签名 URL（24h 有效），SUCCESS 后仍需转存。
3. 无对白 prompt 会跳过音频槽（has_dialogue 门控），带引号对白即传音色。
