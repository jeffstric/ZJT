import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard reference-to-video without first frame', () => {
    it('direct video submit skips first-frame gate in multi_reference and sends image_mode', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');
        const start = eventsSource.indexOf('async function sendDirectVideo(');
        const end = eventsSource.indexOf('function recordPowerSpend', start);
        expect(start).toBeGreaterThan(-1);
        expect(end).toBeGreaterThan(start);
        const fn = eventsSource.slice(start, end);
        expect(fn).toContain("imageMode === 'first_last_frame'");
        expect(fn).toContain('config.image_mode = imageMode');
        expect(fn).toContain('reference_image_urls');
        expect(fn).toContain("imageMode === 'multi_reference'");
        expect(fn).not.toMatch(/if \(!firstFrameUrl\) \{\s*notify\('请先生成并选中首帧/);
    });

    it('missing-video batch includes scenes without first frames in multi_reference', () => {
        const stateSource = readSource('web/js/storyboard/auto_missing_videos_state.js');
        expect(stateSource).toContain("state.videoImageMode === 'multi_reference'");
        expect(stateSource).toContain('if (!isMultiRef && !scene.firstFrameUrl) return false');
        expect(stateSource).toContain('全能参考逐个生成视频');
        expect(stateSource).not.toContain('（全能参考：首帧+角色/场景参考+画风参考）');
    });

    it('mode selector copy explains skipping storyboard images', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        expect(renderSource).toContain('可不生成分镜图，直接用角色/场景/道具参考图生视频');
        expect(renderSource).toContain('将使用分镜角色/场景/道具参考图');
    });

    it('mode selector keeps Beta tag only on the panel option, not the collapsed button', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        // 下拉面板选项保留 Beta 标识（选择入口，空间充足）
        expect(renderSource).toContain("<strong>${escapeHtml(opt.title)}${opt.beta ? REF_VIDEO_BETA_TAG : ''}</strong>");
        // 收起态按钮 / 静态标签不再带 Beta：工具栏区域狭小，徽标冗余（截图反馈优化）
        expect(renderSource).not.toContain('${escapeHtml(modeLabel)}${betaTag}');
        expect(renderSource).not.toContain('video-mode-static-label">${escapeHtml(modeLabel)}${betaTag}');
        const cssSource = readSource('web/css/storyboard.css');
        expect(cssSource).not.toContain('.video-mode-btn .beta-tag');
        expect(cssSource).toContain('.video-mode-texts .beta-tag');
    });

    it('empty media stack keeps only the add button so the textarea stays wide', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        const cssSource = readSource('web/css/storyboard.css');
        // 空态不再渲染内联提示文案（截图反馈：提示 div 把提示词 textarea 挤得太窄），
        // 参考图自动收集的说明收纳进 + 按钮的 title 悬浮提示
        expect(renderSource).not.toContain('media-stack-hint');
        expect(renderSource).toContain('上传参考图；不上传时将使用分镜角色/场景/道具参考图');
        expect(cssSource).not.toContain('.media-stack-hint');
    });

    it('video mode selector offers reference mode from union of all video models', () => {
        const stateSource = readSource('web/js/storyboard/state.js');
        const renderSource = readSource('web/js/storyboard/render.js');
        const eventsSource = readSource('web/js/storyboard/events.js');
        // 可选项取全部视频模型支持模式的并集，而非「当前模式选中模型」的能力——
        // 否则首帧模式（尤其无输入图时解析到文生视频模型）下只剩首尾帧，参考生视频入口永不出现
        expect(stateSource).toContain('export function getAvailableVideoImageModes()');
        expect(stateSource).toContain('allImageToVideoModels().forEach');
        expect(renderSource).toMatch(/function renderVideoModeSelector\(disabled\) \{[\s\S]*?const modes = getAvailableVideoImageModes\(\)/);
        expect(eventsSource).toMatch(/action === 'set-video-image-mode'[\s\S]*?const supported = getAvailableVideoImageModes\(\);/);
    });

    it('reference mode resolves reference-slot model regardless of uploaded inputs', () => {
        const stateSource = readSource('web/js/storyboard/state.js');
        const start = stateSource.indexOf('export function getSelectedVideoModel()');
        const end = stateSource.indexOf('function allImageToVideoModels()', start);
        expect(start).toBeGreaterThan(-1);
        expect(end).toBeGreaterThan(start);
        const fn = stateSource.slice(start, end);
        // 参考模式固定解析「参考视频槽」模型（与提交链路 getSelectedVideoTaskId 同口径），
        // 不能因「尚无输入图」落到文生视频模型，否则模式能力判断与实际提交模型错位
        expect(fn).toMatch(/const taskId = isReference\s*\? state\.selectedReferenceToVideoTaskId/);
        expect(fn).toMatch(/const models = isReference\s*\? getReferenceToVideoSlotModels\(\)/);
    });

    it('reference mode stops showing misleading pending labels for storyboard images', () => {
        const stateSource = readSource('web/js/storyboard/auto_missing_images_state.js');
        const renderSource = readSource('web/js/storyboard/render.js');
        // 缺失分镜图在参考生视频模式下展示「免分镜图」而非「待生成」
        expect(stateSource).toContain("if (status === 'missing' && state.videoImageMode === 'multi_reference')");
        expect(stateSource).toContain("return '免分镜图';");
        expect(stateSource).toContain("label: isRefVideoMode ? '补全分镜图（可选）' : '自动补全未生成分镜'");
        expect(renderSource).toContain('return \'<span class="status idle">免分镜图</span>\';');
        // 顶部统计：参考生视频模式不再展示图片「N 个待生成」，改为模式说明
        expect(renderSource).toMatch(/const imageHint = isRefVideoMode \? '' : ` · \$\{summary\.missingCount\} 个待生成`/);
        expect(renderSource).toContain("const refModeHint = isRefVideoMode ? ' · 参考生视频免分镜图' : '';");
    });
});
