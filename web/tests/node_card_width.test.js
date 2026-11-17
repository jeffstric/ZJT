/**
 * 分镜帧宽度必须写死。
 * width:auto + flex:1（flex-basis:0%）+ min-width:0 在绝对定位下会 shrink-to-fit，
 * Edge 把不确定宽度的 0% 当成 0，故事板转出的分镜帧会塌到约 340px。
 * 剧本 / 分镜组 / 图生视频节点仍按内容收缩。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const css = fs.readFileSync(
  path.resolve(import.meta.dirname, '../css/video_workflow.css'),
  'utf8'
);

function ruleBody(selector) {
  const start = css.indexOf(selector + ' {');
  expect(start, selector).toBeGreaterThanOrEqual(0);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  return css.slice(open + 1, close);
}

describe('分镜节点固定宽度', () => {
  it('分镜帧写死 960px，不用 width:auto', () => {
    const selector = '.node:has(.script-node-body):has(.shot-frame-generate-btn)';
    const body = ruleBody(selector);
    expect(body).toContain('width: 960px');
    expect(body).not.toMatch(/width:\s*auto/);
    expect(css.indexOf(selector)).toBeGreaterThan(css.indexOf('.node:has(.script-node-body) {'));
  });

  it('剧本和分镜组仍按内容收缩', () => {
    const body = ruleBody('.node:has(.script-node-body)');
    expect(body).toMatch(/width:\s*auto/);
    expect(body).toContain('min-width: 340px');
    expect(body).toContain('max-width: 960px');
    expect(body).not.toMatch(/^\s*width:\s*960px/m);
  });

  it('图生视频节点仍按内容收缩', () => {
    const body = ruleBody('.node:has(.video-node-body)');
    expect(body).toMatch(/width:\s*auto/);
    expect(body).toContain('min-width: 280px');
    expect(body).toContain('max-width: 720px');
  });
});
