/**
 * 回归（2026-11-13，会话 904714e1）：Agent 模式选 MiniMax H3（首尾帧）上传图片点生成，
 * 任务创建成功后 clearAllMedia() 使 hasUploadedImage true→false，watcher else 分支无条件
 * 改选 text_to_video 槽位偏好（该用户存的是 Seedance 2.5），界面模型被"自动切换"。
 * 实际生成走的是 MiniMax H3（后端日志 minimax_h3_runninghub_v1 证实），纯前端显示/状态被改。
 *
 * 契约（hasUploadedImage true→false 时）：
 * 1) 当前模型本身在文生视频列表（双分类，如 Seedance 2.5）→ 保留用户选择；
 * 2) 否则优先同家族文生模型（minimax_h3_image_to_video → minimax_h3_text_to_video）；
 * 3) 无家族匹配才回退 text_to_video 槽位偏好 → localStorage → 列表第一项。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

// ---- 提取被测源码切片（与页面真实实现保持一致） ----
function extractHelpers() {
    const start = source.indexOf('function findVideoModelInList(');
    expect(start, 'findVideoModelInList 应存在').toBeGreaterThan(-1);
    const end = source.indexOf('function modelSupportsReferenceSlot', start);
    expect(end, 'modelSupportsReferenceSlot 应紧随 helper 之后').toBeGreaterThan(start);
    const block = source.slice(start, end);
    return new Function(`${block}\nreturn { findVideoModelInList, findSameFamilyTextToVideoModel };`)();
}

function extractHasUploadedImageWatcher() {
    const start = source.indexOf('Vue.watch(hasUploadedImage, async (newVal, oldVal) => {');
    expect(start, 'hasUploadedImage watcher 应存在').toBeGreaterThan(-1);
    const end = source.indexOf('// 监听视频生成方式变化', start);
    expect(end, 'watcher 结束标记应存在').toBeGreaterThan(start);
    return source.slice(start, end);
}

const { findVideoModelInList, findSameFamilyTextToVideoModel } = extractHelpers();
const watcherSlice = extractHasUploadedImageWatcher();

// ---- 构造模型列表（对齐 config/unified_config.py 真实 key/short_key） ----
const MINIMAX_H3_T2V = { key: 'minimax_h3_text_to_video', short_key: 'minimax_h3_t2v', value: 'minimax_h3_t2v', name: 'MiniMax H3' };
const SEEDANCE_2_5 = { key: 'seedance_2_5_image_to_video', short_key: 'seedance_2_5', value: 'seedance_2_5', name: 'Seedance 2.5（效果，36算力）' };
const WAN3_T2V = { key: 'wan3_text_to_video', short_key: 'wan3_t2v', value: 'wan3_t2v', name: '万相3.0 (文生)' };
const T2V_LIST = [MINIMAX_H3_T2V, SEEDANCE_2_5, WAN3_T2V];

// 槽位偏好模拟：该用户 marketing_ui video.text_to_video 槽存的是 Seedance 2.5（task_id=36）
const slotPreference = (slot, models) => models.find(m => m.key === 'seedance_2_5_image_to_video') || null;

async function runWatcherTrueToFalse({ selectedKey, selectedName }) {
    let captured = null;
    const Vue = { watch: (target, cb) => { captured = cb; } };
    const state = {
        selectedVideoModelName: { value: selectedName },
        selectedVideoModelKey: { value: selectedKey },
        selectedImageModel: { value: '' },
        selectedImageModelKey: { value: '' },
    };
    const refreshCalls = { count: 0 };
    const harness = new Function(
        'Vue', 'hasUploadedImage', 'restoringGenerationParams', 'isVideoMode',
        'allImageEditModels', 'allImageModels', 'allImageToVideoModels', 'allTextToVideoModels',
        'modelForMediaSlot', 'selectedImageModel', 'selectedImageModelKey', 'refreshModelSettings',
        'videoImageMode', 'pickModelForVideoSlot', 'userId', 'worldId', 'fetch', 'authToken',
        'checkAuthResponse', 'window', 'savedImg2VidModelKey', 'savedImg2VidModelName',
        'localStorage', 'selectedVideoModelName', 'selectedVideoModelKey',
        'findVideoModelInList', 'findSameFamilyTextToVideoModel',
        `${watcherSlice};`
    );
    harness(
        Vue, { value: false }, false, { value: true },
        { value: [] }, { value: [] }, { value: [] }, { value: T2V_LIST },
        slotPreference, state.selectedImageModel, state.selectedImageModelKey, () => { refreshCalls.count += 1; },
        { value: 'first_last_frame' }, () => null, { value: '1' }, { value: '1' }, async () => ({}), { value: 'token' },
        () => true, {}, { value: '' }, { value: '' },
        { getItem: () => null }, state.selectedVideoModelName, state.selectedVideoModelKey,
        findVideoModelInList, findSameFamilyTextToVideoModel
    );
    expect(captured, 'watcher 回调应被注册').toBeTypeOf('function');
    await captured(false, true);
    return state;
}

describe('findSameFamilyTextToVideoModel', () => {
    it('首尾帧 key → 同家族文生模型', () => {
        expect(findSameFamilyTextToVideoModel(T2V_LIST, 'minimax_h3_image_to_video')).toBe(MINIMAX_H3_T2V);
    });

    it('参考生 key → 同家族文生模型', () => {
        expect(findSameFamilyTextToVideoModel(T2V_LIST, 'minimax_h3_reference_to_video')).toBe(MINIMAX_H3_T2V);
    });

    it('short_key 入参同样命中', () => {
        expect(findSameFamilyTextToVideoModel(T2V_LIST, 'minimax_h3')).toBe(MINIMAX_H3_T2V);
    });

    it('双分类模型经前缀匹配命中自身（文生能力由 categories 提供）', () => {
        expect(findSameFamilyTextToVideoModel(T2V_LIST, 'seedance_2_5_image_to_video')).toBe(SEEDANCE_2_5);
    });

    it('无家族匹配返回 null（走槽位偏好回退）', () => {
        expect(findSameFamilyTextToVideoModel(T2V_LIST, 'vidu_q2_image_to_video')).toBeNull();
    });

    it('空 key / 空列表返回 null', () => {
        expect(findSameFamilyTextToVideoModel(T2V_LIST, '')).toBeNull();
        expect(findSameFamilyTextToVideoModel([], 'minimax_h3_image_to_video')).toBeNull();
    });
});

describe('hasUploadedImage true→false（发送成功后 clearAllMedia 路径）', () => {
    it('MiniMax H3 首尾帧 → 切同家族 MiniMax H3 (文生)，而不是槽位偏好的 Seedance 2.5', async () => {
        const state = await runWatcherTrueToFalse({
            selectedKey: 'minimax_h3_image_to_video',
            selectedName: 'MiniMax H3（性价比，12算力）',
        });
        expect(state.selectedVideoModelKey.value).toBe('minimax_h3_text_to_video');
        expect(state.selectedVideoModelName.value).toBe('MiniMax H3');
    });

    it('双分类模型（Seedance 2.5）本身支持文生视频 → 保留用户选择', async () => {
        const state = await runWatcherTrueToFalse({
            selectedKey: 'seedance_2_5_image_to_video',
            selectedName: 'Seedance 2.5（效果，36算力）',
        });
        expect(state.selectedVideoModelKey.value).toBe('seedance_2_5_image_to_video');
        expect(state.selectedVideoModelName.value).toBe('Seedance 2.5（效果，36算力）');
    });

    it('无同家族文生模型 → 回退 text_to_video 槽位偏好', async () => {
        const state = await runWatcherTrueToFalse({
            selectedKey: 'vidu_q2_image_to_video',
            selectedName: 'Vidu-Q2',
        });
        expect(state.selectedVideoModelKey.value).toBe('seedance_2_5_image_to_video');
    });

    it('未选中任何模型 → 回退槽位偏好', async () => {
        const state = await runWatcherTrueToFalse({ selectedKey: '', selectedName: '' });
        expect(state.selectedVideoModelKey.value).toBe('seedance_2_5_image_to_video');
    });
});
