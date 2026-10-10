const {
  promptHasShotFrameMention,
  shouldUseH3KeyframeRefModel,
  resolveShotFrameReferenceSubmitModel,
  shotFrameMentionImageLimit,
} = require('../js/shot_frame_video_generator.js');

describe('H3 首帧参考混合模型路由', () => {
  test('参考模式的 H3 参考模型点名首帧或尾帧时改走混合模型，图片上限 3', () => {
    expect(shouldUseH3KeyframeRefModel('multi_reference', 'minimax_h3_r2v', '从 @首帧图 开始')).toBe(true);
    expect(shouldUseH3KeyframeRefModel('multi_reference', 'minimax_h3_reference_to_video', '停在 @尾帧图')).toBe(true);
    expect(resolveShotFrameReferenceSubmitModel('multi_reference', 'minimax_h3_r2v', '@首帧图 @尾帧图')).toBe('minimax_h3_kfr');
    expect(shotFrameMentionImageLimit('multi_reference', 'minimax_h3_r2v', '@首帧图')).toBe(3);
  });

  test('首帧模式、没有标记、以及其他模型都不换', () => {
    expect(shouldUseH3KeyframeRefModel('first_last_frame', 'minimax_h3_r2v', '@首帧图')).toBe(false);
    expect(shouldUseH3KeyframeRefModel('multi_reference', 'minimax_h3_r2v', '普通提示词')).toBe(false);
    expect(shouldUseH3KeyframeRefModel('multi_reference', 'minimax_h3', '@首帧图')).toBe(false);
    expect(shouldUseH3KeyframeRefModel('multi_reference', 'minimax_h3_t2v', '@尾帧图')).toBe(false);
    expect(shouldUseH3KeyframeRefModel('multi_reference', 'seedance_2_0', '@首帧图')).toBe(false);
    expect(resolveShotFrameReferenceSubmitModel('multi_reference', 'seedance_2_0', '@首帧图')).toBe('seedance_2_0');
    expect(shotFrameMentionImageLimit('multi_reference', 'seedance_2_0', '@首帧图')).toBe(5);
  });

  test('@首帧图片 和 @尾帧图片 不是槽位标记', () => {
    expect(promptHasShotFrameMention('@首帧图片')).toBe(false);
    expect(promptHasShotFrameMention('@尾帧图片')).toBe(false);
    expect(promptHasShotFrameMention('同时用 @首帧图 和 @尾帧图')).toBe(true);
  });
});
