/**
 * 思考强度（effort）选择器的供应商覆盖一致性测试。
 *
 * 背景 BUG：effort 档位下拉的显示判定只认 volcengine/doubao。glm-5.3 / glm-5.3-flash
 * 接入 glmcn（智谱 BigModel）双供应商后，经 glmcn 条目选择 GLM 模型时强度选择器
 * 恒隐藏，thinking_effort 固定 medium（后端 GLM_REASONING_EFFORT_MAP 映射为 high），
 * 用户无法选 low/max。GLM-5.3 是"始终思考"模型，恰恰最需要强度选择。
 *
 * 三处判定必须保持一致（源码注释中互相引用）：
 * - web/js/script_writer.js          updateThinkingEffortVisibility
 * - web/js/script_node.js            isDoubaoEffortModelOption
 * - web/js/storyboard/state.js       isDoubaoEffort 元数据
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

describe('thinking effort selector covers glmcn GLM models', () => {
  it('script_writer 判定包含 glmcn 供应商与 glm- 模型前缀', () => {
    const src = readSource('web/js/script_writer.js');
    expect(src).toContain("vendorName === 'glmcn'");
    expect(src).toContain("modelValue.startsWith('glm-')");
  });

  it('script_node 判定包含 glmcn 供应商与 glm- 模型前缀', () => {
    const src = readSource('web/js/script_node.js');
    expect(src).toContain("vendorName === 'glmcn'");
    expect(src).toContain("modelValue.startsWith('glm-')");
  });

  it('storyboard state 判定包含 glmcn 供应商与 glm- 模型前缀', () => {
    const src = readSource('web/js/storyboard/state.js');
    expect(src).toContain("vendorName === 'glmcn'");
    expect(src).toContain("modelName.startsWith('glm-')");
  });

  it('volcengine 原有路径未被破坏（doubao 判定仍在）', () => {
    const writer = readSource('web/js/script_writer.js');
    const node = readSource('web/js/script_node.js');
    const state = readSource('web/js/storyboard/state.js');
    expect(writer).toContain("vendorName === 'volcengine'");
    expect(node).toContain("vendorName === 'volcengine'");
    expect(state).toContain("vendorName === 'volcengine'");
  });
});
