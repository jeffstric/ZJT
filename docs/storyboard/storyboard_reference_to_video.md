# 故事板参考生视频（无需分镜图）

对照工作流分镜节点「参考图模式」（`docs/video/shot_frame_video_mode.md`）：故事板「全能参考」可不先生成分镜图，直接用角色 / 场景 / 道具参考图生成视频。

## 模式

| `videoImageMode` | 是否要分镜图 | 输入 |
|------------------|--------------|------|
| `first_last_frame` | 要 | 选中首帧（可选尾帧） |
| `multi_reference`（全能参考） | **不要** | 选中首帧（可选）+ 角色/场景/道具 + 画风参考 + 用户上传；无任何图则单镜回退文生视频 |

不新增第三种 `videoImageMode`。对口型分镜仍要求形象图 / 首帧 + 成片配音。

## 参考图顺序（去重保序）

后端 `StoryboardAgentCliService._collect_video_reference_bundle`：

1. 若已有选中首帧 → 图1（主参考）
2. 角色 / 场景 / 道具（`scene_context` → `_collect_reference_image_items`）
3. 全局画风 `style_reference_image`
4. 用户在媒体槽额外上传的图

提示词在全能参考下追加「图N是…」图例，以及画风 / 构图（`append_storyboard_visual_suffix`）。

## 入口

| 入口 | 行为 |
|------|------|
| 分镜智能体面板 → 视频图片模式下拉 | 可选项取「全部视频模型支持模式」的并集（`getAvailableVideoImageModes`），而非当前模式选中模型的能力——否则首帧模式（尤其无输入图时解析到文生视频模型）下只剩首尾帧，参考生视频入口永不出现；选中后按槽位锁定模型（参考模式 → `video.reference_to_video` 槽） |
| 直连「视频生成」`POST /scene/{id}/generate-video` | 传 `image_mode`；社区版走 `AITools.create`（`reference_images` + extra_config.`image_mode`）；无图回退文生 |
| 智能体 AI 生视频 | 全能参考时后端把自动收集的 URL 写入【视频输入说明】 |
| 时间轴「逐个生成视频」批量 | 全能参考不要求首帧；无参考图的分镜 `skipped / missing_references`（批次不混文生模型） |

## 模式持久化与恢复

- 拆分时按所选「视频生成方式」把 `videoImageMode` 持久化进 storyboard `config_json`（后端 `StoryboardModel.patch_config_json` + 前端 `persistUiConfig` 双写）
- 重新进入故事板时 `restoreUiConfig(config_json)` 恢复该模式；进入「视频生成」助手模式触发的 `ensureVideoImageModeSupported()` 按**参考视频槽模型**校验能力（`getSelectedVideoModel` 在参考模式下固定解析参考槽，不因「尚无输入图」落到文生视频模型），参考生视频模式不会被误重置回首尾帧
- 行为级回归见 `web/tests/storyboard_reference_mode_restore.test.js`

## 参考模式下分镜图的状态展示

参考生视频模式下分镜图**非必需**（拆分时也不自动补全首帧），为避免「待生成」误导用户必须补图：

- 分镜卡片角标 / 预览占位 / 时间轴缩略图：缺失分镜图展示「免分镜图」（`getFirstFrameStatusLabel` 对 `missing` 的文案分支）
- 顶部统计：不再展示图片「N 个待生成」，改为追加「参考生视频免分镜图」
- 批量补全按钮：文案为「补全分镜图（可选）」——补全仅是可选增强，有图会作为主参考一并注入

拆分弹窗若锁定参考生视频，会在发布前把同一场内的短镜头合并成接近模型上限的单条分镜（`pack_shots_for_reference_video`），因此一镜仍对应一条视频，导出不用 clip 窗口。

## Beta 标识

参考生视频仍在灰度验证期，`Beta` 徽标只放在空间充足的入口（`web/js/storyboard/render.js` 的 `REF_VIDEO_BETA_TAG`，样式 `web/css/storyboard.css` 的 `.beta-tag`，与 `web/css/index.css` 同名样式保持一致）：

- 「从剧本拆分」弹窗 → 视频生成方式 →「参考生视频」chip
- 分镜智能体面板 → 视频图片模式下拉面板 →「全能参考」选项

收起态模式下拉按钮 / 单选项静态标签**不带** Beta：工具栏区域狭小，徽标冗余（截图反馈优化）。

功能转正时删除该常量与两处 `beta: true` 声明即可（有 `web/tests/storyboard_split_video_gen_mode.test.js` 断言兜底）。

## 回退

- 单镜全能参考且一张图都没有 → `text_to_video`，使用文生视频槽模型
- 批量全能参考且该镜无图 → 跳过 `missing_references`，不在同一批次回退文生

## 相关文件

- `services/storyboard_agent_cli_service.py` — 收集、图例、批量规划、CLI `generate_video`
- `api/storyboard.py` — 直连 generate-video、智能体上下文
- `web/js/storyboard/events.js` / `auto_missing_videos_state.js` / `render.js`
- `web/js/storyboard/state.js` — `getAvailableVideoImageModes`（模式下拉可选项并集）、`getSelectedVideoModel`（参考模式固定解析参考视频槽）
