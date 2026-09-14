/**
 * 画布分组（canvas_groups.js）+ 复制/粘贴（canvas_clipboard.js）+ 右键菜单
 * （canvas_context_menu.js）行为与接线测试。
 *
 * 覆盖三层：
 * 1. 分组行为层：编组包围盒计算、拖入拖出成员归属判定、解散/恢复（含陈旧成员过滤）；
 * 2. 剪贴板行为层：复制类型过滤（分镜/分镜组/剧本排除）、内部连线收集、
 *    粘贴 id 重映射与连线重建、连续粘贴偏移、再制锚点、运行态字段净化；
 * 3. 接线层：serializeWorkflow/restoreWorkflow/右键菜单/快捷键/脚本引入的存在性。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// ─── 环境搭建：以真实源码 + 全局 stub 驱动 ───────────────────────

const canvasHost = document.createElement('div');
canvasHost.id = 'canvas';
document.body.appendChild(canvasHost);

const containerHost = document.createElement('div');
containerHost.id = 'canvasContainer';
document.body.appendChild(containerHost);

const state = {};
globalThis.state = state;
globalThis.MIN_NODE_Y = 80;
globalThis.showToast = vi.fn();
globalThis.safeAutoSave = vi.fn();
globalThis.clearSelection = vi.fn();
globalThis.getNodeSize = (node) => ({ w: node._w || 300, h: node._h || 200 });
globalThis.getViewportNodePosition = () => ({ x: 100, y: 120 });
globalThis.renderAllConnections = vi.fn();
globalThis.renderMinimap = vi.fn();
globalThis.setMultipleSelected = vi.fn();
globalThis.captureHistorySnapshot = vi.fn();
// 粘贴复原能力用最小桩模拟 createXxxNodeWithData：按给定 id/x/y 建节点
globalThis.restoreNode = (nodeData) => {
  state.nodes.push({
    id: nodeData.id,
    type: nodeData.type,
    title: nodeData.title,
    x: nodeData.x,
    y: nodeData.y,
    data: nodeData.data
  });
};

function resetState() {
  Object.assign(state, {
    nodes: [],
    groups: [],
    nextGroupId: 1,
    nextNodeId: 10,
    selectedNodeIds: [],
    selectedGroupId: null,
    clipboard: null,
    lastMouseWorldPos: null,
    connections: [],
    imageConnections: [],
    firstFrameConnections: [],
    videoConnections: [],
    referenceConnections: [],
    audioConnections: [],
    nextConnId: 1,
    nextImgConnId: 1,
    nextFirstFrameConnId: 1,
    nextVideoConnId: 1,
    nextReferenceConnId: 1,
    nextAudioConnId: 1
  });
}

function loadScript(relativePath) {
  (0, eval)(readSource(relativePath));
}

if (typeof globalThis.createGroupFromNodes !== 'function') {
  loadScript('web/js/canvas_groups.js');
}
if (typeof globalThis.copySelectedNodes !== 'function') {
  loadScript('web/js/canvas_clipboard.js');
}
loadScript('web/js/canvas_context_menu.js');

function addNode(id, type, x, y, w, h, data) {
  const node = { id, type, title: `node${id}`, x, y, data: data || {} };
  if (w) node._w = w;
  if (h) node._h = h;
  state.nodes.push(node);
  return node;
}

beforeEach(() => {
  resetState();
  canvasHost.innerHTML = '';
  containerHost.innerHTML = '';
  vi.clearAllMocks();
});

// ─── 分组行为层 ───────────────────────────────────────────────

describe('canvas_groups 编组与成员归属', () => {
  it('编组按成员包围盒+留白计算组框，并创建组框 DOM', () => {
    addNode(1, 'image', 100, 100, 300, 200);
    addNode(2, 'text', 500, 100, 300, 200);

    const group = createGroupFromNodes([1, 2]);

    expect(group.id).toBe(1);
    expect(group.nodeIds).toEqual([1, 2]);
    // minX=100,minY=100,maxX=800,maxY=300 → padding 28
    expect(group.x).toBe(72);
    expect(group.y).toBe(72);
    expect(group.w).toBe(756);
    expect(group.h).toBe(256);

    const el = canvasHost.querySelector('.node-group[data-group-id="1"]');
    expect(el).not.toBeNull();
    expect(el.style.width).toBe('756px');
    expect(el.querySelector('.node-group-title').textContent).toBe('分组 1');
  });

  it('节点中心拖入组框自动加入，拖出自动移出', () => {
    addNode(1, 'image', 100, 100, 300, 200);   // 中心 (250,200)
    addNode(2, 'text', 500, 100, 300, 200);    // 中心 (650,200)
    createGroupFromNodes([1]);

    // n2 中心 (650,200) 在组外 → 无变化
    updateNodeGroupMembership(2);
    expect(findGroupById(1).nodeIds).toEqual([1]);

    // n2 拖到中心 (350,200) → 落入组内
    const n2 = state.nodes.find(n => n.id === 2);
    n2.x = 200;
    updateNodeGroupMembership(2);
    expect(findGroupById(1).nodeIds).toEqual([1, 2]);
    // 包围盒随成员扩张：maxX=500 → w=456
    expect(findGroupById(1).w).toBe(456);

    // 拖回中心 (650,200) → 移出
    n2.x = 500;
    updateNodeGroupMembership(2);
    expect(findGroupById(1).nodeIds).toEqual([1]);
    expect(findGroupById(1).w).toBe(356);
  });

  it('组内成员在框内任意拖动不脱离；移出框边界才脱离（BUG 回归）', () => {
    addNode(1, 'image', 100, 100, 300, 200);   // 中心 (250,200)
    addNode(2, 'text', 500, 100, 300, 200);    // 中心 (650,200)
    const group = createGroupFromNodes([1, 2]);
    // 成员包围盒 100..800 × 100..300，加 padding 后框 = 72..828 × 72..328
    const frame = { ...group };

    // 模拟拖动节点 2：mousemove 期间框必须保持静止（不跟随扩张）
    const n2 = state.nodes.find(n => n.id === 2);
    n2.x = 600; n2.y = 200; // 中心 (750,300)，仍在框内（框右边界 828）
    updateGroupFramesDuringDrag({ nodeId: 2, groupId: null, nodePositions: {} }, 100, 100);
    expect(group.x).toBe(frame.x);
    expect(group.y).toBe(frame.y);
    expect(group.w).toBe(frame.w);
    expect(group.h).toBe(frame.h);

    // mouseup：节点 2 中心在框内 → 不脱离（即使远离节点 1，框也不再紧贴成员）
    expect(updateNodeGroupMembership(2)).toBe(false);
    expect(group.nodeIds).toEqual([1, 2]);

    // 拖出框边界（中心在框右侧外）→ 脱离，框收缩回节点 1 的包围
    n2.x = 900; n2.y = 100; // 中心 (1050,200)，超出框右边界 828
    expect(updateNodeGroupMembership(2)).toBe(true);
    expect(group.nodeIds).toEqual([1]);
    expect(group.w).toBe(356);
  });

  it('整组拖动时组框跟随成员平移，成员归属不变', () => {
    addNode(1, 'image', 100, 100, 300, 200);
    addNode(2, 'text', 500, 100, 300, 200);
    const group = createGroupFromNodes([1, 2]);
    // events.js 的整组拖动 mousemove 分支会平移所有成员，这里模拟平移后的状态
    state.nodes.find(n => n.id === 1).x += 250;
    state.nodes.find(n => n.id === 1).y += 120;
    state.nodes.find(n => n.id === 2).x += 250;
    state.nodes.find(n => n.id === 2).y += 120;
    updateGroupFramesDuringDrag({ groupId: group.id, nodePositions: { 1: { x: 350, y: 220 }, 2: { x: 750, y: 220 } } }, 250, 120);
    // 框被重算到成员新位置的包围盒（原框 72,72 → 平移 +250,+120）
    expect(group.x).toBe(72 + 250);
    expect(group.y).toBe(72 + 120);
    expect(group.nodeIds).toEqual([1, 2]);
  });

  it('重叠组框按面积最小者归属', () => {
    addNode(1, 'image', 100, 100, 300, 200); // 中心 (250,200)
    // 大组：覆盖 (250,200)
    createGroupFromNodes([], { x: 0, y: 0 });
    const big = findGroupById(1);
    big.w = 600; big.h = 600;
    // 小组：同样覆盖 (250,200) 但面积更小
    createGroupFromNodes([], { x: 100, y: 100 });
    const small = findGroupById(2);
    small.w = 300; small.h = 300;

    updateNodeGroupMembership(1);
    expect(small.nodeIds).toEqual([1]);
    expect(big.nodeIds).toEqual([]);
  });

  it('解散分组保留节点；删除节点自动清理归属', () => {
    addNode(1, 'image', 100, 100);
    addNode(2, 'text', 500, 100);
    createGroupFromNodes([1, 2]);

    expect(dissolveGroup(1)).toBe(true);
    expect(state.groups).toEqual([]);
    expect(canvasHost.querySelector('.node-group')).toBeNull();
    // 节点不受影响
    expect(state.nodes.length).toBe(2);
    expect(safeAutoSave).toHaveBeenCalled();

    // 组内删除节点：归属被清理，空组保留原 bounds
    createGroupFromNodes([1, 2]);
    removeNodeIdFromGroups(2, { skipSave: true });
    expect(findGroupById(2).nodeIds).toEqual([1]);
    removeNodeIdFromGroups(1, { skipSave: true });
    expect(findGroupById(2).nodeIds).toEqual([]);
    // 空组保留用户放置的框（不塌缩）
    expect(findGroupById(2).w).toBeGreaterThan(0);
  });

  it('restoreGroups 过滤陈旧成员并重算包围盒，恢复 nextGroupId', () => {
    addNode(1, 'image', 100, 100, 300, 200);
    restoreGroups([
      { id: 5, title: '陈旧组', x: 10, y: 20, w: 100, h: 100, nodeIds: [999] },
      { id: 3, title: '有效组', x: 0, y: 0, w: 0, h: 0, nodeIds: [1] }
    ], 2);

    expect(state.groups.length).toBe(2);
    // 陈旧成员被过滤，空组保留落库的 bounds
    expect(findGroupById(5).nodeIds).toEqual([]);
    expect(findGroupById(5).x).toBe(10);
    // 有效组重算包围盒
    expect(findGroupById(3).x).toBe(72);
    expect(findGroupById(3).w).toBe(356);
    // nextGroupId 用传入值（虽然小于 max(id)+1 时以传入为准的语义由调用方保证）
    expect(state.nextGroupId).toBe(2);
  });

  it('组选中与节点选中互斥', () => {
    addNode(1, 'image', 100, 100);
    addNode(2, 'text', 500, 100);
    createGroupFromNodes([1, 2]);

    selectGroup(1);
    expect(state.selectedGroupId).toBe(1);
    expect(clearSelection).toHaveBeenCalled();
    expect(canvasHost.querySelector('.node-group.selected')).not.toBeNull();

    deselectGroup();
    expect(state.selectedGroupId).toBeNull();
    expect(canvasHost.querySelector('.node-group.selected')).toBeNull();
  });
});

// ─── 剪贴板行为层 ──────────────────────────────────────────────

describe('canvas_clipboard 复制粘贴', () => {
  it('复制过滤分镜/分镜组/剧本节点，只收集选中集内部连线', () => {
    addNode(1, 'image', 100, 100, 300, 200, { url: 'http://a', uploading: true });
    addNode(2, 'text', 500, 100, 300, 200, { content: 'hi' });
    addNode(3, 'shot_frame', 900, 100, 300, 200, { shotId: 's1' });
    state.connections.push({ id: 1, from: 1, to: 2 });          // 内部连线 → 保留
    state.imageConnections.push({ id: 2, from: 1, to: 3, portType: 'start' }); // 跨排除节点 → 丢弃

    state.selectedNodeIds = [1, 2, 3];
    expect(copySelectedNodes()).toBe(true);

    expect(state.clipboard.nodes.length).toBe(2);
    expect(state.clipboard.nodes.map(n => n.type)).toEqual(['image', 'text']);
    expect(state.clipboard.connections.length).toBe(1);
    expect(state.clipboard.connections[0].array).toBe('connections');
  });

  it('选中全是排除类型时拒绝复制', () => {
    addNode(1, 'script', 100, 100);
    state.selectedNodeIds = [1];
    expect(copySelectedNodes()).toBe(false);
    expect(state.clipboard).toBeNull();
    expect(showToast).toHaveBeenCalled();
  });

  it('粘贴分配新 id、按锚点保持相对布局、重映射连线并净化运行态字段', () => {
    addNode(1, 'image', 100, 100, 300, 200, { url: 'http://a', uploading: true });
    addNode(2, 'text', 500, 200, 300, 200, { content: 'hi' });
    // 与生产一致：连线 id 走计数器
    state.connections.push({ id: state.nextConnId++, from: 1, to: 2 });
    state.selectedNodeIds = [1, 2];
    copySelectedNodes();

    state.lastMouseWorldPos = { x: 1000, y: 500 };
    const newIds = pasteClipboard();

    expect(newIds.length).toBe(2);
    expect(newIds).toEqual([10, 11]);  // nextNodeId 从 10 起
    // 包围盒 minX=100,minY=100 → 锚点平移 (900,400)
    const [n1, n2] = newIds.map(id => state.nodes.find(n => n.id === id));
    expect(n1.x).toBe(1000);
    expect(n1.y).toBe(500);
    expect(n2.x).toBe(1400);
    expect(n2.y).toBe(600);
    // 运行态字段被净化
    expect(n1.data.uploading).toBe(false);
    // 连线重映射
    expect(state.connections.length).toBe(2);
    const newConn = state.connections[1];
    expect(newConn.from).toBe(n1.id);
    expect(newConn.to).toBe(n2.id);
    expect(newConn.id).toBe(2);
    expect(state.nextConnId).toBe(3);
    // 粘贴后选中新节点，且落了快照与保存
    expect(setMultipleSelected).toHaveBeenCalledWith(newIds);
    expect(captureHistorySnapshot).toHaveBeenCalled();
    expect(safeAutoSave).toHaveBeenCalled();
  });

  it('连续粘贴向右下错开 30px', () => {
    addNode(1, 'image', 0, 0, 300, 200, {});
    state.selectedNodeIds = [1];
    copySelectedNodes();
    state.lastMouseWorldPos = { x: 500, y: 500 };

    const first = pasteClipboard();
    const second = pasteClipboard();
    const n1 = state.nodes.find(n => n.id === first[0]);
    const n2 = state.nodes.find(n => n.id === second[0]);
    expect(n2.x).toBe(n1.x + 30);
    expect(n2.y).toBe(n1.y + 30);
  });

  it('再制在原位置右下 30px，不叠加连续粘贴偏移', () => {
    addNode(1, 'image', 200, 200, 300, 200, {});
    addNode(2, 'audio', 600, 200, 300, 200, {});
    state.connections.push({ id: 1, from: 1, to: 2 });
    state.selectedNodeIds = [1, 2];
    copySelectedNodes();
    // 模拟已经连续粘贴过多次
    state.clipboard.pasteCount = 5;
    // 先粘贴一次制造偏移计数（再制内部会归零）
    const dupIds = duplicateSelectedNodes();
    expect(dupIds.length).toBe(2);
    const orig = state.nodes.find(n => n.id === 1);
    const copy = state.nodes.find(n => n.id === dupIds[0]);
    // 再制锚点 = 原包围盒 + 30，不受 pasteCount=5 影响
    expect(copy.x).toBe(orig.x + 30);
    expect(copy.y).toBe(orig.y + 30);
    // 再制同样重建内部连线
    const lastConn = state.connections[state.connections.length - 1];
    expect(lastConn.from).toBe(dupIds[0]);
    expect(lastConn.to).toBe(dupIds[1]);
  });
});

// ─── 右键菜单行为层 ────────────────────────────────────────────

describe('canvas_context_menu 右键菜单', () => {
  function contextMenuEl() {
    return document.querySelector('.canvas-context-menu');
  }

  it('右键画布弹出菜单并按上下文启用禁用', () => {
    containerHost.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: 50, clientY: 60
    }));
    const menu = contextMenuEl();
    expect(menu).not.toBeNull();
    expect(menu.classList.contains('show')).toBe(true);

    // 无选中：复制/删除禁用，粘贴禁用（剪贴板空）
    expect(menu.querySelector('[data-action="copy"]').classList.contains('disabled')).toBe(true);
    expect(menu.querySelector('[data-action="paste"]').classList.contains('disabled')).toBe(true);
    expect(menu.querySelector('[data-action="delete"]').classList.contains('disabled')).toBe(true);
  });

  it('右键节点切换单选，菜单点击复制生效', () => {
    addNode(1, 'image', 100, 100);
    // canvas_context_menu 右键未选中节点时会调用全局 setSelected（canvas.js 提供）
    globalThis.setSelected = vi.fn((id) => { state.selectedNodeIds = [id]; });
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node';
    nodeEl.dataset.nodeId = '1';
    containerHost.appendChild(nodeEl);

    nodeEl.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: 30, clientY: 40
    }));
    // 右键未选中节点 → 自动单选（不走 setMultipleSelected）
    expect(setSelected).toHaveBeenCalledWith(1);
    expect(state.selectedNodeIds).toEqual([1]);
    const menu = contextMenuEl();
    expect(menu.querySelector('[data-action="copy"]').classList.contains('disabled')).toBe(false);

    menu.querySelector('[data-action="copy"]').click();
    expect(state.clipboard).not.toBeNull();
    expect(state.clipboard.nodes.length).toBe(1);
    expect(menu.classList.contains('show')).toBe(false);
  });
});

// ─── 接线层：存量文件与新功能的集成点 ─────────────────────────────

describe('分组与复制的持久化/交互接线', () => {
  const workflowJs = readSource('web/js/workflow.js');
  const eventsJs = readSource('web/js/events.js');
  const canvasJs = readSource('web/js/canvas.js');
  const layoutJs = readSource('web/js/workflow_layout.js');
  const html = readSource('web/video_workflow.html');

  it('serializeWorkflow 输出 groups/nextGroupId', () => {
    expect(workflowJs).toContain('groups: state.groups.map(g => ({');
    expect(workflowJs).toContain('nextGroupId: state.nextGroupId');
  });

  it('restoreWorkflow 恢复分组（在节点恢复之后）', () => {
    const restorePos = workflowJs.indexOf('restoreGroups(data.groups');
    const nodeRestorePos = workflowJs.indexOf('restoreNode(nodeData)');
    expect(restorePos).toBeGreaterThan(-1);
    expect(restorePos).toBeGreaterThan(nodeRestorePos);
  });

  it('events.js 注册复制/粘贴/再制/编组快捷键与分组菜单入口', () => {
    expect(eventsJs).toContain("copySelectedNodes()");
    expect(eventsJs).toContain("pasteClipboard()");
    expect(eventsJs).toContain("duplicateSelectedNodes()");
    expect(eventsJs).toContain("groupSelectedNodes()");
    expect(eventsJs).toContain("ungroupSelection()");
    expect(eventsJs).toContain("menuAddGroup");
    expect(eventsJs).toContain('updateNodeGroupMembership(nodeId)');
  });

  it('canvas.js 删除节点/放置结束接入分组', () => {
    expect(canvasJs).toContain('removeNodeIdFromGroups(id');
    expect(canvasJs).toContain('updateNodeGroupMembership(placedNodeId)');
  });

  it('自动排列后重算组框；HTML 引入三个新脚本与分组菜单项', () => {
    expect(layoutJs).toContain('recalcAllGroupsBounds()');
    expect(html).toContain('canvas_groups.js');
    expect(html).toContain('canvas_clipboard.js');
    expect(html).toContain('canvas_context_menu.js');
    expect(html).toContain('id="menuAddGroup"');
  });

  it('快捷键说明按钮与弹窗已接线', () => {
    expect(html).toContain('id="shortcutHelpBtn"');
    expect(html).toContain('id="shortcutHelpModal"');
    expect(html).toContain('canvas_shortcuts.js');
    const shortcutsJs = readSource('web/js/canvas_shortcuts.js');
    // 按钮 → 打开弹窗；Esc / 遮罩 / 关闭按钮均可关闭
    expect(shortcutsJs).toContain("getElementById('shortcutHelpBtn')");
    expect(shortcutsJs).toContain("classList.add('show')");
    expect(shortcutsJs).toContain("'Escape'");
    // 弹窗内覆盖全部画布快捷键条目
    const modalHtml = html.slice(html.indexOf('id="shortcutHelpModal"'), html.indexOf('id="saveConflictModal"'));
    for (const key of ['Ctrl</kbd><span class="plus">+</span><kbd>C', 'Ctrl</kbd><span class="plus">+</span><kbd>V', 'Ctrl</kbd><span class="plus">+</span><kbd>D', 'Ctrl</kbd><span class="plus">+</span><kbd>Z', 'Ctrl</kbd><span class="plus">+</span><kbd>G', 'Shift</kbd><span class="plus">+</span><kbd>G', 'Delete']) {
      expect(modalHtml).toContain(key);
    }
    expect(modalHtml).toContain('shortcut-combo');
    expect(modalHtml).toContain('shortcut-or');
    const css = readSource('web/css/video_workflow.css');
    const helpCss = css.slice(css.indexOf('画布快捷键说明弹窗'));
    expect(helpCss).toContain('background: var(--surface)');
    expect(helpCss).toContain('html.theme-dark #shortcutHelpModal .shortcut-keys kbd');
    expect(helpCss).not.toContain('background: #ffffff');
  });
});
