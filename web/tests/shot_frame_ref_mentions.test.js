const { placeShotFrameMentionImages } = require('../js/shot_frame_video_generator.js');

describe('placeShotFrameMentionImages', () => {
  test('没有标记时不改提示词，也不改入参数组', () => {
    const urls = ['a', 'b'];
    const suffix = ['图1是甲', '图2是乙'];
    const result = placeShotFrameMentionImages('保持原文', urls, suffix, 'first.png', 'last.png', 5);
    expect(result).toEqual({
      prompt: '保持原文',
      referenceImageUrls: ['a', 'b'],
      promptSuffix: ['图1是甲', '图2是乙'],
      error: ''
    });
    expect(result.referenceImageUrls).not.toBe(urls);
    expect(urls).toEqual(['a', 'b']);
    expect(suffix).toEqual(['图1是甲', '图2是乙']);
  });

  test('只点名首帧时插到图1，并顺延原有序号', () => {
    const result = placeShotFrameMentionImages(
      '从 @首帧图 开始',
      ['a', 'b'],
      ['图1是甲', '图2是乙'],
      'first.png',
      'last.png',
      5
    );
    expect(result.error).toBe('');
    expect(result.prompt).toBe('从 图1 开始');
    expect(result.referenceImageUrls).toEqual(['first.png', 'a', 'b']);
    expect(result.promptSuffix).toEqual(['图1是首帧', '图2是甲', '图3是乙']);
  });

  test('只点名尾帧时追加到末尾，中间序号不变', () => {
    const result = placeShotFrameMentionImages(
      '停在 @尾帧图',
      ['a'],
      ['图1是甲'],
      '',
      'last.png',
      5
    );
    expect(result.error).toBe('');
    expect(result.prompt).toBe('停在 图2');
    expect(result.referenceImageUrls).toEqual(['a', 'last.png']);
    expect(result.promptSuffix).toEqual(['图1是甲', '图2是尾帧']);
  });

  test('首尾帧同时点名时分别占两端', () => {
    const result = placeShotFrameMentionImages(
      '从 @首帧图 到 @尾帧图',
      ['a'],
      ['图1是甲'],
      'first.png',
      'last.png',
      5
    );
    expect(result.error).toBe('');
    expect(result.prompt).toBe('从 图1 到 图3');
    expect(result.referenceImageUrls).toEqual(['first.png', 'a', 'last.png']);
    expect(result.promptSuffix).toEqual(['图1是首帧', '图2是甲', '图3是尾帧']);
  });

  test('缺少对应图片时返回错误，且不把帧加进列表', () => {
    const missingFirst = placeShotFrameMentionImages('@首帧图', ['a'], ['图1是甲'], '', 'last.png', 5);
    expect(missingFirst.error).toBe('missing_first');
    expect(missingFirst.referenceImageUrls).toEqual(['a']);

    const missingLast = placeShotFrameMentionImages('@尾帧图', ['a'], ['图1是甲'], 'first.png', '  ', 5);
    expect(missingLast.error).toBe('missing_last');
    expect(missingLast.prompt).toBe('@尾帧图');
  });

  test('名额不够时先裁中间参考，两端仍留给被点名的帧', () => {
    const result = placeShotFrameMentionImages(
      '@首帧图 @尾帧图',
      ['a', 'b', 'c', 'd'],
      ['图1是甲', '图2是乙', '图3是丙', '图4是丁'],
      'first.png',
      'last.png',
      3
    );
    expect(result.error).toBe('');
    expect(result.referenceImageUrls).toEqual(['first.png', 'a', 'last.png']);
    expect(result.promptSuffix).toEqual(['图1是首帧', '图2是甲', '图3是尾帧']);
    expect(result.prompt).toBe('图1 图3');
  });

  test('名额放不下一对首尾帧时返回 over_capacity', () => {
    const result = placeShotFrameMentionImages('@首帧图@尾帧图', ['a'], ['图1是甲'], 'first.png', 'last.png', 1);
    expect(result.error).toBe('over_capacity');
    expect(result.referenceImageUrls).toEqual(['a']);
  });

  test('@首帧图片 不匹配 @首帧图', () => {
    const result = placeShotFrameMentionImages(
      '@首帧图片之后是 @首帧图',
      [],
      [],
      'first.png',
      '',
      5
    );
    expect(result.error).toBe('');
    expect(result.prompt).toBe('@首帧图片之后是 图1');
    expect(result.referenceImageUrls).toEqual(['first.png']);
    expect(result.promptSuffix).toEqual(['图1是首帧']);
  });
});
