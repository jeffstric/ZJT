import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('index CLI media preferences UI', () => {
    it('adds simplified agent model tab inside connection modal', () => {
        const htmlSource = readSource('web/index.html');
        const cssSource = readSource('web/css/index.css');
        const appSource = readSource('web/js/index_app.js');

        expect(htmlSource).toContain('智能体模型偏好');
        expect(htmlSource).toContain('cli-media-pref-panel');
        expect(htmlSource).toContain('cli-media-pref-intro');
        expect(htmlSource).toContain("switchAgentConnectionTab('cliMediaPref')");
        expect(htmlSource).toContain('cliMediaPrefFlatSlots');
        // 面向用户界面不展示底层 mode / surface / CLI 命令细节
        expect(htmlSource).not.toContain('surface:');
        expect(htmlSource).not.toContain('preference media set');
        expect(htmlSource).not.toContain('复制当前 CLI 命令');
        expect(htmlSource).not.toMatch(/cli-media-pref-mode/);

        expect(cssSource).toContain('.cli-media-pref-panel');
        expect(cssSource).toContain('.cli-media-pref-intro');
        expect(cssSource).toContain('.cli-media-pref-list');
        expect(cssSource).toContain('.agent-connection-tabs');

        expect(appSource).toContain("agentConnectionTab: 'connection'");
        expect(appSource).toContain('/api/storyboard/cli/media-preferences');
        expect(appSource).toContain('ensureCliMediaPreferencesLoaded');
        expect(appSource).toContain('onCliMediaPrefModelChange');
        expect(appSource).toContain('cliMediaPrefFlatSlots');
        expect(appSource).toContain('firstLastFrameOnly: true');
        expect(appSource).toContain('filterCliFirstLastFrameModels');
        // 下拉展示不含 task_id 技术字段
        expect(appSource).not.toContain('task_id=${model.task_id}');
    });

    it('warns when the saved model is missing from the available list instead of silent fallback', () => {
        const htmlSource = readSource('web/index.html');
        const cssSource = readSource('web/css/index.css');
        const appSource = readSource('web/js/index_app.js');

        // 存储的生效值不在可用模型列表（驱动未配置/停用）时，必须给出警示：
        // 下拉回退值只是展示替代，并未保存，不回写、不静默
        expect(appSource).toContain('cliMediaPrefInvalidValue');
        expect(appSource).toMatch(
            /invalidValue = \{\s*task_id: taskId,\s*model_name: profile\.model_name \|\| '',\s*\};/
        );
        expect(htmlSource).toContain('cli-media-pref-row-warning');
        expect(htmlSource).toContain('cliMediaPrefInvalidValue[slot.key].model_name');
        expect(cssSource).toContain('.cli-media-pref-row-warning');
    });
});
