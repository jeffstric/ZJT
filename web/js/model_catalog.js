/**
 * 场景模型目录：性价比 / 效果双档 + LLM 供应商折叠。
 * 与后端 config/model_catalog.py 对齐。推荐不覆盖已保存偏好。
 */
(function (window) {
  'use strict';

  const TRACK_VALUE = 'value';
  const TRACK_QUALITY = 'quality';
  const TRACK_CUSTOM = 'custom';

  const SCENES = {
    LLM_CHAT: 'llm.chat',
    LLM_SCRIPT_SPLIT: 'llm.script_split',
    LLM_MARKETING: 'llm.marketing',
    LLM_STYLE_RECOGNIZE: 'llm.style_recognize',
    IMAGE_TEXT_TO_IMAGE: 'image.text_to_image',
    IMAGE_IMAGE_EDIT: 'image.image_edit',
    VIDEO_TEXT_TO_VIDEO: 'video.text_to_video',
    VIDEO_IMAGE_TO_VIDEO: 'video.image_to_video',
    VIDEO_REFERENCE_TO_VIDEO: 'video.reference_to_video',
    VIDEO_DIGITAL_HUMAN: 'video.digital_human',
  };

  const FALLBACK_CATALOG = {
    'llm.chat': { value: 'deepseek-v4-flash', quality: 'deepseek-v4-pro' },
    'llm.script_split': { value: 'deepseek-v4-flash', quality: 'deepseek-v4-pro' },
    'llm.agent': { value: 'deepseek-v4-flash', quality: 'deepseek-v4-pro' },
    'llm.marketing': { value: 'doubao-seed-2-0-lite', quality: 'doubao-seed-2-0-pro' },
    'llm.style_recognize': { value: 'doubao-seed-2-0-lite', quality: 'doubao-seed-2-0-pro' },
    'image.text_to_image': { value: 'gpt-image-2', quality: 'gpt-image-2' },
    'image.image_edit': { value: 'gpt-image-2', quality: 'gpt-image-2' },
    'image.grid': { value: 'gpt-image-2', quality: 'gpt-image-2' },
    'image.script_writer': { value: 'gpt-image-2', quality: 'seedream-5.0-pro' },
    'video.text_to_video': { value: 'minimax_h3', quality: 'seedance_2_0' },
    'video.image_to_video': { value: 'minimax_h3', quality: 'seedance_2_0' },
    'video.reference_to_video': { value: 'minimax_h3_r2v', quality: 'seedance_2_0' },
    'video.digital_human': { value: 'digital_human_ltx2_3_voice', quality: 'digital_human_minimax_h3' },
  };

  function matchCanonical(item, target) {
    if (!item || !target) return false;
    const left = String(item).trim().toLowerCase();
    const right = String(target).trim().toLowerCase();
    if (left === right) return true;
    if (left.startsWith(right)) {
      const nxt = left.charAt(right.length);
      return !nxt || ' （(·/|'.includes(nxt);
    }
    return false;
  }

  function llmCanonical(model) {
    return String(model?.name || model?.model || model?.model_name || model?.canonical || '').trim();
  }

  function taskCanonical(task) {
    return String(task?.short_key || task?.canonical || task?.value || task?.key || '').trim();
  }

  function sceneForVideoImageMode(imageMode) {
    const mode = String(imageMode || '').trim();
    if (mode === 'text_to_video') return SCENES.VIDEO_TEXT_TO_VIDEO;
    if (mode === 'multi_reference' || mode === 'first_last_with_ref') {
      return SCENES.VIDEO_REFERENCE_TO_VIDEO;
    }
    return SCENES.VIDEO_IMAGE_TO_VIDEO;
  }

  function tracksFromCatalog(catalog, scene) {
    if (catalog?.tracks?.value || catalog?.tracks?.quality) {
      return {
        value: catalog.tracks.value?.canonical || '',
        quality: catalog.tracks.quality?.canonical || '',
        payload: catalog,
      };
    }
    const sceneCatalog = catalog?.[scene] || catalog?.scenes?.[scene];
    if (sceneCatalog?.tracks) {
      return {
        value: sceneCatalog.tracks.value?.canonical || '',
        quality: sceneCatalog.tracks.quality?.canonical || '',
        payload: sceneCatalog,
      };
    }
    const fallback = FALLBACK_CATALOG[scene] || {};
    return { value: fallback.value || '', quality: fallback.quality || '', payload: null };
  }

  function inferTrack(scene, canonical, catalog) {
    const tracks = tracksFromCatalog(catalog, scene);
    if (matchCanonical(canonical, tracks.value)) return TRACK_VALUE;
    if (matchCanonical(canonical, tracks.quality)) return TRACK_QUALITY;
    return TRACK_CUSTOM;
  }

  function pickDefaultRoute(routes, preferredVendors) {
    const list = (routes || []).filter(Boolean);
    if (!list.length) return null;
    const prefs = preferredVendors || [];
    for (let i = 0; i < prefs.length; i++) {
      const vendor = String(prefs[i] || '').toLowerCase();
      const hit = list.find((m) => String(m.vendor_name || '').toLowerCase() === vendor);
      if (hit) return hit;
    }
    const marked = list.find((m) => m.is_default_route);
    if (marked) return marked;
    const withTh = list.filter((m) => m.input_token_threshold);
    if (withTh.length) {
      return withTh.reduce((best, cur) => (
        Number(cur.input_token_threshold) > Number(best.input_token_threshold) ? cur : best
      ));
    }
    return list[0];
  }

  function collapseLlmModels(models, scene, catalog) {
    const tracks = tracksFromCatalog(catalog, scene);
    const groups = {};
    (models || []).forEach((model) => {
      const name = llmCanonical(model);
      const key = name.toLowerCase();
      if (!groups[key]) groups[key] = [];
      groups[key].push(model);
    });
    return Object.keys(groups).map((key) => {
      const routes = groups[key];
      const name = llmCanonical(routes[0]);
      const track = inferTrack(scene, name, catalog);
      const preferred = track === TRACK_VALUE
        ? catalog?.tracks?.value?.preferred_vendors
        : (track === TRACK_QUALITY ? catalog?.tracks?.quality?.preferred_vendors : []);
      const fallbackPreferred = name.includes('deepseek')
        ? ['deepseek', 'zjt_api']
        : (name.includes('doubao') ? ['volcengine', 'zjt_api'] : []);
      const defaultRoute = pickDefaultRoute(routes, preferred || fallbackPreferred);
      return {
        canonical: name,
        name,
        track,
        family: routes[0].family || (name.includes('deepseek') ? 'DeepSeek' : (name.includes('doubao') ? 'Doubao' : '其它')),
        defaultRoute,
        routes,
        reason: track === TRACK_VALUE
          ? (catalog?.tracks?.value?.reason || '')
          : (track === TRACK_QUALITY ? (catalog?.tracks?.quality?.reason || '') : ''),
      };
    }).sort((a, b) => {
      const rank = (t) => (t === TRACK_VALUE ? 0 : (t === TRACK_QUALITY ? 1 : 2));
      const diff = rank(a.track) - rank(b.track);
      if (diff !== 0) return diff;
      return a.name.localeCompare(b.name);
    });
  }

  function findCollapsedByTrack(collapsed, track) {
    return (collapsed || []).find((item) => item.track === track) || null;
  }

  function findCollapsedByName(collapsed, name) {
    return (collapsed || []).find((item) => matchCanonical(item.canonical, name) || matchCanonical(name, item.canonical)) || null;
  }

  function sortTaskOptions(options, scene, catalog) {
    const tracks = tracksFromCatalog(catalog, scene);
    const rankOf = (opt) => {
      const key = taskCanonical(opt);
      if (matchCanonical(key, tracks.value) || matchCanonical(opt.label, tracks.value)) return 0;
      if (matchCanonical(key, tracks.quality) || matchCanonical(opt.label, tracks.quality)) return 1;
      return 2;
    };
    return (options || []).slice().sort((a, b) => {
      const diff = rankOf(a) - rankOf(b);
      if (diff !== 0) return diff;
      return String(a.label || a.value || '').localeCompare(String(b.label || b.value || ''));
    });
  }

  function findTaskByTrack(options, scene, catalog, track) {
    const tracks = tracksFromCatalog(catalog, scene);
    const target = track === TRACK_QUALITY ? tracks.quality : tracks.value;
    if (!target) return null;
    return (options || []).find((opt) => (
      matchCanonical(taskCanonical(opt), target)
      || matchCanonical(opt.short_key, target)
      || matchCanonical(opt.value, target)
      || matchCanonical(opt.key, target)
      || matchCanonical(opt.label, target)
      || matchCanonical(opt.name, target)
    )) || null;
  }

  function mountTrackToggle(host, options) {
    if (!host) return null;
    const opts = options || {};
    let wrap = host.querySelector(':scope > .model-track-toggle');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'model-track-toggle';
      wrap.setAttribute('role', 'group');
      wrap.setAttribute('aria-label', '模型档位');
      wrap.innerHTML = (
        '<button type="button" class="model-track-btn" data-track="value">性价比</button>'
        + '<button type="button" class="model-track-btn" data-track="quality">效果</button>'
      );
      host.insertBefore(wrap, host.firstChild);
    }
    const buttons = wrap.querySelectorAll('[data-track]');
    const current = opts.track || TRACK_CUSTOM;
    buttons.forEach((btn) => {
      const active = btn.getAttribute('data-track') === current && current !== TRACK_CUSTOM;
      btn.classList.toggle('is-active', active);
      btn.disabled = !!opts.disabled;
    });
    wrap._latestOnSelect = opts.onSelect;
    if (!wrap._delegated) {
      wrap._delegated = true;
      wrap.addEventListener('click', (event) => {
        const btn = event.target.closest('[data-track]');
        if (!btn || btn.disabled) return;
        const fn = wrap._latestOnSelect;
        if (typeof fn === 'function') fn(btn.getAttribute('data-track'));
      });
    }
    return wrap;
  }

  function applyTrackButtons(wrap, track) {
    if (!wrap) return;
    wrap.querySelectorAll('[data-track]').forEach((btn) => {
      btn.classList.toggle('is-active', btn.getAttribute('data-track') === track && track !== TRACK_CUSTOM);
    });
  }

  function bindSelectTrack(host, select, scene, kind) {
    if (!host || !select) return null;
    const readCanonical = () => {
      const opt = select.options[select.selectedIndex];
      if (!opt) return '';
      if (kind === 'llm') return opt.value || '';
      return opt.dataset.shortKey || opt.value || '';
    };
    const apply = (track) => {
      if (kind === 'llm') {
        const targetTracks = tracksFromCatalog(null, scene);
        const target = track === TRACK_QUALITY ? targetTracks.quality : targetTracks.value;
        const hit = Array.from(select.options).find((opt) => (
          !opt.disabled && matchCanonical(opt.value, target)
        ));
        if (hit) {
          select.value = hit.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }
      } else {
        const opts = Array.from(select.options).map((opt) => ({
          value: opt.value,
          short_key: opt.dataset.shortKey || opt.value,
          name: opt.textContent,
          label: opt.textContent,
          disabled: opt.disabled,
        }));
        const hit = findTaskByTrack(opts, scene, null, track);
        if (hit && !hit.disabled) {
          select.value = hit.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
      applyTrackButtons(host.querySelector('.model-track-toggle'), track);
    };
    return mountTrackToggle(host, {
      track: inferTrack(scene, readCanonical(), null),
      onSelect: apply,
    });
  }

  window.ModelCatalog = {
    TRACK_VALUE,
    TRACK_QUALITY,
    TRACK_CUSTOM,
    SCENES,
    FALLBACK_CATALOG,
    matchCanonical,
    llmCanonical,
    taskCanonical,
    tracksFromCatalog,
    sceneForVideoImageMode,
    inferTrack,
    pickDefaultRoute,
    collapseLlmModels,
    findCollapsedByTrack,
    findCollapsedByName,
    sortTaskOptions,
    findTaskByTrack,
    mountTrackToggle,
    applyTrackButtons,
    bindSelectTrack,
  };

  if (typeof module !== 'undefined') {
    module.exports = window.ModelCatalog;
  }
})(typeof window !== 'undefined' ? window : globalThis);
