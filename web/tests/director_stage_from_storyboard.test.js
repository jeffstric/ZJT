/**
 * 故事板 3D 空间 → 导演台转换测试。
 *
 * 行为部分：jsdom 下加载 director_stage_from_storyboard.js（IIFE 挂 window），
 * 经测试钩子 __dsFromSbInternals 验证轻量记录器重放（增量链/链边界/异常
 * 收集）与 directorData 映射（人偶 rotY 度对度、机位、timeline 结构）。
 * 接线部分：源码断言（分镜帧按钮/脚本引入/i18n/后端透传字段）。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, beforeAll } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

const moduleSrc = readSource('web/js/director_stage_from_storyboard.js');

function makeFrame(id, shotNumber, code, seqStart) {
  return {
    id,
    type: 'shot_frame',
    title: `分镜${shotNumber}`,
    x: 100,
    y: 100,
    data: {
      shotJson: {
        shot_number: shotNumber,
        three_scene_code: code,
        ...(seqStart ? { three_scene_seq_start: true } : {}),
      },
    },
  };
}

describe('故事板3D空间→导演台：重放与映射（行为）', () => {
  beforeAll(() => {
    // 模块 IIFE 只挂 window.*，重复执行幂等
    window.eval(moduleSrc);
  });

  it('记录器重放增量链：moveActor 累积、setCamera 记录机位', () => {
    const { createRecorderContext, runRecorderCode } = window.__dsFromSbInternals;
    const { ctx, helpers } = createRecorderContext();
    runRecorderCode(ctx, helpers,
      "startScene('大厅');\nmakeActor('李卫国', 0.3, -0.3, {facing: 180});\nmakeActor('赵志高', -0.5, 0.5, {facing: 0});\nsetCamera(-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50);",
      '分镜1');
    runRecorderCode(ctx, helpers,
      "moveActor('赵志高', -1.0, 1.0, {facing: 30});\nsetCamera(-1.5, 1.6, 2.2, -0.5, 1.0, 0.3, 45);",
      '分镜2');
    expect(ctx.actors['李卫国']).toEqual({ name: '李卫国', x: 0.3, z: -0.3, facing: 180 });
    expect(ctx.actors['赵志高']).toEqual({ name: '赵志高', x: -1, z: 1, facing: 30 });
    expect(ctx.camera).toEqual({ eye: [-1.5, 1.6, 2.2], target: [-0.5, 1, 0.3], fov: 45 });
    expect(ctx.errors).toEqual([]);
  });

  it('startScene 清空旧序列实体；异常代码收集不中断', () => {
    const { createRecorderContext, runRecorderCode } = window.__dsFromSbInternals;
    const { ctx, helpers } = createRecorderContext();
    runRecorderCode(ctx, helpers, "makeActor('A', 1, 1);", 'S1');
    runRecorderCode(ctx, helpers, "startScene('新场景');\nmakeActor('B', 2, 2);", 'S2');
    expect(ctx.actors['A']).toBeUndefined();
    expect(ctx.actors['B']).toEqual({ name: 'B', x: 2, z: 2, facing: 0 });
    runRecorderCode(ctx, helpers, "moveActor('不存在', 0, 0);", 'S3');
    expect(ctx.errors).toHaveLength(1);
    expect(ctx.errors[0].shot).toBe('S3');
  });

  it('分镜帧链重放：从最近序列首镜切链，硬切后旧实体不残留', () => {
    const { replayShotSpatialChain } = window.__dsFromSbInternals;
    // state.js 是顶层 const（全局词法、不挂 window），模块经裸引用读取：
    // 测试经 globalThis 注入（属性对全局词法读取可见；ESM 严格模式禁隐式全局）
    globalThis.state = {
      nodes: [
        makeFrame(1, 1, "startScene('天台');\nmakeActor('苏雨晴', 0, 4, {facing: 0});\nsetCamera(-1.5, 1.3, 1, 0, 1.4, 0.8, 50);", true),
        makeFrame(2, 2, "moveActor('苏雨晴', 1, 3);\nsetCamera(0, 1.5, 2, 1, 1, 3, 45);", false),
        makeFrame(3, 3, "startScene('办公区');\nmakeActor('李卫国', 0, 0);\nsetCamera(0.8, 1.8, -1.5, 0, 0.8, 0, 55);", true),
        makeFrame(4, 4, "moveActor('李卫国', 0.5, 0.5);\nsetCamera(1, 1.5, -2.5, 0.5, 1.4, 0.5, 48);", false),
      ],
    };
    // 分镜4 属于第二序列（首镜=分镜3），不应重放天台序列
    const rec = replayShotSpatialChain(globalThis.state.nodes[3]);
    expect(rec.replayed).toBe(2);
    expect(rec.ctx.actors['苏雨晴']).toBeUndefined();
    expect(rec.ctx.actors['李卫国']).toEqual({ name: '李卫国', x: 0.5, z: 0.5, facing: 0 });
    expect(rec.ctx.camera.fov).toBe(48);
  });

  it('全局 state 缺失时链重放安全返回 null（不抛错）', () => {
    const { replayShotSpatialChain } = window.__dsFromSbInternals;
    const saved = globalThis.state;
    try {
      delete globalThis.state;
      expect(replayShotSpatialChain({ id: 1, type: 'shot_frame', data: { shotJson: { shot_number: 1, three_scene_code: 'setCamera(0,1,5,0,1,0,50);' } } })).toBeNull();
    } finally {
      globalThis.state = saved;
    }
  });

  it('映射 directorData：人偶 rotY 度对度、机位、timeline 结构、version 2', () => {
    const { createRecorderContext, runRecorderCode, buildDirectorData } = window.__dsFromSbInternals;
    const { ctx, helpers } = createRecorderContext();
    runRecorderCode(ctx, helpers,
      "makeActor('李卫国', 0.3, -0.3, {facing: 180});\nsetCamera(-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50);",
      'S1');
    const dd = buildDirectorData({ ctx });
    expect(dd.version).toBe(2);
    expect(dd.puppets).toHaveLength(1);
    expect(dd.puppets[0]).toMatchObject({ name: '李卫国', x: 0.3, z: -0.3, rotY: 180, bodyType: 'man' });
    // 朝向约定两侧一致（度、0°=+Z）：facing 直接落 rotY
    expect(dd.cameras).toEqual([{
      id: 'cam1', name: '镜头 1',
      pos: [-0.6, 1.5, 1.8], target: [0.2, 0.8, -0.2], fov: 50,
    }]);
    expect(dd.activeCameraId).toBe('cam1');
    expect(dd.camera.pos).toEqual([-0.6, 1.5, 1.8]);
    expect(dd.environment).toBeNull();
    const camTrack = dd.timeline.tracks.find((t) => t.kind === 'camera');
    expect(camTrack.keys[0]).toMatchObject({ t: 0, fov: 50, camId: 'cam1', cut: false });
    const puppetTrack = dd.timeline.tracks.find((t) => t.kind === 'puppet');
    expect(puppetTrack.keys[0]).toMatchObject({ t: 0, x: 0.3, z: -0.3, rotY: 180 });
  });

  it('无机位时代码给导演台默认机位（编辑器初始 virtualCamCfg）', () => {
    const { createRecorderContext, buildDirectorData } = window.__dsFromSbInternals;
    const { ctx } = createRecorderContext();
    const dd = buildDirectorData({ ctx });
    expect(dd.cameras[0].pos).toEqual([0, 1.5, 4.2]);
    expect(dd.cameras[0].fov).toBe(35);
  });
});

describe('故事板3D空间→导演台：接线（源码断言）', () => {
  it('转换模块暴露入口与按钮判定', () => {
    expect(moduleSrc).toContain('window.openDirectorStageFromShotFrame');
    expect(moduleSrc).toContain('window.shotFrameHasSpatialCode');
  });

  it('分镜帧节点：携带 3D 代码时渲染导演台按钮，双状态文案（未关联=创建 / 已关联=打开）', () => {
    const frameSrc = readSource('web/js/shot_frame_node.js');
    expect(frameSrc).toContain('shot-frame-open-director-btn');
    expect(frameSrc).toContain('shotFrameHasSpatialCode(node)');
    expect(frameSrc).toContain('shotFrameDirectorLinked(node)');
    expect(frameSrc).toContain("t('shot_frame_create_director_btn')");
    expect(frameSrc).toContain("t('shot_frame_open_director_btn')");
    expect(frameSrc).toContain('openDirectorStageFromShotFrame(id)');
  });

  it('转换后按钮文案即时翻转 + 关联判定暴露', () => {
    expect(moduleSrc).toContain('window.shotFrameDirectorLinked');
    expect(moduleSrc).toContain("frameEl.textContent = tr('shot_frame_open_director_btn'");
  });

  it('video_workflow.html 引入转换模块（导演台节点之后）', () => {
    const html = readSource('web/video_workflow.html');
    const nodeIdx = html.indexOf('director_stage_node.js');
    const convIdx = html.indexOf('director_stage_from_storyboard.js');
    expect(nodeIdx).toBeGreaterThan(-1);
    expect(convIdx).toBeGreaterThan(nodeIdx);
  });

  it('i18n 双语文案齐全', () => {
    const zh = readSource('web/i18n/locales/zh-CN/video_workflow.json');
    const en = readSource('web/i18n/locales/en/video_workflow.json');
    for (const src of [zh, en]) {
      expect(src).toContain('"shot_frame_open_director_btn"');
      expect(src).toContain('"director_stage_from_sb_no_data"');
      expect(src).toContain('"director_stage_from_sb_skipped"');
    }
  });

  it('后端转换透传字段（shotJson.three_scene_code + seq_start）', () => {
    const pySrc = readSource('api/storyboard_conversion.py');
    expect(pySrc).toContain("shot['three_scene_code']");
    expect(pySrc).toContain("shot['three_scene_seq_start']");
    expect(pySrc).toContain('is_sequence_start_code(three_code)');
  });
});

describe('故事板3D空间→导演台：空镜检查（与 spatial_camera_edit.cameraSeesActors 逻辑互为镜像）', () => {
  it('分镜5 实测数据：机位朝空地 → visible=0；正常朝向 → 可见', () => {
    const { cameraSeesActors } = window.__dsFromSbInternals;
    // 分镜5 实测：角色均在 (-1.8~-1, 1~1.2)，机位看向 (3.9, 1.45, -1.1)
    const empty = cameraSeesActors(
      { eye: [2, 1.65, 2.6], target: [3.9, 1.45, -1.1], fov: 50 },
      [{ x: -1.8, z: 1.2 }, { x: -1.0, z: 1.0 }],
    );
    expect(empty).toEqual({ visible: 0, total: 2 });

    // 分镜1：机位 (-0.6,1.5,1.8) 看向 (0.2,0.8,-0.2)，两角色在其正前方
    const ok = cameraSeesActors(
      { eye: [-0.6, 1.5, 1.8], target: [0.2, 0.8, -0.2], fov: 50 },
      [{ x: 0.3, z: -0.3 }, { x: -0.5, z: 0.5 }],
    );
    expect(ok.visible).toBe(2);
  });
});

describe('导演台编辑器：对话改机位（接线层源码断言）', () => {
  const editorSrc = readSource('web/js/director_stage_editor.js');
  const serverSrc = readSource('server.py');
  const cssSrc = readSource('web/css/director_stage.css');

  it('编辑器具备对话条 UI（输入条/模型选择/发送/提示）', () => {
    expect(editorSrc).toContain("id=\"dsChatBar\"");
    expect(editorSrc).toContain("id=\"dsChatInput\"");
    expect(editorSrc).toContain("id=\"dsChatModel\"");
    expect(editorSrc).toContain("id=\"dsChatSend\"");
    expect(editorSrc).toContain("id=\"dsChatNote\"");
  });

  it('编辑器接线：sendCameraChat / loadChatModels / Esc 输入框守卫', () => {
    expect(editorSrc).toContain('sendCameraChat = function');
    expect(editorSrc).toContain('loadChatModels = function');
    expect(editorSrc).toContain("fetch('/api/video-workflow/camera-chat'");
    expect(editorSrc).toContain('current_camera');
    // 输入框聚焦时 Esc 不应关闭整个导演台
    expect(editorSrc).toContain('inField && document.activeElement && document.activeElement.blur');
  });

  it('后端路由：/api/video-workflow/camera-chat 复用机位对话服务', () => {
    expect(serverSrc).toContain("'/api/video-workflow/camera-chat'");
    expect(serverSrc).toContain('VideoWorkflowCameraChatRequest');
    expect(serverSrc).toContain('parse_camera_instruction');
    // 与故事板场景路由同款模型归一化
    expect(serverSrc).toContain('normalize_model_selection_refs');
  });

  it('CSS：对话条与提示样式', () => {
    expect(cssSrc).toContain('.ds-chatbar');
    expect(cssSrc).toContain('.ds-chat-note.is-error');
  });
});
