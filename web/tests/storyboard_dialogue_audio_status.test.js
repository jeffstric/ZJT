/**
 * 对话行配音状态展示单测：
 * - isAudioRunningStatus / isAudioFailedStatus 与后端 AIAudioStatus 对齐
 * - renderDialoguePanel / renderDialogueRowOuter 两处行模板必须使用同一 renderDialogueAudioBlock，
 *   保证轮询局部更新与全量渲染的展示一致（进度条 / 旧配音标识 / 失败提示）
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { isAudioRunningStatus, isAudioFailedStatus } from '../js/storyboard/utils.js';

describe('isAudioRunningStatus', () => {
    it('识别后端 AIAudioStatus 数值状态（0=PENDING 1=PROCESSING）', () => {
        expect(isAudioRunningStatus(0)).toBe(true);
        expect(isAudioRunningStatus(1)).toBe(true);
        expect(isAudioRunningStatus(2)).toBe(false);  // COMPLETED
        expect(isAudioRunningStatus(-1)).toBe(false); // FAILED
        expect(isAudioRunningStatus(null)).toBe(false);
        expect(isAudioRunningStatus(undefined)).toBe(false);
    });

    it('兼容字符串状态', () => {
        expect(isAudioRunningStatus('pending')).toBe(true);
        expect(isAudioRunningStatus('PROCESSING')).toBe(true);
        expect(isAudioRunningStatus('0')).toBe(true);
        expect(isAudioRunningStatus('completed')).toBe(false);
    });
});

describe('isAudioFailedStatus', () => {
    it('FAILED = -1，兼容字符串态', () => {
        expect(isAudioFailedStatus(-1)).toBe(true);
        expect(isAudioFailedStatus('-1')).toBe(true);
        expect(isAudioFailedStatus('failed')).toBe(true);
        expect(isAudioFailedStatus(0)).toBe(false);
        expect(isAudioFailedStatus(2)).toBe(false);
        expect(isAudioFailedStatus(null)).toBe(false);
    });
});

describe('对话行配音区块渲染', () => {
    const root = path.resolve(import.meta.dirname, '../..');
    const renderSource = fs.readFileSync(path.join(root, 'web/js/storyboard/render.js'), 'utf8');

    it('两处行模板都使用 renderDialogueAudioBlock', () => {
        const matches = renderSource.match(/\$\{renderDialogueAudioBlock\(d\)\}/g) || [];
        expect(matches.length).toBe(2);
    });

    it('两处行模板都使用 renderGenerateVoiceoverBtn（生成中禁用）', () => {
        const matches = renderSource.match(/\$\{renderGenerateVoiceoverBtn\(d\)\}/g) || [];
        expect(matches.length).toBe(2);
    });

    it('生成中展示不确定进度条，旧配音有降级样式与提示', () => {
        expect(renderSource).toContain('dialogue-audio-progress-track');
        expect(renderSource).toContain('is-stale');
        expect(renderSource).toContain('dialogue-audio-note stale');
        expect(renderSource).toContain('dialogue-audio-note failed');
    });
});
