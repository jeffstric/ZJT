/**
 * 新建分镜默认参考生视频；旧工作流没有 videoMode 时重新加载仍是首帧生视频。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const shotFrameSource = fs.readFileSync(path.join(root, 'web/js/shot_frame_node.js'), 'utf8');
const workflowSource = fs.readFileSync(path.join(root, 'web/js/workflow.js'), 'utf8');

describe('分镜默认视频模式', () => {
  it('新建节点数据默认 multi_reference，按钮高亮参考模式', () => {
    expect(shotFrameSource).toMatch(/videoMode:\s*'multi_reference'/);
    expect(shotFrameSource).toMatch(
      /data-mode="multi_reference"[^>]*class="video-mode-btn is-active"|class="video-mode-btn is-active"[^>]*data-mode="multi_reference"/,
    );
    expect(shotFrameSource).toMatch(/video\.reference_to_video/);
  });

  it('重新加载时缺 videoMode 仍回退 first_last_frame', () => {
    const start = workflowSource.indexOf('function createShotFrameNodeWithData');
    const restore = workflowSource.slice(start, start + 8000);
    expect(restore).toMatch(/nodeData\.data\.videoMode\s*\|\|\s*'first_last_frame'/);
    expect(restore).toMatch(/node\.data\.videoMode\s*=\s*restoredVideoMode/);
  });
});
