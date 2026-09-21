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
  ed.puppets = [
    { id: 'p1', x: 0, z: 0, rotY: 0, jointDeg: {}, rig: { joints: {} } },
    { id: 'p2', x: 0, z: 0, rotY: 0, jointDeg: {}, rig: { joints: {} } }
  ];
  // 多机位宿主：cam1 / cam2
  ed.cameras = [
    { id: 'cam1', name: '镜头 1', pos: [0, 1, 4], target: [0, 1, 0], fov: 35 },
    { id: 'cam2', name: '镜头 2', pos: [5, 1, 4], target: [5, 1, 0], fov: 50 }
  ];
  ed.activeCameraId = 'cam1';
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

function camKey(t, px, fov, cut = false, camId = null) {
  return { t, pos: [px, 1, 4], target: [0, 1, 0], fov, cut, camId };
}

function getTrack(ed, kind, id) {
  return ed.tl.tracks.find((tr) => tr.kind === kind && tr.id === id) || null;
}

function camLane(ed, camId) {
  return getTrack(ed, 'camera', camId);
}

describe('DirectorStageTimeline：多轨道数据模型（每机位一轨）', () => {
  test('restoreTimeline: 无 timeline 字段时给默认值', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({ puppets: [] });
    expect(ed.tl.duration).toBe(6);
    expect(ed.tl.tracks).toEqual([]);
    expect(ed.tl.playing).toBe(false);
  });

  test('restoreTimeline: 每机位相机轨按 id 恢复，cut/camId 保留', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 999,
        tracks: [
          { kind: 'camera', id: 'cam2', keys: [camKey(2, 10, 50, true, 'cam2'), camKey(0, 8, 40)] },
          { kind: 'camera', id: 'cam1', keys: [camKey(0, 0, 35), camKey(4, 4, 45)] },
          { kind: 'puppet', id: 'p1', keys: [
            { t: 3, x: 3, z: 0, rotY: 90 },
            { t: 1, x: 1, z: 0, rotY: 0 },
            { t: 'bad', x: 0, z: 0, rotY: 0 }
          ] }
        ]
      }
    });
    expect(ed.tl.duration).toBe(60);
    const c1 = camLane(ed, 'cam1');
    expect(c1.keys.map((k) => k.t)).toEqual([0, 4]);
    const c2 = camLane(ed, 'cam2');
    expect(c2.keys.map((k) => k.t)).toEqual([0, 2]);
    expect(c2.keys[1].cut).toBe(true);
    expect(getTrack(ed, 'puppet', 'p1').keys.map((k) => k.t)).toEqual([1, 3]);
  });

  test('restoreTimeline: v3 无 id 相机轨整体并入激活机位轨（行为不变迁移）', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.activeCameraId = 'cam2';   // 旧数据落轨到激活机位
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        tracks: [
          { kind: 'camera', keys: [camKey(0, 0, 30), camKey(2, 10, 50, true), camKey(4, 20, 70)] },
          { kind: 'puppet', id: 'p1', keys: [{ t: 0, x: 0, z: 0, rotY: 0 }] }
        ]
      }
    });
    const lane = camLane(ed, 'cam2');
    expect(lane).toBeTruthy();
    expect(lane.keys.map((k) => k.t)).toEqual([0, 2, 4]);
    expect(lane.keys[1].cut).toBe(true);   // 原 cut 语义保留
    expect(camLane(ed, 'cam1')).toBeNull();
  });

  test('restoreTimeline: v2 旧格式全局 keys 迁移（相机并入激活机位轨）', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        keys: [
          { t: 0, puppets: { p1: { x: 0, z: 0, rotY: 0 }, p2: { x: 5, z: 0, rotY: 0 } }, camera: { pos: [0, 1, 4], target: [0, 1, 0], fov: 35 } },
          { t: 2, puppets: { p1: { x: 2, z: 0, rotY: 90 } }, camera: { pos: [2, 1, 4], target: [0, 1, 0], fov: 40 } },
          { t: 'bad', puppets: null, camera: null }
        ]
      }
    });
    const lane = camLane(ed, 'cam1');   // activeCameraId 默认 cam1
    expect(lane.keys.map((k) => k.t)).toEqual([0, 2]);
    const p2 = getTrack(ed, 'puppet', 'p2');
    expect(p2.keys.map((k) => k.t)).toEqual([0]);
  });

  test('recordTimelineKey: 记录所有角色 + 相机到激活机位轨，相近时刻覆盖', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline(null);
    ed.puppets[0].x = 2.5;
    ed.tl.playhead = 1.0;
    ed.recordTimelineKey();
    expect(getTrack(ed, 'puppet', 'p1').keys.length).toBe(1);
    expect(getTrack(ed, 'puppet', 'p1').keys[0].x).toBe(2.5);
    expect(camLane(ed, 'cam1').keys.length).toBe(1);
    expect(camLane(ed, 'cam1').keys[0].camId).toBe('cam1');

    // 激活机位切到 cam2 → 相机键落到 cam2 轨
    ed.activeCameraId = 'cam2';
    ed.tl.playhead = 2.0;
    ed.recordTimelineKey();
    expect(camLane(ed, 'cam2').keys.length).toBe(1);
    expect(camLane(ed, 'cam2').keys[0].camId).toBe('cam2');
    // 各轨键数独立
    expect(camLane(ed, 'cam1').keys.map((k) => k.t)).toEqual([1]);
    expect(getTrack(ed, 'puppet', 'p1').keys.map((k) => k.t)).toEqual([1, 2]);
  });

  test('recordTimelineKeyOnTrack: camera:<id> 只写对应机位轨', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline(null);
    ed.tl.playhead = 1;
    ed.recordTimelineKeyOnTrack('camera:cam2');
    expect(camLane(ed, 'cam2').keys.length).toBe(1);
    expect(camLane(ed, 'cam2').keys[0].camId).toBe('cam2');
    expect(camLane(ed, 'cam1')).toBeNull();

    ed.recordTimelineKeyOnTrack('puppet:p1');
    expect(getTrack(ed, 'puppet', 'p1').keys.length).toBe(1);
  });

  test('serializeTimeline: 丢弃已删除机位/人偶轨，往返一致', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        tracks: [
          { kind: 'camera', id: 'cam1', keys: [camKey(1, 0, 35)] },
          { kind: 'camera', id: 'dead-cam', keys: [camKey(1, 9, 90)] },
          { kind: 'puppet', id: 'p1', keys: [{ t: 1, x: 1, z: 2, rotY: 3 }] },
          { kind: 'puppet', id: 'dead', keys: [{ t: 1, x: 9, z: 9, rotY: 9 }] }
        ]
      }
    });
    const out = ed.serializeTimeline();
    expect(out.tracks.length).toBe(2);
    expect(out.tracks.find((tr) => tr.kind === 'camera').id).toBe('cam1');
    expect(out.tracks.some((tr) => tr.id === 'dead-cam')).toBe(false);
    expect(out.tracks.some((tr) => tr.id === 'dead')).toBe(false);

    const ed2 = createFakeEditor(makeEditorClass(loadModule()));
    ed2.restoreTimeline({ timeline: out });
    expect(camLane(ed2, 'cam1').keys.length).toBe(1);
    expect(getTrack(ed2, 'puppet', 'p1').keys[0].x).toBe(1);
  });

  test('deleteTimelineKeyAtPlayhead: 跨轨取最近；deleteTimelineKeyOnTrack: 只删本轨', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        tracks: [
          { kind: 'camera', id: 'cam1', keys: [camKey(3.1, 0, 35)] },
          { kind: 'puppet', id: 'p1', keys: [{ t: 1, x: 0, z: 0, rotY: 0 }, { t: 3, x: 0, z: 0, rotY: 0 }] },
          { kind: 'puppet', id: 'p2', keys: [{ t: 1.05, x: 0, z: 0, rotY: 0 }] }
        ]
      }
    });
    // 播放头 3.0：p1@3(0.0) 与 cam1@3.1(0.1) → 删最近的 p1@3
    ed.tl.playhead = 3.0;
    ed.deleteTimelineKeyAtPlayhead();
    expect(getTrack(ed, 'puppet', 'p1').keys.map((k) => k.t)).toEqual([1]);
    expect(camLane(ed, 'cam1').keys.length).toBe(1);

    // 单轨删除只影响本轨（删空后轨道对象保留，序列化时剔除）
    ed.tl.playhead = 1.0;
    ed.deleteTimelineKeyOnTrack('puppet:p1');
    expect(getTrack(ed, 'puppet', 'p1').keys.length).toBe(0);
    expect(getTrack(ed, 'puppet', 'p2').keys.length).toBe(1);

    // 远离任何关键帧时无操作
    ed.tl.playhead = 5.5;
    ed.deleteTimelineKeyAtPlayhead();
    expect(camLane(ed, 'cam1').keys.length).toBe(1);
  });

  test('toggleCameraCutAtPlayhead: 跨机位轨找最近键切跳切，半径外无操作', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        tracks: [
          { kind: 'camera', id: 'cam1', keys: [camKey(1, 0, 35)] },
          { kind: 'camera', id: 'cam2', keys: [camKey(4, 10, 50)] }
        ]
      }
    });
    ed.tl.playhead = 1.1;
    ed.toggleCameraCutAtPlayhead();
    expect(camLane(ed, 'cam1').keys[0].cut).toBe(true);
    // 半径外：4.3 距 cam2@4 是 0.3 > 0.2 → 不切换
    ed.tl.playhead = 4.3;
    ed.toggleCameraCutAtPlayhead();
    expect(camLane(ed, 'cam2').keys[0].cut).toBe(false);
  });
});

describe('DirectorStageTimeline：多机位求值与播放', () => {
  test('多机位接管：键落在哪条机位轨，画面就归哪个机位（跨轨=硬切）', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        tracks: [
          // cam1：0s 全景位 → 4s 推近（平滑运镜）
          { kind: 'camera', id: 'cam1', keys: [camKey(0, 0, 30), camKey(4, 4, 50)] },
          // cam2：2s 切过来（接管），自身只有一个键 → 保持
          { kind: 'camera', id: 'cam2', keys: [camKey(2, 10, 60, false, 'cam2')] }
        ]
      }
    });
    // t=1：cam1 轨内平滑
    ed.applyTimelineAt(1, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(1);
    expect(ed.virtualCamCfg.fov).toBeCloseTo(35);
    // t=1.99：仍 cam1（还没到 cam2 的键），轨内线性 pos.x ≈ 1.99
    ed.applyTimelineAt(1.99, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(1.99);
    // t=2：cam2 键接管 → 瞬间跳变到 cam2 配置（硬切，不经过中间机位）
    ed.applyTimelineAt(2, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(10);
    expect(ed.virtualCamCfg.fov).toBeCloseTo(60);
    // t=3：cam2 无下一键 → 保持
    ed.applyTimelineAt(3, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(10);
    // t=4：cam1@4 接管 → 切回 cam1 末键位形
    ed.applyTimelineAt(4, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(4);
    expect(ed.virtualCamCfg.fov).toBeCloseTo(50);
    // t=5：cam1 轨内末键之后保持
    ed.applyTimelineAt(5, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(4);
  });

  test('同轨跳切：cut 键在单轨内也硬切；机位删除后其轨不参与求值', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 6,
        tracks: [
          { kind: 'camera', id: 'cam1', keys: [camKey(0, 0, 30), camKey(2, 10, 50, true), camKey(4, 20, 70)] },
          { kind: 'camera', id: 'dead-cam', keys: [camKey(3, 99, 99)] }
        ]
      }
    });
    // 同轨 cut：t=1 保持 0s 配置，t=2 跳变
    ed.applyTimelineAt(1, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(0);
    ed.applyTimelineAt(2, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(10);
    // dead-cam 不在 editor.cameras 里 → 3s 不会被它劫持，仍 cam1 轨内插值
    ed.applyTimelineAt(3, 0);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(15);
  });

  test('逐轨插值（两轨键密度不同互不影响），rotY 走最短路径', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 4,
        tracks: [
          { kind: 'puppet', id: 'p1', keys: [
            { t: 0, x: 0, z: 0, rotY: 350 },
            { t: 4, x: 4, z: 8, rotY: 10 }
          ] },
          { kind: 'puppet', id: 'p2', keys: [
            { t: 0, x: 10, z: 0, rotY: 0 },
            { t: 2, x: 12, z: 0, rotY: 90 },
            { t: 4, x: 14, z: 0, rotY: 0 }
          ] },
          { kind: 'camera', id: 'cam1', keys: [camKey(0, 0, 30), camKey(4, 4, 50)] }
        ]
      }
    });
    ed.applyTimelineAt(2, 0);
    const p1 = ed.puppets.find((p) => p.id === 'p1');
    const p2 = ed.puppets.find((p) => p.id === 'p2');
    expect(p1.x).toBeCloseTo(2);
    expect(p1.z).toBeCloseTo(4);
    // 350° → 10° 应经 0°（+20°），而非绕 -340°
    expect(p1.rotY).toBeCloseTo(0);
    // p2 在 t=2 精确落在自己的第二键上
    expect(p2.x).toBeCloseTo(12);
    expect(p2.rotY).toBeCloseTo(90);
    expect(ed.virtualCamCfg.pos.x).toBeCloseTo(2);
    expect(ed.virtualCamCfg.fov).toBeCloseTo(40);
  });

  test('applyTimelineAt: 无轨道的人偶保持当前编辑位形', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 2,
        tracks: [{ kind: 'puppet', id: 'p2', keys: [{ t: 0, x: 0, z: 0, rotY: 0 }, { t: 2, x: 2, z: 0, rotY: 0 }] }]
      }
    });
    ed.puppets[0].x = 7;
    ed.applyTimelineAt(1, 0);
    expect(ed.puppets[0].x).toBe(7);
    expect(ed.puppets[1].x).toBeCloseTo(1);
  });

  test('tickTimeline: 播放推进到时长末尾自动停止', () => {
    const ed = createFakeEditor(makeEditorClass(loadModule()));
    ed.restoreTimeline({
      timeline: {
        duration: 1,
        tracks: [
          { kind: 'puppet', id: 'p1', keys: [{ t: 0, x: 0, z: 0, rotY: 0 }, { t: 1, x: 1, z: 0, rotY: 0 }] },
          { kind: 'camera', id: 'cam1', keys: [camKey(0, 0, 35), camKey(1, 1, 35)] }
        ]
      }
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
