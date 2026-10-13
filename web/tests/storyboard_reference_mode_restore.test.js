// 参考生视频故事板进入「视频生成」模式时，videoImageMode 必须保持 multi_reference，
// 不得回退为首尾帧。
//
// 背景 BUG：拆分时已把 video_gen_mode 持久化进 storyboard config_json，bootstrap
// restoreUiConfig 也能恢复 multi_reference；但随后 ensureVideoImageModeSupported()
// 按「当前选中模型」校验能力，而旧实现 getSelectedVideoModel() 在参考模式 + 无输入图时
// 会解析到文生视频模型（后端不下发 supported_image_modes），能力并集退化为
// ['first_last_frame']，模式被强制重置回首尾帧——用户每次进入视频生成都看到首尾帧。

import state, {
    setModels,
    restoreUiConfig,
    ensureVideoImageModeSupported,
    getSelectedVideoModel,
    getAvailableVideoImageModes,
} from '../js/storyboard/state.js';

const REF_MODEL = {
    task_id: 9101,
    key: 'minimax_h3_r2v',
    name: 'MiniMax H3',
    supported_image_modes: ['multi_reference'],
};

const I2V_MODEL = {
    task_id: 9102,
    key: 'kling_v2',
    name: 'Kling V2',
    supported_image_modes: ['first_last_frame'],
};

describe('storyboard reference mode default on video chat mode', () => {
    it('restored multi_reference survives ensure when entering video mode (no inputs)', () => {
        setModels({
            image_to_video_models: [I2V_MODEL, REF_MODEL],
            video_models: [I2V_MODEL, REF_MODEL],
        });
        // 模拟 bootstrap：config_json 恢复（拆分时已持久化 video_gen_mode）
        restoreUiConfig({ videoImageMode: 'multi_reference', chatMode: 'video' });
        expect(state.videoImageMode).toBe('multi_reference');
        // 进入视频生成模式时 bootstrap / chat-mode 切换都会执行能力校验——不得回退首尾帧
        ensureVideoImageModeSupported();
        expect(state.videoImageMode).toBe('multi_reference');
        // 参考模式固定解析「参考视频槽」模型，与提交链路 getSelectedVideoTaskId 同口径
        expect(getSelectedVideoModel()?.task_id).toBe(9101);
    });

    it('mode selector offers reference mode from the union of all video models', () => {
        setModels({ image_to_video_models: [I2V_MODEL, REF_MODEL] });
        const modes = getAvailableVideoImageModes();
        expect(modes).toContain('first_last_frame');
        expect(modes).toContain('multi_reference');
    });

    it('falls back to first_last_frame when no model supports reference', () => {
        setModels({ image_to_video_models: [I2V_MODEL] });
        expect(getAvailableVideoImageModes()).toEqual(['first_last_frame']);
    });
});
