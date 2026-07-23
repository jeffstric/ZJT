import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';

import state, { applyGenerateProgressStatus } from '../js/storyboard/state.js';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard script split progress', () => {
    beforeEach(() => {
        state.generateProgressPercent = 0;
        state.generateProgressMessage = '';
    });

    it('normalizes backend progress and keeps the current phase message', () => {
        applyGenerateProgressStatus({ progress: 46.4, message: '正在拆分第 2/4 段' });
        expect(state.generateProgressPercent).toBe(46);
        expect(state.generateProgressMessage).toBe('正在拆分第 2/4 段');

        applyGenerateProgressStatus({ progress: 180, message: '' });
        expect(state.generateProgressPercent).toBe(100);
        expect(state.generateProgressMessage).toBe('正在处理任务');
    });

    it('renders an accessible progress bar and updates it from both polling paths', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        const bootstrapSource = readSource('web/js/storyboard/bootstrap.js');
        const eventsSource = readSource('web/js/storyboard/events.js');
        const cssSource = readSource('web/css/storyboard.css');

        expect(renderSource).toContain('role="progressbar"');
        expect(renderSource).toContain('aria-valuenow="${progressPercent}"');
        expect(renderSource).toContain('generate-progress-percent');
        expect(renderSource).toContain('generate-progress-message');
        expect(bootstrapSource).toContain('applyGenerateProgressStatus(statusData)');
        expect(eventsSource).toContain('applyGenerateProgressStatus(statusData)');
        expect(cssSource).toContain('.generate-progress-track');
        expect(cssSource).toContain('.generate-progress-fill');
    });
});
