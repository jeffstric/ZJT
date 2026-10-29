/**
 * 时间轴：柱子归属链（682f89a3e 语音节点全链路）+ 导出素材包数据收集
 * （94ab321c6 导出素材包 / 351890ab2 防误清的 blob: 回退、download_url 协议校验）。
 *
 * timeline.js 为纯 IIFE 不导出，切片 eval 后注入 state 测试。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/timeline.js'), 'utf8');

// 切出 getPillarForNode（含递归）与导出数据收集三函数
const pillarStart = source.indexOf('function getPillarForNode');
const pillarEnd = source.indexOf('function addClipToPillar');
const pillarSrc = source.slice(pillarStart, pillarEnd);

const exportStart = source.indexOf('function isValidMediaUrl');
const exportEnd = source.indexOf('function exportTimelineToDraft');
const exportSrc = source.slice(exportStart, exportEnd);

const makePillarFn = (state) => {
  const factory = new Function('state', `${pillarSrc}; return getPillarForNode;`);
  return factory(state);
};

const makeExportFns = (state) => {
  const factory = new Function(
    'state', 'console',
    `${exportSrc}; return { isValidMediaUrl, resolveClipExportUrl, collectTimelineExportClips };`
  );
  return factory(state, console);
};

// 构造：剧本(script 5) → 分镜组(shot_group 6) → 分镜(shot_frame 7, 镜号2) → 视频(8)
// 分镜 → 对话组(dialogue_group 9)；对话组 → TTS(text_to_speech 10)；TTS → 音频(audio 11)
function makeState() {
  const nodes = [
    { id: 5, type: 'script', data: {} },
    { id: 6, type: 'shot_group', data: {} },
    { id: 7, type: 'shot_frame', data: { shotData: { shot_number: 2 } } },
    { id: 8, type: 'video', data: {} },
    { id: 9, type: 'dialogue_group', data: {} },
    { id: 10, type: 'text_to_speech', data: {} },
    { id: 11, type: 'audio', data: {} },
  ];
  const state = {
    nodes,
    connections: [
      { from: 5, to: 6 },
      { from: 6, to: 7 },
    ],
    videoConnections: [],
    imageConnections: [],
    audioConnections: [],
    timeline: {
      pillars: [{ id: '5_2', shotNumber: 2, videoClipIds: [], audioClipIds: [] }],
      clips: [],
      audioClips: [],
    },
  };
  return state;
}

describe('getPillarForNode 柱子归属链', () => {
  it('视频节点沿连线追溯到分镜柱子', () => {
    const state = makeState();
    state.connections.push({ from: 7, to: 8 });
    const fn = makePillarFn(state);
    expect(fn(8)?.id).toBe('5_2');
  });

  it('分镜节点直接解析镜号柱子', () => {
    const fn = makePillarFn(makeState());
    expect(fn(7)?.id).toBe('5_2');
  });

  it('TTS 节点经 dialogue_link/voice 线 → 对话组 → 分镜柱子', () => {
    const state = makeState();
    state.connections.push({ from: 7, to: 9 });
    state.audioConnections.push({ from: 9, to: 10, portType: 'dialogue_link' });
    const fn = makePillarFn(state);
    expect(fn(10)?.id).toBe('5_2');
  });

  it('音频节点经产出连线向上追溯（无 portType 的 TTS 产出线）', () => {
    const state = makeState();
    state.connections.push({ from: 7, to: 9 });
    state.audioConnections.push({ from: 9, to: 10, portType: 'dialogue_link' });
    state.audioConnections.push({ from: 10, to: 11, portType: null });
    const fn = makePillarFn(state);
    expect(fn(11)?.id).toBe('5_2');
  });

  it('音频节点经 data.ttsNodeId 回退追溯', () => {
    const state = makeState();
    state.connections.push({ from: 7, to: 9 });
    state.audioConnections.push({ from: 9, to: 10, portType: 'voice' });
    state.nodes.find((n) => n.id === 11).data.ttsNodeId = 10;
    const fn = makePillarFn(state);
    expect(fn(11)?.id).toBe('5_2');
  });

  it('音频节点经 sourceNodeId 找到对话组', () => {
    const state = makeState();
    state.connections.push({ from: 7, to: 9 });
    state.nodes.find((n) => n.id === 11).data.sourceNodeId = 9;
    const fn = makePillarFn(state);
    expect(fn(11)?.id).toBe('5_2');
  });

  it('孤立节点返回 null', () => {
    const fn = makePillarFn(makeState());
    expect(fn(11)).toBeNull();
  });
});

describe('导出素材包数据收集', () => {
  it('blob: 片段回退到所属节点当前 /upload 地址', () => {
    const state = makeState();
    state.nodes.push({ id: 20, type: 'video', data: { url: '/upload/videos/final.mp4' } });
    state.timeline.clips = [
      { order: 1, url: 'blob:https://x/tmp', name: 'a.mp4', duration: 5, nodeId: 20 },
    ];
    const { collectTimelineExportClips } = makeExportFns(state);
    const { videoClipsData } = collectTimelineExportClips();
    expect(videoClipsData[0].url).toBe('/upload/videos/final.mp4');
  });

  it('节点也无效时保留原地址（不阻塞导出）', () => {
    const state = makeState();
    state.timeline.clips = [
      { order: 1, url: 'blob:https://x/tmp', name: 'a.mp4', duration: 5, nodeId: 999 },
    ];
    const { collectTimelineExportClips } = makeExportFns(state);
    expect(collectTimelineExportClips().videoClipsData[0].url).toBe('blob:https://x/tmp');
  });

  it('按 order 排序、endTime 兜底 duration', () => {
    const state = makeState();
    state.timeline.clips = [
      { order: 2, url: 'https://c/2.mp4', name: 'b', duration: 4 },
      { order: 1, url: 'https://c/1.mp4', name: 'a', duration: 6, startTime: 2, endTime: 5 },
    ];
    state.timeline.audioClips = [
      { order: 1, url: '/upload/v.wav', name: 'v.wav', duration: 3 },
    ];
    const { collectTimelineExportClips } = makeExportFns(state);
    const v = collectTimelineExportClips().videoClipsData;
    expect(v.map((c) => c.name)).toEqual(['a', 'b']);
    expect(v[0].startTime).toBe(2);
    expect(v[0].endTime).toBe(5);
    expect(v[1].endTime).toBe(4); // 兜底 duration
    expect(v[1].startTime).toBe(0);
    expect(collectTimelineExportClips().audioClipsData[0].url).toBe('/upload/v.wav');
  });

  it('isValidMediaUrl 认可 http(s) 与 /upload/，拒绝 blob:/data:', () => {
    const { isValidMediaUrl } = makeExportFns(makeState());
    expect(isValidMediaUrl('https://cdn/a.mp4')).toBe(true);
    expect(isValidMediaUrl('http://cdn/a.mp4')).toBe(true);
    expect(isValidMediaUrl('/upload/a.mp4')).toBe(true);
    expect(isValidMediaUrl('blob:https://x/a')).toBe(false);
    expect(isValidMediaUrl('data:video/mp4;base64,x')).toBe(false);
    expect(isValidMediaUrl(undefined)).toBe(false);
  });
});

describe('exportTimelineAssets 契约（源码断言）', () => {
  const fnSrc = source.slice(
    source.indexOf('async function exportTimelineAssets'),
    source.indexOf('// 绑定音频片段事件'),
  );

  it('请求携带 video_clips/audio_clips 与身份头，走 Authorization 之外仍需 X-User-Id', () => {
    expect(fnSrc).toContain("'/api/export_timeline_assets'");
    expect(fnSrc).toContain('video_clips: videoClipsData');
    expect(fnSrc).toContain('audio_clips: audioClipsData');
    expect(fnSrc).toContain("localStorage.getItem('user_id')");
  });

  it('download_url 协议校验防 open redirect', () => {
    expect(fnSrc).toContain("test(downloadUrl)");
    expect(fnSrc).toContain('Invalid download URL protocol');
  });

  it('优先 downloadWithAuth（带 Authorization 代理下载），兼容回退 location.href', () => {
    expect(fnSrc).toContain('window.downloadWithAuth(downloadUrl,');
    expect(fnSrc).toContain('window.location.href = downloadUrl');
  });

  it('空时间轴提前拦截不发请求', () => {
    expect(fnSrc.indexOf('timeline_assets_empty')).toBeGreaterThan(-1);
    expect(fnSrc.indexOf('timeline_assets_empty')).toBeLessThan(fnSrc.indexOf('collectTimelineExportClips'));
  });
});
