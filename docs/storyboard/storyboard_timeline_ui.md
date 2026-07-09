# Storyboard Timeline UI

`web/storyboard.html` 的分镜时间轴由 `web/js/storyboard/render.js` 渲染，样式位于
`web/css/storyboard.css`。

## 分镜卡片

- 时间轴分镜使用固定横向卡片尺寸，通过 CSS 变量
  `--timeline-thumb-width` 和 `--timeline-thumb-height` 控制。
- 分镜首帧图片使用 `object-fit: contain`，竖屏图片会在横向卡片中完整显示高度，
  两侧保留暗色背景，不再按工作流比例裁切成窄条。
- 分镜时长显示在卡片左下角，带播放图标；复制和删除按钮作为合法的兄弟按钮保留在
  `.scene-timeline-actions` 中，并通过绝对定位覆盖到卡片右下角。

## 插入分镜

- 分镜之间的添加入口仍由 `renderInsertSceneSlot(..., 'timeline')` 生成。
- 时间轴模式下按钮类名为 `.scene-timeline-insert-slot`，事件仍使用
  `data-action="insert-scene"`、`data-prev-id` 和 `data-next-id`。
- 插入按钮样式为细竖线加圆形加号，降低横向浏览时的占位，但保留原有点击语义。
