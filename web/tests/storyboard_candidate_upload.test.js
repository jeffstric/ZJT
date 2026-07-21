import { beforeEach, describe, expect, it } from 'vitest';

import state from '../js/storyboard/state.js';
import { validateCandidateUploadFile } from '../js/storyboard/events.js';
import { renderRightSidebar } from '../js/storyboard/render.js';

describe('分镜候选区上传', () => {
    beforeEach(() => {
        state.sceneCandidates = {};
        state.candidateUploadsBySceneId = {};
        state.candidateDeletesBySceneId = {};
        state.scenes = [];
        state.currentSceneId = null;
    });

    it('分别渲染分镜图与视频上传入口及文件类型约束', () => {
        const html = renderRightSidebar({ id: 12, taskStatus: {} });

        expect(html).toContain('data-candidate-upload-type="first_frame"');
        expect(html).toContain('data-candidate-upload-input="first_frame"');
        expect(html).toContain('data-candidate-upload-type="video"');
        expect(html).toContain('data-candidate-upload-input="video"');
        expect(html).toContain('data-scene-id="12"');
        expect(html).toContain('.mp4,.webm');
    });

    it('仅禁用正在上传的分镜与资产类型按钮', () => {
        state.candidateUploadsBySceneId = {
            12: { video: { uploading: true } },
            13: { first_frame: { uploading: true } },
        };

        const html = renderRightSidebar({ id: 12, taskStatus: {} });
        const imageButton = html.match(/<button[^>]+data-candidate-upload-type="first_frame"[\s\S]*?<\/button>/)?.[0];
        const videoButton = html.match(/<button[^>]+data-candidate-upload-type="video"[\s\S]*?<\/button>/)?.[0];

        expect(imageButton).not.toContain('disabled');
        expect(videoButton).toContain('disabled');
        expect(videoButton).toContain('上传中');
    });

    it('前端格式校验与后端支持范围保持一致', () => {
        expect(validateCandidateUploadFile({ name: 'shot.WEBP', type: 'image/webp' }, 'first_frame')).toBe('');
        expect(validateCandidateUploadFile({ name: 'shot.txt', type: 'text/plain' }, 'first_frame')).toContain('仅支持');
        expect(validateCandidateUploadFile({ name: 'shot.mp4', type: 'video/mp4' }, 'video')).toBe('');
        expect(validateCandidateUploadFile({ name: 'shot.mov', type: 'video/quicktime' }, 'video')).toContain('MP4');
    });

    it('上传后的视频资产会进入视频候选而不是继续显示空状态', () => {
        const scene = {
            id: 12,
            firstFrameUrl: '/upload/storyboard/first_frame/storyboard.png',
            taskStatus: {},
        };
        state.scenes = [scene];
        state.currentSceneId = 12;
        state.sceneCandidates = {
            12: {
                images: [],
                videos: [{
                    id: 88,
                    url: '/upload/storyboard/video/demo.mp4',
                    status: null,
                    selected: true,
                }],
            },
        };

        const html = renderRightSidebar(scene);

        expect(html).toContain('data-candidate-id="88"');
        expect(html).toContain('data-action="delete-scene-candidate"');
        expect(html).toContain('data-candidate-delete-id="88"');
        expect(html).toContain('src="/upload/storyboard/video/demo.mp4#t=0.1"');
        expect(html).not.toContain('poster="/upload/storyboard/first_frame/storyboard.png"');
        expect(html).not.toContain('暂无视频候选');
    });

    it('删除中的候选只禁用自身删除按钮', () => {
        state.sceneCandidates = {
            12: {
                images: [
                    { id: 51, url: '/upload/storyboard/first_frame/a.png', selected: true },
                    { id: 52, url: '/upload/storyboard/first_frame/b.png', selected: false },
                ],
                videos: [],
            },
        };
        state.candidateDeletesBySceneId = { 12: { 51: true } };

        const html = renderRightSidebar({ id: 12, taskStatus: {} });
        const deletingButton = html.match(/<button[^>]+data-candidate-delete-id="51"[\s\S]*?<\/button>/)?.[0];
        const otherButton = html.match(/<button[^>]+data-candidate-delete-id="52"[\s\S]*?<\/button>/)?.[0];

        expect(deletingButton).toContain('disabled');
        expect(deletingButton).toContain('aria-busy="true"');
        expect(otherButton).not.toContain('disabled');
    });
});
