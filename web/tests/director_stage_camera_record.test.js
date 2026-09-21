/**
 * 导演台「多机位 + 录制视频」接线层源码断言。
 *
 * 覆盖两条新链路的防回退断言：
 * 1. 多机位：editor 的 cameras 数据模型（迁移/序列化/机位槽方法）、
 *    timeline 相机键 camId、右栏机位组 UI；
 * 2. 录制视频：顶栏 ⏺ 按钮、MediaRecorder 生命周期（start/stop/discard/upload）、
 *    播放结束/停止自动停录制、close 丢弃、画布 video 节点 helper 与 i18n。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

const editorSrc = readSource('web/js/director_stage_editor.js');
const timelineSrc = readSource('web/js/director_stage_timeline.js');
const nodeSrc = readSource('web/js/director_stage_node.js');
const zhI18n = readSource('web/i18n/locales/zh-CN/video_workflow.json');
const enI18n = readSource('web/i18n/locales/en/video_workflow.json');

describe('导演台：多机位（接线层源码断言）', () => {
  it('editor 具备机位数据模型：迁移/序列化/机位槽方法', () => {
    expect(editorSrc).toContain('Array.isArray(d.cameras)');      // restore 优先读 cameras（旧 camera 迁移）
    expect(editorSrc).toContain('activeCameraId');
    expect(editorSrc).toContain('applyCameraSlot');
    expect(editorSrc).toContain('updateCameraSlot');
    expect(editorSrc).toContain('addCameraSlot');
    expect(editorSrc).toContain('removeCameraSlot');
    expect(editorSrc).toContain('getActiveCamera');
  });

  it('serializeData 输出 cameras + activeCameraId，并保留冗余旧 camera 字段', () => {
    const idx = editorSrc.indexOf('DirectorEditor.prototype.serializeData = function');
    expect(idx).toBeGreaterThan(-1);
    const block = editorSrc.slice(idx, idx + 2200);
    expect(block).toContain('cameras: this.cameras.map');
    expect(block).toContain('activeCameraId: this.activeCameraId');
    expect(block).toContain('// 冗余旧字段');
  });

  it('右栏镜头设置面板渲染机位组', () => {
    expect(editorSrc).toContain('buildCamerasGroupHtml');
    expect(editorSrc).toContain('dsAddCamBtn');
    expect(editorSrc).toContain('data-cam-act="update"');
  });

  it('timeline 相机键记录/保留 camId；相机轨按机位 id 分轨（多机位 lane）', () => {
    expect(timelineSrc).toContain('camId');
    expect(timelineSrc).toContain('editor.activeCameraId');
    expect(timelineSrc).toContain("ref.indexOf('camera:') === 0");  // camera:<id> 轨道引用
    expect(timelineSrc).toContain('liveCameraLanes');               // 机位删除后其轨不参与求值
    expect(timelineSrc).toContain('takeover');                      // 跨轨接管=隐式硬切
  });
});

describe('导演台：录制视频（接线层源码断言）', () => {
  it('顶栏录制按钮 + MediaRecorder 生命周期方法', () => {
    expect(editorSrc).toContain('id="dsRecordBtn"');
    expect(editorSrc).toContain('MediaRecorder');
    expect(editorSrc).toContain('captureStream(30)');
    expect(editorSrc).toContain('startRecording = function');
    expect(editorSrc).toContain('stopRecording = function');
    expect(editorSrc).toContain('discardRecording = function');
    expect(editorSrc).toContain('_uploadRecording = async function');
    expect(editorSrc).toContain('createDirectorStageVideoNode');
  });

  it('播放结束/停止自动结束录制；关闭编辑器丢弃录制', () => {
    expect(timelineSrc).toContain('stopRecording');
    // close() 丢弃未完成录制（避免后台上传半成品）
    const idx = editorSrc.indexOf('DirectorEditor.prototype.close = function');
    expect(idx).toBeGreaterThan(-1);
    expect(editorSrc.slice(idx, idx + 400)).toContain('discardRecording');
  });

  it('画布视频节点 helper：创建 video 节点并回填预览', () => {
    expect(nodeSrc).toContain('createDirectorStageVideoNode');
    expect(nodeSrc).toContain('window.createDirectorStageVideoNode');
    expect(nodeSrc).toContain("createVideoNode({");
    expect(nodeSrc).toContain('setupVideoThumbnail');
    expect(nodeSrc).toContain('.video-preview-field');
  });

  it('i18n 两个语言均有视频节点名 key', () => {
    expect(zhI18n).toContain('director_stage_video_name');
    expect(enI18n).toContain('director_stage_video_name');
  });
});
