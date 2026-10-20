/**
 * 工作流 TTS 节点：文案键必须进中英语言包；音色库请求不依赖 axios。
 */
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '../..');
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');

const TTS_KEYS = [
  'tts_title',
  'tts_output_port',
  'tts_text_label',
  'tts_text_placeholder',
  'tts_no_text_error',
  'tts_generate_btn',
  'tts_result_label',
  'tts_download_btn',
  'tts_ref_audio_label',
  'tts_clear_btn',
  'tts_emo_method_label',
  'tts_emo_same_as_ref',
  'tts_emo_use_ref',
  'tts_emo_ref_label',
  'tts_emo_weight_label',
  'tts_emo_weight_hint',
];

describe('tts node copy', () => {
  it('zh-CN and en locales both have the node keys', () => {
    const zh = JSON.parse(read('web/i18n/locales/zh-CN/video_workflow.json'));
    const en = JSON.parse(read('web/i18n/locales/en/video_workflow.json'));
    TTS_KEYS.forEach((key) => {
      expect(zh[key]).toEqual(expect.any(String));
      expect(en[key]).toEqual(expect.any(String));
      expect(zh[key]).not.toBe(key);
      expect(en[key]).not.toBe(key);
      expect(zh[key].length).toBeGreaterThan(0);
      expect(en[key].length).toBeGreaterThan(0);
    });
  });

  it('falls back when window.t echoes the missing key', () => {
    const src = read('web/js/text_to_speech_node.js');
    expect(src).toContain('value === key');
    expect(src).toContain("provider: 'volcengine'");
  });
});

describe('text to speech node render', () => {
  it('shows translated title, label and button, and lists volcengine voices', async () => {
    const zh = JSON.parse(read('web/i18n/locales/zh-CN/video_workflow.json'));
    window.t = (key) => (Object.prototype.hasOwnProperty.call(zh, key) ? zh[key] : key);
    window.VoiceLibraryApi = {
      listVoices: vi.fn().mockResolvedValue({
        success: true,
        voices: [
          { id: 7, provider: 'volcengine', name: '通用女声' },
        ],
        power_tiers: [],
      }),
    };
    global.createNodeWithDataFactory = (createFn) => createFn;
    global.registerNodeType = () => {};
    global.createNodeBase = function (config, opts) {
      const node = { id: 1, data: JSON.parse(JSON.stringify(config.defaultData)) };
      const title = typeof config.title === 'function' ? config.title(opts) : config.title;
      const el = document.createElement('div');
      el.innerHTML = '<div class="node-title">' + title + '</div>' + config.bodyHtml(opts, node);
      document.body.appendChild(el);
      config.onCreated(node, el, opts);
      return 1;
    };

    delete require.cache[require.resolve('../js/text_to_speech_node.js')];
    require('../js/text_to_speech_node.js');
    window.createTextToSpeechNode();
    await vi.waitFor(() => {
      expect(document.querySelector('.tts-voice-select').textContent).toContain('通用女声');
    });

    expect(document.querySelector('.node-title').textContent).toContain('文字转语音');
    expect(document.querySelector('.node-title').textContent).not.toContain('tts_title');
    expect(document.body.textContent).toContain('生成文本');
    expect(document.body.textContent).not.toContain('tts_text_label');
    expect(document.querySelector('.tts-text').getAttribute('placeholder')).toBe('输入要转换为语音的文本');
    expect(document.querySelector('.tts-generate-btn').textContent).toBe('生成语音');
    expect(window.VoiceLibraryApi.listVoices).toHaveBeenCalledWith({
      page_size: 300,
      provider: 'volcengine',
    });
  });
});

describe('VoiceLibraryApi', () => {
  beforeEach(() => {
    localStorage.setItem('auth_token', 'tts-token');
    jestResetFetch();
    delete require.cache[require.resolve('../js/voice_library_api.js')];
    require('../js/voice_library_api.js');
  });

  function jestResetFetch() {
    global.fetch = vi.fn();
  }

  it('does not call axios', () => {
    expect(read('web/js/voice_library_api.js')).not.toMatch(/axios\s*\./);
    expect(read('web/video_workflow.html')).toContain('/js/voice_library_api.js');
  });

  it('lists voices with Authorization and filters provider on the client', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        voices: [
          { id: 1, provider: 'volcengine', name: '通用女声' },
          { id: 2, provider: 'reference_audio', name: '克隆预置' },
        ],
        power_tiers: [[50, 1]],
      }),
    });

    const data = await window.VoiceLibraryApi.listVoices({
      page_size: 300,
      provider: 'volcengine',
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toContain('/api/tts/voices?');
    expect(url).toContain('page_size=300');
    expect(url).not.toContain('provider=');
    expect(init.headers.Authorization).toBe('Bearer tts-token');
    expect(init.credentials).toBe('same-origin');
    expect(data.voices.map((v) => v.id)).toEqual([1]);
  });

  it('surfaces API detail on failure', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: '无权限' }),
    });

    await expect(window.VoiceLibraryApi.listVoices({ page_size: 10 }))
      .rejects.toMatchObject({
        message: '无权限',
        response: { data: { detail: '无权限' }, status: 403 },
      });
  });
});
