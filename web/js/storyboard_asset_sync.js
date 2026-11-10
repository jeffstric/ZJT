// ============================
// storyboard_asset_sync.js - 故事板 → 画布 增量资产同步（前端合并）
//
// 背景（见 docs/storyboard/storyboard_workflow_conversion.md）：
// 「故事板→工作流」为一次性转换——已关联画布直接返回，不覆盖画布内容。
// 故事板后续生成的分镜图/视频因此永远不会出现在画布上（停在转换时刻的
// 快照）。修复：已关联时 to-workflow 附带只读资产包（sync_assets），由
// 故事板页暂存 sessionStorage，画布页 loadWorkflow 完成后在内存态合并。
//
// 为什么在前端合并：画布保存模型是"前端内存态整体覆盖 workflow_data"
// （content_version 乐观锁 + last_write_id 会话互判 409）。后端直写会被
// 持有旧内存态的前端下一次 autoSave 静默回滚；前端合并则画布的唯一写者
// 仍是当前会话，多标签页并发交由既有 409 机制兜底，无新增并发类。
//
// 合并语义（与一次性转换一致，只增不改不删）：
// - 补缺失：故事板资产 URL 在画布该分镜的连线下挂节点中不存在时新建节点
// - 选中跟随故事板（入口=从故事板跳画布，故事板是最后操作端）：
//   previewImageUrl + 首帧端口连线指向选中图；选中视频连线重排到首位
//   （W→S 回转落库选中取连线第一，往返闭环）
// - 画布上删除过的节点会被再次补回（只增语义）；匹配不到分镜帧的场景跳过
// ============================

(function () {
  'use strict';

  var STORAGE_KEY = 'sb_to_canvas_asset_sync';

  /** URL 归一化：剥当前 origin 前缀，画布节点 URL 与资产包 URL 才可比对。 */
  function normalizeUrl(url) {
    var s = String(url || '');
    try {
      if (typeof location !== 'undefined' && location.origin && s.indexOf(location.origin) === 0) {
        return s.slice(location.origin.length);
      }
    } catch (e) { /* 非浏览器环境（测试）忽略 */ }
    return s;
  }

  function shotNumberOf(frame) {
    var d = (frame && frame.data) || {};
    var shot = d.shotJson || d.shotData || {};
    return shot.shot_number || '';
  }

  /** 按 shot_id 找画布分镜帧（资产包 source_shot_key = 场景 source_shot_key）。 */
  function findFrameByShotId(st, shotId) {
    var key = String(shotId || '');
    if (!key) return null;
    return (st.nodes || []).find(function (n) {
      if (!n || n.type !== 'shot_frame') return false;
      var d = n.data || {};
      var shot = d.shotJson || d.shotData || {};
      return String(shot.shot_id || '') === key;
    }) || null;
  }

  /**
   * 收集分镜帧连线下挂的某类型节点（按连线顺序）。
   * 返回 [{node, url, connIndex}]。
   */
  function connectedNodesOf(st, frameId, type) {
    var out = [];
    (st.connections || []).forEach(function (conn, idx) {
      if (conn.from !== frameId) return;
      var node = (st.nodes || []).find(function (n) { return n.id === conn.to; });
      if (node && node.type === type) {
        out.push({ node: node, url: normalizeUrl((node.data || {}).url), connIndex: idx });
      }
    });
    return out;
  }

  /** 该帧同列已有节点的最大 y（追加新节点用），无则返回 frame.y。 */
  function nextColumnY(st, frame, type) {
    var base = frame.y;
    var max = null;
    connectedNodesOf(st, frame.id, type).forEach(function (entry) {
      if (max === null || entry.node.y > max) max = entry.node.y;
    });
    return max === null ? base : max + 280;
  }

  /**
   * 纯逻辑：计算单个分镜帧的同步计划（可测）。
   * scenePayload: {first_frames:[{id,url}], videos:[{id,url}],
   *                selected_first_frame_url, selected_video_url, last_frame_url}
   * frameUrls: {images: Set(url), videos: Set(url)} 画布已有的 URL 集合
   */
  function planFrameSync(scenePayload, frameUrls) {
    var plan = {
      addImages: [],
      addVideos: [],
      selectFirstFrameUrl: '',
      selectVideoUrl: '',
      lastFrameUrl: '',
    };
    (scenePayload.first_frames || []).forEach(function (item) {
      var url = normalizeUrl(item && item.url);
      if (url && !frameUrls.images.has(url)) plan.addImages.push(url);
    });
    (scenePayload.videos || []).forEach(function (item) {
      var url = normalizeUrl(item && item.url);
      if (url && !frameUrls.videos.has(url)) plan.addVideos.push(url);
    });
    // 选中图若画布上没有（被删过），也要补建后才能指向
    var selImg = normalizeUrl(scenePayload.selected_first_frame_url);
    if (selImg) {
      plan.selectFirstFrameUrl = selImg;
      if (!frameUrls.images.has(selImg) && plan.addImages.indexOf(selImg) < 0) {
        plan.addImages.push(selImg);
      }
    }
    var selVid = normalizeUrl(scenePayload.selected_video_url);
    if (selVid) {
      plan.selectVideoUrl = selVid;
      if (!frameUrls.videos.has(selVid) && plan.addVideos.indexOf(selVid) < 0) {
        plan.addVideos.push(selVid);
      }
    }
    plan.lastFrameUrl = normalizeUrl(scenePayload.last_frame_url);
    return plan;
  }

  /**
   * 执行单个分镜帧的同步。ctx 见 applyPayload。
   * 返回 {images, videos, changed}：images/videos 新建数；changed 含选中/
   * 尾帧等无新增节点的变更（决定是否渲染保存）。
   */
  function syncFrame(frame, scenePayload, ctx) {
    var st = ctx.state;
    var shotNum = shotNumberOf(frame);
    var existingImages = connectedNodesOf(st, frame.id, 'image');
    var existingVideos = connectedNodesOf(st, frame.id, 'video');
    var frameUrls = {
      images: new Set(existingImages.map(function (e) { return e.url; })),
      videos: new Set(existingVideos.map(function (e) { return e.url; })),
    };
    var plan = planFrameSync(scenePayload, frameUrls);
    var addedImages = 0, addedVideos = 0;

    function createAssetNode(type, url, index) {
      var multi = (type === 'image'
        ? existingImages.length + plan.addImages.length
        : existingVideos.length + plan.addVideos.length) > 1;
      var label = type === 'image'
        ? '分镜' + shotNum + '图' + (multi ? String(index + 1) : '')
        : '分镜' + shotNum + '视频' + (multi ? String(index + 1) : '');
      var newX = frame.x + (type === 'image' ? 900 : 1340);
      var newY = nextColumnY(st, frame, type);
      var newNodeId = type === 'image'
        ? ctx.createImageNode({ x: newX, y: newY, checkCollision: true })
        : ctx.createVideoNode({ x: newX, y: newY, checkCollision: true });
      var node = (st.nodes || []).find(function (n) { return n.id === newNodeId; });
      if (node) {
        node.data.url = url;
        node.data.name = label;
        node.title = type === 'video' ? '分镜视频' : label;
        if (type === 'image') node.data.preview = url;
        if (type === 'video') node.data.project_id = null;
      }
      st.connections.push({ id: st.nextConnId++, from: frame.id, to: newNodeId });
      return newNodeId;
    }

    plan.addImages.forEach(function (url, i) {
      createAssetNode('image', url, existingImages.length + i);
      addedImages++;
    });
    plan.addVideos.forEach(function (url, i) {
      createAssetNode('video', url, existingVideos.length + i);
      addedVideos++;
    });

    // 选中跟随故事板：首帧槽 + 首帧端口连线只指向选中图。
    // 实际变更检测：画布当前值已一致则不置 changed（避免每次跳转白保存）
    var selectionChanged = false;
    if (plan.selectFirstFrameUrl) {
      if (frame.data.previewImageUrl !== plan.selectFirstFrameUrl) {
        frame.data.previewImageUrl = plan.selectFirstFrameUrl;
        selectionChanged = true;
      }
      var selImgEntry = connectedNodesOf(st, frame.id, 'image').find(function (e) {
        return e.url === plan.selectFirstFrameUrl;
      });
      if (selImgEntry) {
        var portConn = (st.firstFrameConnections || []).find(function (c) { return c.to === frame.id; });
        if (!portConn || portConn.from !== selImgEntry.node.id) {
          st.firstFrameConnections = (st.firstFrameConnections || []).filter(function (c) {
            return c.to !== frame.id;
          });
          st.firstFrameConnections.push({
            id: st.nextFirstFrameConnId++, from: selImgEntry.node.id, to: frame.id,
          });
          selectionChanged = true;
        }
      }
    }
    // 选中视频连线重排到该帧 video 连线首位（W→S 回转选中取连线第一）
    if (plan.selectVideoUrl) {
      var selVidEntry = connectedNodesOf(st, frame.id, 'video').find(function (e) {
        return e.url === plan.selectVideoUrl;
      });
      if (selVidEntry) {
        var vidConns = st.connections.filter(function (c) {
          if (c.from !== frame.id) return false;
          var toNode = (st.nodes || []).find(function (n) { return n.id === c.to; });
          return !!toNode && toNode.type === 'video';
        });
        if (!vidConns.length || vidConns[0].to !== selVidEntry.node.id) {
          st.connections.splice(selVidEntry.connIndex, 1);
          var firstVidIdx = st.connections.findIndex(function (c) {
            if (c.from !== frame.id) return false;
            var toNode = (st.nodes || []).find(function (n) { return n.id === c.to; });
            return !!toNode && toNode.type === 'video';
          });
          st.connections.splice(firstVidIdx < 0 ? st.connections.length : firstVidIdx, 0,
            { id: st.nextConnId++, from: frame.id, to: selVidEntry.node.id });
          selectionChanged = true;
        }
      }
    }
    // 尾帧：故事板有值才覆盖（空值不动画布已有尾帧）
    if (plan.lastFrameUrl && frame.data.lastFrameUrl !== plan.lastFrameUrl) {
      frame.data.lastFrameUrl = plan.lastFrameUrl;
      selectionChanged = true;
    }

    return {
      images: addedImages,
      videos: addedVideos,
      changed: (addedImages + addedVideos > 0) || selectionChanged,
    };
  }

  /**
   * 应用整个资产包。ctx: {state, createImageNode, createVideoNode,
   * renderAllConnections, renderMinimap, safeAutoSave, showToast}（测试注入用；
   * 生产默认取画布全局函数）。返回 {addedImages, addedVideos, skippedScenes}。
   */
  function applyPayload(payload, ctx) {
    var scenes = (payload && payload.scenes) || [];
    var addedImages = 0, addedVideos = 0, skippedScenes = 0, changed = false;
    scenes.forEach(function (scene) {
      var frame = findFrameByShotId(ctx.state, scene && scene.source_shot_key);
      if (!frame) { skippedScenes++; return; }
      var res = syncFrame(frame, scene, ctx);
      addedImages += res.images;
      addedVideos += res.videos;
      changed = changed || res.changed;
    });
    // 有新增节点或选中/尾帧同步过 → 渲染并保存；否则画布已最新，静默
    if (changed) {
      if (ctx.renderAllConnections) ctx.renderAllConnections();
      if (ctx.renderMinimap) ctx.renderMinimap();
      if (ctx.safeAutoSave) ctx.safeAutoSave();
    }
    if (ctx.showToast && (addedImages || addedVideos)) {
      ctx.showToast('已从故事板同步 ' + addedImages + ' 张分镜图 / ' + addedVideos + ' 个视频', 'success');
    }
    return { addedImages: addedImages, addedVideos: addedVideos, skippedScenes: skippedScenes, changed: changed };
  }

  /** 画布全局 state/函数（state.js 顶层 const：裸引用 + typeof 保护）。 */
  function defaultCtx() {
    return {
      state: (typeof state !== 'undefined' && state && Array.isArray(state.nodes)) ? state : null,
      createImageNode: (typeof createImageNode === 'function') ? createImageNode : null,
      createVideoNode: (typeof createVideoNode === 'function') ? createVideoNode : null,
      renderAllConnections: (typeof renderAllConnections === 'function') ? renderAllConnections : null,
      renderMinimap: (typeof renderMinimap === 'function') ? renderMinimap : null,
      safeAutoSave: (typeof safeAutoSave === 'function') ? safeAutoSave : null,
      showToast: (typeof showToast === 'function') ? showToast : null,
    };
  }

  window.StoryboardAssetSync = {
    /** 故事板页跳转前暂存资产包（payload 需带 workflow_id 供画布页校验）。 */
    stash: function (payload) {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ts: Date.now(), payload: payload }));
      } catch (e) {
        console.warn('[故事板资产同步] sessionStorage 暂存失败:', e);
      }
    },

    /**
     * 画布页 loadWorkflow 后调用：workflow_id 匹配才合并，读完即清
     * （幂等：资产包重复应用无副作用，节点 URL 去重）。
     */
    applyPending: function (workflowId) {
      var raw = null;
      try { raw = sessionStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
      if (!raw) return null;
      try {
        var entry = JSON.parse(raw);
        var payload = entry && entry.payload;
        if (!payload || Number(payload.workflow_id) !== Number(workflowId)) return null;
        try { sessionStorage.removeItem(STORAGE_KEY); } catch (e) { /* 尽力清理 */ }
        var ctx = defaultCtx();
        if (!ctx.state || !ctx.createImageNode || !ctx.createVideoNode) {
          console.warn('[故事板资产同步] 画布环境不完整，跳过合并');
          return null;
        }
        return applyPayload(payload, ctx);
      } catch (e) {
        console.warn('[故事板资产同步] 合并失败:', e);
        return null;
      }
    },
  };

  // 纯逻辑测试钩子（仅 vitest 使用，生产不依赖）
  window.StoryboardAssetSync._internals = {
    normalizeUrl: normalizeUrl,
    planFrameSync: planFrameSync,
    findFrameByShotId: findFrameByShotId,
    applyPayload: applyPayload,
  };
})();
