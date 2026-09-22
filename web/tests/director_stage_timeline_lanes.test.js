/**
 * 导演台时间轴 lane 同步回归测试（源码断言）。
 *
 * 背景 BUG：多轨道时间轴改造后，新建/删除人偶只刷新了人偶列表面板，
 * 没有调用 renderTimeline()，导致时间轴上对应的轨道 lane 不增/不减，
 * 要等其他操作触发重绘才出现（用户反馈：新建人物后时间轴没自动加轨道）。
 *
 * 约定：addPuppet（非 skipRefresh 分支）与 removePuppet 的刷新流程必须
 * 调用 renderTimeline() 重建时间轴轨道。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');

/** 提取 `DirectorEditor.prototype.<name> = function` 到下一个原型方法之间的源码 */
function prototypeBlock(name) {
  const marker = `DirectorEditor.prototype.${name} = function`;
  const idx = src.indexOf(marker);
  expect(idx).toBeGreaterThan(-1);
  const rest = src.slice(idx + marker.length);
  const next = rest.search(/DirectorEditor\.prototype\.[a-zA-Z]+\s*=/);
  return next > -1 ? rest.slice(0, next) : rest;
}

describe('导演台：增删人偶同步时间轴轨道（源码断言）', () => {
  it('addPuppet 刷新流程调用 renderTimeline', () => {
    const block = prototypeBlock('addPuppet');
    expect(block).toContain('renderTimeline');
  });

  it('removePuppet 刷新流程调用 renderTimeline', () => {
    const block = prototypeBlock('removePuppet');
    expect(block).toContain('renderTimeline');
  });
});
