function getAuthToken() {
  return localStorage.getItem('auth_token') || '';
}

function getUserId() {
  return localStorage.getItem('user_id') || '';
}

function authHeaders() {
  const token = getAuthToken();
  const userId = getUserId();
  const headers = {};
  if (token) headers.Authorization = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
  if (userId) headers['X-User-Id'] = userId;
  return headers;
}

export function normalizeFoldersResponse(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.folders)) return data.folders;
  if (Array.isArray(data?.data?.folders)) return data.data.folders;
  if (Array.isArray(data?.data?.data)) return data.data.data;
  return [];
}

export function buildStoryboardUrl(folder) {
  const params = new URLSearchParams();
  if (folder.storyboard_id) params.set('id', folder.storyboard_id);
  if (folder.world_id) params.set('world_id', folder.world_id);
  params.set('episode_number', folder.episode_number || 1);
  if (folder.script_id) params.set('script_id', folder.script_id);
  if (folder.workflow_id) params.set('workflow_id', folder.workflow_id);
  // 注意：不把 auth_token 放到 URL 中（避免敏感信息暴露），storyboard 页面会从 localStorage 读取（与 script_writer.html 保持一致）
  // 也不拼 user_id：URL 中的 user_id 是链接生成者的身份，转发给他人会触发后端身份一致性校验 401
  return `/storyboard?${params.toString()}`;
}

// 转义统一收敛到 web/js/escape.js（window.escapeHtml）。
// 旧 textContent→innerHTML 实现不转义引号，在属性上下文可被逃逸，已废弃。
const escapeHtml = window.escapeHtml;

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function statusLabel(status) {
  if (status === 'created') return '已创建';
  if (status === 'orphan') return '剧本缺失';
  return '未创建';
}

let foldersCache = [];
let ownerScope = 'mine';
let ownerQuery = '';
let isAdminUser = false;

async function loadIsAdmin() {
  try {
    const response = await fetch('/api/user/role', { headers: authHeaders() });
    const data = await response.json().catch(() => null);
    isAdminUser = !!(data && data.code === 0 && data.data && data.data.role === 'admin');
  } catch {
    isAdminUser = false;
  }
}

function syncOwnerScopeUi() {
  const bar = document.getElementById('storyboardOwnerScope');
  const form = document.getElementById('storyboardOwnerForm');
  if (bar) bar.hidden = !isAdminUser;
  if (form) form.hidden = !(isAdminUser && ownerScope === 'user');
  document.querySelectorAll('.owner-scope-btn').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.scope === ownerScope);
  });
}

async function fetchFolders() {
  const params = new URLSearchParams(window.location.search);
  const worldId = params.get('world_id');
  const query = new URLSearchParams();
  if (worldId) query.set('world_id', worldId);
  if (isAdminUser && ownerScope) query.set('scope', ownerScope);
  if (isAdminUser && ownerScope === 'user' && ownerQuery) query.set('owner', ownerQuery);
  const qs = query.toString();
  const url = qs ? `/api/storyboard/folders?${qs}` : '/api/storyboard/folders';
  const response = await fetch(url, { headers: authHeaders() });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false || data.code === -1) {
    throw new Error(data.error || data.message || '加载故事板列表失败');
  }
  const hint = document.getElementById('storyboardOwnerHint');
  if (hint) {
    const message = typeof data.message === 'string' ? data.message : '';
    hint.textContent = message;
    hint.hidden = !message;
  }
  return normalizeFoldersResponse(data);
}

function renderFolders() {
  const container = document.getElementById('storyboardFolderContainer');
  const keyword = (document.getElementById('storyboardSearchInput')?.value || '').trim().toLowerCase();
  const status = document.getElementById('storyboardStatusFilter')?.value || '';
  const folders = foldersCache.filter((folder) => {
    const haystack = `${folder.script_title || ''} ${folder.storyboard_title || ''} ${folder.world_name || ''}`.toLowerCase();
    return (!keyword || haystack.includes(keyword)) && (!status || folder.status === status);
  });

  if (!folders.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div>
          <h2>暂无故事板文件夹</h2>
          <p>先在剧本智能体中完成剧本资产，再从这里进入故事板制作。</p>
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = folders.map((folder) => {
    const primaryText = folder.storyboard_id ? '打开故事板' : '创建故事板';
    const title = folder.script_title || folder.storyboard_title || `第 ${folder.episode_number || 1} 集`;
    const scriptUrl = folder.world_id
      ? `/script-writer?world_id=${encodeURIComponent(folder.world_id)}&user_id=${encodeURIComponent(getUserId())}`
      : `/script-writer?user_id=${encodeURIComponent(getUserId())}`;
    const isOwn = folder.owner_user_id == null || String(folder.owner_user_id) === String(getUserId());
    const deleteButton = folder.storyboard_id && isOwn
      ? `<button class="btn btn-danger" data-action="delete" data-id="${folder.storyboard_id}">删除</button>`
      : '';
    const ownerName = String(folder.owner_nickname || '').trim();
    const ownerHtml = ownerName
      ? `<div class="folder-owner">${escapeHtml(ownerName)}</div>`
      : '';

    return `
      <article class="folder-card ${escapeHtml(folder.status)}">
        <div class="folder-tab"></div>
        <div class="folder-body">
          <div class="folder-title-row">
            <h2 class="folder-title">${escapeHtml(title)}</h2>
            <span class="status-pill ${escapeHtml(folder.status)}">${statusLabel(folder.status)}</span>
          </div>
          ${ownerHtml}
          <div class="folder-meta">
            <div class="meta-item">
              <span class="meta-label">世界</span>
              <span class="meta-value">${escapeHtml(folder.world_name || '-')}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">集数</span>
              <span class="meta-value">第 ${escapeHtml(folder.episode_number || 1)} 集</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">分镜</span>
              <span class="meta-value">${escapeHtml(folder.scene_count || 0)}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">最近编辑</span>
              <span class="meta-value">${escapeHtml(formatDate(folder.update_at))}</span>
            </div>
          </div>
          <div class="folder-actions">
            <a class="btn btn-primary" href="${buildStoryboardUrl(folder)}">${primaryText}</a>
            <a class="btn btn-secondary" href="${scriptUrl}">回到剧本</a>
            ${deleteButton}
          </div>
        </div>
      </article>
    `;
  }).join('');
}

function showToast(message, type = '') {
  const toast = document.getElementById('storyboardToast');
  if (!toast) return;
  toast.textContent = message;
  toast.className = `toast ${type}`;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2600);
}

async function deleteStoryboard(id) {
  if (!id || !confirm('确定删除该故事板吗？所有分镜将一并删除。')) return;
  const response = await fetch(`/api/storyboard/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data.error || data.message || '删除失败');
  }
  foldersCache = foldersCache.map((folder) => (
    String(folder.storyboard_id) === String(id)
      ? { ...folder, storyboard_id: null, storyboard_title: null, scene_count: 0, status: 'not_created' }
      : folder
  ));
  renderFolders();
  showToast('故事板已删除');
}

async function init() {
  const container = document.getElementById('storyboardFolderContainer');
  // 兼容期双写：登录态以 localStorage.auth_token 为准
  const loggedIn = !!getAuthToken();
  if (!loggedIn || !getUserId()) {
    window.location.href = '/?login=1&redirect_url=storyboard-list';
    return;
  }

  document.getElementById('storyboardSearchInput')?.addEventListener('input', renderFolders);
  document.getElementById('storyboardStatusFilter')?.addEventListener('change', renderFolders);
  document.getElementById('storyboardOwnerScope')?.addEventListener('click', async (event) => {
    const button = event.target.closest('.owner-scope-btn');
    if (!button || !isAdminUser) return;
    ownerScope = button.dataset.scope || 'mine';
    syncOwnerScopeUi();
    if (ownerScope === 'user' && !ownerQuery) {
      foldersCache = [];
      const hint = document.getElementById('storyboardOwnerHint');
      if (hint) {
        hint.textContent = '请输入昵称或账号';
        hint.hidden = false;
      }
      renderFolders();
      return;
    }
    try {
      foldersCache = await fetchFolders();
      renderFolders();
    } catch (error) {
      showToast(error.message, 'error');
    }
  });
  document.getElementById('storyboardOwnerForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    ownerScope = 'user';
    ownerQuery = (document.getElementById('storyboardOwnerInput')?.value || '').trim();
    syncOwnerScopeUi();
    if (!ownerQuery) {
      foldersCache = [];
      const hint = document.getElementById('storyboardOwnerHint');
      if (hint) {
        hint.textContent = '请输入昵称或账号';
        hint.hidden = false;
      }
      renderFolders();
      return;
    }
    try {
      foldersCache = await fetchFolders();
      renderFolders();
    } catch (error) {
      showToast(error.message, 'error');
    }
  });
  container?.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-action="delete"]');
    if (!target) return;
    event.preventDefault();
    try {
      await deleteStoryboard(target.dataset.id);
    } catch (error) {
      showToast(error.message, 'error');
    }
  });

  try {
    await loadIsAdmin();
    syncOwnerScopeUi();
    foldersCache = await fetchFolders();
    renderFolders();
  } catch (error) {
    container.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', init);
}
