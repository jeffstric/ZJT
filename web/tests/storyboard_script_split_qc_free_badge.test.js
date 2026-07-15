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
});
