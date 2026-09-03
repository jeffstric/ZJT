import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard insert scene confirm dialog', () => {
    it('requires confirmation before issuing the insert request', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');

        // insert-scene 处理中：必须先 window.confirm，确认后才走到智能/普通插入请求
        expect(eventsSource).toMatch(
            /action === 'insert-scene'[\s\S]{0,600}?window\.confirm[\s\S]{0,800}?api\.smartInsertScene/
        );
        // in-flight 守卫仍位于确认之前（连点直接忽略，不重复弹框）
        expect(eventsSource).toMatch(
            /action === 'insert-scene'[\s\S]{0,300}?state\.isSmartInserting[\s\S]{0,300}?window\.confirm/
        );
    });
});
