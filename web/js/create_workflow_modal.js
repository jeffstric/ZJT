// 新建画布模态框逻辑
// 在 video_workflow.html 左上角「新建画布」按钮被点击时触发，
// 提交后调用后端 POST /api/video-workflow/create 创建工作流，
// 创建成功后跳转到 /video-workflow?id=xxx 进入画布页
// （画布页 getWorkflowIdFromUrl 以 id 为主参数，与列表页跳转保持一致）

(function () {
  // 避免重复初始化
  if (window.__createWorkflowModalInited) return;

  // DOM 元素引用（一次性获取）
  let modalEl = null;
  let nameInputEl = null;
  let worldSelectEl = null;
  let ratioGroupEl = null;
  let saveBtnEl = null;
  let cancelBtnEl = null;
  let closeBtnEl = null;

  // 默认比例
  const DEFAULT_RATIO = '16:9';

  /**
   * 更新比例卡片的选中态样式（兼容不支持 :has() 的浏览器）
   */
  function updateWorkflowRatioStyles() {
    if (!ratioGroupEl) return;
    ratioGroupEl.querySelectorAll('.ratio-option').forEach(option => {
      const radio = option.querySelector('input[type="radio"]');
      if (radio && radio.checked) {
        option.classList.add('checked');
      } else {
        option.classList.remove('checked');
      }
    });
  }

  /**
   * 填充世界下拉选项，复用 world.js 的 worldListCache
   */
  async function populateWorkflowWorldOptions() {
    if (!worldSelectEl) return;

    // 清空并保留默认占位项
    const placeholderText = (window.t && window.t('select_world_placeholder')) || '选择世界（可选）';
    worldSelectEl.innerHTML = '<option value="">' + escapeHtmlSafe(placeholderText) + '</option>';

    // 复用 world.js 的全局缓存（若缓存为空则触发一次加载）
    let worlds = [];
    if (typeof worldListCache !== 'undefined' && Array.isArray(worldListCache) && worldListCache.length > 0) {
      worlds = worldListCache;
    } else if (typeof loadWorlds === 'function') {
      try {
        worlds = await loadWorlds();
      } catch (err) {
        console.error('[新建画布] 加载世界列表失败:', err);
        worlds = [];
      }
    }

    worlds.forEach(world => {
      const option = document.createElement('option');
      option.value = world.id;
      option.textContent = world.name;
      worldSelectEl.appendChild(option);
    });

    // 若当前画布已有选中世界，预选它
    if (typeof state !== 'undefined' && state.defaultWorldId) {
      worldSelectEl.value = state.defaultWorldId;
    } else {
      worldSelectEl.value = '';
    }
  }

  function escapeHtmlSafe(str) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(str);
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * 打开新建画布弹窗
   */
  async function openCreateWorkflowModal() {
    if (!modalEl) {
      console.error('[新建画布] 未找到 #createWorkflowModal');
      return;
    }

    // 清空表单
    if (nameInputEl) nameInputEl.value = '';

    // 填充世界选项（异步）
    await populateWorkflowWorldOptions();

    // 画幅比例默认值：优先继承当前画布的 state.ratio，找不到时降级到 16:9
    let initialRatio = DEFAULT_RATIO;
    try {
      if (typeof state !== 'undefined' && state && state.ratio) {
        initialRatio = state.ratio;
      }
    } catch (err) {
      /* state 未定义时降级 */
    }
    let targetRadio = ratioGroupEl && ratioGroupEl.querySelector(`input[name="createWorkflowRatio"][value="${initialRatio}"]`);
    if (!targetRadio) {
      // 兜底：当继承的值不在选项中（例如未知比例），降级到默认 16:9
      targetRadio = ratioGroupEl && ratioGroupEl.querySelector(`input[name="createWorkflowRatio"][value="${DEFAULT_RATIO}"]`);
    }
    if (targetRadio) {
      targetRadio.checked = true;
    }
    updateWorkflowRatioStyles();

    // 显示弹窗
    modalEl.setAttribute('aria-hidden', 'false');
    modalEl.classList.add('show');

    // 自动聚焦名称输入框
    if (nameInputEl) {
      setTimeout(() => nameInputEl.focus(), 10);
    }
  }

  /**
   * 关闭新建画布弹窗
   */
  function closeCreateWorkflowModal() {
    if (!modalEl) return;
    modalEl.classList.remove('show');
    modalEl.setAttribute('aria-hidden', 'true');
  }

  /**
   * 提交创建请求
   */
  async function submitCreateWorkflow() {
    if (!saveBtnEl) return;

    // 登录校验
    if (typeof ensureLoggedIn === 'function' && !ensureLoggedIn()) return;

    const name = nameInputEl ? nameInputEl.value.trim() : '';
    const worldId = worldSelectEl ? worldSelectEl.value : '';
    const ratioRadio = ratioGroupEl && ratioGroupEl.querySelector('input[name="createWorkflowRatio"]:checked');
    const ratio = ratioRadio ? ratioRadio.value : '';

    // 字段校验
    if (!name) {
      const msg = (window.t && window.t('toast_workflow_name_required')) || '请输入工作流名称';
      showToast(msg, 'error');
      if (nameInputEl) nameInputEl.focus();
      return;
    }
    if (!ratio) {
      const msg = (window.t && window.t('toast_ratio_required')) || '请选择画幅比例';
      showToast(msg, 'error');
      return;
    }

    // 组装请求体（参考列表页 createWorkflowData 字段约定）
    const data = {
      name: name,
      status: 1,
      workflow_ratio: ratio
    };
    if (worldId) {
      const parsedWorldId = parseInt(worldId, 10);
      if (!Number.isNaN(parsedWorldId)) {
        data.default_world_id = parsedWorldId;
      }
    }

    // 防重复提交
    const originalText = saveBtnEl.textContent;
    saveBtnEl.disabled = true;
    const submittingText = (window.t && window.t('creating_btn')) || '创建中...';
    saveBtnEl.textContent = submittingText;

    try {
      const response = await fetch('/api/video-workflow/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': (typeof getAuthToken === 'function') ? getAuthToken() : '',
          'X-User-Id': (typeof getUserId === 'function') ? getUserId() : ''
        },
        body: JSON.stringify(data)
      });

      const result = await response.json();

      if (result.code === 0 && result.data && result.data.id) {
        const successMsg = (window.t && window.t('toast_create_success')) || '创建成功';
        showToast(successMsg, 'success');
        closeCreateWorkflowModal();
        // 跳转到新建的画布（必须用 id=，与列表页/getWorkflowIdFromUrl 一致；
        // 误用 workflow_id= 会导致 loadWorkflow 读不到 ID，世界和比例保持默认）
        const newWorkflowId = result.data.id;
        // 给 toast 一点展示时间再跳转
        setTimeout(() => {
          window.location.href = '/video-workflow?id=' + encodeURIComponent(newWorkflowId);
        }, 300);
      } else {
        const failMsg = result.message || ((window.t && window.t('toast_operation_failed')) || '创建失败，请稍后重试');
        showToast(failMsg, 'error');
      }
    } catch (err) {
      console.error('[新建画布] 创建失败:', err);
      const errMsg = (window.t && window.t('toast_operation_failed')) || '创建失败，请稍后重试';
      showToast(errMsg, 'error');
    } finally {
      saveBtnEl.disabled = false;
      saveBtnEl.textContent = originalText;
    }
  }

  /**
   * 初始化：绑定事件（在 DOM 就绪后调用）
   */
  function initCreateWorkflowModal() {
    if (window.__createWorkflowModalInited) return;

    modalEl = document.getElementById('createWorkflowModal');
    nameInputEl = document.getElementById('createWorkflowNameInput');
    worldSelectEl = document.getElementById('createWorkflowWorldSelect');
    ratioGroupEl = document.getElementById('createWorkflowRatioGroup');
    saveBtnEl = document.getElementById('createWorkflowSaveBtn');
    cancelBtnEl = document.getElementById('createWorkflowCancelBtn');
    closeBtnEl = document.getElementById('createWorkflowModalClose');

    if (!modalEl) {
      // 不在 video_workflow.html 页面时直接跳过
      return;
    }

    // 暴露给 world.js 调用（按钮 click 事件由 world.js 的 initWorldSelector 统一绑定，
    // 避免重复触发）
    window.openCreateWorkflowModal = openCreateWorkflowModal;

    // 关闭/取消按钮
    if (closeBtnEl) {
      closeBtnEl.addEventListener('click', (e) => {
        e.preventDefault();
        closeCreateWorkflowModal();
      });
    }
    if (cancelBtnEl) {
      cancelBtnEl.addEventListener('click', (e) => {
        e.preventDefault();
        closeCreateWorkflowModal();
      });
    }

    // 保存按钮
    if (saveBtnEl) {
      saveBtnEl.addEventListener('click', (e) => {
        e.preventDefault();
        submitCreateWorkflow();
      });
    }

    // 比例卡片点击：让整个 label 可点击切换（radio 被隐藏时由 label 自动触发，这里同步更新样式）
    if (ratioGroupEl) {
      ratioGroupEl.querySelectorAll('.ratio-option').forEach(option => {
        const radio = option.querySelector('input[type="radio"]');
        if (radio) {
          radio.addEventListener('change', () => {
            updateWorkflowRatioStyles();
          });
        }
        // 点击 label 时也更新样式（部分浏览器兼容）
        option.addEventListener('click', (e) => {
          // 让 label 默认行为触发 radio 选中后再更新
          setTimeout(updateWorkflowRatioStyles, 0);
          // 阻止冒泡到 modal 的关闭逻辑
          if (e) { e.stopPropagation(); }
        });
      });
    }

    // 点击遮罩关闭
    modalEl.addEventListener('click', (e) => {
      if (e.target === modalEl) {
        closeCreateWorkflowModal();
      }
    });

    // 回车提交（名称输入框内按 Enter）
    if (nameInputEl) {
      nameInputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitCreateWorkflow();
        }
      });
    }

    // ESC 关闭
    modalEl.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeCreateWorkflowModal();
      }
    });

    window.__createWorkflowModalInited = true;
  }

  // 自动初始化（脚本在 body 末尾加载，DOM 已就绪）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCreateWorkflowModal);
  } else {
    initCreateWorkflowModal();
  }
})();
