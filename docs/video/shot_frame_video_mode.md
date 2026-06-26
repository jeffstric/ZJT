# 分镜节点视频生成模式

## 功能概述

分镜节点（shot_frame）支持两种视频生成模式，允许用户根据需求灵活选择生成流程：

- **首帧模式（first_last_frame）**：先生成分镜图，再以分镜图作为视频首帧生成视频（原有流程）
- **参考图模式（multi_reference）**：跳过生成分镜图，直接收集角色/场景/道具参考图，以多参考图模式生成视频

## 模式切换

在分镜节点第3列"模型与生成"区域，视频模型选择器上方新增了模式切换按钮 `[首帧模式 | 参考图模式]`。

### 首帧模式

- 默认模式，保持与旧工作流完全兼容
- 需要先点击"生成分镜图"生成分镜图（作为视频首帧）
- 再点击"生成视频"以分镜图为首帧生成视频
- 视频模型列表：所有 image_to_video 模型

### 参考图模式

- 无需生成分镜图，直接使用参考图生成视频
- 自动从节点配置的角色、场景、道具中收集参考图
- 调用 `/api/ai-app-run-image` 端点，`image_mode=multi_reference`
- 若无任何参考图，自动回退到文生视频 API（`/api/ai-app-run`）
- 视频模型列表：仅显示支持 multi_reference 的模型（如 veo3、grok、seedance 2.0、vidu_q2、happy_horse_r2v）
- 参考图数量受 `max_multi_ref_images` 配置限制

## 参考图收集逻辑

参考图模式下，自动收集以下来源的参考图：

1. **角色参考图**：从图片提示词中提取 `【【角色名】】` 标记，查询角色 API 获取 reference_image
2. **场景参考图**：从节点引用的场景中获取 reference_image
3. **道具参考图**：从节点引用的道具中获取 reference_image

## 文生视频回退

当参考图模式下没有收集到任何参考图时：
- 自动回退调用 `/api/ai-app-run`（text_to_video 端点）
- 仅当所选视频模型同时支持 text_to_video 分类时才可用（如 veo3、grok、seedance 2.0 / 2.0 Fast / 2.0 Mini）
- 若模型不支持 text_to_video，提示用户添加参考图或切换模型
- 回退时启用角色标记替换（`replaceCharacterMarkers`）

## 数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `node.data.videoMode` | `'first_last_frame'` / `'multi_reference'` | 视频生成模式 |

## 向后兼容

- 旧工作流无 `videoMode` 字段时，自动使用 `'first_last_frame'`（首帧模式）
- 序列化/反序列化自动包含 `videoMode` 字段

## 批量生成

分镜组节点的"逐个生成视频"功能已兼容混合模式：
- 首帧模式节点：正常生成（需有首帧图片）
- 参考图模式节点：独立生成（不继承分镜组的视频模型，保持自己的模型选择）

## 相关文件

- `web/js/nodes.js` — createShotFrameNode(): 模式切换 UI
- `web/js/shot_frame_generator.js` — collectShotFrameRefImages(): 参考图收集
- `web/js/shot_frame_video_generator.js` — generateShotFrameVideo(): API 分支逻辑
- `web/js/workflow.js` — createShotFrameNodeWithData(): 模式状态恢复

---

# 分镜组节点视频生成模式

## 功能概述

分镜组节点（shot_group）的"合并生成视频"和"逐个生成视频"功能支持两种生成模式，通过第3列"视频生成"区域的下拉选择器切换：

- **首帧模式（first_last_frame）**：将多个分镜的首帧图合并为宫格图，以宫格图作为首帧生成视频（原有逻辑）
- **参考模式（multi_reference）**：收集所有分镜的角色/场景/道具参考图，以多参考图模式生成视频

## 模式切换

在分镜组节点第3列"视频生成"区域，视频模型选择器上方新增了"视频生成模式"下拉框（首帧模式 / 参考模式）。

在分镜节点的"模型与生成"区域，视频模型选择器上方新增了模式切换按钮 `[首帧模式 | 参考模式]`。

### 首帧模式

- 默认模式，保持与旧工作流完全兼容
- 多分镜时合并为首帧宫格图，单分镜直接使用首帧图
- 调用 `/api/ai-app-run-image`，`image_mode=first_last_frame`
- 合并按钮可见性由模型的 `supports_grid_merge` 配置控制

### 参考模式

- 收集所有分镜节点的角色/场景/道具参考图（复用 `collectReferenceImagesForGrid`）
- 调用 `/api/ai-app-run-image`，`image_mode=multi_reference`
- 合并按钮始终显示（不需要宫格合并支持）
- 若无任何参考图，自动回退到文生视频 API（`/api/ai-app-run`）

## 对两个按钮的影响

| 按钮 | 首帧模式 | 参考模式 |
|------|---------|---------|
| 合并生成视频 | 宫格合并首帧图 → `first_last_frame` | 收集参考图 → `multi_reference`，无参考图降级 `text_to_video` |
| 逐个生成视频 | 各子节点用首帧图（继承组模型） | 各子节点收集参考图 → `multi_reference`（不继承组模型） |

## 参考图收集

参考模式下，复用 `collectReferenceImagesForGrid()` 函数，从所有分镜节点中收集：

1. **角色参考图**：从图片提示词中提取 `【【角色名】】` 标记，查询角色 API 获取 reference_image
2. **场景参考图**：从分镜引用的场景中获取 reference_image
3. **道具参考图**：从分镜引用的道具中获取 reference_image

## 数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `node.data.videoGenMode` | `'first_last_frame'` / `'multi_reference'` | 分镜组视频生成模式 |

## 向后兼容

- 旧工作流无 `videoGenMode` 字段时，自动使用 `'first_last_frame'`（首尾帧模式）
- 序列化/反序列化自动包含 `videoGenMode` 字段

## 相关文件

- `web/js/nodes.js` — createShotGroupNode(): 模式选择器 UI、generateShotGroupVideo(): 合并生成逻辑、generateAllShotFrameVideos(): 逐个生成逻辑
- `web/js/nodes.js` — collectReferenceImagesForGrid(): 参考图收集
- `web/js/workflow.js` — createShotGroupNodeWithData(): 模式状态恢复
