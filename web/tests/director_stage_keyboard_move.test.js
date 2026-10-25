/**
 * 导演台方向键平移回归测试。
 *
 * 契约：选中角色后方向键按当前观察方向平移人偶，Shift 加速；
 * 输入框/下拉框聚焦时不响应；播放中会先暂停；每次移动支持撤销/自动保存。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');
const GROUND_LIMIT = 9.5;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function loadNudge() {
  const start = src.indexOf('DirectorEditor.prototype.nudgeSelectedPuppet = function');
  const end = src.indexOf('DirectorEditor.prototype.getPuppetWorldScale', start);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  const block = 'function DirectorEditor() {}\n' + src.slice(start, end);
  return new Function('GROUND_LIMIT', 'clamp', `${block}\nreturn DirectorEditor;`)(GROUND_LIMIT, clamp);
}

const DirectorEditor = loadNudge();

function makeEditor(overrides) {
  const calls = { applied: 0, gizmo: 0, sliders: 0, dirty: 0, status: [], paused: 0 };
  const puppet = { id: 'p1', name: '甲', x: 0, z: 0, rotY: 0, scale: 1 };
  const editor = Object.assign(Object.create(DirectorEditor.prototype), {
    selectedPuppetId: 'p1',
    orbit: { theta: 0 },
    tl: { playing: false },
    puppets: { p1: puppet },
    getPuppet(id) { return this.puppets[id] || null; },
    applyPuppetTransform() { calls.applied++; },
    updateAxisGizmo() { calls.gizmo++; },
    syncPuppetAxisSliders() { calls.sliders++; },
    markDirty() { calls.dirty++; },
    setStatus(msg) { calls.status.push(msg); },
    pauseTimeline() { calls.paused++; this.tl.playing = false; },
  }, overrides);
  return { editor, puppet, calls };
}

describe('导演台：方向键平移人偶', () => {
  it('theta=0 时按观察方向移动，普通步长 0.05', () => {
    const { editor, puppet, calls } = makeEditor();
    expect(editor.nudgeSelectedPuppet('ArrowRight', false)).toBe(true);
    expect(puppet.x).toBeCloseTo(0.05, 8);
    expect(puppet.z).toBeCloseTo(0, 8);
    expect(editor.nudgeSelectedPuppet('ArrowLeft', false)).toBe(true);
    expect(puppet.x).toBeCloseTo(0, 8);
    expect(editor.nudgeSelectedPuppet('ArrowUp', false)).toBe(true);
    expect(puppet.z).toBeCloseTo(-0.05, 8);
    expect(editor.nudgeSelectedPuppet('ArrowDown', false)).toBe(true);
    expect(puppet.z).toBeCloseTo(0, 8);
    expect(calls.applied).toBe(4);
    expect(calls.gizmo).toBe(4);
    expect(calls.sliders).toBe(4);
    expect(calls.dirty).toBe(4);
  });

  it('Shift 加速步长 0.25', () => {
    const { editor, puppet } = makeEditor();
    editor.nudgeSelectedPuppet('ArrowRight', true);
    expect(puppet.x).toBeCloseTo(0.25, 8);
  });

  it('移动范围 clamp 到 ±GROUND_LIMIT', () => {
    const { editor, puppet } = makeEditor({ orbit: { theta: 0 } });
    for (let i = 0; i < 500; i++) editor.nudgeSelectedPuppet('ArrowRight', true);
    expect(puppet.x).toBe(GROUND_LIMIT);
    for (let i = 0; i < 1000; i++) editor.nudgeSelectedPuppet('ArrowLeft', true);
    expect(puppet.x).toBe(-GROUND_LIMIT);
    for (let i = 0; i < 500; i++) editor.nudgeSelectedPuppet('ArrowUp', true);
    expect(puppet.z).toBe(-GROUND_LIMIT);
    for (let i = 0; i < 1000; i++) editor.nudgeSelectedPuppet('ArrowDown', true);
    expect(puppet.z).toBe(GROUND_LIMIT);
  });

  it('theta=π/2 时方向随观察方向旋转', () => {
    const { editor, puppet } = makeEditor({ orbit: { theta: Math.PI / 2 } });
    // theta=π/2：forward=(-1,0)，right=(0,-1)
    editor.nudgeSelectedPuppet('ArrowUp', false);
    expect(puppet.x).toBeCloseTo(-0.05, 8);
    expect(puppet.z).toBeCloseTo(0, 8);
    editor.nudgeSelectedPuppet('ArrowRight', false);
    expect(puppet.z).toBeCloseTo(-0.05, 8);
  });

  it('未选中人偶返回 false 且不标脏', () => {
    const { editor, calls } = makeEditor({ selectedPuppetId: null });
    expect(editor.nudgeSelectedPuppet('ArrowRight', false)).toBe(false);
    expect(calls.dirty).toBe(0);
    expect(calls.applied).toBe(0);
  });

  it('未知按键返回 false', () => {
    const { editor, calls } = makeEditor();
    expect(editor.nudgeSelectedPuppet('ArrowFoo', false)).toBe(false);
    expect(editor.nudgeSelectedPuppet('Enter', false)).toBe(false);
    expect(calls.dirty).toBe(0);
  });

  it('播放中先暂停时间轴再平移', () => {
    const { editor, calls } = makeEditor({ tl: { playing: true } });
    expect(editor.nudgeSelectedPuppet('ArrowRight', false)).toBe(true);
    expect(calls.paused).toBe(1);
    expect(calls.applied).toBe(1);
  });

  it('键盘接线：原生 keydown 分支、SELECT 聚焦排除、成功移动才拦截', () => {
    expect(src).toContain("this.on(document, 'keydown', function (e) {");
    expect(src).toContain("tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'");
    expect(src).toContain("e.key.indexOf('Arrow') === 0");
    expect(src).toContain('self.nudgeSelectedPuppet(e.key, e.shiftKey)');
  });
});
