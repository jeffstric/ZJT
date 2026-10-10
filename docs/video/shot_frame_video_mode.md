# 分镜节点视频生成模式

## 功能概述

分镜节点（shot_frame）支持两种视频生成模式，允许用户根据需求灵活选择生成流程：

- **首帧模式（first_last_frame）**：先生成分镜图，再以分镜图作为视频首帧生成视频（原有流程）
- **参考图模式（multi_reference）**：收集角色/场景/道具参考图，以多参考图模式生成视频。首帧图和尾帧图仍然可以设置；只有视频提示词里写了 `@首帧图` 或 `@尾帧图` 时，才会把对应图片排进参考图两端

## 模式切换

在分镜节点第3列"模型与生成"区域，视频模型选择器上方新增了模式切换按钮 `[首帧模式 | 参考图模式]`。

### 首帧模式

- 默认模式，保持与旧工作流完全兼容
- 需要先点击"生成分镜图"生成分镜图（作为视频首帧）
- 再点击"生成视频"以分镜图为首帧生成视频
- 视频模型列表：所有 image_to_video 模型
- 可选尾帧：第 1 列「视频首帧」下方。可以把图片节点连到尾帧端口，也可以本地上传。尾帧只参与生成视频，不改分镜图，也不进父分镜组宫格
- 模型 `supports_last_frame === false` 时，尾帧端口和上传禁用，已填的图保留但不提交
- 参考模式不隐藏尾帧区，首帧预览、首帧端口、尾帧上传和尾帧连线都保持可用。参考模式不看模型的 `supports_last_frame`，本地上传尾帧也按这个规则放行。首帧模式仍按该配置禁用尾帧端口和上传，已填的图保留但不按严格尾帧提交
- 有可用尾帧且当前是首帧模式时，`image_urls` 为 `首帧URL,尾帧URL`，接口 `image_mode` 仍是 `first_last_frame`。算力上下文用 `first_last_with_tail`。参考模式不走这条路径
- 每个分镜只保留一条尾帧连线，存在 `state.lastFrameConnections`。上传尾帧会去掉这条连线。旧工作流没有该数组时视为没有尾帧

### 参考图模式

- 可以不生成分镜图，直接使用角色、场景、道具参考图生成视频
- 视频提示词编辑框按 `@`、`/` 或 `、` 打开下拉。已设置首帧图时置顶「首帧图」，已设置尾帧图时置顶「尾帧图」，选中后插入字面量 `@首帧图` 或 `@尾帧图`。角色仍插入 `【【角色名】】`。图片提示词的 `@` 只插入角色
- 节点上把这两个标记画成带缩略图的标签。保存的仍是 `videoPromptText`，重新加载走原有恢复
- 提交时若提示词含 `@首帧图` 但没有首帧图，或含 `@尾帧图` 但没有尾帧图，提示后中止，不提交
- 被点名的首帧是参考图列表的图1，说明为「图1是首帧」；原有角色/场景/道具参考依次后移。被点名的尾帧是最后一张，说明为「图N是尾帧」。提交给接口的提示词把标记改写成对应的「图N」，并沿用原来的「图N是…」后缀。节点里保存的提示词仍是 `@首帧图` / `@尾帧图`
- 参考模式在视频提示词下方有只读的「首尾帧提示词」。有首帧图时显示 `@首帧图是首帧`，有尾帧图时显示 `@尾帧图是尾帧`，两张都有时用中文逗号连成 `@首帧图是首帧，@尾帧图是尾帧`。没有图时这一行隐藏。文字不能编辑，句子本身不翻译。它存在 `frameAutoPrompt`，不写入 `videoPromptText`
- 首帧图还在是指 `previewImageUrl` 非空且 `firstFrameDismissed` 不为真。尾帧图还在是指 `lastFrameUrl` 非空，或尾帧端口仍有连线。图片变化、清除、重新加载后按这两张图重算这四种文本
- 参考模式的「视频首帧」有清除按钮。点击后 `firstFrameDismissed` 为真，预览清空，只读字段去掉首帧句。已连接的图片节点还在，但不会自动填回预览。从菜单选图、把图片接到首帧端口，或把某张图确认为首帧后，开关关掉，首帧句回来。首帧模式不显示这个按钮
- 尾帧清除沿用原按钮。清空 `lastFrameUrl` 并去掉尾帧连线后，只读字段去掉尾帧句
- 单节点「生成视频」和分镜组「逐个生成」在参考模式读取这个字段。字段里有首帧句且首帧 URL 还在，就在本次提交副本末尾补一行 `@首帧图`（原文已有该标记则不补）。尾帧同理。副本不写回节点。随后仍把标记改写成「图N」，并附上「图N是首帧」或「图N是尾帧」
- 用户在视频提示词里手写的 `@首帧图` / `@尾帧图` 仍然生效。和只读字段同时点名同一张时只放一次。手写了标记但图已清除时，仍提示并中止，不改用户的原文
- 分镜组「合并生成视频」不读 `frameAutoPrompt`，只拼接各镜头已保存的视频提示词
- 没被只读字段或手写标记点名的首帧或尾帧不加入参考图，也不改已有序号
- 超过 `max_multi_ref_images` 时先裁掉中间的角色/场景/道具，被点名的首尾帧留在两端。名额放不下预留的首尾帧时提示并中止
- 调用 `/api/ai-app-run-image` 端点，`image_mode` 仍是 `multi_reference`，不使用 `first_last_with_ref`
- 当前模型是 MiniMax H3 参考生视频（`minimax_h3_r2v`），并且提示词含 `@首帧图` 或 `@尾帧图` 时，这次提交的 `task_id` 改为隐藏任务 `minimax_h3_kfr`（MiniMax H3 首帧参考生视频）。画面模式仍是参考模式，不切换到首帧模式，节点上保存的模型也不改。图片上限按 3 张重排。参考音频最多送 2 路，对应 `<Audio 1>` 和 `<Audio 2>`。下拉框不显示这个混合模型。其他参考模型、没有这两个标记的 H3 参考提交、以及首帧模式，都走原来选中的模型
- 故事板全能参考使用同一对标记，由服务端 `services/storyboard_frame_mention.py` 排图并在 H3 参考模型上改交 `minimax_h3_kfr`。见 `docs/storyboard/storyboard_reference_to_video.md`
- 若没有参考图，也没有被点名的首尾帧，自动回退到文生视频 API（`/api/ai-app-run`）
- 视频模型列表：仅显示支持 multi_reference 且驱动已配置的模型（如 MiniMax H3 参考生视频、seedance 2.0、vidu_q2、happy_horse_r2v）
- 无已保存模型时默认性价比档 MiniMax H3 参考生视频（`minimax_h3_r2v`），效果档为 Seedance 2.0；未配置供应商的模型不出现在新下拉中
- 参考图数量受 `max_multi_ref_images` 配置限制

## 参考图收集逻辑

参考图模式下，自动收集以下来源的参考图：

1. **角色参考图**：从**图片提示词 ∪ 生视频提示词**中提取 `【【角色名】】` 标记（去重，图片提示词中先出现的在前），查询角色 API 获取 `reference_image`。同一角色只传一张（用户在分镜里选过的造型优先，否则主图）。
2. **场景参考图**：从节点引用的场景中获取 reference_image
3. **道具参考图**：从节点引用的道具中获取 reference_image

数量超过当前视频模型的 `max_multi_ref_images` 时，收集阶段先从列表尾部裁掉。若视频提示词点名了首帧或尾帧，提交前再按「两端留给帧、中间继续裁」重排，并把「图N是xxx」后缀的序号顺延。

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
| `node.data.videoPromptText` | string | 视频提示词原文。`@首帧图` / `@尾帧图` 存在这里，提交时才改写成「图N」 |
| `node.data.previewImageUrl` | string | 视频首帧。首帧模式作为严格首帧提交；参考模式在只读字段或提示词点名首帧时作为图1 |
| `node.data.firstFrameDismissed` | boolean | 参考模式用户清除过视频首帧。为真且预览为空时，不从已连接图片自动填回 |
| `node.data.frameAutoPrompt` | string | 参考模式只读首尾帧提示词。只可能是空、`@首帧图是首帧`、`@尾帧图是尾帧`，或两者用 `，` 连接 |
| `node.data.lastFrameUrl` | string | 可选尾帧 URL。空字符串表示没有尾帧。首帧模式按模型能力提交；参考模式在只读字段或提示词点名尾帧时作为最后一张参考图 |
| `lastFrameConnections` | `{id, from, to}[]` | 图片节点到分镜尾帧端口的连线，随工作流保存 |

## 向后兼容

- 旧工作流无 `videoMode` 字段时，自动使用 `'first_last_frame'`（首帧模式）
- 序列化/反序列化自动包含 `videoMode` 字段

## 模型与模式兼容性自动迁移

部分模型按模式拆分为多个任务条目（如 MiniMax H3：`minimax_h3` 首尾帧专属 / `minimax_h3_r2v` 多参考专属），跨模式保留旧模型会被后端 `validate_model` 拒绝（`MODEL_INPUT_UNSUPPORTED`「模型 MiniMax H3 不支持多参考图输入」）。历史 BUG：TaskConfig 异步加载完成后的补偿刷新（`workflow.js` `refreshShotFrameNodesModels`）曾把不支持当前模式的已保存模型原样塞回下拉保留，构造出非法组合。

现行为（`web/js/video_model_compat.js` 的 `resolveSavedVideoModelForMode`）：

- 已保存模型**不支持当前模式** → 迁移到当前模式首个可用模型（存量坏组合在下次页面加载时自动纠正）
- 模型支持当前模式（如仅被驱动状态过滤）→ 保留原值
- 模型不在配置中（未知）→ 保留原值（沿用历史行为）

回归测试：`web/tests/video_model_compat.test.js`。

## 批量生成

分镜组节点的"逐个生成视频"功能已兼容混合模式：
- 首帧模式节点：正常生成（需有首帧图片）。该分镜如果填了可用尾帧，会一并提交
- 参考图模式节点：独立生成（不继承分镜组的视频模型，保持自己的模型选择）
- 「合并生成视频」仍只用宫格首帧，不读取各分镜视频提示词里的 `@首帧图` / `@尾帧图`，也不带各分镜的尾帧

## 相关文件

- `web/js/shot_frame_node.js` — 模式切换、尾帧端口、上传、`@首帧图` / `@尾帧图` 标签与算力
- `web/js/nodes.js` — 视频提示词放大窗口的首尾帧下拉
- `web/js/shot_frame_generator.js` — collectShotFrameRefImages(): 参考图收集
- `web/js/shot_frame_video_generator.js` — generateShotFrameVideo() 与 placeShotFrameMentionImages(): 首帧模式把尾帧拼进 image_urls；参考模式按 @ 标记重排参考图
- `web/js/workflow.js` — createShotFrameNodeWithData(): 模式与尾帧状态恢复
- `web/js/events.js` — 图片节点拖到首帧或尾帧端口
- `web/tests/shot_frame_ref_mentions.test.js` — 参考图两端排序

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

1. **角色参考图**：从各分镜的图片提示词 ∪ 生视频提示词中提取 `【【角色名】】`，跨分镜按名字去重
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
