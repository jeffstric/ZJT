// 「直填生图」预填提示词组合测试（Vitest，CI 运行）。
// 回归背景：曾错误拼接 character_desc（纯角色名列表，实际生图链路不使用，
// 角色外貌由参考图注入），导致预填文本末尾出现「，赵志高、王小胖」尾巴。
// 实际生图链路：services/storyboard_agent_cli_service.py:_compose_image_prompt。
import { describe, expect, it } from 'vitest';

import { composeSceneImagePrompt } from '../js/storyboard/state.js';

describe('composeSceneImagePrompt', () => {
    it('joins perspective / style / scene_desc with Chinese comma', () => {
        const scene = {
            promptJson: {
                perspective: '平视 / 中景',
                style: '现代都市写实风格',
                scene_desc: '中景，画面左侧【【赵志高】】还在叉腰。',
                character_desc: '赵志高、王小胖',
            },
        };
        expect(composeSceneImagePrompt(scene)).toBe(
            '平视 / 中景，现代都市写实风格，中景，画面左侧【【赵志高】】还在叉腰。'
        );
    });

    it('never appends character_desc', () => {
        const scene = {
            promptJson: {
                scene_desc: '画面描述',
                character_desc: '赵志高、王小胖',
            },
        };
        const prompt = composeSceneImagePrompt(scene);
        expect(prompt).toBe('画面描述');
        expect(prompt).not.toContain('赵志高');
    });

    it('filters empty segments', () => {
        const scene = {
            promptJson: {
                perspective: '',
                style: '  ',
                scene_desc: '只有画面描述',
            },
        };
        expect(composeSceneImagePrompt(scene)).toBe('只有画面描述');
    });

    it('returns empty string for missing scene or promptJson', () => {
        expect(composeSceneImagePrompt(null)).toBe('');
        expect(composeSceneImagePrompt({})).toBe('');
        expect(composeSceneImagePrompt({ promptJson: null })).toBe('');
    });
});
