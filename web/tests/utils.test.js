const {
  escapeHtml,
  getNodeImageUrl,
  isImageSourceNodeType,
  IMAGE_SOURCE_NODE_TYPES,
  extractMarkedCharacterNames,
  mergeShotCharacterNames,
  truncateRefCollection
} = require('../js/utils.js');

describe('escapeHtml', () => {
  test('转义 HTML 特殊字符', () => {
    expect(escapeHtml('<script>alert("xss")</script>')).toBe(
      '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
    );
  });

  test('转义 & 符号', () => {
    expect(escapeHtml('a & b')).toBe('a &amp; b');
  });

  test('转义单引号为 &#39;', () => {
    expect(escapeHtml("it's")).toBe("it&#39;s");
  });

  test('null 返回空字符串', () => {
    expect(escapeHtml(null)).toBe('');
  });

  test('undefined 返回空字符串', () => {
    expect(escapeHtml(undefined)).toBe('');
  });

  test('数值 0 不应返回空字符串', () => {
    expect(escapeHtml(0)).toBe('0');
  });

  test('数字类型正确转为字符串', () => {
    expect(escapeHtml(42)).toBe('42');
  });

  test('空字符串返回空字符串', () => {
    expect(escapeHtml('')).toBe('');
  });

  test('不含特殊字符的字符串原样返回', () => {
    expect(escapeHtml('hello world')).toBe('hello world');
  });

  test('已转义的字符串不会双重转义', () => {
    expect(escapeHtml('&amp;')).toBe('&amp;amp;');
  });
});

describe('getNodeImageUrl', () => {
  test('空节点返回空字符串', () => {
    expect(getNodeImageUrl(null)).toBe('');
    expect(getNodeImageUrl(undefined)).toBe('');
    expect(getNodeImageUrl({})).toBe('');
  });

  test('图片节点优先返回 data.url', () => {
    expect(getNodeImageUrl({ type: 'image', data: { url: 'https://a.png', preview: 'https://b.png' } })).toBe('https://a.png');
  });

  test('图片节点无 url 时回退 preview', () => {
    expect(getNodeImageUrl({ type: 'image', data: { preview: 'https://b.png' } })).toBe('https://b.png');
  });

  test('角色/场景/道具返回 reference_image', () => {
    expect(getNodeImageUrl({ type: 'character', data: { reference_image: 'https://char.png' } })).toBe('https://char.png');
    expect(getNodeImageUrl({ type: 'location', data: { reference_image: 'https://loc.png' } })).toBe('https://loc.png');
    expect(getNodeImageUrl({ type: 'props', data: { reference_image: 'https://prop.png' } })).toBe('https://prop.png');
  });

  test('角色没有参考图时返回空字符串', () => {
    expect(getNodeImageUrl({ type: 'character', data: { name: '张三' } })).toBe('');
  });
});

describe('isImageSourceNodeType', () => {
  test('包含图片与资产节点', () => {
    expect(IMAGE_SOURCE_NODE_TYPES).toEqual(['image', 'character', 'location', 'props']);
    expect(isImageSourceNodeType('image')).toBe(true);
    expect(isImageSourceNodeType('character')).toBe(true);
    expect(isImageSourceNodeType('video')).toBe(false);
  });
});

describe('extractMarkedCharacterNames', () => {
  test('空输入返回空数组', () => {
    expect(extractMarkedCharacterNames('')).toEqual([]);
    expect(extractMarkedCharacterNames(null)).toEqual([]);
    expect(extractMarkedCharacterNames(undefined)).toEqual([]);
  });

  test('按出现顺序提取并去重', () => {
    expect(extractMarkedCharacterNames('【【张三】】与【【李四】】，【【张三】】再出场')).toEqual(['张三', '李四']);
  });

  test('忽略空白名', () => {
    expect(extractMarkedCharacterNames('【【 】】【【赵六】】')).toEqual(['赵六']);
  });
});

describe('mergeShotCharacterNames', () => {
  test('空节点返回空数组', () => {
    expect(mergeShotCharacterNames(null)).toEqual([]);
    expect(mergeShotCharacterNames({})).toEqual([]);
  });

  test('图片与生视频提示词取并集，图片优先', () => {
    const node = {
      data: {
        imagePrompt: '【【张三】】站在门口',
        videoPromptText: '【【李四】】走进来，【【张三】】回头'
      }
    };
    expect(mergeShotCharacterNames(node)).toEqual(['张三', '李四']);
  });

  test('只在生视频提示词出现的角色也会被收集', () => {
    const node = {
      data: {
        imagePrompt: '空镜',
        videoPromptText: '【【周子豪】】和【【李卫国】】对话'
      }
    };
    expect(mergeShotCharacterNames(node)).toEqual(['周子豪', '李卫国']);
  });

  test('videoPromptText 为空时回退 videoPrompt', () => {
    const node = {
      data: {
        imagePrompt: '',
        videoPrompt: '【【土豆】】出场'
      }
    };
    expect(mergeShotCharacterNames(node)).toEqual(['土豆']);
  });
});

describe('truncateRefCollection', () => {
  test('同步裁切 URL 与后缀', () => {
    const urls = ['a', 'b', 'c', 'd'];
    const suffix = ['图1是a', '图2是b', '图3是c', '图4是d'];
    truncateRefCollection(urls, suffix, 2);
    expect(urls).toEqual(['a', 'b']);
    expect(suffix).toEqual(['图1是a', '图2是b']);
  });

  test('未超限不改动', () => {
    const urls = ['a', 'b'];
    const suffix = ['图1是a', '图2是b'];
    truncateRefCollection(urls, suffix, 5);
    expect(urls).toEqual(['a', 'b']);
    expect(suffix).toEqual(['图1是a', '图2是b']);
  });
});
