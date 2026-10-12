import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');
const readJson = (relativePath) => JSON.parse(readSource(relativePath));

// 回归背景（2026-10-12 课堂事故）：学生打开带他人 user_id 的链接后，页面复用了
// 他人的会话，每次发消息 POST /task 都被属主断言 404，前端只报「发送消息失败」
// 且无自愈，重试永远失败。修复：task 404 时自愈一次（新建会话并原样重发），
// 且 createSession 不再回传 URL user_id，会话归属以登录身份为准。
describe('script_writer session 404 self heal', () => {
    const source = readSource('web/js/script_writer.js');
    const sendStart = source.indexOf('async function sendMessage(customMessage');
    const recoverStart = source.indexOf('async function recoverBrokenSession');
    const recoverBody = source.slice(recoverStart, source.indexOf('function removeLastUserBubble'));

    it('sendMessage 自愈入口仅对 404 生效，且重试请求不再二次自愈', () => {
        expect(sendStart).toBeGreaterThan(-1);
        expect(source).toContain('async function sendMessage(customMessage = null, isSystemMessage = false, recoveryOptions = null)');
        const sendBody = source.slice(sendStart, source.indexOf('// 检查任务状态'));
        expect(sendBody).toContain('taskResponse.status === 404');
        expect(sendBody).toContain('recoveryOptions.skipSessionRecovery');
        expect(sendBody).toContain('clearTimeout(timeoutId)');
        expect(sendBody).toContain('await recoverBrokenSession(message, isSystemMessage)');
    });

    it('recoverBrokenSession 丢弃旧会话、createSession 重建并以 skipSessionRecovery 重发', () => {
        expect(recoverStart).toBeGreaterThan(-1);
        expect(recoverBody).toContain('status_session_recreating');
        expect(recoverBody).toContain('sessionId = null');
        expect(recoverBody).toContain('await createSession()');
        // 防递归：重试请求带 skipSessionRecovery
        expect(recoverBody).toContain('{ skipSessionRecovery: true }');
        // 重发前移除失败尝试的用户气泡，避免气泡重复
        expect(recoverBody).toContain('removeLastUserBubble()');
    });

    it('重建失败时把消息放回输入框并恢复发送按钮', () => {
        expect(recoverBody).toContain('error_session_recreate_failed');
        expect(recoverBody).toContain('input.value = message');
        expect(recoverBody).toContain('isProcessing = false');
    });

    it('createSession 不再回传 URL user_id（会话归属以登录身份为准）', () => {
        const createStart = source.indexOf('async function createSession');
        const createBody = source.slice(createStart, source.indexOf('// 会话失效自愈'));
        expect(createBody).toContain("fetch('/api/session/create'");
        expect(createBody).not.toContain('user_id: USER_ID');
    });

    it('i18n 提供自愈文案（zh-CN / en）', () => {
        const zh = readJson('web/i18n/locales/zh-CN/index.json');
        const en = readJson('web/i18n/locales/en/index.json');
        expect(zh.status_session_recreating).toContain('正在新建会话');
        expect(zh.error_session_recreate_failed).toBeTruthy();
        expect(en.status_session_recreating).toBeTruthy();
        expect(en.error_session_recreate_failed).toBeTruthy();
    });
});
