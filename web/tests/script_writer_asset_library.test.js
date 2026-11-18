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

describe('script_writer 场景图片从资产库导入', () => {
    const pickLocStart = source.indexOf('function pickLocMultiImageFromAssetLibrary()');
    const pickLocEnd = source.indexOf('window.pickLocMultiImageFromAssetLibrary', pickLocStart);
    const pickLocSource = source.slice(pickLocStart, pickLocEnd);

    const pickPreviewStart = source.indexOf('function pickPreviewImageFromAssetLibrary()');
    const pickPreviewEnd = source.indexOf('async function applyAssetAsPreviewImage(url)', pickPreviewStart);
    const pickPreviewSource = source.slice(pickPreviewStart, pickPreviewEnd);

    const applyStart = source.indexOf('async function applyAssetAsPreviewImage(url)');
    const applyEnd = source.indexOf('window.pickPreviewImageFromAssetLibrary', applyStart);
    const applySource = source.slice(applyStart, applyEnd);

    function createLocMultiPicker({ angle = 'front', angleText = '正面', label = '', withAssetLibrary = true } = {}) {
        const openModal = vi.fn();
        const addLocMultiImageItem = vi.fn();
        const windowMock = { AssetLibrary: withAssetLibrary ? { openModal } : undefined };
        const angleSelect = { value: angle, options: [{ text: angleText }], selectedIndex: 0 };
        const labelInput = { value: label };
        const list = { appendChild: vi.fn() };
        const documentMock = {
            getElementById: (id) => (
                { 'loc-multi-image-angle': angleSelect, 'loc-multi-image-label': labelInput, 'loc-multi-image-list': list }[id] || null
            ),
        };
        const factory = new Function(
            'window',
            'document',
            'addLocMultiImageItem',
            `${pickLocSource}; return pickLocMultiImageFromAssetLibrary;`,
        );
        return {
            handler: factory(windowMock, documentMock, addLocMultiImageItem),
            openModal,
            addLocMultiImageItem,
            labelInput,
            list,
        };
    }

    function createPickPreviewHandler({ fileType = 'locations', withAssetLibrary = true } = {}) {
        const openModal = vi.fn();
        const applyAssetAsPreviewImage = vi.fn();
        const windowMock = { AssetLibrary: withAssetLibrary ? { openModal } : undefined, t: null };
        const factory = new Function(
            'window',
            'previewImageFileType',
            'applyAssetAsPreviewImage',
            `${pickPreviewSource}; return pickPreviewImageFromAssetLibrary;`,
        );
        return {
            handler: factory(windowMock, fileType, applyAssetAsPreviewImage),
            openModal,
            applyAssetAsPreviewImage,
        };
    }

    function createApplyHandler({ fileType = 'locations', fileName = '场景A', entityKey = 'location', currentImage = '/upload/old.png' } = {}) {
        const getPayload = { success: true, [entityKey]: { json_data: { reference_image: currentImage } } };
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => getPayload })
            .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) });
        const deps = {
            previewImageFileType: fileType,
            previewImageFileName: fileName,
            USER_ID: 'u1',
            WORLD_ID: 'w1',
            AUTH_TOKEN: 'tok',
            fetch: fetchMock,
            checkTokenExpired: vi.fn(() => false),
            showInfo: vi.fn(),
            showSuccess: vi.fn(),
            showError: vi.fn(),
            closeImagePreviewModal: vi.fn(),
            loadFiles: vi.fn(),
            notifyAgentAssetUpdated: vi.fn(),
        };
        const factory = new Function(
            ...Object.keys(deps),
            `${applySource}; return applyAssetAsPreviewImage;`,
        );
        return { handler: factory(...Object.values(deps)), fetchMock, ...deps };
    }

    it('场景编辑表单与预览弹窗按钮已绑定资产库入口', () => {
        expect(pickLocStart).toBeGreaterThan(-1);
        expect(pickPreviewStart).toBeGreaterThan(-1);
        expect(applyStart).toBeGreaterThan(-1);
        expect(html).toContain("pickImageFromAssetLibrary('loc-image')");
        expect(html).toContain('pickLocMultiImageFromAssetLibrary()');
        expect(html).toContain('id="preview-location-asset-library-btn"');
        expect(html).toContain('onclick="pickPreviewImageFromAssetLibrary()"');
        expect(source).toContain('window.pickLocMultiImageFromAssetLibrary = pickLocMultiImageFromAssetLibrary;');
        expect(source).toContain("!['characters', 'locations', 'props'].includes(previewImageFileType)");
    });

    it('多角度图选择资产后按当前角度与标签加入列表并清空标签输入', () => {
        const { handler, openModal, addLocMultiImageItem, labelInput } = createLocMultiPicker({ label: '正门' });

        handler();
        expect(openModal).toHaveBeenCalledTimes(1);

        openModal.mock.calls[0][0].onPick({ file_url: '/upload/asset_library/1/a.png' });

        expect(addLocMultiImageItem).toHaveBeenCalledWith(expect.anything(), '正门', '/upload/asset_library/1/a.png', 'front', undefined);
        expect(labelInput.value).toBe('');
    });

    it('标签为空时回退到当前角度文案', () => {
        const { handler, openModal, addLocMultiImageItem, labelInput } = createLocMultiPicker({ label: '   ' });

        handler();
        openModal.mock.calls[0][0].onPick({ file_url: '/upload/asset_library/1/b.png' });

        expect(addLocMultiImageItem).toHaveBeenCalledWith(expect.anything(), '正面', '/upload/asset_library/1/b.png', 'front', undefined);
        expect(labelInput.value).toBe('');
    });

    it('无效资产不加入列表', () => {
        const { handler, openModal, addLocMultiImageItem } = createLocMultiPicker();

        handler();
        openModal.mock.calls[0][0].onPick(null);
        openModal.mock.calls[0][0].onPick({});

        expect(addLocMultiImageItem).not.toHaveBeenCalled();
    });

    it('场景预览弹窗打开资产库选择器并把选中资产交给保存函数', () => {
        const { handler, openModal, applyAssetAsPreviewImage } = createPickPreviewHandler({ fileType: 'locations' });

        handler();

        expect(openModal).toHaveBeenCalledTimes(1);
        expect(openModal.mock.calls[0][0].title).toBe('从资产库选择场景主图');

        openModal.mock.calls[0][0].onPick({ file_url: '/upload/asset_library/1/a.png' });
        expect(applyAssetAsPreviewImage).toHaveBeenCalledWith('/upload/asset_library/1/a.png');
    });

    it('非角色/场景/道具类型不打开选择器', () => {
        const { handler, openModal } = createPickPreviewHandler({ fileType: 'worlds' });

        handler();

        expect(openModal).not.toHaveBeenCalled();
    });

    it('场景选中资产后写入 locations 接口的 reference_image', async () => {
        const { handler, fetchMock, notifyAgentAssetUpdated, closeImagePreviewModal, loadFiles } = createApplyHandler({
            fileType: 'locations',
            fileName: '场景A',
        });

        await handler('/upload/asset_library/1/a.png');

        const [getUrl, getOpts] = fetchMock.mock.calls[0];
        expect(getUrl).toBe(`/api/locations-files/${encodeURIComponent('场景A')}?user_id=u1&world_id=w1&raw_json=true`);
        expect(getOpts.headers.Authorization).toBe('Bearer tok');

        const [postUrl, postOpts] = fetchMock.mock.calls[1];
        expect(postUrl).toBe(`/api/locations-files/${encodeURIComponent('场景A')}?user_id=u1&world_id=w1`);
        expect(postOpts.method).toBe('POST');
        const body = JSON.parse(postOpts.body);
        expect(JSON.parse(body.content).reference_image).toBe('/upload/asset_library/1/a.png');
        expect(body.auth_token).toBe('tok');

        expect(notifyAgentAssetUpdated).toHaveBeenCalledWith(expect.stringContaining('场景'));
        expect(notifyAgentAssetUpdated).toHaveBeenCalledWith(expect.stringContaining('主参考图'));
        expect(closeImagePreviewModal).toHaveBeenCalled();
        expect(loadFiles).toHaveBeenCalledWith('locations');
    });

    it('所选资产已是当前主图时不再重复保存', async () => {
        const { handler, fetchMock, showInfo } = createApplyHandler({
            fileType: 'locations',
            entityKey: 'location',
            currentImage: '/upload/asset_library/1/a.png',
        });

        await handler('/upload/asset_library/1/a.png');

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(showInfo).toHaveBeenCalled();
    });

    it('角色/道具保存链路不受影响（回归保护）', async () => {
        const { handler, fetchMock } = createApplyHandler({
            fileType: 'props',
            fileName: '道具A',
            entityKey: 'prop',
        });

        await handler('/upload/asset_library/1/c.png');

        expect(fetchMock.mock.calls[0][0]).toContain('/api/props-files/');
        expect(fetchMock.mock.calls[1][0]).toContain('/api/props-files/');
        const body = JSON.parse(fetchMock.mock.calls[1][1].body);
        expect(JSON.parse(body.content).reference_image).toBe('/upload/asset_library/1/c.png');
    });
});
