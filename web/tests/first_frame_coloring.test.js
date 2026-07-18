/**
 * 故事板分镜首帧涂色适配层单测
 */
import { describe, expect, it, beforeEach, vi } from 'vitest';

// 最小 state stub（first_frame_coloring 依赖）
vi.mock('../js/storyboard/state.js', () => {
  const state = {
    scenes: [],
    sceneCandidates: {},
    chatMode: 'dialogue',
    isPlaying: false,
    currentSceneId: 1,
  };
  return {
    default: state,
    getCurrentScene: () => state.scenes.find(s => s.id === state.currentSceneId) || state.scenes[0] || null,
    refreshSceneFirstFrameSlot: vi.fn(),
  };
});

vi.mock('../js/storyboard/api.js', () => ({
  uploadSceneAsset: vi.fn(),
}));

vi.mock('../js/storyboard/utils.js', () => ({
  showToast: vi.fn(),
}));

vi.mock('../js/storyboard/candidate_selection_state.js', () => ({
  choosePreviewMedia: (scene) => {
    if (scene?.previewAssetType === 'video' && scene.videoUrl) {
      return { kind: 'video', url: scene.videoUrl };
    }
    if (scene?.firstFrameUrl) {
      return { kind: 'image', url: scene.firstFrameUrl };
    }
    return { kind: 'empty', url: '' };
  },
}));

const {
  canColorFirstFrame,
  getColorFirstFrameBlockMessage,
  dataUrlToBlob,
  applyColoredAssetToScene,
} = await import('../js/storyboard/first_frame_coloring.js');
const stateMod = await import('../js/storyboard/state.js');
const state = stateMod.default;

describe('canColorFirstFrame', () => {
  it('无分镜不允许', () => {
    expect(canColorFirstFrame(null).allowed).toBe(false);
    expect(canColorFirstFrame(null).reason).toBe('no_scene');
  });

  it('播放中不允许', () => {
    expect(
      canColorFirstFrame(
        { id: 1, firstFrameUrl: 'https://cdn.example.com/a.png' },
        { isPlaying: true },
      ),
    ).toEqual({ allowed: false, reason: 'playing' });
  });

  it('当前预览是视频时不允许', () => {
    expect(
      canColorFirstFrame({
        id: 1,
        firstFrameUrl: 'https://cdn.example.com/a.png',
        videoUrl: 'https://cdn.example.com/v.mp4',
        previewAssetType: 'video',
      }),
    ).toEqual({ allowed: false, reason: 'not_image' });
  });

  it('有首帧图时允许并返回 url', () => {
    expect(
      canColorFirstFrame({
        id: 1,
        firstFrameUrl: 'https://cdn.example.com/a.png',
        previewAssetType: 'first_frame',
      }),
    ).toEqual({
      allowed: true,
      reason: 'ok',
      url: 'https://cdn.example.com/a.png',
    });
  });

  it('逗号拼接多图 URL 视为不可用', () => {
    expect(
      canColorFirstFrame({
        id: 1,
        firstFrameUrl: 'https://a.png,https://b.png',
      }).allowed,
    ).toBe(false);
  });
});

describe('getColorFirstFrameBlockMessage', () => {
  it('playing / no_image 有可读文案', () => {
    expect(getColorFirstFrameBlockMessage('playing')).toMatch(/播放|涂色/);
    expect(getColorFirstFrameBlockMessage('no_image')).toMatch(/分镜图|生成/);
  });
});

describe('dataUrlToBlob', () => {
  it('解析 PNG dataURL', () => {
    // 1x1 透明 PNG
    const dataUrl =
      'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
    const blob = dataUrlToBlob(dataUrl);
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('image/png');
    expect(blob.size).toBeGreaterThan(0);
  });

  it('非法 dataURL 抛错', () => {
    expect(() => dataUrlToBlob('not-a-data-url')).toThrow();
  });
});

describe('applyColoredAssetToScene', () => {
  beforeEach(() => {
    state.sceneCandidates = {};
  });

  it('写入 firstFrameUrl / selectedFirstFrameId 并插入候选', () => {
    const scene = {
      id: 9,
      firstFrameUrl: 'https://old.png',
      selectedFirstFrameId: 1,
      previewAssetType: 'video',
    };
    state.sceneCandidates[9] = {
      images: [{ id: 1, url: 'https://old.png', selected: true }],
      videos: [],
    };

    applyColoredAssetToScene(scene, {
      assetId: 42,
      resultUrl: 'https://colored.png',
      assetType: 'first_frame',
    });

    expect(scene.firstFrameUrl).toBe('https://colored.png');
    expect(scene.selectedFirstFrameId).toBe(42);
    expect(scene.previewAssetType).toBe('first_frame');
    const images = state.sceneCandidates[9].images;
    expect(images[0]).toMatchObject({ id: 42, url: 'https://colored.png', selected: true });
    expect(images.find(i => i.id === 1)?.selected).toBe(false);
  });
});
