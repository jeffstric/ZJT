# 故事板参考生视频 · 智能体测试移交

> 移交对象：负责本功能手工/接口验收的智能体。  
> 实现分支：`develop_f739`  
> 设计文档：[storyboard_reference_to_video.md](storyboard_reference_to_video.md)  
> 操作 API：[`.agents/skills/storyboard-agent-api/SKILL.md`](../../.agents/skills/storyboard-agent-api/SKILL.md)

本轮做了两件事，**不要再测「按幕把多条短分镜合成一条视频」**（已废弃）：

1. **全能参考生视频**：分镜可以没有首帧，直接用角色/场景/道具参考图出视频。
2. **剧创式拆分**：拆剧本时锁定「参考生视频」，同一场内把短镜头打包成接近模型上限（如 Seedance 2.0 = 15 秒）的单条分镜。

---

## 1. 环境

```bash
git checkout develop_f739
git pull origin develop_f739
```

- 服务端需能跑（`config_dev.yml`、数据库、算力账户）。
- HTTP 认证：用户首页点用户名旁智能体图标，复制 connection package，按 skill 用 `POST /api/agent-auth/exchange` 换 `auth_token`。
- 不要把 token 拼进 URL。
- 选一个**已有角色参考图、场景参考图**的世界；剧本至少两场、每场有多段连续动作/对白（方便验证打包）。

建议剧本：同一客厅连续 20 秒以上表演，再换一个地点。预期参考生拆完后，客厅被压成 1～2 条接近 15 秒的分镜，而不是一堆 3～5 秒碎镜。

---

## 2. L1 自动化（先跑，不启服务也可）

在仓库根目录：

```bash
python -m pytest tests/llm/test_shot_pack.py tests/storyboard/test_storyboard_generate_from_script.py::test_build_scenes_packs_shots_in_reference_mode tests/storyboard/test_storyboard_agent_cli_service.py::test_generate_video_multi_reference_appends_legend_and_style tests/storyboard/test_storyboard_agent_cli_service.py::test_generate_video_multi_reference_falls_back_to_text_when_no_images tests/storyboard/test_storyboard_agent_cli_service.py::test_plan_video_batch_multi_reference_allows_missing_first_frame tests/storyboard/test_storyboard_agent_cli_service.py::test_plan_video_batch_filters_selection_and_requires_first_frame -q
```

期望：**全部 passed**。

```bash
npx vitest run web/tests/storyboard_reference_to_video.test.js web/tests/storyboard_split_video_gen_mode.test.js
```

期望：5 passed。

打包规则对照：

| 输入 duration | 上限 | 期望 |
|---------------|------|------|
| 5+5+6 | 15 | 两条：10s（含 `镜头1：0~5S`）+ 6s |
| 5+12 | 15 | 不合（17>15），仍两条 |
| 跨两个 `shot_groups` 各 5s | 15 | **不跨组**合并 |

---

## 3. L2 拆分（参考生 · 必测）

### 3.1 页面路径

1. 打开 `/storyboard?world_id=…&episode_number=…`（空故事板或新建）。
2. 拆分弹窗选 **参考生视频**（不要选首帧生视频）。
3. **单镜最长时长**应出现当前参考视频模型的档位（Seedance 2.0 一般为 15），默认取最大档。
4. 默认视频模型应是参考视频模型列表，不是只支持首尾帧的模型。
5. 提交拆分，等到 `completed`。

断言：

- 时间轴 **没有** 自动开始「补全首帧」。
- `GET` 故事板 `config_json.videoImageMode === "multi_reference"`。
- `list-scenes`：同一场连续短戏被合成更少、更长的分镜；单镜 duration 多数接近 15（或所选上限），换场处切开。
- 合并镜的 `video_prompt` 含 `镜头1：0~` 时段拼接。

### 3.2 智能体命令路径

先 `list-llm-models`，再：

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/split-from-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"storyboard_id":<id>,"model":"deepseek-v4-flash","model_id":<id>,"vendor_id":<id>,"max_group_duration":15,"video_gen_mode":"multi_reference","max_shot_duration":15}'
```

CLI 等价：

```bash
python -m scripts.storyboard_agent_cli split-from-script \
  --storyboard-id <id> --user-id <uid> --auth-token "<auth_token>" \
  --model deepseek-v4-flash --model-id <id> --vendor-id <id> \
  --video-gen-mode multi_reference --max-shot-duration 15 --max-group-duration 15
```

轮询 `GET /api/script-split/tasks/{task_id}` 直到 `completed`，再 `list-scenes`。断言同 3.1。

对照：同一剧本再用 `video_gen_mode=first_last_frame` 拆到**新**故事板，分镜数应明显更多、单镜更短。

---

## 4. L3 无首帧直接生视频（必测）

前置：参考生拆完的故事板，分镜 **没有** 选中首帧，但角色/场景有参考图。

### 4.1 页面

1. 确认模式是 **全能参考**（与拆分锁定一致）。
2. 时间轴按钮不应是灰色「需先补全画面」，应是「全能参考逐个生成视频 (N)」。
3. 打开分镜助手「视频生成」，无首帧也可发送。
4. 右侧出现视频生成中占位，轮询直到完成，分镜有 `video_url`。

### 4.2 命令

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/generate-video" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":<id>,"mode":"image_to_video","image_mode":"multi_reference"}'
```

- 有参考图：应提交图生/参考生，不要 400「请先生成并选中首帧」。
- 提示词应带「图N是…」图例（可从 `scene-context` 或任务 extra 核对）。
- 轮询 `task-status` `asset_type=video`：`status` 2 且有 `result_url`。延迟选中：成功前 `selected_video_id` 仍是旧值（没有则保持空），成功后才切到新资产。

批量：

```bash
curl -s -X POST "$BASE_URL/api/storyboard/<sid>/auto-generate-missing-videos" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"image_mode":"multi_reference","continue_on_error":true}'
```

无首帧但有角色/场景参考图的镜应为 pending/submitted，不应 `missing_first_frame`。一张参考图都没有的镜可为 `missing_references` 跳过。

### 4.3 首帧模式回归

切回 **首尾帧** 后：无首帧点生视频应提示先生成首帧；批量按钮「需先补全画面」。

---

## 5. 不要测 / 不要当成 bug

| 现象 | 原因 |
|------|------|
| 没有「按幕合并成一条视频」按钮 | 已废弃，改拆分拉满 |
| 参考生拆完不自动生分镜图 | 预期 |
| 对口型仍要形象图+配音 | 本期不改 |
| `video_workflow.html` 分镜组合并生视频 | 工作流原能力，故事板不搬 |
| 社区版智能体 AI 生视频不可用 | 直连「视频生成」才是社区入口 |

---

## 6. 验收清单（回报时逐条打勾）

- [ ] L1 pytest / vitest 全绿
- [ ] 参考生拆分：分镜变少变长，接近 15s，换场切开，`videoImageMode=multi_reference`
- [ ] 参考生拆完不自动补全首帧
- [ ] 无首帧 + 全能参考：单镜 generate-video 成功
- [ ] 无首帧 + 全能参考：批量 missing-videos 不因缺首帧全跳过
- [ ] 首尾帧模式仍强制首帧
- [ ] 未把 token 放进 URL

失败时附：`storyboard_id` / `scene_id` / `task_id`、请求 body、响应 JSON、分镜 `duration` 列表。
