(function(){
  const DEFAULT_NODE_WIDTH = 320;
  const DEFAULT_NODE_HEIGHT = 220;
  const COLUMN_GAP = 120;
  const ROW_GAP = 80;
  const COLUMN_STACK_GAP = 48;
  const BASE_PADDING_X = 80;
  const BASE_PADDING_Y = 80;
  const LANE_COUNT = 1;
  const LANE_VERTICAL_GAP = 80;
  const CLUSTER_GAP_Y = 120;
  const SCRIPT_COLUMN_GAP = 80;
  const MIN_ROW_HEIGHT = LANE_COUNT * DEFAULT_NODE_HEIGHT + (LANE_COUNT - 1) * LANE_VERTICAL_GAP;

  function extractFirstNumber(text){
    if(typeof text !== 'string') return null;
    const match = text.match(/(\d+)/);
    return match ? Number(match[1]) : null;
  }

  function naturalCompareTitles(aTitle, bTitle){
    const aNum = extractFirstNumber(aTitle);
    const bNum = extractFirstNumber(bTitle);
    if(aNum !== null && bNum !== null){
      if(aNum !== bNum) return aNum - bNum;
    } else if(aNum !== null){
      return -1;
    } else if(bNum !== null){
      return 1;
    }
    return String(aTitle || '').localeCompare(String(bTitle || ''), 'zh-CN', { numeric: true, sensitivity: 'base' });
  }

  function getNodeDimensions(nodeId){
    const el = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
    if(!el){
      return { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
    }
    return {
      width: Math.max(DEFAULT_NODE_WIDTH, el.offsetWidth || DEFAULT_NODE_WIDTH),
      height: Math.max(DEFAULT_NODE_HEIGHT, el.offsetHeight || DEFAULT_NODE_HEIGHT)
    };
  }

  function positionNode(node){
    const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
    if(el){
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
    }
  }

  function forEachEdge(callback){
    const add = (conn) => callback(conn.from, conn.to);
    state.connections.forEach(add);
    state.imageConnections.forEach(add);
    state.firstFrameConnections.forEach(add);
  }

  function buildGraph(){
    const adjacency = new Map();
    const reverseAdjacency = new Map();
    const indegree = new Map();

    state.nodes.forEach(node => {
      adjacency.set(node.id, []);
      reverseAdjacency.set(node.id, []);
      indegree.set(node.id, 0);
    });

    forEachEdge((from, to) => {
      if(!adjacency.has(from) || !adjacency.has(to)) return;
      adjacency.get(from).push(to);
      reverseAdjacency.get(to).push(from);
      indegree.set(to, (indegree.get(to) || 0) + 1);
    });

    return { adjacency, reverseAdjacency, indegree };
  }

  function buildSubgraph(allowedIds){
    const adjacency = new Map();
    const indegree = new Map();

    allowedIds.forEach(id => {
      adjacency.set(id, []);
      indegree.set(id, 0);
    });

    forEachEdge((from, to) => {
      if(!allowedIds.has(from) || !allowedIds.has(to)) return;
      adjacency.get(from).push(to);
      indegree.set(to, indegree.get(to) + 1);
    });

    return { adjacency, indegree };
  }

  function collectClusterNodes(rootId, adjacency, assigned, nodeMap){
    if(assigned.has(rootId) || !nodeMap.has(rootId)) return new Set();
    const cluster = new Set();
    const queue = [rootId];

    while(queue.length){
      const currentId = queue.shift();
      if(cluster.has(currentId)) continue;
      const currentNode = nodeMap.get(currentId);
      if(!currentNode) continue;
      cluster.add(currentId);

      const neighbors = adjacency.get(currentId) || [];
      neighbors.forEach(nextId => {
        if(cluster.has(nextId) || assigned.has(nextId)) return;
        const nextNode = nodeMap.get(nextId);
        if(!nextNode) return;
        if(nextNode.type === 'shot_group' && nextId !== rootId) return;
        queue.push(nextId);
      });
    }

    return cluster;
  }

  function computeClusterDepths(rootId, adjacency, clusterSet){
    const depthMap = new Map();
    const queue = [rootId];
    depthMap.set(rootId, 0);

    while(queue.length){
      const nodeId = queue.shift();
      const neighbors = adjacency.get(nodeId) || [];
      neighbors.forEach(nextId => {
        if(!clusterSet.has(nextId)) return;
        if(depthMap.has(nextId)) return;
        depthMap.set(nextId, depthMap.get(nodeId) + 1);
        queue.push(nextId);
      });
    }

    clusterSet.forEach(id => {
      if(!depthMap.has(id)){
        depthMap.set(id, id === rootId ? 0 : (Math.max(...depthMap.values()) || 0) + 1);
      }
    });

    return depthMap;
  }

  function layoutShotGroupCluster(cluster, baseY, adjacency, reverseAdjacency, nodeMap, startX){
    if(!cluster.nodeIds.size) return { height: 0, width: 0 };

    const depthMap = computeClusterDepths(cluster.rootId, adjacency, cluster.nodeIds);
    const entries = [];
    const entryMap = new Map();
    cluster.nodeIds.forEach(id => {
      const node = nodeMap.get(id);
      if(!node) return;
      const dims = getNodeDimensions(id);
      const depth = depthMap.get(id) ?? 0;
      const entry = { node, dims, depth };
      entries.push(entry);
      entryMap.set(id, entry);
    });

    const depthGroups = new Map();
    entries.forEach(entry => {
      if(!depthGroups.has(entry.depth)) depthGroups.set(entry.depth, []);
      depthGroups.get(entry.depth).push(entry);
    });

    const sortedDepths = Array.from(depthGroups.keys()).sort((a, b) => a - b);
    const columnMeta = new Map();
    let columnCursor = startX;
    sortedDepths.forEach(depth => {
      const nodesAtDepth = depthGroups.get(depth) || [];
      nodesAtDepth.sort((a, b) => naturalCompareTitles(a.node.title, b.node.title));
      const columnWidth = nodesAtDepth.reduce((max, entry) => Math.max(max, entry.dims.width), DEFAULT_NODE_WIDTH);
      columnMeta.set(depth, { left: columnCursor, width: Math.max(columnWidth, DEFAULT_NODE_WIDTH) });
      columnCursor += Math.max(columnWidth, DEFAULT_NODE_WIDTH) + COLUMN_GAP;
    });
    const totalWidth = Math.max(0, columnCursor - COLUMN_GAP - startX);

    const shotEntries = entries
      .filter(entry => entry.node.type === 'shot_frame')
      .sort((a, b) => naturalCompareTitles(a.node.title, b.node.title));

    if(!shotEntries.length){
      let maxBottom = baseY;
      sortedDepths.forEach(depth => {
        const nodesAtDepth = depthGroups.get(depth) || [];
        let cursorY = baseY;
        const column = columnMeta.get(depth);
        nodesAtDepth.forEach(entry => {
          const targetX = Math.max(20, column.left + (column.width - entry.dims.width) / 2);
          entry.node.x = Math.round(targetX);
          entry.node.y = Math.max(20, Math.round(cursorY));
          positionNode(entry.node);
          cursorY += entry.dims.height + ROW_GAP;
          maxBottom = Math.max(maxBottom, entry.node.y + entry.dims.height);
        });
      });
      return { height: Math.max(0, maxBottom - baseY), width: totalWidth };
    }

    const rowByNodeId = new Map();
    shotEntries.forEach((entry, index) => rowByNodeId.set(entry.node.id, index));
    if(!rowByNodeId.has(cluster.rootId)){
      rowByNodeId.set(cluster.rootId, 0);
    }

    const queue = shotEntries.map(entry => entry.node.id);
    while(queue.length){
      const nodeId = queue.shift();
      const rowIndex = rowByNodeId.get(nodeId);
      const neighbors = adjacency.get(nodeId) || [];
      neighbors.forEach(nextId => {
        if(!cluster.nodeIds.has(nextId) || rowByNodeId.has(nextId)) return;
        rowByNodeId.set(nextId, rowIndex);
        queue.push(nextId);
      });
    }

    const unassigned = [];
    cluster.nodeIds.forEach(id => {
      if(rowByNodeId.has(id)) return;
      unassigned.push(id);
    });

    let safety = 0;
    let carry = unassigned;
    while(carry.length && safety < cluster.nodeIds.size){
      const remaining = [];
      carry.forEach(id => {
        const parents = reverseAdjacency.get(id) || [];
        const parentRow = parents.map(pid => rowByNodeId.get(pid)).find(row => row !== undefined);
        if(parentRow !== undefined){
          rowByNodeId.set(id, parentRow);
        } else {
          remaining.push(id);
        }
      });
      if(remaining.length === carry.length) break;
      carry = remaining;
      safety++;
    }

    let maxRowIndex = rowByNodeId.size ? Math.max(...rowByNodeId.values()) : -1;
    carry.forEach(id => {
      maxRowIndex += 1;
      rowByNodeId.set(id, maxRowIndex);
    });

    const rows = new Map();
    const rowColumnStacks = new Map();
    rowByNodeId.forEach((rowIndex, nodeId) => {
      const entry = entryMap.get(nodeId);
      if(!entry) return;
      if(!rows.has(rowIndex)) rows.set(rowIndex, []);
      rows.get(rowIndex).push(entry);
    });

    const sortedRows = Array.from(rows.keys()).sort((a, b) => a - b);
    const rowTops = new Map();
    const rowHeights = new Map();
    let cursorY = baseY;
    sortedRows.forEach(rowIndex => {
      const nodesInRow = rows.get(rowIndex) || [];
      nodesInRow.sort((a, b) => {
        if(a.depth !== b.depth) return a.depth - b.depth;
        return naturalCompareTitles(a.node.title, b.node.title);
      });

      const columnStacks = new Map();
      nodesInRow.forEach(entry => {
        if(!columnStacks.has(entry.depth)) columnStacks.set(entry.depth, []);
        columnStacks.get(entry.depth).push(entry);
      });
      columnStacks.forEach(list => {
        list.sort((a, b) => naturalCompareTitles(a.node.title, b.node.title));
      });

      const stackHeights = Array.from(columnStacks.values()).map(list => {
        return list.reduce((sum, entry, idx) => sum + entry.dims.height + (idx ? COLUMN_STACK_GAP : 0), 0);
      });
      const rowHeight = Math.max(DEFAULT_NODE_HEIGHT, ...stackHeights, nodesInRow.reduce((max, entry) => Math.max(max, entry.dims.height), DEFAULT_NODE_HEIGHT));

      rowColumnStacks.set(rowIndex, columnStacks);
      rowHeights.set(rowIndex, rowHeight);
      rowTops.set(rowIndex, cursorY);
      cursorY += rowHeight + ROW_GAP;
    });
    const clusterHeight = sortedRows.length ? Math.max(0, cursorY - ROW_GAP - baseY) : 0;

    rows.forEach((nodesInRow, rowIndex) => {
      const rowTop = rowTops.get(rowIndex) ?? baseY;
      const rowHeight = rowHeights.get(rowIndex) ?? DEFAULT_NODE_HEIGHT;
      const columnStacks = rowColumnStacks.get(rowIndex) || new Map();

      columnStacks.forEach((stackEntries, depth) => {
        const column = columnMeta.get(depth);
        if(!column) return;
        const stackHeight = stackEntries.reduce((sum, entry, idx) => sum + entry.dims.height + (idx ? COLUMN_STACK_GAP : 0), 0);
        let columnY = rowTop + (rowHeight - stackHeight) / 2;
        stackEntries.forEach(entry => {
          const targetX = Math.max(20, column.left + (column.width - entry.dims.width) / 2);
          const targetY = Math.max(20, columnY);
          entry.node.x = Math.round(targetX);
          entry.node.y = Math.round(targetY);
          positionNode(entry.node);
          columnY += entry.dims.height + COLUMN_STACK_GAP;
        });
      });
    });

    return { height: clusterHeight, width: totalWidth };
  }

  function layoutRemainingNodes(remainingNodes, startY){
    if(!remainingNodes.length) return startY;

    const allowedIds = new Set(remainingNodes.map(node => node.id));
    const { adjacency, indegree } = buildSubgraph(allowedIds);
    const layerMap = new Map();
    const queue = [];

    indegree.forEach((deg, nodeId) => {
      if(deg === 0){
        queue.push({ nodeId, layer: 0 });
      }
    });

    while(queue.length){
      const { nodeId, layer } = queue.shift();
      if(layerMap.has(nodeId)) continue;
      layerMap.set(nodeId, layer);
      const neighbors = adjacency.get(nodeId) || [];
      neighbors.forEach(nextId => {
        indegree.set(nextId, Math.max(0, indegree.get(nextId) - 1));
        if(indegree.get(nextId) === 0){
          queue.push({ nodeId: nextId, layer: layer + 1 });
        }
      });
    }

    if(layerMap.size !== allowedIds.size){
      let fallbackLayer = (Math.max(0, ...layerMap.values()) || 0) + 1;
      allowedIds.forEach(id => {
        if(layerMap.has(id)) return;
        layerMap.set(id, fallbackLayer);
        fallbackLayer++;
      });
    }

    const layers = new Map();
    remainingNodes.forEach(node => {
      const layer = layerMap.get(node.id) ?? 0;
      if(!layers.has(layer)) layers.set(layer, []);
      layers.get(layer).push(node);
    });

    const sortedLayerKeys = Array.from(layers.keys()).sort((a, b) => a - b);
    let cursorX = BASE_PADDING_X;
    const baseY = Math.max(startY, BASE_PADDING_Y);
    let maxBottom = baseY;

    sortedLayerKeys.forEach(layer => {
      const nodesInLayer = layers.get(layer);
      const columnWidth = nodesInLayer.reduce((max, node) => {
        const dims = getNodeDimensions(node.id);
        return Math.max(max, dims.width);
      }, DEFAULT_NODE_WIDTH);

      let cursorY = baseY;
      nodesInLayer.forEach(node => {
        const dims = getNodeDimensions(node.id);
        const targetX = Math.max(20, cursorX + (columnWidth - dims.width) / 2);
        node.x = Math.round(targetX);
        node.y = Math.round(cursorY);
        positionNode(node);
        cursorY += dims.height + ROW_GAP;
        maxBottom = Math.max(maxBottom, node.y + dims.height);
      });

      cursorX += columnWidth + COLUMN_GAP;
    });

    return maxBottom;
  }

  function autoArrangeNodes(){
    if(!state.nodes.length){
      showToast('暂无节点可排列', 'error');
      return;
    }

    const nodeMap = new Map(state.nodes.map(node => [node.id, node]));
    const scriptNodes = state.nodes.filter(node => node.type === 'script').sort((a, b) => naturalCompareTitles(a.title, b.title));
    const scriptColumnWidth = Math.max(
      DEFAULT_NODE_WIDTH,
      ...scriptNodes.map(node => getNodeDimensions(node.id).width || DEFAULT_NODE_WIDTH)
    );
    const scriptColumnCenterX = BASE_PADDING_X + scriptColumnWidth / 2;
    const scriptRowCenters = new Map(); // scriptId -> { sum, count }
    const referencedScriptIds = new Set();
    const { adjacency, reverseAdjacency } = buildGraph();
    const shotGroupNodes = state.nodes.filter(node => node.type === 'shot_group').sort((a, b) => naturalCompareTitles(a.title, b.title));
    const assigned = new Set();
    let currentY = BASE_PADDING_Y;

    shotGroupNodes.forEach(groupNode => {
      if(assigned.has(groupNode.id)) return;
      const clusterNodes = collectClusterNodes(groupNode.id, adjacency, assigned, nodeMap);
      if(!clusterNodes.size) return;
      const cluster = { rootId: groupNode.id, nodeIds: clusterNodes };
      const scriptConn = state.connections.find(c => c.to === groupNode.id && nodeMap.get(c.from)?.type === 'script');
      const parentScriptId = scriptConn ? scriptConn.from : null;
      const startX = BASE_PADDING_X + scriptColumnWidth + SCRIPT_COLUMN_GAP;
      const { height } = layoutShotGroupCluster(cluster, currentY, adjacency, reverseAdjacency, nodeMap, startX);
      const rowHeight = Math.max(height, MIN_ROW_HEIGHT);
      const rowCenter = currentY + rowHeight / 2;

      if(parentScriptId && nodeMap.has(parentScriptId)){
        const stats = scriptRowCenters.get(parentScriptId) || { sum: 0, count: 0 };
        stats.sum += rowCenter;
        stats.count += 1;
        scriptRowCenters.set(parentScriptId, stats);
        referencedScriptIds.add(parentScriptId);
      }

      clusterNodes.forEach(id => assigned.add(id));
      currentY += rowHeight + CLUSTER_GAP_Y;
    });

    scriptNodes.forEach(scriptNode => {
      const dims = getNodeDimensions(scriptNode.id);
      const stats = scriptRowCenters.get(scriptNode.id);
      let targetY;
      if(stats && stats.count){
        const avgCenter = stats.sum / stats.count;
        targetY = Math.max(20, Math.round(avgCenter - dims.height / 2));
      } else {
        targetY = Math.max(20, Math.round(currentY));
        currentY += dims.height + ROW_GAP;
      }
      scriptNode.x = Math.round(scriptColumnCenterX - dims.width / 2);
      scriptNode.y = targetY;
      positionNode(scriptNode);
      assigned.add(scriptNode.id);
    });

    const remainingNodes = state.nodes.filter(node => !assigned.has(node.id)).sort((a, b) => naturalCompareTitles(a.title, b.title));
    const finalBottom = layoutRemainingNodes(remainingNodes, currentY);
    currentY = Math.max(currentY, finalBottom);

    renderConnections();
    renderImageConnections();
    renderFirstFrameConnections();
    renderMinimap();
    updateCanvasSize();
    try{ autoSaveWorkflow(); }catch(e){ console.warn('自动保存失败', e); }
    showToast('自动排列完成', 'success');
  }

  const autoArrangeBtn = document.getElementById('autoArrangeBtn');
  if(autoArrangeBtn){
    autoArrangeBtn.addEventListener('click', () => {
      try {
        autoArrangeNodes();
      } catch(error){
        console.error('autoArrangeNodes error:', error);
        showToast('自动排列失败: ' + (error.message || '未知错误'), 'error');
      }
    });
  }

  window.autoArrangeNodes = autoArrangeNodes;
})();
