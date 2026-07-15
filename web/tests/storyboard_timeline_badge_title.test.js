import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard timeline badge uses title instead of database id', () => {
    it('renders the timeline id badge from scene.title', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        // 时间轴分镜编号徽章应使用 scene.title（由 sort_order 生成，如"分镜1"），
        // 而不是 scene.id（数据库自增 ID），否则分镜 1 可能显示为"分镜630"。
        const badgeMatch = renderSource.match(
            /scene-timeline-id-badge\$\{statusClass\}[\s\S]*?<\/div>/
        );
        expect(badgeMatch).toBeTruthy();
        expect(badgeMatch[0]).toContain('scene.title');
        expect(badgeMatch[0]).not.toContain('scene.id');
    });
});
