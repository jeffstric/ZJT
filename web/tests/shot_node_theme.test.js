/**
 * 分镜 / 分镜组节点暗色主题：列背景与模式按钮必须走 CSS token，
 * 禁止内联浅色底（#fcfcfc / #f9fafb / #f3f4f6）以及 JS 写 style.background。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

const shotFrameJs = readSource('web/js/shot_frame_node.js');
const shotGroupJs = readSource('web/js/shot_group_node.js');
const workflowJs = readSource('web/js/workflow.js');
const css = readSource('web/css/video_workflow.css');
const catalogCss = readSource('web/css/model_catalog.css');

describe('分镜节点暗色主题接线', () => {
  it('分镜/分镜组 script-section 不再内联浅色背景', () => {
    expect(shotFrameJs).not.toContain('background: #fcfcfc');
    expect(shotFrameJs).not.toContain('background: #f9fafb');
    expect(shotGroupJs).not.toContain('background: #f9fafb');
    expect(shotGroupJs).not.toContain('background: #f8f9fa');
  });

  it('视频模式按钮用 is-active class，不写死浅色 style.background', () => {
    expect(shotFrameJs).toContain('video-mode-btn is-active');
    expect(shotFrameJs).toContain('classList.toggle(\'is-active\'');
    expect(shotFrameJs).not.toContain("style.background = isActive ? '#3b82f6'");
    expect(workflowJs).toContain('_syncVideoModeButtons');
    expect(workflowJs).not.toContain("style.background = isActive ? '#3b82f6'");
  });

  it('CSS 用主题变量覆盖分区、场景框、模式切换', () => {
    expect(css).toContain('.script-section:nth-child(2)');
    expect(css).toContain('html.theme-dark .node .script-section');
    expect(css).toContain('.shot-frame-video-mode-toggle .video-mode-btn.is-active');
    expect(css).toContain('.shot-group-shot-item');
    expect(css).toContain('.shot-ref-section');
    expect(css).toContain('background: var(--surface-2)');
    expect(catalogCss).toContain('background: var(--surface');
  });
});
