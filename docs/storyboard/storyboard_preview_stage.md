# 故事板主预览：固定画幅 Stage + 预览分辨率

> **状态**：已实现（2026-07-22）  
> **范围**：`web/storyboard.html` 主预览与时间轴缩略图展示层；不改生图/生视频真实输出分辨率。

## 1. 问题

- 不同分镜生成图分辨率不一致（如 1K / 2K）时，主预览「画面」视觉宽高不一致。
- 主预览区域随中栏 `flex:1` 铺满，没有按 `workflow_ratio` 锁定监视器框。
- 需要可调的**逻辑分辨率**（默认 720p），超大媒体按最长边约束缩小，小图不强行放大。

## 2. 设计结论

| 维度 | 字段 | 说明 |
|------|------|------|
| 画幅比例 | `state.workflowRatio` / 库 `workflow_ratio` | 16:9 / 9:16 / … |
| 预览分辨率 | `state.previewResolution` | `480p` / `720p`（默认）/ `1080p`，与生成用 `videoResolution` **独立** |
| 逻辑画布 | `resolveLogicalCanvas(ratio, res)` | 短边 = N（720p→720），长边按比例取整 |
| 媒体适配 | CSS `object-fit: scale-down` | **只缩不放**（方案 A） |
| 屏幕投影 | `applyPreviewCanvas` | stage CSS 尺寸 = 逻辑画布 × min(1, panel/logical) |

### 逻辑画布示例

| 档位 | 16:9 | 9:16 |
|------|------|------|
| 720p（默认） | 1280×720 | **720×1280** |
| 1080p | 1920×1080 | 1080×1920 |
| 480p | 854×480 | 480×854 |

## 3. DOM 结构

```html
<section class="preview-wrapper" data-ratio="9:16" data-preview-resolution="720p"
         style="--logical-w:720;--logical-h:1280;--preview-ar:720 / 1280;">
  <div class="preview-stage"><!-- 固定比例监视器，JS 写入宽高 -->
    <!-- media / empty / buffering / subtitle -->
  </div>
  <div class="preview-caption">…</div>
</section>
```

- **外框**（stage）尺寸只跟 ratio + previewResolution + 中栏可用区有关，与单张图像素无关。
- 字幕在 stage 内；标题 caption 在 wrapper 上，避免压画面逻辑。

## 4. 时间轴（方案 B）

- `.scene-timeline-list` 使用 CSS 变量 `--timeline-thumb-width/height`。
- `applyTimelineRatioVars(list, ratio)`：
  - 横屏：固定高 96px，宽按比例；
  - 竖屏：固定宽 72px，高按比例（避免细条）；
  - 1:1：96×96。
- 缩略图媒体：`object-fit: scale-down`，与主预览一致。

## 5. UI 入口

Header 比例下拉旁新增 **预览分辨率** 下拉：

- `data-preview-resolution-select`
- 选项文案带当前逻辑尺寸，如 `720p · 720×1280`
- 变更后写入 `config_json.previewResolution`（`serializeUiConfig` / `restoreUiConfig`）

改 **画面比例** 时：`rerender([HEADER, CENTER], { forcePreview: true })`，主预览 + 时间轴同步。

## 6. 关键文件

| 文件 | 职责 |
|------|------|
| `web/js/storyboard/preview_canvas.js` | 逻辑画布、fit、stage、ResizeObserver、时间轴变量 |
| `web/js/storyboard/state.js` | `previewResolution` 默认与持久化 |
| `web/js/storyboard/render.js` | stage DOM、header 选择器、patchPreview 挂 stage |
| `web/js/storyboard/playback.js` | 播放媒体挂入 stage |
| `web/js/storyboard/events.js` | 比例 / 预览分辨率 change |
| `web/css/storyboard.css` | stage 布局、scale-down、时间轴变量尺寸 |

## 7. 验收

1. 默认 9:16 逻辑画布为 720×1280；16:9 为 1280×720。
2. 同一窗口下切换 1K/2K 分镜，**stage 外框像素不变**。
3. 媒体大于逻辑画布：等比缩小装入；小于：居中不放大。
4. 切换预览 720p↔1080p：外框与 header 尺寸文案更新，并写入 config_json。
5. 切换 workflow_ratio：主预览与时间轴拇指比例一致。
6. 播放 / 涂色 / 局部 patch 不拆掉 stage 外壳。
