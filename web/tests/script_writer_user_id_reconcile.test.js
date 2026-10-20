import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/script_writer.js'), 'utf8');

describe('script_writer wrong user_id and hide error', () => {
    const reconcileStart = source.indexOf('async function reconcileScriptWriterUserId');
    const reconcileBody = source.slice(reconcileStart, source.indexOf("document.addEventListener('DOMContentLoaded'"));
    const initStart = source.indexOf("document.addEventListener('DOMContentLoaded'");
    const initBody = source.slice(initStart, initStart + 500);
    const hideStart = source.indexOf('async function hideWorld');
    const hideBody = source.slice(hideStart, source.indexOf('async function restoreWorld'));

    it('入口用登录身份替换错误 user_id，并去掉对方的 world_id', () => {
        expect(reconcileStart).toBeGreaterThan(-1);
        expect(reconcileBody).toContain('resolveLoggedInUserId');
        expect(reconcileBody).toContain("params.set('user_id', authUserId)");
        expect(reconcileBody).toContain("params.delete('world_id')");
        expect(reconcileBody).toContain('window.location.replace');
        expect(initBody).toContain('await reconcileScriptWriterUserId()');
        expect(initBody).toContain('return;');
    });

    it('登录身份优先取 /api/user/role 的 data.id', () => {
        const resolveStart = source.indexOf('async function resolveLoggedInUserId');
        const resolveBody = source.slice(resolveStart, reconcileStart);
        expect(resolveBody).toContain("fetch('/api/user/role'");
        expect(resolveBody).toContain('data.data.id');
        expect(resolveBody).toContain("localStorage.getItem('user_id')");
    });

    it('隐藏世界失败时展示接口 detail，而不是固定未知错误', () => {
        expect(source).toContain('function readApiErrorText');
        expect(hideBody).toContain('readApiErrorText(data)');
        expect(hideBody).not.toContain("data.message || data.error || '未知错误'");
    });
});
