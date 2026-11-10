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

// 切出柱子系统三段：createOrUpdatePillar / getPillarForNode / 迁移两函数
const segFrom = (startMark, endMark) => {
  const start = source.indexOf(startMark);
  const end = source.indexOf(endMark);
  return source.slice(start, end);
};
const pillarCreateSrc = segFrom('function createOrUpdatePillar', 'function getOrCreateFreePillar');
const pillarForNodeSrc = segFrom('function getPillarForNode', 'function addClipToPillar');
const migrateSrc = segFrom('function resolveShotGroupPillarScriptId', '// 添加视频到时间轴');

const makeFns = (state) => {
  const factory = new Function(
    'state', 'console',
    `${pillarCreateSrc}${pillarForNodeSrc}${migrateSrc}
     return { getPillarForNode, autoMigratePillars };`
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
