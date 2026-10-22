# 生成类工具统一注册表（GENERATION_TOOL_REGISTRY）

## 背景

同一批生成类工具名曾散落 3 个文件共 6 份手写清单，各自维护、互不感知，新增工具时极易漏配：

| 清单 | 位置 | 用途 |
| --- | --- | --- |
| project_ids 收集白名单 | `script_writer_core/agents/expert_agent.py` | 收集工具返回的 `project_ids` 进 `pending_project_ids` |
| `BILLABLE_GENERATION_TOOLS` | `script_writer_core/agents/power_confirm.py` | 算力确认门（提交前弹窗确认） |
| `IMAGE_TOOLS` / `VIDEO_TOOLS` | 同上 | 算力预估分流（`_estimate_image` / `_estimate_video`） |
| `TOOL_LABELS` | 同上 | 确认弹窗中文展示名 |
| `VIDEO_GENERATION_EXPERT_SKILLS` | `script_writer_core/agents/pm_agent.py` | 按 skill_name 决定推 `video_task_submitted` 还是 `image_task_submitted` |

## 两次漏配事故

1. **会话 5847bc38**：`digital-human-creator` 技能不在 `VIDEO_GENERATION_EXPERT_SKILLS`，数字人视频被推成
   `image_task_submitted`，前端按图片轮询，完成后图片 URL 为空，误报"图片生成失败，请稍后重试"。
2. **会话 cf028375（dev2，project 12752）**：两段式数字人（v2）全部经 `confirm_digital_human` 提交，但
   expert_agent 的 project_ids 收集白名单未同步补入，`video_task_submitted` 事件不推送——视频实际生成
   成功，界面却全程看不到"视频生成中"，完成后也不展示视频。

## 现行机制

唯一数据源：`config/constant.py` 的 `GENERATION_TOOL_REGISTRY`。每个生成类工具登记四个字段：

| 字段 | 含义 |
| --- | --- |
| `emits_project_ids` | 返回结构含 `project_ids` 且需推送前端轮询（expert_agent 收集 → pm_agent 推 SSE 事件）。四宫格三件套走独立前端展示且不返回 project_ids，为 `False` |
| `estimate` | 算力预估分流：`image`（`_estimate_image`）/ `video`（`_estimate_video`）/ `digital_human`（`_estimate_digital_human` 固定预估）/ `""`（不参与预估） |
| `billable` | 是否纳入算力确认门。两段式数字人 prepare/confirm 流程自带 UI 确认、`generate_marketing_video` 的内部子工具各自过门，均为 `False`（不重复弹门） |
| `label` | 确认弹窗等处的中文展示名 |

派生常量（业务代码只允许引用派生常量，禁止再手写工具名清单）：

- `GENERATION_TOOLS_EMIT_PROJECT_IDS` — expert_agent project_ids 收集白名单
- `GENERATION_TOOLS_BILLABLE` — 算力确认门（power_confirm 以 `BILLABLE_GENERATION_TOOLS` 别名再导出，外部引用不变）
- `GENERATION_TOOLS_IMAGE` / `GENERATION_TOOLS_VIDEO` — 算力预估分流（power_confirm 的 `IMAGE_TOOLS` / `VIDEO_TOOLS`）
- `GENERATION_TOOLS_ESTIMATE_DIGITAL_HUMAN` — 数字人固定预估分流
- `GENERATION_TOOL_LABELS` — 工具中文展示名
- `VIDEO_GENERATION_EXPERT_SKILLS` — 视频类专家技能清单（skill_name 维度，与工具名维度并存）

## 新增生成工具时的操作

**只在 `GENERATION_TOOL_REGISTRY` 登记一行**，按工具实际语义勾选字段：

- 返回 `project_ids` 且要前端展示进度/结果 → `emits_project_ids: True`
- 有独立算力预估规则 → `estimate` 填对应类别（无则 `""`，走 unknown 降级）
- 需要提交前弹窗确认 → `billable: True`
- 补 `label` 中文名

若同时新增**专家技能**（skill_name）产出视频任务，还需在 `VIDEO_GENERATION_EXPERT_SKILLS` 追加技能名。

## 行为一致性验证

重构提交（2026-10-19）以临时测试逐成员断言派生清单与重构前 6 份清单完全一致（含
`generate_digital_human` 故意不在 `VIDEO_TOOLS`——它的预估走独立的 `_estimate_digital_human`
固定值分支，若混入 `_estimate_video` 会变成按参数预估）后才删除临时测试。
