const {
  promptHasShotFrameMention,
  isH3ReferenceVideoModel,
  shotFrameMultiRefLimit,
  placeShotFrameMentionImages,
} = require('../js/shot_frame_video_generator.js');

describe('H3 首帧参考混合实现方（服务端探测选择，前端不再换绑）', () => {
  test('前端不再换绑 task_id：导出面不包含换绑函数与常量', () => {
    const module = require('../js/shot_frame_video_generator.js');
    expect(module.shouldUseH3KeyframeRefModel).toBeUndefined();
    expect(module.resolveShotFrameReferenceSubmitModel).toBeUndefined();
    expect(module.H3_KEYFRAME_REF_ROUTE_ENABLED).toBeUndefined();
    expect(module.H3_KEYFRAME_REF_SHORT_KEY).toBeUndefined();
  });

  test('H3 参考模型识别保持不变（排图与自动带入仍按模型判断）', () => {
    expect(isH3ReferenceVideoModel('minimax_h3_r2v')).toBe(true);
    expect(isH3ReferenceVideoModel('minimax_h3_reference_to_video')).toBe(true);
    expect(isH3ReferenceVideoModel('minimax_h3')).toBe(false);
    expect(isH3ReferenceVideoModel('minimax_h3_t2v')).toBe(false);
  });

  test('张数上限回到模型默认（测试环境无 TaskConfig 时为 5），不再预裁 3', () => {
    expect(shotFrameMultiRefLimit('minimax_h3_r2v')).toBe(5);
    expect(shotFrameMultiRefLimit('seedance_2_0')).toBe(5);
  });

  test('点名排图仍把首尾帧放到两端并改写提示词（服务端按实现方裁 3）', () => {
    const placed = placeShotFrameMentionImages(
      '从 @首帧图 走到 @尾帧图',
      ['m1.png', 'm2.png', 'm3.png'],
      ['图1是角色A', '图2是场景B', '图3是画风C'],
      'first.png',
      'last.png',
      5,
    );
    expect(placed.error).toBe('');
    expect(placed.referenceImageUrls[0]).toBe('first.png');
    expect(placed.referenceImageUrls[placed.referenceImageUrls.length - 1]).toBe('last.png');
    expect(placed.prompt).toContain('图1');
    expect(placed.prompt).not.toContain('@首帧图');
  });

  test('@首帧图片 和 @尾帧图片 不是槽位标记', () => {
    expect(promptHasShotFrameMention('@首帧图片')).toBe(false);
    expect(promptHasShotFrameMention('@尾帧图片')).toBe(false);
    expect(promptHasShotFrameMention('同时用 @首帧图 和 @尾帧图')).toBe(true);
  });
});
