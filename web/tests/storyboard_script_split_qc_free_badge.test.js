import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard script split QC free badge', () => {
    it('places a limited-free badge beside the QC rounds label', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        const cssSource = readSource('web/css/storyboard.css');

        expect(renderSource).toMatch(
            /script-split-qc-rounds-heading[\s\S]*?质检最大循环次数[\s\S]*?script-split-qc-free-badge[\s\S]*?限时免费/
        );
        expect(cssSource).toContain('.script-split-qc-rounds-heading');
        expect(cssSource).toContain('.script-split-qc-free-badge');
    });

    it('empty storyboard can reopen the split dialog from header start button', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        const eventsSource = readSource('web/js/storyboard/events.js');
        const cssSource = readSource('web/css/storyboard.css');
        expect(renderSource).toContain("data-action=\"open-generate-from-script\"");
        expect(renderSource).toContain('开始拆分');
        expect(renderSource).toContain('canShowStartSplitEntry');
        expect(eventsSource).toContain("action === 'open-generate-from-script'");
        expect(cssSource).toContain('.header-start-split');
    });

    it('moves group duration to the right column and collapses text-to-image', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        expect(renderSource).toMatch(
            /\$\{splitOptionsConfig\}[\s\S]*\$\{splitDurationConfig\}/,
        );
        expect(renderSource).not.toMatch(
            /\$\{videoModelConfig\}[\s\S]*\$\{splitDurationConfig\}[\s\S]*\$\{splitOptionsConfig\}/,
        );
        expect(renderSource).toContain('collapseTextToImage: true');
        expect(renderSource).toContain('toggle-script-split-t2i');
        expect(renderSource).toContain('gfs-t2i-panel');
    });
});
