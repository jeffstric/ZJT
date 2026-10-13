import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');
const readJson = (relativePath) => JSON.parse(readSource(relativePath));

// 用户备注 + 用户自定义昵称（随机趣味默认昵称）功能回归：
// - 管理端：用户列表备注列 + 备注编辑弹窗 + PUT /api/admin/users/{id}/remark
// - 用户端：PUT /api/user/nickname（空=重新随机分配），/api/user/role 带出昵称
describe('admin user remark', () => {
    it('admin.js saveUserRemark calls the remark API with Authorization header', () => {
        const source = readSource('web/js/admin.js');
        const fnBody = source.slice(
            source.indexOf('async saveUserRemark()'),
            source.indexOf('async saveUserRemark()') + 1200
        );
        expect(fnBody).toContain('/api/admin/users/${this.remarkModal.userId}/remark');
        expect(fnBody).toContain('Authorization');
        expect(fnBody).toContain('remark:');
        // 保存成功后刷新列表，让备注列立即更新
        expect(fnBody).toContain('loadUsers()');
    });

    it('admin.js wires open/close remark modal state', () => {
        const source = readSource('web/js/admin.js');
        expect(source).toContain('openRemarkModal(user)');
        expect(source).toContain('closeRemarkModal()');
        expect(source).toMatch(/remarkModal:\s*\{[\s\S]{0,120}show:\s*false/);
    });

    it('admin.html renders remark column, nickname subtitle and remark modal', () => {
        const source = readSource('web/admin.html');
        expect(source).toContain("{{ t('col_remark') }}");
        expect(source).toContain('remark-cell');
        expect(source).toContain('account-nickname');
        expect(source).toContain('openRemarkModal(user)');
        expect(source).toContain('v-if="remarkModal.show"');
        // 备注编辑上限 500（与服务端 REMARK_MAX_LEN 一致）
        expect(source).toContain('maxlength="500"');
        // 详情弹窗展示昵称
        expect(source).toContain("userDetailModal.user.display_name");
    });

    it('admin i18n locales contain the new keys in zh-CN and en', () => {
        for (const locale of ['zh-CN', 'en']) {
            const dict = readJson(`web/i18n/locales/${locale}/admin.json`);
            expect(dict.col_remark).toBeTruthy();
            expect(dict.col_nickname).toBeTruthy();
            expect(dict.btn_edit_remark).toBeTruthy();
            expect(dict.modal_remark).toBeTruthy();
            expect(dict.modal_remark_content).toBeTruthy();
            expect(dict.toast_remark_saved).toBeTruthy();
        }
    });

    it('backend exposes remark endpoint and nickname in role API', () => {
        const adminApi = readSource('api/admin.py');
        expect(adminApi).toContain('"/users/{user_id}/remark"');
        expect(adminApi).toContain('REMARK_MAX_LEN');
        // remark 不进 to_dict，由 admin 路径单独附加（防用户侧泄漏）
        expect(adminApi).toContain("user_dict['remark'] = user.remark");
        const server = readSource('server.py');
        expect(server).toContain('"display_name"');
        expect(server).toContain('"nickname": user.nickname');
    });
});

describe('user nickname self service', () => {
    it('api/user.py exposes PUT /nickname with empty-reset semantics', () => {
        const source = readSource('api/user.py');
        expect(source).toContain('@router.put("/nickname")');
        expect(source).toContain('NICKNAME_MAX_LEN');
        expect(source).toContain('UsersModel.update_nickname');
    });

    it('index_app.js saves nickname and top bar prefers displayName', () => {
        const appJs = readSource('web/js/index_app.js');
        expect(appJs).toContain('async saveNickname()');
        expect(appJs).toContain("axios.put('/api/user/nickname'");
        expect(appJs).toContain('displayName()');
        expect(appJs).toContain('this.nickname = response.data.data.nickname');
        const indexHtml = readSource('web/index.html');
        expect(indexHtml).toContain('{{ displayName }}');
        expect(indexHtml).toContain('userSettingsTab === \'profile\'');
        expect(indexHtml).toContain('id="profile-nickname-input"');
    });
});
