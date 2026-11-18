/**
 * 回归（2026-11-13）：营销页模型列表未按驱动可用状态过滤——环境未配置火山引擎时，
 * Seedream/Seedance 等模型仍显示在模型列表中（workflow/nodes/image_to_video 页面早已通过
 * TaskConfig.filterAvailableModelOptions + /api/computing-power-config 的 driver_status 过滤）。
 *
 * 契约：
 * - initTaskConfig 拉取 /api/computing-power-config 的 driver_status（失败保持 {}，视为全部可用）
 * - 文生图/图片编辑/文生视频/图生视频四个模型列表均经过 filterAvailableModelOptions 过滤
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const require_ = createRequire(import.meta.url);
const TaskConfig = require_('../js/task_config.js');

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

function extractInitSlice() {
    const start = source.indexOf('async function initTaskConfig()');
    expect(start, 'initTaskConfig 应存在').toBeGreaterThan(-1);
    const end = source.indexOf('function loadDefaultModels()', start);
    expect(end, 'loadDefaultModels 应存在').toBeGreaterThan(start);
    return source.slice(start, end);
}

const initSlice = extractInitSlice();

describe('marketing_agent initTaskConfig 驱动状态过滤', () => {
    it('拉取 /api/computing-power-config 的 driver_status', () => {
        expect(initSlice).toContain('/api/computing-power-config');
        expect(initSlice).toContain('driver_status');
    });

    it('四个模型分类均经过 availableOpts（filterAvailableModelOptions）过滤', () => {
        for (const category of ['text_to_image', 'image_edit', 'text_to_video', 'image_to_video']) {
            expect(
                initSlice,
                `${category} 模型列表应经过驱动可用性过滤`
            ).toMatch(new RegExp(`availableOpts\\(\\s*window\\.TaskConfig\\.getModelOptionsForCategory\\('${category}'\\)\\s*\\)`));
        }
    });

    it('availableOpts 委托给 TaskConfig.filterAvailableModelOptions，缺省时原样返回', () => {
        expect(initSlice).toMatch(/const availableOpts = \(opts\) => \(window\.TaskConfig\.filterAvailableModelOptions/);
    });
});

describe('TaskConfig.filterAvailableModelOptions（真实实现）', () => {
    const options = [
        { value: 'seedream-5.0', taskType: 16 },
        { value: 'gpt-image-2-edit', taskType: 26 },
        { value: 'minimax_h3_t2v', taskType: 45 },
        { value: 'seedance_2_5', taskType: 36 },
    ];

    it('无 driverStatus（加载失败）→ 全部保留，与旧行为一致', () => {
        expect(TaskConfig.filterAvailableModelOptions(options, {})).toHaveLength(4);
        expect(TaskConfig.filterAvailableModelOptions(options, null)).toHaveLength(4);
    });

    it('火山引擎驱动不可用 → Seedream/Seedance 被过滤，其余保留', () => {
        const driverStatus = {
            16: { available: false, missing_configs: ['Volcengine API Key'] },
            18: { available: false, missing_configs: ['Volcengine API Key'] },
            33: { available: false, missing_configs: ['Volcengine API Key'] },
            36: { available: false, missing_configs: ['Volcengine API Key'] },
        };
        const filtered = TaskConfig.filterAvailableModelOptions(options, driverStatus);
        expect(filtered.map(o => o.value)).toEqual(['gpt-image-2-edit', 'minimax_h3_t2v']);
    });

    it('状态条目缺失时该模型视为可用', () => {
        const driverStatus = { 16: { available: false } };
        const filtered = TaskConfig.filterAvailableModelOptions(options, driverStatus);
        expect(filtered.map(o => o.value)).toEqual(['gpt-image-2-edit', 'minimax_h3_t2v', 'seedance_2_5']);
    });
});
