/**
 * 分镜尾帧模式 → 算力档位联动（f0101b875）。
 *
 * 契约（resolveShotFrameVideoImageMode）：
 * - 首尾帧齐备 + 模型支持尾帧 → 内部 image_mode 用 first_last_with_tail（算力更高档）
 * - 提交给接口的 image_mode 仍是 first_last_frame（服务端不识别 with_tail）
 * - 仅首帧 / 模型不支持 / 非 first_last_frame 模式 → 保持原 mode
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/shot_frame_node.js'), 'utf8');
const generatorSource = fs.readFileSync(
    path.join(root, 'web/js/shot_frame_video_generator.js'), 'utf8');

const start = source.indexOf('function resolveShotFrameVideoImageMode');
const end = source.indexOf('function createShotFrameNode');
const helpers = source.slice(start, end);

function createResolver({ supports = true, previewImageUrl = 'p', lastFrameUrl = 'l', videoMode = 'first_last_frame' } = {}) {
    const factory = new Function('__supports', `
        const shotFrameModelSupportsLastFrame = () => __supports;
        ${helpers};
        return { resolveShotFrameVideoImageMode, resolveShotFrameLastFrameUrl };
    `);
    const { resolveShotFrameVideoImageMode, resolveShotFrameLastFrameUrl } = factory(supports);
    const node = {
        data: { videoMode, previewImageUrl, lastFrameUrl },
    };
    return { resolveShotFrameVideoImageMode, resolveShotFrameLastFrameUrl, node };
}

describe('resolveShotFrameVideoImageMode 档位联动', () => {
    it("首尾帧齐备 → 'first_last_with_tail'（算力更高档）", () => {
        const { resolveShotFrameVideoImageMode, node } = createResolver();
        expect(resolveShotFrameVideoImageMode(node)).toBe('first_last_with_tail');
    });

    it('仅首帧（无尾帧）保持 first_last_frame', () => {
        const { resolveShotFrameVideoImageMode, node } = createResolver({ lastFrameUrl: '' });
        expect(resolveShotFrameVideoImageMode(node)).toBe('first_last_frame');
    });

    it('模型不支持尾帧时不升级档位', () => {
        const { resolveShotFrameVideoImageMode, node } = createResolver({ supports: false });
        expect(resolveShotFrameVideoImageMode(node)).toBe('first_last_frame');
    });

    it.each(['reference', 'multi_reference'])('%s 模式不被改写', (mode) => {
        const { resolveShotFrameVideoImageMode, node } = createResolver({ videoMode: mode });
        expect(resolveShotFrameVideoImageMode(node)).toBe(mode);
    });
});

describe('提交契约（源码断言）', () => {
    it('内部档位仅用于算力查询，提交 image_mode 保持 first_last_frame', () => {
        // 服务端只识别 first_last_frame；with_tail 若外泄将导致提交被拒
        expect(source).toContain("context.image_mode = resolveShotFrameVideoImageMode(node);");
        expect(generatorSource).toMatch(/image_mode/);
        expect(generatorSource).not.toContain('first_last_with_tail');
    });

    it('尾帧地址优先取已保存值，回退 lastFrameConnections 源节点', () => {
        expect(source).toContain('const saved = String(node.data.lastFrameUrl || \'\').trim();');
        expect(source).toContain('state.lastFrameConnections');
    });
});
