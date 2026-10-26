// 「生成 3D 导演台」开关的 UI 配置语义：
// - enableDirectorStage：生成分镜弹窗内的勾选值（默认关闭），随 config_json 持久化；
// - directorStageGenerated：最近一次生成时的实际开关值（后端写入 config_json），
//   显式 false 时前端隐藏分镜「3D」空间预览入口；无该字段（旧故事板）保持展示。

import state, {
    restoreUiConfig,
    serializeUiConfig,
} from '../js/storyboard/state.js';

describe('storyboard director stage ui config', () => {
    it('defaults: option off, generated flag on (backwards compatible)', () => {
        expect(state.enableDirectorStage).toBe(false);
        expect(state.directorStageGenerated).toBe(true);
    });

    it('restoreUiConfig applies persisted option and generated flag', () => {
        restoreUiConfig({ enableDirectorStage: true, directorStageGenerated: false });
        expect(state.enableDirectorStage).toBe(true);
        expect(state.directorStageGenerated).toBe(false);

        restoreUiConfig({ enableDirectorStage: false, directorStageGenerated: true });
        expect(state.enableDirectorStage).toBe(false);
        expect(state.directorStageGenerated).toBe(true);
    });

    it('legacy storyboard without directorStageGenerated keeps 3D entry visible', () => {
        restoreUiConfig({});
        expect(state.directorStageGenerated).toBe(true);
    });

    it('serializeUiConfig round-trips enableDirectorStage', () => {
        state.enableDirectorStage = true;
        const cfg = serializeUiConfig();
        expect(cfg.enableDirectorStage).toBe(true);
        state.enableDirectorStage = false;
        expect(serializeUiConfig().enableDirectorStage).toBe(false);
    });
});
