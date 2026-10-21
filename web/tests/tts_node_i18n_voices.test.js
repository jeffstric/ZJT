/**
 * 工作流 TTS 节点：文案键必须进中英语言包；音色库请求不依赖 axios。
 */
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '../..');
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');

const DIALOGUE_TTS_KEYS = [
  'dialogue_create_tts_btn',
  'dialogue_open_tts_btn',
  'dialogue_create_tts_all',
  'dialogue_tts_hint',
  'dialogue_tts_created',
  'dialogue_tts_opened',
  'dialogue_tts_all_created',
  'dialogue_tts_empty_line',
  'dialogue_tts_missing',
  'dialogue_video_port_retired',
  'dialogue_voice_output_port',
  'dialogue_voice_unmatched',
  'dialogue_voice_no_world',
];

const VOICE_PORT_KEYS = [
  'tts_voice_input_port',
  'tts_voice_input_label',
  'tts_voice_input_hint',
  'tts_voice_connected',
  'tts_voice_no_ref',
  'character_voice_output_port',
];

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
    TTS_KEYS.concat(DIALOGUE_TTS_KEYS, VOICE_PORT_KEYS).forEach((key) => {
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
      const raw = typeof config.defaultData === 'function' ? config.defaultData(opts) : config.defaultData;
      const node = { id: 1, data: JSON.parse(JSON.stringify(raw)) };
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

describe('dialogue group hands synthesis to text to speech', () => {
  it('creates tts nodes instead of calling audio-generate', () => {
    const dialogue = read('web/js/dialogue_group_node.js');
    const shot = read('web/js/shot_frame_node.js');
    const tts = read('web/js/text_to_speech_node.js');
    expect(dialogue).not.toContain('/api/audio-generate');
    expect(dialogue).not.toContain('renderRefAudiosList');
    expect(dialogue).toContain('createTextToSpeechNode');
    expect(dialogue).toContain('createDialogueTtsNodes');
    expect(dialogue).toContain('ttsNodeIds');
    expect(shot).not.toContain('dialogue-generate-all-btn');
    expect(shot).toContain('createDialogueTtsNodes');
    expect(tts).toContain('applyTtsPatch');
    expect(tts).toContain('refAudioUrl');
  });
});

describe('voice input and character voice output', () => {
  it('keeps the voice output only on character nodes and routes it to the tts voice input', () => {
    const events = read('web/js/events.js');
    const tts = read('web/js/text_to_speech_node.js');
    const canvas = read('web/js/canvas.js');
    expect((events.match(/class="port output voice-output-port"/g) || []).length).toBe(2);
    expect((events.match(/fromPort: 'voice'/g) || []).length).toBe(2);
    expect(events).toContain('findNearestConnectablePort(mouseX, mouseY, \'voice\', PROXIMITY_DIST)');
    expect(events).toContain('audioPort.portType === \'voice\'');
    expect(events).toContain('!draggingVoice');
    expect(tts).toContain('registerInputPorts(\'text_to_speech\'');
    expect(tts).toContain('portType: \'voice\'');
    expect(tts).toContain("accepts: ['voice', 'audio']");
    expect(canvas).toContain('clearConnectedVoice');
  });

  it('connects a character voice or an audio node onto the tts voice input', () => {
    document.body.innerHTML = '';
    const registered = [];
    global.registerInputPorts = (type, ports) => registered.push({ type, ports });
    global.state = {
      audioConnections: [],
      nextAudioConnId: 1,
      nodes: [],
    };
    window.state = global.state;
    const toasts = [];
    global.showToast = (msg) => toasts.push(msg);
    window.t = (key) => key;

    delete require.cache[require.resolve('../js/text_to_speech_node.js')];
    require('../js/text_to_speech_node.js');

    expect(registered[0].type).toBe('text_to_speech');
    expect(registered[0].ports[0].selector).toBe('.port.voice-input-port');
    expect(registered[0].ports[0].accepts).toEqual(['voice', 'audio']);

    const tts = { id: 9, applyConnectedVoice: vi.fn() };
    const character = {
      id: 2,
      type: 'character',
      title: '甲',
      data: { default_voice: 'http://example.com/a.wav', name: '甲' },
    };
    expect(window.attachVoiceConnection(character, { nodeId: 9, node: tts })).toBe(true);
    expect(global.state.audioConnections).toEqual([
      { id: 1, from: 2, to: 9, portType: 'voice' },
    ]);
    expect(tts.applyConnectedVoice).toHaveBeenCalledWith({
      url: 'http://example.com/a.wav',
      name: '甲',
    });

    const audio = { id: 4, type: 'audio', title: '旁白', data: { url: 'http://example.com/b.wav', name: '旁白' } };
    expect(window.attachVoiceConnection(audio, { nodeId: 9, node: tts })).toBe(true);
    expect(global.state.audioConnections).toEqual([
      { id: 2, from: 4, to: 9, portType: 'voice' },
    ]);

    const empty = { id: 5, type: 'character', title: '乙', data: {} };
    expect(window.attachVoiceConnection(empty, { nodeId: 9, node: tts })).toBe(false);
    expect(global.state.audioConnections).toHaveLength(1);
    expect(toasts.length).toBe(1);

    global.state.audioConnections = [];
    global.state.nextAudioConnId = 1;
    const lineTts = { id: 11, applyConnectedVoice: vi.fn() };
    expect(window.commitVoiceConnection(
      { id: 3, type: 'dialogue_group' },
      { nodeId: 11, node: lineTts },
      { url: 'http://example.com/line.wav', name: '甲' },
      { voiceLineIndex: 0 }
    )).toBe(true);
    expect(global.state.audioConnections[0]).toMatchObject({
      from: 3,
      to: 11,
      portType: 'voice',
      voiceLineIndex: 0,
    });
  });
});

describe('dialogue line voice output', () => {
  it('exposes one reference-voice port per line and connects a matched world character', async () => {
    document.body.innerHTML = '';
    window.escapeHtml = (value) => String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    global.state = {
      defaultWorldId: 9,
      audioConnections: [],
      nodes: [],
      nextAudioConnId: 1,
    };
    window.state = global.state;
    global.getAuthToken = () => 'token';
    global.getUserId = () => '1';
    global.registerNodeType = () => {};
    global.createNodeWithDataFactory = () => () => {};
    global.bindInputPortEvents = () => {};
    const commits = [];
    window.commitVoiceConnection = (fromNode, voicePort, voice, extra) => {
      commits.push({ from: fromNode.id, voice, extra });
      return true;
    };
    const toasts = [];
    global.showToast = (msg) => { toasts.push(msg); };
    global.fetch = vi.fn(async (url) => {
      const text = String(url);
      const name = text.includes(encodeURIComponent('甲')) ? '甲' : '';
      const rows = name
        ? [{ name: '甲', default_voice: 'http://example.com/jia.wav' }]
        : [{ name: '别人', default_voice: 'http://example.com/other.wav' }];
      return {
        ok: true,
        json: async () => ({ code: 0, data: { data: name ? rows : [] } }),
      };
    });
    global.createNodeBase = function(config, opts) {
      const node = {
        id: 3,
        type: 'dialogue_group',
        x: 0,
        y: 0,
        data: config.defaultData(opts),
      };
      global.state.nodes.push(node);
      const el = document.createElement('div');
      el.className = 'node';
      el.innerHTML = '<div class="node-body">' + config.bodyHtml(opts, node) + '</div>';
      document.body.appendChild(el);
      config.onCreated(node, el, opts);
      window.__dialogue = node;
      return 3;
    };

    delete require.cache[require.resolve('../js/dialogue_group_node.js')];
    require('../js/dialogue_group_node.js');
    window.createDialogueGroupNode({
      dialogueData: [
        { character_name: '甲', text: '你好' },
        { character_name: '乙', text: '嗯' },
      ],
    });

    expect(document.querySelectorAll('.dialogue-voice-output').length).toBe(2);
    const readyPort = document.querySelector('.dialogue-item[data-index="0"] .dialogue-voice-output');
    await vi.waitFor(() => {
      expect(readyPort.classList.contains('is-ready')).toBe(true);
    });
    readyPort.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 12, clientY: 24 }));
    expect(global.state.connecting).toMatchObject({ fromId: 3, fromPort: 'voice', voiceLineIndex: 0 });

    const tts = { id: 8, applyConnectedVoice: vi.fn() };
    await expect(window.attachDialogueLineVoice(window.__dialogue, { nodeId: 8, node: tts }, 0)).resolves.toBe(true);
    expect(commits[0].voice.url).toBe('http://example.com/jia.wav');
    expect(commits[0].extra.voiceLineIndex).toBe(0);

    const unmatched = document.querySelector('.dialogue-item[data-index="1"] .dialogue-voice-output');
    await vi.waitFor(() => {
      expect(unmatched.classList.contains('disabled')).toBe(true);
    });
    await expect(window.attachDialogueLineVoice(window.__dialogue, { nodeId: 8, node: tts }, 1)).resolves.toBe(false);
    expect(commits).toHaveLength(1);
    expect(toasts.length).toBeGreaterThan(0);
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
