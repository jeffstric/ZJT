import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/script_writer.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/script_writer.html'), 'utf8');
const functionStart = source.indexOf('function addPreviewImageToAssetLibrary()');
const functionEnd = source.indexOf('window.addPreviewImageToAssetLibrary', functionStart);
const functionSource = source.slice(functionStart, functionEnd);

function createHandler({ images = [], index = 0, fileName = '角色A', withAssetLibrary = true } = {}) {
    const promptAdd = vi.fn();
    const showError = vi.fn();
    const windowMock = {
        t: null,
        AssetLibrary: withAssetLibrary ? { promptAdd } : undefined,
    };
    const factory = new Function(
        'previewImages',
        'previewImageIndex',
        'previewImageFileName',
        'window',
        'showError',
        `${functionSource}; return addPreviewImageToAssetLibrary;`,
    );
    return {
        handler: factory(images, index, fileName, windowMock, showError),
        promptAdd,
        showError,
    };
}

describe('script_writer 当前预览图加入资产库', () => {
    it('预览弹窗按钮绑定入库函数并暴露全局处理函数', () => {
        expect(functionStart).toBeGreaterThan(-1);
        expect(functionEnd).toBeGreaterThan(functionStart);
        expect(html).toContain('id="preview-add-asset-library-btn"');
        expect(html).toContain('onclick="addPreviewImageToAssetLibrary()"');
        expect(source).toContain('window.addPreviewImageToAssetLibrary = addPreviewImageToAssetLibrary;');
    });

    it('传入当前缩略图 URL，并用对象名和图片描述生成默认资产名', () => {
        const { handler, promptAdd, showError } = createHandler({
            images: [
                { url: '/upload/main.png', label: '主图' },
                { url: '/upload/outfit.png', label: '服装2' },
            ],
            index: 1,
        });

        handler();

        expect(promptAdd).toHaveBeenCalledWith({
            sourceUrl: '/upload/outfit.png',
            name: '角色A-服装2',
        });
        expect(showError).not.toHaveBeenCalled();
    });

    it('无当前图片时提示且不调用资产库', () => {
        const { handler, promptAdd, showError } = createHandler();

        handler();

        expect(promptAdd).not.toHaveBeenCalled();
        expect(showError).toHaveBeenCalledWith('当前没有可加入资产库的图片');
    });

    it.each(['data:image/png;base64,abc', 'blob:http://localhost/image'])(
        '本地临时地址 %s 不调用资产库',
        (url) => {
            const { handler, promptAdd, showError } = createHandler({
                images: [{ url, label: '主图' }],
            });

            handler();

            expect(promptAdd).not.toHaveBeenCalled();
            expect(showError).toHaveBeenCalledWith('本地临时图片暂不支持加入资产库，请先上传或生成图片');
        },
    );

    it('资产库模块不可用时提示', () => {
        const { handler, promptAdd, showError } = createHandler({
            images: [{ url: '/upload/main.png', label: '主图' }],
            withAssetLibrary: false,
        });

        handler();

        expect(promptAdd).not.toHaveBeenCalled();
        expect(showError).toHaveBeenCalledWith('资产库功能暂不可用');
    });
});
