
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
  defaultWorldSelect.innerHTML = '<option value="">选择世界...</option>';
  
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
  
  // Update visual state
  updateWorldSelectorState();
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

// Update world selector visual state (red if no world selected)
function updateWorldSelectorState() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  if (!defaultWorldSelect) return;
  
  if (!defaultWorldSelect.value) {
    defaultWorldSelect.classList.add('no-world-selected');
    defaultWorldSelect.title = '请选择或创建世界';
  } else {
    defaultWorldSelect.classList.remove('no-world-selected');
    defaultWorldSelect.title = '选择默认世界';
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
function initWorldSelector() {
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  const createWorldBtn = document.getElementById('createWorldBtn');
  const editWorldBtn = document.getElementById('editWorldBtn');
  const deleteWorldBtn = document.getElementById('deleteWorldBtn');
  const editWorldModal = document.getElementById('editWorldModal');
  const editWorldSaveBtn = document.getElementById('editWorldSaveBtn');
  const editWorldCancelBtn = document.getElementById('editWorldCancelBtn');
  const editWorldModalClose = document.getElementById('editWorldModalClose');
  
  if (!defaultWorldSelect) return;
  
  // Load worlds
  populateWorldSelector();
  
  // Handle selection change
  defaultWorldSelect.addEventListener('change', (e) => {
    handleWorldSelectionChange(e.target.value);
  });
  
  // Handle create world button (复用现有的createWorldModal)
  if (createWorldBtn) {
    createWorldBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openWorldCreationModal();
    });
  }

  if (editWorldBtn) {
    editWorldBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openEditWorldModal();
    });
  }

  if (deleteWorldBtn) {
    deleteWorldBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      deleteCurrentWorld();
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
