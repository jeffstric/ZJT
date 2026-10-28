import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/script_writer.js'), 'utf8');
const librarySource = fs.readFileSync(path.join(root, 'web/js/script_writer_library.js'), 'utf8');
const helperStart = source.indexOf('const ENTITY_NAME_MAX_LENGTH = 200;');
const helperEnd = source.indexOf('let isCommunityEdition', helperStart);
const helperSource = source.slice(helperStart, helperEnd);

function createHelpers() {
    const showError = vi.fn();
    const factory = new Function(
        'window',
        'showError',
        `${helperSource}; return { getEntityNameValidationError, validateEntityName };`,
    );
    return { ...factory({ t: null }, showError), showError };
}

describe('script_writer 实体名称校验', () => {
    it('接受正常中英文名称', () => {
        const { getEntityNameValidationError } = createHelpers();
        expect(getEntityNameValidationError('角色 A', '角色名称')).toBe('');
        expect(getEntityNameValidationError('Scene 01', '场景名称')).toBe('');
        expect(getEntityNameValidationError('名'.repeat(200), '剧本标题')).toBe('');
    });

    it.each(['<', '>', ':', '"', '/', '\\', '|', '?', '*', '\x00', '\x1f'])(
        '拒绝特殊字符 %s',
        (char) => {
            const { getEntityNameValidationError } = createHelpers();
            expect(getEntityNameValidationError(`A${char}B`, '角色名称')).toContain('不能包含');
        },
    );

    it.each(['', ' ', '.', '..', 'name.', 'name ', '名'.repeat(201)])(
        '拒绝空名称、非法结尾或超长名称：%j',
        (name) => {
            const { getEntityNameValidationError } = createHelpers();
            expect(getEntityNameValidationError(name, '剧本标题')).not.toBe('');
        },
    );

    it('validateEntityName 显示错误并阻止提交', () => {
        const { validateEntityName, showError } = createHelpers();
        expect(validateEntityName('A/B', '角色名称')).toBe(false);
        expect(showError).toHaveBeenCalledWith('角色名称不能包含 < > : " / \\ | ? * 或控制字符');
        expect(validateEntityName('角色A', '角色名称')).toBe(true);
    });

    it('新建、暂存编辑和数据库编辑均接入统一校验', () => {
        for (const functionName of ['createNewScript', 'createNewCharacter', 'createNewLocation', 'saveEditedFile']) {
            const start = source.indexOf(`function ${functionName}`);
            const body = source.slice(start, start + 1800);
            expect(body, functionName).toContain('validateEntityName');
        }
        expect(source).toContain('function checkCharacterNameDuplicate()');
        expect(source).toContain('function checkLocationNameDuplicate()');
        expect(source.match(/getEntityNameValidationError\(value, typeLabel\)/g)).toHaveLength(2);
        expect(librarySource).toContain('validateEntityName(entityNameConfig.value, typeLabel)');
    });
});
