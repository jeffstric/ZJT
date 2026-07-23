// task_config.js 测试
// 需要 mock fetch 来加载配置数据，然后测试纯 getter 函数

// 模拟测试数据
const mockConfigData = {
  tasks: [
    {
      id: 1,
      key: 'sora2',
      short_key: 'sora2',
      name: 'Sora 2',
      category: 'image_to_video',
      categories: ['image_to_video', 'text_to_video'],
      supported_durations: [5, 10],
      supported_ratios: ['16:9', '9:16', '1:1'],
      supported_sizes: ['1080p', '720p'],
      default_duration: 5,
      default_ratio: '16:9',
      default_size: '1080p',
      computing_power: 100,
      hidden: false
    },
    {
      id: 2,
      key: 'kling',
      short_key: 'kling',
      name: 'Kling',
      category: 'image_to_video',
      supported_durations: [5, 10, 15],
      supported_ratios: ['16:9', '9:16'],
      default_duration: 10,
      default_ratio: '9:16',
      computing_power: { 5: 80, 10: 150, 15: 200 },
      hidden: false
    },
    {
      id: 3,
      key: 'gpt-image-2',
      short_key: 'gpt-image-2',
      name: 'GPT Image 2',
      category: 'image_edit',
      computing_power: 50,
      hidden: false
    },
    {
      id: 4,
      key: 'hidden_model',
      short_key: 'hidden_model',
      name: 'Hidden Model',
      category: 'image_to_video',
      computing_power: 10,
      hidden: true
    },
    {
      id: 5,
      key: 'seedance_2_0',
      short_key: 'seedance_2_0',
      name: 'Seedance 2.0',
      category: 'image_to_video',
      computing_power: 120,
      hidden: false
    },
    {
      id: 6,
      key: 'seedance_2_0_fast_image_to_video',
      short_key: 'seedance_2_0_fast',
      name: 'Seedance 2.0 Fast',
      category: 'image_to_video',
      computing_power: 60,
      hidden: false
    }
  ],
  categories: {
    image_to_video: '图生视频',
    text_to_video: '文生视频',
    image_edit: '图片编辑'
  },
  providers: {
    sora: 'OpenAI',
    kling: 'Kuaishou'
  },
  runninghub_configured: true
};

// mock fetch
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// mock localStorage
const mockLocalStorage = {
  getItem: vi.fn(() => 'test_token'),
  setItem: vi.fn(),
  removeItem: vi.fn()
};
globalThis.localStorage = mockLocalStorage;

// 加载模块（会执行 IIFE 并设置 window.TaskConfig）
const TaskConfig = require('../js/task_config.js');

// 在所有测试前加载配置
beforeAll(async () => {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ code: 0, data: mockConfigData })
  });
  await TaskConfig.load();
});

// ── 基础查询 ──
describe('TaskConfig - 基础查询', () => {
  test('isLoaded 返回 true', () => {
    expect(TaskConfig.isLoaded()).toBe(true);
  });

  test('getAllTasks 返回所有任务', () => {
    const tasks = TaskConfig.getAllTasks();
    expect(tasks.length).toBe(6);
  });

  test('getTaskById 返回正确任务', () => {
    expect(TaskConfig.getTaskById(1).key).toBe('sora2');
    expect(TaskConfig.getTaskById(2).key).toBe('kling');
    expect(TaskConfig.getTaskById(999)).toBeNull();
  });

  test('getTaskByKey 精确匹配', () => {
    expect(TaskConfig.getTaskByKey('sora2').id).toBe(1);
    expect(TaskConfig.getTaskByKey('kling').id).toBe(2);
  });

  test('getTaskByKey 短键匹配', () => {
    expect(TaskConfig.getTaskByKey('sora2').id).toBe(1);
  });

  test('getTaskByKey 前缀匹配', () => {
    // 'seedance_2_0' 应精确匹配，不应匹配到 'seedance_2_0_fast_image_to_video'
    expect(TaskConfig.getTaskByKey('seedance_2_0').id).toBe(5);
  });

  test('getTaskByKey 不存在返回 null', () => {
    expect(TaskConfig.getTaskByKey('nonexistent')).toBeNull();
  });

  test('getTaskIdByKey 返回任务 ID', () => {
    expect(TaskConfig.getTaskIdByKey('sora2')).toBe(1);
    expect(TaskConfig.getTaskIdByKey('nonexistent')).toBeNull();
  });

  test('getTaskIdByKey 带分类精确匹配', () => {
    expect(TaskConfig.getTaskIdByKey('sora2', 'image_to_video')).toBe(1);
    expect(TaskConfig.getTaskIdByKey('sora2', 'text_to_video')).toBe(1);
  });
});

// ── 分类查询 ──
describe('TaskConfig - 分类查询', () => {
  test('getTasksByCategory 返回分类任务（排除 hidden）', () => {
    const tasks = TaskConfig.getTasksByCategory('image_to_video');
    // 3 个非 hidden 的 image_to_video: sora2, kling, seedance_2_0, seedance_2_0_fast
    expect(tasks.length).toBe(4);
    expect(tasks.every(t => !t.hidden)).toBe(true);
  });

  test('getTasksByCategory 支持多分类', () => {
    // sora2 同时属于 image_to_video 和 text_to_video
    const tasks = TaskConfig.getTasksByCategory('text_to_video');
    expect(tasks.some(t => t.key === 'sora2')).toBe(true);
  });

  test('getTasksByCategory 空分类返回空数组', () => {
    expect(TaskConfig.getTasksByCategory('nonexistent')).toEqual([]);
  });

  test('getCategories 返回分类映射', () => {
    const cats = TaskConfig.getCategories();
    expect(cats.image_to_video).toBe('图生视频');
  });

  test('getProviders 返回供应商映射', () => {
    const providers = TaskConfig.getProviders();
    expect(providers.sora).toBe('OpenAI');
  });
});

// ── 选项查询 ──
describe('TaskConfig - 选项查询', () => {
  test('getDurationOptions 返回时长选项', () => {
    expect(TaskConfig.getDurationOptions('sora2')).toEqual([5, 10]);
    expect(TaskConfig.getDurationOptions('kling')).toEqual([5, 10, 15]);
  });

  test('getDurationOptions 不存在的模型返回默认值', () => {
    expect(TaskConfig.getDurationOptions('nonexistent')).toEqual([5, 10]);
  });

  test('getRatioOptions 返回比例选项', () => {
    expect(TaskConfig.getRatioOptions('sora2')).toEqual(['16:9', '9:16', '1:1']);
  });

  test('getRatioOptions 不存在的模型返回默认值', () => {
    expect(TaskConfig.getRatioOptions('nonexistent')).toEqual(['9:16', '16:9', '1:1']);
  });

  test('getSizeOptions 返回尺寸选项', () => {
    expect(TaskConfig.getSizeOptions('sora2')).toEqual(['1080p', '720p']);
  });

  test('getSizeOptions 不存在的模型返回默认值', () => {
    expect(TaskConfig.getSizeOptions('nonexistent')).toEqual(['1K', '2K']);
  });
});

// ── 默认值查询 ──
describe('TaskConfig - 默认值查询', () => {
  test('getDefaultDuration 返回默认时长', () => {
    expect(TaskConfig.getDefaultDuration('sora2')).toBe(5);
    expect(TaskConfig.getDefaultDuration('kling')).toBe(10);
  });

  test('getDefaultDuration 不存在的模型返回 5', () => {
    expect(TaskConfig.getDefaultDuration('nonexistent')).toBe(5);
  });

  test('getDefaultRatio 返回默认比例', () => {
    expect(TaskConfig.getDefaultRatio('sora2')).toBe('16:9');
  });

  test('getDefaultRatio 不存在的模型返回 9:16', () => {
    expect(TaskConfig.getDefaultRatio('nonexistent')).toBe('9:16');
  });

  test('getDefaultSize 返回默认尺寸', () => {
    expect(TaskConfig.getDefaultSize('sora2')).toBe('1080p');
  });
});

// ── 算力计算 ──
describe('TaskConfig - 算力计算', () => {
  test('固定算力任务', () => {
    expect(TaskConfig.getComputingPower(1)).toBe(100); // sora2
    expect(TaskConfig.getComputingPower('sora2')).toBe(100);
  });

  test('按时长计费任务', () => {
    expect(TaskConfig.getComputingPower('kling', 5)).toBe(80);
    expect(TaskConfig.getComputingPower('kling', 10)).toBe(150);
    expect(TaskConfig.getComputingPower('kling', 15)).toBe(200);
  });

  test('按时长计费 - 不存在的时长取第一个', () => {
    expect(TaskConfig.getComputingPower('kling', 999)).toBe(80);
  });

  test('不存在的任务返回 0', () => {
    expect(TaskConfig.getComputingPower('nonexistent')).toBe(0);
    expect(TaskConfig.getComputingPower(999)).toBe(0);
  });
});

// ── 兼容旧格式 ──
describe('TaskConfig - 兼容旧格式', () => {
  test('getVideoModelDurationOptions 返回视频模型时长', () => {
    const result = TaskConfig.getVideoModelDurationOptions();
    expect(result.sora2).toEqual([5, 10]);
    expect(result.kling).toEqual([5, 10, 15]);
  });

  test('getModelConfigs 返回模型配置', () => {
    const result = TaskConfig.getModelConfigs();
    expect(result.sora2.ratios).toEqual(['16:9', '9:16', '1:1']);
    expect(result.sora2.durations).toEqual([5, 10]);
    expect(result.sora2.default_ratio).toBe('16:9');
  });

  test('getTaskComputingPowerConfig 返回算力配置', () => {
    const result = TaskConfig.getTaskComputingPowerConfig();
    expect(result[1]).toBe(100); // sora2
    expect(result[2]).toEqual({ 5: 80, 10: 150, 15: 200 }); // kling
  });

  test('getTaskTypeConfig 返回任务类型配置', () => {
    const result = TaskConfig.getTaskTypeConfig();
    expect(result.image_to_video_types).toContain(1); // sora2
    expect(result.image_edit_types).toContain(3); // gpt-image-2
    expect(result.task_type_name_map[1]).toBe('Sora 2');
  });

  test('getTaskTypeIdsByCategory 返回分类任务 ID', () => {
    const result = TaskConfig.getTaskTypeIdsByCategory('image_edit');
    expect(result).toContain(3); // gpt-image-2
  });
});

// ── RunningHub 配置 ──
describe('TaskConfig - RunningHub', () => {
  test('isRunningHubConfigured 返回 true', () => {
    expect(TaskConfig.isRunningHubConfigured()).toBe(true);
  });
});

// ── 回调机制 ──
describe('TaskConfig - 回调机制', () => {
  test('onConfigLoaded 配置已加载时立即执行回调', () => {
    const callback = vi.fn();
    TaskConfig.onLoaded(callback);
    // 配置已在 beforeAll 中加载，回调应立即执行
    expect(callback).toHaveBeenCalled();
    expect(callback).toHaveBeenCalledWith(expect.objectContaining({ tasks: expect.any(Array) }));
  });
});
