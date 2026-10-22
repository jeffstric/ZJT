/**
 * 工作流页面 @ 下拉悬停大图预览（web/js/hover_preview.js）：
 * - 下拉条目挂 data-hover-preview 后，mouseover 即在条目右侧弹出原图预览；
 * - 移开鼠标 / 主动 hide() 后预览消失；预览内容经 window.escapeHtml 转义。
 * - image_to_video_node.js / nodes.js 的下拉条目已挂 data-hover-preview，关闭时主动隐藏。
 */
import fs from 'node:fs';
import path from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// 只加载一次：模块闭包内有 hoverBound/previewEl 单例，重复 eval 会叠加委托与浮层
beforeAll(() => {
    window.eval(readSource('web/js/escape.js'));
    window.eval(readSource('web/js/hover_preview.js'));
});

function makeDropdownItem(className, previewUrl) {
    const dropdown = document.createElement('div');
    dropdown.className = 'mention-dropdown';
    const item = document.createElement('div');
    item.className = className;
    if (previewUrl) item.dataset.hoverPreview = previewUrl;
    dropdown.appendChild(item);
    document.body.appendChild(dropdown);
    return item;
}

describe('workflow hover preview 行为', () => {
    it('mouseover 命中 data-hover-preview 条目时显示原图预览', () => {
        const item = makeDropdownItem('mention-dropdown-item', 'https://cdn.test/frame.png');

        item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));

        const pop = document.getElementById('wf-hover-preview');
        expect(pop).toBeTruthy();
        expect(pop.style.display).toBe('block');
        expect(pop.dataset.url).toBe('https://cdn.test/frame.png');
        expect(pop.querySelector('img').getAttribute('src')).toBe('https://cdn.test/frame.png');
    });

    it('预览 HTML 经 window.escapeHtml 转义，防属性逃逸', () => {
        const item = makeDropdownItem('mention-dropdown-item', 'https://cdn.test/a.png?x=1&y=2"><b>');

        item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));

        const pop = document.getElementById('wf-hover-preview');
        expect(pop.dataset.url).toBe('https://cdn.test/a.png?x=1&y=2"><b>');
        expect(pop.innerHTML).toContain('&amp;');
        expect(pop.innerHTML).toContain('&quot;');
        expect(pop.innerHTML).not.toContain('"><b>');
    });

    it('移开鼠标与 WFHoverPreview.hide() 均隐藏预览', () => {
        const item = makeDropdownItem('mention-dropdown-item', 'https://cdn.test/a.png');
        item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        const pop = document.getElementById('wf-hover-preview');
        expect(pop.style.display).toBe('block');

        document.body.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        expect(pop.style.display).toBe('none');

        item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        expect(pop.style.display).toBe('block');
        window.WFHoverPreview.hide();
        expect(pop.style.display).toBe('none');
    });

    it('无 data-hover-preview 的条目不弹预览', () => {
        window.WFHoverPreview.hide();
        const item = makeDropdownItem('mention-dropdown-item', '');
        item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        const pop = document.getElementById('wf-hover-preview');
        expect(pop.style.display).toBe('none');
    });
});

describe('workflow @ 下拉条目预览接线', () => {
    it('image_to_video_node.js 的 @ 下拉图片条目挂 data-hover-preview，关闭时隐藏预览', () => {
        const source = readSource('web/js/image_to_video_node.js');
        expect(source).toContain('data-hover-preview="${escapeHtml(item.url)}"');
        // 仅图片类条目带预览（音频/视频不走 <img> 预览）
        expect(source).toMatch(/hoverPreviewAttr = isImage && item\.url/);
        expect(source).toMatch(/hideMentionDropdown\(\)\{[\s\S]{0,200}WFHoverPreview\.hide\(\)/);
    });

    it('nodes.js 角色/首尾帧下拉挂 data-hover-preview，关闭时隐藏预览', () => {
        const source = readSource('web/js/nodes.js');
        expect(source).toContain('data-hover-preview="${escapeHtml(item.url)}"');
        expect(source).toMatch(/hasImage \? ` data-hover-preview="\$\{escapeHtml\(char\.reference_image\)\}"` : ''/);
        expect(source).toMatch(/hideCharacterDropdownForImagePrompt\(nodeId, dropdownKey = 'imageprompt'\) \{[\s\S]{0,120}WFHoverPreview\.hide\(\)/);
    });

    it('video_workflow.html 引入 hover_preview.js，样式含 .wf-hover-preview', () => {
        expect(readSource('web/video_workflow.html')).toContain('/js/hover_preview.js');
        const css = readSource('web/css/video_workflow.css');
        expect(css).toContain('.wf-hover-preview');
        expect(css).toMatch(/\.wf-hover-preview img \{[\s\S]{0,120}max-width: 280px/);
    });
});
