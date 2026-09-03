/**
 * 内容违规（违禁词 / 内容安全）识别与用户提醒 — 前端兜底层。
 *
 * 特征来源：/nas/tmp/api_request_log/ 2026-08-01 ~ 2026-08-30 真实失败样本，
 * 与后端 utils/content_moderation_error.py（方案 A 规则映射）保持同源对齐。
 * 后端归一为主（图/视频失败 reason 已改写为「内容审核未通过…」中文），本模块为前端兜底：
 * 1. 识别原始英文/未改写 reason（归一上线前的历史数据）；
 * 2. 生成友好中文文案（describe，文案模板与后端 _SOURCE_HINT_MESSAGES 一致）；
 * 3. 任务失败命中违规时弹出醒目的「内容违规提醒」弹框（notify，带冷却去重）。
 *
 * 用法（video_workflow / storyboard 通用）：
 *   window.ContentViolation.isViolation(task.error)
 *   window.ContentViolation.describe(task.error)
 *   window.ContentViolation.notify('wf:' + projectId, task.error)
 */
(function (global) {
  'use strict';

  var FRIENDLY_PREFIX = '内容审核未通过';

  // 英文特征（小写后匹配）。覆盖各供应商审核拒绝话术：
  // - GPT Image: "Your request was rejected by the safety system." / moderation_blocked / invalid_prompt
  // - Gemini 网关: "Gemini image generation blocked [IMAGE_SAFETY|IMAGE_OTHER|PROHIBITED_CONTENT|...]"
  // - Gemini duomi: "sensitive_words_detected" / "The generated images appear to be unsafe."
  //                 / "The provided prompt is considered unsafe..."
  //                 / "gemini blocked: finish_reason:STOP (candidate stopped before producing an image)"
  // - 火山 Seedream/Seedance: "Input(Image|Video)SensitiveContentDetected(.PrivacyInformation)"
  //                            / "Output(Video|Audio)SensitiveContentDetected"
  // - Grok 渠道: "Content security audit did not pass"
  var EN_MARKERS = (
    'safety system,' +
    'safety policy,' +
    'safety_violations,' +
    'moderation_blocked,' +
    'invalid_prompt,' +
    'content policy,' +
    'content_filter,' +
    'content moderation,' +
    'content security,' +
    'data_inspection_failed,' +
    'sensitive content,' +
    'sensitive information,' +
    'sensitivecontent,' +
    'sensitive_words,' +
    'image generation blocked,' +
    'generation was stopped,' +
    'generation blocked,' +
    'candidate stopped before producing,' +
    'prohibited content,' +
    'prohibited material,' +
    'policy violation,' +
    'image_safety,' +
    'image_other,' +
    'image_prohibited,' +
    'copyright,' +
    'trademark,' +
    'appear to be unsafe,' +
    'appears to be unsafe,' +
    'considered unsafe,' +
    'real person,' +
    'gemini blocked'
  ).split(',');

  // 中文特征。注意只匹配错误文案，不匹配提示词正文。
  var ZH_MARKERS = (
    '内容审核,' +
    '内容安全,' +
    '敏感内容,' +
    '敏感信息,' +
    '违禁,' +
    '违规,' +
    '审核未通过,' +
    '审核不通过,' +
    '版权,' +
    '商标'
  ).split(',');

  // 与后端 _SAFETY_VIOLATION_LABELS 对齐
  var VIOLATION_LABELS = {
    violence: '暴力', sexual: '色情', self_harm: '自残', 'self-harm': '自残',
    hate: '仇恨', harassment: '骚扰', illegal: '违法', drugs: '毒品',
    weapon: '武器', weapons: '武器', child: '未成年人相关', political: '政治敏感',
    safety: '安全策略', prohibited: '违禁内容', copyright: '版权/商标', trademark: '版权/商标'
  };

  // 与后端 _SOURCE_HINT_MESSAGES / _source_action_hint 对齐
  var SOURCE_MESSAGES = {
    prompt: FRIENDLY_PREFIX + '：提示词包含敏感/违禁内容，请修改提示词后重试',
    reference_image: FRIENDLY_PREFIX + '：参考图片包含敏感内容，请更换参考图后重试',
    output: FRIENDLY_PREFIX + '：生成结果可能包含敏感内容，请调整提示词或参考图后重试',
    copyright: FRIENDLY_PREFIX + '（版权/商标）：提示词或参考内容可能涉及受保护形象/标识，请修改后重试',
    general: FRIENDLY_PREFIX + '：请求被安全系统拦截，请检查提示词和参考图后重试'
  };

  function isViolation(text) {
    if (!text) return false;
    var msg = String(text);
    // 后端友好文案快速通道（utils/content_moderation_error.py FRIENDLY_PREFIX）
    if (msg.indexOf(FRIENDLY_PREFIX) >= 0) return true;
    var lower = msg.toLowerCase();
    for (var i = 0; i < EN_MARKERS.length; i++) {
      if (lower.indexOf(EN_MARKERS[i]) >= 0) return true;
    }
    for (var j = 0; j < ZH_MARKERS.length; j++) {
      if (msg.indexOf(ZH_MARKERS[j]) >= 0) return true;
    }
    return false;
  }

  // 提取违规标签（safety_violations=[...] / Gemini [REASON]）
  function extractLabels(msg) {
    var labels = [];
    var push = function (label) {
      if (label && labels.indexOf(label) < 0) labels.push(label);
    };
    var violMatch = msg.match(/safety_violations\s*=\s*\[([^\]]*)\]/i);
    if (violMatch) {
      violMatch[1].split(',')
        .map(function (s) { return s.trim().replace(/["']/g, '').toLowerCase(); })
        .filter(Boolean)
        .forEach(function (v) { push(VIOLATION_LABELS[v] || v); });
    }
    var blockMatch = msg.match(/(?:gemini\s+)?image\s+generation\s+blocked\s*\[([^\]]+)\]/i);
    if (blockMatch) {
      var reason = blockMatch[1].toUpperCase();
      if (reason.indexOf('SAFETY') >= 0) push('安全策略');
      else if (reason.indexOf('PROHIBITED') >= 0) push('违禁内容');
    }
    return labels;
  }

  // 推断违规来源（与后端 _infer_source_from_message 对齐）
  function inferSource(msg, lower) {
    if (/(copyright|trademark|image_other|image_recitation|recitation)/i.test(msg) || /版权|商标/.test(msg)) {
      return 'copyright';
    }
    if (
      /OutputImageSensitive|OutputVideoSensitive|OutputAudioSensitive|OutputTextSensitive/i.test(msg) ||
      /IMAGE_SAFETY/i.test(msg) ||
      /generated (image|images|video|audio)/i.test(msg) ||
      /output (image|video|audio)/i.test(msg) ||
      /output may contain/i.test(msg)
    ) {
      return 'output';
    }
    if (
      /InputImageSensitive|InputVideoSensitive/i.test(msg) ||
      /PrivacyInformation/i.test(msg) ||
      /real person/i.test(msg) ||
      /reference image/i.test(msg)
    ) {
      return 'reference_image';
    }
    if (
      /invalid_prompt|sensitive_words|InputTextSensitive/i.test(msg) ||
      /IMAGE_PROHIBITED|PROHIBITED_CONTENT/i.test(msg) ||
      /considered unsafe/i.test(msg) ||
      /candidate stopped before producing/i.test(msg) ||
      (/modify your prompt/i.test(msg) && !/generated (image|images)/i.test(msg))
    ) {
      return 'prompt';
    }
    return 'general';
  }

  /**
   * 生成用户友好中文文案；非违规文案返回 null。
   * 已是「内容审核未通过…」开头的不再二次包裹（与后端规则一致）。
   */
  function describe(text) {
    if (!isViolation(text)) return null;
    var msg = String(text);
    if (msg.indexOf(FRIENDLY_PREFIX) === 0) return msg;
    var lower = msg.toLowerCase();
    var source = inferSource(msg, lower);
    var labels = extractLabels(msg);
    if (source === 'copyright') return SOURCE_MESSAGES.copyright;
    var action = SOURCE_MESSAGES[source] ? SOURCE_MESSAGES[source].slice(FRIENDLY_PREFIX.length + 1) : SOURCE_MESSAGES.general.slice(FRIENDLY_PREFIX.length + 1);
    if (labels.length) {
      return FRIENDLY_PREFIX + '（' + labels.join('、') + '）：' + action;
    }
    return SOURCE_MESSAGES[source] || SOURCE_MESSAGES.general;
  }

  // ==================== 违规提醒弹框（带冷却去重） ====================

  var keyLastNotify = {}; // key -> 上次提醒时间戳
  var lastGlobalNotify = 0;
  var STYLE_ID = 'content-violation-styles';

  function ensureStyles() {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '.cv-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(15,23,42,.72);',
      'display:flex;align-items:center;justify-content:center;z-index:100001;}',
      '.cv-card{background:#fff;border-radius:14px;max-width:440px;width:92%;padding:26px 26px 20px;',
      'box-shadow:0 24px 70px rgba(0,0,0,.35);}',
      '.cv-title{display:flex;align-items:center;gap:8px;font-size:17px;font-weight:700;color:#b91c1c;margin-bottom:14px;}',
      '.cv-title .cv-icon{font-size:20px;}',
      '.cv-body{font-size:14px;color:#1f2937;line-height:1.7;white-space:pre-wrap;word-break:break-all;}',
      '.cv-raw{margin-top:12px;font-size:12px;color:#6b7280;}',
      '.cv-raw summary{cursor:pointer;user-select:none;color:#6b7280;}',
      '.cv-raw pre{margin:6px 0 0;padding:10px;background:#f3f4f6;border-radius:8px;font-size:12px;',
      'line-height:1.5;white-space:pre-wrap;word-break:break-all;max-height:180px;overflow:auto;}',
      '.cv-actions{display:flex;justify-content:flex-end;margin-top:20px;}',
      '.cv-btn{padding:8px 26px;border:none;border-radius:8px;background:#dc2626;color:#fff;',
      'font-size:14px;font-weight:500;cursor:pointer;}',
      '.cv-btn:hover{background:#b91c1c;}'
    ].join('');
    document.head.appendChild(style);
  }

  function showModal(friendly, rawText, opts) {
    if (typeof document === 'undefined') return;
    ensureStyles();
    var title = (opts && opts.title) || '内容违规提醒';
    var raw = String(rawText || '').slice(0, 400);

    var overlay = document.createElement('div');
    overlay.className = 'cv-overlay';
    var card = document.createElement('div');
    card.className = 'cv-card';
    card.setAttribute('role', 'alertdialog');
    card.setAttribute('aria-label', title);

    var titleEl = document.createElement('div');
    titleEl.className = 'cv-title';
    var iconEl = document.createElement('span');
    iconEl.className = 'cv-icon';
    iconEl.textContent = '⚠️';
    titleEl.appendChild(iconEl);
    titleEl.appendChild(document.createTextNode(title));

    var bodyEl = document.createElement('div');
    bodyEl.className = 'cv-body';
    bodyEl.textContent = friendly;

    card.appendChild(titleEl);
    card.appendChild(bodyEl);

    if (raw) {
      var details = document.createElement('details');
      details.className = 'cv-raw';
      var summary = document.createElement('summary');
      summary.textContent = '查看原始错误信息';
      var pre = document.createElement('pre');
      pre.textContent = raw;
      details.appendChild(summary);
      details.appendChild(pre);
      card.appendChild(details);
    }

    var actions = document.createElement('div');
    actions.className = 'cv-actions';
    var btn = document.createElement('button');
    btn.className = 'cv-btn';
    btn.type = 'button';
    btn.textContent = '我知道了';
    actions.appendChild(btn);
    card.appendChild(actions);

    var close = function () {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener('keydown', onKey, true);
    };
    var onKey = function (e) {
      if (e.key === 'Escape') close();
    };
    btn.addEventListener('click', close);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();
    });
    document.addEventListener('keydown', onKey, true);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    if (btn.focus) btn.focus();
  }

  /**
   * 违规提醒入口：text 命中违规特征时弹框提醒，否则静默返回 false。
   * 去重策略：
   * - 同 key（同一任务/分镜资产）冷却窗口内（默认 120s）只提醒一次；
   * - 全局冷却（默认 8s）防止批量生成时连环弹窗。
   * @param {string} key 提醒去重键（如 'wf:{project_id}' / 'sb:{scene_id}:video'）
   * @param {string} text 任务失败 reason / error 原文
   * @param {object} [opts] { title, onNotified, keyCooldownMs, globalCooldownMs }
   * @returns {boolean} 是否实际弹出了提醒
   */
  function notify(key, text, opts) {
    if (!isViolation(text)) return false;
    opts = opts || {};
    var now = Date.now();
    var keyCooldown = opts.keyCooldownMs != null ? opts.keyCooldownMs : 120000;
    var globalCooldown = opts.globalCooldownMs != null ? opts.globalCooldownMs : 8000;
    if (key && keyLastNotify[key] && now - keyLastNotify[key] < keyCooldown) return false;
    if (now - lastGlobalNotify < globalCooldown) return false;
    if (key) {
      // 防止 key 无限增长：超过 500 条时清理全部（冷却语义上等价于全部过期）
      if (Object.keys(keyLastNotify).length > 500) keyLastNotify = {};
      keyLastNotify[key] = now;
    }
    lastGlobalNotify = now;
    var friendly = describe(text) || SOURCE_MESSAGES.general;
    showModal(friendly, text, opts);
    if (typeof opts.onNotified === 'function') {
      try { opts.onNotified(friendly, text); } catch (e) { /* 回调异常不影响主流程 */ }
    }
    return true;
  }

  // 测试辅助：重置去重状态
  function _resetForTest() {
    keyLastNotify = {};
    lastGlobalNotify = 0;
  }

  var api = {
    isViolation: isViolation,
    describe: describe,
    notify: notify,
    _resetForTest: _resetForTest
  };

  global.ContentViolation = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
