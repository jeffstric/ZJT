import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('index agent connection limited-free badge', () => {
    it('shows the badge only for the community edition', () => {
        const htmlSource = readSource('web/index.html');
        const cssSource = readSource('web/css/index.css');
        const appSource = readSource('web/js/index_app.js');

        expect(htmlSource).toMatch(
            /v-if="isCommunityEdition"\s+class="agent-connection-free-badge">限时免费<\/span>/
        );
        // CLI 仅服务故事板：营销模式下不展示智能体连接入口
        expect(htmlSource).toMatch(
            /v-if="isLoggedIn && creationMode === 'short_drama'"\s+class="agent-connect-btn"/
        );
        expect(appSource).toContain("if (this.creationMode !== 'short_drama')");
        expect(cssSource).toContain('.agent-connection-free-badge');
        expect(appSource).toContain('this.isCommunityEdition = !response.data.data.is_enterprise;');
    });
});
