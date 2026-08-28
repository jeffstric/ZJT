// ============================
// director_stage_editor.js - 导演台 3D 编辑器
// 类似 liblib 导演台：创建人偶 / 移动人偶 / 控制人偶姿态 / 设置镜头
// 依赖: /assets/vendor/three.min.js (r128 UMD)
// DOM 由本模块自注入（参考 image_coloring_editor.js 模式），样式在 /css/director_stage.css
// ============================

(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  // ============ 常量 ============

  var GROUND_LIMIT = 9.5;             // 人偶/相机可拖拽范围
  var HIP_H = 0.905;                  // 髋关节离地高度（米）
  var MAX_UNDO = 50;

  var PUPPET_COLORS = ['#4f8ef7', '#f76f5e', '#34c38f', '#b57de8', '#e8b34d', '#4dc3e8', '#f07ab6', '#8d9aa8'];

  // 关节旋转轴约定（度，右手系，人偶面向 +Z）:
  //   肩/髋 X:-θ=向前抬，肘 X:-θ=向前弯，膝 X:+θ=向后弯，
  //   侧抬臂 Z: 左臂为正，躯干前倾 X:+θ
  var JOINT_GROUPS = [
    { key: 'torso', label: '躯干', joints: ['spine', 'chest'] },
    { key: 'headNeck', label: '头颈', joints: ['neck', 'head'] },
    { key: 'armL', label: '左臂', joints: ['shoulderL', 'elbowL', 'wristL'] },
    { key: 'armR', label: '右臂', joints: ['shoulderR', 'elbowR', 'wristR'] },
    { key: 'legL', label: '左腿', joints: ['hipL', 'kneeL', 'ankleL'] },
    { key: 'legR', label: '右腿', joints: ['hipR', 'kneeR', 'ankleR'] }
  ];

  var JOINT_LABELS = {
    spine: '腰部', chest: '胸部', neck: '颈部', head: '头部',
    shoulderL: '左肩', elbowL: '左肘', wristL: '左腕',
    shoulderR: '右肩', elbowR: '右肘', wristR: '右腕',
    hipL: '左髋', kneeL: '左膝', ankleL: '左踝',
    hipR: '右髋', kneeR: '右膝', ankleR: '右踝'
  };

  // 姿态预设（关节欧拉角，度）
  var POSE_PRESETS = {
    stand: {
      label: '站立',
      joints: { shoulderL: [2, 0, 8], elbowL: [-6, 0, 4], shoulderR: [2, 0, -8], elbowR: [-6, 0, -4] }
    },
    tpose: {
      label: 'T-Pose',
      joints: { shoulderL: [0, 0, 86], shoulderR: [0, 0, -86] }
    },
    walk: {
      label: '行走',
      joints: {
        hipL: [-24, 0, 2], kneeL: [30, 0, 0], ankleL: [8, 0, 0],
        hipR: [16, 0, -2], kneeR: [18, 0, 0], ankleR: [4, 0, 0],
        shoulderL: [26, 0, 10], elbowL: [-28, 0, 6],
        shoulderR: [-32, 0, -10], elbowR: [-42, 0, -6],
        spine: [3, 0, 0]
      }
    },
    run: {
      label: '奔跑',
      joints: {
        hipL: [-55, 0, 3], kneeL: [72, 0, 0], ankleL: [18, 0, 0],
        hipR: [38, 0, -3], kneeR: [62, 0, 0],
        shoulderL: [58, 0, 12], elbowL: [-82, 0, 8],
        shoulderR: [-66, 0, -12], elbowR: [-95, 0, -8],
        spine: [14, 0, 0], chest: [6, 0, 0], head: [-8, 0, 0]
      }
    },
    sit: {
      label: '坐姿',
      rootYOffset: -0.44,
      joints: {
        hipL: [-86, 4, 6], kneeL: [84, 0, 0],
        hipR: [-86, -4, -6], kneeR: [84, 0, 0],
        shoulderL: [-14, 0, 6], elbowL: [-22, 0, 4],
        shoulderR: [-14, 0, -6], elbowR: [-22, 0, -4],
        spine: [4, 0, 0]
      }
    },
    squat: {
      label: '蹲姿',
      rootYOffset: -0.42,
      joints: {
        hipL: [-96, 0, 10], kneeL: [118, 0, 0], ankleL: [26, 0, 0],
        hipR: [-96, 0, -10], kneeR: [118, 0, 0], ankleR: [26, 0, 0],
        spine: [18, 0, 0], chest: [8, 0, 0],
        shoulderL: [-55, 0, 8], elbowL: [-18, 0, 6],
        shoulderR: [-55, 0, -8], elbowR: [-18, 0, -6]
      }
    },
    jump: {
      label: '跳跃',
      rootYOffset: 0.35,
      joints: {
        shoulderL: [-20, 0, 140], elbowL: [-24, 0, 10],
        shoulderR: [-20, 0, -140], elbowR: [-24, 0, -10],
        hipL: [-38, 0, 8], kneeL: [72, 0, 0],
        hipR: [-38, 0, -8], kneeR: [72, 0, 0],
        spine: [-4, 0, 0], head: [-6, 0, 0]
      }
    },
    wave: {
      label: '挥手',
      joints: {
        shoulderR: [-12, 0, -128], elbowR: [-24, 0, -52],
        shoulderL: [2, 0, 8], elbowL: [-8, 0, 4],
        head: [0, 0, -6]
      }
    },
    point: {
      label: '指向',
      joints: {
        shoulderR: [-88, 0, -4], elbowR: [-6, 0, 0], wristR: [-14, 0, 0],
        shoulderL: [4, 0, 8], elbowL: [-8, 0, 4], spine: [0, 6, 0]
      }
    },
    surprise: {
      label: '惊讶',
      joints: {
        shoulderL: [-30, 0, 128], elbowL: [-38, 0, 16],
        shoulderR: [-30, 0, -128], elbowR: [-38, 0, -16],
        spine: [-8, 0, 0], head: [-10, 0, 0]
      }
    },
    think: {
      label: '思考',
      joints: {
        shoulderL: [-32, 8, 18], elbowL: [-118, 0, 26],
        shoulderR: [4, 0, -64], elbowR: [-76, 0, 52],
        head: [4, 10, 8], spine: [2, 0, 0]
      }
    },
    kneel: {
      label: '跪地',
      rootYOffset: -0.38,
      joints: {
        hipR: [6, 0, -8], kneeR: [96, 0, 0], ankleR: [20, 0, 0],
        hipL: [-78, 0, 8], kneeL: [86, 0, 0], ankleL: [10, 0, 0],
        spine: [6, 0, 0]
      }
    }
  };

  // 镜头预设机位
  var CAMERA_PRESETS = {
    eye_front: { label: '正面·平视', pos: [0, 1.5, 4.2], target: [0, 1.05, 0], fov: 35 },
    closeup_front: { label: '正面·近景', pos: [0, 1.55, 2.0], target: [0, 1.5, 0], fov: 32 },
    wide_front: { label: '正面·全景', pos: [0, 1.7, 6.8], target: [0, 1.0, 0], fov: 40 },
    three_quarter: { label: '3/4侧', pos: [3.2, 1.5, 3.2], target: [0, 1.05, 0], fov: 35 },
    side_left: { label: '左侧', pos: [-4.6, 1.45, 0.3], target: [0, 1.0, 0], fov: 35 },
    side_right: { label: '右侧', pos: [4.6, 1.45, 0.3], target: [0, 1.0, 0], fov: 35 },
    back: { label: '背面', pos: [0, 1.5, -4.2], target: [0, 1.05, 0], fov: 35 },
    low_angle: { label: '仰拍', pos: [0.8, 0.35, 3.4], target: [0, 1.7, 0], fov: 48 },
    high_angle: { label: '俯拍', pos: [0.8, 4.6, 3.6], target: [0, 0.9, 0], fov: 42 },
    top_down: { label: '顶摄', pos: [0, 7.5, 0.02], target: [0, 0, 0], fov: 45 },
    over_shoulder: { label: '过肩', dynamic: 'over_shoulder' }
  };

  // 快照分辨率（按工作流画幅）
  var SNAPSHOT_RES = {
    '16:9': [1344, 756], '9:16': [756, 1344], '1:1': [1024, 1024],
    '4:3': [1152, 864], '3:4': [864, 1152]
  };

  // ============ 工具 ============

  function deg2rad(d) { return d * Math.PI / 180; }
  function rad2deg(r) { return r * 180 / Math.PI; }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function fmt(n) { return (Math.round(n * 10) / 10).toFixed(1); }
  function esc(v) { return window.escapeHtml ? window.escapeHtml(String(v == null ? '' : v)) : String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

  function getWorkflowRatio() {
    var el = document.getElementById('ratioSelect');
    var v = el ? el.value : '16:9';
    return SNAPSHOT_RES[v] ? v : '16:9';
  }

  function dataUrlToBlob(dataUrl) {
    var parts = dataUrl.split(',');
    var mime = (parts[0].match(/data:(.*?);base64/) || [])[1] || 'image/jpeg';
    var bin = atob(parts[1]);
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  // ============ 人偶骨骼构建 ============

  function buildPuppetRig(colorHex) {
    var mat = new THREE.MeshStandardMaterial({ color: colorHex, roughness: 0.82, metalness: 0.05 });
    var jointMat = new THREE.MeshBasicMaterial({ color: 0xffd54f, transparent: true, opacity: 0.95 });
    var eyeMat = new THREE.MeshBasicMaterial({ color: 0x14161d });

    var rig = { joints: {}, markers: {}, bodyMeshes: [], materials: [mat, jointMat, eyeMat] };

    function cyl(r, h, matx) {
      var g = new THREE.CylinderGeometry(r, r * 0.92, h, 12);
      var m = new THREE.Mesh(g, matx || mat);
      rig.bodyMeshes.push(m);
      return m;
    }
    function box(w, h, d) {
      var m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      rig.bodyMeshes.push(m);
      return m;
    }
    function sph(r, m2) {
      var mesh = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), m2 || mat);
      rig.bodyMeshes.push(mesh);
      return mesh;
    }
    function joint(key, parent, x, y, z) {
      var g = new THREE.Group();
      g.position.set(x, y, z);
      parent.add(g);
      rig.joints[key] = g;
      // 关节标记球（选中人偶时显示）
      var marker = new THREE.Mesh(new THREE.SphereGeometry(0.042, 10, 8), jointMat.clone());
      marker.visible = false;
      marker.userData.jointKey = key;
      g.add(marker);
      rig.markers[key] = marker;
      return g;
    }

    var root = new THREE.Group();
    rig.root = root;

    var hipsY = new THREE.Group();
    hipsY.position.y = HIP_H;
    root.add(hipsY);
    rig.hipsY = hipsY;

    var pelvis = box(0.30, 0.17, 0.19); pelvis.position.y = 0.02; hipsY.add(pelvis);

    // 躯干
    var spine = joint('spine', hipsY, 0, 0.12, 0);
    var waist = cyl(0.095, 0.10); waist.position.y = 0.06; spine.add(waist);
    var chest = joint('chest', spine, 0, 0.15, 0);
    var chestMesh = box(0.335, 0.26, 0.20); chestMesh.position.y = 0.10; chest.add(chestMesh);

    // 颈 / 头
    var neck = joint('neck', chest, 0, 0.25, 0);
    var neckMesh = cyl(0.045, 0.08); neckMesh.position.y = 0.03; neck.add(neckMesh);
    var head = joint('head', neck, 0, 0.08, 0);
    var headMesh = sph(0.115); headMesh.position.y = 0.10; head.add(headMesh);
    // 眼睛（面向 +Z 指示）
    var eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.017, 8, 6), eyeMat);
    eyeL.position.set(0.042, 0.115, 0.102); head.add(eyeL);
    var eyeR = eyeL.clone(); eyeR.position.x = -0.042; head.add(eyeR);

    // 手臂（puppet 左侧 = +X）
    function buildArm(side) {
      var s = side === 'L' ? 1 : -1;
      var sh = joint('shoulder' + side, chest, s * 0.225, 0.19, 0);
      var upper = cyl(0.048, 0.27); upper.position.y = -0.135; sh.add(upper);
      var elbow = joint('elbow' + side, sh, 0, -0.27, 0);
      var lower = cyl(0.042, 0.25); lower.position.y = -0.125; elbow.add(lower);
      var wrist = joint('wrist' + side, elbow, 0, -0.25, 0);
      var hand = sph(0.055); hand.position.y = -0.02; wrist.add(hand);
    }
    buildArm('L');
    buildArm('R');

    // 腿
    function buildLeg(side) {
      var s = side === 'L' ? 1 : -1;
      var hip = joint('hip' + side, hipsY, s * 0.105, -0.06, 0);
      var upper = cyl(0.068, 0.40); upper.position.y = -0.20; hip.add(upper);
      var knee = joint('knee' + side, hip, 0, -0.40, 0);
      var lower = cyl(0.055, 0.38); lower.position.y = -0.19; knee.add(lower);
      var ankle = joint('ankle' + side, knee, 0, -0.38, 0);
      var foot = box(0.10, 0.06, 0.21); foot.position.set(0, -0.035, 0.05); ankle.add(foot);
    }
    buildLeg('L');
    buildLeg('R');

    rig.bodyMeshes.forEach(function (m) { m.castShadow = false; m.receiveShadow = false; });
    return rig;
  }

  // 对焦十字标记纹理：白色圆环 + 十字准线（用 material.color 染色，便于切换选中色）
  function makeFocusMarkerSprite() {
    var S = 128;
    var canvas = document.createElement('canvas');
    canvas.width = S; canvas.height = S;
    var ctx = canvas.getContext('2d');
    ctx.strokeStyle = '#ffffff';
    ctx.lineCap = 'round';

    // 外圆环
    ctx.lineWidth = 9;
    ctx.beginPath();
    ctx.arc(S / 2, S / 2, 40, 0, Math.PI * 2);
    ctx.stroke();

    // 十字准线（中心留空隙，摄影对焦框样式）
    ctx.lineWidth = 7;
    var gap = 16, outer = 60;
    [[S / 2, S / 2 - outer, S / 2, S / 2 - gap],
     [S / 2, S / 2 + gap, S / 2, S / 2 + outer],
     [S / 2 - outer, S / 2, S / 2 - gap, S / 2],
     [S / 2 + gap, S / 2, S / 2 + outer, S / 2]].forEach(function (seg) {
      ctx.beginPath();
      ctx.moveTo(seg[0], seg[1]);
      ctx.lineTo(seg[2], seg[3]);
      ctx.stroke();
    });

    // 中心点
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(S / 2, S / 2, 5, 0, Math.PI * 2);
    ctx.fill();

    var tex = new THREE.CanvasTexture(canvas);
    tex.needsUpdate = true;
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, depthTest: false, color: 0xfbbf24
    }));
    sprite.scale.set(0.22, 0.22, 1);
    sprite.renderOrder = 998;
    sprite.userData._texture = tex;
    return sprite;
  }

  function makeLabelSprite(text) {
    var canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 64;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(20,22,29,0.72)';
    roundRect(ctx, 4, 8, 248, 48, 12);
    ctx.fill();
    ctx.font = '600 26px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#f3f4f6';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(text).slice(0, 8), 128, 33);
    var tex = new THREE.CanvasTexture(canvas);
    tex.needsUpdate = true;
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    sprite.scale.set(0.72, 0.18, 1);
    sprite.position.y = 2.02;
    sprite.renderOrder = 999;
    sprite.userData._texture = tex;
    return sprite;
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // ============ 编辑器 ============

  var ed = null; // 当前编辑器实例

  function DirectorEditor(nodeId) {
    this.nodeId = nodeId;
    this.node = state.nodes.find(function (n) { return n.id === nodeId; });
    if (!this.node) throw new Error('节点不存在');

    this.puppets = [];          // {id,name,color,characterId,characterName,rig,jointDeg:{},x,z,rotY,rootYOffset,scale,pose,label}
    this.selectedPuppetId = null;
    this.selectedJointKey = null;
    this.selectedCamTarget = null; // 'camera' | 'focus' | null（与人偶选中互斥）
    this._lastHoverAt = 0;
    this.undoStack = [];
    this.undoTimer = null;
    this.colorIndex = 0;
    this.puppetSeq = 1;
    this.dragging = null;
    this.orbit = { theta: 0.55, phi: 1.02, radius: 8.5, target: new THREE.Vector3(0, 1.0, 0) };
    this.virtualCamCfg = { pos: new THREE.Vector3(0, 1.5, 4.2), target: new THREE.Vector3(0, 1.05, 0), fov: 35 };
    this.rafId = null;
    this.bound = [];            // [target, event, handler] 便于清理
    this.roObserver = null;
    this.helpersVisible = true;
    this.gridVisible = true;
  }

  // ---------- DOM 注入 ----------

  var OVERLAY_HTML =
    '<div class="ds-topbar">' +
      '<button class="ds-btn ghost" id="dsBackBtn" title="返回画布">✕</button>' +
      '<div class="ds-topbar-title">' +
        '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 10L21 8V16L16 14V10Z"/></svg>' +
        '<span>导演台</span>' +
      '</div>' +
      '<div class="ds-topbar-subtitle" id="dsSubtitle"></div>' +
      '<div class="ds-topbar-spacer"></div>' +
      '<button class="ds-btn" id="dsUndoBtn" title="撤销">↶ 撤销</button>' +
      '<button class="ds-btn success" id="dsExportBtn" title="将当前镜头画面保存为快照并更新节点缩略图">📷 导出快照</button>' +
      '<button class="ds-btn primary" id="dsDoneBtn">保存并关闭</button>' +
    '</div>' +
    '<div class="ds-main">' +
      '<div class="ds-left">' +
        '<div class="ds-section-head"><span>人偶</span></div>' +
        '<div style="padding: 0 10px 8px;"><button class="ds-mini-btn" id="dsAddPuppetBtn" style="width:100%; justify-content:center;">＋ 添加人偶</button></div>' +
        '<div class="ds-puppet-list" id="dsPuppetList"></div>' +
        '<div class="ds-section-head"><span>姿态预设</span></div>' +
        '<div class="ds-pose-list" id="dsPoseList"></div>' +
        '<div class="ds-section-head"><span>全景环境</span></div>' +
        '<div style="padding: 0 10px 12px;" id="dsEnvSection"></div>' +
      '</div>' +
      '<div class="ds-viewport-wrap" id="dsViewportWrap">' +
        '<canvas id="dsCanvas" tabindex="0"></canvas>' +
        '<div class="ds-viewport-toolbar">' +
          '<button class="ds-mini-btn active" id="dsFocusBtn" title="视角对焦到选中对象">对焦</button>' +
          '<button class="ds-mini-btn active" id="dsGridBtn" title="显示/隐藏网格">网格</button>' +
          '<button class="ds-mini-btn" id="dsResetViewBtn" title="重置视角">重置视角</button>' +
        '</div>' +
        '<div class="ds-mode-hint" id="dsModeHint">左键拖人偶=移动 · 点关节球=调姿态 · 空白拖拽=旋转视角 · 滚轮=缩放 · 右键拖拽=平移</div>' +
        '<div class="ds-drag-banner" id="dsDragBanner"></div>' +
        '<div class="ds-hover-tip" id="dsHoverTip"></div>' +
        '<div class="ds-pip" id="dsPip">' +
          '<div class="ds-pip-header"><span>镜头预览</span><span class="rec-dot"></span></div>' +
          '<canvas id="dsPipCanvas"></canvas>' +
        '</div>' +
        '<div class="ds-selection-tip" id="dsSelectionTip"></div>' +
        '<div class="ds-add-pop" id="dsAddPop">' +
          '<div class="ds-add-pop-head"><span>添加人偶</span><button class="ds-puppet-del" id="dsAddPopClose" style="font-size:16px;">✕</button></div>' +
          '<div class="ds-add-pop-body" id="dsAddPopBody"></div>' +
        '</div>' +
      '</div>' +
      '<div class="ds-right" id="dsPropsPanel"></div>' +
    '</div>' +
    '<div class="ds-statusbar">' +
      '<span class="ds-status-dot" id="dsStatusDot"></span>' +
      '<span id="dsStatusText">就绪</span>' +
      '<span style="flex:1;"></span>' +
      '<span id="dsRatioText"></span>' +
    '</div>';

  DirectorEditor.prototype.injectDom = function () {
    var old = document.getElementById('directorStageOverlay');
    if (old) old.remove();
    var overlay = document.createElement('div');
    overlay.className = 'ds-overlay';
    overlay.id = 'directorStageOverlay';
    overlay.innerHTML = OVERLAY_HTML;
    document.body.appendChild(overlay);
    this.overlay = overlay;
  };

  DirectorEditor.prototype.$ = function (id) { return document.getElementById(id); };

  DirectorEditor.prototype.on = function (target, ev, handler, opts) {
    target.addEventListener(ev, handler, opts);
    this.bound.push([target, ev, handler, opts]);
  };

  // ---------- 场景初始化 ----------

  DirectorEditor.prototype.initScene = function () {
    var canvas = this.$('dsCanvas');
    this.renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputEncoding = THREE.sRGBEncoding;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x14161d);

    // 光照
    this.scene.add(new THREE.HemisphereLight(0x8ea2c0, 0x1a1d26, 0.95));
    var key = new THREE.DirectionalLight(0xffffff, 0.85);
    key.position.set(4, 7, 5);
    this.scene.add(key);
    var fill = new THREE.DirectionalLight(0x88aaff, 0.3);
    fill.position.set(-5, 3, -4);
    this.scene.add(fill);

    // 地面
    var ground = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 60),
      new THREE.MeshStandardMaterial({ color: 0x191c24, roughness: 0.95 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.005;
    this.scene.add(ground);
    this.groundPlane = ground;

    // 站位圆台（快照保留）
    var disc = new THREE.Mesh(
      new THREE.CircleGeometry(2.6, 48),
      new THREE.MeshStandardMaterial({ color: 0x232734, roughness: 0.9 })
    );
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.001;
    this.scene.add(disc);
    this.groundDisc = disc;

    // 网格（helper，快照隐藏）
    this.grid = new THREE.GridHelper(20, 20, 0x3a4052, 0x272c3a);
    this.grid.position.y = 0.003;
    this.scene.add(this.grid);

    // 编辑视角相机
    this.viewCam = new THREE.PerspectiveCamera(50, 1, 0.1, 100);

    // 虚拟相机 helper（机身图标 + 视锥线）
    this.camRig = this.buildCameraHelper();
    this.scene.add(this.camRig);

    // PiP renderer（内部分辨率 = 快照分辨率）
    var ratio = getWorkflowRatio();
    var res = SNAPSHOT_RES[ratio];
    this.pipRenderer = new THREE.WebGLRenderer({ canvas: this.$('dsPipCanvas'), antialias: true, preserveDrawingBuffer: true });
    this.pipRenderer.setSize(res[0], res[1], false);
    this.pipRenderer.outputEncoding = THREE.sRGBEncoding;
    this.virtualCam = new THREE.PerspectiveCamera(this.virtualCamCfg.fov, res[0] / res[1], 0.1, 100);
    this.$('dsRatioText').textContent = '画幅 ' + ratio;

    // PiP 显示尺寸（按比例缩放）
    this.layoutPip(ratio);

    // 拖拽用平面与射线
    this.raycaster = new THREE.Raycaster();
    // three 默认 Line 拾取容差为 1 个世界单位（1米），会让相机视锥线"吞掉"周围 1 米内的点击
    // （焦点标记就在这个范围内，导致无法选中）。收窄到 5cm。
    this.raycaster.params.Line.threshold = 0.05;
    this.dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  };

  DirectorEditor.prototype.layoutPip = function (ratio) {
    var pip = this.$('dsPip');
    var vertical = ratio === '9:16' || ratio === '3:4';
    pip.style.width = vertical ? '150px' : '240px';
  };

  DirectorEditor.prototype.buildCameraHelper = function () {
    var group = new THREE.Group();
    var bodyMat = new THREE.MeshStandardMaterial({ color: 0xef4444, roughness: 0.6 });
    this.camBodyMat = bodyMat;
    var body = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.13, 0.22), bodyMat);
    group.add(body);
    var lens = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.06, 0.08, 10), bodyMat);
    lens.rotation.x = Math.PI / 2;
    lens.position.z = 0.14;
    group.add(lens);

    // 视锥线框
    var len = 0.9;
    var half = 0.28;
    var pts = [
      0, 0, 0.05, half, half * 0.7, len,
      0, 0, 0.05, -half, half * 0.7, len,
      0, 0, 0.05, half, -half * 0.7, len,
      0, 0, 0.05, -half, -half * 0.7, len,
      half, half * 0.7, len, -half, half * 0.7, len,
      -half, half * 0.7, len, -half, -half * 0.7, len,
      -half, -half * 0.7, len, half, -half * 0.7, len,
      half, -half * 0.7, len, half, half * 0.7, len
    ];
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    var frustumMat = new THREE.LineBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.55 });
    this.camFrustumMat = frustumMat;
    var frustum = new THREE.LineSegments(geo, frustumMat);
    group.add(frustum);

    // 选中环（地面橙色圆环，相机选中时显示；独立于 group，保持水平并跟随机位）
    var ring = new THREE.Mesh(
      new THREE.RingGeometry(0.2, 0.28, 32),
      new THREE.MeshBasicMaterial({ color: 0xf97316, transparent: true, opacity: 0.9, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.012;
    ring.visible = false;
    this.camSelectRing = ring;

    // 对焦十字标记（Sprite 自动面向渲染相机，主视口与画中画均正确朝向）
    this.focusMarker = makeFocusMarkerSprite();
    this.focusMarker.userData._isFocusMarker = true;

    // 隐形拾取球：标记本体较小，用更大的不可见球体做射线命中区
    var pickSphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.18, 8, 6),
      new THREE.MeshBasicMaterial({ visible: false })
    );
    pickSphere.userData._isFocusPick = true;
    this.focusPickSphere = pickSphere;

    // 相机 → 焦点 视线虚线：直观表达「镜头看向这里」
    var sightGeo = new THREE.BufferGeometry();
    sightGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.5, 0, 0, 1.05, 0], 3));
    this.sightLine = new THREE.Line(sightGeo, new THREE.LineDashedMaterial({
      color: 0xfbbf24, transparent: true, opacity: 0.55, dashSize: 0.12, gapSize: 0.08
    }));

    group.userData._isCamRig = true;
    return group;
  };

  // ---------- 数据恢复 / 序列化 ----------

  DirectorEditor.prototype.restoreFromData = function () {
    var d = this.node.data && this.node.data.directorData;
    var self = this;

    if (d && d.puppets) {
      d.puppets.forEach(function (pd) { self.addPuppet(pd, true); });
    }
    if (!this.puppets.length) {
      this.addPuppet({ name: '人偶 1' }, true);
    }
    if (d && d.camera) {
      this.virtualCamCfg.pos.fromArray(d.camera.pos || [0, 1.5, 4.2]);
      this.virtualCamCfg.target.fromArray(d.camera.target || [0, 1.05, 0]);
      this.virtualCamCfg.fov = d.camera.fov || 35;
    }
    // 全景环境（来自 360全景图节点连线）
    if (d && d.environment && d.environment.url) {
      this.setupEnvironment(d.environment);
    }
    // 初始撤销快照
    this.undoStack = [this.serializeData()];
  };

  DirectorEditor.prototype.serializeData = function () {
    var puppets = this.puppets.map(function (p) {
      return {
        id: p.id, name: p.name, color: p.color,
        characterId: p.characterId || null, characterName: p.characterName || '',
        x: round2(p.x), z: round2(p.z), rotY: round2(p.rotY),
        rootYOffset: round2(p.rootYOffset), scale: round2(p.scale),
        pose: p.pose || 'custom',
        joints: serializeJoints(p.jointDeg)
      };
    });
    var env = this.node.data.directorData && this.node.data.directorData.environment;
    return {
      version: 1,
      puppets: puppets,
      environment: (env && env.url) ? {
        url: env.url,
        ratio: env.ratio || '21:9',
        yaw: round2(env.yaw || 0)
      } : null,
      camera: {
        pos: [round2(this.virtualCamCfg.pos.x), round2(this.virtualCamCfg.pos.y), round2(this.virtualCamCfg.pos.z)],
        target: [round2(this.virtualCamCfg.target.x), round2(this.virtualCamCfg.target.y), round2(this.virtualCamCfg.target.z)],
        fov: Math.round(this.virtualCamCfg.fov)
      }
    };
  };

  function round2(v) { return Math.round(v * 100) / 100; }

  function serializeJoints(jointDeg) {
    var out = {};
    Object.keys(jointDeg).forEach(function (k) {
      out[k] = [Math.round(jointDeg[k][0]), Math.round(jointDeg[k][1]), Math.round(jointDeg[k][2])];
    });
    return out;
  }

  DirectorEditor.prototype.markDirty = function (skipUndo) {
    if (!skipUndo) this.pushUndo();
    this.node.data.directorData = this.serializeData();
    this.updateNodeShell();
    this.$('dsStatusDot').classList.add('dirty');
    this.$('dsStatusText').textContent = '已修改，自动保存中…';
    var self = this;
    if (this.dirtyTimer) clearTimeout(this.dirtyTimer);
    this.dirtyTimer = setTimeout(function () {
      self.dirtyTimer = null;
      if (typeof safeAutoSave === 'function') safeAutoSave();
    }, 400);
  };

  DirectorEditor.prototype.pushUndo = function () {
    this.undoStack.push(this.serializeData());
    if (this.undoStack.length > MAX_UNDO) this.undoStack.shift();
  };

  DirectorEditor.prototype.undo = function () {
    if (this.undoStack.length <= 1) {
      this.setStatus('没有可撤销的操作');
      return;
    }
    this.undoStack.pop();
    var snap = this.undoStack[this.undoStack.length - 1];
    this.rebuildFromSnapshot(snap);
    this.node.data.directorData = this.serializeData();
    this.updateNodeShell();
    if (typeof safeAutoSave === 'function') safeAutoSave();
    this.setStatus('已撤销');
  };

  DirectorEditor.prototype.rebuildFromSnapshot = function (snap) {
    var self = this;
    this.clearPuppets();
    (snap.puppets || []).forEach(function (pd) { self.addPuppet(pd, true); });
    if (!this.puppets.length) this.addPuppet({ name: '人偶 1' }, true);
    if (snap.camera) {
      this.virtualCamCfg.pos.fromArray(snap.camera.pos);
      this.virtualCamCfg.target.fromArray(snap.camera.target);
      this.virtualCamCfg.fov = snap.camera.fov;
    }
    this.selectedPuppetId = null;
    this.selectedJointKey = null;
    this.renderPuppetList();
    this.renderPropsPanel();
    this.updateSelectionVisuals();
  };

  DirectorEditor.prototype.clearPuppets = function () {
    var self = this;
    this.puppets.forEach(function (p) {
      self.scene.remove(p.rig.root);
      disposeRig(p.rig);
      if (p.label) {
        if (p.label.userData._texture) p.label.userData._texture.dispose();
        p.label.material.dispose();
      }
    });
    this.puppets = [];
  };

  function disposeRig(rig) {
    rig.root.traverse(function (obj) {
      if (obj.geometry) obj.geometry.dispose();
    });
    rig.materials.forEach(function (m) { m.dispose(); });
  }

  DirectorEditor.prototype.setStatus = function (text) {
    this.$('dsStatusText').textContent = text;
  };

  // ---------- 全景环境管理（与 360全景图节点融合） ----------

  // 加载全景环境球：equirectangular 纹理贴到部分球面内壁
  // 比例→视场换算与 panorama_node.js computePanoramaFov 保持一致
  DirectorEditor.prototype.setupEnvironment = function (env) {
    var self = this;
    this.removeEnvironment();
    if (!env || !env.url) return;
    var url = (typeof proxyImageUrl === 'function' ? proxyImageUrl(env.url) : env.url);
    this._envLoading = true;
    this.renderEnvSection();

    new THREE.TextureLoader().load(url, function (texture) {
      // 编辑器已关闭则直接释放
      if (!self.overlay || !self.overlay.classList.contains('show')) {
        texture.dispose();
        return;
      }
      texture.encoding = THREE.sRGBEncoding;

      var w = 21, h = 9;
      var m = String(env.ratio || '').match(/^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/i);
      if (m) { w = parseFloat(m[1]); h = parseFloat(m[2]); }
      var haov, vaov;
      if (w / h >= 2) {
        haov = 360;
        vaov = Math.min(180, 360 * h / w);
      } else {
        vaov = 180;
        haov = Math.min(360, 180 * w / h);
      }
      var phiLength = haov / 360 * Math.PI * 2;
      var thetaLength = vaov / 180 * Math.PI;
      var thetaStart = (Math.PI - thetaLength) / 2;      // 垂直居中
      var phiStart = Math.PI / 2 - phiLength / 2;        // equirect 水平中心对齐 +Z（人偶面向）
      var geo = new THREE.SphereGeometry(50, 64, 40, phiStart, phiLength, thetaStart, thetaLength);
      geo.scale(-1, 1, 1); // 翻转到内壁视角，图像不镜像
      var sphere = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: texture }));
      sphere.rotation.y = deg2rad(env.yaw || 0);
      self.scene.add(sphere);
      self.envSphere = sphere;
      self._envLoading = false;
      self.applyGroundVisibility();
      self.renderEnvSection();
      self.setStatus('全景环境已加载');
    }, undefined, function () {
      self._envLoading = false;
      self.renderEnvSection();
      self.setStatus('全景环境加载失败');
      if (typeof showToast === 'function') showToast('全景环境图片加载失败', 'error');
    });
  };

  DirectorEditor.prototype.removeEnvironment = function () {
    if (this.envSphere) {
      this.scene.remove(this.envSphere);
      this.envSphere.geometry.dispose();
      if (this.envSphere.material.map) this.envSphere.material.map.dispose();
      this.envSphere.material.dispose();
      this.envSphere = null;
    }
    this._envLoading = false;
    this.applyGroundVisibility();
    this.renderEnvSection();
  };

  // 有环境时隐藏默认地面/站位圆台（露出全景自带地面）
  DirectorEditor.prototype.applyGroundVisibility = function () {
    var hasEnv = !!this.envSphere;
    if (this.groundPlane) this.groundPlane.visible = !hasEnv;
    if (this.groundDisc) this.groundDisc.visible = !hasEnv;
  };

  // 当前保存的环境数据（随 markDirty 序列化）
  DirectorEditor.prototype.getEnvData = function () {
    var d = this.node.data.directorData;
    return (d && d.environment && d.environment.url) ? d.environment : null;
  };

  // 从画布上相连的 360全景节点重新拉取最新结果（全景重新生成后使用）
  DirectorEditor.prototype.refreshEnvironment = function () {
    var conn = (state.connections || []).find(function (c) {
      return c.to === this.nodeId && c.portType === 'environment';
    }, this);
    if (!conn) {
      this.setStatus('未找到相连的全景节点');
      return;
    }
    var fromNode = state.nodes.find(function (n) { return n.id === conn.from; });
    var url = fromNode && fromNode.data && fromNode.data.url;
    if (!url) {
      this.setStatus('全景节点还没有生成结果');
      return;
    }
    var env = this.getEnvData() || {};
    env.url = url;
    env.ratio = (fromNode.data.ratio || env.ratio || '21:9');
    if (!this.node.data.directorData) this.node.data.directorData = {};
    this.node.data.directorData.environment = env;
    this.setupEnvironment(env);
    this.markDirty();
    this.setStatus('已从全景节点刷新环境');
  };

  // 左栏「全景环境」区块
  DirectorEditor.prototype.renderEnvSection = function () {
    var wrap = this.$('dsEnvSection');
    if (!wrap) return;
    var self = this;
    var env = this.getEnvData();
    var html = '';
    if (this._envLoading) {
      html = '<div style="padding:10px; font-size:12px; color:#9ca3af;">🌐 全景环境加载中…</div>';
    } else if (!env) {
      html = '<div style="padding:10px 12px; font-size:11px; color:#6b7280; line-height:1.7;">' +
        '在画布上把「360全景图」节点的输出连到导演台节点左侧的环境端口，即可把全景作为舞台背景。</div>';
    } else {
      var imgUrl = (typeof proxyImageUrl === 'function' ? proxyImageUrl(env.url) : env.url);
      html =
        '<div style="border:1px solid #2a2e3a; border-radius:8px; overflow:hidden; background:#20232e;">' +
          '<img src="' + esc(imgUrl) + '" style="width:100%; height:64px; object-fit:cover; display:block;" alt="">' +
          '<div style="padding:8px 10px; font-size:11px; color:#9ca3af;">🌐 全景环境 · ' + esc(env.ratio || '21:9') + '</div>' +
        '</div>' +
        '<div class="ds-slider-row" style="margin-top:8px;">' +
          '<label title="环境旋转">旋转</label>' +
          '<input type="range" id="dsEnvYaw" min="0" max="360" step="1" value="' + Math.round(env.yaw || 0) + '" />' +
          '<input type="number" class="ds-num" id="dsEnvYawNum" min="0" max="360" value="' + Math.round(env.yaw || 0) + '" />' +
        '</div>' +
        '<div style="display:flex; gap:6px; margin-top:8px;">' +
          '<button class="ds-mini-btn" id="dsEnvRefresh" style="flex:1; justify-content:center;">↻ 刷新</button>' +
          '<button class="ds-mini-btn danger" id="dsEnvRemove" style="flex:1; justify-content:center;">✕ 移除</button>' +
        '</div>';
    }
    wrap.innerHTML = html;

    if (!this._envLoading && env) {
      var yawSlider = this.$('dsEnvYaw');
      var yawNum = this.$('dsEnvYawNum');
      if (yawSlider) {
        this.on(yawSlider, 'input', function () {
          env.yaw = parseFloat(yawSlider.value) || 0;
          if (self.envSphere) self.envSphere.rotation.y = deg2rad(env.yaw);
          if (yawNum) yawNum.value = yawSlider.value;
          self.markDirty(true);
        });
        this.on(yawSlider, 'change', function () { self.markDirty(); });
      }
      if (yawNum) {
        this.on(yawNum, 'change', function () {
          env.yaw = clamp(parseFloat(yawNum.value) || 0, 0, 360);
          if (self.envSphere) self.envSphere.rotation.y = deg2rad(env.yaw);
          if (yawSlider) yawSlider.value = env.yaw;
          self.markDirty();
        });
      }
      var refreshBtn = this.$('dsEnvRefresh');
      if (refreshBtn) this.on(refreshBtn, 'click', function () { self.refreshEnvironment(); });
      var removeBtn = this.$('dsEnvRemove');
      if (removeBtn) {
        this.on(removeBtn, 'click', function () {
          if (self.node.data.directorData) self.node.data.directorData.environment = null;
          self.removeEnvironment();
          self.markDirty();
          self.setStatus('已移除全景环境');
        });
      }
    }
  };

  // ---------- 人偶管理 ----------

  DirectorEditor.prototype.addPuppet = function (pd, skipRefresh) {
    pd = pd || {};
    var color = pd.color || PUPPET_COLORS[this.colorIndex % PUPPET_COLORS.length];
    this.colorIndex++;

    var rig = buildPuppetRig(color);
    var puppet = {
      id: pd.id || ('p' + Date.now().toString(36) + Math.floor(Math.random() * 1000)),
      name: pd.name || ('人偶 ' + this.puppetSeq),
      color: color,
      characterId: pd.characterId || null,
      characterName: pd.characterName || '',
      rig: rig,
      x: typeof pd.x === 'number' ? pd.x : (this.puppets.length % 2 === 0 ? -0.6 : 0.6),
      z: typeof pd.z === 'number' ? pd.z : (this.puppets.length === 0 ? 0 : 1.0),
      rotY: typeof pd.rotY === 'number' ? pd.rotY : 0,
      rootYOffset: typeof pd.rootYOffset === 'number' ? pd.rootYOffset : 0,
      scale: typeof pd.scale === 'number' ? clamp(pd.scale, 0.7, 1.3) : 1,
      pose: pd.pose || 'stand',
      jointDeg: {},
      label: null
    };
    this.puppetSeq++;

    // 初始化关节角（预设 or 保存值）
    var joints = {};
    if (pd.joints) {
      Object.keys(pd.joints).forEach(function (k) { joints[k] = pd.joints[k].slice(); });
    } else {
      var preset = POSE_PRESETS[puppet.pose] || POSE_PRESETS.stand;
      Object.keys(preset.joints).forEach(function (k) { joints[k] = preset.joints[k].slice(); });
      if (preset.rootYOffset) puppet.rootYOffset = preset.rootYOffset;
    }
    puppet.jointDeg = normalizeJoints(joints);

    // body mesh 标记
    var self = this;
    rig.bodyMeshes.forEach(function (m) { m.userData.puppetId = puppet.id; });

    // 名牌
    var label = makeLabelSprite(puppet.name);
    puppet.label = label;
    rig.root.add(label);

    this.scene.add(rig.root);
    this.puppets.push(puppet);
    this.applyPuppetTransform(puppet);
    this.applyJointDeg(puppet);

    if (!skipRefresh) {
      this.selectedPuppetId = puppet.id;
      this.selectedJointKey = null;
      this.renderPuppetList();
      this.renderPropsPanel();
      this.updateSelectionVisuals();
      this.markDirty();
      this.setStatus('已添加「' + puppet.name + '」');
    }
    return puppet;
  };

  // 关节数据补全为全量（未指定的保持 0）
  var ALL_JOINT_KEYS = JOINT_GROUPS.reduce(function (acc, g) { return acc.concat(g.joints); }, []);
  function normalizeJoints(joints) {
    var out = {};
    ALL_JOINT_KEYS.forEach(function (k) {
      out[k] = (joints[k] || [0, 0, 0]).slice(0, 3);
      while (out[k].length < 3) out[k].push(0);
    });
    return out;
  }

  DirectorEditor.prototype.getPuppet = function (id) {
    return this.puppets.find(function (p) { return p.id === id; }) || null;
  };

  DirectorEditor.prototype.removePuppet = function (id) {
    var p = this.getPuppet(id);
    if (!p) return;
    this.scene.remove(p.rig.root);
    disposeRig(p.rig);
    if (p.label && p.label.userData._texture) p.label.userData._texture.dispose();
    this.puppets = this.puppets.filter(function (x) { return x.id !== id; });
    if (this.selectedPuppetId === id) {
      this.selectedPuppetId = null;
      this.selectedJointKey = null;
    }
    this.renderPuppetList();
    this.renderPropsPanel();
    this.updateSelectionVisuals();
    this.markDirty();
    this.setStatus('已删除人偶');
  };

  DirectorEditor.prototype.applyPuppetTransform = function (p) {
    p.rig.root.position.set(p.x, 0, p.z);
    p.rig.root.rotation.y = deg2rad(p.rotY);
    p.rig.root.scale.setScalar(p.scale);
    p.rig.hipsY.position.y = (HIP_H + p.rootYOffset);
  };

  DirectorEditor.prototype.applyJointDeg = function (p) {
    var self = this;
    ALL_JOINT_KEYS.forEach(function (k) {
      var g = p.rig.joints[k];
      var deg = p.jointDeg[k] || [0, 0, 0];
      g.rotation.set(deg2rad(deg[0]), deg2rad(deg[1]), deg2rad(deg[2]));
    });
  };

  DirectorEditor.prototype.applyPose = function (poseKey) {
    var p = this.getPuppet(this.selectedPuppetId);
    if (!p) return;
    var preset = POSE_PRESETS[poseKey];
    if (!preset) return;
    var self = this;
    // 未在预设中定义的关节清零，保证预设切换干净
    var fresh = {};
    Object.keys(preset.joints).forEach(function (k) { fresh[k] = preset.joints[k].slice(); });
    p.jointDeg = normalizeJoints(fresh);
    p.rootYOffset = preset.rootYOffset || 0;
    p.pose = poseKey;
    this.applyPuppetTransform(p);
    this.applyJointDeg(p);
    this.renderPropsPanel();
    this.markDirty();
    this.setStatus('已应用姿态「' + preset.label + '」');
  };

  // ---------- 选择与高亮 ----------

  DirectorEditor.prototype.selectPuppet = function (id, jointKey) {
    this.selectedPuppetId = id;
    this.selectedJointKey = jointKey || null;
    if (id) this._panelMode = 'puppet';
    if (id) this.selectedCamTarget = null;
    this.renderPuppetList();
    this.renderPropsPanel();
    this.updateSelectionVisuals();
  };

  // 选中相机/对焦中心（与人偶选中互斥），右栏切换到镜头设置
  DirectorEditor.prototype.selectCamera = function (target) {
    this.selectedCamTarget = target || null;
    if (this.selectedCamTarget) {
      this.selectedPuppetId = null;
      this.selectedJointKey = null;
      this._panelMode = 'camera';
    }
    this.renderPuppetList();
    this.renderPropsPanel();
    this.updateSelectionVisuals();
  };

  DirectorEditor.prototype.updateSelectionVisuals = function () {
    var sel = this.getPuppet(this.selectedPuppetId);
    this.puppets.forEach(function (p) {
      var isSel = sel && p.id === sel.id;
      // 高亮：主体 emissive
      var m = p.rig.materials[0];
      m.emissive = m.emissive || new THREE.Color(0);
      m.emissive.setHex(isSel ? 0x1c2440 : 0x000000);
      // 关节球显隐
      Object.keys(p.rig.markers).forEach(function (k) {
        p.rig.markers[k].visible = !!isSel;
      });
    });

    // 相机 / 对焦中心选中高亮：机身红→橙、视锥线加亮、地面显示橙色选中环、对焦十字与视线虚线变青
    var camSel = this.selectedCamTarget === 'camera';
    var focusSel = this.selectedCamTarget === 'focus';
    if (this.camBodyMat) {
      this.camBodyMat.color.setHex(camSel ? 0xf97316 : 0xef4444);
      if (!this.camBodyMat.emissive) this.camBodyMat.emissive = new THREE.Color(0);
      this.camBodyMat.emissive.setHex(camSel ? 0x7c2d12 : 0x000000);
    }
    if (this.camFrustumMat) {
      this.camFrustumMat.color.setHex(camSel ? 0xfb923c : 0xef4444);
      this.camFrustumMat.opacity = camSel ? 0.95 : 0.55;
    }
    this.updateCamSelectRing();
    if (this.focusMarker) {
      this.focusMarker.material.color.setHex(focusSel ? 0x22d3ee : 0xfbbf24);
    }
    if (this.sightLine) {
      this.sightLine.material.color.setHex(focusSel ? 0x22d3ee : 0xfbbf24);
      this.sightLine.material.opacity = focusSel ? 0.9 : 0.55;
    }

    // 选中信息浮层
    var tip = this.$('dsSelectionTip');
    if (sel) {
      Object.keys(sel.rig.markers).forEach((k) => {
        var mk = sel.rig.markers[k];
        mk.material.color.setHex(k === this.selectedJointKey ? 0xff8c42 : 0xffd54f);
        mk.scale.setScalar(k === this.selectedJointKey ? 1.5 : 1);
      });
      var jointLabel = this.selectedJointKey ? (' · ' + (JOINT_LABELS[this.selectedJointKey] || this.selectedJointKey)) : '';
      tip.textContent = sel.name + jointLabel;
      tip.classList.add('show');
    } else if (camSel) {
      tip.textContent = '🎥 机位已选中 — 按住拖动移动；高度在右侧「镜头设置」中调整';
      tip.classList.add('show');
    } else if (focusSel) {
      tip.textContent = '🎯 对焦中心已选中 — 按住拖动移动';
      tip.classList.add('show');
    } else {
      tip.classList.remove('show');
    }
  };

  // 选中环跟随相机位置；helper 隐藏（快照渲染）时一并隐藏
  DirectorEditor.prototype.updateCamSelectRing = function () {
    if (!this.camSelectRing) return;
    var shouldShow = this.selectedCamTarget === 'camera' && this.camRig && this.camRig.visible;
    if (shouldShow && this.camSelectRing.parent !== this.scene) {
      this.scene.add(this.camSelectRing);
    }
    if (this.camSelectRing.parent) {
      this.camSelectRing.position.x = this.virtualCamCfg.pos.x;
      this.camSelectRing.position.z = this.virtualCamCfg.pos.z;
    }
    this.camSelectRing.visible = shouldShow;
  };

  // ---------- 左栏渲染 ----------

  DirectorEditor.prototype.renderPuppetList = function () {
    var listEl = this.$('dsPuppetList');
    var self = this;
    listEl.innerHTML = this.puppets.map(function (p) {
      return '<div class="ds-puppet-item' + (p.id === self.selectedPuppetId ? ' selected' : '') + '" data-pid="' + esc(p.id) + '">' +
        '<span class="ds-puppet-color" style="background:' + esc(p.color) + '"></span>' +
        '<span class="ds-puppet-name" title="' + esc(p.name) + '">' + esc(p.name) + '</span>' +
        '<button class="ds-puppet-del" data-del="' + esc(p.id) + '" title="删除">✕</button>' +
      '</div>';
    }).join('') || '<div style="padding:12px; font-size:12px; color:#6b7280; text-align:center;">无人偶，点击上方添加</div>';

    listEl.querySelectorAll('.ds-puppet-item').forEach(function (item) {
      self.on(item, 'click', function (e) {
        if (e.target.closest('.ds-puppet-del')) return;
        self.selectPuppet(item.dataset.pid, null);
        self.setStatus('已选中 ' + (self.getPuppet(item.dataset.pid) || {}).name);
      });
    });
    listEl.querySelectorAll('.ds-puppet-del').forEach(function (btn) {
      self.on(btn, 'click', function (e) {
        e.stopPropagation();
        self.removePuppet(btn.dataset.del);
      });
    });
  };

  DirectorEditor.prototype.renderPoseList = function () {
    var el = this.$('dsPoseList');
    var self = this;
    el.innerHTML = Object.keys(POSE_PRESETS).map(function (k) {
      return '<div class="ds-pose-item" data-pose="' + k + '">' + esc(POSE_PRESETS[k].label) + '</div>';
    }).join('');
    el.querySelectorAll('.ds-pose-item').forEach(function (item) {
      self.on(item, 'click', function () {
        if (!self.selectedPuppetId) {
          self.setStatus('请先选中一个人偶');
          return;
        }
        self.applyPose(item.dataset.pose);
        self.highlightPose(item.dataset.pose);
      });
    });
  };

  DirectorEditor.prototype.highlightPose = function (poseKey) {
    var self = this;
    this.$('dsPoseList').querySelectorAll('.ds-pose-item').forEach(function (item) {
      var p = self.getPuppet(self.selectedPuppetId);
      item.classList.toggle('active', !!p && p.pose === item.dataset.pose);
    });
  };

  // ---------- 右栏属性面板 ----------

  DirectorEditor.prototype.renderPropsPanel = function () {
    var panel = this.$('dsPropsPanel');
    if (this._panelMode === 'camera') {
      panel.innerHTML = this.buildCameraPropsHtml();
      this.bindCameraProps(panel);
      return;
    }
    var p = this.getPuppet(this.selectedPuppetId);
    if (!p) {
      this._panelMode = 'camera';
      panel.innerHTML = this.buildCameraPropsHtml();
      this.bindCameraProps(panel);
      return;
    }
    panel.innerHTML = this.buildPuppetPropsHtml(p);
    this.bindPuppetProps(panel, p);
    this.highlightPose(p.pose);
  };

  DirectorEditor.prototype.buildPuppetPropsHtml = function (p) {
    var html = '';
    html += '<div class="ds-section-head"><span>人偶属性</span>' +
      '<button class="ds-mini-btn" id="dsSwitchCamProps">镜头设置</button></div>';
    html += '<div class="ds-prop-group">' +
      '<div class="ds-prop-label"><span>名称</span></div>' +
      '<input class="ds-prop-input" id="dsPuppetName" value="' + esc(p.name) + '" maxlength="20" />' +
    '</div>';
    html += '<div class="ds-prop-group">' +
      sliderRow('朝向', 'rotY', -180, 180, 1, fmt(p.rotY), 'dsPupRotY') +
      sliderRow('身高', 'scale', 0.75, 1.25, 0.01, fmt(p.scale), 'dsPupScale') +
      sliderRow('离地高度', 'yOff', -0.5, 0.6, 0.01, fmt(p.rootYOffset), 'dsPupYOff') +
    '</div>';
    html += '<div class="ds-prop-group">' +
      '<div class="ds-prop-label"><span>位置</span><span class="ds-prop-value" id="dsPupPos">' + fmt(p.x) + ', ' + fmt(p.z) + '</span></div>' +
    '</div>';
    html += JOINT_GROUPS.map((g) => {
      return '<details class="ds-joint-details" open>' +
        '<summary>' + esc(g.label) + '</summary>' +
        '<div class="ds-joint-body">' +
        g.joints.map((jk) => {
          var deg = p.jointDeg[jk] || [0, 0, 0];
          var active = jk === this.selectedJointKey ? ' active' : '';
          return '<div class="ds-joint-row' + active + '" data-joint="' + jk + '">' +
            '<div class="ds-joint-name"><span>' + esc(JOINT_LABELS[jk]) + '</span>' +
            '<button class="ds-joint-reset" data-reset="' + jk + '">重置</button></div>' +
            sliderRow('X', jk + '-x', -150, 150, 1, String(Math.round(deg[0])), '') +
            sliderRow('Y', jk + '-y', -150, 150, 1, String(Math.round(deg[1])), '') +
            sliderRow('Z', jk + '-z', -150, 150, 1, String(Math.round(deg[2])), '') +
          '</div>';
        }).join('') +
        '</div></details>';
    }).join('');
    return html;
  };

  function sliderRow(label, key, min, max, step, val, idAttr) {
    var id = idAttr ? ' id="' + idAttr + '"' : '';
    return '<div class="ds-slider-row">' +
      '<label title="' + esc(label) + '">' + esc(label) + '</label>' +
      '<input type="range" data-slider="' + esc(key) + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + val + '"' + id + ' />' +
      '<input type="number" class="ds-num" data-num="' + esc(key) + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + val + '" />' +
    '</div>';
  }

  DirectorEditor.prototype.bindPuppetProps = function (panel, p) {
    var self = this;

    // 名称
    var nameInput = panel.querySelector('#dsPuppetName');
    this.on(nameInput, 'change', function () {
      p.name = nameInput.value.trim() || p.name;
      if (p.label && p.label.userData._texture) p.label.userData._texture.dispose();
      p.rig.root.remove(p.label);
      p.label = makeLabelSprite(p.name);
      p.rig.root.add(p.label);
      self.renderPuppetList();
      self.updateSelectionVisuals();
      self.markDirty();
    });

    // 朝向 / 身高 / 离地
    bindTransformSlider.call(this, 'rotY', function (v) { p.rotY = v; self.applyPuppetTransform(p); }, -180, 180);
    bindTransformSlider.call(this, 'scale', function (v) { p.scale = v; self.applyPuppetTransform(p); }, 0.75, 1.25);
    bindTransformSlider.call(this, 'yOff', function (v) { p.rootYOffset = v; self.applyPuppetTransform(p); }, -0.5, 0.6);

    // 关节滑块
    panel.querySelectorAll('input[data-slider]').forEach(function (input) {
      var m = input.dataset.slider.match(/^(.+)-([xyz])$/);
      if (!m) return;
      var jk = m[1], axisIdx = m[2] === 'x' ? 0 : (m[2] === 'y' ? 1 : 2);
      self.on(input, 'input', function () {
        p.jointDeg[jk][axisIdx] = parseFloat(input.value) || 0;
        p.pose = 'custom';
        self.applyJointDeg(p);
        self.syncNum(panel, input.dataset.slider, input.value);
        self.markDirty(true); // 拖动节流，change 时入撤销栈
      });
      self.on(input, 'change', function () {
        p.pose = 'custom';
        self.markDirty();
      });
    });
    panel.querySelectorAll('input[data-num]').forEach(function (input) {
      var m = input.dataset.num.match(/^(.+)-([xyz])$/);
      if (!m) return;
      var jk = m[1], axisIdx = m[2] === 'x' ? 0 : (m[2] === 'y' ? 1 : 2);
      self.on(input, 'change', function () {
        p.jointDeg[jk][axisIdx] = clamp(parseFloat(input.value) || 0, -150, 150);
        p.pose = 'custom';
        self.applyJointDeg(p);
        self.syncSlider(panel, input.dataset.num, p.jointDeg[jk][axisIdx]);
        self.markDirty();
      });
    });

    // 关节行点击 → 场景中该关节高亮
    panel.querySelectorAll('.ds-joint-row').forEach(function (row) {
      self.on(row, 'click', function (e) {
        if (e.target.closest('.ds-joint-reset')) return;
        self.selectedJointKey = row.dataset.joint;
        self.updateSelectionVisuals();
        panel.querySelectorAll('.ds-joint-row').forEach(function (r) {
          r.classList.toggle('active', r.dataset.joint === self.selectedJointKey);
        });
      });
    });
    // 关节重置
    panel.querySelectorAll('.ds-joint-reset').forEach(function (btn) {
      self.on(btn, 'click', function (e) {
        e.stopPropagation();
        var jk = btn.dataset.reset;
        p.jointDeg[jk] = [0, 0, 0];
        p.pose = 'custom';
        self.applyJointDeg(p);
        self.renderPropsPanel();
        self.markDirty();
      });
    });

    // 切换到相机面板
    this.on(panel.querySelector('#dsSwitchCamProps'), 'click', function () {
      self._panelMode = 'camera';
      self.renderPropsPanel();
    });
  };

  function bindTransformSlider(key, apply, min, max) {
    var panel = this.$('dsPropsPanel');
    var slider = panel.querySelector('input[data-slider="' + key + '"]');
    var num = panel.querySelector('input[data-num="' + key + '"]');
    if (!slider) return;
    var self = this;
    this.on(slider, 'input', function () {
      apply(parseFloat(slider.value));
      if (num) num.value = slider.value;
      self.markDirty(true);
    });
    this.on(slider, 'change', function () { self.markDirty(); });
  }

  DirectorEditor.prototype.syncNum = function (panel, key, val) {
    var num = panel.querySelector('input[data-num="' + key + '"]');
    if (num) num.value = val;
  };
  DirectorEditor.prototype.syncSlider = function (panel, key, val) {
    var s = panel.querySelector('input[data-slider="' + key + '"]');
    if (s) s.value = val;
  };

  DirectorEditor.prototype.buildCameraPropsHtml = function () {
    var c = this.virtualCamCfg;
    var html = '';
    html += '<div class="ds-section-head"><span>镜头设置</span>' +
      '<button class="ds-mini-btn" id="dsSwitchPuppetProps">人偶属性</button></div>';
    html += '<div class="ds-prop-group"><div class="ds-prop-label"><span>预设机位</span></div></div>';
    html += '<div class="ds-camera-preset-grid">' +
      Object.keys(CAMERA_PRESETS).map(function (k) {
        return '<div class="ds-pose-item" data-campreset="' + k + '">' + esc(CAMERA_PRESETS[k].label) + '</div>';
      }).join('') +
    '</div>';
    html += '<div class="ds-prop-group">' +
      sliderRow('焦距 FOV', 'cam-fov', 15, 90, 1, String(Math.round(c.fov)), '') +
      sliderRow('高度', 'cam-y', 0.2, 8, 0.05, fmt(c.pos.y), '') +
      sliderRow('焦点高度', 'cam-ty', 0, 4, 0.05, fmt(c.target.y), '') +
      sliderRow('焦点前后', 'cam-tz', -9.5, 9.5, 0.1, fmt(c.target.z), '') +
      sliderRow('焦点左右', 'cam-tx', -9.5, 9.5, 0.1, fmt(c.target.x), '') +
    '</div>';
    html += '<div class="ds-prop-group"><div class="ds-prop-label"><span>机位坐标</span>' +
      '<span class="ds-prop-value" id="dsCamPosRead">' + fmt(c.pos.x) + ', ' + fmt(c.pos.y) + ', ' + fmt(c.pos.z) + '</span></div></div>';
    html += '<div class="ds-prop-group" style="font-size:11px; color:#6b7280; line-height:1.7;">' +
      '提示：场景中红色相机图标可直接拖拽（水平移动）；黄色圆球为对焦中心，可直接拖拽。' +
      '右侧「镜头预览」即最终画面，导出快照将保存该画面。' +
    '</div>';
    return html;
  };

  DirectorEditor.prototype.bindCameraProps = function (panel) {
    var self = this;
    var c = this.virtualCamCfg;

    function applyCam() {
      self.virtualCam.fov = c.fov;
      self.virtualCam.updateProjectionMatrix();
      self.updateCamHelper();
    }

    panel.querySelectorAll('[data-campreset]').forEach(function (item) {
      self.on(item, 'click', function () {
        self.applyCameraPreset(item.dataset.campreset);
        self.renderPropsPanel();
        self.markDirty();
      });
    });

    function bindCam(key, apply) {
      var slider = panel.querySelector('input[data-slider="' + key + '"]');
      if (!slider) return;
      self.on(slider, 'input', function () {
        apply(parseFloat(slider.value));
        self.syncNum(panel, key, slider.value);
        applyCam();
        self.markDirty(true);
      });
      self.on(slider, 'change', function () { self.markDirty(); });
    }
    bindCam('cam-fov', function (v) { c.fov = v; });
    bindCam('cam-y', function (v) { c.pos.y = v; });
    bindCam('cam-ty', function (v) { c.target.y = v; });
    bindCam('cam-tx', function (v) { c.target.x = v; });
    bindCam('cam-tz', function (v) { c.target.z = v; });

    this.on(panel.querySelector('#dsSwitchPuppetProps'), 'click', function () {
      self._panelMode = 'puppet';
      self.renderPropsPanel();
    });
    this.updateCamHelper();
  };

  DirectorEditor.prototype.applyCameraPreset = function (key) {
    var preset = CAMERA_PRESETS[key];
    if (!preset) return;
    if (preset.dynamic === 'over_shoulder') {
      this.applyOverShoulder();
      return;
    }
    this.virtualCamCfg.pos.fromArray(preset.pos);
    this.virtualCamCfg.target.fromArray(preset.target);
    this.virtualCamCfg.fov = preset.fov;
    this.setStatus('机位：' + preset.label);
  };

  // 过肩镜头：基于选中人偶（或第一个人偶）动态计算
  DirectorEditor.prototype.applyOverShoulder = function () {
    var p = this.getPuppet(this.selectedPuppetId) || this.puppets[0];
    if (!p) return;
    var yaw = deg2rad(p.rotY);
    var back = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)).multiplyScalar(-1); // 人偶背后方向
    var right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
    var pos = new THREE.Vector3(p.x, 0, p.z)
      .add(back.clone().multiplyScalar(1.1))
      .add(right.clone().multiplyScalar(0.38));
    pos.y = 1.58;
    var target = new THREE.Vector3(p.x, 0, p.z)
      .add(back.clone().multiplyScalar(-2.5));
    target.y = 1.35;
    this.virtualCamCfg.pos.copy(pos);
    this.virtualCamCfg.target.copy(target);
    this.virtualCamCfg.fov = 38;
    this.setStatus('机位：过肩');
  };

  DirectorEditor.prototype.updateCamHelper = function () {
    var c = this.virtualCamCfg;
    this.camRig.position.copy(c.pos);
    this.camRig.lookAt(c.target);

    // 对焦标记 + 隐形拾取球跟随焦点
    if (this.focusMarker) {
      if (this.focusMarker.parent !== this.scene) this.scene.add(this.focusMarker);
      this.focusMarker.position.copy(c.target);
    }
    if (this.focusPickSphere) {
      if (this.focusPickSphere.parent !== this.scene) this.scene.add(this.focusPickSphere);
      this.focusPickSphere.position.copy(c.target);
    }

    // 相机 → 焦点 视线虚线
    if (this.sightLine) {
      if (this.sightLine.parent !== this.scene) this.scene.add(this.sightLine);
      var posAttr = this.sightLine.geometry.attributes.position;
      posAttr.setXYZ(0, c.pos.x, c.pos.y, c.pos.z);
      posAttr.setXYZ(1, c.target.x, c.target.y, c.target.z);
      posAttr.needsUpdate = true;
      this.sightLine.geometry.computeBoundingSphere();
      this.sightLine.computeLineDistances();
    }
  };

  // ---------- 视口交互 ----------

  // 屏幕坐标 → NDC（原型方法，交互与 hover 共用）
  DirectorEditor.prototype.ndcAt = function (e) {
    var canvas = this.$('dsCanvas');
    var rect = canvas.getBoundingClientRect();
    return new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
  };

  // 射线拾取：joint marker → 人偶 body → 相机 helper / 焦点球
  DirectorEditor.prototype.pickAt = function (e) {
    this.raycaster.setFromCamera(this.ndcAt(e), this.viewCam);
    var hits = [];
    // 1. 关节球（选中人偶的）
    var sel = this.getPuppet(this.selectedPuppetId);
    if (sel) {
      Object.keys(sel.rig.markers).forEach(function (k) {
        if (sel.rig.markers[k].visible) hits.push(sel.rig.markers[k]);
      });
      var mh = this.raycaster.intersectObjects(hits, false);
      if (mh.length) return { type: 'joint', jointKey: mh[0].object.userData.jointKey, puppet: sel };
    }
    // 2. 人偶 body
    var meshes = [];
    this.puppets.forEach(function (p) { meshes.push.apply(meshes, p.rig.bodyMeshes); });
    var ph = this.raycaster.intersectObjects(meshes, false);
    if (ph.length) return { type: 'puppet', puppet: this.getPuppet(ph[0].object.userData.puppetId) };
    // 3. 焦点标记（隐形拾取球；优先于相机组合体检测，避免视锥线抢先命中）
    if (this.focusPickSphere) {
      var fh = this.raycaster.intersectObject(this.focusPickSphere, false);
      if (fh.length) return { type: 'focus' };
    }
    // 4. 相机 helper（机身 / 镜筒 / 视锥线）
    var ch = this.raycaster.intersectObject(this.camRig, true);
    if (ch.length) {
      return { type: 'camera' };
    }
    return null;
  };

  // 悬停检测：更新 cursor 与跟随提示（30ms 节流）
  DirectorEditor.prototype.handleHover = function (e) {
    var now = Date.now();
    if (now - this._lastHoverAt < 30) {
      this.moveHoverTip(e);
      return;
    }
    this._lastHoverAt = now;
    var hit = null;
    try { hit = this.pickAt(e); } catch (err) { hit = null; console.log('[DS-HOVER] pickAt error:', err && err.message); }
    var cursor = '';
    var text = '';
    if (hit) {
      if (hit.type === 'joint') {
        cursor = 'pointer';
        text = '🖱 ' + (JOINT_LABELS[hit.jointKey] || hit.jointKey) + ' — 点击选中关节';
      } else if (hit.type === 'puppet') {
        cursor = 'grab';
        text = '🧍 ' + hit.puppet.name + ' — 按住拖动移动，单击选中';
      } else if (hit.type === 'camera') {
        cursor = 'move';
        text = '🎥 虚拟相机 — 按住拖动机位，单击选中';
      } else if (hit.type === 'focus') {
        cursor = 'move';
        text = '🎯 对焦中心 — 镜头看向这里，按住拖动';
      }
    }
    var canvas = this.$('dsCanvas');
    if (canvas) canvas.style.cursor = cursor;
    var tip = this.$('dsHoverTip');
    if (tip) {
      if (text) {
        tip.textContent = text;
        tip.classList.add('show');
        this.moveHoverTip(e);
      } else {
        tip.classList.remove('show');
      }
    }
  };

  DirectorEditor.prototype.moveHoverTip = function (e) {
    var wrap = this.$('dsViewportWrap');
    var tip = this.$('dsHoverTip');
    if (!wrap || !tip || !tip.classList.contains('show')) return;
    var rect = wrap.getBoundingClientRect();
    var x = e.clientX - rect.left + 16;
    var y = e.clientY - rect.top + 18;
    var maxX = rect.width - tip.offsetWidth - 8;
    var maxY = rect.height - tip.offsetHeight - 8;
    tip.style.left = Math.max(8, Math.min(x, maxX)) + 'px';
    tip.style.top = Math.max(8, Math.min(y, maxY)) + 'px';
  };

  // 拖拽模式横幅：明确告知当前拖动操作的对象
  DirectorEditor.prototype.showDragBanner = function (mode, extra) {
    var map = {
      orbit: '🔄 旋转视角 — 只改变观察角度，不影响镜头画面',
      pan: '✋ 平移视角 — 只改变观察角度，不影响镜头画面',
      puppet: '🧍 移动人偶' + (extra ? '：' + extra : '') + ' — 松开鼠标落位',
      camera: '🎥 移动机位 — 水平拖动；高度用右侧「镜头设置」滑块调整',
      focus: '🎯 移动对焦中心 — 镜头始终看向它'
    };
    var cursorMap = { orbit: 'grabbing', pan: 'move', puppet: 'grabbing', camera: 'move', focus: 'move' };
    var banner = this.$('dsDragBanner');
    if (banner) {
      banner.textContent = map[mode] || '';
      banner.classList.add('show');
    }
    var hint = this.$('dsModeHint');
    if (hint) hint.style.display = 'none';
    var canvas = this.$('dsCanvas');
    if (canvas) canvas.style.cursor = cursorMap[mode] || '';
    var htip = this.$('dsHoverTip');
    if (htip) htip.classList.remove('show');
  };

  DirectorEditor.prototype.hideDragBanner = function () {
    var banner = this.$('dsDragBanner');
    var hint = this.$('dsModeHint');
    if (banner) banner.classList.remove('show');
    if (hint) hint.style.display = '';
    var canvas = this.$('dsCanvas');
    if (canvas) canvas.style.cursor = '';
  };

  DirectorEditor.prototype.setupViewportInteraction = function () {
    var canvas = this.$('dsCanvas');
    var wrap = this.$('dsViewportWrap');
    var self = this;

    function groundPoint(e, planeY) {
      self.raycaster.setFromCamera(self.ndcAt(e), self.viewCam);
      self.dragPlane.constant = -(planeY || 0);
      var v = new THREE.Vector3();
      return self.raycaster.ray.intersectPlane(self.dragPlane, v) ? v : null;
    }

    this.on(canvas, 'pointerdown', function (e) {
      canvas.focus();
      canvas.setPointerCapture(e.pointerId);
      var hit = e.button === 0 ? self.pickAt(e) : null;
      self.orbitStart = null;

      if (e.button === 0 && hit) {
        if (hit.type === 'joint') {
          self.selectPuppet(hit.puppet.id, hit.jointKey);
          self.setStatus('调整关节：' + (JOINT_LABELS[hit.jointKey] || hit.jointKey));
          return;
        }
        if (hit.type === 'puppet') {
          if (self.selectedPuppetId !== hit.puppet.id) {
            self.selectPuppet(hit.puppet.id, null);
          }
          var gp = groundPoint(e, 0);
          if (gp) {
            self.dragging = {
              mode: 'puppet', puppet: hit.puppet,
              offX: gp.x - hit.puppet.x, offZ: gp.z - hit.puppet.z
            };
            self.showDragBanner('puppet', hit.puppet.name);
          }
          return;
        }
        if (hit.type === 'camera') {
          self.selectCamera('camera');
          var cp = groundPoint(e, self.virtualCamCfg.pos.y);
          if (cp) {
            self.dragging = {
              mode: 'camera',
              offX: cp.x - self.virtualCamCfg.pos.x,
              offZ: cp.z - self.virtualCamCfg.pos.z
            };
          }
          self.showDragBanner('camera');
          return;
        }
        if (hit.type === 'focus') {
          self.selectCamera('focus');
          var fp = groundPoint(e, self.virtualCamCfg.target.y);
          if (fp) {
            self.dragging = {
              mode: 'focus',
              offX: fp.x - self.virtualCamCfg.target.x,
              offZ: fp.z - self.virtualCamCfg.target.z
            };
          }
          self.showDragBanner('focus');
          return;
        }
      }

      // 空白处：视角控制
      self.dragging = {
        mode: e.button === 2 ? 'pan' : 'orbit',
        lastX: e.clientX, lastY: e.clientY, moved: false
      };
      self.showDragBanner(self.dragging.mode);
    });

    this.on(canvas, 'pointermove', function (e) {
      var d = self.dragging;
      if (!d) {
        self.handleHover(e);
        return;
      }

      if (d.mode === 'orbit') {
        var dx = e.clientX - d.lastX, dy = e.clientY - d.lastY;
        if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
        self.orbit.theta -= dx * 0.006;
        self.orbit.phi = clamp(self.orbit.phi - dy * 0.005, 0.12, 1.5);
        d.lastX = e.clientX; d.lastY = e.clientY;
      } else if (d.mode === 'pan') {
        var px = e.clientX - d.lastX, py = e.clientY - d.lastY;
        if (Math.abs(px) + Math.abs(py) > 2) d.moved = true;
        var scale = self.orbit.radius * 0.0016;
        var right = new THREE.Vector3(Math.cos(self.orbit.theta), 0, -Math.sin(self.orbit.theta));
        self.orbit.target.addScaledVector(right, -px * scale);
        self.orbit.target.y = clamp(self.orbit.target.y + py * scale, 0, 8);
        d.lastX = e.clientX; d.lastY = e.clientY;
      } else if (d.mode === 'puppet') {
        var gp = groundPoint(e, 0);
        if (gp) {
          d.puppet.x = clamp(gp.x - d.offX, -GROUND_LIMIT, GROUND_LIMIT);
          d.puppet.z = clamp(gp.z - d.offZ, -GROUND_LIMIT, GROUND_LIMIT);
          self.applyPuppetTransform(d.puppet);
          var posEl = self.$('dsPupPos');
          if (posEl) posEl.textContent = fmt(d.puppet.x) + ', ' + fmt(d.puppet.z);
        }
      } else if (d.mode === 'camera') {
        var cp = groundPoint(e, self.virtualCamCfg.pos.y);
        if (cp) {
          self.virtualCamCfg.pos.x = clamp(cp.x - d.offX, -GROUND_LIMIT, GROUND_LIMIT);
          self.virtualCamCfg.pos.z = clamp(cp.z - d.offZ, -GROUND_LIMIT, GROUND_LIMIT);
          self.updateCamHelper();
          self.syncCameraPanelSliders();
        }
      } else if (d.mode === 'focus') {
        var fp = groundPoint(e, self.virtualCamCfg.target.y);
        if (fp) {
          self.virtualCamCfg.target.x = clamp(fp.x - d.offX, -GROUND_LIMIT, GROUND_LIMIT);
          self.virtualCamCfg.target.z = clamp(fp.z - d.offZ, -GROUND_LIMIT, GROUND_LIMIT);
          self.updateCamHelper();
          self.syncCameraPanelSliders();
        }
      }
    });

    this.on(canvas, 'pointerup', function (e) {
      var d = self.dragging;
      self.dragging = null;
      self.hideDragBanner();
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
      if (!d) return;
      if ((d.mode === 'puppet' || d.mode === 'camera' || d.mode === 'focus')) {
        self.markDirty();
      } else if (d.mode === 'orbit' && !d.moved && e.button === 0) {
        // 点击空白取消选中（人偶 / 相机 / 焦点）
        if (self.selectedPuppetId !== null || self.selectedCamTarget !== null) {
          self.selectedPuppetId = null;
          self.selectedJointKey = null;
          self.selectedCamTarget = null;
          self._panelMode = 'camera';
          self.renderPuppetList();
          self.renderPropsPanel();
          self.updateSelectionVisuals();
        }
      }
    });

    this.on(canvas, 'pointerleave', function () {
      if (self.dragging) return;
      var tip = self.$('dsHoverTip');
      if (tip) tip.classList.remove('show');
      canvas.style.cursor = '';
    });

    this.on(canvas, 'wheel', function (e) {
      e.preventDefault();
      self.orbit.radius = clamp(self.orbit.radius * (1 + (e.deltaY > 0 ? 0.09 : -0.08)), 1.6, 30);
    }, { passive: false });

    this.on(canvas, 'contextmenu', function (e) { e.preventDefault(); });

    // 工具栏
    this.on(this.$('dsFocusBtn'), 'click', function () {
      var p = self.getPuppet(self.selectedPuppetId);
      if (p) {
        self.orbit.target.set(p.x, 0.95 * p.scale, p.z);
      } else {
        self.orbit.target.copy(self.virtualCamCfg.target);
      }
    });
    this.on(this.$('dsGridBtn'), 'click', function () {
      self.gridVisible = !self.gridVisible;
      self.grid.visible = self.gridVisible;
      this.classList.toggle('active', self.gridVisible);
    });
    this.on(this.$('dsResetViewBtn'), 'click', function () {
      self.orbit = { theta: 0.55, phi: 1.02, radius: 8.5, target: new THREE.Vector3(0, 1.0, 0) };
    });

    // 尺寸自适应
    this.roObserver = new ResizeObserver(function () {
      var w = wrap.clientWidth, h = wrap.clientHeight;
      if (w > 0 && h > 0) {
        self.renderer.setSize(w, h, false);
        self.viewCam.aspect = w / h;
        self.viewCam.updateProjectionMatrix();
      }
    });
    this.roObserver.observe(wrap);
  };

  DirectorEditor.prototype.updateCamPosRead = function () {
    var el = this.$('dsCamPosRead');
    if (!el) return;
    var c = this.virtualCamCfg;
    el.textContent = fmt(c.pos.x) + ', ' + fmt(c.pos.y) + ', ' + fmt(c.pos.z);
  };

  // 拖拽相机/焦点后，同步右栏镜头面板的滑块与数值显示
  DirectorEditor.prototype.syncCameraPanelSliders = function () {
    var panel = this.$('dsPropsPanel');
    if (!panel || this._panelMode !== 'camera') return;
    var c = this.virtualCamCfg;
    var map = {
      'cam-fov': Math.round(c.fov),
      'cam-y': Math.round(c.pos.y * 20) / 20,
      'cam-ty': Math.round(c.target.y * 20) / 20,
      'cam-tx': Math.round(c.target.x * 10) / 10,
      'cam-tz': Math.round(c.target.z * 10) / 10
    };
    var keys = Object.keys(map);
    for (var i = 0; i < keys.length; i++) {
      var s = panel.querySelector('input[data-slider="' + keys[i] + '"]');
      var n = panel.querySelector('input[data-num="' + keys[i] + '"]');
      if (s) s.value = map[keys[i]];
      if (n) n.value = map[keys[i]];
    }
    this.updateCamPosRead();
  };

  // ---------- 添加人偶弹层 ----------

  DirectorEditor.prototype.setupAddPuppet = function () {
    var self = this;
    var pop = this.$('dsAddPop');
    var body = this.$('dsAddPopBody');

    function closePop() { pop.classList.remove('show'); }

    this.on(this.$('dsAddPuppetBtn'), 'click', async function () {
      body.innerHTML = '<div style="color:#6b7280; font-size:12px; padding:8px 0;">加载中…</div>';
      pop.classList.add('show');
      var items = ['<div class="ds-char-item" data-blank="1"><span class="ds-char-placeholder">🧍</span><span>空白人偶</span></div>'];
      try {
        var worldId = '';
        var ws = document.getElementById('defaultWorldSelect');
        if (ws) worldId = ws.value;
        if (worldId) {
          var headers = {};
          var token = localStorage.getItem('auth_token');
          if (token) headers['Authorization'] = token;
          var uid = localStorage.getItem('user_id');
          if (uid) headers['X-User-Id'] = uid;
          var resp = await fetch('/api/characters?world_id=' + encodeURIComponent(worldId) + '&page=1&page_size=100', { headers: headers });
          var result = await resp.json();
          if (result.code === 0 && result.data && result.data.data) {
            result.data.data.forEach(function (c) {
              var img = c.avatar_url || c.image_url || c.reference_image || '';
              var thumb = img
                ? '<img src="' + esc(normalizeImageUrl ? normalizeImageUrl(img) : img) + '" alt="">'
                : '<span class="ds-char-placeholder">👤</span>';
              items.push('<div class="ds-char-item" data-cid="' + esc(String(c.id)) + '" data-cname="' + esc(c.name || '') + '">' + thumb + '<span>' + esc(c.name || ('角色 ' + c.id)) + '</span></div>');
            });
          }
        } else {
          items.push('<div style="color:#6b7280; font-size:11px; padding:4px 0;">未选择世界，仅可添加空白人偶</div>');
        }
      } catch (err) {
        items.push('<div style="color:#f87171; font-size:11px; padding:4px 0;">角色列表加载失败</div>');
      }
      body.innerHTML = items.join('');

      body.querySelectorAll('.ds-char-item').forEach(function (item) {
        self.on(item, 'click', function () {
          var p;
          if (item.dataset.blank) {
            p = self.addPuppet({ name: '人偶 ' + (self.puppets.length + 1) });
          } else {
            p = self.addPuppet({
              name: item.dataset.cname || '角色人偶',
              characterId: parseInt(item.dataset.cid, 10) || null,
              characterName: item.dataset.cname || ''
            });
          }
          closePop();
          self.setStatus('已添加「' + p.name + '」');
        });
      });
    });

    this.on(this.$('dsAddPopClose'), 'click', closePop);
    this.on(this.overlay, 'pointerdown', function (e) {
      if (!pop.classList.contains('show')) return;
      if (!pop.contains(e.target) && e.target.id !== 'dsAddPuppetBtn') closePop();
    });
  };

  // ---------- 快照导出 ----------

  DirectorEditor.prototype.renderSnapshotDataUrl = function () {
    this.setHelpersVisible(false);
    this.pipRenderer.render(this.scene, this.virtualCam);
    var dataUrl = this.pipRenderer.domElement.toDataURL('image/jpeg', 0.92);
    this.setHelpersVisible(true);
    return dataUrl;
  };

  DirectorEditor.prototype.setHelpersVisible = function (visible) {
    this.grid.visible = visible && this.gridVisible;
    this.camRig.visible = visible;
    if (this.focusMarker) this.focusMarker.visible = visible;
    if (this.sightLine) this.sightLine.visible = visible;
    this.updateCamSelectRing();
    var self = this;
    this.puppets.forEach(function (p) {
      Object.keys(p.rig.markers).forEach(function (k) { p.rig.markers[k].visible = false; });
      if (p.label) p.label.visible = visible;
      if (visible && p.id === self.selectedPuppetId) {
        Object.keys(p.rig.markers).forEach(function (k) { p.rig.markers[k].visible = true; });
      }
    });
  };

  DirectorEditor.prototype.exportSnapshot = async function () {
    var btn = this.$('dsExportBtn');
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = '导出中…';
    try {
      var dataUrl = this.renderSnapshotDataUrl();
      var blob = dataUrlToBlob(dataUrl);
      var file = new File([blob], 'director_snapshot.jpg', { type: 'image/jpeg' });
      var url = null;
      if (typeof uploadFile === 'function') {
        url = await uploadFile(file);
      }
      if (!url) throw new Error('上传失败');
      this.node.data.snapshotUrl = url;
      this.node.data.snapshotRatio = getWorkflowRatio();
      this.updateNodeShell();

      // 导出快照后，在画布上自动创建展示该快照的图片节点并连线
      var ratio = getWorkflowRatio();
      var imgNodeId = null;
      if (typeof window.createDirectorStageImageNode === 'function') {
        imgNodeId = window.createDirectorStageImageNode(this.node, url, ratio);
      }

      if (typeof safeAutoSave === 'function') safeAutoSave();
      this.setStatus(imgNodeId ? '快照已导出，已在画布生成图片节点' : '快照已导出并更新节点缩略图');
      if (typeof showToast === 'function') {
        showToast(imgNodeId ? '快照已导出，已在画布生成图片节点' : '导演台快照已导出', 'success');
      }
    } catch (err) {
      console.error('导出快照失败:', err);
      if (typeof showToast === 'function') showToast('导出快照失败: ' + (err.message || err), 'error');
      this.setStatus('导出失败');
    } finally {
      btn.disabled = false;
      btn.textContent = '📷 导出快照';
    }
  };

  // 节点壳缩略图/信息更新（由节点模块提供）
  DirectorEditor.prototype.updateNodeShell = function () {
    if (typeof window.updateDirectorStageNodeShell === 'function') {
      window.updateDirectorStageNodeShell(this.nodeId);
    }
  };

  // ---------- 渲染循环 ----------

  DirectorEditor.prototype.startLoop = function () {
    var self = this;
    var o = this.orbit;
    function frame() {
      if (!self.overlay || !self.overlay.classList.contains('show')) return;
      self.rafId = requestAnimationFrame(frame);

      // 编辑视角
      var sp = Math.sin(o.phi), cp = Math.cos(o.phi);
      self.viewCam.position.set(
        o.target.x + o.radius * sp * Math.sin(o.theta),
        o.target.y + o.radius * cp,
        o.target.z + o.radius * sp * Math.cos(o.theta)
      );
      self.viewCam.lookAt(o.target);

      // 虚拟相机姿态
      self.virtualCam.position.copy(self.virtualCamCfg.pos);
      self.virtualCam.lookAt(self.virtualCamCfg.target);
      self.virtualCam.fov = self.virtualCamCfg.fov;
      self.virtualCam.updateProjectionMatrix();

      self.renderer.render(self.scene, self.viewCam);

      // 对焦十字呼吸动画 + 选中放大
      if (self.focusMarker) {
        var tNow = (window.performance && performance.now) ? performance.now() / 1000 : Date.now() / 1000;
        var fBase = self.selectedCamTarget === 'focus' ? 0.32 : 0.22;
        var fPulse = 1 + 0.05 * Math.sin(tNow * 3);
        self.focusMarker.scale.set(fBase * fPulse, fBase * fPulse, 1);
      }

      // PiP（隐藏 helper 再渲染）
      self.setHelpersVisible(false);
      self.pipRenderer.render(self.scene, self.virtualCam);
      self.setHelpersVisible(true);
    }
    this.rafId = requestAnimationFrame(frame);
  };

  // ---------- 生命周期 ----------

  DirectorEditor.prototype.open = function () {
    if (!window.THREE) {
      if (typeof showToast === 'function') showToast('导演台组件(three.js)加载失败，请刷新页面重试', 'error');
      return false;
    }
    this.injectDom();
    this.initScene();
    this.restoreFromData();
    this.renderPuppetList();
    this.renderPoseList();
    this.renderEnvSection();
    this._panelMode = 'camera';
    this.renderPropsPanel();
    this.updateSelectionVisuals();
    this.updateCamHelper();
    this.setupViewportInteraction();
    this.setupAddPuppet();
    this.bindTopbar();
    this.overlay.classList.add('show');

    this.$('dsSubtitle').textContent = this.node.title || '';
    this.setStatus('就绪');

    // 初始尺寸
    var wrap = this.$('dsViewportWrap');
    this.renderer.setSize(wrap.clientWidth, wrap.clientHeight, false);
    this.viewCam.aspect = wrap.clientWidth / wrap.clientHeight;
    this.viewCam.updateProjectionMatrix();

    this.startLoop();
    return true;
  };

  DirectorEditor.prototype.bindTopbar = function () {
    var self = this;
    this.on(this.$('dsBackBtn'), 'click', function () { self.close(true); });
    this.on(this.$('dsDoneBtn'), 'click', function () { self.close(true); });
    this.on(this.$('dsUndoBtn'), 'click', function () { self.undo(); });
    this.on(this.$('dsExportBtn'), 'click', function () { self.exportSnapshot(); });
    this.on(document, 'keydown.directorStage', function (e) {
      if (!self.overlay || !self.overlay.classList.contains('show')) return;
      if (e.key === 'Escape') { self.close(true); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); self.undo(); }
      else if (e.key.toLowerCase() === 'delete' && self.selectedPuppetId) {
        var tag = document.activeElement && document.activeElement.tagName;
        if (tag !== 'INPUT' && tag !== 'TEXTAREA') self.removePuppet(self.selectedPuppetId);
      }
    });
  };

  DirectorEditor.prototype.close = function (flush) {
    // 收尾数据
    this.node.data.directorData = this.serializeData();
    this.updateNodeShell();
    if (this.dirtyTimer) { clearTimeout(this.dirtyTimer); this.dirtyTimer = null; }
    if (typeof safeAutoSave === 'function') safeAutoSave();
    if (flush && typeof flushAutoSave === 'function') {
      try { flushAutoSave(); } catch (e) { /* noop */ }
    }

    if (this.rafId) cancelAnimationFrame(this.rafId);
    if (this.roObserver) this.roObserver.disconnect();
    this.removeEnvironment();
    this.bound.forEach(function (b) {
      try { b[0].removeEventListener(b[1], b[2], b[3]); } catch (e) { /* noop */ }
    });
    this.bound = [];
    this.clearPuppets();

    // dispose renderer
    try { this.renderer.dispose(); } catch (e) { /* noop */ }
    try { this.pipRenderer.dispose(); } catch (e) { /* noop */ }
    if (this.camSelectRing && this.camSelectRing.parent) this.camSelectRing.parent.remove(this.camSelectRing);
    if (this.focusMarker) {
      if (this.focusMarker.parent) this.focusMarker.parent.remove(this.focusMarker);
      if (this.focusMarker.userData._texture) this.focusMarker.userData._texture.dispose();
      this.focusMarker.material.dispose();
    }
    if (this.focusPickSphere && this.focusPickSphere.parent) this.focusPickSphere.parent.remove(this.focusPickSphere);
    if (this.sightLine && this.sightLine.parent) {
      this.sightLine.parent.remove(this.sightLine);
      this.sightLine.geometry.dispose();
      this.sightLine.material.dispose();
    }

    if (this.overlay) this.overlay.remove();
    ed = null;
  };

  // ============ 对外 API ============

  function openDirectorStageEditor(nodeId) {
    if (ed) ed.close(false);
    try {
      ed = new DirectorEditor(nodeId);
      return ed.open();
    } catch (err) {
      console.error('打开导演台失败:', err);
      if (typeof showToast === 'function') showToast('打开导演台失败: ' + (err.message || err), 'error');
      ed = null;
      return false;
    }
  }

  function isDirectorStageEditorOpen() {
    return !!(ed && ed.overlay && ed.overlay.classList.contains('show'));
  }

  window.DirectorStageEditor = {
    open: openDirectorStageEditor,
    isOpen: isDirectorStageEditorOpen
  };
})();
