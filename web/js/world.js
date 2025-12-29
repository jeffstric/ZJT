
// World management functionality

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
      return result.data.data;
    } else {
      console.error('Failed to load worlds:', result.message);
      return [];
    }
  } catch (error) {
    console.error('Error loading worlds:', error);
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

// Handle world selection change
function handleWorldSelectionChange(worldId) {
  state.defaultWorldId = worldId ? parseInt(worldId) : null;
  
  // Update visual state
  updateWorldSelectorState();
  
  // Save to workflow
  const workflowId = getWorkflowIdFromUrl();
  if (workflowId) {
    saveDefaultWorld(workflowId, state.defaultWorldId);
  }
  
  console.log('Default world changed to:', state.defaultWorldId);
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
}
