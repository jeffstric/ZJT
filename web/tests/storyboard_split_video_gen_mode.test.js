import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard split video gen mode', () => {
    it('split dialog locks first-frame vs reference and sends video_gen_mode', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        const eventsSource = readSource('web/js/storyboard/events.js');
        expect(renderSource).toContain('function renderSplitVideoGenMode');
        expect(renderSource).toContain('set-split-video-gen-mode');
        expect(renderSource).toContain('单镜最长时长');
        expect(eventsSource).toContain("video_gen_mode:");
        expect(eventsSource).toContain('max_shot_duration');
        expect(eventsSource).toContain("action === 'set-split-video-gen-mode'");
    });

    it('skips auto first-frame completion in reference mode', () => {
        const source = readSource('web/js/storyboard/auto_missing_images.js');
        expect(source).toMatch(
            /export async function autoGenerateMissingFirstFrames\(\) \{\s*if \(state\.videoImageMode === 'multi_reference'\) return;/,
        );
    });
});
