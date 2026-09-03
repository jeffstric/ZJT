// ============================
// director_stage_node.js - 导演台节点
// 节点壳：画布内展示快照缩略图 + 入口按钮
// 3D 编辑器实现在 director_stage_editor.js（依赖 three.min.js）
// ============================

(function () {

  var DIRECTOR_STAGE_PORTS = [
    // 全景环境输入：接收 360 全景图节点的输出，把全景作为导演台 3D 场景的环境背景
    { direction: 'input', titleI18nKey: 'director_stage_env_port', acceptType: 'panorama', connectionType: 'connections', cssClass: 'ds-env-port' }
  ];

  function directorShellHtml() {
    return '<div class="ds-node-preview ds-open-editor" title="打开导演台">' +
        '<img class="ds-node-snapshot" style="display:none;" alt="" />' +
        '<div class="ds-node-preview-empty">' +
          '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">' +
            '<rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 10L21 8V16L16 14V10Z"/>' +
            '<circle cx="8.5" cy="12" r="1.6"/><path d="M12 12h2"/>' +
          '</svg>' +
          '<span>' + (window.t ? window.t('director_stage_empty_hint') : '点击进入导演台，摆人偶、调姿态、设镜头') + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="ds-node-actions">' +
        '<button type="button" class="ds-node-btn primary ds-open-editor" style="width:100%;">' +
          (window.t ? window.t('director_stage_open') : '🎬 打开导演台') +
        '</button>' +
      '</div>' +
      '<div class="ds-node-meta">' +
        '<span class="ds-meta-puppets">🧍 ' + (window.t ? window.t('director_stage_puppets_zero') : '人偶 ×0') + '</span>' +
        '<span class="ds-meta-shot">🎥 FOV --</span>' +
        '<span class="ds-meta-env" style="display:none;">🌐 ' + (window.t ? window.t('director_stage_env_badge') : '全景环境') + '</span>' +
      '</div>' +
      '<div class="ds-node-hint" style="margin-top:6px; font-size:11px; color:#6b7280; text-align:center;">' +
        (window.t ? window.t('director_stage_export_hint') : '在导演台中「导出快照」会自动生成图片节点') +
      '</div>';
  }

  function createDirectorStageNode(opts) {
    return createNodeBase({
      type: 'director_stage',
      title: function () { return window.t ? window.t('director_stage_title') : '导演台'; },
      defaultData: {
        directorData: null,
        snapshotUrl: '',
        snapshotRatio: ''
      },
      ports: DIRECTOR_STAGE_PORTS,
      width: 300,
      height: 250,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 10L21 8V16L16 14V10Z"/></svg>',
      bodyHtml: function () { return directorShellHtml(); },
      onCreated: function (node, el) {
        bindDirectorStageEvents(node, el);
      }
    }, opts);
  }

  function bindDirectorStageEvents(node, el) {
    el.querySelectorAll('.ds-open-editor').forEach(function (elm) {
      elm.addEventListener('click', function () {
        if (window.DirectorStageEditor) {
          window.DirectorStageEditor.open(node.id);
        } else {
          showToast('导演台编辑器未加载，请刷新页面', 'error');
        }
      });
    });
  }

  // 在导演台节点右侧创建展示快照的图片节点并连线（由编辑器导出快照时调用）
  // node: 导演台节点；url: 快照服务器地址；ratio: 快照画幅
  function createDirectorStageImageNode(node, url, ratio) {
    if (!node || !url) return null;

    // 已生成的快照图片节点数（用于纵向错开，避免重叠）
    var count = state.connections.filter(function (c) { return c.from === node.id; }).length;

    var newNodeId = createImageNode({
      x: node.x + 380,
      y: node.y + count * 300,
      checkCollision: true
    });

    var newNode = state.nodes.find(function (n) { return n.id === newNodeId; });
    if (!newNode) return null;

    var imgNodeName = (window.t ? window.t('director_stage_image_name') : '导演台快照') + (count > 0 ? ' ' + (count + 1) : '');
    newNode.data.name = imgNodeName;
    newNode.data.url = url;
    newNode.data.preview = url;
    newNode.data.ratio = ratio || '16:9';
    newNode.title = imgNodeName;

    var newEl = canvasEl.querySelector('.node[data-node-id="' + newNodeId + '"]');
    if (newEl) {
      var titleEl = newEl.querySelector('.node-title');
      if (titleEl) titleEl.textContent = imgNodeName;
      // 图片预览回填：与 image_node.js 上传/恢复逻辑一致（.image-preview + 显示 preview-row）
      var previewImg = newEl.querySelector('.image-preview');
      var previewRow = newEl.querySelector('.image-preview-row');
      if (previewImg) {
        previewImg.src = typeof proxyImageUrl === 'function' ? proxyImageUrl(url) : url;
        if (previewRow) previewRow.style.display = 'flex';
      }
      var ratioEl = newEl.querySelector('.image-ratio');
      if (ratioEl) ratioEl.value = newNode.data.ratio;
    }

    state.connections.push({
      id: state.nextConnId++,
      from: node.id,
      to: newNodeId
    });

    renderAllConnections();
    renderMinimap();
    if (typeof safeAutoSave === 'function') safeAutoSave();
    return newNodeId;
  }

  // 编辑器内数据变化时刷新节点壳显示（由 director_stage_editor.js 调用）
  function updateDirectorStageNodeShell(nodeId) {
    var node = state.nodes.find(function (n) { return n.id === nodeId; });
    if (!node) return;
    var el = canvasEl.querySelector('.node[data-node-id="' + nodeId + '"]');
    if (!el) return;

    var imgEl = el.querySelector('.ds-node-snapshot');
    var emptyEl = el.querySelector('.ds-node-preview-empty');
    if (node.data.snapshotUrl) {
      var url = normalizeImageUrl ? normalizeImageUrl(node.data.snapshotUrl) : node.data.snapshotUrl;
      if (imgEl) {
        imgEl.src = url;
        imgEl.style.display = 'block';
      }
      if (emptyEl) emptyEl.style.display = 'none';
    }

    var d = node.data.directorData;
    var puppetCount = d && d.puppets ? d.puppets.length : 0;
    var pupEl = el.querySelector('.ds-meta-puppets');
    if (pupEl) {
      pupEl.textContent = '🧍 ' + (window.t ? window.t('director_stage_puppets_count', { count: puppetCount }) : ('人偶 ×' + puppetCount));
    }
    var shotEl = el.querySelector('.ds-meta-shot');
    if (shotEl && d && d.camera) {
      shotEl.textContent = '🎥 FOV ' + Math.round(d.camera.fov || 35) + '°';
    }
    var envEl = el.querySelector('.ds-meta-env');
    if (envEl) {
      envEl.style.display = (d && d.environment && d.environment.url) ? '' : 'none';
    }
  }

  var createDirectorStageNodeWithData = createNodeWithDataFactory(
    createDirectorStageNode,
    function (el, node) {
      // 工作流重载后复原：快照缩略图 + 人偶/镜头统计（场景数据存于 node.data.directorData，编辑器打开时恢复）
      updateDirectorStageNodeShell(node.id);
    }
  );

  // 注册到全局
  window.createDirectorStageNode = createDirectorStageNode;
  window.createDirectorStageNodeWithData = createDirectorStageNodeWithData;
  window.updateDirectorStageNodeShell = updateDirectorStageNodeShell;
  window.createDirectorStageImageNode = createDirectorStageImageNode;

  // 注册环境输入端口：接受 360 全景图节点连线，导入全景作为导演台环境
  registerInputPorts('director_stage', [{
    selector: '.ds-env-port',
    portType: 'environment',
    accepts: ['panorama'],
    connectionType: 'connections',
    guard: function (node) {
      // 全景节点无生成结果时也可连线（等待生成后手动刷新），不做硬限制
      return true;
    },
    onConnect: function (fromNode, targetNode) {
      var url = fromNode.data && fromNode.data.url;
      if (!url) {
        showToast(window.t ? window.t('director_stage_env_no_result') : '全景节点还没有生成结果，生成后请在导演台中刷新环境', 'info');
        return;
      }
      if (!targetNode.data.directorData) targetNode.data.directorData = {};
      targetNode.data.directorData.environment = {
        url: url,
        ratio: fromNode.data.ratio || '21:9',
        yaw: 0
      };
      if (typeof updateDirectorStageNodeShell === 'function') updateDirectorStageNodeShell(targetNode.id);
      if (typeof safeAutoSave === 'function') safeAutoSave();
      showToast(window.t ? window.t('director_stage_env_connected') : '全景环境已导入导演台', 'success');
    }
  }]);

  // 断开环境连线时清除导演台环境（由 nodes.js removeConnection 调用）
  window.handleDirectorStageEnvDisconnect = function (fromNodeId, toNode) {
    if (!toNode || toNode.type !== 'director_stage') return;
    var d = toNode.data.directorData;
    var fromNode = state.nodes.find(function (n) { return n.id === fromNodeId; });
    if (!d || !d.environment) return;
    if (fromNode && fromNode.type === 'panorama' && fromNode.data.url !== d.environment.url) return; // 环境已来自其他来源
    d.environment = null;
    if (typeof updateDirectorStageNodeShell === 'function') updateDirectorStageNodeShell(toNode.id);
    if (typeof safeAutoSave === 'function') safeAutoSave();
  };

  // 注册到节点注册表
  registerNodeType('director_stage', {
    createFn: createDirectorStageNode,
    createWithDataFn: createDirectorStageNodeWithData
  });

})();
