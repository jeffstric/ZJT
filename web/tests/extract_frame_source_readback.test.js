/**
 * 提取帧节点源视频地址实时回读（fix 81686538）。
 *
 * 背景：画布上视频节点上传期间的 blob: 临时地址被提取帧节点记住后，提交
 * 提取请求时服务端报「不支持外部视频URL」——blob:/data: 是浏览器本地地址，
 * 服务端无法访问。修复契约：提交前从连线源节点实时回读最新 videoUrl，
 * 临时地址拦截提示，URL 变化时覆盖节点数据并触发自动保存。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/extract_frame_node.js'), 'utf8');

const helperStart = source.indexOf('// 浏览器本地临时地址');
const helperEnd = source.indexOf('// 秒 → "mm:ss.cc" 时间码');
const helperSource = source.slice(helperStart, helperEnd);
const factory = new Function('state', `${helperSource}; return { isTemporaryVideoUrl, findConnectedVideoNode };`);
const makeHelpers = (state) => factory(state);

describe('isTemporaryVideoUrl', () => {
  const { isTemporaryVideoUrl } = makeHelpers(undefined);

  it('blob: 与 data: 前缀视为临时地址', () => {
    expect(isTemporaryVideoUrl('blob:https://localhost/abc')).toBe(true);
    expect(isTemporaryVideoUrl('data:video/mp4;base64,xxx')).toBe(true);
  });

  it('正常 http(s) 地址不是临时地址', () => {
    expect(isTemporaryVideoUrl('https://cdn.example.com/a.mp4')).toBe(false);
    expect(isTemporaryVideoUrl('/upload/videos/a.mp4')).toBe(false);
  });

  it('空值返回 false', () => {
    expect(isTemporaryVideoUrl('')).toBe(false);
    expect(isTemporaryVideoUrl(null)).toBe(false);
    expect(isTemporaryVideoUrl(undefined)).toBe(false);
  });
});

describe('findConnectedVideoNode', () => {
  it('沿 connections 找到源节点', () => {
    const state = {
      connections: [{ from: 'node-a', to: 'node-b' }],
      nodes: [
        { id: 'node-a', type: 'video' },
        { id: 'node-b', type: 'extract_frame' },
      ],
    };
    const { findConnectedVideoNode } = makeHelpers(state);
    expect(findConnectedVideoNode({ id: 'node-b' })?.id).toBe('node-a');
  });

  it('无连线返回 null', () => {
    const { findConnectedVideoNode } = makeHelpers({
      connections: [], nodes: [{ id: 'node-a' }],
    });
    expect(findConnectedVideoNode({ id: 'node-b' })).toBeNull();
  });

  it('连线指向其他节点时不匹配', () => {
    const { findConnectedVideoNode } = makeHelpers({
      connections: [{ from: 'node-a', to: 'node-c' }],
      nodes: [{ id: 'node-a' }, { id: 'node-b' }],
    });
    expect(findConnectedVideoNode({ id: 'node-b' })).toBeNull();
  });

  it('state 未初始化时安全返回 null', () => {
    const { findConnectedVideoNode } = makeHelpers(undefined);
    expect(findConnectedVideoNode({ id: 'x' })).toBeNull();
  });
});

describe('extractFrame 提交前回读契约（源码断言）', () => {
  const start = source.indexOf('async function extractFrame()');
  const body = source.slice(start, source.indexOf('var hasVideoFile', start));

  it('无本地文件时先回读连线源节点', () => {
    expect(body).toContain('findConnectedVideoNode(node)');
  });

  it('源节点还没有视频 → 提示并中止提交', () => {
    expect(body).toContain("extract_frame_source_no_video");
    expect(body.slice(body.indexOf('if (!liveUrl)'), body.indexOf('if (isTemporaryVideoUrl')))
      .toContain('return');
  });

  it('源视频是 blob:/data: 临时地址 → 提示上传中并中止', () => {
    expect(body).toContain('isTemporaryVideoUrl(liveUrl)');
    expect(body).toContain("extract_frame_source_uploading");
  });

  it('源地址与节点缓存不一致 → 覆盖并触发自动保存', () => {
    expect(body).toContain('liveUrl !== node.data.videoUrl');
    expect(body).toContain('applySourceVideo(connectedVideoNode)');
    expect(body).toContain('safeAutoSave()');
  });
});
