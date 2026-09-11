import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

const extractFunctionBody = (source, signature) => {
    const match = source.match(new RegExp(`${signature} \\{[\\s\\S]*?\\n\\}`));
    return match ? match[0] : '';
};

describe('storyboard direct submit feedback (toast + optimistic candidate)', () => {
    const eventsSource = readSource('web/js/storyboard/events.js');
    const videoBody = extractFunctionBody(eventsSource, 'async function sendDirectVideo\\(current\\)');
    const imageBody = extractFunctionBody(eventsSource, 'async function sendDirectImage\\(current\\)');

    it('direct modes do not push chat bubbles (agent-panel logic stays in agent modes)', () => {
        expect(videoBody).not.toContain('pushAgentMessageForScene');
        expect(imageBody).not.toContain('pushAgentMessageForScene');
    });

    it('inserts an optimistic generating candidate immediately on submit', () => {
        expect(videoBody).toContain("insertOptimisticGeneratingCandidate(sceneId, 'videos')");
        expect(imageBody).toContain("insertOptimisticGeneratingCandidate(sceneId, 'images')");
    });

    it('adopts the real asset id on success and removes the optimistic card on failure', () => {
        expect(videoBody).toContain('adoptOptimisticCandidate(sceneId, \'videos\', optimisticId, result?.asset_id)');
        expect(videoBody).toContain("removeOptimisticCandidate(sceneId, 'videos', optimisticId)");
        expect(imageBody).toContain('adoptOptimisticCandidate(sceneId, \'images\', optimisticId, result?.asset_ids?.[0])');
        expect(imageBody).toContain("removeOptimisticCandidate(sceneId, 'images', optimisticId)");
    });

    it('shows a nearby submit toast instead of staying silent', () => {
        // showToast 为多行三元：对口型 / 无首帧按参考图直提 / 常规视频三种文案分支
        expect(videoBody).toMatch(/showToast\(\s*isDh\s*\?/);
        expect(videoBody).toContain("'对口型视频已提交，右侧候选区生成中'");
        expect(videoBody).toContain("'已按参考图提交视频，右侧候选区生成中'");
        expect(videoBody).toContain("'视频生成任务已提交，右侧候选区生成中'");
        expect(imageBody).toContain("showToast('生图任务已提交，右侧候选区生成中', 'info')");
    });

    it('keeps the running-scene re-submit toast guard', () => {
        const guard = 'showToast(\'当前分镜有任务正在处理中，请稍候\', \'info\')';
        expect(videoBody).toContain(guard);
        expect(imageBody).toContain(guard);
    });

    it('optimistic helpers keep ids string-comparable with task-status upsert', () => {
        const helpers = extractFunctionBody(eventsSource, 'function adoptOptimisticCandidate\\(sceneId, listKey, tempId, realAssetId\\)');
        expect(helpers).toContain('String(realAssetId)');
    });
});
