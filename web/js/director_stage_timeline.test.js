import { describe, expect, test } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// 加载 IIFE 模块（无 DOM 依赖，attach 才触碰编辑器原型）
function loadModule() {
  const source = fs.readFileSync(path.resolve('web/js/director_stage_timeline.js'), 'utf8');
  const fakeWindow = {};
  const factory = new Function('window', `${source}\n;return window.DirectorStageTimelineModule;`);
  return factory(fakeWindow);
}

function makeEditorClass(module) {
  function FakeEditor() {}
  module.attach(FakeEditor, {
    clamp: (v, lo, hi) => Math.min(hi, Math.max(lo, v)),
    round2: (v) => Math.round(v * 100) / 100,
    deg2rad: (d) => (d * Math.PI) / 180
  });
  return FakeEditor;
}

function createFakeEditor(FakeEditor) {
  const ed = new FakeEditor();
  ed.puppets = [{ id: 'p1', x: 0, z: 0, rotY: 0, jointDeg: {}, rig: { joints: {} } }];
  ed.virtualCamCfg = {
    pos: { x: 0, y: 1, z: 4, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
    target: { x: 0, y: 1, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
    fov: 35
  };
  ed.applyPuppetTransform = () => {};
  ed.applyJointDeg = () => {};
  ed.updateCamHelper = () => {};
  ed.markDirty = () => {};
  ed.renderTimeline = () => {};
  ed.renderTimelineTime = () => {};
  ed.setStatus = () => {};
  ed.$ = () => null;
  return ed;
}

describe('DirectorStageTimeline', () => {
  test('restoreTimeline: 旧数据无 timeline 字段时给默认值', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({ puppets: [] });
    expect(ed.tl.duration).toBe(6);
    expect(ed.tl.keys).toEqual([]);
    expect(ed.tl.playing).toBe(false);
  });

  test('restoreTimeline: 非法时长/乱序关键帧被清洗排序', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 999,
        keys: [
          { t: 3, puppets: { p1: { x: 3, z: 0, rotY: 90 } }, camera: { pos: [3, 1, 3], target: [0, 1, 0], fov: 40 } },
          { t: 1, puppets: { p1: { x: 1, z: 0, rotY: 0 } }, camera: { pos: [1, 1, 4], target: [0, 1, 0], fov: 35 } },
          { t: 'bad', puppets: null, camera: null }
        ]
      }
    });
    expect(ed.tl.duration).toBe(60);
    expect(ed.tl.keys.map((k) => k.t)).toEqual([1, 3]);
    // 缺 camera 的关键帧补全默认结构，避免插值崩溃（排序后第 2 个是 t=3）
    expect(ed.tl.keys[1].camera.pos).toEqual([3, 1, 3]);
  });

  test('recordTimelineKey: 快照当前位形并在相近时刻覆盖', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline(null);
    ed.puppets[0].x = 2.5;
    ed.tl.playhead = 1.0;
    ed.recordTimelineKey();
    expect(ed.tl.keys.length).toBe(1);
    expect(ed.tl.keys[0].puppets.p1.x).toBe(2.5);

    // 时刻 1.02 在覆盖窗口内 → 不新增
    ed.puppets[0].x = 9;
    ed.tl.playhead = 1.02;
    ed.recordTimelineKey();
    expect(ed.tl.keys.length).toBe(1);
    expect(ed.tl.keys[0].t).toBe(1);
    expect(ed.tl.keys[0].puppets.p1.x).toBe(9);

    // 时刻 2.0 → 新增并保持排序
    ed.tl.playhead = 2.0;
    ed.recordTimelineKey();
    expect(ed.tl.keys.map((k) => k.t)).toEqual([1, 2]);
  });

  test('applyTimelineAt: 角色位置/相机线性插值，rotY 走最短路径', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 4,
        keys: [
          { t: 0, puppets: { p1: { x: 0, z: 0, rotY: 350 } }, camera: { pos: [0, 1, 4], target: [0, 1, 0], fov: 30 } },
          { t: 4, puppets: { p1: { x: 4, z: 8, rotY: 10 } }, camera: { pos: [4, 1, 0], target: [4, 1, 8], fov: 50 } }
        ]
      }
    });
    ed.applyTimelineAt(2, 0);
    const p = ed.puppets[0];
    expect(p.x).toBeCloseTo(2);
    expect(p.z).toBeCloseTo(4);
    // 350° → 10° 应经 0°（+20°），而非绕 -340°
    expect(p.rotY).toBeCloseTo(0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(2);
    expect(ed.virtualCamCfg.pos.z).toBeCloseTo(2);
    expect(ed.virtualCamCfg.fov).toBeCloseTo(40);
  });

  test('applyTimelineAt: 末关键帧之后保持末帧位形', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 2,
        keys: [
          { t: 0, puppets: { p1: { x: 0, z: 0, rotY: 0 } }, camera: { pos: [0, 1, 4], target: [0, 1, 0], fov: 35 } },
          { t: 1, puppets: { p1: { x: 1, z: 1, rotY: 45 } }, camera: { pos: [1, 1, 1], target: [1, 1, 1], fov: 45 } }
        ]
      }
    });
    ed.applyTimelineAt(1.8, 0);
    expect(ed.puppets[0].x).toBe(1);
    expect(ed.puppets[0].rotY).toBe(45);
    expect(ed.virtualCamCfg.fov).toBe(45);
  });

  test('applyTimelineAt: 关键帧未包含的人偶保持当前编辑位形', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 2,
        keys: [
          { t: 0, puppets: {}, camera: { pos: [0, 1, 4], target: [0, 1, 0], fov: 35 } },
          { t: 2, puppets: {}, camera: { pos: [2, 1, 4], target: [0, 1, 0], fov: 35 } }
        ]
      }
    });
    ed.puppets[0].x = 7;
    ed.applyTimelineAt(1, 0);
    expect(ed.puppets[0].x).toBe(7);
  });

  test('serializeTimeline: 丢弃已删除人偶的关键帧数据', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline(null);
    ed.tl.keys = [{
      t: 1,
      puppets: { p1: { x: 1, z: 2, rotY: 3 }, dead: { x: 9, z: 9, rotY: 9 } },
      camera: { pos: [1, 1, 1], target: [0, 0, 0], fov: 35 }
    }];
    const out = ed.serializeTimeline();
    expect(out.keys[0].puppets.p1).toEqual({ x: 1, z: 2, rotY: 3 });
    expect(out.keys[0].puppets.dead).toBeUndefined();
  });

  test('deleteTimelineKeyAtPlayhead: 只删吸附半径内的关键帧', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: { duration: 6, keys: [
        { t: 1, puppets: {}, camera: { pos: [0, 0, 0], target: [0, 0, 0], fov: 35 } },
        { t: 3, puppets: {}, camera: { pos: [1, 1, 1], target: [0, 0, 0], fov: 35 } }
      ] }
    });
    ed.tl.playhead = 2.9;
    ed.deleteTimelineKeyAtPlayhead();
    expect(ed.tl.keys.map((k) => k.t)).toEqual([1]);
    // 远离任何关键帧时无操作
    ed.tl.playhead = 5.5;
    ed.deleteTimelineKeyAtPlayhead();
    expect(ed.tl.keys.map((k) => k.t)).toEqual([1]);
  });

  test('tickTimeline: 播放推进到时长末尾自动停止', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: { duration: 1, keys: [
        { t: 0, puppets: { p1: { x: 0, z: 0, rotY: 0 } }, camera: { pos: [0, 1, 4], target: [0, 1, 0], fov: 35 } },
        { t: 1, puppets: { p1: { x: 1, z: 0, rotY: 0 } }, camera: { pos: [1, 1, 4], target: [0, 1, 0], fov: 35 } }
      ] }
    });
    ed.tl.playing = true;
    ed.tl.lastFrameAt = 10;
    // dt=0.05 → playhead 0.05，继续播放
    ed.tickTimeline(10.05);
    expect(ed.tl.playing).toBe(true);
    expect(ed.tl.playhead).toBeCloseTo(0.05);
    // dt=0.25 被 clamp 到 0.1 → playhead 0.15，仍继续
    ed.tickTimeline(10.3);
    expect(ed.tl.playing).toBe(true);
    expect(ed.tl.playhead).toBeCloseTo(0.15);
    // 连续推进到时长末尾 → 停在 1.0 并结束
    for (let i = 0; i < 20 && ed.tl.playing; i++) {
      ed.tickTimeline(10.4 + i * 0.1);
    }
    expect(ed.tl.playing).toBe(false);
    expect(ed.tl.playhead).toBe(1);
  });
});
