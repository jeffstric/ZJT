/**
 * 视频工作流 → 故事板 切换入口（见 docs/storyboard/storyboard_workflow_conversion.md）
 *
 * 顶部「转故事板」按钮：先把挂起的自动保存落盘（flushAutoSave + 短暂等待），
 * 再 POST /api/storyboard/from-workflow（服务端按 workflow_id 幂等 upsert 场景），
 * 成功后跳转故事板编辑器。
 */
(function () {
  var FLUSH_WAIT_MS = 800;

  function workflowIdFromUrl() {
    var params = new URLSearchParams(window.location.search);
    return params.get('id') || params.get('workflow_id');
  }

  function t(key, fallback) {
    try {
      var v = window.t && window.t(key);
      return (v && v !== key) ? v : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function toast(message, type) {
    if (typeof showToast === 'function') {
      showToast(message, type || '');
    } else {
      window.alert(message);
    }
  }

  function requestStoryboardConversion(workflowId) {
    var userId = '';
    var token = '';
    try {
      userId = localStorage.getItem('user_id') || '';
      token = localStorage.getItem('auth_token') || '';
    } catch (e) { /* 隐私模式等场景忽略 */ }
    var headers = { 'Content-Type': 'application/json' };
    if (userId) headers['X-User-Id'] = userId;
    if (token) {
      headers.Authorization = token.indexOf('Bearer ') === 0 ? token : 'Bearer ' + token;
    }
    return fetch('/api/storyboard/from-workflow', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ workflow_id: Number(workflowId) }),
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        if (!resp.ok || !data.success) {
          var err = new Error(data.error || data.message || ('HTTP ' + resp.status));
          err.status = resp.status;
          throw err;
        }
        return data;
      });
    });
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function handleConvert(btn) {
    var workflowId = workflowIdFromUrl();
    if (!workflowId) {
      toast(t('msg_storyboard_need_save', '画布尚未保存，请先保存后再转换故事板'), 'warning');
      return;
    }
    btn.disabled = true;
    // 先把挂起的自动保存触发出去；等待片刻让 PUT 尽量到达服务端，
    // 转换读取的是服务端数据，直接跳过可能丢最后一次编辑。
    try {
      if (typeof flushAutoSave === 'function') flushAutoSave();
    } catch (e) { /* 忽略，按服务端现状转换 */ }

    sleep(FLUSH_WAIT_MS)
      .then(function () { return requestStoryboardConversion(workflowId); })
      .then(function (data) {
        window.location.href = '/storyboard?id=' + encodeURIComponent(data.storyboard_id);
      })
      .catch(function (err) {
        btn.disabled = false;
        toast(t('msg_storyboard_convert_failed', '转换故事板失败：') + (err && err.message ? err.message : ''), 'error');
      });
  }

  function bind() {
    var btn = document.getElementById('toStoryboardBtn');
    if (!btn || btn.dataset.conversionBound === '1') return;
    btn.dataset.conversionBound = '1';
    btn.addEventListener('click', function () { handleConvert(btn); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
