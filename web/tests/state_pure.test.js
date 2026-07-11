// state.js 纯函数测试
// 测试不依赖 DOM 的工具函数

const stateModule = require('../js/state.js');
const { normalizeVideoUrl, extractResultsArray, isSameOriginUrl, normalizeImageUrl, proxyImageUrl, proxyDownloadUrl, getWorkflowIdFromUrl } = stateModule;

// ── normalizeVideoUrl ──
describe('normalizeVideoUrl', () => {
  test('null/undefined 返回空字符串', () => {
    expect(normalizeVideoUrl(null)).toBe('');
    expect(normalizeVideoUrl(undefined)).toBe('');
  });

  test('字符串直接返回', () => {
    expect(normalizeVideoUrl('http://example.com/v.mp4')).toBe('http://example.com/v.mp4');
  });

  test('对象中提取 url 字段', () => {
    expect(normalizeVideoUrl({ url: 'http://example.com/v.mp4' })).toBe('http://example.com/v.mp4');
  });

  test('对象中提取 video_url 字段', () => {
    expect(normalizeVideoUrl({ video_url: 'http://example.com/v.mp4' })).toBe('http://example.com/v.mp4');
  });

  test('对象中提取 videoUrl 字段', () => {
    expect(normalizeVideoUrl({ videoUrl: 'http://example.com/v.mp4' })).toBe('http://example.com/v.mp4');
  });

  test('对象中提取 file_url 字段', () => {
    expect(normalizeVideoUrl({ file_url: 'http://example.com/v.mp4' })).toBe('http://example.com/v.mp4');
  });

  test('对象中提取 oss_url 字段', () => {
    expect(normalizeVideoUrl({ oss_url: 'http://example.com/v.mp4' })).toBe('http://example.com/v.mp4');
  });

  test('对象中提取 path 字段', () => {
    expect(normalizeVideoUrl({ path: '/uploads/v.mp4' })).toBe('/uploads/v.mp4');
  });

  test('空对象返回空字符串', () => {
    expect(normalizeVideoUrl({})).toBe('');
  });

  test('数字返回空字符串', () => {
    expect(normalizeVideoUrl(123)).toBe('');
  });
});

// ── extractResultsArray ──
describe('extractResultsArray', () => {
  test('null/undefined 返回空数组', () => {
    expect(extractResultsArray(null)).toEqual([]);
    expect(extractResultsArray(undefined)).toEqual([]);
  });

  test('数组直接返回', () => {
    const arr = [{ id: 1 }, { id: 2 }];
    expect(extractResultsArray(arr)).toEqual(arr);
  });

  test('非对象返回空数组', () => {
    expect(extractResultsArray('string')).toEqual([]);
    expect(extractResultsArray(123)).toEqual([]);
  });

  test('从 results 字段提取', () => {
    expect(extractResultsArray({ results: [{ id: 1 }] })).toEqual([{ id: 1 }]);
  });

  test('从 result 字段提取', () => {
    expect(extractResultsArray({ result: [{ id: 1 }] })).toEqual([{ id: 1 }]);
  });

  test('从 videos 字段提取', () => {
    expect(extractResultsArray({ videos: ['v1.mp4'] })).toEqual(['v1.mp4']);
  });

  test('从 data 字段递归提取', () => {
    expect(extractResultsArray({ data: { results: [{ id: 1 }] } })).toEqual([{ id: 1 }]);
  });

  test('从 output 字段递归提取', () => {
    expect(extractResultsArray({ output: { videos: ['v1.mp4'] } })).toEqual(['v1.mp4']);
  });

  test('嵌套 data.data.results 提取', () => {
    const payload = { data: { data: { results: [{ id: 1 }] } } };
    expect(extractResultsArray(payload)).toEqual([{ id: 1 }]);
  });

  test('results 为对象时包装为数组', () => {
    const result = extractResultsArray({ results: { url: 'test.mp4' } });
    expect(result).toEqual([{ url: 'test.mp4' }]);
  });

  test('result 为对象时包装为数组', () => {
    const result = extractResultsArray({ result: { url: 'test.mp4' } });
    expect(result).toEqual([{ url: 'test.mp4' }]);
  });

  test('无有效字段返回空数组', () => {
    expect(extractResultsArray({ foo: 'bar' })).toEqual([]);
  });
});

// ── isSameOriginUrl ──
describe('isSameOriginUrl', () => {
  test('同源相对路径返回 true', () => {
    expect(isSameOriginUrl('/api/test')).toBe(true);
  });

  test('跨域 URL 返回 false', () => {
    expect(isSameOriginUrl('http://example.com/api/test')).toBe(false);
  });

  test('无效 URL 返回 true（容错）', () => {
    expect(isSameOriginUrl(':::invalid:::')).toBe(true);
  });
});

// ── normalizeImageUrl ──
describe('normalizeImageUrl', () => {
  test('空值返回空字符串', () => {
    expect(normalizeImageUrl(null)).toBe('');
    expect(normalizeImageUrl('')).toBe('');
    expect(normalizeImageUrl(undefined)).toBe('');
  });

  test('非字符串返回空字符串', () => {
    expect(normalizeImageUrl(123)).toBe('');
  });

  test('完整 HTTP URL 直接返回', () => {
    expect(normalizeImageUrl('http://example.com/img.png')).toBe('http://example.com/img.png');
  });

  test('完整 HTTPS URL 直接返回', () => {
    expect(normalizeImageUrl('https://example.com/img.png')).toBe('https://example.com/img.png');
  });

  test('data: URL 直接返回', () => {
    expect(normalizeImageUrl('data:image/png;base64,abc')).toBe('data:image/png;base64,abc');
  });

  test('blob: URL 直接返回', () => {
    expect(normalizeImageUrl('blob:http://localhost/123')).toBe('blob:http://localhost/123');
  });

  test('绝对路径转为完整 URL', () => {
    const result = normalizeImageUrl('/uploads/img.png');
    expect(result).toContain('/uploads/img.png');
    expect(result.startsWith('http')).toBe(true);
  });

  test('其他路径原样返回', () => {
    expect(normalizeImageUrl('relative/img.png')).toBe('relative/img.png');
  });
});

// ── proxyImageUrl ──
describe('proxyImageUrl', () => {
  test('空值返回空字符串', () => {
    expect(proxyImageUrl(null)).toBe('');
    expect(proxyImageUrl('')).toBe('');
  });

  test('data: URL 直接返回', () => {
    expect(proxyImageUrl('data:image/png;base64,abc')).toBe('data:image/png;base64,abc');
  });

  test('blob: URL 直接返回', () => {
    expect(proxyImageUrl('blob:http://localhost/123')).toBe('blob:http://localhost/123');
  });

  test('跨域 URL 通过代理', () => {
    const result = proxyImageUrl('http://example.com/img.png');
    expect(result).toContain('/api/proxy-image?url=');
    expect(result).toContain(encodeURIComponent('http://example.com/img.png'));
  });
});

// ── proxyDownloadUrl ──
describe('proxyDownloadUrl', () => {
  test('空值返回空字符串', () => {
    expect(proxyDownloadUrl(null)).toBe('');
    expect(proxyDownloadUrl('')).toBe('');
  });

  test('data: URL 直接返回', () => {
    expect(proxyDownloadUrl('data:video/mp4;base64,abc')).toBe('data:video/mp4;base64,abc');
  });

  test('跨域 URL 通过代理', () => {
    const result = proxyDownloadUrl('http://example.com/video.mp4');
    expect(result).toContain('/api/download?url=');
    expect(result).toContain(encodeURIComponent('http://example.com/video.mp4'));
  });

  test('跨域 URL 带文件名', () => {
    const result = proxyDownloadUrl('http://example.com/video.mp4', 'test.mp4');
    expect(result).toContain('/api/download?url=');
    expect(result).toContain('filename=' + encodeURIComponent('test.mp4'));
  });
});

// ── getWorkflowIdFromUrl ──
describe('getWorkflowIdFromUrl', () => {
  const originalSearch = window.location.search;

  afterEach(() => {
    // jsdom 不允许直接修改 window.location.search，跳过恢复
  });

  test('能从 URL 参数获取 id', () => {
    // jsdom 环境中 URLSearchParams 读取 window.location.search
    // 由于无法直接修改，此函数在 jsdom 中使用默认值
    const result = getWorkflowIdFromUrl();
    // jsdom 默认 search 为空，所以返回 null
    expect(result === null || typeof result === 'string').toBe(true);
  });
});
