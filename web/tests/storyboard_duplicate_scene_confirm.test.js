import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard duplicate scene confirm dialog', () => {
    it('requires confirmation before issuing the duplicate request', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');

        // duplicate-scene 处理中：必须先 window.confirm，确认后才走到 api.duplicateScene
        expect(eventsSource).toMatch(
            /action === 'duplicate-scene'[\s\S]{0,500}?window\.confirm[\s\S]{0,500}?api\.duplicateScene/
        );
        // 确认文案带分镜标题，无标题时回退通用文案
        expect(eventsSource).toContain('确定复制分镜「');
        expect(eventsSource).toContain('确定复制这个分镜吗？');
        // in-flight 守卫仍位于确认之后、发请求之前（守卫条件不变）
        expect(eventsSource).toMatch(
            /state\.duplicatingSceneId === sceneId[\s\S]{0,300}?window\.confirm/
        );
    });
});
