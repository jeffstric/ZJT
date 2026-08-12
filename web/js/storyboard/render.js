import state, {
    getCurrentScene,
    getTotalDuration,
    getSupportedVideoImageModes,
    videoModelSupportsLastFrame,
    getMaxVideoMediaCount,
    canAddVideoMedia,
    isRenderableMediaUrl,
    getSelectedVideoModel,
    getSelectedImageToVideoModel,
    getImageToVideoSlotModels,
    getReferenceToVideoSlotModels,
    modelNeedsFaceMask,
    isEnterpriseEdition,
    getVideoSupportedDurations,
    resolveVideoDurationSeconds,
    getVideoResolutionOptions,
    getDefaultVideoResolution,
    getAgentChatFontSizes,
    AGENT_CHAT_FONT_STEP_MIN,
    AGENT_CHAT_FONT_STEP_MAX,
    getSelectedLlmMeta,
    isSceneAgentRunning,
} from './state.js';
import { characterReferenceSelectionKey, formatDuration, mapAssetAvatar } from './adapters.js';
import { icon } from './icons.js';
import {
    t as i18nT,
    EMO_VEC_LABELS,
    EMO_VEC_MAX_SUM,
    EMO_VEC_MAX_EACH,
    EMO_VEC_COLORS,
    formatEmoVecSummary,
    getEmoVecActiveDims,
    isAudioRunningStatus,
    isAudioFailedStatus,
    parseEmoVec,
} from './utils.js';
import {
    getAutoCompleteButtonViewModel,
    getAutoCompleteSummary,
    getFirstFrameDisplayStatus,
    getFirstFrameStatusLabel,
    isAutoImageBatchActive,
} from './auto_missing_images_state.js';
import {
    getAutoVideoCompleteButtonViewModel,
    getAutoVideoCompleteSummary,
} from './auto_missing_videos_state.js';
import {
    onDomWillRerender,
    updatePlayheadPosition,
    isPreviewMediaBusy,
} from './playback.js';
import {
    SCENE_AUDIO_MODE,
    resolveSceneAudioMode,
    sceneHasDialogueAudio,
} from './playback_audio.js';
import { Region } from './ui_regions.js';
import { choosePreviewMedia } from './candidate_selection_state.js';
import { canSwitchToDigitalHuman } from './video_type_switch_state.js';
import {
    getSelectedSceneIds,
    isBatchSelectionActive,
    isSceneSelected,
} from './batch_selection_state.js';
import {
    PREVIEW_RESOLUTION_OPTIONS,
    normalizePreviewResolution,
    resolveLogicalCanvas,
    applyPreviewCanvas,
    bindPreviewCanvasObserver,
    ensurePreviewStage,
    applyTimelineRatioVars,
} from './preview_canvas.js';

export { Region } from './ui_regions.js';

// 确保 i18n 在首次 render 前已初始化（bootstrap 中已调用 initI18n）

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Map scene.videoType to Chinese label for UI. */
export function videoTypeLabel(videoType) {
    const key = String(videoType || 'video').toLowerCase();
    if (key === 'digital_human') return '对口型';
    if (key === 'image') return '图片';
    return '视频';
}

export function isDigitalHumanScene(scene) {
    return String(scene?.videoType || scene?.video_type || '').toLowerCase() === 'digital_human';
}

// 缩略图服务（参考 video_workflow.html 中 shot_frame_node.js 的实现）
// 用于场景、道具、角色图片，避免加载大图
export function getThumbnailUrl(imageUrl, size) {
    size = size || 32;
    if (!imageUrl) return '';
    if (imageUrl.startsWith('data:') || imageUrl.startsWith('blob:')) return imageUrl;
    return '/api/thumbnail?url=' + encodeURIComponent(imageUrl) + '&size=' + size;
}

function unwrapPromptAssetName(value) {
    return String(value || '')
        .replace(/【【([^】]+)】】/g, '$1')
        .replace(/〖〖([^〗]+)〗〗/g, '$1')
        .trim();
}

function removeNestedRoleNames(value) {
    return String(value || '').replace(/【【[^】]+】】/g, '').trim();
}

function normalizeAssetName(value) {
    return unwrapPromptAssetName(value).replace(/\s+/g, '');
}

function buildAssetNameCandidates(value) {
    const raw = String(value || '').trim();
    return [raw, unwrapPromptAssetName(raw), removeNestedRoleNames(raw)]
        .map(item => item.trim())
        .filter((item, index, list) => item && list.indexOf(item) === index);
}

function findPromptAsset(assetList, rawName, isProp) {
    const candidates = buildAssetNameCandidates(rawName);
    const normalizedCandidates = candidates.map(normalizeAssetName).filter(Boolean);
    let asset = assetList.find(item => normalizedCandidates.includes(normalizeAssetName(item.name || '')));
    if (!asset && isProp) {
        asset = assetList.find(item => {
            const assetName = normalizeAssetName(item.name || '');
            return assetName && normalizedCandidates.some(candidate =>
                candidate && (assetName.endsWith(candidate) || candidate.endsWith(assetName))
            );
        });
    }
    return asset || null;
}

function tagPlainRolesOutsideProps(text, names) {
    if (!names.length) return text;
    const namePattern = names.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    const plainRe = new RegExp(`(?<!【【)(${namePattern})(?!】】)`, 'g');
    const propPattern = /〖〖[^〗]+〗〗/g;
    let result = '';
    let lastIndex = 0;
    let match;
    while ((match = propPattern.exec(text)) !== null) {
        if (match.index > lastIndex) {
            result += text.substring(lastIndex, match.index).replace(plainRe, '【【$1】】');
        }
        result += match[0];
        lastIndex = match.index + match[0].length;
    }
    if (lastIndex < text.length) {
        result += text.substring(lastIndex).replace(plainRe, '【【$1】】');
    }
    return result;
}

// 将提示词文本中的角色标记替换为 <img>角色名 格式
// 参考 video_workflow.html 分镜节点的 renderPromptWithInlineChars
export function renderPromptWithInlineRoles(text, usedChars, usedProps, scene = null) {
    if (!text) return '<span style="color:#999;">(空)</span>';

    text = String(text).trim();

    // Sanitize if previously polluted with HTML from bad render
    if (text.includes('<') || text.includes('&lt;')) {
        const tmp = document.createElement('div');
        tmp.innerHTML = text;
        text = tmp.textContent || tmp.innerText || text;
    }

    const displayEl = document.createElement('span');
    let lastIndex = 0;
    const worldChars = usedChars || [];
    const worldProps = usedProps || [];

    // Pre-tag plain role names so they get imaged too (safe, only for render)
    let processedText = text;
    const names = worldChars.map(c => c.name).filter(Boolean);
    if (names.length > 0) {
        processedText = tagPlainRolesOutsideProps(processedText, names);
    }

    // Unified pattern: 角色【【】】 或 道具〖〖〗〗
    const pattern = /【【([^】]+)】】|〖〖([^〗]+)〗〗/g;
    let match;
    while ((match = pattern.exec(processedText)) !== null) {
        if (match.index > lastIndex) {
            displayEl.appendChild(document.createTextNode(processedText.substring(lastIndex, match.index)));
        }
        const isProp = match[2] !== undefined;
        const rawAssetName = (match[1] || match[2]).trim();
        const assetList = isProp ? worldProps : worldChars;
        const asset = findPromptAsset(assetList, rawAssetName, isProp);
        const assetName = asset ? String(asset.name || rawAssetName).trim() : unwrapPromptAssetName(rawAssetName);
        if (isProp && !asset) {
            displayEl.appendChild(document.createTextNode(assetName));
            lastIndex = match.index + match[0].length;
            continue;
        }
        const avatarUrl = asset && (asset.avatar || asset.reference_image || mapAssetAvatar(asset.raw || asset));
        const chip = document.createElement('span');
        chip.className = isProp ? 'prop-chip' : 'role-chip';
        chip.title = assetName;
        if (!isProp) {
            const selectionKey = characterReferenceSelectionKey(asset || { name: assetName });
            const selection = scene?.referenceSelections?.characters?.[selectionKey];
            chip.dataset.referenceVariant = 'character';
            chip.dataset.action = 'select-character-reference';
            chip.dataset.characterName = assetName;
            if (asset?.id != null) chip.dataset.characterId = String(asset.id);
            if (selection?.url) {
                chip.classList.add('has-reference-selection');
                chip.title = `${assetName} · ${selection.label || '已选择参考图'}`;
            }
        }
        if (avatarUrl) {
            const avatar = document.createElement('img');
            avatar.src = getThumbnailUrl(avatarUrl, 16);
            avatar.alt = assetName;
            avatar.style.cssText = 'width:16px;height:16px;border-radius:50%;vertical-align:middle;margin-right:3px;object-fit:cover;';
            chip.appendChild(avatar);
        } else {
            const ph = document.createElement('span');
            ph.style.cssText = 'display:inline-block;width:16px;text-align:center;vertical-align:middle;margin-right:3px;';
            chip.appendChild(ph);
        }
        const nameSpan = document.createElement('span');
        nameSpan.textContent = assetName;
        chip.appendChild(nameSpan);
        if (!isProp) {
            const selectionKey = characterReferenceSelectionKey(asset || { name: assetName });
            const selection = scene?.referenceSelections?.characters?.[selectionKey];
            if (selection?.label) {
                const label = document.createElement('span');
                label.className = 'reference-selection-label';
                label.textContent = selection.label;
                chip.appendChild(label);
            }
        }
        displayEl.appendChild(chip);
        lastIndex = match.index + match[0].length;
    }
    if (lastIndex < processedText.length) {
        displayEl.appendChild(document.createTextNode(processedText.substring(lastIndex)));
    }
    return displayEl.innerHTML;
}

function truncateText(str, maxLen = 18) {
    if (!str) return '未设置';
    const s = String(str).trim();
    return s.length > maxLen ? s.slice(0, maxLen) + '...' : s;
}

// 当前选中资产是否有结果（用于卡片角标）
function hasAsset(scene, kind) {
    if (!scene) return false;
    if (kind === 'video') return Boolean(scene.videoUrl);
    if (kind === 'first_frame') return Boolean(scene.firstFrameUrl);
    if (kind === 'last_frame') return Boolean(scene.lastFrameUrl);
    return false;
}

function assetBadge(scene, kind, label) {
    if (kind === 'first_frame') {
        const status = getFirstFrameDisplayStatus(scene);
        if (status === 'ready') return `<span class="status ready">${label}已生成</span>`;
        if (['running', 'pending', 'regenerating', 'regenerate_pending'].includes(status)) {
            return `<span class="status running">${label}${getFirstFrameStatusLabel(status)}</span>`;
        }
        if (status === 'failed' || status === 'regenerate_failed') {
            return `<span class="status failed">${label}${getFirstFrameStatusLabel(status)}</span>`;
        }
        return `<span class="status idle">${label}待生成</span>`;
    }
    return hasAsset(scene, kind)
        ? `<span class="status ready">${label}已生成</span>`
        : `<span class="status idle">${label}待生成</span>`;
}

// 分镜难度 badge：易=绿 / 中=橙 / 难=红（与 .status.ready/running/failed 同色系）
function difficultyBadge(scene) {
    const d = scene.difficulty;
    let cls = 'diff-medium';
    if (d === '易') cls = 'diff-easy';
    else if (d === '难') cls = 'diff-hard';
    return `<span class="difficulty-badge ${cls}">${escapeHtml(d || '中')}</span>`;
}

// 所属幕/分镜组名称（仅在存在时显示，避免空标签）
function actNameTag(scene) {
    return scene.actName
        ? `<span class="act-name-tag" title="${escapeHtml(scene.actName)}">${escapeHtml(scene.actName)}</span>`
        : '';
}

/** 幕号：grp_001 → 幕01；无 groupId 返回空 */
function groupActLabel(scene) {
    if (!scene || !scene.groupId) return '';
    const numStr = String(scene.groupId).replace(/^grp_?0*/i, '');
    const num = parseInt(numStr, 10);
    if (!Number.isFinite(num) || num <= 0) return '';
    return `幕${String(num).padStart(2, '0')}`;
}

function videoTypeBadgeClass(videoType) {
    const key = String(videoType || 'video').toLowerCase();
    if (key === 'digital_human') return 'type-digital-human';
    if (key === 'image') return 'type-image';
    return 'type-video';
}

/** 场景：补全 avatar（与左侧栏一致） */
function resolveSceneLocation(scene) {
    if (!scene || !scene.location) return null;
    let loc = { ...scene.location };
    const locId = loc.id || loc.db_id;
    if (locId && !loc.avatar && !loc.reference_image) {
        const fullLoc = (state.locations || []).find((l) => String(l.id) === String(locId));
        if (fullLoc) loc = { ...fullLoc, ...loc };
    }
    const avatar = loc.avatar || loc.reference_image || mapAssetAvatar(loc.raw || loc) || '';
    return {
        id: locId,
        name: loc.name || '场景',
        avatar,
    };
}

/**
 * 角色列表（去重保序）：
 * 1) 对话 characterId  2) referenceSelections.characters  3) 提示词【【角色】】
 */
function resolveSceneCharacters(scene) {
    if (!scene) return [];
    const byKey = new Map();
    const worldChars = state.characters || [];

    const findById = (id) => worldChars.find((c) => String(c.id) === String(id));
    const findByName = (name) => {
        const n = String(name || '').trim().replace(/\s+/g, '');
        if (!n) return null;
        return worldChars.find((c) => String(c.name || '').trim().replace(/\s+/g, '') === n);
    };
    const avatarOf = (c, fallback = '') =>
        (c && (c.avatar || c.reference_image || mapAssetAvatar(c.raw || c))) || fallback || '';

    const add = (id, name, avatar) => {
        const nm = String(name || '').trim();
        if (!nm) return;
        const key = id != null && id !== '' ? `id:${id}` : `name:${nm.replace(/\s+/g, '')}`;
        if (byKey.has(key)) return;
        byKey.set(key, { id: id ?? null, name: nm, avatar: avatar || '' });
    };

    (scene.dialogues || []).forEach((d) => {
        if (d.characterId == null || d.characterId === '') return;
        const c = findById(d.characterId);
        if (c) add(c.id, c.name, avatarOf(c));
    });

    const refChars = scene.referenceSelections?.characters || {};
    Object.entries(refChars).forEach(([key, item]) => {
        const id = item?.character_id ?? item?.characterId ?? null;
        const nameFromKey = String(key || '').replace(/^name:/, '');
        const name = (item?.name || nameFromKey || '').trim();
        const c = (id != null ? findById(id) : null) || findByName(name);
        if (c) add(c.id, c.name, avatarOf(c, item?.url || ''));
        else if (name) add(id, name, item?.url || '');
    });

    const texts = [
        scene.promptJson?.scene_desc || '',
        scene.promptJson?.character_desc || '',
        scene.videoPrompt || '',
    ].join('\n');
    const re = /【【([^】]+)】】/g;
    let match;
    while ((match = re.exec(texts)) !== null) {
        const name = String(match[1] || '').trim();
        const c = findByName(name);
        if (c) add(c.id, c.name, avatarOf(c));
        else if (name) add(null, name, '');
    }

    return Array.from(byKey.values());
}

/** 有台词的对白配音进度；无对白返回 null（不展示） */
function dialogueAudioProgress(scene) {
    const dialogues = (scene?.dialogues || []).filter((d) => String(d.text || '').trim());
    if (!dialogues.length) return null;
    const done = dialogues.filter((d) => String(d.audioUrl || d.audio_url || '').trim()).length;
    return { done, total: dialogues.length };
}

function audioProgressBadge(scene) {
    const p = dialogueAudioProgress(scene);
    if (!p) return '';
    const cls = p.done >= p.total ? 'ready' : (p.done > 0 ? 'running' : 'idle');
    return `<span class="status ${cls}" title="配音进度">配 ${p.done}/${p.total}</span>`;
}

function digitalHumanAudioHint(scene) {
    const dialogues = scene?.dialogues || [];
    const hasReadyAudio = dialogues.some((dialogue) =>
        String(dialogue.audioUrl || dialogue.audio_url || '').trim()
    );
    if (hasReadyAudio) {
        return {
            label: '配音已就绪',
            cssClass: 'ready',
            title: '对口型分镜配音已完成，可以生成 MiniMax H3 数字人视频',
        };
    }

    const runningStatuses = new Set([0, 1, '0', '1', 'pending', 'queued', 'running', 'processing']);
    const hasRunningAudio = dialogues.some((dialogue) => {
        const status = dialogue.audioStatus ?? dialogue.audio_status ?? dialogue.status;
        return runningStatuses.has(typeof status === 'string' ? status.toLowerCase() : status);
    });
    if (hasRunningAudio) {
        return {
            label: '配音生成中',
            cssClass: 'running',
            title: '对口型分镜的配音正在生成，完成后即可生成 MiniMax H3 数字人视频',
        };
    }

    return {
        label: '需先配音',
        cssClass: 'missing',
        title: '对口型分镜：请先在对话 Tab 生成配音，再生成 MiniMax H3 数字人视频',
    };
}

export function updateDigitalHumanAudioHint(scene) {
    if (!scene || scene.id !== state.currentSceneId) return false;
    const element = document.querySelector('.ai-dh-hint');
    if (!element) return false;
    const hint = digitalHumanAudioHint(scene);
    element.className = `ai-dh-hint ${hint.cssClass}`;
    element.title = hint.title;
    element.textContent = `对口型 · MiniMax H3 · ${hint.label}`;
    return true;
}

function renderGridThumb(scene) {
    const act = groupActLabel(scene);
    const typeLabel = videoTypeLabel(scene?.videoType);
    const typeCls = videoTypeBadgeClass(scene?.videoType);
    return `
        <div class="storyboard-thumb">
            ${mediaFrame(scene)}
            <span class="grid-type-badge ${typeCls}">${escapeHtml(typeLabel)}</span>
            <span class="grid-thumb-duration">${escapeHtml(scene.durationLabel || '00:00')}</span>
            ${act ? `<span class="grid-thumb-act">${escapeHtml(act)}</span>` : ''}
        </div>`;
}

function renderGridLocationRow(scene) {
    const loc = resolveSceneLocation(scene);
    if (!loc) {
        return `<div class="card-meta-row card-location is-empty" title="未选场景">
            <span class="card-meta-icon" aria-hidden="true">📍</span>
            <span class="card-meta-text is-muted">未选场景</span>
        </div>`;
    }
    const img = loc.avatar
        ? `<img class="card-meta-avatar is-square" src="${escapeHtml(getThumbnailUrl(loc.avatar, 24))}" alt="">`
        : `<span class="card-meta-avatar is-square is-placeholder" aria-hidden="true"></span>`;
    return `<div class="card-meta-row card-location" title="${escapeHtml(loc.name)}">
        <span class="card-meta-icon" aria-hidden="true">📍</span>
        ${img}
        <span class="card-meta-text">${escapeHtml(truncateText(loc.name, 14))}</span>
    </div>`;
}

function renderGridCharactersRow(scene) {
    const chars = resolveSceneCharacters(scene);
    if (!chars.length) {
        return `<div class="card-meta-row card-characters is-empty" title="无角色">
            <span class="card-meta-icon" aria-hidden="true">👤</span>
            <span class="card-meta-text is-muted">无角色</span>
        </div>`;
    }
    const maxShow = 3;
    const shown = chars.slice(0, maxShow);
    const rest = chars.length - maxShow;
    const avatars = shown.map((c) => {
        if (c.avatar) {
            return `<img class="card-char-avatar" src="${escapeHtml(getThumbnailUrl(c.avatar, 24))}" alt="${escapeHtml(c.name)}" title="${escapeHtml(c.name)}">`;
        }
        const initial = (c.name || '?').slice(0, 1);
        return `<span class="card-char-avatar is-placeholder" title="${escapeHtml(c.name)}">${escapeHtml(initial)}</span>`;
    }).join('');
    const nameParts = shown.map((c) => c.name);
    if (rest > 0) nameParts.push(`+${rest}`);
    const nameText = nameParts.join(' · ');
    const fullTitle = chars.map((c) => c.name).join('、');
    return `<div class="card-meta-row card-characters" title="${escapeHtml(fullTitle)}">
        <span class="card-char-stack">${avatars}</span>
        <span class="card-meta-text">${escapeHtml(truncateText(nameText, 18))}</span>
    </div>`;
}

function renderGridPerspective(scene) {
    const perspective = String(
        scene?.promptJson?.perspective || scene?.sceneInfo?.perspective || ''
    ).trim();
    if (!perspective) return '';
    return `<div class="card-perspective" title="${escapeHtml(perspective)}">${escapeHtml(truncateText(perspective, 22))}</div>`;
}

/** 单张 Grid 卡片（cell 含 insert slot），renderGridInner / 局部刷新共用 */
function renderStoryboardCardCell(scene, nextScene) {
    if (!scene) return '';
    const groupLabel = groupActLabel(scene);
    const actName = String(scene.actName || '').trim();
    // 幕号已在缩略图展示时，body 仅在 actName 与幕号不同时再显示长名称
    const showActName = actName && actName !== groupLabel;
    const selecting = isBatchSelectionActive();
    const selected = selecting && isSceneSelected(scene.id);
    return `
            <div class="storyboard-grid-cell" data-scene-id="${scene.id}">
                <article class="storyboard-card ${state.currentSceneId === scene.id ? 'active' : ''} ${selecting ? 'is-batch-selecting' : ''} ${selected ? 'is-batch-selected' : ''}" data-scene="${scene.id}">
                    ${selecting ? `<input class="storyboard-batch-checkbox" type="checkbox" data-action="toggle-batch-scene" data-id="${scene.id}" aria-label="选择${escapeHtml(scene.title)}" ${selected ? 'checked' : ''} ${state.batchSelection?.submittingAction ? 'disabled' : ''}>` : ''}
                    ${renderGridThumb(scene)}
                    <div class="storyboard-card-body">
                        <div class="card-title-row">
                            <h3>${escapeHtml(scene.title)}</h3>
                            ${difficultyBadge(scene)}
                        </div>
                        <div class="card-status">${assetBadge(scene, 'first_frame', '图')} ${assetBadge(scene, 'video', '视频')} ${audioProgressBadge(scene)}</div>
                        ${renderGridLocationRow(scene)}
                        ${renderGridCharactersRow(scene)}
                        ${renderGridPerspective(scene)}
                        ${showActName ? `<div class="card-act-name">${actNameTag(scene)}</div>` : ''}
                        ${selecting ? '' : `<div class="storyboard-card-actions">
                            <button data-action="edit-scene" data-id="${scene.id}">${icon('edit', 14)} 编辑</button>
                            <button data-action="duplicate-scene" data-id="${scene.id}"${state.duplicatingSceneId === scene.id ? ' disabled' : ''}>${icon('copy', 14)} 复制</button>
                            <button data-action="delete-scene" data-id="${scene.id}">${icon('delete', 14)} 删除</button>
                        </div>`}
                    </div>
                </article>
                ${!selecting && nextScene ? renderInsertSceneSlot(scene, nextScene, 'grid') : ''}
            </div>`;
}

function renderFirstFrameColoringToolbar(scene) {
    // 播放中 / 无图 / 当前预览不是图：不展示
    if (!scene || state.isPlaying) return '';
    const previewMedia = choosePreviewMedia(scene);
    if (previewMedia.kind !== 'image' || !previewMedia.url) return '';
    return `
        <div class="preview-image-toolbar">
            <button
                type="button"
                class="preview-tool-btn"
                data-action="color-first-frame"
                title="涂色编辑分镜图"
            >${icon('edit', 14)} 涂色编辑</button>
        </div>`;
}

export function mediaFrame(scene) {
    if (!scene) {
        return '<div class="preview-empty">选择一个分镜开始编辑</div>';
    }
    // 时间轴预览播放中由 playback.js 接管媒体元素；静态渲染时保留 controls。
    const previewMedia = choosePreviewMedia(scene);
    if (previewMedia.kind === 'video') {
        if (state.isPlaying) {
            return `<video src="${escapeHtml(previewMedia.url)}" playsinline muted class="preview-media is-playback"></video>`;
        }
        return `<video src="${escapeHtml(previewMedia.url)}" controls class="preview-media"></video>`;
    }
    if (previewMedia.kind === 'image') {
        return `<div class="preview-media-stack">
            <img src="${escapeHtml(previewMedia.url)}" alt="${escapeHtml(scene.title)}" class="preview-media">
            ${renderFirstFrameColoringToolbar(scene)}
        </div>`;
    }
    const displayStatus = getFirstFrameDisplayStatus(scene);
    return `<div class="preview-empty preview-empty-${displayStatus}">${escapeHtml(getFirstFrameStatusLabel(displayStatus) || '当前分镜还没有画面')}</div>`;
}

/** 主预览字幕层 HTML（播放引擎写入文本） */
export function previewSubtitleHtml() {
    return '<div class="preview-subtitle" hidden></div>';
}

function renderFirstFrameStatusMark(scene) {
    const status = getFirstFrameDisplayStatus(scene);
    if (status === 'ready') return '';
    const label = getFirstFrameStatusLabel(status);
    const spinner = status === 'running' || status === 'regenerating' ? icon('loading', 12) : '';
    return `<span class="first-frame-status-mark ${status}">${spinner}${escapeHtml(label)}</span>`;
}

function renderVideoTypeBadge(scene) {
    if (!isDigitalHumanScene(scene)) return '';
    return `<span class="scene-video-type-badge digital-human" title="对口型（MiniMax H3，需先配音）">对口型</span>`;
}

function renderTimelineMediaFrame(scene) {
    const status = getFirstFrameDisplayStatus(scene);
    const label = getFirstFrameStatusLabel(status);
    return `<span class="scene-timeline-media-frame first-frame-${status}">
        ${renderFirstFrameStatusMark(scene)}
        ${renderVideoTypeBadge(scene)}
        ${scene.firstFrameUrl
            ? `<img src="${escapeHtml(scene.firstFrameUrl)}" alt="${escapeHtml(scene.title)}">`
            : `<span>${escapeHtml(label || '无画面')}</span>`}
    </span>`;
}

function renderAutoCompleteControl() {
    const vm = getAutoCompleteButtonViewModel();
    const lockedAttrs = vm.locked ? 'aria-disabled="true" data-batch-locked="true"' : '';
    const disabledAttr = vm.disabled ? 'disabled' : '';
    const busyAttr = vm.busy ? 'aria-busy="true"' : '';
    return `
        <button
            class="${vm.className}"
            data-action="auto-complete-missing-frames"
            ${lockedAttrs}
            ${disabledAttr}
            ${busyAttr}
            title="批量补全缺失首帧"
        >${icon(vm.icon, 15)} <span>${escapeHtml(vm.label)}</span></button>`;
}

function renderAutoVideoCompleteControl() {
    const vm = getAutoVideoCompleteButtonViewModel();
    const lockedAttrs = vm.locked ? 'aria-disabled="true" data-batch-locked="true"' : '';
    const disabledAttr = vm.disabled ? 'disabled' : '';
    const busyAttr = vm.busy ? 'aria-busy="true"' : '';
    const title = escapeHtml(vm.title || '批量生成缺失分镜视频（需已有首帧）');
    return `
        <button
            class="${vm.className}"
            data-action="auto-complete-missing-videos"
            ${lockedAttrs}
            ${disabledAttr}
            ${busyAttr}
            title="${title}"
        >${icon(vm.icon, 15)} <span>${escapeHtml(vm.label)}</span></button>`;
}

function renderAutoCompleteHeader(title, actionsHtml = '') {
    if (state.viewMode === 'grid' && isBatchSelectionActive()) {
        const selectedCount = getSelectedSceneIds().length;
        const totalCount = (state.scenes || []).length;
        const submitting = Boolean(state.batchSelection?.submittingAction);
        const disabled = selectedCount === 0 || submitting ? 'disabled' : '';
        const selectedIds = new Set(getSelectedSceneIds().map(String));
        const selectedScenes = (state.scenes || []).filter(scene => selectedIds.has(String(scene.id)));
        const existingImageCount = selectedScenes.filter(scene => Boolean(String(scene.firstFrameUrl || '').trim())).length;
        const isCommunity = String(state.editionInfo?.mode || '').toLowerCase() === 'community';
        const imageVerb = existingImageCount === 0
            ? '生成'
            : (existingImageCount === selectedCount ? '重新生成' : '生成/重新生成');
        const imageBatchActive = isAutoImageBatchActive();
        const imageActionLabel = imageBatchActive
            ? '分镜图生成中'
            : `${isCommunity ? '批量' : '按幕'}${imageVerb}分镜图`;
        const imageActionTitle = imageBatchActive
            ? '当前已有分镜图生成任务进行中'
            : `${isCommunity ? '当前社区版将逐镜生成首帧' : '按幕使用 2×2/3×3 宫格生成首帧'}；已有图片会保留为候选`;
        const imageDisabled = selectedCount === 0 || submitting || imageBatchActive ? 'disabled' : '';
        return `
            <div class="auto-complete-header storyboard-batch-toolbar" data-auto-complete-header>
                <span class="auto-complete-title">已选择 ${selectedCount} / ${totalCount}</span>
                <div class="auto-complete-actions" aria-live="polite">
                    <button class="btn-ghost" data-action="batch-select-all" ${submitting ? 'disabled' : ''}>全选</button>
                    <button class="btn-ghost" data-action="batch-invert-selection" ${submitting ? 'disabled' : ''}>反选</button>
                    <button class="btn-ghost" data-action="batch-clear-selection" ${submitting ? 'disabled' : ''}>清空</button>
                    <span class="storyboard-batch-divider" aria-hidden="true"></span>
                    <button data-action="batch-generate-voiceovers" ${disabled}>${icon('mic', 15)} 批量生成配音</button>
                    <button data-action="batch-generate-videos" ${disabled}>${icon('video', 15)} 批量生成视频</button>
                    <button data-action="batch-generate-images" title="${imageActionTitle}" ${imageDisabled}>${icon('wand', 15)} ${imageActionLabel}</button>
                    <button class="storyboard-batch-delete" data-action="batch-delete-scenes" ${disabled}>${icon('delete', 15)} 删除分镜</button>
                    <button class="btn-ghost" data-action="exit-batch-selection" ${submitting ? 'disabled' : ''}>完成</button>
                    ${actionsHtml}
                </div>
            </div>`;
    }
    const summary = getAutoCompleteSummary();
    const videoSummary = getAutoVideoCompleteSummary();
    const videoHint = videoSummary.missingCount > 0
        ? ` · 视频 ${videoSummary.missingCount} 待生成`
        : '';
    const gate = state.autoImageLocationGate || {};
    const parentNames = (gate.blockers || [])
        .map(item => item.parent_location_name)
        .filter(Boolean)
        .join('、');
    const gateMessage = gate.status && gate.status !== 'idle'
        ? `<span class="auto-location-reference-alert ${escapeHtml(gate.status)}"
                 title="${escapeHtml(gate.message || '')}">${escapeHtml(
                     parentNames
                         ? `${parentNames} 缺少参考图，后续分镜队列尚未启动`
                         : (gate.message || '场景参考图尚未就绪'),
                 )}</span>`
        : '';
    return `
        <div class="auto-complete-header" data-auto-complete-header>
            <span class="auto-complete-title">${escapeHtml(title)} · ${summary.totalScenes} 个分镜 · ${summary.missingCount} 个待生成${videoHint}</span>
            ${gateMessage}
            <div class="auto-complete-actions" aria-live="polite">
                ${renderAutoCompleteControl()}
                ${renderAutoVideoCompleteControl()}
                ${actionsHtml}
            </div>
        </div>`;
}

// 预览媒体（img/video）的稳定 key，用于判断新旧是否同一资源
export function previewMediaKey(el) {
    if (!el) return '';
    return `${el.tagName}|${el.getAttribute('src') || ''}`;
}

// 给新插入的 .preview-media 元素附加过渡：与 oldKey 相同则立即显示（避免重建闪烁），不同则等加载后淡入。
// 供 renderApp 全量重建与 polling 局部更新复用。
export function attachPreviewMediaTransition(newPreview, oldKey) {
    if (!newPreview) return;
    if (newPreview.classList.contains('preview-media')) {
        const newKey = previewMediaKey(newPreview);
        if (newKey === oldKey) {
            newPreview.classList.add('loaded');
            return;
        }
        if (newPreview.tagName === 'IMG') {
            if (newPreview.complete && newPreview.naturalWidth > 0) {
                newPreview.classList.add('loaded');
            } else {
                newPreview.addEventListener('load', () => newPreview.classList.add('loaded'), { once: true });
                newPreview.addEventListener('error', () => newPreview.classList.add('loaded'), { once: true });
            }
        } else if (newPreview.tagName === 'VIDEO') {
            if (newPreview.readyState >= 2) {
                newPreview.classList.add('loaded');
            } else {
                newPreview.addEventListener('loadeddata', () => newPreview.classList.add('loaded'), { once: true });
                newPreview.addEventListener('error', () => newPreview.classList.add('loaded'), { once: true });
            }
        } else {
            newPreview.classList.add('loaded');
        }
    }
}

function episodeFolderStatusLabel(folder) {
    if (!folder) return '';
    if (folder.storyboard_id) {
        const n = Number(folder.scene_count) || 0;
        return n > 0 ? `${n} 分镜` : '已创建';
    }
    if (folder.status === 'not_created' || folder.script_id) return '未建故事板';
    return '可新建';
}

function renderEpisodePicker() {
    if (!state.showEpisodePicker) return '';
    const folders = [...(state.episodeFolders || [])]
        .sort((a, b) => (Number(a.episode_number) || 0) - (Number(b.episode_number) || 0));
    const currentEp = Number(state.episodeNumber) || 1;
    const rows = folders.length
        ? folders.map((f) => {
            const ep = Number(f.episode_number) || 1;
            const active = ep === currentEp ? 'active' : '';
            const title = f.script_title || f.storyboard_title || `第${ep}集`;
            const status = episodeFolderStatusLabel(f);
            return `
                <button type="button" class="episode-picker-item ${active}"
                    data-action="switch-episode"
                    data-episode="${ep}"
                    data-script-id="${f.script_id || ''}"
                    data-storyboard-id="${f.storyboard_id || ''}"
                    title="${escapeHtml(title)}">
                    <span class="episode-picker-ep">第${ep}集</span>
                    <span class="episode-picker-title">${escapeHtml(truncateText(title, 18))}</span>
                    <span class="episode-picker-status">${escapeHtml(status)}</span>
                </button>`;
        }).join('')
        : `<div class="episode-picker-empty">${state.episodeFoldersLoading ? '加载中…' : '暂无集列表，可在下方输入集数进入'}</div>`;

    return `
        <div class="episode-picker-panel" data-episode-picker-panel>
            <div class="episode-picker-list">${rows}</div>
            <div class="episode-picker-custom">
                <label class="episode-picker-custom-label">其他集数</label>
                <div class="episode-picker-custom-row">
                    <input type="number" min="1" step="1" class="episode-picker-input"
                        data-episode-custom-input
                        placeholder="输入集数"
                        value="">
                    <button type="button" class="btn-primary episode-picker-go" data-action="switch-episode-custom">进入</button>
                </div>
                <p class="episode-picker-hint">无故事板时将自动创建；有剧本的集会自动关联剧本。</p>
            </div>
        </div>`;
}

function getPowerLevelClass(power) {
    const val = typeof power === 'number' ? power : parseFloat(String(power ?? '').replace(/,/g, ''));
    if (!Number.isFinite(val)) return '';
    if (val < 100) return 'low-power';
    if (val < 1000) return 'medium-power';
    return 'high-power';
}

function formatPowerDisplay(power) {
    if (power == null || power === '') return '--';
    const num = typeof power === 'number' ? power : Number(power);
    if (Number.isFinite(num)) return num.toLocaleString();
    return String(power);
}

function isEmptyStoryboard() {
    return !Array.isArray(state.scenes) || state.scenes.length === 0;
}

function hasActiveScriptSplit() {
    return Boolean(state.generateFromScriptTaskId || state.isGeneratingFromScript);
}

/** 空故事板且拆分弹窗已关、无进行中任务时，右上角显示「开始拆分」 */
function canShowStartSplitEntry() {
    return isEmptyStoryboard()
        && !hasActiveScriptSplit()
        && !state.showGenerateFromScriptDialog
        && !state.ratioGateActive;
}

// Header 拆分入口：进行中显示进度徽章；空板且弹窗已关时显示「开始拆分」
function renderHeaderSplitBadge() {
    if (state.generateFromScriptTaskId && !state.showGenerateProgressDialog) {
        const rawPct = Number(state.generateProgressPercent);
        const pct = Number.isFinite(rawPct) ? Math.round(Math.max(0, Math.min(100, rawPct))) : 0;
        const errored = Boolean(state.generateProgressError);
        const iconHtml = errored
            ? icon('stop', 14)
            : `<span class="spinner mini">${icon('loading', 14)}</span>`;
        const label = errored ? '拆分待处理' : `拆分中 ${pct}%`;
        const title = errored
            ? '剧本拆分已停止，点击查看详情'
            : '剧本拆分进行中（后台运行），点击查看进度';
        return `
        <button type="button" class="header-split-badge ${errored ? 'is-errored' : ''}"
            data-action="reopen-generate-progress" title="${escapeHtml(title)}">
            ${iconHtml}
            <span class="header-split-badge-label">${escapeHtml(label)}</span>
        </button>`;
    }
    if (!canShowStartSplitEntry()) return '';
    return `
        <button type="button" class="header-split-badge header-start-split"
            data-action="open-generate-from-script" title="根据本集剧本拆分并生成分镜">
            ${icon('wand', 14)}
            <span class="header-split-badge-label">开始拆分</span>
        </button>`;
}

function renderHeader() {
    const power = state.computingPower;
    const powerText = formatPowerDisplay(power);
    const powerLevel = getPowerLevelClass(power);
    const epOpen = state.showEpisodePicker ? 'open' : '';
    return `
        <header class="header">
            <div class="header-left">
                <img src="/files/logo.svg" alt="Logo" class="header-logo-img" data-route="storyboard-list">
                <div>
                    <h1 class="header-title">${escapeHtml(state.title)}</h1>
                    <div class="header-subtitle">
                        <div class="episode-switcher ${epOpen}" data-episode-switcher>
                            <button type="button" class="episode-switcher-btn" data-action="toggle-episode-picker"
                                title="切换集数（可进入尚未创建的故事板）" aria-expanded="${state.showEpisodePicker ? 'true' : 'false'}">
                                第${state.episodeNumber || 1}集
                                <span class="episode-switcher-caret" aria-hidden="true">▾</span>
                            </button>
                            ${renderEpisodePicker()}
                        </div>
                        <span class="header-subtitle-sep">·</span>
                        <select class="header-ratio-select" data-ratio-select title="点击切换画面比例">
                            ${['9:16','3:4','1:1','4:3','16:9'].map(r => 
                                `<option value="${r}" ${state.workflowRatio === r ? 'selected' : ''}>${r}</option>`
                            ).join('')}
                        </select>
                        <select class="header-preview-res-select" data-preview-resolution-select
                            title="预览逻辑分辨率（与视频生成分辨率独立；默认 720p）">
                            ${PREVIEW_RESOLUTION_OPTIONS.map((opt) => {
                                const cur = normalizePreviewResolution(state.previewResolution);
                                const canvas = resolveLogicalCanvas(state.workflowRatio || '16:9', opt.value);
                                const dim = `${canvas.width}×${canvas.height}`;
                                return `<option value="${opt.value}" ${cur === opt.value ? 'selected' : ''}>${opt.label} · ${dim}</option>`;
                            }).join('')}
                        </select>
                        <span class="header-style-info" data-action="edit-global-style" title="点击编辑全局画风和构图倾向">
                            画风：${escapeHtml(truncateText(state.style, 15))} 构图倾向：${escapeHtml(truncateText(state.compositionPreference, 15))}
                        </span>
                    </div>
                </div>
            </div>
            <nav class="header-nav" aria-label="创作工坊导航">
                <button class="header-nav-btn" data-route="script">剧本策划</button>
                <button class="header-nav-btn" data-route="canvas">画布</button>
                <button class="header-nav-btn active" type="button">编辑器</button>
            </nav>
            <div class="header-right">
                ${renderHeaderSplitBadge()}
                <button type="button"
                    class="computing-power-display ${powerLevel}"
                    data-action="open-power-logs"
                    title="当前算力（点击查看日志）">
                    <span class="power-icon">⚡</span>
                    <span class="power-value">${escapeHtml(powerText)}</span>
                </button>
                <button class="btn-primary" data-action="export-full">一键转视频</button>
                <button class="btn-ghost" data-action="export-scenes">导出素材包</button>
            </div>
        </header>`;
}

function renderScenePanel(scene) {
    const prompt = scene.promptJson || {};
    const currentVideoType = String(scene.videoType || 'video');
    const switchState = state.videoTypeSwitch || {};
    const switchSaving = Boolean(switchState.saving);
    const dhAvailability = canSwitchToDigitalHuman(scene);
    const videoTypeSwitchHtml = currentVideoType === 'image' ? '' : `
        <div class="scene-video-type-switch">
            <div class="scene-video-type-switch-header">
                <span>分镜生成方式</span>
                <small>${switchSaving ? '正在切换…' : '切换后不会删除已有视频'}</small>
            </div>
            <div class="video-type-switch-options" role="group" aria-label="分镜生成方式">
                <button type="button"
                    class="video-type-switch-option ${currentVideoType === 'video' ? 'active' : ''}"
                    data-action="request-video-type-switch" data-video-type="video"
                    ${switchSaving || currentVideoType === 'video' ? 'disabled' : ''}>视频模式</button>
                <button type="button"
                    class="video-type-switch-option ${currentVideoType === 'digital_human' ? 'active' : ''}"
                    data-action="request-video-type-switch" data-video-type="digital_human"
                    title="${escapeHtml(dhAvailability.reason || '使用单人配音生成对口型视频')}"
                    ${switchSaving || currentVideoType === 'digital_human' || !dhAvailability.allowed ? 'disabled' : ''}>对口型</button>
            </div>
            ${!dhAvailability.allowed ? `<div class="video-type-switch-warning">对口型模式仅支持单个说话角色</div>` : ''}
        </div>`;

    const allChars = state.characters || [];

    // 丰富 location / props 使用 state 里的完整数据（含 avatar），即使后端只返回 id/name
    let currentLocation = scene && scene.location ? { ...scene.location } : null;
    if (currentLocation && !currentLocation.avatar && !currentLocation.reference_image) {
        const locId = currentLocation.id || currentLocation.db_id;
        const fullLoc = state.locations.find(l => String(l.id) === String(locId));
        if (fullLoc) currentLocation = { ...fullLoc, ...currentLocation };
    }

    // 场景显示（带头像，参考分镜节点可切换/添加）
    let locationHtml;
    if (currentLocation) {
        const loc = currentLocation;
        const locImg = loc.avatar || loc.reference_image;
        const locationSelection = scene.referenceSelections?.location;
        const locationLabel = locationSelection?.label || locationSelection?.angle || '';
        locationHtml = `<span class="asset-chip ${locationSelection?.url ? 'has-reference-selection' : ''}" data-action="select-location-reference" data-scene-id="${scene.id}" data-location-id="${escapeHtml(loc.id || loc.db_id || '')}" title="点击选择场景角度">
            ${locImg ? `<img src="${escapeHtml(getThumbnailUrl(locImg, 24))}" alt="">` : ''}
            ${escapeHtml(loc.name || '场景')}
            ${locationLabel ? `<span class="reference-selection-label">${escapeHtml(locationLabel)}</span>` : ''}
            <span class="remove-x" data-action="remove-location" data-scene-id="${scene.id}" title="移除">×</span>
        </span>`;
    } else {
        locationHtml = `<span class="asset-chip add" data-action="switch-location" data-scene-id="${scene.id}">+ 选择场景</span>`;
    }

    return `
        <div class="tab-panel">
            ${videoTypeSwitchHtml}
            <div class="scene-assets-bar">
                <div class="assets-row">
                    <span class="assets-label">场景:</span>
                    ${locationHtml}
                </div>
            </div>

            <div class="info-card">
                <div class="info-card-header">
                    <div class="info-card-title">${icon('image', 18)} 画面提示词</div>
                </div>
                <div class="info-card-body">
                    <div style="font-size:10px;color:#9ca3af;margin-bottom:2px;">提示：输入 @ 可插入角色或道具</div>
                    <div class="prompt-display" data-prompt-type="scene" data-scene-id="${scene.id}" style="border:1px solid #ccc; padding:8px; border-radius:4px; background:#fff; min-height:80px; white-space:pre-wrap; font-size:12px; cursor:text; overflow:auto;">${renderPromptWithInlineRoles(prompt.scene_desc || '', allChars, state.props, scene)}</div>
                </div>
            </div>

            <div class="info-card">
                <div class="info-card-header">
                    <div class="info-card-title">${icon('image', 18)} 视频提示词（${escapeHtml(videoTypeLabel(scene.videoType))}）${isDigitalHumanScene(scene) ? ' · 台词以配音为准' : ''}</div>
                </div>
                <div class="info-card-body">
                    <div style="font-size:10px;color:#9ca3af;margin-bottom:2px;">提示：输入 @ 可插入角色或道具</div>
                    <div class="prompt-display" data-prompt-type="video" data-scene-id="${scene.id}" style="border:1px solid #ccc; padding:8px; border-radius:4px; background:#fff; min-height:80px; white-space:pre-wrap; font-size:12px; cursor:text; overflow:auto;">${renderPromptWithInlineRoles(scene.videoPrompt || '', allChars, state.props, scene)}</div>
                </div>
            </div>
        </div>`;
}

function renderDialogueAudioSource(scene) {
    const hasVideo = Boolean(String(scene.videoUrl || '').trim());
    const hasTts = sceneHasDialogueAudio(scene.dialogues);
    const preferredVideo = Boolean(scene.audioEmbedded);
    // 有效音源与预览/导出一致：无配音时自动视频原声；配音就绪后 audio_embedded=0 自动回 TTS
    const audioMode = resolveSceneAudioMode({
        visualType: hasVideo ? 'video' : 'empty',
        audioEmbedded: preferredVideo,
        audios: hasTts ? [{}] : [],
        videoHasAudio: scene.videoHasAudio,
    });
    const useVideoAudio = audioMode === SCENE_AUDIO_MODE.VIDEO;
    const autoVideoFallback = useVideoAudio && !preferredVideo && hasVideo && !hasTts;

    let hint = '视频保持静音，连续预览和完整视频导出按顺序使用下方对话配音。';
    if (autoVideoFallback) {
        hint = '当前没有对话配音，已自动使用视频原声；生成配音后会自动改回对话配音。';
    } else if (useVideoAudio && hasVideo) {
        hint = '连续预览和完整视频导出使用视频自带音轨，不再播放下方对话配音。';
    } else if (preferredVideo && !hasVideo) {
        hint = hasTts
            ? '当前分镜暂无视频；生成视频前，连续预览和导出会暂用下方对话配音。'
            : '当前分镜暂无视频与对话配音，生成后再预览。';
    } else if (!hasTts && !hasVideo) {
        hint = '暂无视频与对话配音；生成视频或配音后再预览。';
    }

    const videoLabel = autoVideoFallback
        ? '视频原声<span class="dialogue-audio-source-auto-badge">自动</span>'
        : '视频原声';

    return `
        <section class="dialogue-audio-source" aria-labelledby="dialogue-audio-source-title">
            <div class="dialogue-audio-source-header">
                <strong id="dialogue-audio-source-title">音频来源</strong>
                <small>视频原声与对话配音不会同时播放</small>
            </div>
            <div class="dialogue-audio-source-options" role="radiogroup" aria-label="音频来源">
                <button type="button"
                    class="dialogue-audio-source-option ${useVideoAudio ? '' : 'active'}"
                    data-action="set-scene-audio-source" data-audio-source="tts"
                    role="radio" aria-checked="${useVideoAudio ? 'false' : 'true'}"
                    title="使用下方对话配音；无配音时会自动使用视频原声">对话配音（TTS）</button>
                <button type="button"
                    class="dialogue-audio-source-option ${useVideoAudio ? 'active' : ''}"
                    data-action="set-scene-audio-source" data-audio-source="video"
                    role="radio" aria-checked="${useVideoAudio ? 'true' : 'false'}"
                    title="${hasVideo ? (autoVideoFallback ? '无对话配音，已自动使用视频原声' : '使用视频文件自带的音轨') : '当前分镜暂无视频'}"
                    ${!hasVideo ? 'disabled' : ''}>${videoLabel}</button>
            </div>
            <p class="dialogue-audio-source-hint">${escapeHtml(hint)}</p>
        </section>`;
}

function renderDialogueEmoSummary(d) {
    const summary = formatEmoVecSummary(d.emoVec);
    const has = summary !== '未设置';
    // 数字放 tooltip，按钮上只用彩色小条展示各维度强弱，避免截断
    const bars = has ? getEmoVecActiveDims(d.emoVec).map(({ index, value }) => {
        const h = Math.max(3, Math.round((value / EMO_VEC_MAX_EACH) * 12));
        return `<span class="emo-bar" style="height:${h}px;background:${EMO_VEC_COLORS[index]}"></span>`;
    }).join('') : '';
    return `
        <button type="button" class="tool-button dialogue-emo-btn ${has ? 'has-emo' : ''}"
            data-action="edit-dialogue-emo-vec" data-dialogue-id="${d.id}"
            title="${has ? `配音情感向量：${escapeHtml(summary)}（点击编辑）` : '查看/编辑配音情感向量'}">
            ${icon('music', 14)} 情感${has ? `<span class="emo-bars" aria-hidden="true">${bars}</span>` : ''}
        </button>`;
}

// 配音音频区：生成中显示不确定进度条；设置变更后标记旧配音；失败给出重试提示。
// 需在 renderDialoguePanel 与 renderDialogueRowOuter 两处行模板中保持一致使用。
function renderDialogueAudioBlock(d) {
    const running = isAudioRunningStatus(d.audioStatus);
    const failed = !running && isAudioFailedStatus(d.audioStatus);
    const stale = !running && !failed && Boolean(d.audioStale && d.audioUrl);
    const audioHtml = d.audioUrl
        ? `<audio src="${escapeHtml(d.audioUrl)}" controls class="dialogue-audio ${running || stale ? 'is-stale' : ''}"></audio>`
        : '';
    let statusHtml = '';
    if (running) {
        statusHtml = `
            <div class="dialogue-audio-progress">
                <span class="dialogue-audio-progress-label">${d.audioUrl ? '正在生成新配音…（下方播放的仍是旧配音）' : '配音生成中…'}</span>
                <span class="dialogue-audio-progress-track"><span class="dialogue-audio-progress-thumb"></span></span>
            </div>`;
    } else if (failed) {
        statusHtml = `<div class="dialogue-audio-note failed">配音生成失败${d.audioError ? `：${escapeHtml(d.audioError)}` : ''}，请点击「生成配音」重试</div>`;
    } else if (stale) {
        statusHtml = `<div class="dialogue-audio-note stale">台词/情感已修改，当前播放的是旧配音；点击「生成配音」更新</div>`;
    }
    return `${statusHtml}${audioHtml}`;
}

// 生成配音按钮：任务进行中禁用并显示「生成中…」，由轮询更新行后恢复。
function renderGenerateVoiceoverBtn(d) {
    const running = isAudioRunningStatus(d.audioStatus);
    return `<button class="tool-button" data-action="generate-voiceover" data-dialogue-id="${d.id}" ${running ? 'disabled' : ''}>${icon('mic', 14)} ${running ? '生成中…' : '生成配音'}</button>`;
}

function renderDialoguePanel(scene) {
    const rows = (scene.dialogues || []).map(d => {
        const characterOptions = '<option value="">旁白</option>' + state.characters.map(c =>
            `<option value="${c.id}" ${d.characterId === c.id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
        ).join('');
        return `
            <div class="dialogue-row" data-dialogue-row data-dialogue-id="${d.id}">
                <select class="dialogue-character" data-dialogue-field="characterId">${characterOptions}</select>
                <textarea class="dialogue-text" data-dialogue-field="text" placeholder="台词">${escapeHtml(d.text)}</textarea>
                <div class="dialogue-meta">
                    <label class="meta-field">语速<input type="number" step="0.1" data-dialogue-field="speed" value="${d.speed ?? 1.0}"></label>
                    <label class="meta-field">音量<input type="number" data-dialogue-field="volume" value="${d.volume ?? 100}"></label>
                </div>
                ${renderDialogueAudioBlock(d)}
                <div class="dialogue-actions">
                    ${renderDialogueEmoSummary(d)}
                    ${renderGenerateVoiceoverBtn(d)}
                    <button class="tool-button" data-action="save-dialogue" data-dialogue-id="${d.id}">${icon('success', 14)} 保存</button>
                    <button class="tool-button" data-action="delete-dialogue" data-dialogue-id="${d.id}">${icon('delete', 14)}</button>
                </div>
            </div>`;
    }).join('');

    return `
        <div class="tab-panel dialogue-panel">
            ${renderDialogueAudioSource(scene)}
            ${rows || '<div class="empty-note">还没有对话，点击下方添加。</div>'}
            <button class="panel-button" data-action="add-dialogue">${icon('add', 16)} 添加对话</button>
        </div>`;
}

function renderTabs(scene) {
    if (!scene) {
        // 拆分进行中但进度弹窗被关掉时：给出恢复入口，避免空板死锁
        const splitBusy = Boolean(
            state.generateFromScriptTaskId
            || state.isGeneratingFromScript
        );
        if (splitBusy && !state.showGenerateProgressDialog) {
            return `
                <div class="empty-note storyboard-split-recover">
                    <p>剧本拆分进行中，分镜尚未生成。</p>
                    <button type="button" class="btn-primary" data-action="reopen-generate-progress">查看拆分进度</button>
                </div>`;
        }
        const startSplit = canShowStartSplitEntry()
            ? `<button type="button" class="btn-primary" data-action="open-generate-from-script">开始拆分</button>`
            : '';
        return `
            <div class="empty-note storyboard-start-split">
                <p>暂无分镜。可以从底部添加一个新分镜，或根据本集剧本自动拆分。</p>
                ${startSplit}
            </div>`;
    }
    if (state.activeTab === 'dialogue') {
        return renderDialoguePanel(scene);
    }
    return renderScenePanel(scene);
}

function renderLeftSidebar(scene) {
    // 音乐 Tab 已移除（音乐属时间轴功能，本期后置）
    const tabs = [
        ['scene', 'image', '画面'],
        ['dialogue', 'mic', '对话'],
    ].map(([key, iconName, label]) => `
        <button class="tab-btn ${state.activeTab === key ? 'active' : ''}" data-tab="${key}">
            ${icon(iconName, 16)} ${label}
        </button>`).join('');

    // 幕号：来自剧本解析的 group_id（如 grp_001 → 幕01）；手动新增的分镜无 group_id 时不显示
    const actTag = (() => {
        if (!scene || !scene.groupId) return '';
        const numStr = String(scene.groupId).replace(/^grp_?0*/i, '');
        const num = parseInt(numStr, 10);
        if (!Number.isFinite(num) || num <= 0) return '';
        return `<span class="act-tag">幕${String(num).padStart(2, '0')}</span>`;
    })();

    return `
        <aside class="left-sidebar">
            <div class="sidebar-content">
                <div class="project-info">
                    <div class="project-brand">
                        ${actTag}
                        <div class="brand-icon">${scene ? escapeHtml(scene.title) : '分镜'}</div>
                        <span>分镜工作台</span>
                    </div>
                </div>
                <div class="tab-nav">${tabs}</div>
                ${renderTabs(scene)}
                <!-- 画风/构图设置已移至 header 顶部显示（全局共享），编辑通过点击 header 信息或后续 modal 实现 -->
            </div>
            ${renderAiPanel()}
        </aside>`;
}

/**
 * 媒体槽角标文案：
 * - 首尾帧模式：首帧 / 尾帧
 * - 全能参考：图1 / 图2 / …（对齐 marketing_agent 的编号展示）
 */
function videoRoleLabel(role, mode, index = 0) {
    if (mode === 'multi_reference') {
        return `图${index + 1}`;
    }
    if (role === 'first_frame') return '首帧';
    if (role === 'last_frame') return '尾帧';
    return `图${index + 1}`;
}

function renderVideoModeSelector(disabled) {
    const modes = getSupportedVideoImageModes();
    const mode = modes.includes(state.videoImageMode) ? state.videoImageMode : (modes[0] || 'first_last_frame');
    const modeLabel = mode === 'multi_reference' ? '全能参考' : '首尾帧';
    const panelOpen = state.showVideoModePanel && !disabled;
    const options = [
        {
            value: 'first_last_frame',
            title: '首尾帧模式',
            desc: '第1张为首帧，第2张可选为尾帧',
            emoji: '🎬',
        },
        {
            value: 'multi_reference',
            title: '全能参考',
            desc: '多张图片作为综合参考驱动',
            emoji: '🖼',
        },
    ].filter(opt => modes.includes(opt.value));

    const panel = panelOpen ? `
        <div class="video-mode-panel" data-video-mode-panel>
            ${options.map(opt => `
                <button type="button" class="video-mode-option ${mode === opt.value ? 'active' : ''}"
                        data-action="set-video-image-mode" data-video-image-mode="${opt.value}" ${disabled ? 'disabled' : ''}>
                    <span class="video-mode-emoji">${opt.emoji}</span>
                    <span class="video-mode-texts">
                        <strong>${opt.title}</strong>
                        <small>${opt.desc}</small>
                    </span>
                    ${mode === opt.value ? '<span class="video-mode-check">✓</span>' : ''}
                </button>
            `).join('')}
        </div>` : '';

    if (options.length <= 1) {
        return `
            <div class="video-mode-dropdown is-static" title="${escapeHtml(options[0]?.desc || '')}">
                <span class="video-mode-static-label">${escapeHtml(modeLabel)}</span>
            </div>`;
    }

    return `
        <div class="video-mode-dropdown">
            <button type="button" class="tool-button video-mode-btn" data-action="toggle-video-mode-panel"
                    ${disabled ? 'disabled' : ''} title="视频图片模式">
                ${icon('video', 14)}
                <span>${escapeHtml(modeLabel)}</span>
            </button>
            ${panel}
        </div>`;
}

function mediaPlusSvg(size = 18) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;
}

function mediaStackRoleText(img, mode, index = 0) {
    return videoRoleLabel(img.role, mode, index);
}

function renderMediaStack(disabled) {
    if (state.chatMode !== 'video') return '';

    const scene = getCurrentScene();
    const mode = state.videoImageMode;
    const items = state.videoMediaItems || [];
    const canAdd = canAddVideoMedia();
    const addTitle = mode === 'first_last_frame'
        ? (videoModelSupportsLastFrame() ? '上传首帧/尾帧' : '上传首帧')
        : '上传参考图';
    const canRestore = scene
        && isRenderableMediaUrl(scene.firstFrameUrl)
        && !items.some(item => item.role === 'first_frame');
    const restoreLabel = mode === 'multi_reference' ? '使用当前分镜图' : '使用当前首帧';
    const restoreTitle = mode === 'multi_reference'
        ? '将当前分镜图重新带入参考槽'
        : '将当前分镜首帧重新带入首帧位';

    const addBtn = (extraClass = '') => canAdd
        ? `<button type="button" class="media-stack-add ${extraClass}" data-action="add-reference-image"
                ${disabled ? 'disabled' : ''} title="${escapeHtml(addTitle)}">${mediaPlusSvg(extraClass.includes('is-fab') ? 14 : 18)}</button>`
        : '';

    const restoreBtn = canRestore
        ? `<button type="button" class="media-stack-restore" data-action="restore-scene-first-frame" ${disabled ? 'disabled' : ''}
                title="${escapeHtml(restoreTitle)}">${escapeHtml(restoreLabel)}</button>`
        : '';

    if (!items.length) {
        return `
            <div class="media-stack is-empty">
                <div class="media-stack-stage">
                    ${addBtn() || `<div class="media-stack-add" style="opacity:.4;pointer-events:none" title="当前模式无法添加图片">${mediaPlusSvg()}</div>`}
                </div>
                ${restoreBtn}
                <input type="file" id="reference-file-input" class="reference-file-input" accept="image/*" multiple>
            </div>`;
    }

    const count = items.length;
    const isMulti = count > 1;
    const expanded = Boolean(state.mediaStackExpanded);
    // 叠放视觉最多 3 层；展开/hover 时 DOM 内已有全部卡片（hover 用 CSS，点击用 is-expanded）
    const stackClass = [
        'media-stack',
        isMulti ? 'is-stacked' : 'is-single',
        expanded ? 'is-expanded' : '',
    ].filter(Boolean).join(' ');

    const cards = items.map((img, index) => {
        const isTop = index === items.length - 1;
        // 非展开叠放时只露最后 3 张，更早的卡片隐藏以免层数过多
        const hideInStack = isMulti && !expanded && index < items.length - 3;
        const src = img.uploading
            ? ''
            : escapeHtml(getThumbnailUrl(img.thumbnailUrl || img.url || '', 96));
        const roleText = mediaStackRoleText(img, mode, index);
        const name = escapeHtml(roleText || img.name || '');
        return `
            <div class="media-stack-card ${img.uploading ? 'uploading' : ''} ${isTop ? 'is-top' : ''} ${hideInStack ? 'is-stack-hidden' : ''}"
                 data-video-media-id="${escapeHtml(String(img.id))}" title="${name}">
                ${src ? `<img src="${src}" alt="${name}">` : '<div class="media-stack-placeholder"></div>'}
                ${img.uploading ? `<div class="reference-spinner">${icon('loading', 14)}</div>` : ''}
                <span class="media-stack-role">${escapeHtml(roleText)}</span>
                <button type="button" class="media-stack-remove" data-action="remove-video-media"
                    data-video-media-id="${escapeHtml(String(img.id))}" ${disabled ? 'disabled' : ''} title="移除">×</button>
            </div>`;
    }).join('');

    const countBadge = isMulti
        ? `<span class="media-stack-count">${count}</span>`
        : '';

    // 右侧虚线 +：仅 hover / focus / expanded 时显示
    // 注意：toggle 只挂在 thumbs 上，不要挂在整个 stack，否则点 + 会被父级 data-action 抢走并 preventDefault
    const maxCount = getMaxVideoMediaCount();
    const addControl = canAdd ? addBtn('is-hover-add') : '';

    return `
        <div class="${stackClass}">
            <div class="media-stack-stage">
                <div class="media-stack-thumbs" data-action="toggle-media-stack"
                     title="${canAdd ? '添加图片 / 查看全部' : `图片 ${count}/${maxCount}`}">
                    ${cards}
                    ${countBadge}
                </div>
                ${addControl}
            </div>
            ${restoreBtn}
            <input type="file" id="reference-file-input" class="reference-file-input" accept="image/*" multiple>
        </div>`;
}

function renderAiPanel() {
    const modes = [
        ['dialogue', '对话改图', '选择对话模型后，可让智能体基于当前画面提示词生成或调整首帧'],
        ['video', '视频生成', '基于当前分镜首帧直接生成视频（不走智能体）'],
        ['aivideo', 'AI生视频', '由智能体基于当前分镜生成视频（商业版）'],
    ].map(([key, label, title]) => `<option value="${key}" ${state.chatMode === key ? 'selected' : ''} title="${title}">${label}</option>`).join('');

    const agentMessages = renderAgentMessages();
    const currentScene = getCurrentScene();
    const sceneAgentRunning = isSceneAgentRunning(currentScene?.id);
    const disabled = sceneAgentRunning ? 'disabled' : '';
    // 两个视频模式（video 直连 / aivideo 智能体）共享视频槽、视频模式选择器
    const isVideoMode = state.chatMode === 'video' || state.chatMode === 'aivideo';
    // 社区版下 AI生视频（智能体）不可用：文本框禁用并提示商业版特权
    const isCommunity = String(state.editionInfo?.mode || '').toLowerCase() === 'community';
    const isAiVideoLocked = state.chatMode === 'aivideo' && isCommunity;
    const placeholder = isAiVideoLocked
        ? 'AI生视频为商业版特权，请切换到「视频生成」模式'
        : (state.chatMode === 'dialogue'
            ? '和智能体描述要如何调整当前分镜画面'
            : (state.chatMode === 'video'
                ? '描述视频的运动方式、镜头变化与角色动作（预填当前分镜视频提示词，可直接编辑）'
                : '和智能体描述要如何生成当前分镜视频'));

    const isVideo = isVideoMode;
    const isDhScene = isDigitalHumanScene(currentScene);
    // 对口型 + 直连「视频生成」：提示词/模型由服务端规划（默认动作句、固定 MiniMax H3），不渲染提示词文本框
    const isDhDirectVideo = state.chatMode === 'video' && isDhScene;
    // 对口型不展示图生视频的首尾帧/参考图模式切换，固定 MiniMax H3 链路
    const videoModeSelector = isVideo && !isDhScene && !isAiVideoLocked ? renderVideoModeSelector(disabled) : '';
    const dhAudioHint = isVideo && !isAiVideoLocked && isDhScene ? digitalHumanAudioHint(currentScene) : null;
    const dhHint = dhAudioHint
        ? `<div class="ai-dh-hint ${dhAudioHint.cssClass}" title="${escapeHtml(dhAudioHint.title)}">对口型 · MiniMax H3 · ${escapeHtml(dhAudioHint.label)}</div>`
        : '';
    const historyOpen = state.agentChatHistoryOpen !== false;
    const msgCount = (state.agentMessages || []).length;
    // 常态历史收起时提示条数；hover 可展开
    const historyMeta = msgCount
        ? `<span class="ai-chat-header-meta">${msgCount} 条消息</span>`
        : '';
    const mediaStack = isVideo && !isDhScene && !isAiVideoLocked
        ? renderMediaStack(disabled)
        : `<input type="file" id="reference-file-input" class="reference-file-input" accept="image/*" multiple hidden>`;
    const fontSizes = getAgentChatFontSizes();
    const fontDownDisabled = fontSizes.step <= AGENT_CHAT_FONT_STEP_MIN ? 'disabled' : '';
    const fontUpDisabled = fontSizes.step >= AGENT_CHAT_FONT_STEP_MAX ? 'disabled' : '';
    const fontControls = `
        <div class="ai-chat-font-controls" title="调节助手区正文字号">
            <button type="button" class="ai-chat-font-btn" data-action="agent-chat-font-down"
                ${fontDownDisabled} title="缩小字体 (A−)" aria-label="缩小字体">A−</button>
            <button type="button" class="ai-chat-font-btn" data-action="agent-chat-font-up"
                ${fontUpDisabled} title="放大字体 (A+)" aria-label="放大字体">A+</button>
        </div>`;
    // 固定展开：点击「展开」后 pin，避免 rerender 丢失 hover；鼠标离开后由 events 清 pin
    const logPinned = Boolean(state.agentChatLogPinned) || sceneAgentRunning;
    const sectionClass = [
        'ai-chat-section',
        historyOpen ? '' : 'is-history-collapsed',
        sceneAgentRunning ? 'is-agent-running' : '',
        logPinned ? 'is-chat-log-pinned' : '',
    ].filter(Boolean).join(' ');
    // AI生视频锁定时，文本框与发送按钮均禁用
    const effectiveDisabled = disabled || (isAiVideoLocked ? 'disabled' : '');
    const sendDisabled = disabled || (isAiVideoLocked ? 'disabled' : '');

    return `
        <section class="${sectionClass}" style="--agent-chat-font-size:${fontSizes.bodyPx}px;--agent-chat-label-size:${fontSizes.labelPx}px;">
            <div class="ai-chat-dock">
                ${agentMessages}
                <div class="ai-chat-header">
                    <button type="button" class="ai-chat-header-toggle" data-action="toggle-agent-chat-history"
                        title="${historyOpen ? '折叠对话历史（收起后悬停也不展开）' : '展开对话历史'}">
                        <span class="ai-chat-header-chevron">${icon('chevronDown', 14)}</span>
                        ${icon('send', 16)} 分镜助手
                    </button>
                    ${fontControls}
                    ${historyMeta}
                </div>
                <div class="chat-composer">
                    ${dhHint}
                    <div class="chat-textarea-row">
                        ${mediaStack}
                        ${isDhDirectVideo ? '' : `<textarea id="chat-textarea" class="chat-textarea" placeholder="${isDhScene && isVideo && !isAiVideoLocked ? '描述对口型表演/镜头（台词以配音为准，需先生成配音）' : placeholder}" ${effectiveDisabled}>${escapeHtml(state.inputMessage)}</textarea>`}
                    </div>
                    <div class="chat-toolbar">
                        <button class="tool-button" data-action="open-model-config" title="模型配置（对话模型按供应商分组，图片/视频模型按当前助手模式）">${icon('settings', 14)}</button>
                        <select id="chat-mode-select" class="chat-mode-select">${modes}</select>
                        ${videoModeSelector}
                        <button class="tool-button" data-action="mention">@</button>
                        <button class="chat-send-btn" data-action="send-ai" title="${isDhDirectVideo ? '生成数字人对口型视频（台词/口型以配音为准）' : '发送'}" ${sendDisabled}>${icon('send', 16)}</button>
                    </div>
                </div>
            </div>
        </section>`;
}

function agentMessageKey(message, index) {
    return String(message.id || message.message_id || `${message.role || 'msg'}-${index}-${(message.content || message.status || '').slice(0, 24)}`);
}

function renderAgentMessages() {
    if (!state.agentMessages.length) {
        return '';
    }
    const expandedMap = state.expandedAgentMessageIds || {};
    const rows = state.agentMessages.slice(-8).map((message, index) => {
        const role = message.role || 'assistant';
        const label = role === 'user' ? '你' : (role === 'status' ? '状态' : '智能体');
        const full = String(message.content || message.status || '');
        const key = agentMessageKey(message, index);
        const limit = role === 'status' ? 160 : 280;
        const isExpanded = Boolean(expandedMap[key]);
        const needsTruncate = full.length > limit;
        const shown = needsTruncate && !isExpanded ? `${full.slice(0, limit)}…` : full;
        const expandBtn = needsTruncate
            ? `<button type="button" class="agent-chat-expand" data-action="toggle-agent-message-expand" data-message-key="${escapeHtml(key)}">${isExpanded ? '收起' : '展开'}</button>`
            : '';
        return `
            <div class="agent-chat-message ${escapeHtml(role)}" data-message-key="${escapeHtml(key)}">
                <span>${label}</span>
                <p>${escapeHtml(shown)}</p>
                ${expandBtn}
            </div>`;
    }).join('');
    const running = isSceneAgentRunning(state.currentSceneId)
        ? '<div class="agent-chat-running">正在处理当前分镜...</div>'
        : '';
    return `<div class="agent-chat-log">${rows}${running}</div>`;
}

function renderCenter(scene) {
    if (state.viewMode === 'grid') return renderStoryboardGrid();
    const ratio = state.workflowRatio || '16:9';
    const previewRes = normalizePreviewResolution(state.previewResolution);
    const canvas = resolveLogicalCanvas(ratio, previewRes);
    return `
        <main class="center-panel">
            <section class="preview-wrapper"
                data-ratio="${escapeHtml(ratio)}"
                data-preview-resolution="${escapeHtml(previewRes)}"
                style="--logical-w:${canvas.width};--logical-h:${canvas.height};--preview-ar:${canvas.width} / ${canvas.height};">
                <div class="preview-stage">
                    ${mediaFrame(scene)}
                    ${previewSubtitleHtml()}
                </div>
                <div class="preview-caption">
                    <strong>${escapeHtml(scene ? scene.title : '未选择分镜')}</strong>
                    <span>${scene ? scene.durationLabel : '00:00'}</span>
                </div>
            </section>
            ${renderTimeline()}
        </main>`;
}

function renderInsertSceneSlot(prevScene, nextScene, mode) {
    if (!prevScene || !nextScene) return '';
    const prevId = prevScene.id;
    const nextId = nextScene.id;
    const className = mode === 'grid' ? 'grid-insert-slot' : 'scene-timeline-insert-slot';
    const label = '在此处添加分镜';
    return `
        <button
            class="${className}"
            data-action="insert-scene"
            data-prev-id="${prevId}"
            data-next-id="${nextId}"
            title="${label}"
            aria-label="${label}"
        >${icon('add', 16)}</button>`;
}

export function renderStoryboardGrid() {
    return `
        <main class="center-panel">
            ${renderAutoCompleteHeader('故事板总览', renderGridHeaderActions())}
            <div class="storyboard-grid" data-scenes-sig="${escapeHtml(scenesStructureSig())}">${renderGridInner()}</div>
        </main>`;
}

function renderGridHeaderActions() {
    const batchButton = isBatchSelectionActive()
        ? ''
        : `<button class="btn-ghost" data-action="enter-batch-selection">${icon('success', 16)} 批量操作</button>`;
    const timelineDisabled = state.batchSelection?.submittingAction ? 'disabled' : '';
    return `${batchButton}<button class="btn-ghost" data-action="toggle-view" ${timelineDisabled}>${icon('list', 16)} 时间轴</button>`;
}

/** 时间轴 list 内部 HTML（playhead + 分镜条 + 添加），供结构 patch 复用 */
function renderTimelineListInner() {
    const scenes = state.scenes.map((scene, index) => {
        const nextScene = state.scenes[index + 1];
        return `
            <div class="scene-timeline-item" data-scene-item="${scene.id}">
                <button class="scene-timeline-thumb ${state.currentSceneId === scene.id ? 'active' : ''}" data-scene="${scene.id}">
                    ${renderTimelineThumbInner(scene)}
                </button>
                <div class="scene-timeline-actions">
                    <button data-action="duplicate-scene" data-id="${scene.id}" title="复制"${state.duplicatingSceneId === scene.id ? ' disabled' : ''}>${icon('copy', 14)}</button>
                    <button data-action="delete-scene" data-id="${scene.id}" title="删除">${icon('delete', 14)}</button>
                </div>
            </div>
            ${nextScene ? renderInsertSceneSlot(scene, nextScene, 'timeline') : ''}`;
    }).join('');
    return `
        <div class="scene-timeline-playhead" aria-hidden="true" title="播放位置" ${state.scenes.length ? '' : 'hidden'}></div>
        ${scenes}<button class="add-scene-btn" data-action="add-scene">${icon('add', 22)}</button>`;
}

/** Grid 内容区 HTML（卡片 + 添加） */
function renderGridInner() {
    const cards = state.scenes.map((scene, index) => {
        const nextScene = state.scenes[index + 1];
        return renderStoryboardCardCell(scene, nextScene);
    }).join('');
    const addButton = isBatchSelectionActive()
        ? ''
        : `<button class="add-board-card" data-action="add-scene">${icon('add', 24)} 添加分镜</button>`;
    return `${cards}${addButton}`;
}

function scenesStructureSig() {
    return (state.scenes || []).map(s => s.id).join(',');
}

export function renderTimeline() {
    return `
        <section class="timeline-controls">
            <div class="timeline-progress-row">
                <button class="play-btn" data-action="toggle-play" aria-label="${state.isPlaying ? '暂停' : '播放'}">${icon(state.isPlaying ? 'pause' : 'play', 18)}</button>
                <span class="timeline-time">${formatDuration(state.currentTime)} / ${formatDuration(getTotalDuration())}</span>
                <label class="subtitle-toggle"><input type="checkbox" data-action="toggle-subtitle" ${state.subtitleEnabled ? 'checked' : ''}> 字幕</label>
                <button class="timeline-view-toggle" data-action="toggle-view">${icon('grid', 16)}</button>
            </div>
            <div class="scene-timeline">
                ${renderAutoCompleteHeader('分镜序列')}
                <div class="scene-timeline-list" data-ratio="${escapeHtml(state.workflowRatio || '16:9')}" data-scenes-sig="${escapeHtml(scenesStructureSig())}">
                    ${renderTimelineListInner()}
                </div>
            </div>
        </section>`;
}

/** 单条可渲染媒体 URL（排除逗号拼接的多参考图输入） */
function isRenderableCandidateUrl(url) {
    if (url == null) return false;
    const value = String(url).trim();
    if (!value) return false;
    if (value.includes(',')) return false;
    return true;
}

function isCandidateTaskFailed(status) {
    return status === -1 || status === 'failed';
}

function isCandidateTaskRunning(status) {
    // ai_tools: 0=PENDING, 1=PROCESSING；也兼容字符串态
    return status === 0 || status === 1
        || status === 'pending' || status === 'running'
        || status === 'queued' || status === 'processing';
}

function renderCandidatePlaceholder(status, kind = 'image') {
    if (isCandidateTaskFailed(status)) {
        return `<div class="candidate-placeholder candidate-failed">
            ${icon('error', 16)}
            <span>生成失败</span>
        </div>`;
    }
    // 无合法 URL：生成中 / 排队中 / 绑定后等待首轮轮询
    const label = kind === 'video' ? '视频生成中' : '生成中';
    return `<div class="candidate-placeholder candidate-loading">
        ${icon('loading', 18)}
        <span>${label}</span>
    </div>`;
}

function getCandidateVideoThumbnailUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    // 媒体时间片段只影响浏览器预览，不会发送到服务端；取 0.1 秒可避开部分视频的空首帧。
    return `${value.split('#')[0]}#t=0.1`;
}

function renderCandidateMedia(item, kind = 'image') {
    const url = isRenderableCandidateUrl(item?.url) ? String(item.url).trim() : '';
    if (url) {
        if (kind === 'video') {
            // 仅展示缩略帧 + 播放标识，不内嵌可操作播放器（避免候选区看不清、误操作）
            // poster 只能使用该视频自身的封面，绝不能回退到分镜首帧，否则会展示成另一张图。
            const poster = isRenderableCandidateUrl(item?.posterUrl)
                ? String(item.posterUrl).trim()
                : '';
            const posterAttr = poster ? ` poster="${escapeHtml(poster)}"` : '';
            const thumbnailUrl = getCandidateVideoThumbnailUrl(url);
            return `
                <div class="candidate-video-thumb">
                    <video src="${escapeHtml(thumbnailUrl)}"${posterAttr} muted playsinline preload="metadata" tabindex="-1" aria-hidden="true"></video>
                    <button type="button" class="candidate-video-badge" data-candidate-play aria-label="播放此候选视频">${icon('play', 14)}</button>
                </div>`;
        }
        return `<img src="${escapeHtml(url)}" alt="${escapeHtml(item.label || '分镜图')}">`;
    }
    return renderCandidatePlaceholder(item?.status, kind);
}

function renderCandidateUploadControl(scene, assetType) {
    const isVideo = assetType === 'video';
    const uploadState = state.candidateUploadsBySceneId?.[scene?.id]?.[assetType];
    const uploading = Boolean(uploadState?.uploading);
    const label = isVideo ? '上传视频' : '上传分镜图';
    const accept = isVideo ? 'video/mp4,video/webm,.mp4,.webm' : 'image/jpeg,image/png,image/gif,image/webp';
    return `
        <button type="button" class="candidate-upload-button${uploading ? ' is-uploading' : ''}"
                data-action="upload-scene-candidate" data-candidate-upload-type="${assetType}"
                ${uploading ? 'disabled aria-busy="true"' : ''}>
            ${icon(uploading ? 'loading' : 'add', 14)}
            <span>${uploading ? '上传中' : label}</span>
        </button>
        <input type="file" class="candidate-upload-input" data-candidate-upload-input="${assetType}"
               data-scene-id="${escapeHtml(scene?.id)}" accept="${accept}">
    `;
}

function renderCandidateDeleteButton(scene, item, assetType) {
    const assetId = Number(item?.id);
    if (!Number.isFinite(assetId) || assetId <= 0) return '';
    const deleting = Boolean(state.candidateDeletesBySceneId?.[scene?.id]?.[assetId]);
    const mediaLabel = assetType === 'video' ? '视频候选' : '分镜图候选';
    return `
        <button type="button" class="candidate-delete-button${deleting ? ' is-deleting' : ''}"
                data-action="delete-scene-candidate" data-candidate-delete-id="${assetId}"
                data-candidate-delete-type="${assetType}" title="删除${mediaLabel}"
                aria-label="删除${mediaLabel}" ${deleting ? 'disabled aria-busy="true"' : ''}>
            ${icon(deleting ? 'loading' : 'delete', 13)}
        </button>`;
}

export function renderRightSidebar(scene) {
    const candidates = state.sceneCandidates?.[scene?.id] || {};
    const imageCandidates = candidates.images || [];
    const videoCandidates = candidates.videos || [];

    // 回退：若尚未加载候选列表，用当前选中的 URL 展示
    const fallbackImages = [];
    if (isRenderableCandidateUrl(scene?.firstFrameUrl)) {
        fallbackImages.push({ id: 'ff', url: scene.firstFrameUrl, status: null });
    }
    if (isRenderableCandidateUrl(scene?.lastFrameUrl)) {
        fallbackImages.push({ id: 'lf', url: scene.lastFrameUrl, status: null });
    }
    // 有候选列表时用列表；若列表为空但任务在跑，用空候选 + loading 不回退到坏 URL
    const displayImages = imageCandidates.length ? imageCandidates : fallbackImages;

    const fallbackVideos = [];
    if (isRenderableCandidateUrl(scene?.videoUrl)) {
        fallbackVideos.push({ id: 'vd', url: scene.videoUrl, status: null });
    }
    const displayVideos = videoCandidates.length ? videoCandidates : fallbackVideos;

    // 无候选资产时，若当前分镜首帧任务仍在跑，显示一个 loading 占位
    const imageRunning = isCandidateTaskRunning(scene?.taskStatus?.first_frame);
    const videoRunning = isCandidateTaskRunning(scene?.taskStatus?.video);

    const imageGrid = displayImages.length
        ? `<div class="candidate-grid">${displayImages.map(img => `
            <div class="candidate-thumb ${img.selected ? 'selected' : ''}${!isRenderableCandidateUrl(img.url) ? ' is-loading' : ''}${state.candidateDeletesBySceneId?.[scene?.id]?.[img.id] ? ' is-deleting' : ''}" data-candidate-id="${img.id}" data-candidate-type="image">
                ${renderCandidateMedia(img, 'image')}
                ${renderCandidateDeleteButton(scene, img, 'first_frame')}
                ${img.label ? `<span class="candidate-label">${escapeHtml(img.label)}</span>` : ''}
            </div>`).join('')}</div>`
        : (imageRunning
            ? `<div class="candidate-grid"><div class="candidate-thumb is-loading">${renderCandidatePlaceholder(scene?.taskStatus?.first_frame, 'image')}</div></div>`
            : '<div class="candidate-empty">暂无分镜图候选</div>');

    const videoGrid = displayVideos.length
        ? `<div class="candidate-grid candidate-video-grid">${displayVideos.map(vid => `
            <div class="candidate-thumb candidate-video-thumb-wrap ${vid.selected ? 'selected' : ''}${!isRenderableCandidateUrl(vid.url) ? ' is-loading' : ''}${state.candidateDeletesBySceneId?.[scene?.id]?.[vid.id] ? ' is-deleting' : ''}"
                 data-candidate-id="${vid.id}" data-candidate-type="video" title="点击选中该视频">
                ${renderCandidateMedia(vid, 'video')}
                ${renderCandidateDeleteButton(scene, vid, 'video')}
                ${vid.label ? `<span class="candidate-label">${escapeHtml(vid.label)}</span>` : ''}
            </div>`).join('')}</div>`
        : (videoRunning
            ? `<div class="candidate-grid candidate-video-grid"><div class="candidate-thumb is-loading">${renderCandidatePlaceholder(scene?.taskStatus?.video, 'video')}</div></div>`
            : '<div class="candidate-empty">暂无视频候选</div>');

    return `
        <aside class="right-sidebar">
            <div class="candidate-section">
                <span class="section-title">分镜图候选</span>
                ${imageGrid}
                ${renderCandidateUploadControl(scene, 'first_frame')}
            </div>
            <div class="candidate-section">
                <span class="section-title">视频候选</span>
                ${videoGrid}
                ${renderCandidateUploadControl(scene, 'video')}
            </div>
        </aside>`;
}

function renderPowerLogsDialog() {
    if (!state.showPowerLogsModal) return '';
    return `
        <div class="modal-overlay power-logs-overlay" data-modal="power-logs">
            <div class="power-logs-dialog" role="dialog" aria-label="算力日志">
                <header class="power-modal-header">
                    <h2 class="power-modal-title">⚡ 算力日志</h2>
                    <div class="power-modal-actions">
                        <button type="button" class="btn-primary power-recharge-btn" data-action="open-recharge">算力充值</button>
                        <button type="button" class="power-modal-close" data-action="close-power-logs" title="关闭">${icon('close', 18)}</button>
                    </div>
                </header>
                <div class="power-logs-body">
                    <iframe class="power-logs-iframe" src="/computing_power_logs.html" title="算力日志"></iframe>
                </div>
            </div>
        </div>`;
}

function renderRechargeDialog() {
    if (!state.showRechargeModal) return '';
    const status = state.rechargeState || 'loading';
    let body = '';

    if (status === 'loading') {
        body = `
            <div class="recharge-center">
                <div class="loading-spinner"></div>
                <p class="recharge-hint">加载套餐中...</p>
            </div>`;
    } else if (status === 'packages') {
        const packages = state.rechargePackages || [];
        if (packages.length === 0) {
            body = `<div class="recharge-center"><p class="recharge-hint">暂无可用套餐</p></div>`;
        } else {
            body = `<div class="package-list">${packages.map((pkg) => {
                // 优先展示扣邀请佣金后的实际到账算力（与 index.html / 后端 settle 口径一致）
                const power = Number(pkg.granted_computing_power ?? pkg.computing_power) || 0;
                const price = Number(pkg.price) || 0;
                const unit = power > 0 ? (price / power * 100).toFixed(2) : '--';
                return `
                    <button type="button" class="package-item"
                        data-action="select-recharge-package"
                        data-package-id="${escapeHtml(String(pkg.package_id))}"
                        data-package-desc="${escapeHtml(pkg.description || '')}"
                        data-package-power="${escapeHtml(String(power))}"
                        data-package-price="${escapeHtml(String(price))}">
                        <div class="package-item-main">
                            <div class="package-item-desc">${escapeHtml(pkg.description || '算力套餐')}</div>
                            <div class="package-item-power">${power} 算力</div>
                        </div>
                        <div class="package-item-price-wrap">
                            <div class="package-item-price">¥${price}</div>
                            <div class="package-item-unit">${unit}元/百算力</div>
                        </div>
                    </button>`;
            }).join('')}</div>`;
        }
    } else if (status === 'qrcode') {
        const pkg = state.selectedRechargePackage || {};
        const qr = state.rechargeQrCodeUrl || '';
        const grantedPower = Number(pkg.granted_computing_power ?? pkg.computing_power) || 0;
        body = `
            <div class="recharge-center">
                <div class="recharge-pkg-title">${escapeHtml(pkg.description || '算力套餐')}</div>
                <div class="recharge-hint">${grantedPower} 算力 - ¥${Number(pkg.price) || 0}</div>
                <div class="recharge-qr-wrap">
                    ${qr
                        ? `<div class="recharge-qr-box"><img src="${escapeHtml(qr)}" alt="微信支付二维码" width="200" height="200" /></div>`
                        : `<div class="loading-spinner"></div><p class="recharge-hint">正在生成支付二维码...</p>`}
                </div>
                ${qr ? `
                    <div class="recharge-pay-tip">
                        请打开微信「扫一扫」完成支付<br/>
                        如果已支付，请稍等片刻系统会自动到账
                    </div>` : ''}
                <button type="button" class="btn-ghost" data-action="back-to-recharge-packages">返回选择套餐</button>
            </div>`;
    } else if (status === 'error') {
        body = `
            <div class="recharge-center">
                <p class="recharge-error">${escapeHtml(state.rechargeError || '加载失败，请重试')}</p>
                <button type="button" class="btn-ghost" data-action="retry-recharge-packages">返回选择套餐</button>
            </div>`;
    }

    return `
        <div class="modal-overlay recharge-overlay" data-modal="recharge">
            <div class="recharge-dialog" role="dialog" aria-label="算力充值">
                <header class="power-modal-header">
                    <h2 class="power-modal-title">⚡ 算力充值</h2>
                    <button type="button" class="power-modal-close" data-action="close-recharge" title="关闭">${icon('close', 18)}</button>
                </header>
                <div class="recharge-body">${body}</div>
            </div>
        </div>`;
}

function renderScriptSplitModelConfig(disabled = false) {
    const vendors = state.llmVendors || [];
    const models = state.llmModels || [];
    const vendorMap = {};
    vendors.forEach(v => {
        vendorMap[v.id || v.vendor_name] = v;
    });

    const groups = {};
    models.forEach(m => {
        const vid = m.vendor_id || m.vendor_name || 'unknown';
        if (!groups[vid]) groups[vid] = [];
        groups[vid].push(m);
    });

    const selected = state.selectedScriptSplitLlmModel || state.selectedLlmModel;
    const isSelectedScriptSplitModel = (model) => {
        if (!selected) return false;
        const val = model.model || model.name || model.id || '';
        const modelId = model.model_id || model.id || '';
        const vendorId = model.vendor_id || '';
        if (typeof selected === 'object') {
            const selectedModelId = selected.model_id || selected.id || '';
            const selectedVendorId = selected.vendor_id || selected.vendorId || '';
            if (selectedModelId || selectedVendorId) {
                return String(selectedModelId) === String(modelId)
                    && String(selectedVendorId || vendorId) === String(vendorId);
            }
            return String(selected.model || selected.name || '') === String(val);
        }
        return String(selected) === String(val);
    };

    let html = '<label class="config-label">拆分剧本模型</label><div class="config-hint">用于把剧本拆成分镜、画面提示词和对话数据</div><div class="config-select-wrapper"><select class="chat-mode-select" data-config-select="scriptSplit"';
    if (disabled) html += ' disabled';
    html += '>';
    const vendorKeys = Object.keys(groups);
    if (vendorKeys.length === 0) {
        html += '<option value="">暂无可用模型</option></select></div>';
        return html;
    }

    vendorKeys.forEach(vid => {
        const v = vendorMap[vid] || { vendor_name: vid };
        const iconStr = v.icon || '🤖';
        const vendorNameAttr = escapeHtml(v.vendor_name || vid);
        html += `<optgroup label="${iconStr} ${vendorNameAttr}">`;
        groups[vid].forEach(m => {
            const val = m.model || m.name || m.id || '';
            const label = m.name || m.model || val;
            const modelId = m.model_id || m.id || '';
            const vendorId = m.vendor_id || '';
            const supportsThinking = m.supports_thinking === true || m.supports_thinking === 1 || m.supports_thinking === 'true' ? 'true' : 'false';
            const sel = isSelectedScriptSplitModel(m) ? 'selected' : '';
            html += `<option value="${escapeHtml(val)}" data-model-id="${escapeHtml(modelId)}" data-vendor-id="${escapeHtml(vendorId)}" data-vendor-name="${vendorNameAttr}" data-supports-thinking="${supportsThinking}" ${sel}>${escapeHtml(label)}</option>`;
        });
        html += '</optgroup>';
    });
    html += '</select></div>';
    html += renderThinkingControls(state.selectedScriptSplitLlmModel || state.selectedLlmModel);
    return html;
}

function renderScriptSplitDuration(disabled = false) {
    const durations = [5, 8, 10, 15];
    const curDuration = durations.includes(Number(state.maxGroupDuration)) ? Number(state.maxGroupDuration) : 15;
    const durationOptions = durations.map(d =>
        `<option value="${d}" ${d === curDuration ? 'selected' : ''}>${d}秒</option>`
    ).join('');
    return `
        <div class="generate-from-script-model">
            <label class="config-label">镜头组时长</label>
            <div class="config-hint">每个分镜组的最大总时长，超时会在同一场景内自动拆分</div>
            <div class="config-select-wrapper">
                <select class="chat-mode-select" data-config-select="maxGroupDuration" ${disabled ? 'disabled' : ''}>${durationOptions}</select>
            </div>
        </div>`;
}

// 渲染剧本拆分的高级选项：语言 + 拆分开关（与 video_workflow 剧本节点保持一致）
function renderScriptSplitOptions(disabled = false) {
    const toggleItem = (action, label, checked, hint = '') => `
        <label class="script-split-toggle-row">
            <input type="checkbox" data-action="${action}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
            <span>${escapeHtml(label)}${hint ? `<span class="script-split-warn">${escapeHtml(hint)}</span>` : ''}</span>
        </label>`;
    const qcOn = state.enableScriptSplitQc === true;
    const qcRounds = [1, 2, 3, 4, 5].includes(Number(state.scriptSplitQcMaxRounds))
        ? Number(state.scriptSplitQcMaxRounds) : 2;
    const qcRoundsOptions = [1, 2, 3, 4, 5].map(n =>
        `<option value="${n}" ${n === qcRounds ? 'selected' : ''}>${n} 次</option>`
    ).join('');
    const languageOptions = (value, custom) => [
        ['', '中文（默认）'],
        ['English', 'English'],
        ['Deutsch', 'Deutsch'],
        ['Français', 'Français'],
        ['Русский', 'Русский'],
    ].map(([optionValue, label]) =>
        `<option value="${escapeHtml(optionValue)}" ${!custom && value === optionValue ? 'selected' : ''}>${escapeHtml(label)}</option>`
    ).join('') + `<option value="**custom**" ${custom ? 'selected' : ''}>自定义语言...</option>`;
    const dialogueLanguage = state.scriptDialogueLanguage || '';
    const promptLanguage = state.scriptPromptLanguage || '';
    const dialogueCustom = state.scriptDialogueLanguageCustom === true;
    const promptCustom = state.scriptPromptLanguageCustom === true;
    const languageLabel = value => value || '中文（默认）';
    return `
        <div class="generate-from-script-model">
            <section class="script-language-panel ${state.scriptLanguageOptionsOpen ? 'is-open' : ''}">
                <button type="button" class="script-language-toggle" data-action="toggle-script-language-options"
                        aria-expanded="${state.scriptLanguageOptionsOpen ? 'true' : 'false'}" ${disabled ? 'disabled' : ''}>
                    <span class="script-language-toggle-title">
                        <span>语言</span>
                        <span class="script-language-summary">对话：${escapeHtml(languageLabel(dialogueLanguage))} · 提示词：${escapeHtml(languageLabel(promptLanguage))}</span>
                    </span>
                    <span class="script-language-chevron" aria-hidden="true">▼</span>
                </button>
                ${state.scriptLanguageOptionsOpen ? `
                <div class="script-language-fields">
                    <label class="script-language-field">
                        <span>对话语言</span>
                        <select data-config-select="scriptDialogueLanguage" ${disabled ? 'disabled' : ''}>${languageOptions(dialogueLanguage, dialogueCustom)}</select>
                        <input type="text" data-script-language-custom="dialogue" value="${escapeHtml(dialogueLanguage)}"
                               placeholder="自定义语言..." ${dialogueCustom ? '' : 'hidden'} ${disabled ? 'disabled' : ''}>
                    </label>
                    <label class="script-language-field">
                        <span>提示词语言</span>
                        <select data-config-select="scriptPromptLanguage" ${disabled ? 'disabled' : ''}>${languageOptions(promptLanguage, promptCustom)}</select>
                        <input type="text" data-script-language-custom="prompt" value="${escapeHtml(promptLanguage)}"
                               placeholder="自定义语言..." ${promptCustom ? '' : 'hidden'} ${disabled ? 'disabled' : ''}>
                    </label>
                </div>` : ''}
            </section>
            <div class="config-label" style="margin-top:12px;">拆分选项</div>
            <div class="script-split-toggles">
                ${toggleItem('toggle-force-medium-shot', '对话禁止全景（使用近景/中景）', state.forceMediumShot !== false)}
                ${toggleItem('toggle-no-bg-music', '不生成背景音乐', state.noBgMusic !== false)}
                ${toggleItem('toggle-split-multi-dialogue', '拆分多人对话镜头（每人尽量一个镜头）', state.splitMultiDialogue === true)}
                ${toggleItem(
                    'toggle-enable-script-split-qc',
                    '开启拆分质检',
                    qcOn,
                    '（会大幅增加时间与算力消耗）'
                )}
            </div>
            ${qcOn ? `
            <div class="script-split-qc-rounds-heading">
                <span class="config-label">质检最大循环次数</span>
                <span class="script-split-qc-free-badge" aria-label="质检次数限时免费">限时免费</span>
            </div>
            <div class="config-hint">拆分→质检最多循环 N 次；仍不通过则强制采用最后一轮结果，避免无法拆分</div>
            <div class="config-select-wrapper">
                <select class="chat-mode-select" data-config-select="scriptSplitQcMaxRounds" ${disabled ? 'disabled' : ''}>${qcRoundsOptions}</select>
            </div>` : ''}
        </div>`;
}

function renderGenerateFromScriptDialog() {
    if (!state.showGenerateFromScriptDialog) return '';
    const busy = state.isGeneratingFromScript;
    const splitModelConfig = renderScriptSplitModelConfig(busy);
    const imageModelConfig = renderImageModelConfig(busy, { collapseTextToImage: true });
    const videoModelConfig = renderDefaultVideoModelConfig(busy);
    const splitDurationConfig = renderScriptSplitDuration(busy);
    const splitOptionsConfig = renderScriptSplitOptions(busy);
    const isEnterprise = state.editionInfo?.mode === 'enterprise';
    const modeIntroCards = [
        ['balanced', '均衡模式', '兼顾生成速度与分镜质量，质量与效率折中。', '质量和效率折中'],
        ['quality', '效果模式', '为长篇连续叙事打造，锁定场景、光影与角色站位一致性，呈现影院级镜头质感。', '影院级一致性'],
        ['speed', '速度模式', '快速拆分剧本，适合草稿预览和方案试跑。', '先出结果']
    ].map(([mode, title, desc, tag]) => {
        // 效果模式（影院级一致性）：金色影院奢华风 + 商业版门控
        const isQuality = mode === 'quality';
        const qualityLocked = isQuality && !isEnterprise;
        const classes = [
            'sequence-mode-intro-card',
            state.autoImageSequenceMode === mode ? 'active' : '',
            busy ? 'is-disabled' : '',
            isQuality ? 'sequence-mode-intro-card--cinema' : '',
            qualityLocked ? 'is-locked' : '',
        ].filter(Boolean).join(' ');
        const proBadge = isQuality ? '<span class="sequence-pro-badge">PRO</span>' : '';
        const lockedBadge = qualityLocked
            ? `<span class="sequence-locked-badge">${icon('lock', 12)}<span>商业版</span></span>`
            : '';
        return `
        <div class="${classes}"
             data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="${mode}">
            <div class="sequence-mode-intro-head">
                <span class="sequence-mode-intro-title">
                    <span class="sequence-mode-radio" aria-hidden="true"></span>
                    <strong>${escapeHtml(title)}</strong>
                </span>
                ${proBadge}
            </div>
            <p>${escapeHtml(desc)}</p>
            <div class="sequence-mode-intro-meta">
                <span class="sequence-mode-benefit">${escapeHtml(tag)}</span>
                ${lockedBadge}
            </div>
        </div>`;
    }).join('');
    return `
        <div class="modal-overlay" data-modal="generate-from-script">
            <div class="export-dialog generate-from-script-dialog">
                <header>
                    <h2>当前故事板还没有分镜</h2>
                    <button data-action="generate-from-script-cancel" ${busy ? 'disabled' : ''}>${icon('close', 18)}</button>
                </header>
                <div class="empty-note">
                    是否根据本集剧本自动拆分并生成分镜、对话数据？
                    ${state.generateFromScriptError ? `<p class="dialog-error">${escapeHtml(state.generateFromScriptError)}</p>` : ''}
                </div>
                <div class="gfs-body">
                    <div class="gfs-col">
                        <div class="generate-from-script-model">
                            ${splitModelConfig}
                        </div>
                        <div class="generate-from-script-model">
                            ${imageModelConfig}
                        </div>
                        <div class="generate-from-script-model">
                            ${videoModelConfig}
                        </div>
                    </div>
                    <div class="gfs-col">
                        ${splitOptionsConfig}
                        ${splitDurationConfig}
                    </div>
                    <div class="gfs-mode-section">
                        <div class="generate-from-script-model">
                            <label class="config-label">分镜图生成模式${state.editionInfo?.mode !== 'enterprise' ? '<span class="config-hint config-hint-inline">效果模式为商业版专属</span>' : ''}</label>
                            <div class="sequence-mode-intro">${modeIntroCards}</div>
                        </div>
                    </div>
                </div>
                <footer class="dialog-footer">
                    <button class="btn-ghost" data-action="generate-from-script-cancel" ${busy ? 'disabled' : ''}>暂不生成</button>
                    <button class="btn-primary" data-action="generate-from-script-confirm" ${busy ? 'disabled' : ''}>
                        ${busy ? '正在生成...' : '生成分镜'}
                    </button>
                </footer>
            </div>
        </div>`;
}

function renderMentionPopup() {
    if (!state.showMentionPopup) return '';
    const groups = {
        character: state.characters,
        scene: state.locations,
        prop: state.props,
    };
    const items = groups[state.mentionTab] || [];
    return `
        <div class="mention-popup">
            <div class="mention-tabs">
                <button data-mention-tab="character" class="${state.mentionTab === 'character' ? 'active' : ''}">角色</button>
                <button data-mention-tab="scene" class="${state.mentionTab === 'scene' ? 'active' : ''}">场景</button>
                <button data-mention-tab="prop" class="${state.mentionTab === 'prop' ? 'active' : ''}">道具</button>
            </div>
            <div class="mention-list">
                ${items.map(item => `<button data-mention-item="${escapeHtml(item.name)}">${item.avatar ? `<img src="${escapeHtml(getThumbnailUrl(item.avatar, 24))}" alt="">` : ''}<span>${escapeHtml(item.name)}</span></button>`).join('') || '<div class="empty-note">暂无资产</div>'}
            </div>
        </div>`;
}

function renderModelConfigModal() {
    if (!state.showModelConfigModal) return '';

    const currentMode = state.chatMode;
    const modeLabel = currentMode === 'video' ? '视频生成' : '对话改图';
    const activeTab = state.currentConfigTab || (currentMode === 'video' ? 'video' : 'dialogue');

    const dialogueContent = renderDialogueModelConfig();
    const imageContent = renderImageModelConfig();
    const videoContent = renderVideoModelConfig();

    return `
        <div class="modal-overlay">
            <div class="export-dialog model-config-dialog" style="max-width: 520px;">
                <header>
                    <h2>模型配置 - ${modeLabel}</h2>
                    <button type="button" class="model-config-close" data-action="close-model-config" aria-label="关闭模型配置" title="关闭">${icon('close', 18)}</button>
                </header>
                <div class="model-config-tabs">
                    <button class="tab-btn ${activeTab==='dialogue'?'active':''}" data-config-tab="dialogue">对话模型</button>
                    <button class="tab-btn ${activeTab==='image'?'active':''}" data-config-tab="image">生图模型</button>
                    <button class="tab-btn ${activeTab==='video'?'active':''}" data-config-tab="video">视频模型</button>
                </div>
                <div class="model-config-body">
                    <div class="config-content" data-config-content="dialogue" style="display:${activeTab==='dialogue'?'block':'none'}">${dialogueContent}</div>
                    <div class="config-content" data-config-content="image" style="display:${activeTab==='image'?'block':'none'}">${imageContent}</div>
                    <div class="config-content" data-config-content="video" style="display:${activeTab==='video'?'block':'none'}">${videoContent}</div>
                </div>
                <footer class="dialog-footer">
                    <div class="model-config-apply-hint">选择后自动应用到助手当前模式</div>
                </footer>
            </div>
        </div>`;
}

function renderDialogueModelConfig() {
    // 按 vendor 分组，复用 script_writer 逻辑 —— 一个 select 多个 optgroup
    const vendors = state.llmVendors || [];
    const models = state.llmModels || [];

    const vendorMap = {};
    vendors.forEach(v => {
        vendorMap[v.id || v.vendor_name] = v;
    });

    const groups = {};
    models.forEach(m => {
        const vid = m.vendor_id || m.vendor_name || 'unknown';
        if (!groups[vid]) groups[vid] = [];
        groups[vid].push(m);
    });

    let html = '<label class="config-label">对话模型</label><div class="config-hint">选择后用于对话改图等需要 LLM 的场景</div><div class="config-select-wrapper"><select class="chat-mode-select" data-config-select="dialogue">';
    const vendorKeys = Object.keys(groups);
    if (vendorKeys.length === 0) {
        html += '<option value="">暂无对话模型</option>';
        html += '</select></div>';
        return html;
    }

    const isSelectedDialogueModel = (model) => {
        const selected = state.selectedLlmModel;
        if (!selected) return false;
        const val = model.model || model.name || model.id || '';
        const modelId = model.model_id || model.id || '';
        const vendorId = model.vendor_id || '';
        if (typeof selected === 'object') {
            const selectedModelId = selected.model_id || selected.id || '';
            const selectedVendorId = selected.vendor_id || '';
            if (selectedModelId || selectedVendorId) {
                return String(selectedModelId) === String(modelId)
                    && String(selectedVendorId || vendorId) === String(vendorId);
            }
            return String(selected.model || selected.name || '') === String(val);
        }
        return String(selected) === String(val);
    };

    vendorKeys.forEach(vid => {
        const v = vendorMap[vid] || { vendor_name: vid };
        const iconStr = v.icon || '🤖';
        const vendorNameAttr = escapeHtml(v.vendor_name || vid);
        html += `<optgroup label="${iconStr} ${vendorNameAttr}">`;
        groups[vid].forEach(m => {
            const val = m.model || m.name || m.id || '';
            const label = m.name || m.model || val;
            const modelId = m.model_id || m.id || '';
            const vendorId = m.vendor_id || '';
            const supportsThinking = m.supports_thinking === true || m.supports_thinking === 1 || m.supports_thinking === 'true' ? 'true' : 'false';
            const sel = isSelectedDialogueModel(m) ? 'selected' : '';
            html += `<option value="${escapeHtml(val)}" data-model-id="${escapeHtml(modelId)}" data-vendor-id="${escapeHtml(vendorId)}" data-vendor-name="${vendorNameAttr}" data-supports-thinking="${supportsThinking}" ${sel}>${escapeHtml(label)}</option>`;
        });
        html += `</optgroup>`;
    });
    html += `</select></div>`;
    html += renderThinkingControls(state.selectedLlmModel);
    return html;
}

/**
 * 思考模式控件（对齐 script_writer）：
 * - supports_thinking 的模型显示开关
 * - DeepSeek：默认开思考
 * - Doubao/volcengine：开思考后显示强度 low/medium/high
 */
function renderThinkingControls(selection) {
    const meta = getSelectedLlmMeta(selection);
    if (!meta.supportsThinking) {
        return '';
    }
    const effortVisible = state.enableThinking && meta.isDoubaoEffort;
    const effort = ['low', 'medium', 'high'].includes(state.thinkingEffort)
        ? state.thinkingEffort
        : 'medium';
    return `
        <div class="sb-thinking-wrap" data-thinking-wrap title="思考模式：让模型先深度思考再回答">
            <label class="sb-thinking-toggle">
                <input type="checkbox" data-action="toggle-enable-thinking" ${state.enableThinking ? 'checked' : ''}>
                <span class="sb-thinking-slider"></span>
            </label>
            <span class="sb-thinking-label" data-action="toggle-enable-thinking-label">思考</span>
            <select class="sb-thinking-effort" data-config-select="thinkingEffort"
                style="display:${effortVisible ? 'inline-block' : 'none'}"
                title="思考强度（Doubao 等模型）">
                <option value="low" ${effort === 'low' ? 'selected' : ''}>低</option>
                <option value="medium" ${effort === 'medium' ? 'selected' : ''}>中</option>
                <option value="high" ${effort === 'high' ? 'selected' : ''}>高</option>
            </select>
        </div>`;
}

/** 格式化模型 option 的算力展示文本。
 *  - 固定计费：'2算力'
 *  - 按时长计费（多档位）：'8-18算力'
 *  - 按时长计费（单档位）：'8+算力'
 *  - 无算力配置：''（调用方据此跳过）
 */
function formatComputingPower(m) {
    const cp = Number(m?.computing_power) || 0;
    if (cp <= 0) return '';
    if (m?.computing_power_mode === 'by_duration') {
        const range = m.computing_power_range;
        if (Array.isArray(range) && range.length === 2 && range[0] !== range[1]) {
            return `${range[0]}-${range[1]}算力`;
        }
        return `${cp}+算力`;
    }
    return `${cp}算力`;
}

/** 格式化模型 option 的分辨率展示文本（仅视频模型有 supported_video_resolutions）。
 *  返回 '480P/720P/1080P/4K'；无则返回 ''。
 */
function formatVideoResolutions(m) {
    const opts = m?.supported_video_resolutions || [];
    if (!Array.isArray(opts) || !opts.length) return '';
    const labels = opts
        .map(o => (typeof o === 'string' ? o : (o?.label || o?.value || '')))
        .filter(Boolean);
    return labels.length ? labels.join('/') : '';
}

/** 格式化模型 option 完整标签：Name + (算力[, 分辨率])。
 *  图片模型只显示算力；视频模型显示算力 + 分辨率（如有）。
 */
function formatModelOptionLabel(m) {
    if (!m) return '';
    const extras = [];
    const power = formatComputingPower(m);
    if (power) extras.push(power);
    const res = formatVideoResolutions(m);
    if (res) extras.push(res);
    return extras.length ? `${m.name}（${extras.join('，')}）` : m.name;
}

function renderMediaModelSelect(label, hint, type, models, selectedTaskId, disabled = false) {
    let html = `<label class="config-label">${escapeHtml(label)}</label>`
        + `<div class="config-hint">${escapeHtml(hint)}</div>`
        + `<div class="config-select-wrapper"><select class="chat-mode-select" data-config-select="${type}"${disabled ? ' disabled' : ''}>`;
    models.forEach(m => {
        const val = m.task_id;
        const sel = String(selectedTaskId) === String(val) ? 'selected' : '';
        html += `<option value="${val}" ${sel}>${escapeHtml(formatModelOptionLabel(m))}</option>`;
    });
    return html + '</select></div>';
}

function renderImageModelConfig(disabled = false, { collapseTextToImage = false } = {}) {
    const textModels = state.textToImageModels.length ? state.textToImageModels : state.imageModels;
    const editModels = state.imageEditModels.length ? state.imageEditModels : state.imageModels;
    const textSelect = renderMediaModelSelect(
        '文生图模型', '无参考图时使用', 'textToImage', textModels,
        state.selectedTextToImageTaskId, disabled,
    );
    const editSelect = renderMediaModelSelect(
        '图片编辑模型', '有参考图或执行改图时使用', 'imageEdit', editModels,
        state.selectedImageEditTaskId, disabled,
    );
    if (!collapseTextToImage) return textSelect + editSelect;

    const open = state.scriptSplitTextToImageOpen === true;
    const selected = textModels.find(m => String(m.task_id) === String(state.selectedTextToImageTaskId))
        || textModels[0];
    const summary = selected ? formatModelOptionLabel(selected) : '未选择';
    return `
        <div class="gfs-t2i-panel ${open ? 'is-open' : ''}">
            <button type="button" class="gfs-t2i-toggle" data-action="toggle-script-split-t2i"
                    aria-expanded="${open ? 'true' : 'false'}" ${disabled ? 'disabled' : ''}>
                <span class="script-language-toggle-title">
                    <span>文生图模型</span>
                    <span class="script-language-summary">${escapeHtml(summary)}</span>
                </span>
                <span class="script-language-chevron" aria-hidden="true">▼</span>
            </button>
            ${open ? `<div class="gfs-t2i-body">${textSelect}</div>` : ''}
        </div>
    ` + editSelect;
}

/**
 * 是否处理人脸（Seedance 2.0 系列；对齐 index 生视频界面）。
 * 社区版置灰 + 提示；商业版可勾选。
 */
function renderFaceMaskToggle(disabled = false) {
    const model = getSelectedImageToVideoModel();
    if (!modelNeedsFaceMask(model)) return '';
    const isEnterprise = isEnterpriseEdition();
    const checked = state.enableFaceMask === true ? 'checked' : '';
    const inputDisabled = disabled || !isEnterprise ? 'disabled' : '';
    const hint = isEnterprise
        ? ''
        : `<div class="process-face-hint">此功能为商业版功能，请联系购买商业版本后使用</div>`;
    return `
        <div class="process-face-row" data-face-mask-toggle>
            <label class="process-face-label">
                <input type="checkbox" data-action="toggle-enable-face-mask"
                       ${checked} ${inputDisabled}>
                <span>是否处理人脸</span>
            </label>
            ${hint}
        </div>`;
}

/** 拆分弹窗：默认视频模型（仅首帧/首尾帧图生视频）+ 条件人脸遮盖 */
function renderDefaultVideoModelConfig(disabled = false) {
    return renderMediaModelSelect(
        '默认视频模型',
        '分镜有首帧时用于生成视频；仅列出支持首帧/首尾帧的模型。参考图专用模型请到齿轮「参考视频模型」中选择',
        'imageToVideo',
        getImageToVideoSlotModels(),
        state.selectedImageToVideoTaskId,
        disabled,
    ) + renderFaceMaskToggle(disabled);
}

function renderVideoResolutionChips(model, { label = '分辨率', hint = '' } = {}) {
    const resOpts = getVideoResolutionOptions(model);
    if (!resOpts.length) return '';
    const curRes = state.videoResolution && resOpts.some(o => o.value === state.videoResolution)
        ? state.videoResolution
        : (getDefaultVideoResolution(model) || resOpts[0]?.value || '');
    let html = `<label class="config-label" style="margin-top:14px;">${escapeHtml(label)}</label>`;
    if (hint) {
        html += `<div class="config-hint">${escapeHtml(hint)}</div>`;
    }
    html += `<div class="config-chip-row">`;
    resOpts.forEach(opt => {
        const active = String(curRes) === String(opt.value) ? 'active' : '';
        html += `<button type="button" class="config-chip ${active}" data-action="set-video-resolution" data-video-resolution="${escapeHtml(opt.value)}">${escapeHtml(opt.label || opt.value)}</button>`;
    });
    html += '</div>';
    return html;
}

function renderVideoModelConfig() {
    // 齿轮弹窗：分辨率绑定「图生视频模型」（分镜主路径 i2v / 对口型共用偏好），
    // 不再用 getSelectedVideoModel()（会随输入图落到文生视频导致分辨率空白/跟错模型）。
    const models = getImageToVideoSlotModels();
    const i2vModel = getSelectedImageToVideoModel();
    const scene = getCurrentScene();
    const durations = getVideoSupportedDurations(i2vModel);
    const resolvedAuto = resolveVideoDurationSeconds(scene, i2vModel, 'auto');
    const sceneDur = Number(scene?.duration);
    const sceneDurLabel = Number.isFinite(sceneDur) ? sceneDur.toFixed(sceneDur % 1 ? 1 : 0) : '—';

    const textModels = state.textToVideoModels.length ? state.textToVideoModels : state.videoModels;
    const referenceModels = getReferenceToVideoSlotModels();
    let html = renderMediaModelSelect(
        '文生视频模型', '无图片输入时使用', 'textToVideo', textModels,
        state.selectedTextToVideoTaskId,
    ) + renderMediaModelSelect(
        '图生视频模型', '首帧或首尾帧输入时使用；对口型数字人也使用此处分辨率偏好', 'imageToVideo', models,
        state.selectedImageToVideoTaskId,
    ) + renderVideoResolutionChips(i2vModel, {
        label: '分辨率',
        hint: '随当前「图生视频模型」变化；对口型 MiniMax 将映射为最长边（480P→720 / 720P→1280 / 1080P→1920）',
    }) + renderFaceMaskToggle() + renderMediaModelSelect(
        '参考视频模型', '多参考图、参考音视频或首尾帧加参考图时使用', 'referenceToVideo', referenceModels,
        state.selectedReferenceToVideoTaskId,
    );

    html += `<label class="config-label" style="margin-top:14px;">视频时长</label>
        <div class="config-hint">Auto 会按当前分镜时长（含配音同步后）匹配「≥分镜时长且最接近」的模型档位；对口型 MiniMax 另 clamp 到 4–10 秒</div>
        <div class="config-select-wrapper">
            <select class="chat-mode-select" data-config-select="videoDuration">`;
    const mode = state.videoDurationMode;
    const autoSel = mode === 'auto' ? 'selected' : '';
    html += `<option value="auto" ${autoSel}>Auto（${escapeHtml(String(sceneDurLabel))}s → ${resolvedAuto}s）</option>`;
    durations.forEach(d => {
        const sel = String(mode) === String(d) ? 'selected' : '';
        html += `<option value="${d}" ${sel}>${d} 秒</option>`;
    });
    html += `</select></div>`;
    if (mode === 'auto') {
        html += `<div class="config-hint config-hint-inline">当前分镜 ${escapeHtml(String(sceneDurLabel))} 秒，将请求 <strong>${resolvedAuto}</strong> 秒视频</div>`;
    }

    const clipChecked = state.clipToAudioDuration !== false ? 'checked' : '';
    html += `<div class="config-toggle-row" style="margin-top:14px;">
        <label class="config-toggle-label">
            <input type="checkbox" data-action="toggle-clip-to-audio" ${clipChecked}>
            <span>裁剪至配音时长</span>
        </label>
        <div class="config-hint">开启后写入分镜配置，导出时将视频裁到与配音（分镜时长）一致；关闭则导出完整视频</div>
    </div>`;

    return html;
}

function renderGlobalStyleDialog() {
    if (!state.showGlobalStyleDialog) return '';
    const styleVal = escapeHtml(state.style || '');
    const compVal = escapeHtml(state.compositionPreference || '');
    return `
        <div class="modal-overlay">
            <div class="edit-dialog">
                <header>
                    <h2>编辑画风和构图倾向</h2>
                    <button data-action="close-global-style">${icon('close', 18)}</button>
                </header>
                <div style="padding:12px 16px;">
                    <label style="display:block; margin-bottom:14px; font-size:13px;">
                        画风（全局共享）
                        <input data-global-field="style" value="${styleVal}" style="width:100%; margin-top:6px; padding:6px 8px; border:1px solid #ccc; border-radius:4px;" placeholder="例如：赛博朋克、写实电影感、动漫风格...">
                    </label>
                    <label style="display:block; font-size:13px;">
                        构图倾向（全局共享）
                        <input data-global-field="composition" value="${compVal}" style="width:100%; margin-top:6px; padding:6px 8px; border:1px solid #ccc; border-radius:4px;" placeholder="例如：三分法、中心构图、对称构图、电影运镜...">
                    </label>
                    <div style="font-size:11px; color:#888; margin-top:10px;">修改后将影响整个故事板的所有分镜画面。</div>
                </div>
                <footer class="dialog-footer">
                    <button class="btn-ghost" data-action="close-global-style">取消</button>
                    <button class="btn-primary" data-action="save-global-style">保存</button>
                </footer>
            </div>
        </div>`;
}

/** 分镜编辑弹框：编辑 title / duration / difficulty / act_name（当前 UI 缺失表单的字段） */
function renderSceneEditDialog() {
    if (!state.showSceneEditDialog) return '';
    const scene = state.scenes.find(s => s.id === state.sceneEditTargetId);
    if (!scene) return '';
    const titleVal = escapeHtml(scene.title || '');
    const durationVal = scene.duration ?? '';
    const difficulty = scene.difficulty || '';
    const actNameVal = escapeHtml(scene.actName || '');
    const errHtml = state.sceneEditError ? `<div class="dialog-error">${escapeHtml(state.sceneEditError)}</div>` : '';
    const saveLabel = state.sceneEditSaving ? '保存中…' : '保存';
    return `
        <div class="modal-overlay">
            <div class="edit-dialog">
                <header>
                    <h2>编辑分镜</h2>
                    <button data-action="close-scene-edit">${icon('close', 18)}</button>
                </header>
                <div style="padding:12px 16px;">
                    <label style="display:block; margin-bottom:14px; font-size:13px;">
                        标题
                        <input data-scene-edit-field="title" value="${titleVal}" style="width:100%; margin-top:6px; padding:6px 8px; border:1px solid #ccc; border-radius:4px;">
                    </label>
                    <label style="display:block; margin-bottom:14px; font-size:13px;">
                        时长（秒）
                        <input type="number" step="0.001" min="0" data-scene-edit-field="duration" value="${durationVal}" style="width:100%; margin-top:6px; padding:6px 8px; border:1px solid #ccc; border-radius:4px;">
                    </label>
                    <label style="display:block; margin-bottom:14px; font-size:13px;">
                        难度
                        <select data-scene-edit-field="difficulty" style="width:100%; margin-top:6px; padding:6px 8px; border:1px solid #ccc; border-radius:4px;">
                            ${['易', '中', '难'].map(d => `<option value="${d}" ${difficulty === d ? 'selected' : ''}>${d}</option>`).join('')}
                        </select>
                    </label>
                    <label style="display:block; font-size:13px;">
                        所属幕
                        <input data-scene-edit-field="act_name" value="${actNameVal}" style="width:100%; margin-top:6px; padding:6px 8px; border:1px solid #ccc; border-radius:4px;" placeholder="可空">
                    </label>
                    ${errHtml}
                </div>
                <footer class="dialog-footer">
                    <button class="btn-ghost" data-action="close-scene-edit">取消</button>
                    <button class="btn-primary" data-action="save-scene-edit" ${state.sceneEditSaving ? 'disabled' : ''}>${saveLabel}</button>
                </footer>
            </div>
        </div>`;
}

function renderVideoTypeSwitchDialog() {
    const switchState = state.videoTypeSwitch || {};
    const targetType = switchState.targetType;
    if (!targetType) return '';
    const switchingToVideo = targetType === 'video';
    const title = switchingToVideo ? '切换为视频模式？' : '切换为对口型模式？';
    const description = switchingToVideo
        ? '已生成的对口型视频仍会保留并继续作为当前视频。正在生成的对口型任务不会中断，完成后只加入候选列表，不会自动替换当前视频。'
        : '已有普通视频会继续保留。对口型视频生成前需要单个说话角色的配音和人物形象。';
    return `
        <div class="modal-overlay" data-modal="video-type-switch">
            <div class="edit-dialog video-type-switch-dialog" role="dialog" aria-modal="true" aria-labelledby="video-type-switch-title">
                <header>
                    <h2 id="video-type-switch-title">${title}</h2>
                    <button type="button" data-action="cancel-video-type-switch" ${switchState.saving ? 'disabled' : ''}>${icon('close', 18)}</button>
                </header>
                <div class="video-type-switch-dialog-body">${description}</div>
                <footer class="dialog-footer">
                    <button class="btn-ghost" data-action="cancel-video-type-switch" ${switchState.saving ? 'disabled' : ''}>取消</button>
                    <button class="btn-primary" data-action="confirm-video-type-switch" ${switchState.saving ? 'disabled' : ''}>${switchState.saving ? '切换中…' : (switchingToVideo ? '切换为视频模式' : '切换为对口型')}</button>
                </footer>
            </div>
        </div>`;
}

function renderGenerateProgressDialog() {
    if (!state.showGenerateProgressDialog) return '';
    const steps = state.generateProgressSteps || [];
    const error = state.generateProgressError || '';
    const rawProgress = Number(state.generateProgressPercent);
    const progressPercent = Number.isFinite(rawProgress)
        ? Math.round(Math.max(0, Math.min(100, rawProgress)))
        : 0;
    const progressMessage = state.generateProgressMessage || '正在处理任务';
    const stepHtml = steps.map((step) => {
        let cls = step.status || 'pending';
        // 失败/暂停后：running 不得继续转圈，降级为 failed 并显示停止图标
        if (cls === 'running' && error) {
            cls = 'failed';
        }
        let iconHtml;
        let statusText;
        if (cls === 'completed') {
            iconHtml = icon('success', 16);
            statusText = '执行完毕';
        } else if (cls === 'running') {
            iconHtml = `<span class="spinner">${icon('loading', 16)}</span>`;
            statusText = '执行中';
        } else if (cls === 'failed') {
            iconHtml = icon('stop', 16);
            statusText = '已停止';
        } else {
            iconHtml = icon('circle', 16);
            statusText = '待开始执行';
        }
        return `
            <div class="progress-step ${cls}">
                <div class="progress-step-icon">${iconHtml}</div>
                <div class="progress-step-name">${escapeHtml(step.name)}</div>
                <div class="progress-step-status ${cls}">${statusText}</div>
            </div>`;
    }).join('');

    const footer = error
        ? `<div class="generate-progress-footer">
            <button class="btn-ghost" data-action="close-generate-progress">关闭</button>
            <button class="btn-primary" data-action="retry-generate-progress">重试</button>
           </div>`
        : '';

    return `
        <div class="modal-overlay" data-modal="generate-progress" data-dismissible="${error ? 'true' : 'false'}">
            <div class="export-dialog generate-progress-dialog">
                <header>
                    <h2>${error ? '分镜生成已停止' : '正在生成分镜...'}</h2>
                    <button data-action="close-generate-progress"
                        title="${error ? '关闭' : '最小化（任务在后台继续运行）'}"
                        aria-label="${error ? '关闭' : '最小化，任务在后台继续运行'}">${icon('close', 18)}</button>
                </header>
                <div class="generate-progress-summary">
                    <div class="generate-progress-meta">
                        <span class="generate-progress-message">${escapeHtml(progressMessage)}</span>
                        <strong class="generate-progress-percent">${progressPercent}%</strong>
                    </div>
                    <div class="generate-progress-track" role="progressbar"
                         aria-label="任务总体进度" aria-valuemin="0" aria-valuemax="100"
                         aria-valuenow="${progressPercent}">
                        <div class="generate-progress-fill" style="width: ${progressPercent}%"></div>
                    </div>
                </div>
                <div class="progress-steps">
                    ${stepHtml}
                </div>
                ${error ? `<div class="generate-progress-error">${escapeHtml(error)}</div>` : ''}
                ${footer}
            </div>
        </div>`;
}

// ==================== 分区刷新 refresh(regions) ====================

/**
 * 世界内首建：视频比例确认门禁弹窗。
 * 确认前不 create、不进入编辑器、不弹拆分框。
 */
function renderRatioConfirmDialog() {
    if (!state.showRatioConfirmDialog && !state.ratioGateActive) return '';
    const busy = !!state.isCreatingStoryboard;
    const selected = state.pendingCreateRatio === '9:16' ? '9:16' : '16:9';
    const err = state.ratioConfirmError
        ? `<p class="dialog-error sb-ratio-confirm-error">${escapeHtml(state.ratioConfirmError)}</p>`
        : '';
    const option = (value, label, iconClass) => {
        const checked = selected === value;
        return `
            <label class="sb-ratio-option ${checked ? 'checked' : ''}" data-action="select-create-ratio" data-ratio="${value}">
                <input type="radio" name="storyboardCreateRatio" value="${value}" ${checked ? 'checked' : ''} ${busy ? 'disabled' : ''}>
                <div class="sb-ratio-icon ${iconClass}"></div>
                <div class="sb-ratio-text">
                    <span class="sb-ratio-value">${value}</span>
                    <span class="sb-ratio-label">${label}</span>
                </div>
            </label>`;
    };
    return `
        <div class="modal-overlay sb-ratio-gate-overlay" data-modal="ratio-confirm" data-dismissible="false">
            <div class="export-dialog sb-ratio-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="sb-ratio-confirm-title">
                <header>
                    <h2 id="sb-ratio-confirm-title">选择视频比例</h2>
                </header>
                <div class="empty-note">
                    本世界尚无故事板，请先选择视频画幅后再继续。后续新建的其它集将自动继承该比例。错误的比例会导致分镜构图与生成结果全部错误。
                    ${err}
                </div>
                <div class="sb-ratio-options">
                    ${option('16:9', '横屏', 'sb-ratio-icon-landscape')}
                    ${option('9:16', '竖屏', 'sb-ratio-icon-portrait')}
                </div>
                <div class="dialog-actions sb-ratio-confirm-actions">
                    <button type="button" class="btn-secondary" data-action="cancel-create-ratio" ${busy ? 'disabled' : ''}>取消</button>
                    <button type="button" class="btn-primary" data-action="confirm-create-ratio" ${busy ? 'disabled' : ''}>
                        ${busy ? '创建中…' : '确认并创建'}
                    </button>
                </div>
            </div>
        </div>`;
}

function renderModalsHtml() {
    return [
        renderRatioConfirmDialog(),
        renderGenerateFromScriptDialog(),
        renderGenerateProgressDialog(),
        renderPowerLogsDialog(),
        renderRechargeDialog(),
        renderMentionPopup(),
        renderModelConfigModal(),
        renderGlobalStyleDialog(),
        renderSceneEditDialog(),
        renderVideoTypeSwitchDialog(),
        renderEmoVecEditorDialog(),
    ].join('');
}

/** 用一段 HTML（单根节点）替换现有节点；返回新节点或 null */
function replaceElWithHtml(el, html) {
    if (!el || !html) return null;
    const tmp = document.createElement('div');
    tmp.innerHTML = html.trim();
    const next = tmp.firstElementChild;
    if (!next) return null;
    el.replaceWith(next);
    return next;
}

function normalizeRegions(regions) {
    if (regions == null || regions === 'all') {
        return new Set(['all']);
    }
    const list = Array.isArray(regions) ? regions : [regions];
    const set = new Set();
    list.forEach((r) => {
        if (r == null || r === '') return;
        if (r === 'all') set.add('all');
        else set.add(r);
    });
    if (set.size === 0) set.add('all');
    return set;
}

/**
 * 播放占用主预览时禁止拆 preview：补丁非媒体区。
 */
export function softRefreshUiWhilePreviewBusy() {
    patchAgentChatLog();
    patchHeaderPower();
    const scene = getCurrentScene();
    if (scene) updateCurrentSceneDetail(scene);
    updateTimelineProgress();
    return true;
}

/** 只刷新 header 算力数字 */
export function patchHeaderPower() {
    const el = document.querySelector('.computing-power-display .power-value');
    if (!el) return false;
    const power = state.computingPower;
    const powerText = formatPowerDisplay(power);
    el.textContent = powerText;
    const btn = el.closest('.computing-power-display');
    if (btn) {
        const level = getPowerLevelClass(power);
        btn.className = `computing-power-display ${level}`;
    }
    return true;
}

/** 只刷新分镜助手对话列表（Agent SSE 高频路径） */
export function patchAgentChatLog() {
    const dock = document.querySelector('.ai-chat-dock');
    const host = (dock && dock.querySelector('.agent-chat-log'))
        || document.querySelector('.agent-chat-log');
    const html = renderAgentMessages();
    if (!html) {
        if (host) host.remove();
        return Boolean(dock || host);
    }
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const next = tmp.firstElementChild;
    if (!next) return false;
    if (host) {
        const wasAtBottom = (host.scrollHeight - host.scrollTop - host.clientHeight) < 48;
        host.replaceWith(next);
        if (wasAtBottom || isSceneAgentRunning(state.currentSceneId)) {
            next.scrollTop = next.scrollHeight;
        }
        return true;
    }
    if (dock) {
        dock.insertBefore(next, dock.firstChild);
        next.scrollTop = next.scrollHeight;
        return true;
    }
    return false;
}

/** 整块刷新分镜助手（历史 + 输入区），不碰主预览 */
export function patchAgentPanel() {
    const section = document.querySelector('.ai-chat-section');
    if (!section) return false;
    const html = renderAiPanel();
    return Boolean(replaceElWithHtml(section, html));
}

/** 整块 header（含集数选择器等） */
export function patchHeader() {
    const header = document.querySelector('.app-shell > header.header, .app-shell > .header, header.header');
    if (!header) return false;
    return Boolean(replaceElWithHtml(header, renderHeader()));
}

/**
 * 捕获容器内焦点，便于 patch 后恢复（避免编辑提示词/台词时光标丢失）。
 * @returns {{ selector: string, start: number, end: number } | null}
 */
function captureFocusIn(container) {
    const ae = document.activeElement;
    if (!container || !ae || !container.contains(ae)) return null;
    if (!(ae instanceof HTMLInputElement || ae instanceof HTMLTextAreaElement || ae instanceof HTMLSelectElement)) {
        return null;
    }
    // 用稳定属性拼选择器
    let selector = ae.tagName.toLowerCase();
    if (ae.id) selector = `#${CSS.escape ? CSS.escape(ae.id) : ae.id}`;
    else if (ae.name) selector += `[name="${ae.name}"]`;
    else if (ae.dataset) {
        const keys = Object.keys(ae.dataset);
        for (const k of keys) {
            const attr = `data-${k.replace(/[A-Z]/g, m => `-${m.toLowerCase()}`)}`;
            const val = ae.getAttribute(attr);
            if (val != null) {
                selector += `[${attr}="${String(val).replace(/"/g, '\\"')}"]`;
                break;
            }
        }
    }
    if (ae.className && typeof ae.className === 'string') {
        const cls = ae.className.trim().split(/\s+/).filter(Boolean)[0];
        if (cls && !ae.id) selector += `.${CSS.escape ? CSS.escape(cls) : cls}`;
    }
    const start = typeof ae.selectionStart === 'number' ? ae.selectionStart : 0;
    const end = typeof ae.selectionEnd === 'number' ? ae.selectionEnd : start;
    return { selector, start, end, value: ae.value };
}

function restoreFocusIn(container, snap) {
    if (!container || !snap) return;
    let el = null;
    try {
        el = container.querySelector(snap.selector);
    } catch {
        el = null;
    }
    if (!el || typeof el.focus !== 'function') return;
    el.focus({ preventScroll: true });
    if (typeof el.setSelectionRange === 'function' && snap.value === el.value) {
        try {
            el.setSelectionRange(snap.start, snap.end);
        } catch {
            // ignore
        }
    }
}

/** 仅刷左栏工作台（标题/Tab/画面|对话），不碰助手，保留滚动与焦点 */
export function patchLeftWorkspace() {
    const aside = document.querySelector('.main-layout > .left-sidebar');
    if (!aside) return false;
    const content = aside.querySelector('.sidebar-content');
    if (!content) return patchLeftSidebar();
    const scene = getCurrentScene();
    const scrollTop = content.scrollTop;
    const focusSnap = captureFocusIn(content);

    // 与 renderLeftSidebar 内 .sidebar-content 结构对齐
    const tabs = [
        ['scene', 'image', '画面'],
        ['dialogue', 'mic', '对话'],
    ].map(([key, iconName, label]) => `
        <button class="tab-btn ${state.activeTab === key ? 'active' : ''}" data-tab="${key}">
            ${icon(iconName, 16)} ${label}
        </button>`).join('');
    const actTag = (() => {
        if (!scene || !scene.groupId) return '';
        const numStr = String(scene.groupId).replace(/^grp_?0*/i, '');
        const num = parseInt(numStr, 10);
        if (!Number.isFinite(num) || num <= 0) return '';
        return `<span class="act-tag">幕${String(num).padStart(2, '0')}</span>`;
    })();
    content.innerHTML = `
        <div class="project-info">
            <div class="project-brand">
                ${actTag}
                <div class="brand-icon">${scene ? escapeHtml(scene.title) : '分镜'}</div>
                <span>分镜工作台</span>
            </div>
        </div>
        <div class="tab-nav">${tabs}</div>
        ${renderTabs(scene)}`;
    content.scrollTop = scrollTop;
    restoreFocusIn(content, focusSnap);
    return true;
}

/** 左栏整块（工作台 + 助手）；切镜时用 */
export function patchLeftSidebar() {
    const aside = document.querySelector('.main-layout > .left-sidebar');
    if (!aside) return false;
    const scene = getCurrentScene();
    const scrollEl = aside.querySelector('.sidebar-content');
    const scrollTop = scrollEl ? scrollEl.scrollTop : 0;
    const focusSnap = captureFocusIn(aside);
    const agentScroll = aside.querySelector('.agent-chat-log')?.scrollTop ?? null;
    const next = replaceElWithHtml(aside, renderLeftSidebar(scene));
    if (next) {
        const sc = next.querySelector('.sidebar-content');
        if (sc) sc.scrollTop = scrollTop;
        const log = next.querySelector('.agent-chat-log');
        if (log && agentScroll != null) log.scrollTop = agentScroll;
        restoreFocusIn(next, focusSnap);
    }
    return Boolean(next);
}

/**
 * 同步时间轴/Grid 选中态（不重建节点）。
 */
export function syncTimelineSelectionActive() {
    const id = state.currentSceneId;
    document.querySelectorAll('.scene-timeline-thumb.active').forEach((n) => n.classList.remove('active'));
    document.querySelectorAll('.storyboard-card.active').forEach((n) => n.classList.remove('active'));
    if (id == null) return false;
    const thumb = document.querySelector(`.scene-timeline-thumb[data-scene="${id}"]`);
    if (thumb) thumb.classList.add('active');
    const card = document.querySelector(`.storyboard-card[data-scene="${id}"]`);
    if (card) card.classList.add('active');
    updatePlayheadPosition({ followScroll: false });
    return true;
}

/**
 * 重建时间轴 list（不碰 preview-wrapper）。用于增删分镜。
 */
export function patchTimelineListStructure() {
    if (state.viewMode === 'grid') return false;
    const list = document.querySelector('.scene-timeline-list');
    if (!list) return false;
    const scrollLeft = list.scrollLeft;
    const sig = scenesStructureSig();
    list.innerHTML = renderTimelineListInner();
    list.dataset.scenesSig = sig;
    applyTimelineRatioVars(list, state.workflowRatio || '16:9');
    list.scrollLeft = scrollLeft;
    // 写入各 thumb 的 mediaSig，避免下一轮 updateSceneThumb 误判重复刷
    (state.scenes || []).forEach((sc) => {
        const thumbBtn = document.querySelector(`.scene-timeline-thumb[data-scene="${sc.id}"]`);
        if (!thumbBtn) return;
        const nextUrl = sc.firstFrameUrl || '';
        const nextStatus = getFirstFrameDisplayStatus(sc);
        thumbBtn.dataset.mediaSig = `${nextUrl}|${nextStatus}|${sc.durationLabel || ''}`;
    });
    updateAutoCompleteHeader();
    updatePlayheadPosition({ followScroll: false });
    return true;
}

/**
 * 重建 Grid 卡片区（grid 模式无中央 preview）。
 */
export function patchGridStructure() {
    if (state.viewMode !== 'grid') return false;
    const grid = document.querySelector('.storyboard-grid');
    if (!grid) return false;
    const scrollTop = grid.scrollTop;
    const sig = scenesStructureSig();
    grid.innerHTML = renderGridInner();
    grid.dataset.scenesSig = sig;
    grid.scrollTop = scrollTop;
    (state.scenes || []).forEach((sc) => {
        const cell = document.querySelector(`.storyboard-card[data-scene="${sc.id}"]`)?.closest('.storyboard-grid-cell');
        if (!cell) return;
        const nextUrl = sc.firstFrameUrl || '';
        const nextStatus = getFirstFrameDisplayStatus(sc);
        cell.dataset.mediaSig = `${nextUrl}|${nextStatus}|${sc.durationLabel || ''}`;
        cell.dataset.sceneId = String(sc.id);
    });
    updateAutoCompleteHeader();
    return true;
}

/**
 * 中栏：仅 viewMode 切换（timeline↔grid）时需要整块替换。
 * 若仅是分镜集合变化，应走 TIMELINE_LIST / GRID 结构 patch，避免拆 preview。
 */
export function patchCenter() {
    const main = document.querySelector('.main-layout > .center-panel');
    if (!main) return false;
    if (isPreviewMediaBusy()) return false;
    const scene = getCurrentScene();
    const list = main.querySelector('.scene-timeline-list');
    const scrollLeft = list ? list.scrollLeft : 0;
    const grid = main.querySelector('.storyboard-grid');
    const scrollTop = grid ? grid.scrollTop : 0;
    const oldKey = previewMediaKey(main.querySelector('.preview-media'));
    // 同 viewMode 且仅结构变化：优先结构 patch，保留 preview 节点
    const hasTimeline = Boolean(list);
    const hasGrid = Boolean(grid);
    const wantGrid = state.viewMode === 'grid';
    if (wantGrid && hasGrid) {
        return patchGridStructure();
    }
    if (!wantGrid && hasTimeline) {
        // 保留 preview-wrapper，只换 timeline 列表
        const ok = patchTimelineListStructure();
        patchTimelineChrome();
        return ok;
    }
    // viewMode 与 DOM 不一致（真正切换视图）
    const next = replaceElWithHtml(main, renderCenter(scene));
    if (next) {
        attachPreviewMediaTransition(next.querySelector('.preview-media'), oldKey);
        const list2 = next.querySelector('.scene-timeline-list');
        if (list2) {
            list2.scrollLeft = scrollLeft;
            applyTimelineRatioVars(list2, state.workflowRatio || '16:9');
        }
        const grid2 = next.querySelector('.storyboard-grid');
        if (grid2) grid2.scrollTop = scrollTop;
        bindPreviewCanvasObserver();
        updatePlayheadPosition({ followScroll: false });
    }
    return Boolean(next);
}

/** 右侧候选 */
export function patchCandidates() {
    const scene = getCurrentScene();
    if (!scene) return false;
    const rightSidebar = document.querySelector('.right-sidebar');
    if (!rightSidebar) return false;
    const tmp = document.createElement('div');
    tmp.innerHTML = renderRightSidebar(scene);
    const newAside = tmp.querySelector('.right-sidebar');
    if (!newAside) return false;
    const nextSig = `${scene.id}|${scene.selectedFirstFrameId || ''}|${scene.selectedVideoId || ''}|${scene.firstFrameUrl || ''}|${scene.videoUrl || ''}|${JSON.stringify(state.sceneCandidates?.[scene.id] || null)}|${JSON.stringify(state.candidateUploadsBySceneId?.[scene.id] || null)}|${JSON.stringify(state.candidateDeletesBySceneId?.[scene.id] || null)}`;
    if (rightSidebar.dataset.candidateSig === nextSig) return true;
    rightSidebar.innerHTML = newAside.innerHTML;
    rightSidebar.dataset.candidateSig = nextSig;
    return true;
}

/**
 * 清掉预览区残留层：empty 状态字 / buffering 遮罩 / 多余 media。
 * 历史 bug：empty 不是 .preview-media，切到有图分镜时只 insert 不 remove → 中间残留「等待…」等文案。
 * stage / caption / subtitle 外壳保留。
 */
function clearPreviewMediaLayers(wrapper) {
    if (!wrapper) return;
    // preview-media-stack 含 img + 涂色工具条，需整层移除
    wrapper.querySelectorAll(
        '.preview-media-stack, .preview-media, .preview-empty, .preview-buffering, .preview-image-toolbar'
    ).forEach((node) => {
        try {
            node.remove();
        } catch {
            // ignore
        }
    });
    const sub = wrapper.querySelector('.preview-subtitle');
    if (sub) {
        sub.hidden = true;
        sub.textContent = '';
    }
}

/**
 * 主预览局部更新：busy 时只改 caption；否则优先改 src，必要时换媒体子节点。
 */
export function patchPreview(scene, options = {}) {
    const { force = false } = options;
    const wrapper = document.querySelector('.preview-wrapper');
    if (!wrapper || !scene) return false;

    const stage = ensurePreviewStage(wrapper);
    const mount = stage || wrapper;

    const previewMedia = choosePreviewMedia(scene);
    const nextKey = previewMedia.kind === 'video'
        ? `VIDEO|${previewMedia.url}`
        : (previewMedia.kind === 'image' ? `IMG|${previewMedia.url}` : '');
    const media = wrapper.querySelector('.preview-media');
    const oldKey = previewMediaKey(media);
    // 是否存在 empty/buffering 残留（即使已有 media 也要清）
    const hasStaleOverlay = Boolean(
        wrapper.querySelector('.preview-empty, .preview-buffering')
    );

    const setCaption = () => {
        const captionEl = wrapper.querySelector('.preview-caption');
        if (!captionEl) return;
        const strong = captionEl.querySelector('strong');
        const span = captionEl.querySelector('span');
        if (strong) strong.textContent = scene.title || '';
        if (span) span.textContent = scene.durationLabel || '';
    };

    if (isPreviewMediaBusy() && !force) {
        setCaption();
        return true;
    }

    // 切镜 force：始终清字幕残留
    if (force) {
        const sub = wrapper.querySelector('.preview-subtitle');
        if (sub) {
            sub.hidden = true;
            sub.textContent = '';
        }
    }

    if (oldKey && nextKey && oldKey === nextKey && !force && !hasStaleOverlay) {
        setCaption();
        applyPreviewCanvas(wrapper);
        return true;
    }

    // 同类型优先改 src，避免销毁节点；但若有 empty 残留仍须清层
    if (
        media && media.tagName === 'VIDEO' && previewMedia.kind === 'video' && oldKey.startsWith('VIDEO|')
        && !hasStaleOverlay
    ) {
        const url = String(previewMedia.url).trim();
        if (media.getAttribute('src') !== url && media.src !== url) {
            media.src = url;
            try { media.load(); } catch { /* ignore */ }
        }
        setCaption();
        applyPreviewCanvas(wrapper);
        return true;
    }
    if (
        media && media.tagName === 'IMG' && previewMedia.kind === 'image'
        && oldKey.startsWith('IMG|') && !hasStaleOverlay
    ) {
        const url = String(previewMedia.url).trim();
        if (media.getAttribute('src') !== url) media.src = url;
        setCaption();
        applyPreviewCanvas(wrapper);
        return true;
    }

    // 类型变化 / empty↔媒体 / 有残留层：整层替换媒体区，挂到 stage 内、subtitle 前
    clearPreviewMediaLayers(wrapper);
    const html = mediaFrame(scene);
    const tmp = document.createElement('div');
    tmp.innerHTML = html.trim();
    const newMedia = tmp.firstElementChild;
    if (!newMedia) return false;
    const subEl = mount.querySelector('.preview-subtitle');
    if (subEl) {
        mount.insertBefore(newMedia, subEl);
    } else {
        mount.appendChild(newMedia);
    }
    if (!mount.querySelector('.preview-subtitle')) {
        const sub = document.createElement('div');
        sub.className = 'preview-subtitle';
        sub.hidden = true;
        mount.appendChild(sub);
    }
    if (!wrapper.querySelector('.preview-caption')) {
        const cap = document.createElement('div');
        cap.className = 'preview-caption';
        cap.innerHTML = `<strong></strong><span></span>`;
        wrapper.appendChild(cap);
    }
    setCaption();
    attachPreviewMediaTransition(wrapper.querySelector('.preview-media'), oldKey);
    applyPreviewCanvas(wrapper);
    return true;
}

const MODAL_SCROLL_SELECTORS = ['.generate-from-script-dialog .gfs-body'];

/** 拆分弹窗：只切换分镜图生成模式卡片的选中态，避免整窗重建把滚动拉回顶部。 */
export function syncSequenceModeIntroCards(root = document) {
    const selected = state.autoImageSequenceMode;
    root.querySelectorAll('[data-action="set-auto-image-sequence-mode"]').forEach((card) => {
        card.classList.toggle('active', card.dataset.autoImageSequenceMode === selected);
    });
}

/** 弹层容器：不碰 app-shell */
export function syncModals() {
    const app = document.getElementById('app');
    if (!app) return false;
    let host = app.querySelector('[data-region="modals"]');
    if (!host) {
        host = document.createElement('div');
        host.dataset.region = 'modals';
        host.className = 'storyboard-modals';
        app.appendChild(host);
    }
    const savedScrolls = MODAL_SCROLL_SELECTORS.map((selector) => {
        const el = host.querySelector(selector);
        return el ? { selector, top: el.scrollTop, left: el.scrollLeft } : null;
    }).filter(Boolean);
    host.innerHTML = renderModalsHtml();
    savedScrolls.forEach(({ selector, top, left }) => {
        const el = host.querySelector(selector);
        if (!el) return;
        el.scrollTop = top;
        el.scrollLeft = left;
    });
    return true;
}

function patchTimelineChrome() {
    updateTimelineProgress();
    // 字幕勾选（action 名称为 toggle-subtitle）
    const cb = document.querySelector(
        '.timeline-progress-row input[type="checkbox"][data-action="toggle-subtitle"]'
    );
    if (cb) cb.checked = Boolean(state.subtitleEnabled);
    return true;
}

/**
 * 时间轴 list / grid：
 * - 分镜 id 序列未变：单卡 thumb + 选中态
 * - 序列变了（增删/插镜）：结构重建，**不**拆 preview
 */
function patchTimelineListOrGrid() {
    const sig = scenesStructureSig();
    if (state.viewMode === 'grid') {
        const grid = document.querySelector('.storyboard-grid');
        if (!grid) return patchCenter();
        if (grid.dataset.scenesSig !== sig) {
            return patchGridStructure();
        }
        let n = 0;
        (state.scenes || []).forEach((sc) => {
            if (updateSceneThumb(sc)) n += 1;
        });
        syncTimelineSelectionActive();
        updateAutoCompleteHeader();
        return n >= 0;
    }

    const list = document.querySelector('.scene-timeline-list');
    if (!list) {
        // 当前可能是 grid 或壳未齐
        if (document.querySelector('.storyboard-grid')) return patchGridStructure();
        return false;
    }
    if (list.dataset.scenesSig !== sig) {
        return patchTimelineListStructure();
    }
    applyTimelineRatioVars(list, state.workflowRatio || '16:9');
    let n = 0;
    (state.scenes || []).forEach((sc) => {
        if (updateSceneThumb(sc)) n += 1;
    });
    syncTimelineSelectionActive();
    updateAutoCompleteHeader();
    updatePlayheadPosition({ followScroll: false });
    return n >= 0;
}

/**
 * 分区刷新主入口。
 * @param {string|string[]|'all'} [regions='all']
 * @param {{ forcePreview?: boolean }} [options]
 */
export function refresh(regions = 'all', options = {}) {
    const app = document.getElementById('app');
    if (!app) return;

    if (state.error) {
        app.innerHTML = `<div class="storyboard-error"><h1>故事板打开失败</h1><p>${escapeHtml(state.error)}</p><button class="btn-primary" data-route="script">返回剧本策划</button></div>`;
        return;
    }

    // 比例门禁：仅渲染确认弹窗，不进入完整编辑器
    if (state.ratioGateActive) {
        onDomWillRerender();
        app.innerHTML = `
            <div class="storyboard-ratio-gate">
                <div class="storyboard-loading">
                    <div class="loading-mark">智</div>
                    <div>请先选择视频比例…</div>
                </div>
            </div>
            <div class="storyboard-modals" data-region="modals">${renderRatioConfirmDialog()}</div>`;
        return;
    }

    const set = normalizeRegions(regions);
    const shellReady = Boolean(app.querySelector('.app-shell'));

    // 无壳或请求 all：全量（仍受 preview busy 保护）
    if (!shellReady || set.has('all')) {
        if (isPreviewMediaBusy() && !options.forcePreview) {
            softRefreshUiWhilePreviewBusy();
            // busy 时仍允许刷弹层（导出等）
            if (set.has(Region.MODAL) || set.has('all')) syncModals();
            return;
        }
        renderAppFull();
        return;
    }

    // 播放保护：剔除 PREVIEW；CENTER 会拆 preview，一并剔除
    if (isPreviewMediaBusy() && !options.forcePreview) {
        set.delete(Region.PREVIEW);
        set.delete(Region.CENTER);
    }

    const scene = getCurrentScene();
    for (const r of set) {
        switch (r) {
            case Region.HEADER_POWER:
                patchHeaderPower();
                break;
            case Region.HEADER:
                patchHeader();
                break;
            case Region.AGENT_LOG:
                patchAgentChatLog();
                break;
            case Region.AGENT_PANEL:
            case Region.AGENT_COMPOSER:
                patchAgentPanel();
                break;
            case Region.LEFT_SIDEBAR:
                patchLeftSidebar();
                break;
            case Region.SCENE_CHROME:
            case Region.LEFT_TABS:
            case Region.LEFT_TAB_BODY:
                // 只刷工作台，避免重挂助手导致输入框/历史被拆
                patchLeftWorkspace();
                break;
            case Region.CANDIDATES:
                patchCandidates();
                break;
            case Region.PREVIEW:
                patchPreview(scene, { force: Boolean(options.forcePreview) });
                break;
            case Region.CENTER:
                patchCenter();
                break;
            case Region.TIMELINE_CHROME:
                patchTimelineChrome();
                break;
            case Region.TIMELINE_LIST:
            case Region.GRID:
                patchTimelineListOrGrid();
                break;
            case Region.MODAL:
                syncModals();
                break;
            default:
                break;
        }
    }
}

/** 兼容旧名：等价 refresh('all') */
export function renderApp() {
    refresh('all');
}

/** 真正的整页重建（仅 refresh all / 首屏 / 错误恢复） */
function renderAppFull() {
    const app = document.getElementById('app');
    const scene = getCurrentScene();
    if (!app) return;

    onDomWillRerender();

    const scrollSelectors = [
        { selector: '.scene-timeline-list', prop: 'scrollLeft' },
        { selector: '.storyboard-grid', prop: 'scrollTop' },
        { selector: '.right-sidebar', prop: 'scrollTop' },
        { selector: '.sidebar-content', prop: 'scrollTop' },
        { selector: '.agent-chat-log', prop: 'scrollTop' },
    ];
    const savedScrolls = [];
    scrollSelectors.forEach(({ selector, prop }) => {
        const el = document.querySelector(selector);
        if (el) savedScrolls.push({ selector, prop, value: el[prop] });
    });
    const prevAgentLog = document.querySelector('.agent-chat-log');
    const agentLogWasAtBottom = prevAgentLog
        ? (prevAgentLog.scrollHeight - prevAgentLog.scrollTop - prevAgentLog.clientHeight) < 48
        : true;

    const oldPreviewKey = previewMediaKey(document.querySelector('.preview-media'));

    app.innerHTML = `
        <div class="app-shell">
            ${renderHeader()}
            <div class="main-layout">
                ${renderLeftSidebar(scene)}
                ${renderCenter(scene)}
                ${renderRightSidebar(scene)}
            </div>
        </div>
        <div class="storyboard-modals" data-region="modals">${renderModalsHtml()}</div>`;

    attachPreviewMediaTransition(app.querySelector('.preview-media'), oldPreviewKey);
    // 时间轴比例 + 主预览逻辑画布
    applyTimelineRatioVars(
        app.querySelector('.scene-timeline-list'),
        state.workflowRatio || '16:9'
    );
    bindPreviewCanvasObserver();

    requestAnimationFrame(() => {
        savedScrolls.forEach(({ selector, prop, value }) => {
            const el = document.querySelector(selector);
            if (el) el[prop] = value;
        });
        const agentLog = document.querySelector('.agent-chat-log');
        if (agentLog && (isSceneAgentRunning(state.currentSceneId) || agentLogWasAtBottom) && state.agentChatHistoryOpen !== false) {
            agentLog.scrollTop = agentLog.scrollHeight;
        }
        updatePlayheadPosition({ followScroll: false });
        applyPreviewCanvas();
    });
}

// ==================== 局部更新 API（供 polling 局部刷新，避免全量重建抢焦点/抖动）====================
// 设计原则：只更新由 applyTaskStatus 真正改动的区域；保留用户正在交互的控件（输入框焦点、滚动位置）。

// 生成单个分镜的时间线缩略图按钮 innerHTML（不含外层 button）。
function renderTimelineThumbInner(scene) {
    const statusClass = getFirstFrameDisplayStatus(scene) === 'ready'
        ? ''
        : ' has-first-frame-status';
    return `${renderTimelineMediaFrame(scene)}
                    <div class="scene-timeline-id-badge${statusClass}">${escapeHtml(scene.title)}</div>
                    <div class="scene-timeline-meta">${icon('play', 14)} <b>${escapeHtml(scene.durationLabel)}</b></div>`;
}

// 生成单个分镜的 grid 卡片 outerHTML（cell 整块，与 renderGridInner 一致）。
function renderStoryboardCardOuter(scene) {
    const idx = state.scenes.indexOf(scene);
    const nextScene = idx >= 0 ? state.scenes[idx + 1] : null;
    return renderStoryboardCardCell(scene, nextScene);
}

// 生成单个 dialogue 行 outerHTML（供局部更新单条对话的 audio 控件，避免触碰其他正在编辑的行）。
// 需与 renderDialoguePanel 内的行模板保持一致。
function renderDialogueRowOuter(d) {
    const characterOptions = '<option value="">旁白</option>' + state.characters.map(c =>
        `<option value="${c.id}" ${d.characterId === c.id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
    ).join('');
    return `
            <div class="dialogue-row" data-dialogue-row data-dialogue-id="${d.id}">
                <select class="dialogue-character" data-dialogue-field="characterId">${characterOptions}</select>
                <textarea class="dialogue-text" data-dialogue-field="text" placeholder="台词">${escapeHtml(d.text)}</textarea>
                <div class="dialogue-meta">
                    <label class="meta-field">语速<input type="number" step="0.1" data-dialogue-field="speed" value="${d.speed ?? 1.0}"></label>
                    <label class="meta-field">音量<input type="number" step="0.1" data-dialogue-field="volume" value="${d.volume ?? 100}"></label>
                </div>
                ${renderDialogueAudioBlock(d)}
                <div class="dialogue-actions">
                    ${renderDialogueEmoSummary(d)}
                    ${renderGenerateVoiceoverBtn(d)}
                    <button class="tool-button" data-action="save-dialogue" data-dialogue-id="${d.id}">${icon('success', 14)} 保存</button>
                    <button class="tool-button" data-action="delete-dialogue" data-dialogue-id="${d.id}">${icon('delete', 14)}</button>
                </div>
            </div>`;
}

function renderEmoVecEditorDialog() {
    const editor = state.emoVecEditor || {};
    if (!editor.open) return '';
    const values = Array.isArray(editor.values) ? editor.values : parseEmoVec(null);
    const sum = values.reduce((a, b) => a + Number(b || 0), 0);
    const valid = sum <= EMO_VEC_MAX_SUM + 1e-6;
    const autoAiOn = Boolean(state.serverFeatures?.dialogue_emotion_tts);
    const sliders = EMO_VEC_LABELS.map((label, idx) => {
        const v = Number(values[idx] || 0);
        return `
            <div class="emo-vec-slider-row" data-emo-idx="${idx}">
                <div class="emo-vec-slider-head">
                    <span class="emo-vec-label">${escapeHtml(label)}</span>
                    <span class="emo-vec-value" data-emo-value="${idx}">${v.toFixed(2)}</span>
                </div>
                <input type="range" min="0" max="1.5" step="0.01"
                    value="${v}"
                    data-emo-slider="${idx}"
                    class="emo-vec-range" />
            </div>`;
    }).join('');
    const errHtml = editor.error
        ? `<div class="dialog-error">${escapeHtml(editor.error)}</div>`
        : '';
    const saveLabel = editor.saving ? '保存中…' : '保存';
    return `
        <div class="modal-overlay" data-modal="emo-vec-editor">
            <div class="edit-dialog emo-vec-dialog" role="dialog" aria-modal="true" aria-labelledby="emo-vec-title">
                <header>
                    <h2 id="emo-vec-title">配音情感向量</h2>
                    <button type="button" data-action="close-emo-vec-editor" title="关闭">${icon('close', 18)}</button>
                </header>
                <div class="emo-vec-body">
                    <p class="emo-vec-hint">
                        控制本句对白生成配音时的情感色彩（8 维，总和 ≤ ${EMO_VEC_MAX_SUM}）。
                        保存后再次「生成配音」将按此向量提交（企业版生效）。
                    </p>
                    <div class="emo-vec-enterprise-note ${autoAiOn ? 'is-active' : ''}">
                        ${autoAiOn
                            ? '当前环境已启用企业版能力：剧本拆分时 AI 可自动为对白填写情感向量。'
                            : '说明：所有用户均可查看与手动编辑。仅<strong>企业版</strong>支持在剧本拆分时由 AI 自动推断情感向量，并在自动配音中应用。'}
                    </div>
                    <div class="emo-vec-sliders">
                        ${sliders}
                    </div>
                    <div class="emo-vec-sum ${valid ? 'ok' : 'bad'}">
                        总和：<strong data-emo-sum>${sum.toFixed(2)}</strong> / ${EMO_VEC_MAX_SUM}
                        ${valid ? '' : '<span class="emo-vec-warn"> 超出上限，请调低</span>'}
                    </div>
                    ${errHtml}
                </div>
                <footer class="dialog-footer">
                    <button type="button" class="btn-ghost" data-action="reset-emo-vec-editor">清零</button>
                    <button type="button" class="btn-ghost" data-action="close-emo-vec-editor">取消</button>
                    <button type="button" class="btn-primary" data-action="save-emo-vec-editor"
                        ${editor.saving || !valid ? 'disabled' : ''}>${saveLabel}</button>
                </footer>
            </div>
        </div>`;
}


// ==================== 对外局部更新函数（polling 调用）====================

// 更新时间线/grid 中某分镜的缩略图。仅当该分镜在当前视图中存在时才更新。
// 返回 true 表示执行了更新。
export function updateSceneThumb(scene) {
    if (!scene) return false;
    let updated = false;
    const nextUrl = scene.firstFrameUrl || '';
    const nextStatus = getFirstFrameDisplayStatus(scene);
    const mediaSig = `${nextUrl}|${nextStatus}|${scene.durationLabel || ''}`;

    // timeline 模式：替换 thumb 按钮内部内容（保留按钮本身，不破坏 active 态与滚动）
    const thumbBtn = document.querySelector(`.scene-timeline-thumb[data-scene="${scene.id}"]`);
    if (thumbBtn) {
        // 媒体签名未变时跳过 innerHTML，避免 img 重复加载导致「闪一下」
        if (thumbBtn.dataset.mediaSig === mediaSig) {
            updated = true;
        } else {
            thumbBtn.innerHTML = renderTimelineThumbInner(scene);
            thumbBtn.dataset.mediaSig = mediaSig;
            updated = true;
        }
    }

    // grid 模式：替换整张卡片（含缩略图/角标）
    const card = document.querySelector(`.storyboard-card[data-scene="${scene.id}"]`);
    if (card) {
        const cell = card.closest('.storyboard-grid-cell');
        if (cell) {
            if (cell.dataset.mediaSig === mediaSig && cell.dataset.sceneId === String(scene.id)) {
                updated = true;
            } else {
                cell.outerHTML = renderStoryboardCardOuter(scene);
                const nextCell = document.querySelector(`.storyboard-card[data-scene="${scene.id}"]`)?.closest('.storyboard-grid-cell');
                if (nextCell) {
                    nextCell.dataset.mediaSig = mediaSig;
                    nextCell.dataset.sceneId = String(scene.id);
                }
                updated = true;
            }
        }
    }
    return updated;
}

// 更新中央主预览 + 右侧候选网格。仅当 scene 为当前选中分镜时才更新。
// 返回 true 表示执行了更新。timeline 与 grid 两种模式都处理主预览（grid 模式主预览不存在则跳过）。
export function updateCurrentSceneDetail(scene) {
    if (!scene || scene.id !== state.currentSceneId) return false;
    let updated = false;

    // 中央主预览（仅 timeline 模式存在 .preview-wrapper）
    // 时间轴试看 / 原生 controls 播放中：禁止 innerHTML 拆掉 video（仅可改 caption 文本）
    const previewWrapper = document.querySelector('.preview-wrapper');
    const previewBusy = isPreviewMediaBusy();
    if (previewWrapper && previewBusy) {
        const captionEl = previewWrapper.querySelector('.preview-caption');
        if (captionEl) {
            const strong = captionEl.querySelector('strong');
            const span = captionEl.querySelector('span');
            if (strong) strong.textContent = scene.title || '';
            if (span) span.textContent = scene.durationLabel || '';
        }
        updated = true;
    } else if (previewWrapper && !previewBusy) {
        const oldKey = previewMediaKey(previewWrapper.querySelector('.preview-media'));
        const previewMedia = choosePreviewMedia(scene);
        const nextKey = previewMedia.kind === 'video'
            ? `VIDEO|${previewMedia.url}`
            : (previewMedia.kind === 'image' ? `IMG|${previewMedia.url}` : '');
        const captionEl = previewWrapper.querySelector('.preview-caption');
        const oldCaption = captionEl
            ? `${captionEl.querySelector('strong')?.textContent || ''}|${captionEl.querySelector('span')?.textContent || ''}`
            : '';
        const nextCaption = `${scene.title || ''}|${scene.durationLabel || ''}`;
        // 主媒体与标题未变：跳过重建，避免轮询导致主预览反复闪烁
        if (oldKey && nextKey && oldKey === nextKey && oldCaption === nextCaption) {
            applyPreviewCanvas(previewWrapper);
            updated = true;
        } else {
            // 走 patchPreview，保留 preview-stage 外壳与逻辑画布
            patchPreview(scene, { force: true });
            updated = true;
        }
    }

    // 右侧候选网格（无输入控件，整块替换安全；可用签名跳过无变化刷新）
    const rightSidebar = document.querySelector('.right-sidebar');
    if (rightSidebar) {
        const tmp = document.createElement('div');
        tmp.innerHTML = renderRightSidebar(scene);
        const newAside = tmp.querySelector('.right-sidebar');
        if (newAside) {
            const nextHtml = newAside.innerHTML;
            const nextSig = `${scene.id}|${scene.selectedFirstFrameId || ''}|${scene.selectedVideoId || ''}|${scene.firstFrameUrl || ''}|${scene.videoUrl || ''}|${JSON.stringify(state.sceneCandidates?.[scene.id] || null)}|${JSON.stringify(state.candidateUploadsBySceneId?.[scene.id] || null)}|${JSON.stringify(state.candidateDeletesBySceneId?.[scene.id] || null)}`;
            if (rightSidebar.dataset.candidateSig !== nextSig) {
                rightSidebar.innerHTML = nextHtml;
                rightSidebar.dataset.candidateSig = nextSig;
            }
            updated = true;
        }
    }
    return updated;
}

// 更新某条 dialogue 行的 audio 控件（仅在当前选中分镜 + 对话 Tab 时）。
// 按 dialogue 行粒度替换，避免触碰用户正在编辑的其他行。返回 true 表示更新了。
export function updateDialogueRow(scene, dialogueId) {
    if (!scene || scene.id !== state.currentSceneId || state.activeTab !== 'dialogue') return false;
    const dialogue = (scene.dialogues || []).find(d => d.id === dialogueId);
    if (!dialogue) return false;
    const row = document.querySelector(`.dialogue-row[data-dialogue-id="${dialogueId}"]`);
    if (!row) return false;
    row.outerHTML = renderDialogueRowOuter(dialogue);
    return true;
}

// 刷新时间线进度行的总时长文本。
// getTotalDuration() 由各 scene.duration 求和得出，某分镜 duration 因音频完成同步而变化后，
// 进度行 span 不会随 updateSceneThumb/updateCurrentSceneDetail 自动重渲（仅全量 renderApp 才刷新），
// 因此需在轮询局部更新里显式调用本函数。返回 true 表示更新了。
export function updateTimelineProgress() {
    // 必须用 .timeline-time，禁止 `.timeline-progress-row span`：
    // 后者会命中 .play-btn 内 icon() 生成的 .sb-icon，把时间写进播放按钮。
    const span = document.querySelector('.timeline-progress-row .timeline-time');
    if (!span) return false;
    span.textContent = `${formatDuration(state.currentTime)} / ${formatDuration(getTotalDuration())}`;
    // duration 变化后重算 playhead 映射
    updatePlayheadPosition({ followScroll: false });
    return true;
}

export function updateAutoCompleteHeader() {
    let updated = false;
    const gridHeader = document.querySelector('.center-panel > .auto-complete-header');
    if (gridHeader && state.viewMode === 'grid') {
        gridHeader.outerHTML = renderAutoCompleteHeader('故事板总览', renderGridHeaderActions());
        updated = true;
    }
    const timelineHeader = document.querySelector('.scene-timeline > .auto-complete-header');
    if (timelineHeader) {
        timelineHeader.outerHTML = renderAutoCompleteHeader('分镜序列');
        updated = true;
    }
    return updated;
}
