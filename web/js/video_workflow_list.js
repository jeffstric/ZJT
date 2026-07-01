// i18n 翻译函数
function t(key, params = {}) {
  if (window.ZJTi18n) {
    return window.ZJTi18n.t(key, params) || key;
  }
  return key;
}

let currentPage = 1;
let pageSize = 10;
let totalPages = 1;
let searchKeyword = '';
let searchTimeout = null;
let worldsCache = [];

function ensureLoggedIn() {
  const uid = getUserId();
  if (!uid) {
    showToast(t('toast_login_required'), 'error');
    return false;
  }
  return true;
}

async function loadWorkflows() {
  const container = document.getElementById('workflowContainer');
  container.innerHTML = '<div class="loading"><div class="loading-spinner"></div><div>' + t('loading') + '</div></div>';

  if (!ensureLoggedIn()) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🔒</div><div class="empty-state-title">' + t('login_required') + '</div><div class="empty-state-desc">' + t('login_required_desc') + '</div><a class="btn" href="/">' + t('go_to_login') + '</a></div>';
    document.getElementById('pagination').style.display = 'none';
    return;
  }

  const status = document.getElementById('statusFilter').value;
  let url = `/api/video-workflow/list?page=${currentPage}&page_size=${pageSize}`;
  if (status) url += `&status=${status}`;
  if (searchKeyword) url += `&keyword=${encodeURIComponent(searchKeyword)}`;

  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      }
    });
    const result = await response.json();

    if (result.code === 0) {
      renderWorkflows(result.data);
    } else {
      showToast(result.message || t('load_failed'), 'error');
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">😕</div><div class="empty-state-title">' + t('load_failed') + '</div><div class="empty-state-desc">' + t('load_failed_desc') + '</div></div>';
    }
  } catch (error) {
    showToast(t('network_error'), 'error');
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">😕</div><div class="empty-state-title">' + t('network_error') + '</div><div class="empty-state-desc">' + t('network_error_desc') + '</div></div>';
  }
}

function renderWorkflows(data) {
  const container = document.getElementById('workflowContainer');
  const pagination = document.getElementById('pagination');

  if (!data.data || data.data.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📋</div>
        <div class="empty-state-title">${t('no_workflows')}</div>
        <div class="empty-state-desc">${t('no_workflows_desc')}</div>
        <button class="btn" onclick="openCreateModal()">${t('create_workflow')}</button>
      </div>
    `;
    pagination.style.display = 'none';
    return;
  }

  totalPages = Math.ceil(data.total / pageSize);

  let html = '<div class="workflow-grid">';
  data.data.forEach(workflow => {
    const statusClass = workflow.status === 1 ? 'status-enabled' :
                       workflow.status === 0 ? 'status-disabled' : 'status-draft';
    const statusText = workflow.status === 1 ? t('status_enabled') :
                      workflow.status === 0 ? t('status_disabled') : t('status_draft');

    const coverHtml = workflow.cover_image
      ? `<img src="${escapeHtml(workflow.cover_image)}" alt="${escapeHtml(workflow.name)}">`
      : '🎬';

    const createTime = workflow.create_time ? new Date(workflow.create_time).toLocaleDateString() : '';

    // 使用 JSON.stringify + escapeHtml 双层转义防止 onclick 实体解码攻击
    const safeName = escapeHtml(JSON.stringify(workflow.name || ''));
    const safeDesc = escapeHtml(JSON.stringify(workflow.description || ''));

    html += `
      <div class="workflow-card" onclick="enterWorkflow(${workflow.id})">
        <div class="workflow-cover">${coverHtml}</div>
        <div class="workflow-content">
          <div class="workflow-name">${escapeHtml(workflow.name)}</div>
          <div class="workflow-desc">${escapeHtml(workflow.description || t('no_description'))}</div>
          <div class="workflow-meta">
            <span>${createTime}</span>
            <span class="workflow-status ${statusClass}">${statusText}</span>
          </div>
        </div>
        <div class="workflow-actions" onclick="event.stopPropagation()">
          <button class="btn btn-secondary btn-sm" onclick="editWorkflow(${workflow.id}, ${safeName}, ${safeDesc}, ${workflow.status})">${t('edit_btn')}</button>
          <button class="btn btn-danger btn-sm" onclick="deleteWorkflow(${workflow.id})">${t('delete_btn')}</button>
        </div>
      </div>
    `;
  });
  html += '</div>';

  container.innerHTML = html;

  // Update pagination
  document.getElementById('pageInfo').textContent = t('page_info', { current: currentPage, total: totalPages, count: data.total });
  document.getElementById('prevBtn').disabled = currentPage <= 1;
  document.getElementById('nextBtn').disabled = currentPage >= totalPages;
  pagination.style.display = 'flex';
}

function handleSearch(event) {
  if (searchTimeout) clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    searchKeyword = document.getElementById('searchInput').value.trim();
    currentPage = 1;
    loadWorkflows();
  }, 300);
}

function prevPage() {
  if (currentPage > 1) {
    currentPage--;
    loadWorkflows();
  }
}

function nextPage() {
  if (currentPage < totalPages) {
    currentPage++;
    loadWorkflows();
  }
}

function enterWorkflow(id) {
  window.location.href = `/video-workflow?id=${id}`;
}

async function openCreateModal(options = {}) {
  document.getElementById('modalTitle').textContent = t('create_modal_title');
  document.getElementById('workflowId').value = '';
  document.getElementById('workflowName').value = '';
  document.getElementById('workflowDesc').value = '';
  document.getElementById('workflowWorld').value = '';
  document.getElementById('workflowStyle').value = '';
  document.getElementById('workflowStatus').value = '1';
  // 重置比例选择为默认值
  const defaultRatioInput = document.querySelector('input[name="workflowRatio"][value="16:9"]');
  if (defaultRatioInput) {
    defaultRatioInput.checked = true;
    // 更新checked类（用于不支持:has()的浏览器）
    updateRatioOptionStyles();
  }
  document.getElementById('descSection').style.display = 'none';
  document.getElementById('toggleDescBtn').textContent = t('expand_desc');
  document.getElementById('styleFieldGroup').style.display = options.hideStyle ? 'none' : '';
  await loadWorlds();
  document.getElementById('createModal').classList.add('active');
}

async function editWorkflow(id, name, desc, status) {
  document.getElementById('modalTitle').textContent = t('edit_modal_title');
  document.getElementById('workflowId').value = id;
  document.getElementById('workflowName').value = name;
  document.getElementById('workflowDesc').value = desc;
  document.getElementById('workflowStatus').value = status;
  document.getElementById('descSection').style.display = 'none';
  document.getElementById('toggleDescBtn').textContent = t('expand_desc');

  await loadWorlds();

  // Load style data
  try {
    const response = await fetch(`/api/video-workflow/${id}`, {
      headers: {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      }
    });
    const result = await response.json();
    if (result.code === 0 && result.data) {
      document.getElementById('workflowWorld').value = result.data.default_world_id || '';
      document.getElementById('workflowStyle').value = result.data.style || '';
      // Load workflow_ratio if provided
      if (result.data.workflow_ratio) {
        const ratioInput = document.querySelector(`input[name="workflowRatio"][value="${result.data.workflow_ratio}"]`);
        if (ratioInput) {
          ratioInput.checked = true;
        }
      } else {
        // Default to 16:9 if no workflow_ratio
        const defaultRatioInput = document.querySelector('input[name="workflowRatio"][value="16:9"]');
        if (defaultRatioInput) {
          defaultRatioInput.checked = true;
        }
      }
      // 更新checked类（用于不支持:has()的浏览器）
      updateRatioOptionStyles();
    }
  } catch (error) {
    console.error('Failed to load workflow details:', error);
  }

  document.getElementById('createModal').classList.add('active');
}

// 更新比例选项的样式（为不支持:has()的浏览器添加checked类）
function updateRatioOptionStyles() {
  const ratioOptions = document.querySelectorAll('.ratio-option');
  ratioOptions.forEach(option => {
    const radio = option.querySelector('input[type="radio"]');
    if (radio && radio.checked) {
      option.classList.add('checked');
    } else {
      option.classList.remove('checked');
    }
  });
}

function closeModal() {
  document.getElementById('createModal').classList.remove('active');
  // 重置比例选择为默认值
  const defaultRatioInput = document.querySelector('input[name="workflowRatio"][value="16:9"]');
  if (defaultRatioInput) {
    defaultRatioInput.checked = true;
    updateRatioOptionStyles();
  }
}

function toggleDescSection() {
  const section = document.getElementById('descSection');
  const btn = document.getElementById('toggleDescBtn');
  if (section.style.display === 'none') {
    section.style.display = 'block';
    btn.textContent = t('collapse_desc');
  } else {
    section.style.display = 'none';
    btn.textContent = t('expand_desc');
  }
}

// 创建工作流的通用逻辑，返回创建的工作流ID
async function createWorkflowData() {
  if (!ensureLoggedIn()) return null;

  const id = document.getElementById('workflowId').value;
  const name = document.getElementById('workflowName').value.trim();
  const description = document.getElementById('workflowDesc').value.trim();
  const status = parseInt(document.getElementById('workflowStatus').value);
  const worldId = document.getElementById('workflowWorld').value;
  const style = document.getElementById('workflowStyle').value.trim();
  const workflowRatio = document.querySelector('input[name="workflowRatio"]:checked')?.value || null;

  if (!name) {
    showToast(t('toast_workflow_name_required'), 'error');
    return null;
  }

  const isEdit = !!id;
  if (!isEdit && !workflowRatio) {
    showToast(t('toast_ratio_required'), 'error');
    return null;
  }

  const data = { name, description, status };

  // Add world_id if provided
  if (worldId) {
    data.default_world_id = parseInt(worldId);
  }

  // Add style if provided
  if (style) {
    data.style = style;
  }

  // Add workflow_ratio if provided
  if (workflowRatio) {
    data.workflow_ratio = workflowRatio;
  }
  const url = isEdit ? `/api/video-workflow/${id}` : '/api/video-workflow/create';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const response = await fetch(url, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      },
      body: JSON.stringify(data)
    });
    const result = await response.json();

    if (result.code === 0) {
      return { isEdit, workflowId: result.data?.id || id };
    } else {
      showToast(result.message || t('toast_operation_failed'), 'error');
      return null;
    }
  } catch (error) {
    showToast(t('network_error'), 'error');
    return null;
  }
}

async function handleSubmit(event) {
  if (event) event.preventDefault();

  // 禁用按钮防止重复提交
  const btns = document.querySelectorAll('#workflowForm .modal-actions .btn');
  const originalTexts = [];
  btns.forEach((btn, i) => {
    originalTexts[i] = btn.textContent;
    btn.disabled = true;
  });

  try {
    const result = await createWorkflowData();
    if (result) {
      showToast(result.isEdit ? t('toast_update_success') : t('toast_create_success'), 'success');
      closeModal();
      loadWorkflows();
    }
  } finally {
    btns.forEach((btn, i) => {
      btn.disabled = false;
      if (originalTexts[i]) btn.textContent = originalTexts[i];
    });
  }
}

async function handleSubmitAndGoScript(event) {
  if (event) event.preventDefault();

  // 禁用按钮防止重复提交
  const btns = document.querySelectorAll('#workflowForm .modal-actions .btn');
  const originalTexts = [];
  btns.forEach((btn, i) => {
    originalTexts[i] = btn.textContent;
    btn.disabled = true;
  });

  try {
    // 先获取世界ID，因为createWorkflowData后表单可能被清空
    const worldId = document.getElementById('workflowWorld').value;

    const result = await createWorkflowData();
    if (result && result.workflowId) {
      showToast(t('toast_creating'), 'success');
      closeModal();
      // 跳转到剧本创作系统
      const userId = getUserId();
      let url = `/script-writer?workflow_id=${result.workflowId}&user_id=${encodeURIComponent(userId)}`;
      if (worldId) {
        url += `&world_id=${worldId}`;
      }
      window.location.href = url;
    }
  } finally {
    btns.forEach((btn, i) => {
      btn.disabled = false;
      if (originalTexts[i]) btn.textContent = originalTexts[i];
    });
  }
}

function deleteWorkflow(id) {
  document.getElementById('deleteWorkflowId').value = id;
  document.getElementById('deleteModal').classList.add('active');
}

function closeDeleteModal() {
  document.getElementById('deleteModal').classList.remove('active');
}

async function confirmDelete() {
  const id = document.getElementById('deleteWorkflowId').value;

  if (!ensureLoggedIn()) return;

  try {
    const response = await fetch(`/api/video-workflow/${id}`, {
      method: 'DELETE',
      headers: {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      }
    });
    const result = await response.json();

    if (result.code === 0) {
      showToast(t('toast_delete_success'), 'success');
      closeDeleteModal();
      loadWorkflows();
    } else {
      showToast(result.message || t('toast_delete_failed'), 'error');
    }
  } catch (error) {
    showToast(t('network_error'), 'error');
  }
}

// Style image preview
async function loadWorlds() {
  if (!ensureLoggedIn()) return;

  try {
    const response = await fetch('/api/worlds?page=1&page_size=100', {
      headers: {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      }
    });
    const result = await response.json();

    if (result.code === 0 && result.data && result.data.data) {
      worldsCache = result.data.data;
      const select = document.getElementById('workflowWorld');
      const currentValue = select.value;

      select.innerHTML = '<option value="">' + t('select_world_placeholder') + '</option>';
      worldsCache.forEach(world => {
        const option = document.createElement('option');
        option.value = world.id;
        option.textContent = world.name;
        select.appendChild(option);
      });

      if (currentValue) {
        select.value = currentValue;
      }
    }
  } catch (error) {
    console.error('Failed to load worlds:', error);
  }
}

function openWorldModal() {
  document.getElementById('worldName').value = '';
  document.getElementById('worldDesc').value = '';
  document.getElementById('worldDescSection').style.display = 'none';
  document.getElementById('toggleWorldDescBtn').textContent = t('expand_desc');
  document.getElementById('worldModal').classList.add('active');
}

function closeWorldModal() {
  document.getElementById('worldModal').classList.remove('active');
}

function toggleWorldDescSection() {
  const section = document.getElementById('worldDescSection');
  const btn = document.getElementById('toggleWorldDescBtn');
  if (section.style.display === 'none') {
    section.style.display = 'block';
    btn.textContent = t('collapse_desc');
  } else {
    section.style.display = 'none';
    btn.textContent = t('expand_desc');
  }
}

async function handleWorldSubmit(event) {
  event.preventDefault();

  if (!ensureLoggedIn()) return;

  const name = document.getElementById('worldName').value.trim();
  const description = document.getElementById('worldDesc').value.trim();

  if (!name) {
    showToast(t('toast_world_name_required'), 'error');
    return;
  }

  try {
    const response = await fetch('/api/worlds', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      },
      body: JSON.stringify({ name, description })
    });
    const result = await response.json();

    if (result.code === 0) {
      showToast(t('toast_world_create_success'), 'success');
      closeWorldModal();
      await loadWorlds();
      if (result.data && result.data.id) {
        document.getElementById('workflowWorld').value = result.data.id;
      }
    } else {
      showToast(result.message || t('toast_world_create_failed'), 'error');
    }
  } catch (error) {
    showToast(t('network_error'), 'error');
  }
}

async function handleAgentClick() {
  if (!ensureLoggedIn()) return;

  try {
    const authToken = getAuthToken();
    const userId = getUserId();

    // 将 auth_token 存储到 localStorage，避免在 URL 中暴露
    localStorage.setItem('auth_token', authToken);

    // 直接跳转到内部路由（不传递 auth_token）
    const url = `/script-writer?user_id=${encodeURIComponent(userId)}`;

    // 打开新窗口
    window.open(url, '_blank');
  } catch (error) {
    console.error('Failed to open script writer:', error);
    showToast(t('network_error'), 'error');
  }
}

// Close modal on overlay click（需检查元素是否存在，测试环境中 DOM 可能未就绪）
const _createModal = document.getElementById('createModal');
if (_createModal) _createModal.addEventListener('click', function(e) { if (e.target === this) closeModal(); });
const _deleteModal = document.getElementById('deleteModal');
if (_deleteModal) _deleteModal.addEventListener('click', function(e) { if (e.target === this) closeDeleteModal(); });
const _worldModal = document.getElementById('worldModal');
if (_worldModal) _worldModal.addEventListener('click', function(e) { if (e.target === this) closeWorldModal(); });

// 初始化 i18n
async function initI18n() {
  if (window.ZJTi18n) {
    const locale = localStorage.getItem('zjt_locale') || 'zh-CN';
    await window.ZJTi18n.setLocale(locale, ['workflow_list']);
    // 扫描 DOM 翻译静态元素
    if (window.ZJTi18nDOM) {
      window.ZJTi18nDOM.scanDOM(document.body);
    }
    // 渲染语言切换器
    if (window.ZJTi18nSwitcher) {
      window.ZJTi18nSwitcher.render('i18nSwitcher');
    }
  }
}

// Initial load（仅在浏览器环境中执行，测试环境跳过）
if (typeof document !== 'undefined' && document.getElementById('workflowContainer')) {
  initI18n().then(() => {
    loadWorkflows();
  }).catch(err => {
    console.error('[i18n] 初始化失败:', err);
    loadWorkflows();
  });

  // 检测URL参数，如果有action=create则自动打开新建表单
  const urlParams = new URLSearchParams(window.location.search);
  // 为比例选择器添加事件监听（用于不支持:has()的浏览器）
  const ratioInputs = document.querySelectorAll('input[name="workflowRatio"]');
  ratioInputs.forEach(input => {
    input.addEventListener('change', updateRatioOptionStyles);
  });

  if (urlParams.get('action') === 'create') {
    const styleFieldGroup = document.getElementById('styleFieldGroup');
    if (styleFieldGroup) styleFieldGroup.style.display = 'none';
    setTimeout(() => {
      openCreateModal({ hideStyle: true });
    }, 100);
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

// ES Module exports（供 Vitest 测试使用，不影响浏览器全局变量）
if (typeof module !== 'undefined') {
  module.exports = { ensureLoggedIn };
}
