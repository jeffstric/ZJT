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
| 直连「视频生成」`POST /scene/{id}/generate-video` | 传 `image_mode`；社区版走 `AITools.create`（`reference_images` + extra_config.`image_mode`）；无图回退文生 |
| 智能体 AI 生视频 | 全能参考时后端把自动收集的 URL 写入【视频输入说明】 |
| 时间轴「逐个生成视频」批量 | 全能参考不要求首帧；无参考图的分镜 `skipped / missing_references`（批次不混文生模型） |

批量文案用「逐个生成」。剧本拆分若锁定参考生视频，会在发布前把同一场内的短镜头合并成接近模型上限的单条分镜（`pack_shots_for_reference_video`），因此一镜仍对应一条视频，导出不用 clip 窗口。

## Beta 标识

参考生视频仍在灰度验证期，所有 UI 入口统一带 `Beta` 徽标（`web/js/storyboard/render.js` 的 `REF_VIDEO_BETA_TAG`，样式 `web/css/storyboard.css` 的 `.beta-tag`，与 `web/css/index.css` 同名样式保持一致）：

- 「从剧本拆分」弹窗 → 视频生成方式 →「参考生视频」chip
- 分镜智能体面板 → 视频图片模式下拉 →「全能参考」选项 / 收起态按钮

功能转正时删除该常量与两处 `beta: true` 声明即可（有 `web/tests/storyboard_split_video_gen_mode.test.js` 断言兜底）。

## 回退

- 单镜全能参考且一张图都没有 → `text_to_video`，使用文生视频槽模型
- 批量全能参考且该镜无图 → 跳过 `missing_references`，不在同一批次回退文生

## 相关文件

- `services/storyboard_agent_cli_service.py` — 收集、图例、批量规划、CLI `generate_video`
- `api/storyboard.py` — 直连 generate-video、智能体上下文
- `web/js/storyboard/events.js` / `auto_missing_videos_state.js` / `render.js`
