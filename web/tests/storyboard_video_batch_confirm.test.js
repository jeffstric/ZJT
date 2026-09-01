import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard video batch confirm dialog with power estimate', () => {
    it('opens the confirm modal and estimates power instead of submitting directly', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');

        // auto-complete-missing-videos：先开弹窗（videoBatchConfirm.open），再试算，
        // 不得在该分支直接调 autoCompleteMissingVideos() 提交批次
        const branch = eventsSource.match(
            /action === 'auto-complete-missing-videos'([\s\S]{0,2000}?)return;\n    \}/
        );
        expect(branch).not.toBeNull();
        expect(branch[1]).toContain('videoBatchConfirm');
        expect(branch[1]).toContain('api.estimateMissingVideosPower');
        expect(branch[1]).not.toContain('autoCompleteMissingVideos()');

        // 确认/取消 action 存在；确认分支才真正提交批次
        expect(eventsSource).toContain("action === 'confirm-video-batch-submit'");
        expect(eventsSource).toContain("action === 'cancel-video-batch-submit'");
        expect(eventsSource).toMatch(
            /action === 'confirm-video-batch-submit'[\s\S]{0,800}?autoCompleteMissingVideos\(\)/
        );
    });

    it('registers the confirm dialog renderer and shows the estimated total power', () => {
        const renderSource = readSource('web/js/storyboard/render.js');

        expect(renderSource).toContain('function renderVideoBatchConfirmDialog()');
        // 注册进 modal 聚合渲染
        expect(renderSource).toMatch(/renderModalsHtml\(\)[\s\S]{0,800}?renderVideoBatchConfirmDialog\(\)/);
        // 弹窗内容包含预计扣减与明细，footer 按钮绑定确认/取消 action
        expect(renderSource).toContain('预计扣减算力');
        expect(renderSource).toContain('confirm-video-batch-submit');
        expect(renderSource).toContain('cancel-video-batch-submit');
    });

    it('wires the estimate api and dialog state', () => {
        const apiSource = readSource('web/js/storyboard/api.js');
        const stateSource = readSource('web/js/storyboard/state.js');

        expect(apiSource).toContain('estimateMissingVideosPower');
        expect(apiSource).toContain('estimate-missing-videos-power');
        expect(stateSource).toContain('videoBatchConfirm');
    });

    it('exposes the estimate endpoint on the backend', () => {
        const routeSource = readSource('api/storyboard.py');
        const serviceSource = readSource('services/storyboard_agent_cli_service.py');

        expect(routeSource).toContain('estimate-missing-videos-power');
        expect(serviceSource).toContain('def estimate_missing_videos_power');
        // 估价与真实扣费同源：常规视频走 get_computing_power_for_task
        expect(serviceSource).toMatch(
            /def estimate_missing_videos_power[\s\S]{0,4000}?get_computing_power_for_task/
        );
    });
});
