# MiniMax H3 晨羽智云驱动（图生视频仅首帧）

## 概述

通过晨羽智云（chenyu.cn）开放 API v2 工作流调用 **MiniMax H3** 生成视频：

| 工作流 | workflow_id | revision_id | 实现方 | 挂载任务 |
|--------|-------------|-------------|--------|----------|
| Minimax-H3图生视频 | `wf_fe451b10caa4bf0a7c99` | `wfr_9088e3367308ac1939d0` | `minimax_h3_chenyu_v1`（ID 110） | `minimax_h3_image_to_video`（首尾帧，type 34） |

- **驱动文件**: `task/visual_drivers/minimax_h3_chenyu_v1_driver.py`
- **供应商**: `TaskProvider.CHENYU`（实现方级 provider 显式标注——任务类型 34 原生供应商是 RunningHub，跨供应商挂载不标注会被密钥池/槽位逻辑误伤，见 [runninghub_concurrency_control.md](../backend/runninghub_concurrency_control.md)）
- **配置键**: `chenyu.api_key`（必填，控制台「API 服务」页创建）/ `chenyu.base_url`（默认 `https://www.chenyu.cn`）

## API 协议

两步异步：

1. `POST {base_url}/api/open/v2/workflow/run/submit`（Bearer 认证）→ `data.run_order_id`
2. `GET {base_url}/api/open/v2/workflow/run/info?run_order_id=...` → `data.run_status` + `data.outputs.n92_images[0]`

- 状态机（小写归一）：`queued/running/pending/submitted/pending_review` → 轮询；`succeeded` → 取成片；`failed/error/cancelled/timeout` → 失败；未知状态不判死继续轮询（任务过期检查兜底）
- `pending_review` 为内容审核阶段（2026-11-08 E2E 实测出现），仍在执行流中
- 业务错误走 HTTP 200 + `code != 0`（如 `code:1 "运行记录不存在"`）；订单不存在可能是刚提交的传播延迟，按 RUNNING 等待
- 轮询期 HTTP 429/404/5xx 均不判死（保持 RUNNING 继续轮询，任务过期检查兜底终态）：判死会误退款且上游任务可能仍在跑——晨羽完成后按 GPU 实际分钟数结算，持续产生费用（5xx 策略与 AutoDL 驱动 a80fae37 对齐）
- FAILED 分支返回 `message` 键（非主契约 `error` 键），消费端 `visual_task` 已做 `error or message` 兜底——上游 `error_message`（内容审核拒绝/GPU 异常等）可透传到 ai_tools.message 供排障
- 幂等：`idempotency_key = zjt_h3_chenyu_{ai_tool.id}`，调度层重试提交同一任务不重复计费（重放时 `data.idempotent_replay=true`）
- 媒体：`n114_image` 直接传公网 HTTPS URL（文档明说支持，无需走 `/assets` 临时资源上传）

## 输入契约（inputs）

| 参数 | 来源 | 说明 |
|------|------|------|
| `n105_104_prompt` | prompt（优先 pipeline 优化结果） | 必填 |
| `n114_image` | `ai_tool.image_path` 首图 | 必填；**工作流无尾帧槽**——带尾帧任务经 `validate_input_compatibility` 判不兼容（避免静默丢尾帧约束），无首帧报 USER 错误 |
| `n105_111_value` | `ai_tool.duration` | 秒数，任务层 4-10 档 |
| `n119_megapixels` | 分辨率映射 | `480P→0.6` / `720P→1.0`（上游档位 0.6=480p、1=768p；2026-11-09 修正，初版误设 0.5——事故 ai_tools 13444 480P 实发 0.5）；**工作流无比例参数，成片比例跟随首帧图** |
| （音频） | `ai_tool.audio_path` | 工作流无音频槽，忽略 |

## 计费与算力（2026-11-08 实测）

提交时预冻结整笔 `quote_amount`（实测约 0.98 元/单，**仅为上限**），完成后按 GPU 实算分钟数结算并退还差额（账单流水：-0.9834 消费 + 0.8272 多退 = 净扣 0.1562）。

实测样本：4s @ 0.5MP（初版错误档位）GPU 实算 157s 实扣 **0.156 元**；用户实测 480p 0.0325 元/秒。GPU 分钟计费 ±20% 波动，480P 定价取实测上界 0.039 元/秒防亏。

算力配置（2026-11-09 三家贴本重定价，收入 0.04 元/算力，`quote_amount` 不可作为成本口径）：

| 秒数 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|------|---|---|---|---|---|---|----|
| 720P（1.0MP，ceil(秒×2.25)） | 9 | 12 | 14 | 16 | 18 | 21 | 23 |
| 480P（0.6MP，×0.44 ceil） | 4 | 6 | 7 | 8 | 8 | 10 | 11 |

`final_power = ceil(base × multiplier)`，两档 0~25% 毛利。DB `implementation_power` 可再覆盖。

## 算力/槽位豁免

实现方级 provider 标注 `TaskProvider.CHENYU`：不占用 RunningHub 槽位、不注入 RunningHub 池密钥、失败不污染 RunningHub 熔断统计（判定见 `is_runninghub_task`）。

## 测试

```bash
pytest tests/drivers/test_minimax_h3_chenyu_v1_driver.py -v
```

覆盖：inputs 构造（幂等键/分辨率→MP/优化提示词优先）、首帧必填、提交成功/业务错误/429 重试/缺 run_order_id、轮询各状态（queued/running/pending_review/成功取片/失败原因/订单不存在不判死/未知状态不判死/成功无输出）、输入契约（带尾帧不兼容、单首帧兼容）。

## 真实联调记录（2026-11-08 ✅ 全链路通过）

用真实 Key（admin 快速配置落库）+ 城市天际线首帧图直接驱动级 E2E：

| 阶段 | 结果 |
|------|------|
| 提交 | `wfrun_6d8c560538e1343a3b75`，queued，冻结 0.9834 元 |
| 轮询 | queued → running → pending_review → succeeded，全程 176s |
| 成片 | `https://media.chenyu.cn/assets/asset_.../content`，video/mp4 1.6MB 可访问 |
| 结算 | 实扣 0.1562 元 + 多退 0.8272 元 |

**实测经验**：
1. `quote_amount ≈ 0.98` 每单恒定（预冻结上限），成本核算只看 `actual_cost`/`final_amount`
2. 4s 成片 GPU 实算约 157s——按分钟计费的执行时长远大于视频时长，成本与像素/时长双挂钩
3. `pending_review` 审核态出现在 succeeded 前，驱动按运行态处理不判死
