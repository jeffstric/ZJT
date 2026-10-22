/**
 * 火山 TTS 音色库共享 API 层
 *
 * 被 Vue 侧（index.html 声音页 voice_picker.js / audio_generate.js）与
 * 工作流画布原生 JS（text_to_speech_node.js）共用。
 * 画布页 video_workflow.html 不加载 axios，这里统一用 fetch，
 * 认证走 Authorization 头（cookie 会话由服务端中间件翻译）。
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

  function withQuery(url, params) {
    if (!params) return url;
    var search = new URLSearchParams();
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === undefined || value === null || value === '') return;
      search.append(key, String(value));
    });
    var qs = search.toString();
    return qs ? url + (url.indexOf('?') >= 0 ? '&' : '?') + qs : url;
  }

  function errorDetail(data, status, fallback) {
    var detail = data && (data.detail || data.message);
    if (Array.isArray(detail)) {
      detail = detail.map(function (item) {
        if (item && typeof item === 'object') return item.msg || '';
        return item == null ? '' : String(item);
      }).filter(Boolean).join('; ');
    } else if (detail && typeof detail === 'object') {
      detail = detail.msg || '';
    }
    if (!detail) detail = fallback || ('请求失败 (' + status + ')');
    return String(detail);
  }

  function throwApiError(data, status, fallback) {
    var detail = errorDetail(data, status, fallback);
    var err = new Error(detail);
    // 兼容声音页 axios 时代的 err.response.data.detail
    err.response = { data: data || { detail: detail }, status: status };
    err.responseData = data || {};
    throw err;
  }

  /**
   * @param {string} method
   * @param {string} url
   * @param {Object|undefined} body
   * @param {string} fallback
   */
  async function requestJson(method, url, body, fallback) {
    var headers = authHeaders();
    var init = { method: method, headers: headers, credentials: 'same-origin' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    var res = await fetch(url, init);
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = null;
    }
    if (!res.ok || !data || !data.success) {
      throwApiError(data, res.status, fallback);
    }
    return data;
  }

  /**
   * 拉取音色库列表 + 计价档位。
   * 后端同时返回 volcengine 与 reference_audio，由调用方按场景筛选。
   * 传入 params.provider 时在这里过滤（接口本身不接收该查询参数）。
   * @param {Object} params {gender, language, keyword, page, page_size, provider}
   * @returns {Promise<Object>} {voices, power_tiers, max_text_length, ...}
   */
  async function listVoices(params) {
    var query = Object.assign({}, params || {});
    var provider = query.provider;
    delete query.provider;
    var data = await requestJson('GET', withQuery('/api/tts/voices', query), undefined, '音色库加载失败');
    if (provider) {
      data.voices = (data.voices || []).filter(function (voice) {
        return voice && voice.provider === provider;
      });
    }
    return data;
  }

  /**
   * 快速合成（同步秒级返回）
   * @param {Object} body {text, voice_id, speed_ratio}
   * @returns {Promise<Object>} {audio_url, duration, computing_power, ...}
   */
  async function synthesize(body) {
    return requestJson('POST', '/api/tts/synthesize', {
      text: body.text,
      voice_id: body.voice_id,
      speed_ratio: body.speed_ratio,
    }, '合成失败');
  }

  /**
   * 试听（服务端固定示例句 + 按音色缓存，免费）
   * @param {number} voiceId
   * @returns {Promise<Object>} {audio_url}
   */
  async function previewVoice(voiceId) {
    return requestJson(
      'GET',
      '/api/tts/preview/' + encodeURIComponent(voiceId),
      undefined,
      '试听失败'
    );
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
