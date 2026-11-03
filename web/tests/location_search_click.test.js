/**
 * 场景弹窗搜索后的结果必须能点击。
 * 画布入口创建场景节点；分镜入口写入当前分镜。
 * nodes.js 不能再单独渲染一套点击无效的 .location-card。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const nodesSource = fs.readFileSync(path.join(root, 'web/js/nodes.js'), 'utf8');
const eventsSource = fs.readFileSync(path.join(root, 'web/js/events.js'), 'utf8');

function sliceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  expect(start).toBeGreaterThanOrEqual(0);
  expect(end).toBeGreaterThan(start);
  return source.slice(start, end);
}

describe('场景列表搜索后可点击', () => {
  it('搜索和切换世界不再由 nodes.js 另画一套卡片', () => {
    const listeners = sliceBetween(nodesSource, '场景选择弹窗事件监听', 'function renderShotGroupEditForm');
    expect(listeners).not.toMatch(/loadLocationsForWorld/);
    expect(listeners).not.toMatch(/locationSearchInput/);
  });

  it('loadLocationsForWorld 转到可点击的 loadLocations', () => {
    const fn = sliceBetween(nodesSource, 'async function loadLocationsForWorld', 'function selectLocation');
    expect(fn).toMatch(/typeof loadLocations === 'function'/);
    expect(fn).toMatch(/return loadLocations\(worldId, keyword\)/);
    expect(fn).toMatch(/createLocationNode\(location\)/);
    expect(fn).toMatch(/currentLocationSelectionContext/);
  });

  it('画布搜索结果在没有分镜上下文时创建场景节点', () => {
    const fn = sliceBetween(eventsSource, 'async function loadLocations', 'async function loadProps');
    expect(fn).toMatch(/window\.currentLocationSelectionContext/);
    expect(fn).toMatch(/window\.selectLocation\(location\)/);
    expect(fn).toMatch(/createLocationNode\(location\)/);
    expect(fn).toMatch(/requestSeq !== locationListRequestSeq/);
    const search = sliceBetween(eventsSource, 'let locationSearchTimer', '道具模态框事件');
    expect(search).toMatch(/loadLocations\(worldId, keyword\)/);
  });
});
