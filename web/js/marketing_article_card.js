/* global window */
/**
 * marketing_article_card.js — 图文转视频（article-to-video）前端渲染工具
 *
 * 职责：
 * 1. 从 ask_user 消息/普通消息中提取 article_to_video_script 脚本 JSON；
 * 2. 把脚本 JSON 渲染为结构化确认卡 HTML（参考图缩略图 + clip 信息）；
 * 3. 用户消息中的公众号/小红书链接加"图文转视频"来源徽标。
 *
 * 安全约定（红线 14）：
 * - 所有动态文本经 window.escapeHtml / window.escapeHtmlAttr 转义；
 * - 图片 src 仅接受以 /upload/ 开头的本系统路径，其余一律不渲染为 <img>。
 */
(function () {
  'use strict';

  var SCRIPT_TYPE = 'article_to_video_script';
  var UPLOAD_PREFIX = '/upload/';

  function safeEscape(text) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(text);
    return String(text == null ? '' : text);
  }

  function safeEscapeAttr(text) {
    if (typeof window.escapeHtmlAttr === 'function') return window.escapeHtmlAttr(text);
    return String(text == null ? '' : text);
  }

  /** 从纯文本中提取脚本对象：优先 ```json 代码块，兜底裸 JSON（LLM 未按格式包裹时）。 */
  function extractScript(text) {
    if (!text || (text.indexOf(SCRIPT_TYPE) === -1 && text.indexOf('"duration_seconds"') === -1)) return null;
    var m, obj;

    // 1) 代码块形态
    var re = /```(?:json)?\s*([\s\S]*?)```/g;
    while ((m = re.exec(text)) !== null) {
      obj = tryParseClipPayload(m[1] || '');
      if (obj) return obj;
    }

    // 2) 裸 JSON 兜底：匹配从首个 [ 或 { 到末个 ] 或 } 的片段（ clips 数组或单对象）
    var candidate = text.substring(text.indexOf('['), text.lastIndexOf(']') + 1);
    obj = tryParseClipPayload(candidate);
    if (obj) return obj;
    candidate = text.substring(text.indexOf('{'), text.lastIndexOf('}') + 1);
    return tryParseClipPayload(candidate);
  }

  /** 校验并归一化脚本负载：必须是含 clip 结构的对象；兼容顶层 clips 数组与裸 clip 数组。 */
  function tryParseClipPayload(raw) {
    if (!raw || (raw.indexOf('"duration_seconds"') === -1 && raw.indexOf(SCRIPT_TYPE) === -1)) return null;
    var parsed;
    try { parsed = JSON.parse(raw); } catch (e) { return null; }
    if (!parsed) return null;

    if (Array.isArray(parsed)) {
      // 裸 clip 数组（LLM 未包 type/clips 顶层时）
      if (!parsed.length || typeof parsed[0] !== 'object') return null;
      return { type: SCRIPT_TYPE, clips: parsed };
    }
    if (Array.isArray(parsed.clips) && parsed.clips.length) return parsed;
    return null;
  }

  function clipModeLabel(clip) {
    var hasRefs = Array.isArray(clip.reference_images) && clip.reference_images.length > 0;
    if (clip.mode === 'text_to_video') return '文生视频';
    // 有参考图即多图全能参考（reference_to_video / multi_reference），非首尾帧图生
    if (hasRefs || clip.mode === 'image_to_video') return '参考生视频';
    return '文生视频';
  }

  /** 参考图 <img>，仅接受本系统 /upload/ 路径，防外链注入。兼容 reference_images（对象数组）与 image_urls（字符串数组）。 */
  function renderRefs(clip) {
    var refs = Array.isArray(clip.reference_images) && clip.reference_images.length
      ? clip.reference_images
      : (Array.isArray(clip.image_urls) ? clip.image_urls : []);
    if (!refs.length) return '';
    var imgs = '';
    refs.forEach(function (ref) {
      var url = typeof ref === 'string' ? ref : (ref && ref.url) || '';
      if (typeof url !== 'string' || url.indexOf(UPLOAD_PREFIX) !== 0) return;
      imgs += '<img src="' + safeEscapeAttr(url) + '" alt="参考图" loading="lazy">';
    });
    return imgs ? '<div class="asc-refs">' + imgs + '</div>' : '';
  }

  function renderClip(clip, index) {
    var refs = renderRefs(clip);
    // 分秒口播时间轴（timeline 数组，信息密度载体）
    var timelineHtml = '';
    if (Array.isArray(clip.timeline) && clip.timeline.length) {
      var rows = '';
      clip.timeline.forEach(function (line, i) {
        if (!line) return;
        rows += '<div class="asc-tl-row"><span class="asc-tl-sec">' + i + 's</span>' +
                '<span class="asc-tl-text">' + safeEscape(line) + '</span></div>';
      });
      if (rows) {
        timelineHtml = '<div class="asc-timeline"><div class="asc-tl-head">🗣 分秒口播</div>' + rows + '</div>';
      }
    }
    // 覆盖的信息点下标（covered_points）
    var coveredHtml = '';
    if (Array.isArray(clip.covered_points) && clip.covered_points.length) {
      coveredHtml = '<span class="asc-tag">要点 ' + clip.covered_points.map(function (p) {
        return '#' + (typeof p === 'number' ? p + 1 : safeEscape(p));
      }).join('、') + '</span>';
    }
    return '<div class="asc-clip">' +
      '<div class="asc-clip-head">' +
      'Clip ' + (clip.index || index + 1) +
      '<span class="asc-tag">' + safeEscape(clip.duration_seconds || '?') + 's</span>' +
      '<span class="asc-tag">' + safeEscape(clip.task_type_name || ('task_type=' + (clip.task_type || '?'))) + '</span>' +
      '<span class="asc-tag">' + clipModeLabel(clip) + '</span>' +
      coveredHtml +
      '</div>' +
      refs +
      '<div class="asc-prompt">' + safeEscape(clip.prompt || '') + '</div>' +
      timelineHtml +
      '</div>';
  }

  /** 脚本 JSON → 结构化确认卡 HTML（含占位脚本替换说明）。 */
  function renderCard(script) {
    var clips = script.clips || [];
    var clipHtml = clips.map(renderClip).join('');
    var meta = [];
    if (script.ratio) meta.push('画幅 ' + script.ratio);
    meta.push('共 ' + clips.length + ' 段');
    if (script.source && script.source.title) meta.push('来源：' + script.source.title);

    return '<div class="article-script-card">' +
      '<div class="asc-title">🎬 ' + safeEscape(script.video_title || '视频脚本') + '</div>' +
      '<div class="asc-meta">' + meta.map(safeEscape).join(' · ') + '</div>' +
      (script.overall_style ? '<div class="asc-notes">' + safeEscape(script.overall_style) + '</div>' : '') +
      clipHtml +
      (script.notes ? '<div class="asc-notes">💡 附加建议：' + safeEscape(script.notes) + '</div>' : '') +
      '</div>';
  }

  /** 消息渲染入口：把脚本 JSON（代码块或裸 JSON）替换为确认卡 HTML，无脚本返回 null。 */
  function transformMessageText(text) {
    var script = extractScript(text);
    if (!script) return null;

    // 代码块形态：整体替换
    var blockRe = /```(?:json)?\s*\{[\s\S]*?"type"\s*:\s*"article_to_video_script"[\s\S]*?\}\s*```/;
    if (blockRe.test(text)) return text.replace(blockRe, function () { return renderCard(script); });

    // 裸 JSON 形态：移除被渲染的原始片段（定位脚本负载的起止）
    var start = text.indexOf('[');
    var end = text.lastIndexOf(']');
    if (start !== -1 && end > start) {
      var candidate = text.substring(start, end + 1);
      if (candidate.indexOf('"duration_seconds"') !== -1) {
        return text.substring(0, start) + renderCard(script) + text.substring(end + 1);
      }
    }
    start = text.indexOf('{');
    end = text.lastIndexOf('}');
    if (start !== -1 && end > start) {
      return text.substring(0, start) + renderCard(script) + text.substring(end + 1);
    }
    return text.replace(/```(?:json)?[\s\S]*?```/, function () { return renderCard(script); });
  }

  /** 用户消息链接徽标：公众号/小红书链接加来源标签。 */
  var SOURCE_BADGES = [
    { pattern: /mp\.weixin\.qq\.com/, label: '📄 公众号图文' },
    { pattern: /xiaohongshu\.com|xhslink\.com/, label: '📕 小红书笔记' }
  ];

  function sourceBadge(text) {
    if (!text) return '';
    for (var i = 0; i < SOURCE_BADGES.length; i++) {
      if (SOURCE_BADGES[i].pattern.test(text)) {
        return '<span class="article-source-badge">🖼 ' + safeEscape(SOURCE_BADGES[i].label) + '可转视频</span>';
      }
    }
    return '';
  }

  window.MarketingArticleCard = {
    extractScript: extractScript,
    renderCard: renderCard,
    transformMessageText: transformMessageText,
    sourceBadge: sourceBadge
  };
})();
