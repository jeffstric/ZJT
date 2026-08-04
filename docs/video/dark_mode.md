# 视频工作流暗色模式

## 概述

`video_workflow.html` 支持 **浅色 / 暗色** 双主题切换。默认仍为浅色（与历史行为一致）；用户可一键切换到暗色，降低暗环境中的眩光。

## 使用方式

1. 打开视频工作流页面。
2. 点击右上角工具条（`.ratio-floating`）中的主题按钮：
   - 浅色模式下显示月亮图标 → 点击切换到暗色。
   - 暗色模式下显示太阳图标 → 点击切换回浅色。
3. 偏好保存在浏览器 `localStorage`，刷新后保持。

## 技术说明

| 项 | 说明 |
|----|------|
| 存储 key | `localStorage.video_workflow_theme` |
| 取值 | `light`（默认）/ `dark` |
| DOM 标记 | `html.theme-dark`（仅暗色时存在） |
| 脚本 | `web/js/theme.js`（`window.WorkflowTheme`） |
| 防 FOUC | `video_workflow.html` 的 `<head>` 内联脚本在首屏前应用 class |
| 样式 | `web/css/video_workflow.css` 中 token + 暗色覆盖层 |

### API

```js
WorkflowTheme.get();           // 'light' | 'dark'
WorkflowTheme.set('dark');     // 应用并持久化
WorkflowTheme.toggle();        // 切换
WorkflowTheme.initToggle({ target: '.ratio-floating' });
```

### 设计原则

- **浅色默认**：无存储或值为 `light` 时不添加 `theme-dark`，视觉与改造前一致。
- **Token 优先**：核心面（画布、节点、浮层、时间轴、表单）使用 CSS 变量。
- **覆盖兜底**：HTML 内联白底弹窗、节点内 `background: white` 表单、部分硬编码通过 `html.theme-dark` 选择器覆盖（`!important` 仅用于压过 inline）。
- **节点表单可读性**：暗色下 select/input/textarea、剧本参数折叠组、次级白底按钮强制深色面 + 浅色字，避免白底白字。
- **资产选择列表 hover**：角色/场景/道具/剧本列表项 hover 使用 CSS token（`--primary-light` + `--primary`），禁止 JS 写死浅色 `#f8fafc` / `#f3f4f6` / `white`。
- **媒体不反色**：图片、视频、二维码等保持原样。

## 相关文件

- `web/js/theme.js`
- `web/css/video_workflow.css`
- `web/css/image_coloring_editor.css`（暗色下涂色弹窗）
- `web/video_workflow.html`
- i18n：`theme_toggle_to_dark` / `theme_toggle_to_light`
