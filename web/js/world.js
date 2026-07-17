
// World management functionality

let worldListCache = [];

// Load worlds list
async function loadWorlds() {
  try {
    const response = await fetch('/api/worlds?page=1&page_size=100', {
      headers: {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      }
    });
    
    const result = await response.json();
    
    if (result.code === 0 && result.data && result.data.data) {
      worldListCache = result.data.data;
      return worldListCache;
    } else {
      console.error('Failed to load worlds:', result.message);
      worldListCache = [];
      return [];
    }
  } catch (error) {
    console.error('Error loading worlds:', error);
    worldListCache = [];
    return [];
  }
}

// Populate world selector
async function populateWorldSelector() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  if (!defaultWorldSelect) return;

  const worlds = await loadWorlds();

  // Clear existing options except the first one
  var defaultLabel = window.t ? window.t('select_world') : '选择世界...';
  defaultWorldSelect.innerHTML = '<option value="">' + escapeHtml(defaultLabel) + '</option>';

  // Add world options
  worlds.forEach(world => {
    const option = document.createElement('option');
    option.value = world.id;
    option.textContent = world.name;
    defaultWorldSelect.appendChild(option);
  });

  // Restore saved world selection
  if (state.defaultWorldId) {
    defaultWorldSelect.value = state.defaultWorldId;
  }

  // 渲染自定义可搜索下拉
  renderWorldSearchOptions(worlds);

  // Update visual state
  updateWorldSelectorState();
}

// 渲染自定义搜索下拉选项
function renderWorldSearchOptions(worlds) {
  const optionsContainer = document.getElementById('worldSearchOptions');
  const triggerText = document.getElementById('worldSearchTriggerText');
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  if (!optionsContainer) return;

  optionsContainer.innerHTML = '';

  if (worlds.length === 0) {
    const emptyItem = document.createElement('div');
    emptyItem.className = 'world-search-empty';
    emptyItem.textContent = window.t ? window.t('no_worlds_found') : '未找到匹配的世界';
    optionsContainer.appendChild(emptyItem);
    return;
  }

  const selectedId = defaultWorldSelect ? defaultWorldSelect.value : '';

  worlds.forEach(world => {
    const optionItem = document.createElement('div');
    optionItem.className = 'world-search-option' + (String(world.id) === selectedId ? ' selected' : '');
    optionItem.setAttribute('role', 'option');
    optionItem.setAttribute('data-world-id', world.id);
    optionItem.textContent = world.name;
    optionItem.title = world.description || world.name;

    optionItem.addEventListener('click', (e) => {
      e.stopPropagation();
      selectWorldInSearchDropdown(world.id);
    });

    optionsContainer.appendChild(optionItem);
  });
}

function selectWorldInSearchDropdown(worldId) {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  if (defaultWorldSelect) {
    defaultWorldSelect.value = worldId;
  }
  handleWorldSelectionChange(worldId);
  closeWorldSearchDropdown();
}

function openWorldSearchDropdown() {
  const dropdown = document.getElementById('worldSearchDropdown');
  const trigger = document.getElementById('worldSearchTrigger');
  const searchInput = document.getElementById('worldSearchInput');
  if (!dropdown) return;

  dropdown.classList.add('open');
  if (trigger) trigger.setAttribute('aria-expanded', 'true');
  dropdown.setAttribute('aria-hidden', 'false');

  // 高亮当前选中项并滚动到可视区域
  const selectedId = state.defaultWorldId || '';
  const optionsContainer = document.getElementById('worldSearchOptions');
  if (optionsContainer) {
    optionsContainer.querySelectorAll('.world-search-option').forEach(el => {
      el.classList.toggle('selected', String(el.dataset.worldId) === String(selectedId));
    });
    const selectedEl = optionsContainer.querySelector('.world-search-option.selected');
    if (selectedEl) {
      selectedEl.scrollIntoView({ block: 'nearest' });
    }
  }

  if (searchInput) {
    searchInput.value = '';
    filterWorldSearchDropdown('');
    setTimeout(() => searchInput.focus(), 10);
  }
}

function closeWorldSearchDropdown() {
  const dropdown = document.getElementById('worldSearchDropdown');
  const trigger = document.getElementById('worldSearchTrigger');
  const searchInput = document.getElementById('worldSearchInput');
  if (!dropdown) return;

  dropdown.classList.remove('open');
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
  dropdown.setAttribute('aria-hidden', 'true');

  if (searchInput) {
    searchInput.value = '';
    filterWorldSearchDropdown('');
  }
}

function toggleWorldSearchDropdown() {
  const dropdown = document.getElementById('worldSearchDropdown');
  if (!dropdown) return;
  if (dropdown.classList.contains('open')) {
    closeWorldSearchDropdown();
  } else {
    openWorldSearchDropdown();
  }
}

function filterWorldSearchDropdown(keyword) {
  const normalized = (keyword || '').toLowerCase().trim();
  const filtered = normalized
    ? worldListCache.filter(world => {
        const name = (world.name || '').toLowerCase();
        const desc = (world.description || '').toLowerCase();
        return name.includes(normalized) || desc.includes(normalized);
      })
    : worldListCache;
  renderWorldSearchOptions(filtered);
}

function getCachedWorld(worldId) {
  if (!worldId) return null;
  const idNum = parseInt(worldId, 10);
  if (Number.isNaN(idNum)) {
    return null;
  }
  return worldListCache.find(world => world.id === idNum) || null;
}

// Handle world selection change
function handleWorldSelectionChange(worldId) {
  const parsedWorldId = worldId ? parseInt(worldId, 10) : null;
  state.defaultWorldId = Number.isNaN(parsedWorldId) ? null : parsedWorldId;

  console.log('[世界选择] worldId参数:', worldId, '解析后的ID:', parsedWorldId, '最终state.defaultWorldId:', state.defaultWorldId);

  // Update visual state
  updateWorldSelectorState();

  // Persist default world to workflow
  const workflowId = typeof getWorkflowIdFromUrl === 'function' ? getWorkflowIdFromUrl() : null;
  if (workflowId && typeof saveDefaultWorld === 'function') {
    saveDefaultWorld(workflowId, state.defaultWorldId);
  }

  // 新建工作流（画风为空）时，自动继承世界的画风和构图倾向
  if (parsedWorldId && !state.style.name) {
    const world = getCachedWorld(parsedWorldId);
    if (world && (world.visual_style || world.composition_preference)) {
      console.log('[世界选择] 工作流画风为空，自动继承世界画风:', world.visual_style, '构图倾向:', world.composition_preference);
      if (world.visual_style) {
        state.style.name = world.visual_style;
      }
      if (world.composition_preference) {
        state.style.compositionPreference = world.composition_preference;
      }
      // 异步保存画风到工作流（等待 saveDefaultWorld 完成后再执行，避免竞态）
      if (workflowId) {
        setTimeout(function() { _saveWorldStyleToWorkflow(workflowId); }, 100);
      }
    }
  }
}

// Save default world to workflow
async function saveDefaultWorld(workflowId, worldId) {
  try {
    const response = await fetch(`/api/video-workflow/${workflowId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      },
      body: JSON.stringify({
        default_world_id: worldId
      })
    });
    
    const result = await response.json();
    
    if (result.code === 0) {
      console.log('Default world saved successfully');
    } else {
      console.warn('Failed to save default world:', result.message);
    }
  } catch (error) {
    console.error('Error saving default world:', error);
  }
}

// 将世界的画风和构图倾向保存到工作流
async function _saveWorldStyleToWorkflow(workflowId) {
  // 工作流未就绪或没有节点，跳过画风同步
  if(!state.workflowReady || state.nodes.length === 0){
    console.warn('[世界画风] 工作流未就绪，跳过画风同步');
    return;
  }
  try {
    const response = await fetch(`/api/video-workflow/${workflowId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      },
      body: JSON.stringify({
        style: state.style.name || null,
        style_reference_image: state.style.referenceImageUrl || null,
        workflow_data: typeof serializeWorkflow === 'function' ? serializeWorkflow() : null
      })
    });

    const result = await response.json();
    if (result.code === 0) {
      console.log('[世界画风] 已将世界画风同步到工作流');
    } else {
      console.warn('[世界画风] 同步失败:', result.message);
    }
  } catch (error) {
    console.error('[世界画风] 同步出错:', error);
  }
}

// Update world selector visual state (red if no world selected)
function updateWorldSelectorState() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  const trigger = document.getElementById('worldSearchTrigger');
  const triggerText = document.getElementById('worldSearchTriggerText');

  if (defaultWorldSelect) {
    if (!defaultWorldSelect.value) {
      defaultWorldSelect.classList.add('no-world-selected');
      defaultWorldSelect.title = '请选择或创建世界';
    } else {
      defaultWorldSelect.classList.remove('no-world-selected');
      defaultWorldSelect.title = '选择默认世界';
    }
  }

  // 同步自定义搜索触发器显示
  if (trigger) {
    const worldId = defaultWorldSelect ? defaultWorldSelect.value : '';
    if (!worldId) {
      trigger.classList.add('no-world-selected');
      if (triggerText) {
        triggerText.textContent = window.t ? window.t('select_world') : '选择世界...';
      }
    } else {
      trigger.classList.remove('no-world-selected');
      const world = getCachedWorld(worldId);
      if (triggerText) {
        triggerText.textContent = world ? world.name : (window.t ? window.t('select_world') : '选择世界...');
      }
    }
  }
}

// Open world creation modal (复用现有的createWorldModal)
function openWorldCreationModal() {
  const modal = document.getElementById('createWorldModal');
  const nameInput = document.getElementById('createWorldNameInput');
  const descInput = document.getElementById('createWorldDescInput');
  
  if (!modal) {
    console.error('World creation modal not found');
    return;
  }
  
  // Clear inputs
  if (nameInput) nameInput.value = '';
  if (descInput) descInput.value = '';
  
  // Show modal
  modal.setAttribute('aria-hidden', 'false');
  modal.classList.add('show');
}

function openEditWorldModal() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  const editModal = document.getElementById('editWorldModal');
  const nameInput = document.getElementById('editWorldNameInput');
  const descInput = document.getElementById('editWorldDescInput');
  if (!defaultWorldSelect || !editModal || !nameInput || !descInput) {
    return;
  }
  const selectedWorldId = defaultWorldSelect.value;
  if (!selectedWorldId) {
    showToast('请先选择要编辑的世界', 'error');
    return;
  }
  const world = getCachedWorld(selectedWorldId);
  if (!world) {
    showToast('未找到所选世界，请刷新后重试', 'error');
    return;
  }
  nameInput.value = world.name || '';
  descInput.value = world.description || '';
  editModal.dataset.worldId = world.id;
  editModal.setAttribute('aria-hidden', 'false');
  editModal.classList.add('show');
}

function closeEditWorldModal() {
  const editModal = document.getElementById('editWorldModal');
  if (!editModal) return;
  editModal.classList.remove('show');
  editModal.setAttribute('aria-hidden', 'true');
  delete editModal.dataset.worldId;
}

async function saveEditedWorld() {
  const editModal = document.getElementById('editWorldModal');
  const nameInput = document.getElementById('editWorldNameInput');
  const descInput = document.getElementById('editWorldDescInput');
  const saveBtn = document.getElementById('editWorldSaveBtn');
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  if (!editModal || !nameInput || !saveBtn || !defaultWorldSelect) return;

  const worldId = editModal.dataset.worldId;
  if (!worldId) {
    showToast('未找到要编辑的世界', 'error');
    return;
  }

  const name = nameInput.value.trim();
  if (!name) {
    showToast('世界名称不能为空', 'error');
    nameInput.focus();
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = '保存中...';

  try {
    const response = await fetch(`/api/worlds/${worldId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      },
      body: JSON.stringify({
        name,
        description: descInput.value.trim() || null
      })
    });

    const result = await response.json();

    if (result.code === 0) {
      showToast('世界更新成功', 'success');
      closeEditWorldModal();
      await populateWorldSelector();
      if (defaultWorldSelect) {
        defaultWorldSelect.value = worldId;
        handleWorldSelectionChange(worldId);
      }
    } else {
      showToast(result.message || '更新失败', 'error');
    }
  } catch (error) {
    console.error('更新世界失败:', error);
    showToast('更新世界失败，请稍后重试', 'error');
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = '保存';
  }
}

async function deleteCurrentWorld() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  if (!defaultWorldSelect) return;
  const worldId = defaultWorldSelect.value;
  if (!worldId) {
    showToast('请先选择要删除的世界', 'error');
    return;
  }
  const world = getCachedWorld(worldId);
  const confirmMessage = world
    ? `确定删除世界「${world.name}」吗？该操作不可撤销。`
    : '确定删除当前选择的世界吗？';
  if (!confirm(confirmMessage)) {
    return;
  }
  try {
    const response = await fetch(`/api/worlds/${worldId}`, {
      method: 'DELETE',
      headers: {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      }
    });
    const result = await response.json();
    if (result.code === 0) {
      showToast('世界删除成功', 'success');
      await populateWorldSelector();
      defaultWorldSelect.value = '';
      handleWorldSelectionChange('');
    } else {
      showToast(result.message || '删除失败', 'error');
    }
  } catch (error) {
    console.error('删除世界失败:', error);
    showToast('删除世界失败，请稍后重试', 'error');
  }
}

// 在世界创建成功后更新左上角的世界选择器（供events.js中的createWorld调用）
async function onWorldCreated(worldId) {
  // Reload worlds and select the new one
  await populateWorldSelector();
  
  if (worldId) {
    const defaultWorldSelect = document.getElementById('defaultWorldSelect');
    if (defaultWorldSelect) {
      defaultWorldSelect.value = worldId;
      handleWorldSelectionChange(worldId);
    }
  }
}

// Initialize world selector
async function initWorldSelector() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  const createWorkflowBtn = document.getElementById('createWorkflowBtn');
  const editWorldModal = document.getElementById('editWorldModal');
  const editWorldSaveBtn = document.getElementById('editWorldSaveBtn');
  const editWorldCancelBtn = document.getElementById('editWorldCancelBtn');
  const editWorldModalClose = document.getElementById('editWorldModalClose');
  const worldSearchTrigger = document.getElementById('worldSearchTrigger');
  const worldSearchInput = document.getElementById('worldSearchInput');
  const worldSearchDropdown = document.getElementById('worldSearchDropdown');

  if (!defaultWorldSelect) return;

  // Load worlds（await 确保下拉框选项填充完成，避免 loadWorkflow 时
  // defaultWorldSelect.value 设值失效）
  await populateWorldSelector();

  // Handle selection change
  defaultWorldSelect.addEventListener('change', (e) => {
    handleWorldSelectionChange(e.target.value);
  });

  // 自定义可搜索下拉事件
  if (worldSearchTrigger) {
    worldSearchTrigger.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleWorldSearchDropdown();
    });
  }

  if (worldSearchInput) {
    worldSearchInput.addEventListener('input', (e) => {
      e.stopPropagation();
      filterWorldSearchDropdown(e.target.value);
    });

    worldSearchInput.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') {
        closeWorldSearchDropdown();
      }
    });

    // 阻止输入框点击冒泡，避免误关闭下拉
    worldSearchInput.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  }

  if (worldSearchDropdown) {
    worldSearchDropdown.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  }

  // 点击外部关闭下拉
  document.addEventListener('click', () => {
    closeWorldSearchDropdown();
  });

  // Handle create workflow button (新建画布)
  if (createWorkflowBtn) {
    createWorkflowBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeWorldSearchDropdown();
      // create_workflow_modal.js 暴露的全局函数
      if (typeof window.openCreateWorkflowModal === 'function') {
        window.openCreateWorkflowModal();
      } else {
        console.error('[新建画布] create_workflow_modal.js 未加载，无法打开弹窗');
      }
    });
  }

  if (editWorldModal) {
    if (editWorldSaveBtn) {
      editWorldSaveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        saveEditedWorld();
      });
    }
    if (editWorldCancelBtn) {
      editWorldCancelBtn.addEventListener('click', (e) => {
        e.preventDefault();
        closeEditWorldModal();
      });
    }
    if (editWorldModalClose) {
      editWorldModalClose.addEventListener('click', (e) => {
        e.preventDefault();
        closeEditWorldModal();
      });
    }
    editWorldModal.addEventListener('click', (e) => {
      if (e.target === editWorldModal) {
        closeEditWorldModal();
      }
    });
  }
}

// 加载并显示版本信息
async function loadAndDisplayEditionInfo() {
  try {
    const editionInfo = await getEditionInfo();
    state.editionInfo = editionInfo;
    
    const editionBadge = document.getElementById('editionBadge');
    if (editionBadge && editionInfo.mode === 'community') {
      editionBadge.style.display = 'inline-block';
      editionBadge.textContent = '公共空间';
      editionBadge.title = '社区版：所有用户共享资源空间';
    } else if (editionBadge) {
      editionBadge.style.display = 'none';
    }
  } catch (error) {
    console.error('Failed to load edition info:', error);
  }
}
