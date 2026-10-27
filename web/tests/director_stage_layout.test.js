/** 导演台视口浮层布局回归测试。 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const css = fs.readFileSync(path.join(root, 'web/css/director_stage.css'), 'utf8');

function ruleBlock(selector) {
  const start = css.indexOf(selector);
  expect(start).toBeGreaterThan(-1);
  const end = css.indexOf('}', start);
  expect(end).toBeGreaterThan(start);
  return css.slice(start, end + 1);
}

describe('导演台：底部对话条与浮层不重叠', () => {
  it('选中提示位于对话条上方，并限制长文本宽度', () => {
    const selection = ruleBlock('.ds-selection-tip {');
    const chat = ruleBlock('.ds-chatbar {');
    expect(selection).toContain('bottom: 52px');
    expect(selection).toContain('left: 12px');
    expect(selection).toContain('transform: none');
    expect(selection).toContain('max-width: min(58%, 500px)');
    expect(selection).toContain('text-overflow: ellipsis');
    expect(chat).toContain('bottom: 12px');
  });

  it('对话反馈位于选中提示的再上方', () => {
    const note = ruleBlock('.ds-chat-note {');
    const selection = ruleBlock('.ds-selection-tip {');
    expect(note).toContain('bottom: 92px');
    expect(selection).toContain('bottom: 52px');
  });
});
