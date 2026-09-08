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

## 5. 字幕版式与导出成片对齐（所见即所得）

预览字幕（`.preview-subtitle`）逐项复刻导出 ASS 硬烧字幕（`services/storyboard_subtitle.py`），避免「预览与播放器对不上」：

| 维度 | 预览 | 导出（ASS） |
|------|------|------|
| 左右边距 | `--sb-side-margin`（默认 7%，设置面板 0~18% 可调） | `MarginL/R = width × ratio` |
| 底部边距 | `--sb-bottom` = `max(12, H×8%) × (stage 显示高/H)` | `MarginV = max(12, height×8%)` |
| 字号 | `--sb-font-size` = `clamp(H/28,28,56) × (stage 显示高/H)` | `clamp(height/28, 28, 56)` |
| 字体 | `@font-face` 加载 `/files/fonts/NotoSansSC-Regular.otf`（同一内置字体文件） | libass 直接读该文件 |
| 样式 | 无背景盒；`-webkit-text-stroke` + `paint-order:stroke fill` 模拟描边（`--sb-stroke` = Outline×2 折算），`text-shadow` 模拟投影（`--sb-shadow`） | BorderStyle=1（描边+投影，无盒）、Outline=2、Shadow=1、白字黑边 |
| 折行 | `subtitle_wrap.js` 逐行移植后端折行算法（标点优先 + 字数硬切，每行最大字符数 = `width×0.86/字号`，单行省略规则一致） | `wrap_subtitle_lines` |
| 分页 | 播放时每条对白按音频时长做页时长分配并随进度翻页（`createSubtitlePager`）；block 整段 ≤3 行/页，smart 逐句 ≤2 行/页（标点切句 + 贪心合并，移植 `split_long_seg_by_inner_punct`） | `paginate_lines` + `fit_pages_to_duration` + `allocate_page_durations` / smart 逐句 cue |

- H 取导出视频分辨率：固定长边 1920，仅由 `workflow_ratio` 决定（与后端 `_ratio_size` 一致，与 `videoResolution`/`previewResolution` 无关）。
- 由 `applyPreviewCanvas` → `applySubtitleLayoutVars` 在每次 stage 重算（含 ResizeObserver）时刷新，窗口缩放不改变字幕相对画面的位置/大小。
- 已知差异：导出 smart 模式的句界/切换时机来自导出时 ASR（SenseVoice）句级时间轴；预览侧无此数据，用标点切句近似句界、按去标点字符占比分配各页时长——行数、断行位置、内容分组与烧录一致，翻页时机为近似值。

## 6. UI 入口

Header 比例下拉旁新增 **预览分辨率** 下拉：

- `data-preview-resolution-select`
- 选项文案带当前逻辑尺寸，如 `720p · 720×1280`
- 变更后写入 `config_json.previewResolution`（`serializeUiConfig` / `restoreUiConfig`）

改 **画面比例** 时：`rerender([HEADER, CENTER], { forcePreview: true })`，主预览 + 时间轴同步。

## 7. 关键文件

| 文件 | 职责 |
|------|------|
| `web/js/storyboard/preview_canvas.js` | 逻辑画布、fit、stage、ResizeObserver、时间轴变量 |
| `web/js/storyboard/state.js` | `previewResolution` 默认与持久化 |
| `web/js/storyboard/render.js` | stage DOM、header 选择器、patchPreview 挂 stage |
| `web/js/storyboard/playback.js` | 播放媒体挂入 stage |
| `web/js/storyboard/events.js` | 比例 / 预览分辨率 change |
| `web/css/storyboard.css` | stage 布局、scale-down、时间轴变量尺寸 |

## 8. 验收

1. 默认 9:16 逻辑画布为 720×1280；16:9 为 1280×720。
2. 同一窗口下切换 1K/2K 分镜，**stage 外框像素不变**。
3. 媒体大于逻辑画布：等比缩小装入；小于：居中不放大。
4. 切换预览 720p↔1080p：外框与 header 尺寸文案更新，并写入 config_json。
5. 切换 workflow_ratio：主预览与时间轴拇指比例一致。
6. 播放 / 涂色 / 局部 patch 不拆掉 stage 外壳。
