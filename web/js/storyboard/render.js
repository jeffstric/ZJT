import state, { getCurrentScene, getTotalDuration } from './state.js';
import { formatDuration, mapAssetAvatar } from './adapters.js';
import { icon } from './icons.js';
import { t as i18nT } from './utils.js';

// 确保 i18n 在首次 render 前已初始化（bootstrap 中已调用 initI18n）

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
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
export function renderPromptWithInlineRoles(text, usedChars, usedProps) {
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

export function mediaFrame(scene) {
    if (!scene) {
        return '<div class="preview-empty">选择一个分镜开始编辑</div>';
    }
    if (scene.videoUrl) {
        return `<video src="${escapeHtml(scene.videoUrl)}" controls class="preview-media"></video>`;
    }
    if (scene.firstFrameUrl) {
        return `<img src="${escapeHtml(scene.firstFrameUrl)}" alt="${escapeHtml(scene.title)}" class="preview-media">`;
    }
    return '<div class="preview-empty">当前分镜还没有画面</div>';
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

function renderHeader() {
    const power = state.computingPower == null ? '--' : state.computingPower;
    return `
        <header class="header">
            <div class="header-left">
                <img src="/files/logo.svg" alt="Logo" class="header-logo-img" data-route="storyboard-list">
                <div>
                    <h1 class="header-title">${escapeHtml(state.title)}</h1>
                    <div class="header-subtitle">
                        <span>第${state.episodeNumber}集 · </span>
                        <select class="header-ratio-select" data-ratio-select title="点击切换画面比例">
                            ${['9:16','3:4','1:1','4:3','16:9'].map(r => 
                                `<option value="${r}" ${state.workflowRatio === r ? 'selected' : ''}>${r}</option>`
                            ).join('')}
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
                <span class="header-badge">算力 ${power}</span>
                <button class="btn-primary" data-action="export-full">一键转视频</button>
                <button class="btn-ghost" data-action="open-export">导出</button>
            </div>
        </header>`;
}

function renderScenePanel(scene) {
    const prompt = scene.promptJson || {};

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
        locationHtml = `<span class="asset-chip" data-action="switch-location" data-scene-id="${scene.id}" title="点击切换场景">
            ${locImg ? `<img src="${escapeHtml(getThumbnailUrl(locImg, 24))}" alt="">` : ''}
            ${escapeHtml(loc.name || '场景')}
            <span class="remove-x" data-action="remove-location" data-scene-id="${scene.id}" title="移除">×</span>
        </span>`;
    } else {
        locationHtml = `<span class="asset-chip add" data-action="switch-location" data-scene-id="${scene.id}">+ 选择场景</span>`;
    }

    return `
        <div class="tab-panel">
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
                    <div class="prompt-display" data-prompt-type="scene" data-scene-id="${scene.id}" style="border:1px solid #ccc; padding:8px; border-radius:4px; background:#fff; min-height:80px; white-space:pre-wrap; font-size:12px; cursor:text; overflow:auto;">${renderPromptWithInlineRoles(prompt.scene_desc || '', allChars, state.props)}</div>
                </div>
            </div>

            <div class="info-card">
                <div class="info-card-header">
                    <div class="info-card-title">${icon('image', 18)} 视频提示词（${escapeHtml(scene.videoType || 'video')}）</div>
                </div>
                <div class="info-card-body">
                    <div style="font-size:10px;color:#9ca3af;margin-bottom:2px;">提示：输入 @ 可插入角色或道具</div>
                    <div class="prompt-display" data-prompt-type="video" data-scene-id="${scene.id}" style="border:1px solid #ccc; padding:8px; border-radius:4px; background:#fff; min-height:80px; white-space:pre-wrap; font-size:12px; cursor:text; overflow:auto;">${renderPromptWithInlineRoles(scene.videoPrompt || '', allChars, state.props)}</div>
                </div>
            </div>
        </div>`;
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
                ${d.audioUrl ? `<audio src="${escapeHtml(d.audioUrl)}" controls class="dialogue-audio"></audio>` : ''}
                <div class="dialogue-actions">
                    <button class="tool-button" data-action="generate-voiceover" data-dialogue-id="${d.id}">${icon('mic', 14)} 生成配音</button>
                    <button class="tool-button" data-action="save-dialogue" data-dialogue-id="${d.id}">${icon('success', 14)} 保存</button>
                    <button class="tool-button" data-action="delete-dialogue" data-dialogue-id="${d.id}">${icon('delete', 14)}</button>
                </div>
            </div>`;
    }).join('');

    return `
        <div class="tab-panel dialogue-panel">
            ${rows || '<div class="empty-note">还没有对话，点击下方添加。</div>'}
            <button class="panel-button" data-action="add-dialogue">${icon('add', 16)} 添加对话</button>
        </div>`;
}

function renderTabs(scene) {
    if (!scene) {
        return '<div class="empty-note">暂无分镜。可以从底部添加一个新分镜。</div>';
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

function renderAiPanel() {
    const scene = getCurrentScene();
    const modes = [
        ['dialogue', '对话改图', '选择对话模型后，可让智能体基于当前画面提示词生成或调整首帧'],
        ['video', '视频生成', '选择对话模型和视频模型后，可让智能体基于当前分镜生成视频'],
    ].map(([key, label, title]) => `<option value="${key}" ${state.chatMode === key ? 'selected' : ''} title="${title}">${label}</option>`).join('');

    const agentMessages = renderAgentMessages();
    const disabled = state.isAgentRunning ? 'disabled' : '';
    const placeholder = state.chatMode === 'dialogue'
        ? '和智能体描述要如何调整当前分镜画面'
        : '和智能体描述要如何生成当前分镜视频';

    // 视频生成模式下渲染补充参考图预览条（首帧图由该分镜选中首帧自动提供，此处仅展示用户上传的补充图）
    const referenceBar = state.chatMode === 'video' ? renderReferenceBar(disabled) : '';

    return `
        <section class="ai-chat-section">
            <div class="ai-chat-header">${icon('send', 16)} 分镜助手</div>
            ${agentMessages}
            <div class="chat-textarea-row">
                <button class="reference-add-btn" data-action="add-reference-image" ${disabled} title="上传参考图">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 5v14M5 12h14"/>
                    </svg>
                </button>
                <input type="file" id="reference-file-input" class="reference-file-input" accept="image/*" multiple hidden>
                <textarea id="chat-textarea" class="chat-textarea" placeholder="${placeholder}" ${disabled}>${escapeHtml(state.inputMessage)}</textarea>
            </div>
            ${referenceBar}
            <div class="chat-toolbar">
                <button class="tool-button" data-action="open-model-config" title="模型配置（对话模型按供应商分组，图片/视频模型按当前助手模式）">${icon('settings', 14)}</button>
                <select id="chat-mode-select" class="chat-mode-select">${modes}</select>
                <button class="tool-button" data-action="mention">@</button>
                <button class="chat-send-btn" data-action="send-ai" ${disabled}>${icon('send', 16)}</button>
            </div>
        </section>`;
}

function renderReferenceBar(disabled) {
    const thumbs = (state.referenceImages || []).map(img => {
        const src = img.uploading
            ? ''
            : escapeHtml(getThumbnailUrl(img.thumbnailUrl || img.url || '', 32));
        const name = escapeHtml(img.name || '');
        return `
            <div class="reference-thumb ${img.uploading ? 'uploading' : ''}" data-reference-id="${escapeHtml(img.id)}" title="${name}">
                <div class="reference-thumb-inner">
                    ${src ? `<img src="${src}" alt="${name}">` : '<div class="reference-placeholder"></div>'}
                    ${img.uploading ? `<div class="reference-spinner">${icon('loading', 14)}</div>` : ''}
                </div>
                <span class="reference-name">${name}</span>
                <button class="reference-remove" data-action="remove-reference-image" data-reference-id="${escapeHtml(img.id)}" title="移除">×</button>
            </div>`;
    }).join('');
    return `
        <div class="reference-bar">
            <div class="reference-thumbs">${thumbs}</div>
            <input type="file" id="reference-file-input" class="reference-file-input" accept="image/*" multiple hidden>
        </div>`;
}

function renderAgentMessages() {
    if (!state.agentMessages.length) {
        return '';
    }
    const rows = state.agentMessages.slice(-8).map(message => {
        const role = message.role || 'assistant';
        const label = role === 'user' ? '你' : (role === 'status' ? '状态' : '智能体');
        return `
            <div class="agent-chat-message ${escapeHtml(role)}">
                <span>${label}</span>
                <p>${escapeHtml(message.content || message.status || '')}</p>
            </div>`;
    }).join('');
    const running = state.isAgentRunning ? '<div class="agent-chat-running">正在处理当前分镜...</div>' : '';
    return `<div class="agent-chat-log">${rows}${running}</div>`;
}

function renderCenter(scene) {
    if (state.viewMode === 'grid') return renderStoryboardGrid();
    return `
        <main class="center-panel">
            <section class="preview-wrapper">
                ${mediaFrame(scene)}
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
    const cards = state.scenes.map((scene, index) => {
        const nextScene = state.scenes[index + 1];
        return `
            <div class="storyboard-grid-cell">
                <article class="storyboard-card ${state.currentSceneId === scene.id ? 'active' : ''}" data-scene="${scene.id}">
                    <div class="storyboard-thumb">${mediaFrame(scene)}</div>
                    <div class="storyboard-card-body">
                        <h3>${escapeHtml(scene.title)}</h3>
                        <p>${escapeHtml(scene.durationLabel)}</p>
                        <div class="card-status">${assetBadge(scene, 'first_frame', '图')} ${assetBadge(scene, 'video', '视频')} ${difficultyBadge(scene)}</div>
                        ${actNameTag(scene) ? `<div class="card-act-name">${actNameTag(scene)}</div>` : ''}
                        <div class="storyboard-card-actions">
                            <button data-action="duplicate-scene" data-id="${scene.id}">${icon('copy', 14)} 复制</button>
                            <button data-action="delete-scene" data-id="${scene.id}">${icon('delete', 14)} 删除</button>
                        </div>
                    </div>
                </article>
                ${nextScene ? renderInsertSceneSlot(scene, nextScene, 'grid') : ''}
            </div>`;
    }).join('');

    return `
        <main class="center-panel">
            <div class="storyboard-grid-header">
                <span>故事板总览</span>
                <button class="btn-ghost" data-action="toggle-view">${icon('list', 16)} 时间轴</button>
            </div>
            <div class="storyboard-grid">${cards}<button class="add-board-card" data-action="add-scene">${icon('add', 24)} 添加分镜</button></div>
        </main>`;
}

export function renderTimeline() {
    const scenes = state.scenes.map((scene, index) => {
        const nextScene = state.scenes[index + 1];
        return `
            <div class="scene-timeline-item">
                <button class="scene-timeline-thumb ${state.currentSceneId === scene.id ? 'active' : ''}" data-scene="${scene.id}">
                    ${scene.firstFrameUrl ? `<img src="${escapeHtml(scene.firstFrameUrl)}" alt="${escapeHtml(scene.title)}">` : '<span>无画面</span>'}
                    <b>${escapeHtml(scene.durationLabel)}</b>
                </button>
                <div class="scene-timeline-actions">
                    <button data-action="duplicate-scene" data-id="${scene.id}" title="复制">${icon('copy', 14)}</button>
                    <button data-action="delete-scene" data-id="${scene.id}" title="删除">${icon('delete', 14)}</button>
                </div>
            </div>
            ${nextScene ? renderInsertSceneSlot(scene, nextScene, 'timeline') : ''}`;
    }).join('');

    return `
        <section class="timeline-controls">
            <div class="timeline-progress-row">
                <button class="play-btn" data-action="toggle-play">${icon(state.isPlaying ? 'pause' : 'play', 18)}</button>
                <span>${formatDuration(state.currentTime)} / ${formatDuration(getTotalDuration())}</span>
                <label class="subtitle-toggle"><input type="checkbox" data-action="toggle-subtitle" ${state.subtitleEnabled ? 'checked' : ''}> 字幕</label>
                <button class="timeline-view-toggle" data-action="toggle-view">${icon('grid', 16)}</button>
            </div>
            <div class="scene-timeline">
                <div class="scene-timeline-header"><span>分镜序列</span></div>
                <div class="scene-timeline-list" data-ratio="${escapeHtml(state.workflowRatio || '16:9')}">${scenes}<button class="add-scene-btn" data-action="add-scene">${icon('add', 22)}</button></div>
            </div>
        </section>`;
}

export function renderRightSidebar(scene) {
    const candidates = state.sceneCandidates?.[scene?.id] || {};
    const imageCandidates = candidates.images || [];
    const videoCandidates = candidates.videos || [];

    // 回退：若尚未加载候选列表，用当前选中的 URL 展示
    const fallbackImages = [];
    if (scene?.firstFrameUrl) fallbackImages.push({ id: 'ff', url: scene.firstFrameUrl });
    if (scene?.lastFrameUrl) fallbackImages.push({ id: 'lf', url: scene.lastFrameUrl });
    const displayImages = imageCandidates.length ? imageCandidates : fallbackImages;

    const fallbackVideos = [];
    if (scene?.videoUrl) fallbackVideos.push({ id: 'vd', url: scene.videoUrl });
    const displayVideos = videoCandidates.length ? videoCandidates : fallbackVideos;

    const imageGrid = displayImages.length
        ? `<div class="candidate-grid">${displayImages.map(img => `
            <div class="candidate-thumb ${img.selected ? 'selected' : ''}" data-candidate-id="${img.id}" data-candidate-type="image">
                ${img.url
                    ? `<img src="${escapeHtml(img.url)}" alt="${escapeHtml(img.label || '分镜图')}">`
                    : '<div class="candidate-placeholder">生成中</div>'}
                ${img.label ? `<span class="candidate-label">${escapeHtml(img.label)}</span>` : ''}
            </div>`).join('')}</div>`
        : '<div class="candidate-empty">暂无分镜图候选</div>';

    const videoList = displayVideos.length
        ? `<div class="candidate-list">${displayVideos.map(vid => `
            <div class="candidate-video-item ${vid.selected ? 'selected' : ''}" data-candidate-id="${vid.id}" data-candidate-type="video">
                <video src="${escapeHtml(vid.url)}" controls></video>
            </div>`).join('')}</div>`
        : '<div class="candidate-empty">暂无视频候选</div>';

    return `
        <aside class="right-sidebar">
            <div class="candidate-section">
                <span class="section-title">分镜图候选</span>
                ${imageGrid}
            </div>
            <div class="candidate-section">
                <span class="section-title">视频候选</span>
                ${videoList}
            </div>
        </aside>`;
}

function renderExportDialog() {
    if (!state.showExportDialog) return '';
    return `
        <div class="modal-overlay">
            <div class="export-dialog">
                <header><h2>导出故事板</h2><button data-action="close-export">${icon('close', 18)}</button></header>
                <button class="export-option" data-action="export-full">导出完整视频</button>
                <button class="export-option" data-action="export-scenes">导出全部分镜</button>
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
        html += `<optgroup label="${iconStr} ${escapeHtml(v.vendor_name || vid)}">`;
        groups[vid].forEach(m => {
            const val = m.model || m.name || m.id || '';
            const label = m.name || m.model || val;
            const modelId = m.model_id || m.id || '';
            const vendorId = m.vendor_id || '';
            const sel = isSelectedScriptSplitModel(m) ? 'selected' : '';
            html += `<option value="${escapeHtml(val)}" data-model-id="${escapeHtml(modelId)}" data-vendor-id="${escapeHtml(vendorId)}" ${sel}>${escapeHtml(label)}</option>`;
        });
        html += '</optgroup>';
    });
    html += '</select></div>';
    return html;
}

// 渲染剧本拆分的高级选项：镜头组时长 + 3 个开关（与 video_workflow 剧本节点保持一致）
function renderScriptSplitOptions(disabled = false) {
    const durations = [5, 8, 10, 15];
    const curDuration = durations.includes(Number(state.maxGroupDuration)) ? Number(state.maxGroupDuration) : 15;
    const durationOptions = durations.map(d =>
        `<option value="${d}" ${d === curDuration ? 'selected' : ''}>${d}秒</option>`
    ).join('');
    const toggleItem = (action, label, checked) => `
        <label><input type="checkbox" data-action="${action}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}><span>${escapeHtml(label)}</span></label>`;
    return `
        <div class="generate-from-script-model">
            <label class="config-label">镜头组时长</label>
            <div class="config-hint">每个分镜组的最大总时长，超时会在同一场景内自动拆分</div>
            <div class="config-select-wrapper">
                <select class="chat-mode-select" data-config-select="maxGroupDuration" ${disabled ? 'disabled' : ''}>${durationOptions}</select>
            </div>
            <div class="config-label" style="margin-top:12px;">拆分选项</div>
            <div class="script-split-toggles">
                ${toggleItem('toggle-force-medium-shot', '对话禁止全景（使用近景/中景）', state.forceMediumShot !== false)}
                ${toggleItem('toggle-no-bg-music', '不生成背景音乐', state.noBgMusic !== false)}
                ${toggleItem('toggle-split-multi-dialogue', '拆分多人对话镜头（每人尽量一个镜头）', state.splitMultiDialogue === true)}
            </div>
        </div>`;
}

function renderGenerateFromScriptDialog() {
    if (!state.showGenerateFromScriptDialog) return '';
    const busy = state.isGeneratingFromScript;
    const splitModelConfig = renderScriptSplitModelConfig(busy);
    const imageModelConfig = renderImageModelConfig(busy);
    const splitOptionsConfig = renderScriptSplitOptions(busy);
    const autoImageModeButtons = `
        <button type="button" class="sequence-mode-button ${state.autoImageSequenceMode === 'balanced' ? 'active' : ''}" data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="balanced" ${busy ? 'disabled' : ''}>均衡</button>
        <button type="button" class="sequence-mode-button ${state.autoImageSequenceMode === 'quality' ? 'active' : ''}" data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="quality" ${busy ? 'disabled' : ''}>效果</button>
        <button type="button" class="sequence-mode-button ${state.autoImageSequenceMode === 'speed' ? 'active' : ''}" data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="speed" ${busy ? 'disabled' : ''}>速度</button>
    `;
    return `
        <div class="modal-overlay">
            <div class="export-dialog generate-from-script-dialog">
                <header>
                    <h2>当前故事板还没有分镜</h2>
                    <button data-action="generate-from-script-cancel" ${busy ? 'disabled' : ''}>${icon('close', 18)}</button>
                </header>
                <div class="empty-note">
                    是否根据本集剧本自动拆分并生成分镜、对话数据？
                    ${state.generateFromScriptError ? `<p class="dialog-error">${escapeHtml(state.generateFromScriptError)}</p>` : ''}
                </div>
                <div class="generate-from-script-model">
                    ${splitModelConfig}
                </div>
                <div class="generate-from-script-model">
                    ${imageModelConfig}
                </div>
                ${splitOptionsConfig}
                <div class="generate-from-script-model">
                    <label class="config-label">分镜图生成模式</label>
                    <div class="sequence-mode-control">${autoImageModeButtons}</div>
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
                    <button data-action="close-model-config">${icon('close', 18)}</button>
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
                    <button class="btn-ghost" data-action="close-model-config">关闭</button>
                    <div style="font-size:12px;color:var(--muted);">选择后自动应用到助手当前模式</div>
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
        html += `<optgroup label="${iconStr} ${escapeHtml(v.vendor_name || vid)}">`;
        groups[vid].forEach(m => {
            const val = m.model || m.name || m.id || '';
            const label = m.name || m.model || val;
            const modelId = m.model_id || m.id || '';
            const vendorId = m.vendor_id || '';
            const sel = isSelectedDialogueModel(m) ? 'selected' : '';
            html += `<option value="${escapeHtml(val)}" data-model-id="${escapeHtml(modelId)}" data-vendor-id="${escapeHtml(vendorId)}" ${sel}>${escapeHtml(label)}</option>`;
        });
        html += `</optgroup>`;
    });
    html += `</select></div>`;
    return html;
}

function renderImageModelConfig(disabled = false) {
    const models = state.textToImageModels.length ? state.textToImageModels : state.imageModels;
    let html = '<label class="config-label">生图模型</label><div class="config-hint">用于对话改图与图片生成</div><div class="config-select-wrapper"><select class="chat-mode-select" data-config-select="image"';
    if (disabled) html += ' disabled';
    html += '>';
    models.forEach(m => {
        const val = m.task_id;
        const sel = String(state.selectedImageTaskId) === String(val) ? 'selected' : '';
        html += `<option value="${val}" ${sel}>${escapeHtml(m.name)}</option>`;
    });
    html += '</select></div>';
    return html;
}

function renderVideoModelConfig() {
    const models = state.imageToVideoModels.length ? state.imageToVideoModels : state.videoModels;
    let html = '<label class="config-label">视频模型</label><div class="config-hint">用于图片生成视频</div><div class="config-select-wrapper"><select class="chat-mode-select" data-config-select="video">';
    models.forEach(m => {
        const val = m.task_id;
        const sel = String(state.selectedVideoTaskId) === String(val) ? 'selected' : '';
        html += `<option value="${val}" ${sel}>${escapeHtml(m.name)}</option>`;
    });
    html += '</select></div>';
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

function renderGenerateProgressDialog() {
    if (!state.showGenerateProgressDialog) return '';
    const steps = state.generateProgressSteps || [];
    const error = state.generateProgressError || '';
    const stepHtml = steps.map((step) => {
        const cls = step.status || 'pending';
        let iconHtml;
        let statusText;
        if (cls === 'completed') {
            iconHtml = icon('success', 16);
            statusText = '执行完毕';
        } else if (cls === 'running') {
            iconHtml = `<span class="spinner">${icon('loading', 16)}</span>`;
            statusText = '执行中';
        } else if (cls === 'failed') {
            iconHtml = icon('close', 16);
            statusText = '失败';
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
        <div class="modal-overlay">
            <div class="export-dialog generate-progress-dialog">
                <header>
                    <h2>正在生成分镜...</h2>
                    ${error ? `<button data-action="close-generate-progress">${icon('close', 18)}</button>` : ''}
                </header>
                <div class="progress-steps">
                    ${stepHtml}
                </div>
                ${error ? `<div class="generate-progress-error">${escapeHtml(error)}</div>` : ''}
                ${footer}
            </div>
        </div>`;
}

export function renderApp() {
    const app = document.getElementById('app');
    const scene = getCurrentScene();

    if (state.error) {
        app.innerHTML = `<div class="storyboard-error"><h1>故事板打开失败</h1><p>${escapeHtml(state.error)}</p><button class="btn-primary" data-route="script">返回剧本策划</button></div>`;
        return;
    }

    const scrollSelectors = [
        { selector: '.scene-timeline-list', prop: 'scrollLeft' },
        { selector: '.storyboard-grid', prop: 'scrollTop' },
        { selector: '.right-sidebar', prop: 'scrollTop' },
        { selector: '.sidebar-content', prop: 'scrollTop' },
    ];
    const savedScrolls = [];
    scrollSelectors.forEach(({ selector, prop }) => {
        const el = document.querySelector(selector);
        if (el) savedScrolls.push({ selector, prop, value: el[prop] });
    });

    // 记录旧的主预览媒体（img/video），用于重建后避免相同图片再次解码/绘制导致闪烁
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
        ${renderExportDialog()}
        ${renderGenerateFromScriptDialog()}
        ${renderGenerateProgressDialog()}
        ${renderMentionPopup()}
        ${renderModelConfigModal()}
        ${renderGlobalStyleDialog()}`;

    // 主图双缓冲：src 未变则立即显示（避免重建空白），src 变化则等加载后淡入
    attachPreviewMediaTransition(app.querySelector('.preview-media'), oldPreviewKey);

    requestAnimationFrame(() => {
        savedScrolls.forEach(({ selector, prop, value }) => {
            const el = document.querySelector(selector);
            if (el) el[prop] = value;
        });
    });
}

// ==================== 局部更新 API（供 polling 局部刷新，避免全量重建抢焦点/抖动）====================
// 设计原则：只更新由 applyTaskStatus 真正改动的区域；保留用户正在交互的控件（输入框焦点、滚动位置）。

// 生成单个分镜的时间线缩略图按钮 innerHTML（不含外层 button，仅 img/span + 时长）。
function renderTimelineThumbInner(scene) {
    return `${scene.firstFrameUrl ? `<img src="${escapeHtml(scene.firstFrameUrl)}" alt="${escapeHtml(scene.title)}">` : '<span>无画面</span>'}
                    <b>${escapeHtml(scene.durationLabel)}</b>`;
}

// 生成单个分镜的 grid 卡片 outerHTML（article 整张卡）。
function renderStoryboardCardOuter(scene) {
    const nextScene = state.scenes[state.scenes.indexOf(scene) + 1];
    return `
            <div class="storyboard-grid-cell">
                <article class="storyboard-card ${state.currentSceneId === scene.id ? 'active' : ''}" data-scene="${scene.id}">
                    <div class="storyboard-thumb">${mediaFrame(scene)}</div>
                    <div class="storyboard-card-body">
                        <h3>${escapeHtml(scene.title)}</h3>
                        <p>${escapeHtml(scene.durationLabel)}</p>
                        <div class="card-status">${assetBadge(scene, 'first_frame', '图')} ${assetBadge(scene, 'video', '视频')} ${difficultyBadge(scene)}</div>
                        ${actNameTag(scene) ? `<div class="card-act-name">${actNameTag(scene)}</div>` : ''}
                        <div class="storyboard-card-actions">
                            <button data-action="duplicate-scene" data-id="${scene.id}">${icon('copy', 14)} 复制</button>
                            <button data-action="delete-scene" data-id="${scene.id}">${icon('delete', 14)} 删除</button>
                        </div>
                    </div>
                </article>
                ${nextScene ? renderInsertSceneSlot(scene, nextScene, 'grid') : ''}
            </div>`;
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
                ${d.audioUrl ? `<audio src="${escapeHtml(d.audioUrl)}" controls class="dialogue-audio"></audio>` : ''}
                <div class="dialogue-actions">
                    <button class="tool-button" data-action="generate-voiceover" data-dialogue-id="${d.id}">${icon('mic', 14)} 生成配音</button>
                    <button class="tool-button" data-action="save-dialogue" data-dialogue-id="${d.id}">${icon('success', 14)} 保存</button>
                    <button class="tool-button" data-action="delete-dialogue" data-dialogue-id="${d.id}">${icon('delete', 14)}</button>
                </div>
            </div>`;
}

// ==================== 对外局部更新函数（polling 调用）====================

// 更新时间线/grid 中某分镜的缩略图。仅当该分镜在当前视图中存在时才更新。
// 返回 true 表示执行了更新。
export function updateSceneThumb(scene) {
    if (!scene) return false;
    let updated = false;

    // timeline 模式：替换 thumb 按钮内部内容（保留按钮本身，不破坏 active 态与滚动）
    const thumbBtn = document.querySelector(`.scene-timeline-thumb[data-scene="${scene.id}"]`);
    if (thumbBtn) {
        thumbBtn.innerHTML = renderTimelineThumbInner(scene);
        updated = true;
    }

    // grid 模式：替换整张卡片（含缩略图/角标）
    const card = document.querySelector(`.storyboard-card[data-scene="${scene.id}"]`);
    if (card) {
        const cell = card.closest('.storyboard-grid-cell');
        if (cell) {
            cell.outerHTML = renderStoryboardCardOuter(scene);
            updated = true;
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
    const previewWrapper = document.querySelector('.preview-wrapper');
    if (previewWrapper) {
        const oldKey = previewMediaKey(previewWrapper.querySelector('.preview-media'));
        // 重建 .preview-wrapper 内容（含 mediaFrame + caption），与 renderCenter 保持一致
        previewWrapper.innerHTML = `
                ${mediaFrame(scene)}
                <div class="preview-caption">
                    <strong>${escapeHtml(scene.title)}</strong>
                    <span>${escapeHtml(scene.durationLabel)}</span>
                </div>`;
        attachPreviewMediaTransition(previewWrapper.querySelector('.preview-media'), oldKey);
        updated = true;
    }

    // 右侧候选网格（无输入控件，整块替换安全）
    const rightSidebar = document.querySelector('.right-sidebar');
    if (rightSidebar) {
        // renderRightSidebar 返回 <aside>...</aside>，解析出其 innerHTML 写入现有容器，保留元素本身
        const tmp = document.createElement('div');
        tmp.innerHTML = renderRightSidebar(scene);
        const newAside = tmp.querySelector('.right-sidebar');
        if (newAside) rightSidebar.innerHTML = newAside.innerHTML;
        updated = true;
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
    const span = document.querySelector('.timeline-progress-row span');
    if (!span) return false;
    span.textContent = `${formatDuration(state.currentTime)} / ${formatDuration(getTotalDuration())}`;
    return true;
}
