/**
 * 时间轴柱子自动迁移（故事板转工作流等无 parsedData 画布的柱子补建）。
 *
 * 背景：「故事板→工作流」转换产物 timeline.pillars 为空且剧本节点无
 * parsedData，首个视频加入时间轴时找不到柱子落入 __free__，时间轴没有
 * 分镜1/分镜2 完备格子。autoMigratePillars 增加分镜组节点作为第二推导
 * 来源，scriptId 口径与 getPillarForNode 一致（剧本节点 → scriptNodeId
 * 字段 → 分镜组自身 id 兜底）。
 *
 * timeline.js 为纯 IIFE 不导出，切片 eval 后注入 state 测试。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/timeline.js'), 'utf8');

// 切出柱子系统三段：createOrUpdatePillar / getPillarForNode / 柱成员维护 + 迁移两函数
const segFrom = (startMark, endMark) => {
  const start = source.indexOf(startMark);
  const end = source.indexOf(endMark);
  return source.slice(start, end);
};
const pillarCreateSrc = segFrom('function createOrUpdatePillar', 'function getOrCreateFreePillar');
const pillarForNodeSrc = segFrom('function getPillarForNode', 'function addClipToPillar');
// addClipToPillar/removeClipFromPillar 是迁移归位（reassignFreePillarClips）的依赖
const pillarMemberSrc = segFrom('function addClipToPillar', 'function resolveShotGroupPillarScriptId');
const migrateSrc = segFrom('function resolveShotGroupPillarScriptId', '// 添加视频到时间轴');

const makeFns = (state) => {
  const factory = new Function(
    'state', 'console',
    `${pillarCreateSrc}${pillarForNodeSrc}${pillarMemberSrc}${migrateSrc}
     return { getPillarForNode, autoMigratePillars, reassignFreePillarClips };`
  );
  return factory(state, { log() {}, warn() {}, error() {} });
};

const makeState = ({ nodes, connections }) => ({
  nodes,
  connections,
  videoConnections: [],
  imageConnections: [],
  audioConnections: [],
  timeline: { pillars: [], clips: [], audioClips: [], nextClipId: 1, visible: false },
});

// 无剧本故事板转出的画布形态：group(10) 带 shots；frame(11) 镜号2；video(20)
const noScriptCanvas = () => makeState({
  nodes: [
    { id: 10, type: 'shot_group', data: { shots: [{ shot_number: 1, duration: 5 }, { shot_number: 2, duration: 4 }] } },
    { id: 11, type: 'shot_frame', data: { shotJson: { shot_number: 2 } } },
    { id: 20, type: 'video', data: { url: 'https://cdn/v.mp4' } },
  ],
  connections: [
    { id: 1, from: 10, to: 11 },
    { id: 2, from: 11, to: 20 },
  ],
});

describe('autoMigratePillars：分镜组节点推导（无 parsedData 画布）', () => {
  it('无剧本节点：柱子 id 以分镜组节点 id 为 scriptId 维度，逐分镜成格', () => {
    const state = noScriptCanvas();
    const { autoMigratePillars } = makeFns(state);
    expect(autoMigratePillars()).toBe(true);
    expect(state.timeline.pillars.map(p => p.id)).toEqual(['10_1', '10_2']);
    expect(state.timeline.pillars[0].defaultDuration).toBe(5);
    expect(state.timeline.visible).toBe(true);
  });

  it('有剧本节点（无 parsedData，如转换产物）：沿连接取剧本节点 id', () => {
    const state = makeState({
      nodes: [
        { id: 1, type: 'script', data: { scriptContent: 'x' } },
        { id: 10, type: 'shot_group', data: { shots: [{ shot_number: 1 }] } },
      ],
      connections: [{ id: 1, from: 1, to: 10 }],
    });
    const { autoMigratePillars } = makeFns(state);
    expect(autoMigratePillars()).toBe(true);
    expect(state.timeline.pillars.map(p => p.id)).toEqual(['1_1']);
  });

  it('已有柱子：跳过迁移', () => {
    const state = noScriptCanvas();
    state.timeline.pillars = [{ id: 'keep' }];
    const { autoMigratePillars } = makeFns(state);
    expect(autoMigratePillars()).toBe(false);
    expect(state.timeline.pillars).toEqual([{ id: 'keep' }]);
  });

  it('script.parsedData 仍是第一来源（画布内拆分链路）', () => {
    const state = makeState({
      nodes: [
        {
          id: 1, type: 'script',
          data: { parsedData: { max_group_duration: 12, shot_groups: [{ shots: [{ shot_number: 3 }] }] } },
        },
      ],
      connections: [],
    });
    const { autoMigratePillars } = makeFns(state);
    expect(autoMigratePillars()).toBe(true);
    expect(state.timeline.pillars.map(p => p.id)).toEqual(['1_3']);
    expect(state.timeline.pillars[0].defaultDuration).toBe(12);
  });
});

describe('getPillarForNode：无剧本节点时以分镜组 id 兜底', () => {
  it('视频 → 分镜帧 → 分镜组（无剧本）：命中 组id_镜号 柱子', () => {
    const state = noScriptCanvas();
    const fns = makeFns(state);
    fns.autoMigratePillars();
    const pillar = fns.getPillarForNode(20);
    expect(pillar && pillar.id).toBe('10_2');
  });
});

// pillars=['__free__'] 是柱子缺失期受损画布的持久化形态（视频落入自由柱后
// 被 autoSave 存盘）。迁移守卫若只看 length 会误判"已有柱子"而永不补建，
// 已落 __free__ 的片段也随迁移后的归位逻辑收回分镜柱。
describe('pillars 仅含 __free__：受损画布重载后照常迁移并归位', () => {
  const damagedCanvas = () => {
    const state = noScriptCanvas();
    // 模拟受损期：video(20) 落入 __free__ 且已持久化；另有一个无归属视频(21)
    state.timeline.pillars = [{
      id: '__free__', scriptId: null, shotNumber: null, defaultDuration: 15,
      videoClipIds: [101, 102], audioClipIds: [201],
    }];
    state.timeline.clips = [
      { id: 101, nodeId: 20, url: 'https://cdn/v.mp4', duration: 4, pillarId: '__free__', order: 0 },
      { id: 102, nodeId: 21, url: 'https://cdn/orphan.mp4', duration: 3, pillarId: '__free__', order: 1 },
    ];
    state.timeline.audioClips = [
      { id: 201, nodeId: 20, url: 'https://cdn/a.mp3', duration: 2, pillarId: '__free__', order: 0 },
    ];
    return state;
  };

  it('__free__ 不算"已有柱子"：迁移照常触发，补建分镜柱', () => {
    const state = damagedCanvas();
    const { autoMigratePillars } = makeFns(state);
    expect(autoMigratePillars()).toBe(true);
    expect(state.timeline.pillars.map(p => p.id)).toEqual(['__free__', '10_1', '10_2']);
  });

  it('可归位的 video/audio 片段从 __free__ 收回到对应分镜柱', () => {
    const state = damagedCanvas();
    const { autoMigratePillars } = makeFns(state);
    autoMigratePillars();
    // video(20) → 镜头2 柱子；audio(201) 同节点同柱；102 无归属留在 __free__
    expect(state.timeline.clips.find(c => c.id === 101).pillarId).toBe('10_2');
    expect(state.timeline.audioClips.find(c => c.id === 201).pillarId).toBe('10_2');
    const free = state.timeline.pillars.find(p => p.id === '__free__');
    expect(free.videoClipIds).toEqual([102]);
    expect(free.audioClipIds).toEqual([]);
    expect(state.timeline.pillars.find(p => p.id === '10_2').videoClipIds).toEqual([101]);
    expect(state.timeline.pillars.find(p => p.id === '10_2').audioClipIds).toEqual([201]);
  });

  it('解析不到分镜柱的片段保持独立片段语义不动', () => {
    const state = damagedCanvas();
    const { autoMigratePillars } = makeFns(state);
    autoMigratePillars();
    // video(21) 无连接可追溯：仍留在 __free__
    const orphan = state.timeline.clips.find(c => c.id === 102);
    expect(orphan.pillarId).toBe('__free__');
    expect(state.timeline.pillars.find(p => p.id === '__free__').videoClipIds).toEqual([102]);
  });
});
