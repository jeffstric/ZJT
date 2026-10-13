/**
 * 火山 TTS 音色库共享 API 层
 *
 * 被 Vue 侧（index.html 声音页 voice_picker.js / audio_generate.js）与
 * 工作流画布原生 JS（volcengine_tts.js / text_to_speech_node.js）共用，
 * 数据与逻辑集中在此，两套 UI 只做薄渲染。
 */
(function (global) {
  'use strict';

  function authToken() {
    return localStorage.getItem('auth_token') || '';
  }

  function authHeaders() {
    var token = authToken();
    return token ? { Authorization: 'Bearer ' + token } : {};
  }

  /**
   * 拉取音色库列表 + 计价档位
   * @param {Object} params {gender, language, keyword, page, page_size}
   * @returns {Promise<Object>} {voices, power_tiers, max_text_length, ...}
   */
  async function listVoices(params) {
    var res = await axios.get('/api/tts/voices', {
      params: params || {},
      headers: authHeaders(),
    });
    if (!res.data || !res.data.success) {
      throw new Error((res.data && res.data.detail) || '音色库加载失败');
    }
    return res.data;
  }

  /**
   * 快速合成（同步秒级返回）
   * @param {Object} body {text, voice_id, speed_ratio}
   * @returns {Promise<Object>} {audio_url, duration, computing_power, ...}
   */
  async function synthesize(body) {
    var res = await axios.post('/api/tts/synthesize', {
      text: body.text,
      voice_id: body.voice_id,
      speed_ratio: body.speed_ratio,
    }, { headers: authHeaders() });
    if (!res.data || !res.data.success) {
      var detail = (res.data && res.data.detail) || '合成失败';
      var err = new Error(detail);
      err.responseData = res.data || {};
      throw err;
    }
    return res.data;
  }

  /**
   * 试听（服务端固定示例句 + 按音色缓存，免费）
   * @param {number} voiceId
   * @returns {Promise<Object>} {audio_url}
   */
  async function previewVoice(voiceId) {
    var res = await axios.get('/api/tts/preview/' + voiceId, {
      headers: authHeaders(),
    });
    if (!res.data || !res.data.success) {
      throw new Error((res.data && res.data.detail) || '试听失败');
    }
    return res.data;
  }

  /**
   * 按后端下发的档位表估算算力消耗（与后端 calc_volcengine_tts_power 同口径）
   * @param {number} charCount
   * @param {Array<Array<number>>} tiers [[上限字符, 算力], ...] 升序
   * @returns {number} 算力；0 表示超档/未配置
   */
  function estimatePower(charCount, tiers) {
    if (!Array.isArray(tiers) || !tiers.length) return 0;
    var count = parseInt(charCount, 10);
    if (!count || count <= 0) return 0;
    for (var i = 0; i < tiers.length; i++) {
      var limit = parseInt(tiers[i][0], 10);
      var power = parseInt(tiers[i][1], 10);
      if (count <= limit && power > 0) return power;
    }
    return 0;
  }

  global.VoiceLibraryApi = {
    listVoices: listVoices,
    synthesize: synthesize,
    previewVoice: previewVoice,
    estimatePower: estimatePower,
  };
})(window);
