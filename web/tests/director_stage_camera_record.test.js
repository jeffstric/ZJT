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

  it('撤销先恢复机位列表和激活机位，再恢复时间轴', () => {
    expect(editorSrc).toContain('restoreCamerasFromData');
    const rebuild = editorSrc.indexOf('DirectorEditor.prototype.rebuildFromSnapshot = function');
    expect(rebuild).toBeGreaterThan(-1);
    const block = editorSrc.slice(rebuild, rebuild + 1600);
    const camAt = block.indexOf('this.restoreCamerasFromData(snap)');
    const tlAt = block.indexOf('this.restoreTimeline(snap)');
    expect(camAt).toBeGreaterThan(-1);
    expect(tlAt).toBeGreaterThan(camAt);
    // 重开与撤销共用同一恢复函数，避免两套迁移逻辑
    expect(editorSrc).toContain('this.restoreCamerasFromData(d)');
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

  it('导演台打开时 Delete/Backspace 不冒泡到画布', () => {
    expect(editorSrc).not.toContain("this.on(document, 'keydown.directorStage'");
    const idx = editorSrc.indexOf("this.on(document, 'keydown'");
    expect(idx).toBeGreaterThan(-1);
    const block = editorSrc.slice(idx, idx + 1500); // Esc 输入框守卫插入后 Delete 分支后移，加宽切片
    expect(block).toContain("e.key === 'Delete' || e.key === 'Backspace'");
    expect(block).toContain('e.stopPropagation()');
    expect(block).toContain('e.preventDefault()');
    expect(block).toContain('removePuppet');
    const eventsSrc = readSource('web/js/events.js');
    expect(eventsSrc).toContain("getElementById('directorStageOverlay')");
    expect(eventsSrc).toContain("directorOverlay.classList.contains('show')");
  });

  it('关闭时收回已提交站位，重开时套用 0 秒位形', () => {
    expect(timelineSrc).toContain('restoreCommittedEditPose');
    const closeIdx = timelineSrc.indexOf('DirectorEditor.prototype.stopTimelineForClose = function');
    expect(closeIdx).toBeGreaterThan(-1);
    const closeBlock = timelineSrc.slice(closeIdx, closeIdx + 400);
    expect(closeBlock).toContain('this.tl.playhead = 0');
    expect(closeBlock).toContain('this.restoreCommittedEditPose()');
    const restoreIdx = editorSrc.indexOf('this.restoreTimeline(d);');
    expect(restoreIdx).toBeGreaterThan(-1);
    expect(editorSrc.slice(restoreIdx, restoreIdx + 500)).toContain('this.applyTimelineAt(0)');
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
