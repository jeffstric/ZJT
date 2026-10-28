/**
 * Safari 输入法组词确认 Enter：WebKit 使 isComposing=false 且 keyCode=229，
 * 只判断 isComposing 会把正在组词的内容当消息发出。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');

describe('发送快捷键拦截 Safari IME keyCode 229', () => {
  it('script_writer 组词确认 Enter 不发送', () => {
    const src = read('js/script_writer.js');
    expect(src).toContain('e.isComposing || e.keyCode === 229');
  });

  it('marketing_agent 组词确认 Enter 不发送', () => {
    const src = read('js/marketing_agent.js');
    expect(src).toContain('e.isComposing || e.keyCode === 229');
  });

  it('marketing_inspiration 组词确认 Enter 不发送', () => {
    const src = read('js/marketing_inspiration.js');
    expect(src).toContain('e.keyCode !== 229');
  });
});
