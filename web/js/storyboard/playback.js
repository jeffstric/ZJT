/**
 * 故事板时间轴预览播放引擎（类剪影试看）
 *
 * 规则：
 * - 有 videoUrl 播视频，否则定格 firstFrameUrl
 * - 音频来源为视频原声时保留视频音轨并跳过 TTS
 * - 音频来源为对话配音时静音视频，dialogues 有 audioUrl 的按 sortOrder 串行播放
 * - 本镜占用时长 = scene.duration（配音齐后后端同步为对白时长和）；不用视频 duration
 * - 到点强制切下一镜；视频仅并行画面，不阻塞切镜（长于本镜则截断，短于则定格）
 * - 进入本镜后先预加载视频+全部配音，就绪后再开时钟与播放
 * - 播放中禁止依赖全量 rerender 驱动媒体；切镜用局部 DOM
 */

import state from './state.js';
import { formatDuration } from './adapters.js';
import { icon } from './icons.js';
import { showToast } from './utils.js';
import { SCENE_AUDIO_MODE, resolveSceneAudioMode } from './playback_audio.js';
import {
    ensurePreviewStage,
    applyPreviewCanvas,
    getPreviewMediaMountParent,
} from './preview_canvas.js';

const EMPTY_HOLD_FALLBACK = 2;
const TICK_MS = 50;
/** 单资源预加载超时（ms），超时 best-effort 继续，避免卡死整片 */
const MEDIA_PRELOAD_TIMEOUT_MS = 20000;
/** HTMLMediaElement.HAVE_FUTURE_DATA */
const HAVE_FUTURE_DATA = 3;

let generation = 0;
let paused = false;
let pauseWaiters = [];
let activeVideoEl = null;
let activeAudioEl = null;
let clockTimer = null;
let sceneBaseGlobalTime = 0;
let sceneStartedAt = 0;
let pausedAccumMs = 0;
let pauseStartedAt = 0;
let runPromise = null;
/** 已完整播完的分镜累计时长（秒，按各镜 scene.duration 累加） */
let playedOffsetSec = 0;
/** 当前镜计划占用（秒），时钟与 playhead 镜内比例用 */
let currentSceneSpan = 0;
/** 画面会话令牌：切镜时递增，使上一镜 runVideoVisual 退出 */
let visualSession = 0;
/** 本镜预加载的 Audio 实例（切镜时释放） */
let preloadedAudioEls = [];

function isActive(gen) {
    return gen === generation && state.isPlaying;
}

function notifyPauseWaiters() {
    const list = pauseWaiters;
    pauseWaiters = [];
    list.forEach(resolve => resolve());
}

async function checkpoint(gen) {
    while (isActive(gen) && paused) {
        await new Promise(resolve => {
            pauseWaiters.push(resolve);
        });
    }
    if (!isActive(gen)) {
        const err = new Error('playback-aborted');
        err.name = 'PlaybackAbortError';
        throw err;
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitMs(ms, gen) {
    let elapsed = 0;
    while (elapsed < ms) {
        await checkpoint(gen);
        const step = Math.min(TICK_MS, ms - elapsed);
        await sleep(step);
        if (!isActive(gen)) {
            const err = new Error('playback-aborted');
            err.name = 'PlaybackAbortError';
            throw err;
        }
        if (!paused) elapsed += step;
    }
}

function isRenderableUrl(url) {
    if (url == null) return false;
    const value = String(url).trim();
    if (!value || value.includes(',')) return false;
    return true;
}

function normalizeVolume(volume) {
    const n = Number(volume);
    if (!Number.isFinite(n)) return 1;
    // 业务上多为 0–100；兼容 0–1
    if (n <= 1) return Math.min(1, Math.max(0, n));
    return Math.min(1, Math.max(0, n / 100));
}

export function buildScenePlan(scene) {
    const dialogues = [...(scene?.dialogues || [])]
        .filter(d => isRenderableUrl(d.audioUrl))
        .sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));

    const audios = dialogues.map(d => ({
        dialogueId: d.id,
        url: String(d.audioUrl).trim(),
        text: d.text || '',
        volume: normalizeVolume(d.volume),
    }));

    let visualType = 'empty';
    let visualUrl = '';
    if (isRenderableUrl(scene?.videoUrl)) {
        visualType = 'video';
        visualUrl = String(scene.videoUrl).trim();
    } else if (isRenderableUrl(scene?.firstFrameUrl)) {
        visualType = 'image';
        visualUrl = String(scene.firstFrameUrl).trim();
    }

    const durationHint = Number(scene?.duration);
    const fallbackHold = Number.isFinite(durationHint) && durationHint > 0
        ? durationHint
        : EMPTY_HOLD_FALLBACK;

    const audioEmbedded = Boolean(scene?.audioEmbedded);
    const audioMode = resolveSceneAudioMode({
        visualType,
        audioEmbedded,
        audios,
        // 预留素材级音轨探测字段；当前旧数据为 undefined 时信任用户的“视频原声”选择。
        videoHasAudio: scene?.videoHasAudio,
    });

    return {
        sceneId: scene?.id ?? null,
        title: scene?.title || '',
        durationLabel: scene?.durationLabel || formatDuration(fallbackHold),
        visualType,
        visualUrl,
        audios,
        audioEmbedded,
        audioMode,
        fallbackHold,
    };
}

function sumDurationBeforeIndex(index) {
    let total = 0;
    for (let i = 0; i < index; i += 1) {
        // 与 playhead / 本镜 span 同一口径，避免 duration 缺失时偏移为 0
        total += resolveSceneSpan(state.scenes[i]);
    }
    return total;
}

/** 分镜在时间轴上的起点（前面所有 scene.duration 之和） */
export function getSceneTimelineOffset(sceneId) {
    const idx = state.scenes.findIndex(s => s.id === sceneId);
    if (idx < 0) return 0;
    return sumDurationBeforeIndex(idx);
}

/**
 * 本镜占用时长：以 scene.duration 为准（配音全部完成后后端会同步为对白时长和）。
 * 无效时回退 EMPTY_HOLD_FALLBACK，避免 0 导致无法推进。
 */
export function resolveSceneSpan(scene) {
    const d = Number(scene?.duration);
    if (Number.isFinite(d) && d > 0) return d;
    return EMPTY_HOLD_FALLBACK;
}

/** 选中分镜作为播放起点（清 ended、对齐 currentTime） */
export function syncSelectionToTimeline(sceneId) {
    if (state.playback) {
        state.playback.status = 'idle';
        state.playback.sceneId = null;
        state.playback.audioDialogueId = null;
        state.playback.sceneLocalTime = 0;
        state.playback.buffering = false;
    }
    state.currentTime = getSceneTimelineOffset(sceneId);
    updatePlayheadPosition({ followScroll: true });
}

function setPlaybackBuffering(on) {
    if (state.playback) state.playback.buffering = !!on;
    const wrapper = document.querySelector('.preview-wrapper');
    if (!wrapper) return;
    const host = ensurePreviewStage(wrapper) || wrapper;
    let mask = wrapper.querySelector('.preview-buffering');
    if (on) {
        if (!mask) {
            mask = document.createElement('div');
            mask.className = 'preview-buffering';
            mask.setAttribute('aria-live', 'polite');
            mask.innerHTML = '<span class="preview-buffering-text">加载中…</span>';
            host.appendChild(mask);
        } else if (mask.parentElement !== host) {
            host.appendChild(mask);
        }
        mask.hidden = false;
    } else if (mask) {
        mask.hidden = true;
    }
}

/**
 * 等待 HTMLMediaElement 可播（视频/音频）。
 * readyState >= HAVE_FUTURE_DATA 视为就绪；超时或 error 返回 false（调用方 best-effort 继续）。
 */
async function waitMediaCanPlay(el, gen, timeoutMs = MEDIA_PRELOAD_TIMEOUT_MS) {
    if (!el) return true;
    if (el.error) return false;
    if (el.readyState >= HAVE_FUTURE_DATA) return true;

    const deadline = performance.now() + timeoutMs;
    while (isActive(gen) && performance.now() < deadline) {
        await checkpoint(gen);
        if (el.error) return false;
        if (el.readyState >= HAVE_FUTURE_DATA) return true;
        await sleep(TICK_MS);
    }
    // 超时：至少有当前帧数据也算可尝试播放
    return !el.error && el.readyState >= 2;
}

async function waitImageLoaded(img, gen, timeoutMs = MEDIA_PRELOAD_TIMEOUT_MS) {
    if (!img) return true;
    if (img.complete && img.naturalWidth > 0) return true;
    const deadline = performance.now() + timeoutMs;
    while (isActive(gen) && performance.now() < deadline) {
        await checkpoint(gen);
        if (img.complete) return img.naturalWidth > 0;
        await sleep(TICK_MS);
    }
    return Boolean(img.complete && img.naturalWidth > 0);
}

function createPreloadedAudio(item) {
    const audio = new Audio();
    audio.preload = 'auto';
    audio.src = item.url;
    audio.volume = item.volume;
    try {
        audio.load();
    } catch {
        // ignore
    }
    return audio;
}

/**
 * 本镜画面 + 全部配音预加载完成后再返回。
 * @returns {{ audioEls: HTMLAudioElement[] }}
 */
async function preloadSceneMedia(plan, videoEl, imageEl, gen) {
    disposePreloadedAudios();
    // 视频原声模式不创建、不下载 TTS，避免无用请求与双音轨。
    const audioEls = plan.audioMode === SCENE_AUDIO_MODE.TTS
        ? (plan.audios || []).map(item => createPreloadedAudio(item))
        : [];
    preloadedAudioEls = audioEls;

    // 触发视频缓冲
    if (videoEl) {
        try {
            videoEl.preload = 'auto';
            videoEl.load();
        } catch {
            // ignore
        }
    }

    const results = await Promise.all([
        videoEl ? waitMediaCanPlay(videoEl, gen) : Promise.resolve(true),
        imageEl ? waitImageLoaded(imageEl, gen) : Promise.resolve(true),
        ...audioEls.map(el => waitMediaCanPlay(el, gen)),
    ]);

    if (!isActive(gen)) {
        disposePreloadedAudios();
        return { audioEls: [] };
    }

    const failed = results.filter(ok => !ok).length;
    if (failed > 0) {
        // 不阻断整片，仅提示
        console.warn(`[storyboard playback] ${failed} 个媒体预加载未完全就绪，将尝试继续播放`);
    }
    return { audioEls };
}

function disposePreloadedAudios() {
    preloadedAudioEls.forEach(audio => {
        try {
            audio.pause();
            audio.removeAttribute('src');
            audio.load();
        } catch {
            // ignore
        }
    });
    preloadedAudioEls = [];
}

function updatePlayButtonIcon() {
    const btn = document.querySelector('.play-btn');
    if (!btn) return;
    const name = state.isPlaying && !paused ? 'pause' : 'play';
    btn.innerHTML = icon(name, 18);
}

function updateProgressChrome() {
    // 专用 .timeline-time，避免命中 .play-btn 内 .sb-icon
    const span = document.querySelector('.timeline-progress-row .timeline-time');
    if (!span) return;
    const total = state.scenes.reduce((t, s) => t + resolveSceneSpan(s), 0);
    span.textContent = `${formatDuration(state.currentTime)} / ${formatDuration(total)}`;
    updatePlayheadPosition({ followScroll: state.isPlaying && !paused });
}

function clamp01(t) {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    return t;
}

/**
 * 播放头定位：优先用「分镜索引 + 镜内比例」，避免仅靠全局 currentTime 累加
 * 在前置 duration 异常/为 0 时把指针错钉在第一镜。
 *
 * - 播放/暂停：playback.sceneId（或 currentSceneId）+ sceneLocalTime / sceneSpan
 * - 空闲/ended：当前选中分镜起点（ratio=0）
 */
function resolvePlayheadPlacement() {
    const scenes = state.scenes || [];
    if (!scenes.length) return null;

    const status = state.playback?.status;
    const playingLike = state.isPlaying || status === 'paused';

    let sceneId = state.currentSceneId;
    let ratio = 0;

    if (playingLike) {
        sceneId = state.playback?.sceneId != null ? state.playback.sceneId : state.currentSceneId;
        const scene = scenes.find(s => s.id === sceneId) || null;
        const span = Math.max(resolveSceneSpan(scene), 0.001);
        const local = Math.max(0, Number(state.playback?.sceneLocalTime) || 0);
        ratio = clamp01(local / span);
    }

    let idx = scenes.findIndex(s => s.id === sceneId);
    if (idx < 0) idx = 0;
    return { idx, ratio };
}

/**
 * 按分镜卡片索引 + 镜内比例 → list 内容坐标 X
 *
 * 注意：.scene-timeline-item / .scene-timeline-thumb 均为 position:relative，
 * thumb.offsetLeft 相对的是 item（≈0），不能用来给相对 list 定位的 playhead。
 * 必须用 getBoundingClientRect + scrollLeft 换算到 list 内容坐标系。
 */
function mapIndexRatioToContentX(list, idx, ratio) {
    const items = list.querySelectorAll('.scene-timeline-item');
    if (!items.length) return null;
    const safeIdx = Math.max(0, Math.min(idx, items.length - 1));
    const item = items[safeIdx];
    if (!item) return null;
    const thumb = item.querySelector('.scene-timeline-thumb') || item;
    const r = clamp01(ratio);
    const listRect = list.getBoundingClientRect();
    const thumbRect = thumb.getBoundingClientRect();
    // 视口差 + 已滚动距离 = 相对 list 滚动内容左缘的 X
    const base = thumbRect.left - listRect.left + list.scrollLeft;
    return base + r * thumbRect.width;
}

function ensurePlayheadVisible(list, contentX) {
    if (!list || !Number.isFinite(contentX)) return;
    const margin = 48;
    const left = list.scrollLeft;
    const right = left + list.clientWidth;
    if (contentX < left + margin) {
        list.scrollLeft = Math.max(0, contentX - margin);
    } else if (contentX > right - margin) {
        list.scrollLeft = Math.max(0, contentX - list.clientWidth + margin);
    }
}

/**
 * 将时间轴横向滚动到指定分镜缩略图可见（键盘/点击切镜共用）。
 * @param {number|string|null} sceneId
 * @param {{ margin?: number }} [options]
 * @returns {boolean}
 */
export function scrollTimelineToScene(sceneId, options = {}) {
    if (sceneId == null) return false;
    const list = document.querySelector('.scene-timeline-list');
    if (!list) return false;
    const thumb = document.querySelector(`.scene-timeline-thumb[data-scene="${sceneId}"]`);
    if (!thumb) return false;
    const margin = Number.isFinite(options.margin) ? options.margin : 48;
    const listRect = list.getBoundingClientRect();
    const thumbRect = thumb.getBoundingClientRect();
    // 换算到 list 内容坐标，再滚到完整可见
    const thumbLeft = thumbRect.left - listRect.left + list.scrollLeft;
    const thumbRight = thumbLeft + thumbRect.width;
    const viewLeft = list.scrollLeft;
    const viewRight = viewLeft + list.clientWidth;
    if (thumbLeft < viewLeft + margin) {
        list.scrollLeft = Math.max(0, thumbLeft - margin);
    } else if (thumbRight > viewRight - margin) {
        list.scrollLeft = Math.max(0, thumbRight - list.clientWidth + margin);
    }
    return true;
}

/**
 * 更新分镜序列上的播放头位置。
 * @param {{ followScroll?: boolean }} [options]
 */
export function updatePlayheadPosition(options = {}) {
    const list = document.querySelector('.scene-timeline-list');
    const playhead = list && list.querySelector('.scene-timeline-playhead');
    if (!list || !playhead) return false;

    if (!state.scenes.length) {
        playhead.hidden = true;
        return false;
    }

    const placement = resolvePlayheadPlacement();
    if (!placement) {
        playhead.hidden = true;
        return false;
    }
    const x = mapIndexRatioToContentX(list, placement.idx, placement.ratio);
    if (x == null || !Number.isFinite(x)) {
        playhead.hidden = true;
        return false;
    }

    playhead.hidden = false;
    playhead.style.left = `${x}px`;

    const follow = options.followScroll === true
        || (options.followScroll !== false && state.isPlaying && !paused);
    if (follow) {
        ensurePlayheadVisible(list, x);
    }
    return true;
}

function setSubtitle(text) {
    const el = document.querySelector('.preview-subtitle');
    if (!el) return;
    const show = Boolean(state.subtitleEnabled && text);
    el.hidden = !show;
    el.textContent = show ? text : '';
}

function updateTimelineActive(sceneId) {
    document.querySelectorAll('.scene-timeline-thumb.active').forEach(node => {
        node.classList.remove('active');
    });
    const thumb = document.querySelector(`.scene-timeline-thumb[data-scene="${sceneId}"]`);
    if (thumb) {
        thumb.classList.add('active');
    }
    // 播放头统一负责横向跟随，避免与 scrollIntoView 抢动画
    updatePlayheadPosition({ followScroll: true });
}

function updatePreviewCaption(plan) {
    const caption = document.querySelector('.preview-caption');
    if (!caption) return;
    const strong = caption.querySelector('strong');
    const span = caption.querySelector('span');
    if (strong) strong.textContent = plan.title || '未选择分镜';
    if (span) span.textContent = plan.durationLabel || '';
}

function ensurePreviewShell() {
    let wrapper = document.querySelector('.preview-wrapper');
    if (!wrapper) return null;
    const stage = ensurePreviewStage(wrapper);
    const mount = stage || wrapper;
    if (!mount.querySelector('.preview-subtitle')) {
        const sub = document.createElement('div');
        sub.className = 'preview-subtitle';
        sub.hidden = true;
        mount.appendChild(sub);
    }
    if (!wrapper.querySelector('.preview-caption')) {
        const cap = document.createElement('div');
        cap.className = 'preview-caption';
        cap.innerHTML = '<strong></strong><span></span>';
        wrapper.appendChild(cap);
    }
    applyPreviewCanvas(wrapper);
    return wrapper;
}

function clearPreviewMedia(wrapper) {
    if (!wrapper) return;
    wrapper.querySelectorAll(
        '.preview-media-stack, .preview-media, .preview-empty, .preview-image-toolbar'
    ).forEach((node) => node.remove());
}

function mountVisual(plan) {
    const wrapper = ensurePreviewShell();
    if (!wrapper) return { videoEl: null, imageEl: null };

    const mount = getPreviewMediaMountParent(wrapper) || wrapper;
    clearPreviewMedia(wrapper);
    activeVideoEl = null;

    const insertMedia = (node) => {
        const sub = mount.querySelector('.preview-subtitle');
        if (sub) mount.insertBefore(node, sub);
        else mount.appendChild(node);
    };

    if (plan.visualType === 'video' && plan.visualUrl) {
        const video = document.createElement('video');
        video.className = 'preview-media is-playback loaded';
        video.src = plan.visualUrl;
        // 与导出保持一致：视频原声模式保留音轨；TTS/静音模式丢弃视频原声。
        video.muted = plan.audioMode !== SCENE_AUDIO_MODE.VIDEO;
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.preload = 'auto';
        video.disablePictureInPicture = true;
        insertMedia(video);
        activeVideoEl = video;
        return { videoEl: video, imageEl: null };
    }

    if (plan.visualType === 'image' && plan.visualUrl) {
        const img = document.createElement('img');
        img.className = 'preview-media is-playback loaded';
        img.src = plan.visualUrl;
        img.alt = plan.title || '';
        insertMedia(img);
        return { videoEl: null, imageEl: img };
    }

    const empty = document.createElement('div');
    empty.className = 'preview-empty';
    empty.textContent = '当前分镜还没有画面';
    insertMedia(empty);
    return { videoEl: null, imageEl: null };
}

function freezeVideoAtEnd(videoEl) {
    if (!videoEl) return;
    try {
        videoEl.pause();
        if (Number.isFinite(videoEl.duration) && videoEl.duration > 0) {
            videoEl.currentTime = Math.max(0, videoEl.duration - 0.05);
        }
    } catch {
        // ignore
    }
}

function isVisualActive(gen, session) {
    return isActive(gen) && session === visualSession;
}

/**
 * 并行播视频：不阻塞切镜。session 失效（切镜）或 gen 失效时退出。
 * 视频先于本镜结束则定格末帧，直到本镜 session 结束。
 */
async function runVideoVisual(videoEl, gen, session, options = {}) {
    if (!videoEl) return;
    const audible = options.audible === true;
    try {
        videoEl.loop = false;
        videoEl.currentTime = 0;
        const playResult = videoEl.play();
        if (playResult && typeof playResult.then === 'function') {
            try {
                await playResult;
            } catch (error) {
                if (audible) {
                    showToast('浏览器阻止了视频原声播放，请允许此站点播放声音', 'info');
                }
            }
        }
        while (isVisualActive(gen, session) && !videoEl.ended) {
            await checkpoint(gen);
            if (!isVisualActive(gen, session)) return;
            if (paused) {
                if (!videoEl.paused) videoEl.pause();
                await sleep(TICK_MS);
                continue;
            }
            if (videoEl.paused && !videoEl.ended) {
                try {
                    await videoEl.play();
                } catch {
                    // ignore
                }
            }
            await sleep(TICK_MS);
        }
        if (videoEl.ended && isVisualActive(gen, session)) {
            freezeVideoAtEnd(videoEl);
            while (isVisualActive(gen, session)) {
                await checkpoint(gen);
                if (!isVisualActive(gen, session)) return;
                await sleep(TICK_MS);
            }
        }
    } catch (err) {
        if (err?.name === 'PlaybackAbortError') return;
    }
}

function stopActiveMedia() {
    visualSession += 1;
    setPlaybackBuffering(false);
    if (activeVideoEl) {
        try {
            activeVideoEl.pause();
        } catch {
            // ignore
        }
    }
    if (activeAudioEl) {
        try {
            activeAudioEl.pause();
            // 预载实例由 disposePreloadedAudios 统一释放，避免双重 load 竞态
            if (!preloadedAudioEls.includes(activeAudioEl)) {
                activeAudioEl.removeAttribute('src');
                activeAudioEl.load();
            }
        } catch {
            // ignore
        }
        activeAudioEl = null;
    }
    disposePreloadedAudios();
}

/**
 * @param {object} item
 * @param {number} gen
 * @param {HTMLAudioElement} [preloadedEl] 预加载好的实例，避免起播再缓冲
 */
async function playOneAudio(item, gen, preloadedEl) {
    await checkpoint(gen);
    state.playback.audioDialogueId = item.dialogueId;
    setSubtitle(item.text || '');

    const audio = preloadedEl || new Audio();
    activeAudioEl = audio;
    if (!preloadedEl) {
        audio.preload = 'auto';
        audio.src = item.url;
    }
    audio.volume = item.volume;

    try {
        // 预载实例从 0 起播
        try {
            audio.currentTime = 0;
        } catch {
            // ignore
        }
        const playResult = audio.play();
        if (playResult && typeof playResult.then === 'function') {
            await playResult.catch((e) => {
                showToast(`配音播放失败：${e?.message || '未知错误'}`, 'error');
            });
        }

        while (isActive(gen) && !audio.ended && activeAudioEl === audio) {
            await checkpoint(gen);
            if (activeAudioEl !== audio) break;
            if (paused) {
                if (!audio.paused) audio.pause();
                await sleep(TICK_MS);
                continue;
            }
            if (audio.paused && !audio.ended) {
                try {
                    await audio.play();
                } catch {
                    break;
                }
            }
            if (audio.error) break;
            await sleep(TICK_MS);
        }
    } finally {
        try {
            audio.pause();
        } catch {
            // ignore
        }
        if (!preloadedEl) {
            try {
                audio.removeAttribute('src');
                audio.load();
            } catch {
                // ignore
            }
        }
        if (activeAudioEl === audio) activeAudioEl = null;
    }
}

async function runAudioQueue(audios, gen, preloadedEls = []) {
    if (!audios.length) {
        state.playback.audioDialogueId = null;
        setSubtitle('');
        return;
    }
    for (let i = 0; i < audios.length; i += 1) {
        if (!isActive(gen)) return;
        const item = audios[i];
        const pre = preloadedEls[i] || null;
        try {
            await playOneAudio(item, gen, pre);
        } catch (err) {
            if (err?.name === 'PlaybackAbortError') throw err;
            showToast('跳过一条无法播放的配音', 'info');
        }
    }
    state.playback.audioDialogueId = null;
    setSubtitle('');
}

function startClock(gen) {
    stopClock();
    sceneStartedAt = performance.now();
    pausedAccumMs = 0;
    pauseStartedAt = 0;
    clockTimer = setInterval(() => {
        if (!isActive(gen)) return;
        if (paused) return;
        let local = (performance.now() - sceneStartedAt - pausedAccumMs) / 1000;
        if (currentSceneSpan > 0) {
            local = Math.min(local, currentSceneSpan);
        }
        state.playback.sceneLocalTime = Math.max(0, local);
        state.currentTime = sceneBaseGlobalTime + state.playback.sceneLocalTime;
        updateProgressChrome();
    }, TICK_MS);
}

function stopClock() {
    if (clockTimer) {
        clearInterval(clockTimer);
        clockTimer = null;
    }
}

async function playOneScene(scene, index, gen) {
    const plan = buildScenePlan(scene);
    // 本镜时长：scene.duration（配音齐后 = 对白时长和），与视频无关
    const sceneSpan = Math.max(resolveSceneSpan(scene), 0.1);
    currentSceneSpan = sceneSpan;

    state.currentSceneId = scene.id;
    state.playback.sceneId = scene.id;
    state.playback.sceneLocalTime = 0;
    state.playback.audioDialogueId = null;
    sceneBaseGlobalTime = playedOffsetSec;
    state.currentTime = sceneBaseGlobalTime;

    updateTimelineActive(scene.id);
    updatePreviewCaption(plan);
    updateProgressChrome();
    setSubtitle('');

    const { videoEl, imageEl } = mountVisual(plan);

    // —— 预加载阶段：时钟未启动，playhead 停在本镜起点 ——
    let audioEls = [];
    setPlaybackBuffering(true);
    try {
        const pre = await preloadSceneMedia(plan, videoEl, imageEl, gen);
        audioEls = pre.audioEls || [];
    } catch (err) {
        setPlaybackBuffering(false);
        if (err?.name === 'PlaybackAbortError') throw err;
        console.warn('[storyboard playback] preload', err);
    }
    setPlaybackBuffering(false);

    if (!isActive(gen)) {
        disposePreloadedAudios();
        currentSceneSpan = 0;
        return;
    }

    // 媒体就绪后再开时钟与音画，避免时间轴空转
    startClock(gen);

    const session = ++visualSession;
    if (plan.visualType === 'video' && videoEl) {
        runVideoVisual(videoEl, gen, session, {
            audible: plan.audioMode === SCENE_AUDIO_MODE.VIDEO,
        }).catch(() => {});
    }
    const audioTask = (plan.audioMode === SCENE_AUDIO_MODE.TTS
        ? runAudioQueue(plan.audios, gen, audioEls)
        : Promise.resolve()
    ).catch((err) => {
        if (err?.name !== 'PlaybackAbortError') {
            console.warn('[storyboard playback] audio queue', err);
        }
    });

    try {
        // 唯一切镜条件：本镜 scene.duration 走完（从就绪后起算）
        await waitMs(sceneSpan * 1000, gen);
        if (isActive(gen)) {
            playedOffsetSec += sceneSpan;
            state.currentTime = playedOffsetSec;
            state.playback.sceneLocalTime = sceneSpan;
            updateProgressChrome();
        }
    } finally {
        stopClock();
        stopActiveMedia();
        void audioTask;
        currentSceneSpan = 0;
    }
}

function finishPlayback(gen, ended) {
    if (gen !== generation) return;
    stopClock();
    state.isPlaying = false;
    paused = false;
    notifyPauseWaiters();
    state.playback.status = ended ? 'ended' : 'idle';
    if (!ended) {
        state.playback.sceneId = null;
        state.playback.audioDialogueId = null;
        state.playback.sceneLocalTime = 0;
    }
    setSubtitle('');
    stopActiveMedia();
    activeVideoEl = null;
    currentSceneSpan = 0;
    updatePlayButtonIcon();
    updateProgressChrome();
}

async function runLoop(startIndex, gen) {
    try {
        for (let i = startIndex; i < state.scenes.length; i += 1) {
            if (!isActive(gen)) return;
            const scene = state.scenes[i];
            if (!scene) continue;
            await playOneScene(scene, i, gen);
        }
        if (isActive(gen)) {
            finishPlayback(gen, true);
        }
    } catch (err) {
        if (err?.name === 'PlaybackAbortError') {
            return;
        }
        console.error('[storyboard playback]', err);
        showToast(err?.message || '预览播放失败', 'error');
        finishPlayback(gen, false);
    }
}

/**
 * 开始或恢复播放
 */
export function togglePlayback() {
    if (state.isPlaying && !paused) {
        pausePlayback();
        return;
    }
    if (state.isPlaying && paused) {
        resumePlayback();
        return;
    }
    startPlayback();
}

export function startPlayback(options = {}) {
    if (!state.scenes.length) {
        showToast('暂无分镜可播放', 'info');
        return;
    }
    if (state.viewMode !== 'timeline') {
        showToast('请切换到时间轴视图再预览', 'info');
        return;
    }
    if (!document.querySelector('.preview-wrapper')) {
        showToast('预览区域未就绪', 'info');
        return;
    }

    // 始终从当前选中分镜起播（含 ended 后再点播放：仍跟选中镜，不强制回片头）
    const targetId = options.fromSceneId != null ? options.fromSceneId : state.currentSceneId;
    let startIndex = state.scenes.findIndex(s => s.id === targetId);
    if (startIndex < 0) startIndex = 0;
    playedOffsetSec = sumDurationBeforeIndex(startIndex);
    state.currentTime = playedOffsetSec;
    // 起播瞬间就把 playhead 钉在目标分镜（避免首帧时钟未跑前仍停在旧位置）
    state.playback.sceneId = state.scenes[startIndex]?.id ?? null;
    state.playback.sceneLocalTime = 0;

    generation += 1;
    const gen = generation;
    state.playback.generation = gen;
    state.isPlaying = true;
    paused = false;
    state.playback.status = 'playing';
    notifyPauseWaiters();
    updatePlayButtonIcon();
    updatePlayheadPosition({ followScroll: true });

    runPromise = runLoop(startIndex, gen).finally(() => {
        if (gen === generation) runPromise = null;
    });
}

export function pausePlayback() {
    if (!state.isPlaying || paused) return;
    paused = true;
    pauseStartedAt = performance.now();
    state.playback.status = 'paused';
    if (activeVideoEl && !activeVideoEl.paused) {
        try {
            activeVideoEl.pause();
        } catch {
            // ignore
        }
    }
    if (activeAudioEl && !activeAudioEl.paused) {
        try {
            activeAudioEl.pause();
        } catch {
            // ignore
        }
    }
    updatePlayButtonIcon();
}

export function resumePlayback() {
    if (!state.isPlaying || !paused) return;
    if (pauseStartedAt) {
        pausedAccumMs += performance.now() - pauseStartedAt;
        pauseStartedAt = 0;
    }
    paused = false;
    state.playback.status = 'playing';
    notifyPauseWaiters();
    updatePlayButtonIcon();
}

export function stopPlayback(options = {}) {
    const { resetTime = false } = options;
    generation += 1;
    state.playback.generation = generation;
    const wasPlaying = state.isPlaying;
    state.isPlaying = false;
    paused = false;
    notifyPauseWaiters();
    stopClock();

    stopActiveMedia();
    activeVideoEl = null;
    currentSceneSpan = 0;

    state.playback.status = 'idle';
    state.playback.sceneId = null;
    state.playback.audioDialogueId = null;
    state.playback.sceneLocalTime = 0;
    if (resetTime) {
        state.currentTime = 0;
        playedOffsetSec = 0;
    }
    setSubtitle('');
    if (wasPlaying) updatePlayButtonIcon();
    updateProgressChrome();
}

/** 全量 rerender 销毁媒体后：停止播放，避免幽灵声音 */
export function onDomWillRerender() {
    if (state.isPlaying || state.playback.status === 'playing' || state.playback.status === 'paused') {
        stopPlayback();
    }
}

/** 时间轴试看引擎是否占用（含暂停态，此时仍绑定预览区媒体） */
export function isPlaybackActive() {
    return Boolean(
        state.isPlaying
        || state.playback?.status === 'playing'
        || state.playback?.status === 'paused'
    );
}

/** 主预览原生 video.controls 是否正在播（不设 isPlaying） */
export function isNativePreviewPlaying() {
    const video = document.querySelector('.preview-wrapper video.preview-media');
    if (!video) return false;
    try {
        return !video.paused && !video.ended && video.readyState > 0;
    } catch {
        return false;
    }
}

/** 任一路径占用主预览：禁止拆 .preview-wrapper 媒体节点 */
export function isPreviewMediaBusy() {
    return isPlaybackActive() || isNativePreviewPlaying();
}
