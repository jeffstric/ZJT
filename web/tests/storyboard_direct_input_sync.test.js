import { describe, expect, it } from 'vitest';

import { nextDirectInputIfUnedited } from '../js/storyboard/state.js';

describe('nextDirectInputIfUnedited', () => {
    it('replaces the box when it still matches the previous prompt', () => {
        expect(nextDirectInputIfUnedited('旧提示词', '旧提示词', '新提示词')).toBe('新提示词');
    });

    it('keeps a box the user already edited', () => {
        expect(nextDirectInputIfUnedited('我改过的', '旧提示词', '新提示词')).toBeNull();
    });

    it('keeps a box the user cleared', () => {
        expect(nextDirectInputIfUnedited('', '旧提示词', '新提示词')).toBeNull();
    });

    it('fills an untouched empty box when the prompt becomes non-empty', () => {
        expect(nextDirectInputIfUnedited('', '', '新提示词')).toBe('新提示词');
    });

    it('does nothing when the prompt text did not change', () => {
        expect(nextDirectInputIfUnedited('同一句', '同一句', '同一句')).toBeNull();
    });
});
