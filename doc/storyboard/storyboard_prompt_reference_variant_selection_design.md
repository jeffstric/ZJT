# Storyboard 提示词参考图变体选择设计

## 1. 背景与目标

`web/storyboard.html` 的图片提示词和视频提示词目前会将角色渲染为可识别标签，但生成时默认使用角色、场景的主参考图，用户无法指定角色服装或场景角度。

本方案参考 `web/video_workflow.html` 分镜节点已有交互，在 Storyboard 中增加：

- 点击提示词中的角色标签，选择该角色的主参考图或不同服装参考图。
- 点击场景标签，选择当前场景的主参考图或不同角度参考图。
- “切换场景”作为弹层右侧的独立按钮，不与场景角度列表混排。
- 同一分镜内只保存一套选择，图片提示词、视频提示词、普通生成和效果模式宫格生成共同使用。
- 刷新页面、重新进入 Storyboard 或重新生成后，选择仍然有效。

本次不扩展道具变体选择；道具继续沿用现有参考图解析逻辑。

## 2. 现状

### 2.1 Video Workflow

`web/js/shot_frame_node.js` 已支持角色服装和场景角度选择：

- 角色主图来自 `reference_image`，服装变体来自 `reference_images`。
- 场景主图来自 `reference_image`，角度变体来自 `reference_images`。
- 节点分别保存选中的 URL 和标签。
- `shot_frame_generator.js` 与 `shot_frame_video_generator.js` 优先使用选中参考图。

该实现可作为交互参考，但 Storyboard 不应直接复制节点私有状态和生成逻辑。

### 2.2 Storyboard

- `web/js/storyboard/render.js` 将 `【【角色】】` 渲染为 `.role-chip`。
- 场景显示在提示词上方的场景资源标签中，而非提示词正文中。
- `web/js/storyboard/events.js` 点击 `.prompt-display` 会进入整段文本编辑，因此角色点击事件需要先于该逻辑处理。
- 角色、场景接口数据已经包含 `reference_image` 和 `reference_images`。
- 分镜的 `prompt_json` 会随分镜更新保存，适合承载分镜级参考图选择，无需新增数据库字段。
- 普通图片/视频生成和效果模式宫格生成存在不同的参考图收集入口，需要统一读取选择结果。

## 3. 方案比较

### 方案 A：仅保存在前端内存

开发量较小，但刷新后丢失，后台任务和效果模式无法可靠使用，排除。

### 方案 B：图片提示词和视频提示词分别保存

灵活度较高，但容易出现首帧服装与视频服装不一致，操作和状态也更复杂，排除。

### 方案 C：分镜级共享选择（采用）

将选择保存到分镜已有的 `prompt_json`。图片、视频以及宫格任务均通过统一服务解析，兼顾一致性、持久化和向后兼容。

## 4. 数据结构

在 `storyboard_scene.prompt_json` 中新增可选字段：

```json
{
  "reference_selections": {
    "schema_version": 1,
    "characters": {
      "4": {
        "character_id": 4,
        "name": "奶昔_Milkshake",
        "url": "/upload/character/milkshake_business.png",
        "label": "商务服装",
        "source": "reference_images"
      }
    },
    "location": {
      "location_id": 708,
      "name": "糖浆陷阱区域",
      "url": "/upload/location/syrup_right.png",
      "label": "右侧视角",
      "angle": "right",
      "source": "reference_images"
    }
  }
}
```

约束：

- 角色优先使用数据库 ID 作为 key，避免同名角色冲突。
- 无数据库 ID 的兼容数据可暂用 `name:<normalized_name>`，资产完成映射后转为 ID。
- 选择主参考图时也保存显式记录，`source` 为 `reference_image`。
- URL 是选择结果，不是可信输入。后端必须确认它仍属于对应资产的 `reference_image` 或 `reference_images`。
- 不修改既有 `prompt_json` 其他字段，更新时执行深合并。
- 旧分镜没有该字段时完全沿用现有默认参考图行为。

## 5. 前端交互

### 5.1 角色服装

点击图片或视频提示词中的角色标签：

1. 阻止 `.prompt-display` 的通用文本编辑事件。
2. 在角色标签下方打开浮层。
3. 首项显示主参考图，标记为“默认”。
4. 后续显示 `reference_images` 中的服装缩略图和标签。
5. 当前选择显示勾选状态。
6. 选择后立即更新该分镜状态并保存。
7. 图片提示词和视频提示词中的同名角色标签同步刷新选择状态。

没有服装变体时，浮层仍可展示主图，并以不可操作状态提示“暂无其他服装”。

### 5.2 场景角度

点击提示词上方的场景标签后打开场景浮层：

- 浮层主体显示当前场景的主参考图和多角度参考图。
- 主图标记为“默认”，其他项显示 `label`，缺失时使用 `angle`。
- 当前角度显示勾选状态。
- 浮层右侧提供独立的“切换场景”按钮。
- 点击“切换场景”进入现有场景选择流程；切换成功后清除旧场景角度选择，并默认使用新场景主图。

场景切换按钮位于标题行右侧，不放在角度列表下方，避免被误解为一个角度选项。

### 5.3 浮层通用行为

- 建议新增独立模块 `web/js/storyboard/reference_variant_selector.js`，不要继续扩大 `events.js`。
- 浮层挂载到 `document.body`，使用锚点定位并处理视口边缘碰撞。
- 点击外部或按 `Escape` 关闭，同一时间只允许一个浮层。
- 支持键盘焦点、方向键浏览、Enter 选择，并提供可读的 `aria-label`。
- 缩略图加载失败时显示资产类型占位图，不改变列表尺寸。
- 保存期间锁定重复选择；保存失败时回滚并显示错误提示。

## 6. 前端状态与保存

### 6.1 状态归一化

在 Storyboard scene adapter 中解析 `prompt_json.reference_selections`，归一化为分镜状态。渲染层只消费归一化数据，不直接读取 `scene.raw`。

### 6.2 保存入口

新增分镜级更新方法，例如：

- `selectCharacterReference(sceneId, characterId, selection)`
- `selectLocationReference(sceneId, locationId, selection)`
- `clearStaleReferenceSelection(sceneId, assetType, assetId)`

这些方法最终调用现有分镜更新接口，更新完整 `prompt_json`。保存时必须保留空间布局、提示词和其他未知扩展字段。

### 6.3 失效选择

当服装图、角度图被删除或角色/场景被替换时：

- 前端归一化阶段将失效选择展示为默认主图。
- 下一次保存时清理失效项。
- 后端生成阶段再次校验，不能因为过期 URL 阻塞生成。

## 7. 后端生成链路

### 7.1 统一解析服务

扩展 `services/storyboard_reference_prompt_service.py`，提供统一的安全解析能力：

1. 从 `prompt_json.reference_selections` 读取分镜选择。
2. 按角色 ID、场景 ID 匹配当前数据库资产。
3. 校验选中 URL 是否属于该资产。
4. 校验成功时返回选中 URL 和标签。
5. 选择不存在或失效时回退主参考图。

普通图片生成、视频生成和其他 Storyboard 参考图收集逻辑均调用该服务，禁止各自复制选择规则。

### 7.2 效果模式宫格

`services/storyboard_first_frame_grid_service.py` 构建每格参考图 manifest 时也必须调用统一解析服务：

- 每个分镜使用自己的角色服装和场景角度选择。
- 全局参考图编号仍由服务层根据最终 URL 去重并分配。
- LLM 只能使用服务层给出的参考图编号，不允许覆盖或自行推测选择。
- 提示词图例应带上服装或角度标签，例如“图1是角色奶昔，商务服装”。

这样可避免 Storyboard UI 显示已选择新服装，但效果模式仍把默认图传给宫格模型。

### 7.3 视频生成

视频生成使用与图片生成相同的分镜级选择。即使视频提示词正文未包含场景名称，只要分镜绑定了场景，也应使用选定角度参考图。

## 8. 一致性规则

- 同一分镜的图片提示词和视频提示词共用选择。
- 不跨分镜自动继承服装或场景角度，避免无意污染后续镜头。
- 若后续需要连续选择，可另行增加“应用到后续分镜”，不纳入本次范围。
- 修改提示词文本不会清除选择。
- 删除角色标记后可保留选择记录，但生成时只收集当前提示词或空间布局实际关联的角色；后续保存可清理孤立记录。
- 切换场景必须清除原场景角度，不能按 URL 或角度名称迁移。

## 9. 代码改动范围

前端预计涉及：

- `web/storyboard.html`：引入新的 JS/CSS 文件。
- `web/js/storyboard/render.js`：为角色和场景标签提供稳定的数据属性及选中状态。
- `web/js/storyboard/events.js`：在通用提示词编辑前分流角色和场景点击。
- `web/js/storyboard/adapters.js`：解析和序列化 `reference_selections`。
- `web/js/storyboard/state.js`：维护分镜级共享选择状态。
- `web/js/storyboard/reference_variant_selector.js`：新增浮层和选择控制器。
- Storyboard 独立样式文件：增加浮层、缩略图、选中态和响应式样式。

后端预计涉及：

- `services/storyboard_reference_prompt_service.py`：增加选择校验和统一解析。
- `services/storyboard_agent_cli_service.py`：普通图片、视频链路接入解析结果。
- `services/storyboard_first_frame_grid_service.py`：宫格 manifest 使用分镜选择。

预计无需数据库迁移，也无需修改 `storyboard_scene` 表结构。

## 10. 接口与并发要求

- 优先复用现有异步分镜更新接口，不新增同步 Web 调用。
- 若需要新增接口，路由和内部数据库调用必须保持非阻塞，不得在异步函数中使用 `requests` 等同步网络调用。
- 更新请求携带当前分镜完整 `prompt_json` 时需防止覆盖其他并发修改；条件允许时增加版本号或只提交 reference selection patch。
- 用户快速连续切换时，应取消/合并尚未发出的前端请求，最终状态以最后一次选择为准。

## 11. 测试方案

### 11.1 前端单元测试

- 角色主图和多服装列表正确生成。
- 场景主图和多角度列表正确生成。
- 点击角色不会触发整段提示词编辑。
- 图片和视频区域同步显示同一选择。
- 切换场景后清除旧角度。
- 保存失败能够回滚。
- 浮层可通过外部点击和 Escape 关闭。

### 11.2 后端单元测试

- 合法角色服装 URL 被采用。
- 合法场景角度 URL 被采用。
- 跨角色、跨场景伪造 URL 被拒绝并回退主图。
- 已删除变体、空数组和旧版 prompt 均能回退。
- 普通图片、视频、效果模式宫格得到一致的选择结果。
- 宫格参考图去重和编号在使用变体后仍正确。

### 11.3 端到端验证

1. 在图片提示词中为角色选择第二套服装。
2. 验证视频提示词区域同步显示该选择。
3. 选择场景的另一个角度。
4. 刷新页面，确认两项选择保留。
5. 分别触发普通首帧、视频和效果模式宫格生成。
6. 检查提交任务的参考图列表和提示词图例均使用选中变体。
7. 删除对应变体后再次生成，确认安全回退主图。

## 12. 验收标准

- 用户能够从角色标签选择主图或服装参考图。
- 用户能够从场景标签选择主图或角度参考图。
- “切换场景”按钮位于场景浮层右侧，并继续完成原有场景切换功能。
- 同一分镜内图片和视频共用选择，刷新后不丢失。
- 普通图片、视频和效果模式宫格任务实际上传选中参考图。
- 旧分镜和无变体资产保持现有行为。
- 不新增数据库字段，不引入阻塞式 Web 调用。

