/**
 * 导演台「重置视角」回归测试。
 *
 * 背景 BUG：点击视口左上角「重置视角」后，鼠标无法再控制视角，画面定死。
 * 根因：startLoop 渲染循环在循环外缓存了视角对象引用（var o = this.orbit），
 * 而重置按钮的处理函数整体替换 self.orbit = {...}，导致渲染循环继续渲染
 * 旧对象（重置不生效、画面冻结），鼠标拖拽修改的是新对象（输入全部无效）。
 *
 * 修复约定：重置视角必须原地修改 orbit 字段（theta/phi/radius/target.set），
 * 禁止整体重新赋值 self.orbit = {...}。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');

/** 提取「重置视角」按钮 click 处理函数体内的源码片段 */
function resetHandlerBlock() {
  const marker = "this.on(this.$('dsResetViewBtn'), 'click', function () {";
  const idx = src.indexOf(marker);
  expect(idx).toBeGreaterThan(-1);
  return src.slice(idx, idx + marker.length + 500);
}

describe('导演台：重置视角（接线层源码断言）', () => {
  it('渲染循环缓存 orbit 引用（本测试所保护的契约）', () => {
    expect(src).toContain('var o = this.orbit;');
  });

  it('重置视角原地修改 orbit，不整体替换对象', () => {
    const block = resetHandlerBlock();
    expect(block).not.toContain('self.orbit =');
    expect(block).not.toContain('self.orbit=');
    expect(block).toContain('self.orbit.theta = 0.55;');
    expect(block).toContain('self.orbit.phi = 1.02;');
    expect(block).toContain('self.orbit.radius = 8.5;');
    expect(block).toContain('self.orbit.target.set(0, 1.0, 0);');
  });
});
