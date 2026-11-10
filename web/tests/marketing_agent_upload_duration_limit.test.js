/**
 * 营销 Agent 上传素材时长上限跟随所选模型（15s 写死 → min(平台配置, 模型最大时长)）。
 *
 * 契约：
 * - computeUploadDurationLimit(modelConfig, serverCap)：
 *   平台配置上限 与 所选模型最大生成时长 取小；未选模型/无时长档位 → 平台上限
 * - 上传校验（视频/音频 ×3 路径）、processVideoFile 截断统一读 effectiveUploadDurationLimit，
 *   不再直接以 maxVideoDurationSeconds 做时长比较（该值仅作平台级上限传入）
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

// 切片提取纯函数（与 canvas_groups_clipboard 等测试的切片风格一致）
function extractUploadLimitFn() {
    const start = source.indexOf('function computeUploadDurationLimit(');
    expect(start, 'computeUploadDurationLimit 应存在于 marketing_agent.js').toBeGreaterThanOrEqual(0);
    const end = source.indexOf('const effectiveUploadDurationLimit', start);
    expect(end, 'effectiveUploadDurationLimit 定义应紧跟纯函数之后').toBeGreaterThan(start);
    const block = source.slice(start, end);
    return new Function(`${block}\nreturn computeUploadDurationLimit;`)();
}

const computeUploadDurationLimit = extractUploadLimitFn();

// 与页面默认/配置对齐：平台级上限 30s（upload.max_video_duration_seconds）
const SERVER_CAP = 30;
const SEEDANCE_2_5 = { durations: [2, 3, 5, 8, 10, 15, 20, 25, 30] };
const SHORT_MODEL = { durations: [5, 10] };

describe('computeUploadDurationLimit', () => {
    it('seedance 2.5（最大 30s）：平台 30 → 30', () => {
        expect(computeUploadDurationLimit(SEEDANCE_2_5, SERVER_CAP)).toBe(30);
    });

    it('10s 模型：平台 30 → 10（取小）', () => {
        expect(computeUploadDurationLimit(SHORT_MODEL, SERVER_CAP)).toBe(10);
    });

    it('未选模型（null）：回落到平台上限', () => {
        expect(computeUploadDurationLimit(null, SERVER_CAP)).toBe(30);
    });

    it('模型无时长档位：回落到平台上限（不用 15s 兜底）', () => {
        expect(computeUploadDurationLimit({ durations: [] }, SERVER_CAP)).toBe(30);
        expect(computeUploadDurationLimit({}, SERVER_CAP)).toBe(30);
    });

    it('非数字档位被忽略', () => {
        expect(computeUploadDurationLimit({ durations: ['auto', 8, 15] }, SERVER_CAP)).toBe(15);
    });

    it('模型上限大于平台配置时以平台配置为准', () => {
        expect(computeUploadDurationLimit({ durations: [5, 10, 15, 30] }, 20)).toBe(20);
    });
});

describe('marketing_agent.js 使用点', () => {
    it('computed 以平台配置为上限、以当前模型配置为输入', () => {
        const def = source.slice(
            source.indexOf('const effectiveUploadDurationLimit'),
            source.indexOf('function resolveSelectedDurationForSubmission')
        );
        expect(def).toContain('computeUploadDurationLimit(getCurrentVideoModelConfig(), maxVideoDurationSeconds.value)');
    });

    it('视频/音频校验与 processVideoFile 截断均使用 effectiveUploadDurationLimit', () => {
        const usages = source.match(/effectiveUploadDurationLimit\.value/g) || [];
        // 8 个校验/截断块，每块 1~2 处引用（含错误消息 {dur}），共 16+ 处使用
        expect(usages.length).toBeGreaterThanOrEqual(16);
        for (const key of [
            'video_duration_limit_reached',
            'video_duration_limit_name_skipped',
            'audio_duration_limit_reached',
            'audio_duration_limit_name_skipped',
        ]) {
            const m = source.match(new RegExp(`window\\.t\\('${key}', \\{dur: ([A-Za-z]+)\\.value[^)]*\\)`));
            expect(m, `错误消息 ${key} 应使用动态上限变量`).not.toBeNull();
            expect(m[1], `${key} 的 {dur} 不应再写死 maxVideoDurationSeconds`).toBe('effectiveUploadDurationLimit');
        }
        // processVideoFile 截断上限
        expect(source).toContain('const effectiveMaxDuration = maxDurationForThis || effectiveUploadDurationLimit.value;');
    });

    it('不再存在以 maxVideoDurationSeconds 直接做时长比较/赋值的残留', () => {
        expect(source).not.toMatch(/remainingDuration = maxVideoDurationSeconds\.value/);
        expect(source).not.toMatch(/let fileDuration = maxVideoDurationSeconds\.value/);
        expect(source).not.toMatch(/vidItem\.duration = maxDurationForThis \|\| maxVideoDurationSeconds\.value/);
    });

    it('导出 effectiveUploadDurationLimit 供模板/测试使用', () => {
        expect(source).toMatch(/^                effectiveUploadDurationLimit,$/m);
    });
});
