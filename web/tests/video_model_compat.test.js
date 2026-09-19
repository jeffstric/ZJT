/**
 * 视频模型与图片模式兼容性迁移测试（video_model_compat.js + workflow.js 两处接入）。
 *
 * 背景 BUG：分镜/分镜组节点保存了首尾帧专属模型（minimax_h3），TaskConfig 异步加载
 * 完成后的补偿刷新（refreshShotFrameNodesModels / refreshShotGroupNodesModels）把
 * 不支持当前模式的模型原样塞回下拉保留，构造出 multi_reference + minimax_h3 非法组合，
 * 提交后后端 validate_model 拒绝：
 *   {"code":"MODEL_INPUT_UNSUPPORTED","message":"模型 MiniMax H3 不支持多参考图输入"}
 * MiniMax H3 有两个任务条目：minimax_h3（首尾帧）与 minimax_h3_r2v（多参考），
 * 参考模式必须使用后者。
 */

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

function loadCompatModule() {
  const context = {};
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(readSource('web/js/video_model_compat.js'), context);
  return context;
}

const OPTIONS = [
  { value: 'minimax_h3', supportedImageModes: ['first_last_frame'] },
  { value: 'minimax_h3_r2v', supportedImageModes: ['multi_reference'] },
  { value: 'seedance_2_0', supportedImageModes: ['first_last_frame', 'multi_reference'] },
];

describe('resolveSavedVideoModelForMode 行为', () => {
  it('已知模型不支持当前模式 → 返回 null（调用方迁移），修复 minimax_h3 残留参考模式', () => {
    const m = loadCompatModule();
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'multi_reference', 'minimax_h3')).toBeNull();
    // 反向：多参考专属模型残留在首尾帧模式，同样迁移
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'first_last_frame', 'minimax_h3_r2v')).toBeNull();
  });

  it('已知模型支持当前模式 → 保留（含被驱动状态过滤但仍兼容的场景）', () => {
    const m = loadCompatModule();
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'multi_reference', 'seedance_2_0')).toBe('seedance_2_0');
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'first_last_frame', 'minimax_h3')).toBe('minimax_h3');
    // 空 options 时无从判定模式兼容性，视为未知模型保留
    expect(m.resolveSavedVideoModelForMode([], 'multi_reference', 'seedance_2_0')).toBe('seedance_2_0');
  });

  it('未知模型（不在配置中）→ 保留原值（沿用历史行为）；空值 → null', () => {
    const m = loadCompatModule();
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'multi_reference', 'some_removed_model')).toBe('some_removed_model');
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'multi_reference', '')).toBeNull();
    expect(m.resolveSavedVideoModelForMode(OPTIONS, 'multi_reference', null)).toBeNull();
  });

  it('兼容 snake_case 字段名（supported_image_modes）', () => {
    const m = loadCompatModule();
    const opts = [{ value: 'x', supported_image_modes: ['multi_reference'] }];
    expect(m.resolveSavedVideoModelForMode(opts, 'multi_reference', 'x')).toBe('x');
    expect(m.resolveSavedVideoModelForMode(opts, 'first_last_frame', 'x')).toBeNull();
  });
});

describe('workflow.js 两处补偿刷新接入', () => {
  const workflowJs = readSource('web/js/workflow.js');

  function functionSegment(name) {
    const start = workflowJs.indexOf(`function ${name}`);
    expect(start).toBeGreaterThan(-1);
    return workflowJs.slice(start, start + 6000);
  }

  it('分镜节点与分镜组节点的刷新都不再无条件保留已保存模型', () => {
    for (const name of ['refreshShotFrameNodesModels', 'refreshShotGroupNodesModels']) {
      const segment = functionSegment(name);
      expect(segment).toContain('resolveSavedVideoModelForMode(filteredByDriver.length ? filteredByDriver : allVideoOptions, mode,');
      // 保留分支必须以 keepSaved 判定为前提（不再直接用 node.data.videoModel / currentVideoModel）
      expect(segment).toContain('if (keepSaved && typeof ensureSelectHasSavedOption === \'function\')');
      // 迁移兜底仍在
      expect(segment).toContain('node.data.videoModel = videoOptions[0].value');
    }
  });

  it('video_workflow.html 引入 video_model_compat.js', () => {
    expect(readSource('web/video_workflow.html')).toContain('/js/video_model_compat.js');
  });
});
