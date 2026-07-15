# Storyboard Image Batch Sequence Modes

`auto-generate-missing-images` creates an orchestration batch for missing storyboard frame images. The orchestration batch controls ordering and dependencies, while each ready item still calls the existing `generate_image()` path. Auth and computing-power deduction therefore remain on the same path as manual frontend generation.

## Modes

- `speed`: submit all missing images up to `limit` without previous-frame references.
- `balanced`: default. Submit the first ready scene in each parsed group concurrently. Later scenes in the same group wait for the previous scene result and submit through `image_edit` with that result as `source_image`.
- `quality`: enterprise-only for first-frame generation. When `StoryboardFeatureFlags.QUALITY_GRID_FIRST_FRAME_ENABLED` is enabled, ready scenes in the same parsed group (`storyboard_image_batch_item.group_key` / `prompt_json.source.group_id`) are submitted as 2x2 or 3x3 storyboard first-frame grids and then split back to each scene; `act_name` is display/fallback metadata and must not merge multiple parsed groups into one grid. The old global previous-frame chain is only the fallback path when this feature flag is disabled.

## Frontend Dialog Copy

When `storyboard.html` opens a storyboard without any scenes, the "generate from script" dialog shows three user-facing modes. The dialog uses a two-column layout for model config and split options, followed by a full-width image generation mode section; it collapses to a single column on narrow screens. Each mode is a single clickable card that both explains and selects the mode (no separate button row). The currently selected mode card is visually highlighted. `quality` remains enterprise-only in the existing click handling.

- 速度模式 (`speed`): 快速拆分剧本，适合草稿预览和方案试跑；标签：先出结果。
- 均衡模式 (`balanced`): 兼顾生成速度与分镜质量，质量与效率折中；标签：质量和效率折中。
- 效果模式 (`quality`): 为长篇连续叙事打造，锁定场景、光影与角色站位一致性，呈现影院级镜头质感；标签：影院级一致性。商业版专属，非商业版用户点击会提示购买。

## 前端视觉规范

三张模式卡片采用 A“柔和高级感”方案，保持统一结构并让 `quality`（影院级一致性）成为唯一视觉强调点：

- 卡片统一使用“标题行 → 描述 → 底部 meta 标签”结构和相同高度，避免标题、radio、标签因通用 `span` 规则形成多层胶囊。
- 每张卡片标题左侧保留 `.sequence-mode-radio`：未选中为空心圆，选中后用 4px 主色圆环表达状态；`balanced` / `speed` 使用产品主蓝，`quality` 使用暖金色。
- `balanced` / `speed` 使用浅灰白底 `#f8fafc`；普通选中态使用主蓝细边框与低透明度蓝底，不增加循环动画。
- `quality`（`.sequence-mode-intro-card--cinema`）使用淡金背景 `#fff8e7`、暖金边框 `#e6b94f` 和低强度阴影；标题行只保留简洁 `PRO` 徽章，底部保留“影院级一致性”标签。
- 已移除深紫黑背景、皇冠、渐变标题、脉冲发光和流光扫过，避免高级能力卡片与现有浅色弹框割裂。
- 社区版锁定态（`.sequence-mode-intro-card.is-locked`）保持完整可读性，在底部 meta 行显示锁图标和“商业版”。卡片仍可点击并沿用 `events.js` 的商业版提示与拦截逻辑，不写入 state、不持久化。

商业版门控的前后端约定保持不变：前端拦截（`events.js` + `state.js` 加载回退）与后端 `enterprise_only`（HTTP 403）双门控。视觉层仅增强表达，不改变门控语义。

Inserted scenes without parsed group metadata inherit the previous scene's group. If the first scene has no group metadata, it uses a temporary manual group.

Existing completed scenes participate in dependencies. If A1 already has a first frame and A2 is missing, A2 references A1 without regenerating A1. Existing running scenes also participate; dependent scenes wait until the selected asset has a result URL.

When a dependent scene uses the previous scene image, that previous image is appended after the scene's described reference images. This keeps prompt legends aligned: if the prompt says Image #1 is a character and Image #2 is a location, those images remain at the front of the image-edit queue, while the previous storyboard frame is an extra continuity reference at the tail. The previous-frame item is also described in the reference legend as `图N是前一分镜。` (no name after the colon), so the legend image numbers stay strictly aligned with the image-edit URL queue. If the previous-frame URL coincides with an existing role/prop/location reference, it is de-duplicated and not described twice.

## CLI

```bash
python -m scripts.storyboard_agent_cli auto-generate-missing-images \
  --storyboard-id 10 \
  --user-id 1 \
  --auth-token "<auth_token>" \
  --asset-type first_frame \
  --limit 5 \
  --sequence-mode balanced
```

The command returns `batch_id`. Query it with:

```bash
python -m scripts.storyboard_agent_cli storyboard-image-batch-status \
  --batch-id <batch_id> \
  --user-id 1
```

## HTTP

```bash
curl -X POST "$BASE_URL/api/storyboard/10/auto-generate-missing-images" \
  -H "Authorization: Bearer <auth_token>" \
  -H "Content-Type: application/json" \
  -d '{"asset_type":"first_frame","mode":"auto","limit":5,"sequence_mode":"balanced"}'
```

```bash
curl "$BASE_URL/api/storyboard/image-batches/<batch_id>/status" \
  -H "Authorization: Bearer <auth_token>"
```

The response status includes `pending`, `running`, `completed`, `failed`, and `partial`.

## Script splitting behavior

The same `sequence_mode` is submitted when generating storyboard scenes from a script. `speed` and `balanced` retain the existing serial segment checkpoint path. Enterprise `quality` first asks the planning LLM for a schema v2 global physical-space contract, then generates up to three independent script segments concurrently. Segment boundaries remain semantic LLM decisions and every generated source segment is hard-limited to 1500 characters.

The quality planner and spatial validation implementation live under `enterprise/services/script_split_quality/`. Community builds reject `quality`; they do not import or contain the quality planning algorithm.
