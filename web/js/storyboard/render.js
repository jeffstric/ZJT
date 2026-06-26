import state, { getCurrentScene, getTotalDuration } from './state.js';
import { formatDuration } from './adapters.js';
import { icon } from './icons.js';

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
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
                    <div class="header-subtitle">第${state.episodeNumber}集 · ${escapeHtml(state.workflowRatio)}</div>
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
    return `
        <div class="tab-panel">
            <div class="info-card">
                <div class="info-card-header">
                    <div class="info-card-title">${icon('image', 18)} 画面提示词</div>
                    <button class="text-button" data-action="open-edit">${icon('edit', 14)} 编辑</button>
                </div>
                <div class="info-card-body">
                    <p class="info-tag">[${escapeHtml(prompt.perspective || '未设置视角')}]</p>
                    <p class="info-tag">[${escapeHtml(prompt.style || state.style || '未设置风格')}]</p>
                    <p>${escapeHtml(prompt.scene_desc || '还没有场景描述。')}</p>
                    <p>${escapeHtml(prompt.character_desc || '还没有角色描述。')}</p>
                </div>
            </div>
            <div class="info-card">
                <div class="info-card-header">
                    <div class="info-card-title">${icon('image', 18)} 视频提示词（${escapeHtml(scene.videoType || 'video')}）</div>
                </div>
                <div class="info-card-body">
                    <textarea class="voice-textarea" data-scene-field="videoPrompt">${escapeHtml(scene.videoPrompt)}</textarea>
                    <button class="panel-button" data-action="save-scene">${icon('success', 16)} 保存分镜内容</button>
                </div>
            </div>
            <div class="thumbnail-card">${mediaFrame(scene)}</div>
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
                    <label>语速<input type="number" step="0.1" data-dialogue-field="speed" value="${d.speed ?? 1.0}"></label>
                    <label>音量<input type="number" data-dialogue-field="volume" value="${d.volume ?? 100}"></label>
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
                    <div class="project-label">${scene ? escapeHtml(scene.title) : '未选择分镜'}</div>
                    <div class="project-brand"><div class="brand-icon">分</div><span>分镜工作台</span></div>
                </div>
                <div class="tab-nav">${tabs}</div>
                ${renderTabs(scene)}
            </div>
            ${renderAiPanel()}
        </aside>`;
}

function renderModelSelect(scene) {
    // 按 AI 助手模式 + 当前分镜 video_type 选择模型列表
    if (state.chatMode === 'image') {
        const opts = state.imageModels.map(m =>
            `<option value="${m.task_id}" ${state.selectedImageTaskId === m.task_id ? 'selected' : ''}>${escapeHtml(m.name)}</option>`
        ).join('');
        return `<select class="chat-mode-select" data-model-select="image">${opts || '<option value="">暂无模型</option>'}</select>`;
    }
    if (state.chatMode === 'video') {
        const isDigitalHuman = scene && scene.videoType === 'digital_human';
        const models = isDigitalHuman ? state.digitalHumanModels : state.videoModels;
        const selected = isDigitalHuman ? state.selectedDigitalHumanTaskId : state.selectedVideoTaskId;
        const kind = isDigitalHuman ? 'digital_human' : 'video';
        const opts = models.map(m =>
            `<option value="${m.task_id}" ${selected === m.task_id ? 'selected' : ''}>${escapeHtml(m.name)}</option>`
        ).join('');
        return `<select class="chat-mode-select" data-model-select="${kind}">${opts || '<option value="">暂无模型</option>'}</select>`;
    }
    return '';
}

function renderAiPanel() {
    const scene = getCurrentScene();
    const modes = [
        ['dialogue', '对话改图'],
        ['image', '图片生成'],
        ['video', '视频生成'],
    ].map(([key, label]) => `<option value="${key}" ${state.chatMode === key ? 'selected' : ''}>${label}</option>`).join('');

    return `
        <section class="ai-chat-section">
            <div class="ai-chat-header">${icon('send', 16)} 分镜助手</div>
            <textarea id="chat-textarea" class="chat-textarea" placeholder="输入你想对当前分镜调整的内容">${escapeHtml(state.inputMessage)}</textarea>
            <div class="chat-toolbar">
                <select id="chat-mode-select" class="chat-mode-select">${modes}</select>
                ${renderModelSelect(scene)}
                <button class="tool-button" data-action="mention">@</button>
                <button class="tool-button ${state.aiOptimize ? 'active' : ''}" data-action="toggle-ai">AI</button>
                <button class="chat-send-btn" data-action="send-ai">${icon('send', 16)}</button>
            </div>
        </section>`;
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

function renderStoryboardGrid() {
    const cards = state.scenes.map(scene => `
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
        </article>`).join('');

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
    const scenes = state.scenes.map(scene => `
        <div class="scene-timeline-item">
            <button class="scene-timeline-thumb ${state.currentSceneId === scene.id ? 'active' : ''}" data-scene="${scene.id}">
                ${scene.firstFrameUrl ? `<img src="${escapeHtml(scene.firstFrameUrl)}" alt="${escapeHtml(scene.title)}">` : '<span>无画面</span>'}
                <b>${escapeHtml(scene.durationLabel)}</b>
            </button>
            <div class="scene-timeline-actions">
                <button data-action="duplicate-scene" data-id="${scene.id}" title="复制">${icon('copy', 14)}</button>
                <button data-action="delete-scene" data-id="${scene.id}" title="删除">${icon('delete', 14)}</button>
            </div>
        </div>`).join('');

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
    const refs = [
        ['首帧', scene?.firstFrameUrl || ''],
        ['尾帧', scene?.lastFrameUrl || ''],
        ['视频', scene?.videoUrl || ''],
    ];
    return `
        <aside class="right-sidebar">
            ${refs.map(([label, url]) => `
                <div class="right-ref">
                    <span>${label}</span>
                    ${url
                        ? (label === '视频'
                            ? `<video src="${escapeHtml(url)}" controls></video>`
                            : `<img src="${escapeHtml(url)}" alt="${label}">`)
                        : '<div class="ref-empty">未生成</div>'}
                </div>`).join('')}
        </aside>`;
}

function renderEditDialog(scene) {
    if (!state.showEditPrompt || !scene) return '';
    const prompt = scene.promptJson || {};
    return `
        <div class="modal-overlay">
            <div class="edit-dialog">
                <header><h2>编辑画面提示词</h2><button data-action="close-edit">${icon('close', 18)}</button></header>
                <label>视角<input data-edit-field="perspective" value="${escapeHtml(prompt.perspective)}"></label>
                <label>风格<input data-edit-field="style" value="${escapeHtml(prompt.style)}"></label>
                <label>场景描述<textarea data-edit-field="scene_desc">${escapeHtml(prompt.scene_desc)}</textarea></label>
                <label>角色描述<textarea data-edit-field="character_desc">${escapeHtml(prompt.character_desc)}</textarea></label>
                <footer><button class="btn-ghost" data-action="close-edit">取消</button><button class="btn-primary" data-action="save-prompt">保存</button></footer>
            </div>
        </div>`;
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
                ${items.map(item => `<button data-mention-item="${escapeHtml(item.name)}">${item.avatar ? `<img src="${escapeHtml(item.avatar)}" alt="">` : ''}<span>${escapeHtml(item.name)}</span></button>`).join('') || '<div class="empty-note">暂无资产</div>'}
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
        ${renderEditDialog(scene)}
        ${renderExportDialog()}
        ${renderMentionPopup()}`;
}
