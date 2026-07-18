# Storyboard Timeline UI

`web/storyboard.html` 的分镜时间轴由 `web/js/storyboard/render.js` 渲染，样式位于
`web/css/storyboard.css`。

时间轴顶部的播放预览（类剪影试看、图/视频/配音编排）见
[storyboard_timeline_playback.md](./storyboard_timeline_playback.md)。

分镜序列 `.scene-timeline-list` 内含 `.scene-timeline-playhead` 竖线，随预览播放进度在卡片上滑动，并在靠近视口边缘时带动列表横向滚动。

## 分镜卡片（时间轴）

- 时间轴分镜使用固定横向卡片尺寸，通过 CSS 变量
  `--timeline-thumb-width` 和 `--timeline-thumb-height` 控制。
- 分镜首帧图片使用 `object-fit: contain`，竖屏图片会在横向卡片中完整显示高度，
  两侧保留暗色背景，不再按工作流比例裁切成窄条。
- 缩略图左上角显示真实数据库 ID，格式为 `分镜{scene.id}`；首帧状态角标同时出现时，
  分镜 ID 自动下移，避免两个角标相互遮挡。初次渲染和单分镜局部刷新共用
  `renderTimelineThumbInner(scene)`，因此轮询刷新不会移除编号。
- 分镜时长显示在卡片左下角，带播放图标；复制和删除按钮作为合法的兄弟按钮保留在
  `.scene-timeline-actions` 中，并通过绝对定位覆盖到卡片右下角。

## Grid 总览卡片

`viewMode === 'grid'` 时由 `renderStoryboardCardCell` 渲染（`renderGridInner` /
局部刷新 `renderStoryboardCardOuter` 共用）：

| 区域 | 内容 |
|------|------|
| 缩略图左上 | 分镜类型：视频 / 对口型 / 图片（`scene.videoType`） |
| 缩略图右上 | 时长 `durationLabel` |
| 缩略图左下 | 幕号（有 `groupId` 时） |
| 标题行 | 标题 + 难度 badge |
| 状态行 | 图/视频状态 + 配音进度「配 a/b」（有对白时） |
| 场景行 | 场景头像 + 名；未绑定显示「未选场景」 |
| 角色行 | ≤3 头像叠 + 名称/ +N；无角色显示「无角色」 |
| 景别 | `promptJson.perspective`，空不占位 |
| 底部 | 编辑 / 复制 / 删除 |

Grid 缩略图虽然复用 `.preview-media`，但会在 `.storyboard-thumb` 内强制保持
`opacity: 1` 并关闭过渡，避免继承主预览区等待 `.loaded` 状态的淡入样式，确保首次渲染和局部刷新后图片均可见。

角色解析顺序：对话 `characterId` → `referenceSelections.characters` → 提示词 `【【名】】`。
场景头像与左侧栏一致，从 `state.locations` 补全。

## 分镜编辑弹框（grid 视图）

Grid 卡片底部「编辑」按钮（`data-action="edit-scene"`）打开统一的 `Region.MODAL` 弹框
（`renderSceneEditDialog`），用于编辑当前 UI 缺失表单入口的 4 个字段：

| 字段 | 控件 | 后端字段 |
|------|------|----------|
| 标题 | `<input>` | `title` |
| 时长（秒） | `<input type="number" step="0.001">` | `duration` |
| 难度 | `<select>` 易/中/难 | `difficulty` |
| 所属幕 | `<input>`（可空） | `act_name` |

- 保存（`data-action="save-scene-edit"`）走 `api.updateScene` → `PUT /api/storyboard/scene/{id}`，
  后端按 `ALLOWED_SCENE_UPDATE_FIELDS` 过滤，只更新这 4 个字段。
- 时长填非数字/负数时弹框内显示 `sceneEditError`，不请求后端、不关闭。
- 保存中按钮显示「保存中…」并 `disabled`，防止重复提交；`sceneEditSaving` 守卫。
- 保存成功后写回本地 `scene.*`，关闭弹框，刷新 `Region.CENTER`（grid 卡片网格）。
- 点遮罩 / 取消 / 关闭按钮均关闭弹框（遮罩兜底在 events.js 全局点击里）。
- 画面提示词、视频提示词、场景、声音同出、对话等**不进弹框**，保持左栏 inline 编辑。

state 字段：`showSceneEditDialog` / `sceneEditTargetId` / `sceneEditSaving` / `sceneEditError`。

## 插入分镜

- 分镜之间的添加入口仍由 `renderInsertSceneSlot(..., 'timeline'|'grid')` 生成。
- 时间轴模式下按钮类名为 `.scene-timeline-insert-slot`，事件仍使用
  `data-action="insert-scene"`、`data-prev-id` 和 `data-next-id`。
- 插入按钮样式为细竖线加圆形加号，降低横向浏览时的占位，但保留原有点击语义。
