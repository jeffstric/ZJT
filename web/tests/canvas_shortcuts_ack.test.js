/**
 * 快捷键弹窗自动弹出策略：
 * - 用户尚未确认过（未点过「滚轮上下平移 / 滚轮缩放画布」，也从未关闭过弹窗）→ 进入画布自动弹。
 * - 点选过任一模式按钮 → localStorage 记 canvasWheelModeAcked=1，后续进入不再自动弹。
 * - 任何形式的关闭（× / Esc / 遮罩）也视为已确认 → 记 canvasWheelModeAcked=1，下次进入不再自动弹。
 * - 工具栏「快捷键」按钮始终可手动打开。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';

const SOURCE = fs.readFileSync(
  path.resolve(import.meta.dirname, '../js/canvas_shortcuts.js'),
  'utf8'
);

function buildDom() {
  document.body.innerHTML = [
    '<button id="shortcutHelpBtn">快捷键</button>',
    '<div class="modal" id="shortcutHelpModal" aria-hidden="true">',
    '  <button id="shortcutHelpModalClose">×</button>',
    '  <div id="shortcutWheelModeHint"></div>',
    '  <button id="shortcutWheelModePan">滚轮上下平移</button>',
    '  <button id="shortcutWheelModeZoom">滚轮缩放画布</button>',
    '  <span id="shortcutWheelZoomKeys"></span>',
    '  <span id="shortcutWheelPanKeys"></span>',
    '</div>',
  ].join('');
  return document.getElementById('shortcutHelpModal');
}

function loadShortcuts() {
  // jsdom 下 document.readyState 为 complete，脚本加载即执行 init
  (0, eval)(SOURCE);
}

function modalShown(modal) {
  return modal.classList.contains('show');
}

describe('快捷键弹窗：未确认过自动弹，确认过不再弹', () => {
  beforeEach(() => {
    localStorage.clear();
    buildDom();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('从未选择过：进入画布自动弹出', () => {
    const modal = document.getElementById('shortcutHelpModal');
    loadShortcuts();
    expect(modalShown(modal)).toBe(true);
  });

  it('点选「滚轮缩放画布」后：本次关闭，再次进入不再自动弹', () => {
    const modal = document.getElementById('shortcutHelpModal');
    loadShortcuts();
    document.getElementById('shortcutWheelModeZoom').click();
    expect(localStorage.getItem('canvasWheelModeAcked')).toBe('1');
    expect(localStorage.getItem('canvasWheelMode')).toBe('zoom');
    // 模拟再次进入画布：重建 DOM 重新 init
    buildDom();
    const modal2 = document.getElementById('shortcutHelpModal');
    loadShortcuts();
    expect(modalShown(modal2)).toBe(false);
  });

  it('点选「滚轮上下平移」（保持默认）也算确认', () => {
    loadShortcuts();
    document.getElementById('shortcutWheelModePan').click();
    expect(localStorage.getItem('canvasWheelModeAcked')).toBe('1');
    expect(localStorage.getItem('canvasWheelMode')).toBe('pan');
    buildDom();
    loadShortcuts();
    expect(modalShown(document.getElementById('shortcutHelpModal'))).toBe(false);
  });

  it('关闭弹窗（Esc / 遮罩 / ×）也算确认，下次进入不再自动弹', () => {
    const modal = document.getElementById('shortcutHelpModal');
    loadShortcuts();
    expect(modalShown(modal)).toBe(true);
    // Esc 关闭
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(modalShown(modal)).toBe(false);
    expect(localStorage.getItem('canvasWheelModeAcked')).toBe('1');
    // 再次进入不再自动弹
    buildDom();
    loadShortcuts();
    expect(modalShown(document.getElementById('shortcutHelpModal'))).toBe(false);
  });

  it('点 × 关闭也算确认，下次进入不再自动弹', () => {
    const modal = document.getElementById('shortcutHelpModal');
    loadShortcuts();
    expect(modalShown(modal)).toBe(true);
    document.getElementById('shortcutHelpModalClose').click();
    expect(modalShown(modal)).toBe(false);
    expect(localStorage.getItem('canvasWheelModeAcked')).toBe('1');
    buildDom();
    loadShortcuts();
    expect(modalShown(document.getElementById('shortcutHelpModal'))).toBe(false);
  });

  it('点遮罩空白处关闭也算确认，下次进入不再自动弹', () => {
    const modal = document.getElementById('shortcutHelpModal');
    loadShortcuts();
    expect(modalShown(modal)).toBe(true);
    // 模拟点击遮罩本身（target === modal）
    modal.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(modalShown(modal)).toBe(false);
    expect(localStorage.getItem('canvasWheelModeAcked')).toBe('1');
    buildDom();
    loadShortcuts();
    expect(modalShown(document.getElementById('shortcutHelpModal'))).toBe(false);
  });

  it('确认过后：工具栏「快捷键」按钮仍可手动打开', () => {
    localStorage.setItem('canvasWheelModeAcked', '1');
    localStorage.setItem('canvasWheelMode', 'zoom');
    const modal = buildDom();
    loadShortcuts();
    expect(modalShown(modal)).toBe(false);
    document.getElementById('shortcutHelpBtn').click();
    expect(modalShown(modal)).toBe(true);
    // 打开时按钮选中态与保存的模式一致
    expect(document.getElementById('shortcutWheelModeZoom').classList.contains('is-selected')).toBe(true);
  });
});
