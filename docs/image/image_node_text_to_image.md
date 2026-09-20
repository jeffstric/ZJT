# 图片节点文生图

## 背景

视频工作流画布的图片节点原先只支持「图生图」：必须先上传底图，「编辑图片」按钮才可用，
无图时点击会提示「请先上传或生成图片」。纯文字出图的场景（先写提示词、直接生成图片）
无法在图片节点内完成，只能借助全景/宫格等间接入口。

## 功能

图片节点现在按「是否有底图」自动切换两种模式：

| 状态 | 按钮文案 | 提示词标签 | 提交链路 |
|------|----------|------------|----------|
| 无底图 | 生成图片 | 提示词 | 文生图 |
| 有底图（已上传/生成） | 编辑图片 | 编辑提示词（可选） | 图生图（原逻辑不变） |

- **无参考图**：`POST /api/text-to-image`（Form：`prompt` / `task_id` / `aspect_ratio` /
  `count` / `image_size`），`task_id` 由 `TaskConfig.getTaskIdByKey(model, 'text_to_image')`
  解析，与宫格生图同源。
- **有参考图（角色/场景/道具连线）**：`POST /api/image-edit` 的 `ref_image_urls`
  无底图路径（与宫格生图一致，编辑接口允许仅参考图），提示词自动追加「图N是某某」后缀。
- 比例沿用节点上的 `ratio` 下拉（文生图作为 `aspect_ratio` 提交）；分辨率档位
  `image_size`、抽卡次数 `drawCount` 对两种模式同样生效。
- 生成结果节点（`生成结果`/`生成结果N`）、任务轮询（`pollVideoStatus` →
  `GET /api/get-status/{id}`）、AiToolTimeline 状态时间轴与图生图共用同一链路。

## 关键改动

- `web/js/workflow.js`：新增 `generateImageFromText(prompt, ratio, model, count, imageSize,
  referenceImageUrls)`，与 `generateEditedImage` 并列；内部按有无参考图选择接口。
- `web/js/image_node.js`：
  - 新增 `updateGenerateModeUI()`：按 `data.url` 切换按钮文案、提示词标签/占位
    （同步切换 `data-i18n` 键，语言重扫不串文案）；上传成功/失败恢复、清除图片、
    工作流重载恢复时都会调用。
  - 「编辑图片」点击逻辑：上传中仍禁止；无底图跳过 `canEditImageNode` 门禁，
    直接走文生图提交；有底图走原 `generateEditedImage`。
- `web/js/workflow.js` `createImageNodeWithData`：恢复后调用
  `el._updateImageGenerateMode()` 复原文案模式。

## 兼容性

- 存量工作流无新字段，重载后按 `data.url` 自动落到正确模式，无迁移。
- 后端零改动（两个接口均为已有异步接口，非阻塞）。

## 人工测试要点

1. 新建图片节点不上传图，输入提示词 → 按钮显示「生成图片」，点击后生成结果节点并轮询回填。
2. 上传底图后按钮切换为「编辑图片」，行为与旧版一致。
3. 无底图但连接角色参考图 → 走 image-edit 参考图路径，提示词带「图2是某某角色」后缀。
4. 清除图片后按钮回到「生成图片」。
5. 保存刷新工作流，节点文案模式随底图状态正确复原。
