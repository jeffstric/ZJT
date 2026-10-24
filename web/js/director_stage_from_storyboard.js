// ============================
// director_stage_from_storyboard.js - 故事板 3D 空间 → 导演台
//
// 故事板效果模式分镜的 3D 空间（three_scene_code，three.js 代码）在
// 「故事板 → 工作流」转换时随 shotJson 透传到分镜帧节点（见
// api/storyboard_conversion.py _scene_to_shot）。本模块在分镜帧的
// 「打开导演台」按钮触发时：
//   1. 轻量记录器重放：不依赖 three.js——helper 只记录参数，从该帧往前
//      找最近的空间序列首镜（three_scene_seq_start），按序重放到本镜，
//      得到该镜最终的角色站位与机位（增量链语义与
//      storyboard/spatial_3d_preview.js 的重放一致）；
//   2. 映射为导演台 directorData：makeActor → 人偶（两侧朝向约定一致：
//      度数、0°=+Z、90°=+X），setCamera → 机位1；场景体块/道具导演台
//      无对应概念，跳过并提示；
//   3. 首次点击自动创建导演台节点（分镜帧右侧 + 连线），写入
//      directorData 后打开编辑器；再次点击直接打开（帧记住节点 id）。
// ============================

(function () {
  'use strict';

  // ---- 轻量记录器重放（helper 契约与 LLM prompt / spatial_3d_preview.js 一一对应）----

  function createRecorderContext() {
    var ctx = {
      actors: {},   // name -> {name, x, z, facing}
      props: {},    // name -> {name, x, z, y}
      stages: {},   // name -> {name, x, z}
      camera: null, // {eye:[x,y,z], target:[x,y,z], fov}
      errors: [],
    };
    var helpers = {
      startScene: function () {
        // 与重放语义一致：startScene 清空世界重建序列
        Object.keys(ctx.actors).forEach(function (k) { delete ctx.actors[k]; });
        Object.keys(ctx.props).forEach(function (k) { delete ctx.props[k]; });
        Object.keys(ctx.stages).forEach(function (k) { delete ctx.stages[k]; });
      },
      makeStage: function (name, w, d, x, z, options) {
        ctx.stages[String(name)] = { name: String(name), x: Number(x) || 0, z: Number(z) || 0 };
      },
      makeActor: function (name, x, z, options) {
        options = options || {};
        ctx.actors[String(name)] = {
          name: String(name),
          x: Number(x) || 0,
          z: Number(z) || 0,
          facing: options.facing != null ? Number(options.facing) : 0,
        };
      },
      makeProp: function (name, x, z, options) {
        options = options || {};
        ctx.props[String(name)] = {
          name: String(name),
          x: Number(x) || 0,
          z: Number(z) || 0,
          y: options.y != null ? Number(options.y) : 0.3,
        };
      },
      moveActor: function (name, x, z, options) {
        var a = ctx.actors[String(name)];
        if (!a) throw new Error('moveActor("' + name + '")：对象不存在');
        a.x = Number(x) || 0;
        a.z = Number(z) || 0;
        if (options && options.facing != null) a.facing = Number(options.facing);
      },
      moveProp: function (name, x, z, options) {
        var p = ctx.props[String(name)];
        if (!p) throw new Error('moveProp("' + name + '")：对象不存在');
        p.x = Number(x) || 0;
        p.z = Number(z) || 0;
        if (options && options.y != null) p.y = Number(options.y);
      },
      setCamera: function (ex, ey, ez, tx, ty, tz, fov) {
        ctx.camera = {
          eye: [Number(ex), Number(ey), Number(ez)],
          target: [Number(tx), Number(ty), Number(tz)],
          fov: Number(fov) || 50,
        };
      },
    };
    return { ctx: ctx, helpers: helpers };
  }

  function runRecorderCode(ctx, helpers, code, label) {
    try {
      // 参数表与 spatial_3d_preview.js runThreeCode 完全一致（代码里可能引用
      // THREE/scene/camera 等注入名；记录器路径下 LLM 代码不会真正用到它们）
      var runner = new Function(
        'THREE', 'scene', 'camera', 'actors', 'props', 'stage',
        'startScene', 'makeStage', 'makeActor', 'makeProp',
        'moveActor', 'moveProp', 'setCamera',
        '"use strict";\n' + String(code || '')
      );
      runner({}, {}, {}, ctx.actors, ctx.props, ctx.stages,
        helpers.startScene, helpers.makeStage, helpers.makeActor, helpers.makeProp,
        helpers.moveActor, helpers.moveProp, helpers.setCamera);
    } catch (err) {
      ctx.errors.push({ shot: label, message: err && err.message ? err.message : String(err) });
    }
  }

  // ---- 分镜帧链收集与重放 ----

  function shotNumber(frameNode) {
    var shot = (frameNode.data && frameNode.data.shotJson) || {};
    return Number(shot.shot_number) || 0;
  }

  function hasThreeCode(frameNode) {
    var shot = (frameNode.data && frameNode.data.shotJson) || {};
    return typeof shot.three_scene_code === 'string' && shot.three_scene_code.trim() !== '';
  }

  function isSeqStart(frameNode) {
    var shot = (frameNode.data && frameNode.data.shotJson) || {};
    return shot.three_scene_seq_start === true;
  }

  /**
   * 从目标分镜帧往前找最近的空间序列首镜帧，顺序重放到目标帧。
   * 只认同一来源（同 storyboard 转换）的 shot_frame 链：按 shot_number
   * 升序排序后定位；无代码的帧（含旧 JSON 分镜）是链边界，从其后继续。
   */
  /**
   * 画布全局 state（state.js 顶层 const 声明：全局词法可访问但不挂
   * window，必须裸引用 + typeof 保护；vitest jsdom 环境下为 null）。
   */
  function canvasState() {
    return (typeof state !== 'undefined' && state && Array.isArray(state.nodes)) ? state : null;
  }

  function replayShotSpatialChain(frameNode) {
    var st = canvasState();
    var nodes = st ? st.nodes : [];
    var frames = nodes
      .filter(function (n) { return n.type === 'shot_frame' && hasThreeCode(n); })
      .sort(function (a, b) { return shotNumber(a) - shotNumber(b); });
    var idx = frames.indexOf(frameNode);
    if (idx < 0) return null;

    var start = idx;
    for (var i = idx; i >= 0; i--) {
      if (isSeqStart(frames[i])) { start = i; break; }
      start = i; // 无显式首镜标记时退化为链内最早已知帧
    }

    var rec = createRecorderContext();
    var replayed = 0;
    for (var j = start; j <= idx; j++) {
      var shot = frames[j].data.shotJson;
      runRecorderCode(rec.ctx, rec.helpers, shot.three_scene_code,
        frames[j].title || ('#' + shotNumber(frames[j])));
      replayed++;
    }
    rec.replayed = replayed;
    rec.chainStartNumber = shotNumber(frames[start]);
    return rec;
  }

  // ---- directorData 映射 ----

  function round2(v) { return Math.round(v * 100) / 100; }

  /**
   * 空镜检查：机位视锥内是否能看到角色（见 spatial_camera_edit.js 的
   * cameraSeesActors，两侧逻辑互为镜像，改动需同步）。
   * camera {eye:[x,y,z] 或 {x,y,z}, target:[...], fov}；actors [{x, z}]。
   * aspect 取画布当前画幅（工作流可能是 9:16 竖屏，不能硬编码 16:9）。
   */
  function aspectFromRatio(ratio, fallback) {
    fallback = fallback || 16 / 9;
    var m = /^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/.exec(String(ratio || '').trim());
    if (!m) return fallback;
    var w = Number(m[1]), h = Number(m[2]);
    return (isFinite(w) && isFinite(h) && w > 0 && h > 0) ? w / h : fallback;
  }

  function canvasAspect() {
    var st = canvasState();
    return aspectFromRatio(st && st.ratio, 16 / 9);
  }

  function cameraSeesActors(camera, actors, aspect) {
    aspect = aspect || canvasAspect();
    var list = Array.isArray(actors) ? actors : [];
    var total = list.length;
    if (!camera || !camera.eye || !camera.target) return { visible: 0, total: total };
    // eye/target 兼容数组与 {x,y,z} 对象两种格式（与 spatial_camera_edit.js 同步）
    var toArr = function (p) {
      return Array.isArray(p) ? p.map(Number) : [Number(p.x), Number(p.y), Number(p.z)];
    };
    var e = toArr(camera.eye), t = toArr(camera.target);
    var ex = e[0], ey = e[1], ez = e[2];
    var tx = t[0], ty = t[1], tz = t[2];
    if (![ex, ey, ez, tx, ty, tz].every(isFinite)) return { visible: 0, total: total };
    // three.js lookAt 基：相机 -Z 朝 target，+Z 指向后方 = normalize(eye - target)
    var zx = ex - tx, zy = ey - ty, zz = ez - tz;
    var zl = Math.hypot(zx, zy, zz);
    if (!zl) return { visible: 0, total: total };
    zx /= zl; zy /= zl; zz /= zl;
    // x = cross(up, z) = (zz, 0, -zx)；y = cross(z, x) = (zy*xaz, zz*xax - zx*xaz, -zy*xax)
    var xax = zz, xaz = -zx;
    var xl = Math.hypot(xax, xaz);
    if (!xl) return { visible: 0, total: total };
    xax /= xl; xaz /= xl;
    var yax = zy * xaz;
    var yay = zz * xax - zx * xaz;
    var yaz = -zy * xax;

    var tanV = Math.tan(((Number(camera.fov) || 50) * Math.PI) / 360);
    var tanH = tanV * aspect;
    var visible = 0;
    for (var i = 0; i < list.length; i++) {
      var a = list[i];
      if (!a || !isFinite(a.x) || !isFinite(a.z)) continue;
      var dx = a.x - ex, dy = 1.1 - ey, dz = a.z - ez; // 躯干代表点
      var vx = dx * xax + dz * xaz;
      var vy = dx * yax + dy * yay + dz * yaz;
      var vz = dx * zx + dy * zy + dz * zz;
      if (vz >= -1e-6) continue;
      if (Math.abs(vy / -vz) > tanV) continue;
      if (Math.abs(vx / -vz) > tanH) continue;
      visible++;
    }
    return { visible: visible, total: total };
  }

  /**
   * 重放结果 → 导演台 directorData（version 2，结构对齐
   * director_stage_editor.js serializeData）。
   * 无机位时给导演台默认机位（与编辑器初始 virtualCamCfg 一致）。
   */
  function buildDirectorData(rec) {
    var ctx = rec.ctx;
    var puppets = Object.keys(ctx.actors).map(function (name, i) {
      var a = ctx.actors[name];
      return {
        id: 'p_sb_' + (i + 1),
        name: a.name,
        bodyType: 'man',
        x: round2(a.x),
        z: round2(a.z),
        rotY: round2(a.facing),
        jointDeg: {},
      };
    });
    var cam = ctx.camera
      ? {
        pos: ctx.camera.eye.map(round2),
        target: ctx.camera.target.map(round2),
        fov: round2(ctx.camera.fov),
      }
      : { pos: [0, 1.5, 4.2], target: [0, 1.05, 0], fov: 35 };

    var tracks = [{
      kind: 'camera', id: 'cam1',
      keys: [{ t: 0, pos: cam.pos.slice(), target: cam.target.slice(), fov: cam.fov, cut: false, camId: 'cam1' }],
    }];
    puppets.forEach(function (p) {
      tracks.push({ kind: 'puppet', id: p.id, keys: [{ t: 0, x: p.x, z: p.z, rotY: p.rotY }] });
    });

    return {
      version: 2,
      puppets: puppets,
      environment: null, // 3D 空间代码无全景图；可在导演台手动接全景节点
      cameras: [{ id: 'cam1', name: '镜头 1', pos: cam.pos.slice(), target: cam.target.slice(), fov: cam.fov }],
      activeCameraId: 'cam1',
      camera: { pos: cam.pos.slice(), target: cam.target.slice(), fov: cam.fov },
      timeline: { duration: 10, tracks: tracks },
    };
  }

  // ---- 入口：分镜帧「打开导演台」 ----

  function tr(key, fallback) {
    return (window.t && window.t(key) !== key) ? window.t(key) : fallback;
  }

  window.openDirectorStageFromShotFrame = function (frameNodeId) {
    // 局部名避免遮蔽全局 state（state.js 顶层 const，词法全局）
    var st = canvasState() || { nodes: [], connections: [], nextConnId: 1 };
    var frameNode = st.nodes.find(function (n) { return n.id === frameNodeId; });
    if (!frameNode) return;

    // 已关联的导演台节点：直接打开（用户在导演台的摆位/快照已持久化）
    var linkedId = frameNode.data.directorStageNodeId;
    if (linkedId && st.nodes.some(function (n) { return n.id === linkedId; })) {
      window.DirectorStageEditor.open(linkedId);
      return;
    }

    var rec = replayShotSpatialChain(frameNode);
    if (!rec) {
      showToast(tr('director_stage_from_sb_no_data', '该分镜没有可用的 3D 空间数据'), 'error');
      return;
    }
    if (rec.ctx.errors.length) {
      console.warn('[导演台转换] 代码重放异常:', rec.ctx.errors);
      showToast(tr('director_stage_from_sb_replay_warn', '部分空间代码执行异常，已按可用结果转换'), 'info');
    }

    var newNodeId = window.createDirectorStageNode({
      x: frameNode.x + 440,
      y: frameNode.y,
      checkCollision: true,
    });
    var node = st.nodes.find(function (n) { return n.id === newNodeId; });
    if (!node) {
      showToast(tr('director_stage_from_sb_create_fail', '导演台节点创建失败'), 'error');
      return;
    }

    node.data.directorData = buildDirectorData(rec);
    node.title = (frameNode.title || '分镜') + ' · ' + tr('director_stage_title_short', '导演台');

    // 分镜帧 → 导演台 连线（空间来源可追溯）
    st.connections.push({ id: st.nextConnId++, from: frameNodeId, to: newNodeId });

    if (typeof renderAllConnections === 'function') renderAllConnections();
    if (typeof renderMinimap === 'function') renderMinimap();
    if (typeof updateDirectorStageNodeShell === 'function') updateDirectorStageNodeShell(newNodeId);
    if (typeof safeAutoSave === 'function') safeAutoSave();

    // 记住关联：再次点击直接打开，不重复创建
    frameNode.data.directorStageNodeId = newNodeId;
    // 按钮文案即时翻转为「打开导演台」（body 模板渲染时按关联状态取文案）
    var frameEl = document.querySelector('.node[data-node-id="' + frameNodeId + '"] .shot-frame-open-director-btn');
    if (frameEl) frameEl.textContent = tr('shot_frame_open_director_btn', '🎬 打开导演台（3D 空间）');

    // 迁移提示合并为一条 toast（跳过的体块/道具 + 空镜警告）
    var msgs = [];
    var skipped = Object.keys(rec.ctx.stages).length + Object.keys(rec.ctx.props).length;
    if (skipped > 0) {
      msgs.push(tr('director_stage_from_sb_skipped', '已迁移角色站位与机位（{n} 个体块/道具暂不支持展示）', { n: skipped })
        .replace('{n}', String(skipped)));
    }
    if (rec.ctx.camera) {
      var actorList = Object.keys(rec.ctx.actors).map(function (name) {
        return { x: rec.ctx.actors[name].x, z: rec.ctx.actors[name].z };
      });
      var seen = cameraSeesActors(rec.ctx.camera, actorList);
      if (actorList.length && !seen.visible) {
        // LLM 产出机位与站位矛盾（如分镜5：机位背对所有角色），空镜可修正
        msgs.push(tr('director_stage_from_sb_empty_shot',
          '机位视野内无角色，镜头预览为空景；可拖拽机位方块或点预设机位调整'));
      }
    }
    if (msgs.length) showToast(msgs.join('；'), 'info');

    window.DirectorStageEditor.open(newNodeId);
  };

  /** 分镜帧是否显示「打开导演台」按钮（shotJson 携带 3D 代码）。 */
  window.shotFrameHasSpatialCode = function (frameNode) {
    return !!(frameNode && frameNode.data && hasThreeCode(frameNode));
  };

  /**
   * 分镜帧是否已关联存活的导演台节点：已关联 → 按钮「打开导演台」，
   * 未关联 → 「创建导演台」（首次点击才新建节点）。
   */
  window.shotFrameDirectorLinked = function (frameNode) {
    if (!frameNode || !frameNode.data || !frameNode.data.directorStageNodeId) return false;
    var st = canvasState();
    if (!st) return false;
    return st.nodes.some(function (n) { return n.id === frameNode.data.directorStageNodeId; });
  };

  // 纯逻辑测试钩子（仅 vitest 使用，生产不依赖）
  window.__dsFromSbInternals = {
    createRecorderContext: createRecorderContext,
    runRecorderCode: runRecorderCode,
    replayShotSpatialChain: replayShotSpatialChain,
    buildDirectorData: buildDirectorData,
    cameraSeesActors: cameraSeesActors,
  };
})();
