import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard export-full subtitles follow the preview toggle', () => {
    it('export-full passes include_subtitles from state.subtitleEnabled instead of hardcoded true', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');

        // 用 8 空格缩进的 return + 4 空格闭括号锚定 export-full 分支结尾
        const branch = eventsSource.match(
            /action === 'export-full'([\s\S]{0,2400}?)\r?\n        return;\r?\n    \}/
        );
        expect(branch).not.toBeNull();
        expect(branch[1]).toContain('include_subtitles: Boolean(state.subtitleEnabled)');
        expect(branch[1]).not.toContain('include_subtitles: true');
    });

    it('exportFullVideo api keeps an explicit false instead of defaulting to true', () => {
        const apiSource = readSource('web/js/storyboard/api.js');

        expect(apiSource).toContain('include_subtitles: options.include_subtitles !== false');
    });

    it('backend export-full-video route honors include_subtitles=false', () => {
        const routeSource = readSource('api/storyboard.py');

        expect(routeSource).toContain("if 'include_subtitles' in body:");
        expect(routeSource).toMatch(
            /burn_subtitles=include_subtitles/
        );
    });
});
