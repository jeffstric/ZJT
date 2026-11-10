/**
 * 故事板 → 画布 增量资产同步（storyboard_asset_sync.js）。
 *
 * 契约（见模块头注释与 docs/storyboard/storyboard_workflow_conversion.md）：
 * - 只增不改不删：缺失 URL 补节点（含选中资产被删后补建），已有 URL 跳过
 * - 选中跟随故事板：previewImageUrl + 首帧端口连线指向选中图；
 *   选中视频连线重排到该帧 video 连线首位（W→S 回转选中取连线第一）
 * - 匹配不到分镜帧（source_shot_key ≠ shot_id）的场景跳过
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/storyboard_asset_sync.js'), 'utf8');

function loadModule() {
    const context = {
        console,
        location: { origin: 'http://127.0.0.1:13009' },
    };
    context.window = {};
    context.globalThis = context;
    vm.createContext(context);
    vm.runInContext(source, context);
    return context.window.StoryboardAssetSync;
}

// 画布形态：分镜帧(7, shot_id=s001) 连线 image(20,url=/a.png) + video(21,url=/v1.mp4)
function makeCanvasState() {
    return {
        nodes: [
            { id: 7, type: 'shot_frame', x: 1420, y: 0, data: { shotJson: { shot_id: 's001', shot_number: 3 }, previewImageUrl: '', lastFrameUrl: '' } },
            { id: 20, type: 'image', x: 2320, y: 0, data: { url: '/a.png' } },
            { id: 21, type: 'video', x: 2760, y: 0, data: { url: '/v1.mp4' } },
        ],
        connections: [
            { id: 1, from: 7, to: 20 },
            { id: 2, from: 7, to: 21 },
        ],
        firstFrameConnections: [{ id: 9, from: 20, to: 7 }],   // 首帧端口已连当前选中图 /a.png
        nextConnId: 3,
        nextFirstFrameConnId: 1,
    };
}

function makeCtx(state) {
    let nextId = 100;
    return {
        state,
        createImageNode: ({ x, y }) => {
            const id = nextId++;
            state.nodes.push({ id, type: 'image', x, y, data: {} });
            return id;
        },
        createVideoNode: ({ x, y }) => {
            const id = nextId++;
            state.nodes.push({ id, type: 'video', x, y, data: {} });
            return id;
        },
        renderAllConnections: vi.fn(),
        renderMinimap: vi.fn(),
        safeAutoSave: vi.fn(),
        showToast: vi.fn(),
    };
}

const scenePayload = (over = {}) => Object.assign({
    source_shot_key: 's001',
    first_frames: [{ id: 1, url: '/a.png' }, { id: 2, url: '/b.png' }],
    videos: [{ id: 3, url: '/v1.mp4' }, { id: 4, url: '/v2.mp4' }],
    selected_first_frame_url: '/b.png',
    selected_video_url: '/v2.mp4',
    last_frame_url: '/last.png',
}, over);

describe('planFrameSync 纯逻辑', () => {
    const Sync = loadModule();

    it('已有 URL 跳过，缺失与选中（含被删的）补建', () => {
        const plan = Sync._internals.planFrameSync(scenePayload(), {
            images: new Set(['/a.png']),
            videos: new Set(['/v1.mp4']),
        });
        expect(plan.addImages).toEqual(['/b.png']);   // /a.png 已有
        expect(plan.addVideos).toEqual(['/v2.mp4']);
        expect(plan.selectFirstFrameUrl).toBe('/b.png');
        expect(plan.selectVideoUrl).toBe('/v2.mp4');
        expect(plan.lastFrameUrl).toBe('/last.png');
    });

    it('选中图不在候选列表也会补建（选中资产画布上被删过）', () => {
        const plan = Sync._internals.planFrameSync({
            first_frames: [], videos: [],
            selected_first_frame_url: '/sel.png',
            selected_video_url: '/selv.mp4',
            last_frame_url: '',
        }, { images: new Set(), videos: new Set() });
        expect(plan.addImages).toEqual(['/sel.png']);
        expect(plan.addVideos).toEqual(['/selv.mp4']);
    });

    it('normalizeUrl 剥当前 origin 前缀', () => {
        expect(Sync._internals.normalizeUrl('http://127.0.0.1:13009/upload/a.png')).toBe('/upload/a.png');
        expect(Sync._internals.normalizeUrl('/upload/a.png')).toBe('/upload/a.png');
    });
});

describe('applyPayload 合并', () => {
    const Sync = loadModule();

    it('补缺失节点+连线，选中首帧进槽并重指首帧端口，选中视频连线重排首位', () => {
        const state = makeCanvasState();
        const ctx = makeCtx(state);
        const res = Sync._internals.applyPayload({ scenes: [scenePayload()] }, ctx);

        expect(res).toMatchObject({ addedImages: 1, addedVideos: 1, skippedScenes: 0 });

        // 新节点与连线
        const newImage = state.nodes.find(n => n.type === 'image' && n.data.url === '/b.png');
        const newVideo = state.nodes.find(n => n.type === 'video' && n.data.url === '/v2.mp4');
        expect(newImage).toBeTruthy();
        expect(newVideo).toBeTruthy();
        expect(newImage.data.name).toBe('分镜3图2');       // 已有1张+新1张 → 多数命名
        expect(state.connections.some(c => c.from === 7 && c.to === newImage.id)).toBe(true);

        // 选中首帧：槽 + 首帧端口连线唯一指向选中图
        expect(state.nodes[0].data.previewImageUrl).toBe('/b.png');
        expect(state.firstFrameConnections).toEqual([
            { id: 1, from: newImage.id, to: 7 },
        ]);

        // 选中视频连线排在该帧 video 连线首位（回转 W→S 选中还原）
        const videoConns = state.connections.filter(c => {
            const toNode = state.nodes.find(n => n.id === c.to);
            return c.from === 7 && toNode && toNode.type === 'video';
        });
        expect(videoConns[0].to).toBe(newVideo.id);

        // 尾帧：故事板有值才覆盖
        expect(state.nodes[0].data.lastFrameUrl).toBe('/last.png');
        // 合并有新增时触发渲染与保存
        expect(ctx.renderAllConnections).toHaveBeenCalled();
        expect(ctx.safeAutoSave).toHaveBeenCalled();
    });

    it('画布已是最新：不新建、不保存、无 toast', () => {
        const state = makeCanvasState();
        // 画布已有资产包的全部 URL 且选中一致
        state.nodes[0].data.previewImageUrl = '/a.png';
        state.nodes[0].data.lastFrameUrl = '';
        const ctx = makeCtx(state);
        const res = Sync._internals.applyPayload({
            scenes: [scenePayload({
                first_frames: [{ id: 1, url: '/a.png' }],
                videos: [{ id: 3, url: '/v1.mp4' }],
                selected_first_frame_url: '/a.png',
                selected_video_url: '/v1.mp4',
                last_frame_url: '',
            })],
        }, ctx);

        expect(res.addedImages).toBe(0);
        expect(res.addedVideos).toBe(0);
        // 选中与尾帧均无变化（画布当前值与包一致）：不渲染不保存
        // ——previewImageUrl/首帧连线本就指向 /a.png，video 连线唯一
        expect(res.changed).toBe(false);
        expect(ctx.safeAutoSave).not.toHaveBeenCalled();
        expect(ctx.showToast).not.toHaveBeenCalled();
    });

    it('仅选中变化（无新增节点）也要渲染保存', () => {
        const state = makeCanvasState();
        state.nodes[0].data.previewImageUrl = '/a.png';
        state.nodes.push({ id: 30, type: 'video', x: 2760, y: 280, data: { url: '/v2.mp4' } });
        state.connections.push({ id: 3, from: 7, to: 30 });
        const ctx = makeCtx(state);
        const res = Sync._internals.applyPayload({
            scenes: [scenePayload({
                first_frames: [{ id: 1, url: '/a.png' }],
                videos: [{ id: 3, url: '/v1.mp4' }, { id: 4, url: '/v2.mp4' }],
                selected_first_frame_url: '/a.png',
                selected_video_url: '/v2.mp4',
                last_frame_url: '',
            })],
        }, ctx);

        expect(res.addedImages).toBe(0);
        expect(res.addedVideos).toBe(0);
        expect(res.changed).toBe(true);              // 选中视频连线重排
        expect(ctx.safeAutoSave).toHaveBeenCalled();
    });

    it('匹配不到分镜帧的场景跳过（不报错）', () => {
        const state = makeCanvasState();
        const ctx = makeCtx(state);
        const res = Sync._internals.applyPayload({
            scenes: [scenePayload({ source_shot_key: 'not_exist' })],
        }, ctx);
        expect(res.skippedScenes).toBe(1);
        expect(res.addedImages).toBe(0);
    });

    it('幂等：同一资产包重复应用第二次无新增', () => {
        const state = makeCanvasState();
        const ctx1 = makeCtx(state);
        const r1 = Sync._internals.applyPayload({ scenes: [scenePayload()] }, ctx1);
        const ctx2 = makeCtx(state);
        const r2 = Sync._internals.applyPayload({ scenes: [scenePayload()] }, ctx2);
        expect(r1.addedImages + r1.addedVideos).toBeGreaterThan(0);
        expect(r2.addedImages).toBe(0);
        expect(r2.addedVideos).toBe(0);
    });
});
