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
        const namePattern = names.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
        const plainRe = new RegExp(`(?<!【【)(${namePattern})(?!】】)`, 'g');
        processedText = processedText.replace(plainRe, '【【$1】】');
    }

    // Unified pattern: 角色【【】】 或 道具〖〖〗〗
    const pattern = /【【([^】]+)】】|〖〖([^〗]+)〗〗/g;
    let match;
    while ((match = pattern.exec(processedText)) !== null) {
        if (match.index > lastIndex) {
            displayEl.appendChild(document.createTextNode(processedText.substring(lastIndex, match.index)));
        }
        const isProp = match[2] !== undefined;
        const assetName = (match[1] || match[2]).trim();
        const assetList = isProp ? worldProps : worldChars;
        const asset = assetList.find(a => String(a.name || '').trim() === assetName);
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

function mediaFrame(scene) {
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

function renderHeader() {
    const power = state.computingPower == null ? '--' : state.computingPower;
    return `
        <header class="header">
            <div class="header-left">
                <div class="header-logo">智</div>
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

    return `
        <aside class="left-sidebar">
            <div class="sidebar-content">
                <div class="project-info">
                    <div class="project-brand">
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
        ['dialogue', '对话改图'],
        ['video', '视频生成'],
    ].map(([key, label]) => `<option value="${key}" ${state.chatMode === key ? 'selected' : ''}>${label}</option>`).join('');

    const agentMessages = renderAgentMessages();
    const disabled = state.isAgentRunning ? 'disabled' : '';
    const placeholder = state.chatMode === 'dialogue'
        ? '和智能体描述要如何调整当前分镜画面'
        : '和智能体描述要如何生成当前分镜视频';

    return `
        <section class="ai-chat-section">
            <div class="ai-chat-header">${icon('send', 16)} 分镜助手</div>
            ${agentMessages}
            <textarea id="chat-textarea" class="chat-textarea" placeholder="${placeholder}" ${disabled}>${escapeHtml(state.inputMessage)}</textarea>
            <div class="chat-toolbar">
                <button class="tool-button" data-action="open-model-config" title="模型配置（对话模型按供应商分组，图片/视频模型按当前助手模式）">${icon('settings', 14)}</button>
                <select id="chat-mode-select" class="chat-mode-select">${modes}</select>
                <button class="tool-button" data-action="mention">@</button>
                <button class="chat-send-btn" data-action="send-ai" ${disabled}>${icon('send', 16)}</button>
            </div>
        </section>`;
}

function renderAgentMessages() {
    if (!state.agentMessages.length) {
        return state.chatMode === 'video'
            ? '<div class="agent-chat-empty">选择对话模型和视频模型后，可让智能体基于当前分镜生成视频。</div>'
            : '<div class="agent-chat-empty">选择对话模型后，可让智能体基于当前画面提示词生成或调整首帧。</div>';
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

function renderStoryboardGrid() {
    const cards = state.scenes.map((scene, index) => {
        const nextScene = state.scenes[index + 1];
        return `
            <div class="storyboard-grid-cell">
                <article class="storyboard-card ${state.currentSceneId === scene.id ? 'active' : ''}" data-scene="${scene.id}">
                    <div class="storyboard-thumb">${mediaFrame(scene)}</div>
                    <div class="storyboard-card-body">
                        <h3>${escapeHtml(scene.title)}</h3>
                        <p>${escapeHtml(scene.durationLabel)}</p>
                        <div class="card-status">${assetBadge(scene, 'first_frame', '图')} ${assetBadge(scene, 'video', '视频')}</div>
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

function renderTimeline() {
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
                <div class="scene-timeline-list">${scenes}<button class="add-scene-btn" data-action="add-scene">${icon('add', 22)}</button></div>
            </div>
        </section>`;
}

function renderRightSidebar(scene) {
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

function renderGenerateFromScriptDialog() {
    if (!state.showGenerateFromScriptDialog) return '';
    const busy = state.isGeneratingFromScript;
    const splitModelConfig = renderScriptSplitModelConfig(busy);
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

function renderImageModelConfig() {
    const models = state.textToImageModels.length ? state.textToImageModels : state.imageModels;
    let html = '<label class="config-label">生图模型</label><div class="config-hint">用于对话改图与图片生成</div><div class="config-select-wrapper"><select class="chat-mode-select" data-config-select="image">';
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

export function renderApp() {
    const app = document.getElementById('app');
    const scene = getCurrentScene();

    if (state.error) {
        app.innerHTML = `<div class="storyboard-error"><h1>故事板打开失败</h1><p>${escapeHtml(state.error)}</p><button class="btn-primary" data-route="script">返回剧本策划</button></div>`;
        return;
    }

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
        ${renderMentionPopup()}
        ${renderModelConfigModal()}
        ${renderGlobalStyleDialog()}`;
}
