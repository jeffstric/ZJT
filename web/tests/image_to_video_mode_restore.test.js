/**
 * 生视频节点「文生视频」模式刷新恢复回归测试。
 *
 * 背景 BUG：workflow.js createImageToVideoNodeWithData 恢复逻辑手写复制了一份
 * 模式显隐实现，其中选择器写错（.first-last-fields 在节点 DOM 中不存在，
 * 实际是 .first-last-frame-tabs-container），且与节点内行为漂移
 * （video 字段在节点内全模式可见，复制品却在非 multi_reference 模式隐藏），
 * 导致文生视频模式刷新后首尾帧上传区错误显示、参考视频字段错误隐藏。
 *
 * 修复：image_to_video_node.js 把闭包内的 updateImageModeUI 暴露为 el._updateImageModeUI，
 * 恢复逻辑删除手写副本、直接复用同一份实现；算力显示同理复用 el._updateComputingPowerDisplay。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

const nodeJs = readSource('web/js/image_to_video_node.js');
const workflowJs = readSource('web/js/workflow.js');

// createImageToVideoNodeWithData 恢复函数源码片段
function restoreSegment() {
  const start = workflowJs.indexOf('function createImageToVideoNodeWithData');
  expect(start).toBeGreaterThan(-1);
  const end = workflowJs.indexOf('function createVideoNodeWithData', start);
  return workflowJs.slice(start, end > start ? end : start + 8000);
}

describe('生视频节点生成模式刷新恢复', () => {
  it('updateImageModeUI 暴露到节点元素，供恢复逻辑复用', () => {
    expect(nodeJs).toContain('el._updateImageModeUI = updateImageModeUI');
  });

  it('恢复逻辑不再引用错误选择器 .first-last-fields（仅允许注释提及）', () => {
    const segment = restoreSegment();
    // 代码层面的引用必须为 0（querySelector/querySelectorAll 均不允许）
    expect(segment.includes("querySelectorAll('.first-last-fields')")).toBe(false);
    expect(segment.includes("querySelector('.first-last-fields')")).toBe(false);
  });

  it('恢复逻辑调用 el._updateImageModeUI 复用节点内显隐实现', () => {
    const segment = restoreSegment();
    expect(segment).toContain('el._updateImageModeUI()');
    // 不再手写 audio/video 字段显隐（与节点内实现漂移的根源）
    expect(segment.includes(".audio-field'")).toBe(false);
    expect(segment.includes(".video-field'")).toBe(false);
  });

  it('恢复后的算力显示复用节点内实时计算（感知模式/分辨率上下文）', () => {
    const segment = restoreSegment();
    expect(segment).toContain('el._updateComputingPowerDisplay()');
    expect(segment.includes('calculateVideoGenerationPower')).toBe(false);
  });

  it('文生视频仍是生成模式的第三个选项，文案与 i18n 完整', () => {
    expect(nodeJs).toContain('value="text_to_video" data-i18n="image_mode_text_to_video"');
    const zh = JSON.parse(readSource('web/i18n/locales/zh-CN/video_workflow.json'));
    const en = JSON.parse(readSource('web/i18n/locales/en/video_workflow.json'));
    expect(zh.image_mode_label).toBe('生成模式');
    expect(en.image_mode_label).toBe('Generation Mode');
    expect(zh.image_mode_text_to_video).toBe('文生视频');
  });
});
