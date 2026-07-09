# 故事板编辑器 - 画风设置与模型动态选择设计

> **状态**：已实现并验证（2026-07-02）。画风/构图移至 header 紧凑展示+点击编辑；左侧卡片已删除；模型配置弹窗支持 tabs 切换对话/生图/视频模型（分组LLM + 分类图像/视频模型）；默认选择逻辑已实现。
> **验证方式**：通过 Playwright 打开 http://localhost:9003/storyboard?... 实际浏览器检查 + 代码审查。

## 1. 背景与需求

用户针对 `web/storyboard.html` 提出三点明确设计要求：

1. **支持调整画风（style）和构图倾向（composition_preference）**  
   这两个字段已存在于 `model/storyboard.py`、`Storyboard` 实体、数据库表以及 `api/storyboard.py` 的创建/更新逻辑中。当前仅在左侧信息卡片只读展示，缺少编辑入口。

2. **左下角“分镜助手”（AI 对话框）需要支持图片模型和视频模型的动态显示**  
   参考 `web/index.html` 及 `js/pages/text_to_image.js` / `image_to_video.js` 的逻辑，区分 **文生图 / 图生图**、**文生视频 / 图生视频**（见 `config/unified_config.py` TaskCategory）。  
   当前实现硬绑定固定分类，需要改进为按类型动态呈现模型列表。

3. **支持修改“对话模型”（LLM 模型）**  
   参考 `web/script_writer.html` 的模型选择器实现（从 `/api/models` 加载、vendor 分组、localStorage 记忆）。

**约束**：
- 必须说中文。
- 所有 web 接口内部函数必须非阻塞。
- 功能改动后同步更新 `docs/` 目录。
- 工作流重新加载友好（通过 `config_json` + `restoreUiConfig`）。
- 兼容 Windows/Linux/macOS。

## 2. 第一版实现范围（保守策略 - 关键决策）

根据 review 反馈，**第一版只开放当前后端已完全支持的能力**：

### 完整可用
- 全局画风 + 构图倾向编辑
- “图片生成”模式 → **仅文生图**（TEXT_TO_IMAGE）
- “视频生成”模式 → **仅图生视频**（IMAGE_TO_VIDEO）

### 准备但禁用 / 弱化（明确标注“待接入”）
- 图生图 / 图片编辑（IMAGE_EDIT）：后端 `generate_scene_image` 目前**不传 image_path**，无法真正条件生成。
- 文生视频（TEXT_TO_VIDEO）：后端 `generate_scene_video` 非数字人分支**始终要求首帧 + image_path**。
- 对话改图（LLM 驱动）：后端 `/scene/{scene_id}/ai-chat` 仍是占位，前端已有“正在接入中”提示。

**好处**：后端 `/models` 接口一次扩展全部分类（为 v2 做准备），但前端第一版**不渲染类型切换 toggle**，避免用户点击到 400 错误或误解功能已完成。

后续当后端支持 `image_path` 传递 和 文生视频无图路径 后，再开放对应切换。

## 3. UI 布局设计（实际实现）

### 3.1 画风/构图倾向（全局）

- **位置**：header 顶部左侧，紧邻 “第X集 · 16:9” 右侧。
- 显示为紧凑文本：`画风：xxx 构图倾向：yyy`（超长截断 ~15 字 + title tooltip 完整内容）。
- **可点击编辑**：点击 `.header-style-info` 弹出专用编辑弹窗（含画风 + 构图倾向两个输入框），保存到后端，立即刷新 header 显示。
- 左侧不再有 style-settings-card 或 thumbnail-card（已按反馈删除）。
- 初始化：后端 create 时从 World.visual_style / composition_preference 继承（model/storyboard.py）。

### 3.2 左下角 AI 对话框（分镜助手）

结构：
- 聊天输入 + 发送
- 模式下拉：对话改图 / 图片生成 / 视频生成 （chatMode 映射）
- 齿轮按钮打开模型配置弹窗（data-action="open-model-config"）
- 模型配置弹窗（tabs）：
  - 对话模型：按供应商分组（optgroup），使用 /api/vendors + /api/models（参考 script_writer）
  - 生图模型：展示 text_to_image / image 模型
  - 视频模型：展示 image_to_video 模型
- 选择后立即更新 state 并 persistUiConfig

无 toolbar 上的小 LLM select（已移除）。

### 3.3 默认模型选择

bootstrap 中实现优先级（仅首次无保存值时）：
deepseek-v4-flash（deepseek vendor） > qwen3.5-plus (zjt_api) > 任意 qwen3.5-plus > 第一个。
同时支持从 storyboard.config_json 恢复。

## 4. 技术实现要点

### 后端（api/storyboard.py）
- 仅修改 `get_storyboard_models`：
  - 返回新增 4 个分类列表。
  - 保留 `image_models` / `video_models` 键以向前兼容现有前端逻辑。
- **不修改** `generate_scene_image` 和 `generate_scene_video`。

### 前端（web/js/storyboard/）
- `state.js`：
  - 新增字段接收 4 类模型 + llmModels + selectedLlmModel。
  - 更新 `serializeUiConfig` / `restoreUiConfig` 以支持 reload 复原。
- `bootstrap.js`：加载 LLM / vendors / models；实现默认 LLM 优先级选择 + restore。
- `render.js`：renderHeader 内联 header-style-info（右侧）；renderModelConfigModal + render*ModelConfig（tabs + 条件内容 + 单个 grouped dialogue select）；删除 renderStyleSettings 和 thumbnail 渲染；使用 truncate。
- `events.js`：configTab（closest 早处理）、configSelect（String 比较 + mainSel sync）、open-model-config 设置 tab；新增 edit-global-style / save-global-style / close-global-style，使用 renderGlobalStyleDialog 实现双字段弹窗编辑。

### i18n & CSS
- 在 `web/i18n/locales/zh-CN/storyboard.json`（及 en）补充画风、构图、待接入等文案。
- CSS 复用现有 `.info-card`、`.chat-mode-select` 样式，新增少量 `.style-settings-card`。

## 5. 重新加载与状态持久化

所有新增 UI 状态（当前选中模型、LLM 模型、画风编辑临时态）通过 serializeUiConfig 纳入 `config_json`，同时 localStorage 作为 fallback。启动时优先 config_json，其次 localStorage。

### 5.1 生图/视频模型的跨故事板记忆

`selectedImageTaskId` / `selectedVideoTaskId` 除写入当前故事板 `config_json` 外，另新增 localStorage 跨故事板兜底键：

| 字段 | localStorage 键 | 写入点 | 读取/兜底点 |
|------|----------------|--------|-------------|
| 生图模型 | `storyboard_lastSelectedImageTaskId` | `events.js` 的 `data-config-select="image"` change 处理 | `state.js` `setModels` → `pickRememberedTaskId` |
| 视频模型 | `storyboard_lastSelectedVideoTaskId` | `events.js` 的 `data-config-select="video"` change 处理 | `state.js` `setModels` → `pickRememberedTaskId` |

**优先级链路**：`config_json`（当前故事板，主记忆）> `localStorage`（跨故事板兜底）> 模型列表第一个。

`pickRememberedTaskId(models, storageKey)` 在读取 localStorage 后会**校验该 task_id 仍存在于当前可用模型列表**，避免读到已下线模型的 task_id 造成空选中；若不存在则回退到列表第一个并同步回写 localStorage 以固化默认。该兜底对齐已有 LLM 模型的 `storyboard_lastSelectedLlmModel` / `storyboard_lastScriptSplitLlmModel` 设计。

### 5.2 预览区与分镜序列缩略图的比例适配

竖屏（9:16）故事板下，预览区与底部分镜序列缩略图原先会出现显示异常或严重裁切。修复后两者均按故事板 `workflowRatio` 自适应：

**主预览区（`.preview-wrapper` / `.preview-media`）** —— 纯 CSS 修复（`storyboard.css`）：

- `.preview-wrapper`：移除 `display:grid; place-items:center`，背景改为纯黑 `#000` 作为信箱留白。
- `.preview-media`：新增 `position:absolute; inset:0` 强制铺满容器，规避 grid item 对带固有宽高比的 `<img>`/`<video>` 解析不稳定的怪异行为；保留 `object-fit:contain`，竖屏图高度 100%、左右留纯黑黑边。
- `.preview-empty`：补 `position:absolute; inset:0; display:grid; place-items:center` 维持空状态居中。
- `.storyboard-thumb .preview-media`：补 `position:static` 让网格卡缩略图回归普通流（防回归）。

**分镜序列缩略图（`.scene-timeline-list` / `.scene-timeline-thumb`）** —— JS + CSS 配合：

- `render.js` 在 `.scene-timeline-list` 上输出 `data-ratio="${state.workflowRatio}"`。
- `storyboard.css` 将缩略图框调整为更小的固定横向黑底胶片框（`180×101.25`），不再随 `[data-ratio]` 变成窄竖框；`.add-scene-btn` 与插入槽同步使用同一高度，保证队列布局稳定。
- 缩略图图片统一包在 `.scene-timeline-media-frame` 中，frame 负责黑底与完整展示；内部 `<img>` 显式 `width:100%; height:100%; object-fit:contain !important; background:#000`，竖屏图按高度 100% 显示并左右留黑边，和上方 preview 一致；横屏图也不裁切。`storyboard.html` 对 `storyboard.css` 使用 `?v=__VERSION__`，避免浏览器继续使用旧 CSS。

效果：底部分镜序列统一为较小的横向黑底胶片框（`180x101.25`），竖屏图高度 100% 显示并左右自然留黑边，和上方 preview 的显示方式一致；横屏图也不裁切。切换 `workflowRatio` 时无需刷新即生效（rerender 重写 `data-ratio`）。

## 6. 风险与缓解（已纳入设计）

| 风险 | 缓解措施 |
|------|----------|
| 文生视频被误用导致 400 | 第一版完全不暴露文生视频模型切换 |
| 图生图看起来可用但实际无图输入 | 第一版不暴露图片编辑模型切换；名称如临时展示必须加“（待参考图支持）” |
| 用户以为对话改图已可用 | LLM 选择器必须带明确“功能开发中”文案 |
| 文档与实现脱节 | 实施前先行落盘本设计文档，实现后补充实际结果 |

## 7. 后续演进（v2 计划）

1. 后端支持 `generate_scene_image` 传入 `image_path`（首帧图生图）。
2. 后端支持 `generate_scene_video` 的 TEXT_TO_VIDEO 无图路径。
3. 实现真正的“对话改图” LLM 逻辑（使用选中的对话模型改写 prompt）。
4. 在 UI 增加类型切换控件 + 智能默认（根据是否有首帧自动推荐）。
5. 可选引入 `TaskConfig` 统一模型加载逻辑，与 index 页面对齐。

## 8. 验证清单（已通过浏览器检查 2026-07-02）

- [x] 画风/构图显示位置在 header “第x集 · 16:9” 右侧，紧凑+tooltip，点击打开双输入框弹窗编辑，保存成功并立即在 header 更新显示两个字段。
- [x] 左侧 style-settings-card 和 thumbnail-card 已彻底删除
- [x] 模型配置弹窗 tabs 正常切换；生图模型 tab 显示图片类模型，视频模型 tab 显示视频类模型；对话模型为 optgroup 分组
- [x] 工具栏无遗留小 LLM <select>
- [x] AI 助手模式下拉区分对话改图/图片生成/视频生成，gear 打开对应配置；魔法棒（AI 优化）按钮仅图片/视频模式出现，对话改图不显示。
- [x] LLM 默认逻辑代码存在（优先 deepseek-v4-flash）；实际选中受 config_json 影响（合理）
- [x] 切换/刷新状态通过 config_json + local 恢复
- [x] 生图/视频模型在新建故事板的拆分剧本弹框中，能记住并回显上一次的选择（localStorage 跨故事板兜底，键 `storyboard_lastSelectedImageTaskId` / `storyboard_lastSelectedVideoTaskId`）
- [x] 主预览区竖屏图高度 100%、左右纯黑黑边；横屏/方图行为无回归；网格卡缩略图未受影响（`position:static` 防回归）
- [x] 分镜序列缩略图随 `workflowRatio` 自适应（竖屏变窄高框、横屏维持宽扁框），`data-ratio` 切换比例后立即生效
- [x] 文档已更新
- [ ] 后续：当对话改图真正后端支持后，完善提示与实际调用

浏览器实测 URL: http://localhost:9003/storyboard?world_id=98&episode_number=1&user_id=1 （登录 15088613226）

### 画面/视频提示词的 / 角色下拉提示与可见性修复
- 在「画面提示词」和「视频提示词」区域上方增加轻提示文案：「提示：输入 / 展示角色的下拉框」。
- 角色选择下拉框（输入 / 触发）现在通过 `document.body` + `position:fixed` + `getBoundingClientRect` 挂载（复用 `positionDropdown` 辅助），并在空间不足时自动上翻，避免被 `.info-card` / `.sidebar-content`（固定高度+overflow:auto）裁剪。
- 位置/尺寸计算允许下拉完整显示（min/max-width 适配），与资产场景/道具下拉统一策略。
- 符合 video_workflow 分镜节点 `/` 触发 + 【【角色】】 插入约定。

---

**附注**：本设计基于 2026-07-02 已批准的计划修订版。所有实现必须严格遵守第一版保守范围。
