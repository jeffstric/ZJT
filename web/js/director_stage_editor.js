// ============================
// director_stage_editor.js - 导演台 3D 编辑器
// 类似 liblib 导演台：创建人偶 / 移动人偶 / 控制人偶姿态 / 设置镜头
// 依赖: /assets/vendor/three.min.js (r128 UMD)
// DOM 由本模块自注入（与 image_doodle_editor.js 同模式），样式在 /css/director_stage.css
// ============================

(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  // ============ 常量 ============

  var GROUND_LIMIT = 9.5;             // 人偶/相机可拖拽范围
  var PUPPET_Y_MIN = -0.5;            // 人偶离地高度下限
  var PUPPET_Y_MAX = 2.0;             // 人偶离地高度上限（轴向拖动）
  var HIP_H = 0.905;                  // 默认髋关节离地高度（米），具体体型见 BODY_TYPES
  var MAX_UNDO = 50;

  var PUPPET_COLORS = ['#4f8ef7', '#f76f5e', '#34c38f', '#b57de8', '#e8b34d', '#4dc3e8', '#f07ab6', '#8d9aa8'];

  // ============ male_base_mesh.glb（男性高精度人台）预载 ============
  // 男人体型优先使用外部蒙皮骨骼人台替换程序化人偶；其余体型保留程序化实现。
  // 预载在模块加载即开始，GLB 只有 93KB；未就绪或失败时 buildPuppetRig 自动回退程序化人偶。
  var MALE_BASE_MESH_URL = '/assets/puppet/male_base_mesh.glb';
  var MALE_BASE_MESH_STATE = 'idle';
  var maleBaseMeshGltf = null;
  // 注意：不要在常量区自动调用 preloadMaleBaseMesh()——提取几何块的测试/预览 harness
  // 会重复执行该定义；真正的预载统一在模块底部（IIFE 末尾）发起一次。
  function preloadMaleBaseMesh() {
    if (MALE_BASE_MESH_STATE !== 'idle') return;
    if (typeof window === 'undefined' || !window.THREE || !THREE.GLTFLoader) {
      MALE_BASE_MESH_STATE = 'unsupported';
      return;
    }
    MALE_BASE_MESH_STATE = 'loading';
    try {
      new THREE.GLTFLoader().load(MALE_BASE_MESH_URL, function (gltf) {
        maleBaseMeshGltf = gltf;
        MALE_BASE_MESH_STATE = 'ready';
        if (typeof window !== 'undefined') window.__maleBaseMeshState = 'ready';
      }, undefined, function () {
        MALE_BASE_MESH_STATE = 'failed';
        if (typeof window !== 'undefined') window.__maleBaseMeshState = 'failed';
      });
    } catch (e) {
      MALE_BASE_MESH_STATE = 'failed';
    }
  }

  // 人偶关节键 → GLB 骨骼名。注意 GLTFLoader 会按 PropertyBinding 规则去掉节点名中的
  // "."（spine.005 → spine005），映射表必须使用加载后的名字。只列出每段骨骼链的顶骨，
  // 子骨（spine002/004、手指、脚趾等）保持原父子关系跟随顶骨，无需逐个挂载。
  var GLB_JOINT_BONES = {
    spine: 'spine001', chest: 'spine003', neck: 'spine005',
    shoulderL: 'upper_armL', elbowL: 'forearmL', wristL: 'handL',
    shoulderR: 'upper_armR', elbowR: 'forearmR', wristR: 'handR',
    hipL: 'thighL', kneeL: 'shinL', ankleL: 'footL',
    hipR: 'thighR', kneeR: 'shinR', ankleR: 'footR'
  };
  // 关节组父子关系（与 JOINT_GROUPS 的层级一致）
  var GLB_JOINT_PARENTS = {
    spine: 'hipsY', chest: 'spine', neck: 'chest', head: 'neck',
    shoulderL: 'chest', elbowL: 'shoulderL', wristL: 'elbowL',
    shoulderR: 'chest', elbowR: 'shoulderR', wristR: 'elbowR',
    hipL: 'hipsY', kneeL: 'hipL', ankleL: 'kneeL',
    hipR: 'hipsY', kneeR: 'hipR', ankleR: 'kneeR'
  };

  // ==== PUPPET_GEOMETRY_BEGIN ====
  // 人偶体型：关节层级相同。躯干用一条侧轮廓控制点列 profile 描述（[y, rx, rz, zOffset]，
  // y 为相对髋节高度，zOffset 为该高度截面的前移量），构建时沿轮廓密排椭球切片平滑混合成
  // 一体成型身体曲线（苹果/沙漏等），不再用大椭球穿插或另贴胸球/肚球。
  var BODY_TYPES = {
    man: {
      label: '男人', hipH: 0.92, labelY: 2.00, jointR: 0.036, useGlb: true,
      headR: 0.116, headScale: [1, 1.04, 0.98], jaw: 0.74,
      neckR: 0.040, neckH: 0.085, neckY: 0.235,
      spineY: 0.12, chestJointY: 0.13,
      profile: [
        [-0.115, 0.105, 0.092, 0], [-0.06, 0.148, 0.112, 0], [0.00, 0.152, 0.112, 0],
        [0.06, 0.138, 0.102, 0], [0.12, 0.128, 0.096, 0], [0.18, 0.138, 0.100, 0.002],
        [0.24, 0.160, 0.110, 0.004], [0.295, 0.166, 0.112, 0.002], [0.345, 0.152, 0.102, 0],
        [0.39, 0.128, 0.092, 0], [0.425, 0.092, 0.076, 0], [0.455, 0.056, 0.056, 0]
      ],
      shoulderX: 0.225, shoulderY: 0.18,
      upperArmR: 0.047, upperArmH: 0.28, lowerArmR: 0.040, lowerArmH: 0.25, hand: [0.040, 0.058, 0.026],
      hipX: 0.10, hipJointY: -0.045, upperLegR: 0.068, upperLegH: 0.42, lowerLegR: 0.052, lowerLegH: 0.40,
      foot: [0.048, 0.030, 0.105]
    },
    woman: {
      label: '女人', hipH: 0.86, labelY: 1.86, jointR: 0.030,
      headR: 0.102, headScale: [0.92, 1.10, 0.95], jaw: 0.60,
      neckR: 0.030, neckH: 0.09, neckY: 0.225,
      spineY: 0.125, chestJointY: 0.125,
      profile: [
        [-0.11, 0.122, 0.100, 0], [-0.055, 0.160, 0.118, 0], [0.005, 0.158, 0.116, 0.002],
        [0.06, 0.130, 0.098, 0], [0.11, 0.106, 0.086, 0], [0.16, 0.112, 0.090, 0.002],
        [0.21, 0.128, 0.104, 0.012], [0.25, 0.136, 0.116, 0.024], [0.29, 0.128, 0.100, 0.010],
        [0.33, 0.106, 0.082, 0], [0.365, 0.086, 0.072, 0], [0.395, 0.066, 0.060, 0], [0.42, 0.048, 0.048, 0]
      ],
      shoulderX: 0.152, shoulderY: 0.165,
      upperArmR: 0.036, upperArmH: 0.255, lowerArmR: 0.030, lowerArmH: 0.235, hand: [0.032, 0.050, 0.022],
      hipX: 0.108, hipJointY: -0.047, upperLegR: 0.060, upperLegH: 0.40, lowerLegR: 0.042, lowerLegH: 0.375,
      foot: [0.040, 0.025, 0.090]
    },
    child: {
      label: '小孩', hipH: 0.50, labelY: 1.20, jointR: 0.034,
      headR: 0.138, headScale: [1.02, 1.0, 1.0], jaw: 0.82,
      neckR: 0.042, neckH: 0.045, neckY: 0.15,
      spineY: 0.10, chestJointY: 0.10,
      profile: [
        [-0.075, 0.096, 0.088, 0], [-0.02, 0.116, 0.104, 0.002], [0.035, 0.118, 0.108, 0.006],
        [0.09, 0.108, 0.100, 0.004], [0.14, 0.106, 0.094, 0], [0.185, 0.100, 0.088, 0],
        [0.225, 0.086, 0.076, 0], [0.26, 0.072, 0.064, 0], [0.29, 0.054, 0.050, 0], [0.315, 0.042, 0.042, 0]
      ],
      shoulderX: 0.135, shoulderY: 0.12,
      upperArmR: 0.040, upperArmH: 0.155, lowerArmR: 0.034, lowerArmH: 0.135, hand: [0.036, 0.042, 0.028],
      hipX: 0.078, hipJointY: -0.036, upperLegR: 0.052, upperLegH: 0.21, lowerLegR: 0.044, lowerLegH: 0.19,
      foot: [0.040, 0.024, 0.072]
    },
    fat: {
      label: '胖子', hipH: 0.86, labelY: 1.88, jointR: 0.042,
      headR: 0.118, headScale: [1.08, 1.02, 1.06], jaw: 0.86,
      neckR: 0.050, neckH: 0.055, neckY: 0.215,
      spineY: 0.13, chestJointY: 0.145,
      profile: [
        [-0.12, 0.142, 0.122, 0], [-0.055, 0.180, 0.150, 0.004], [0.01, 0.196, 0.166, 0.012],
        [0.075, 0.206, 0.180, 0.024], [0.14, 0.200, 0.176, 0.026], [0.20, 0.188, 0.162, 0.018],
        [0.26, 0.176, 0.146, 0.008], [0.315, 0.158, 0.128, 0.002], [0.36, 0.128, 0.102, 0],
        [0.40, 0.104, 0.086, 0], [0.435, 0.080, 0.070, 0], [0.465, 0.062, 0.060, 0]
      ],
      shoulderX: 0.215, shoulderY: 0.155,
      upperArmR: 0.068, upperArmH: 0.25, lowerArmR: 0.056, lowerArmH: 0.23, hand: [0.045, 0.055, 0.032],
      hipX: 0.12, hipJointY: -0.054, upperLegR: 0.086, upperLegH: 0.39, lowerLegR: 0.066, lowerLegH: 0.36,
      foot: [0.052, 0.030, 0.10]
    },
    thin: {
      label: '瘦子', hipH: 0.95, labelY: 2.08, jointR: 0.028,
      headR: 0.108, headScale: [0.95, 1.08, 0.95], jaw: 0.66,
      neckR: 0.028, neckH: 0.10, neckY: 0.24,
      spineY: 0.11, chestJointY: 0.135,
      profile: [
        [-0.105, 0.088, 0.076, 0], [-0.05, 0.110, 0.088, 0], [0.01, 0.106, 0.084, 0],
        [0.07, 0.094, 0.078, 0], [0.13, 0.096, 0.078, 0], [0.19, 0.106, 0.082, 0],
        [0.25, 0.116, 0.086, 0], [0.305, 0.112, 0.082, 0], [0.35, 0.094, 0.074, 0],
        [0.39, 0.080, 0.068, 0], [0.425, 0.060, 0.056, 0], [0.455, 0.050, 0.050, 0]
      ],
      shoulderX: 0.185, shoulderY: 0.19,
      upperArmR: 0.036, upperArmH: 0.30, lowerArmR: 0.031, lowerArmH: 0.27, hand: [0.032, 0.052, 0.021],
      hipX: 0.082, hipJointY: -0.038, upperLegR: 0.052, upperLegH: 0.45, lowerLegR: 0.042, lowerLegH: 0.43,
      foot: [0.038, 0.022, 0.092]
    }
  };
  var LIMB_JOINTS = {
    shoulderL: 1, shoulderR: 1, elbowL: 1, elbowR: 1, wristL: 1, wristR: 1,
    hipL: 1, hipR: 1, kneeL: 1, kneeR: 1, ankleL: 1, ankleR: 1
  };

  var BODY_TYPE_ORDER = ['man', 'woman', 'child', 'fat', 'thin'];

  function getBodyType(key) {
    return BODY_TYPES[key] || BODY_TYPES.man;
  }
  function normalizeBodyType(key) {
    return BODY_TYPES[key] ? key : 'man';
  }
  function inferBodyType(name, age, identity) {
    var blob = ((name || '') + ' ' + (identity || '') + ' ' + (age || '')).toLowerCase();
    var n = parseInt(age, 10);
    if ((n > 0 && n < 12) || /童|孩|婴|娃|child|kid|baby|toddler/.test(blob)) return 'child';
    if (/胖|肥|\bfat\b|chubby/.test(blob)) return 'fat';
    if (/瘦|slim|thin|skinny/.test(blob)) return 'thin';
    if (/女|woman|female|girl|姐|妹|妈|娘|夫人|阿姨|小姐/.test(blob)) return 'woman';
    return 'man';
  }

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

  // 用 male_base_mesh.glb 构建男人体型人偶：克隆蒙皮模型 → 归一化（面向 +Z、
  // 身高 1.75m、脚底 y=0）→ 新增"头骨"并转移 spine.005 的头侧权重（原模型无头骨，
  // 不补头骨则头部无法跟随"头部"关节）→ 按 GLB_JOINT_BONES 把各段骨骼链的顶骨
  // 用 attach() 重挂到镜像关节组下（attach 保持世界变换，关节滑块的欧拉角语义与
  // 程序化人偶完全一致，姿态预设/时间轴/关节球选中等全部复用）。
  function buildGlbPuppetRig(colorHex, t) {
    var R = (typeof window !== 'undefined') ? window.DirectorStageRendering : null;
    var materialBundle = R ? R.createResinMaterials(colorHex, null) : null;
    var mat = materialBundle ? materialBundle.body
      : new THREE.MeshStandardMaterial({ color: colorHex, roughness: 0.5, metalness: 0 });
    var seamMat = materialBundle ? materialBundle.seam : mat;
    var markerBaseMat = new THREE.MeshBasicMaterial({ color: 0xffd54f, transparent: true, opacity: 0.95 });

    var rig = {
      joints: {}, markers: {}, bodyMeshes: [], materials: [mat, seamMat, markerBaseMat],
      materialBundle: materialBundle,
      bodyType: normalizeBodyType('man'), rootYOffset: 0
    };

    var model = THREE.SkeletonUtils.clone(maleBaseMeshGltf.scene);
    model.updateMatrixWorld(true); // 此刻 matrixWorld == 原始 metarig 空间 == 几何局部空间

    var skinned = null;
    model.traverse(function (o) { if (o.isSkinnedMesh) skinned = o; });
    if (!skinned) throw new Error('male_base_mesh.glb 缺少 SkinnedMesh');
    // r128 的蒙皮由 material.skinning 开关控制（程序参数 skinning: material.skinning，
    // 非自动检测），自定义材质必须显式打开，否则渲染为绑定姿态（T-pose 不动）。
    mat.skinning = true;
    // skinIndex 要做头骨增权手术，几何必须独立副本，避免污染共享缓存
    skinned.geometry = skinned.geometry.clone();
    skinned.frustumCulled = false;
    skinned.material = mat;
    rig.bodyMeshes.push(skinned);

    function findBone(name) {
      var found = null;
      model.traverse(function (o) { if (o.isBone && o.name === name) found = o; });
      return found;
    }

    // —— 头骨手术：原模型脊柱链终止于 spine005，头颈权重全在它身上 ——
    var spine5 = findBone('spine005');
    if (!spine5) throw new Error('male_base_mesh.glb 缺少 spine005 骨骼');
    var skeleton = skinned.skeleton;
    var s5Idx = -1;
    skeleton.bones.forEach(function (b, i) { if (b === spine5) s5Idx = i; });
    var posAttr = skinned.geometry.attributes.position;
    var headTop = -Infinity;
    for (var vi = 0; vi < posAttr.count; vi++) headTop = Math.max(headTop, posAttr.getY(vi));
    var neckBase = new THREE.Vector3().setFromMatrixPosition(spine5.matrixWorld).y;
    var cut = neckBase + (headTop - neckBase) * 0.30; // 切分点：颈根向上 30% 头颈区
    var headBone = new THREE.Bone();
    headBone.name = 'head.glb';
    headBone.position.set(
      new THREE.Vector3().setFromMatrixPosition(spine5.matrixWorld).x,
      cut + (headTop - cut) * 0.25,
      new THREE.Vector3().setFromMatrixPosition(spine5.matrixWorld).z
    );
    // skeleton.init() 按 bones.length 分配 boneMatrices/boneTexture；新增骨骼后必须重建，
    // 否则头骨矩阵写越界（静默丢弃）且纹理槽位不足；boneInverses 数组与缓存共享，
    // 追加前必须复制，否则会把缓存骨架变成 bones/inverses 数量不匹配。
    model.add(headBone);
    headBone.updateMatrixWorld(true);
    skeleton.boneInverses = skeleton.boneInverses.slice();
    skeleton.bones.push(headBone);
    skeleton.boneInverses.push(headBone.matrixWorld.clone().invert());
    skeleton.init();
    var headIdx = skeleton.bones.length - 1;
    var si = skinned.geometry.attributes.skinIndex;
    for (var wi = 0; wi < si.count; wi++) {
      if (posAttr.getY(wi) <= cut) continue;
      var i0 = si.getX(wi), i1 = si.getY(wi), i2 = si.getZ(wi), i3 = si.getW(wi);
      if (i0 !== s5Idx && i1 !== s5Idx && i2 !== s5Idx && i3 !== s5Idx) continue;
      si.setXYZW(wi,
        i0 === s5Idx ? headIdx : i0,
        i1 === s5Idx ? headIdx : i1,
        i2 === s5Idx ? headIdx : i2,
        i3 === s5Idx ? headIdx : i3
      );
    }
    si.needsUpdate = true;

    // —— 归一化：面向 +Z、身高 1.75m、脚底贴地、水平居中 ——
    var container = new THREE.Group();
    container.add(model);
    container.rotation.y = -Math.PI / 2; // 模型原面向 +X
    var b1 = new THREE.Box3().setFromObject(container);
    var rawH = b1.max.y - b1.min.y;
    var s = 1.75 / rawH;
    container.scale.set(s, s, s);
    container.updateMatrixWorld(true);
    var b2 = new THREE.Box3().setFromObject(container);
    container.position.set(-(b2.min.x + b2.max.x) / 2, -b2.min.y, -(b2.min.z + b2.max.z) / 2);

    var root = new THREE.Group();
    rig.root = root;
    root.add(container);
    root.updateMatrixWorld(true);

    var bonePos = function (b) { return new THREE.Vector3().setFromMatrixPosition(b.matrixWorld); };

    // hipsY 挂在骨盆（spine 骨骼头）高度
    var spineBone = findBone('spine');
    var hipH = bonePos(spineBone).y;
    rig.hipH = hipH;
    var hipsY = new THREE.Group();
    hipsY.position.set(0, hipH, 0);
    root.add(hipsY);
    rig.hipsY = hipsY;
    rig.labelY = 1.75 + 0.12;

    function glbJoint(key, parentKey, pos) {
      var parent = parentKey === 'hipsY' ? hipsY : rig.joints[parentKey];
      var g = new THREE.Group();
      g.position.copy(pos);
      parent.add(g);
      rig.joints[key] = g;
      var markerMat = markerBaseMat.clone();
      rig.materials.push(markerMat);
      var marker = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.032, (t.jointR || 0.036) * 0.9), 10, 8), markerMat);
      marker.visible = false;
      marker.userData.jointKey = key;
      g.add(marker);
      rig.markers[key] = marker;
      return g;
    }

    // 先创建全部关节组（位置=对应骨骼头的"相对父组的局部偏移"），再统一重挂骨骼链顶骨。
    // 注意组是嵌套的：bonePos 是世界坐标，必须减去父组世界位置（静止时旋转均为 0，直接相减）。
    var attachPlan = [];
    var order = ['spine', 'chest', 'neck', 'head',
      'shoulderL', 'elbowL', 'wristL', 'shoulderR', 'elbowR', 'wristR',
      'hipL', 'kneeL', 'ankleL', 'hipR', 'kneeR', 'ankleR'];
    var boneOf = {
      spine: 'spine001', chest: 'spine003', neck: 'spine005'
    };
    var groupWorld = { hipsY: new THREE.Vector3(0, hipH, 0) };
    var i, key;
    for (i = 0; i < order.length; i++) {
      key = order[i];
      var targetBone;
      if (key === 'head') {
        targetBone = headBone;
      } else {
        targetBone = findBone(boneOf[key] || GLB_JOINT_BONES[key]);
      }
      if (!targetBone) throw new Error('male_base_mesh.glb 缺少骨骼: ' + (boneOf[key] || GLB_JOINT_BONES[key]));
      var headW = bonePos(targetBone);
      var parentKey = GLB_JOINT_PARENTS[key];
      var parentW = groupWorld[parentKey];
      var local = headW.clone().sub(parentW);
      glbJoint(key, parentKey, local);
      groupWorld[key] = headW;
      attachPlan.push([key, targetBone]);
    }
    root.updateMatrixWorld(true);
    for (i = 0; i < attachPlan.length; i++) {
      rig.joints[attachPlan[i][0]].attach(attachPlan[i][1]);
    }
    root.updateMatrixWorld(true);
    return rig;
  }

  function buildPuppetRig(colorHex, bodyTypeKey, renderer) {
    var t = getBodyType(bodyTypeKey);
    // 男人体型优先使用 GLB 人台；未就绪/构建失败自动回退程序化人偶
    if (t.useGlb === true && MALE_BASE_MESH_STATE === 'ready' && maleBaseMeshGltf && maleBaseMeshGltf.scene) {
      try {
        return buildGlbPuppetRig(colorHex, t);
      } catch (e) {
        console.warn('导演台：GLB 人偶构建失败，已回退程序化人偶。', e);
      }
    }
    var t = getBodyType(bodyTypeKey);
    // 分部位 PBR 树脂材质；无渲染模块时保留 StandardMaterial 回退。
    var materialBundle = null;
    if (typeof window !== 'undefined' && window.DirectorStageRendering) {
      materialBundle = window.DirectorStageRendering.createResinMaterials(colorHex, renderer);
    }
    var mat = materialBundle ? materialBundle.body : new THREE.MeshStandardMaterial({ color: colorHex, roughness: 0.5, metalness: 0.0 });
    var torsoMat = materialBundle ? materialBundle.torso : mat;
    var headMat = materialBundle ? materialBundle.head : mat;
    var seamMat = materialBundle ? materialBundle.seam : new THREE.MeshStandardMaterial({
      color: new THREE.Color(colorHex).multiplyScalar(0.8), roughness: 0.55, metalness: 0.0
    });
    var markerBaseMat = new THREE.MeshBasicMaterial({ color: 0xffd54f, transparent: true, opacity: 0.95 });

    var rig = {
      joints: {}, markers: {}, bodyMeshes: [], materials: [mat, seamMat, markerBaseMat],
      materialBundle: materialBundle,
      hipH: t.hipH, labelY: t.labelY, bodyType: normalizeBodyType(bodyTypeKey)
    };
    if (torsoMat !== mat) rig.materials.push(torsoMat);
    if (headMat !== mat && headMat !== torsoMat) rig.materials.push(headMat);

    // 人偶网格几乎都是缩放球体，rig 内共享同一个单位球几何体
    var unitSphere = new THREE.SphereGeometry(1, 24, 18);

    function ball(r, m2) {
      var mesh = new THREE.Mesh(unitSphere, m2 || mat);
      mesh.scale.set(r, r, r);
      rig.bodyMeshes.push(mesh);
      return mesh;
    }
    function ellip(rx, ry, rz, m2) {
      var m = new THREE.Mesh(unitSphere, m2 || mat);
      m.scale.set(rx, ry, rz);
      rig.bodyMeshes.push(m);
      return m;
    }
    function armorPlate(rx, ry, rz, radius, m2) {
      var geo = materialBundle ? window.DirectorStageRendering.roundedJoint(rx * 2, ry * 2, rz * 2, radius) : null;
      if (!geo) return ellip(rx, ry, rz, m2);
      var mesh = new THREE.Mesh(geo, m2 || mat);
      rig.bodyMeshes.push(mesh);
      return mesh;
    }
    function joint(key, parent, x, y, z) {
      var g = new THREE.Group();
      g.position.set(x, y, z);
      parent.add(g);
      rig.joints[key] = g;
      // 仿生咬合关节：同色关节球（半径略大于肢体端径）+ 深色细咬合环，
      // 呈"承口"结构而非生硬卡球
      if (LIMB_JOINTS[key]) {
        g.add(ball(t.jointR * 1.06, mat));
        var biteRing = new THREE.Mesh(
          new THREE.TorusGeometry(t.jointR * 0.98, t.jointR * 0.15, 8, 18),
          seamMat,
        );
        biteRing.rotation.x = Math.PI / 2; // 环面法线沿肢体延伸轴（局部 -Y）
        g.add(biteRing);
      }
      var markerMat = markerBaseMat.clone();
      rig.materials.push(markerMat);
      var marker = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.032, t.jointR * 0.9), 10, 8), markerMat);
      marker.visible = false;
      marker.userData.jointKey = key;
      g.add(marker);
      rig.markers[key] = marker;
      return g;
    }
    // 通过控制点的 Catmull-Rom 样条插值（索引空间均匀参数化），返回密集采样表。
    // 注意不能用 smoothstep：它在每个控制点导数为零，旋转成曲面后会留下一圈圈棱线。
    function smoothProfile(ctrl, samples) {
      function cr(p0, p1, p2, p3, f) {
        return 0.5 * ((2 * p1) + (-p0 + p2) * f +
          (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f + (-p0 + 3 * p1 - 3 * p2 + p3) * f * f * f);
      }
      var out = [];
      var n = ctrl.length - 1;
      for (var k = 0; k <= samples; k++) {
        var g = k / samples * n;
        var i = Math.min(Math.floor(g), n - 1);
        var f = g - i;
        var p0 = ctrl[Math.max(0, i - 1)], p1 = ctrl[i], p2 = ctrl[i + 1], p3 = ctrl[Math.min(n, i + 2)];
        var row = [];
        for (var c = 0; c < p1.length; c++) row.push(cr(p0[c] || 0, p1[c] || 0, p2[c] || 0, p3[c] || 0, f));
        out.push(row);
      }
      return out;
    }
    // lathe 曲面在 phi 环绕接缝处的顶点是两份，法线各算一半会留一条竖直接缝，这里把接缝两侧法线焊平。
    // 注意 LatheGeometry 顶点序是"分段在外、控制点在内"：同一圈第 j 点的接缝对是 [j] 与 [segs*rings + j]。
    function weldLatheSeam(geo, segs) {
      var nrm = geo.attributes.normal;
      var rings = nrm.count / (segs + 1);
      for (var j = 0; j < rings; j++) {
        var a = j, b = segs * rings + j;
        var nx = (nrm.getX(a) + nrm.getX(b)) / 2;
        var ny = (nrm.getY(a) + nrm.getY(b)) / 2;
        var nz = (nrm.getZ(a) + nrm.getZ(b)) / 2;
        var len = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
        nrm.setXYZ(a, nx / len, ny / len, nz / len);
        nrm.setXYZ(b, nx / len, ny / len, nz / len);
      }
    }
    // 一段肢体：沿 -Y 的 lathe 平滑曲面，肌肉轮廓一次成型，两端收进球形关节
    function limbSeg(parent, prof2) {
      var pts = smoothProfile(prof2, 24).map(function (p) {
        return new THREE.Vector2(Math.max(0.004, p[1]), p[0]);
      });
      var geo = new THREE.LatheGeometry(pts, 22);
      geo.computeVertexNormals();
      weldLatheSeam(geo, 22);
      var m = new THREE.Mesh(geo, mat);
      rig.bodyMeshes.push(m);
      parent.add(m);
      return m;
    }

    var root = new THREE.Group();
    rig.root = root;

    var hipsY = new THREE.Group();
    hipsY.position.y = t.hipH;
    root.add(hipsY);
    rig.hipsY = hipsY;

    var spine = joint('spine', hipsY, 0, t.spineY, 0);
    var chest = joint('chest', spine, 0, t.chestJointY, 0);

    // 躯干：按 profile 轮廓（[y, rx, rz, zOffset]，y 相对髋节）生成三段连续内芯与对应外甲。
    // 内芯挂 hipsY/spine/chest 并互相嵌入；外甲按骨盆/腹/胸分件，弯腰/转胸时随各自关节联动。
    var spineAbs = t.spineY;
    var chestAbs = t.spineY + t.chestJointY;
    var prof = t.profile;

    var profDense = smoothProfile(prof, 240);
    function profileAt(y) {
      var first = profDense[0], last = profDense[profDense.length - 1];
      if (y <= first[0]) return { rx: first[1], rz: first[2], z: first[3] };
      if (y >= last[0]) return { rx: last[1], rz: last[2], z: last[3] };
      var lo = 0, hi = profDense.length - 1;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (profDense[mid][0] <= y) lo = mid; else hi = mid; }
      var a = profDense[lo], b = profDense[hi];
      var f = (y - a[0]) / Math.max(1e-6, b[0] - a[0]);
      return { rx: a[1] + (b[1] - a[1]) * f, rz: a[2] + (b[2] - a[2]) * f, z: a[3] + (b[3] - a[3]) * f };
    }

    // 躯干段同时用于深色内芯与外侧装甲。内芯的延伸段互相嵌入，保证弯腰/转胸时不断裂；
    // 装甲不设延伸段，以真实窄缝分件。armor 模式压平前后面并略向外抬，形成硬壳而非肌肉轮廓。
    function torsoPart(y0, y1, extDown, extUp, parent, baseY, shellScale, shellMat, armor) {
      var radialScale = shellScale || 1;
      function taper(y) {
        var f = 1;
        if (y < y0 && extDown > 0) f = (y - (y0 - extDown)) / extDown;
        else if (y > y1 && extUp > 0) f = 1 - (y - y1) / extUp;
        f = Math.max(0, Math.min(1, f));
        return f * f * (3 - 2 * f);
      }
      var pts = [];
      var ya = y0 - extDown, yb = y1 + extUp;
      var N = 40;
      for (var k = 0; k <= N; k++) {
        var y = ya + (yb - ya) * k / N;
        pts.push(new THREE.Vector2(Math.max(0.0035, profileAt(y).rz * taper(y) * radialScale), y - baseY));
      }
      var geo = new THREE.LatheGeometry(pts, 28);
      var pos = geo.attributes.position;
      for (var v = 0; v < pos.count; v++) {
        var yAbs = pos.getY(v) + baseY;
        var pr = profileAt(yAbs);
        var ratio = pr.rz > 0.0001 ? pr.rx / pr.rz : 1;
        pos.setX(v, pos.getX(v) * ratio);
        var localZ = pos.getZ(v);
        if (armor) {
          var plateV = clamp((yAbs - y0) / Math.max(0.001, y1 - y0), 0, 1);
          var front = clamp(localZ / Math.max(0.001, pr.rz * radialScale), -1, 1);
          var curve = Math.abs(front);
          var xScale = 1, yShift = 0;
          if (armor === 'chest') {
            // 胸甲上宽下窄，底缘向前/后下方弯成弧面；最小宽度也必须大于内芯。
            yShift = -0.042 * curve * Math.pow(1 - plateV, 3);
            xScale = (0.94 + 0.18 * plateV) * (1 - 0.02 * Math.pow(1 - plateV, 2));
          } else if (armor === 'abdomen') {
            // 腹甲两端随胸甲/骨盆甲弯曲，中间宽、上下窄，形成独立椭圆甲片。
            yShift = -0.012 * curve * Math.pow(1 - plateV, 3) - 0.035 * curve * Math.pow(plateV, 3);
            xScale = 1 - 0.08 * Math.pow(Math.abs(plateV - 0.5) * 2, 2);
          } else if (armor === 'pelvis') {
            // 骨盆甲上宽下窄，前侧向下延伸成护裆，顶部弧线与腹甲保持窄缝。
            yShift = -0.040 * Math.max(0, front) * Math.pow(1 - plateV, 3) - 0.006 * curve * Math.pow(plateV, 3);
            xScale = 1.06 - 0.12 * (1 - plateV);
          }
          pos.setX(v, pos.getX(v) * xScale);
          pos.setY(v, pos.getY(v) + yShift);
          localZ = localZ * 0.86 + (localZ >= 0 ? 0.012 : -0.012);
        }
        pos.setZ(v, localZ + pr.z);
      }
      if (armor && materialBundle) window.DirectorStageRendering.ensureUv2(geo);
      geo.computeVertexNormals();
      weldLatheSeam(geo, 28);
      var mesh = new THREE.Mesh(geo, shellMat || mat);
      rig.bodyMeshes.push(mesh);
      parent.add(mesh);
      return mesh;
    }

    var waistSplit = spineAbs * 0.55;                 // 髋/腰分段高度
    var chestSplit = spineAbs + t.chestJointY * 0.55; // 腰/胸分段高度
    // 深色内芯保持关节活动时的连续性，只在装甲窄缝中露出。
    torsoPart(prof[0][0], waistSplit, 0.05, 0.11, hipsY, 0, 0.90, seamMat);
    torsoPart(waistSplit, chestSplit, 0.07, 0.11, spine, spineAbs, 0.90, seamMat);
    torsoPart(chestSplit, prof[prof.length - 1][0], 0.07, 0.045, chest, chestAbs, 0.90, seamMat);
    // 骨盆甲 / 腹甲 / 胸甲：分件之间留 16mm 窄缝，前后壳面压平形成盔甲硬壳。
    torsoPart(prof[0][0] + 0.006, waistSplit - 0.008, 0, 0, hipsY, 0, 1.025, torsoMat, 'pelvis');
    torsoPart(waistSplit + 0.008, chestSplit - 0.008, 0, 0, spine, spineAbs, 1.025, torsoMat, 'abdomen');
    torsoPart(chestSplit + 0.008, prof[prof.length - 1][0] - 0.004, 0, 0, chest, chestAbs, 1.025, torsoMat, 'chest');
    // 只保留上述结构分件，不再叠加腰线/胸线/腹肌线/锁骨等装饰椭球。

    var neck = joint('neck', chest, 0, t.neckY, 0);
    var neckMesh = ellip(t.neckR * 1.25, t.neckH * 0.7, t.neckR * 1.2);
    neckMesh.position.y = t.neckH * 0.15;
    neck.add(neckMesh);

    var head = joint('head', neck, 0, t.neckH * 0.8, 0);
    var headScale = t.headScale || [1, 1, 1];
    var headCY = t.headR * headScale[1] * 0.82;
    // 无五官连续头型：头顶、太阳穴、下颌由一条连续轮廓成型，面部/后脑由下方
    // 同一网格的顶点处理区分朝向，不叠加任何五官小件。男人体型默认改用 GLB 人台
    //（见 buildGlbPuppetRig），本程序化头型服务于其余体型与 GLB 未就绪时的回退。
    var jawWidth = 0.82 + (t.jaw || 0.74) * 0.18;
    var headProfile = [
      [-1.02, 0.004], [-0.98, 0.26 * jawWidth], [-0.86, 0.58 * jawWidth],
      [-0.62, 0.80 * jawWidth], [-0.30, 0.93 * jawWidth], [0.05, 0.99],
      [0.38, 1.00], [0.66, 0.91], [0.85, 0.70], [0.97, 0.36], [1.02, 0.004]
    ];
    var headPoints = smoothProfile(headProfile, 48).map(function (p) {
      return new THREE.Vector2(Math.max(0.003, p[1]), p[0]);
    });
    var headGeo = new THREE.LatheGeometry(headPoints, 32);
    var headPos = headGeo.attributes.position;
    for (var hi = 0; hi < headPos.count; hi++) {
      var hx = headPos.getX(hi), hy = headPos.getY(hi), hz = headPos.getZ(hi);
      if (hz >= 0) {
        // 面部是平缓硬平面；五官全部由下方独立硬表面小件拼出，绝不用噪声位移软化轮廓。
        var facePlane = 0.74 + 0.06 * (hy + 0.1);
        var faceZone = clamp((0.95 - hy) / 0.25, 0, 1) * clamp((hy + 0.92) / 0.25, 0, 1);
        if (hz > facePlane) hz = facePlane + (hz - facePlane) * (1 - 0.80 * faceZone);
        var chinWeight = Math.exp(-Math.pow((hy + 0.68) / 0.22, 2));
        hz += 0.10 * chinWeight * Math.max(0, 1 - Math.abs(hx));
      } else {
        // 枕部向后鼓起、下脑后收，侧面形成明确的后脑勺轮廓。
        var occiput = Math.exp(-Math.pow((hy - 0.18) / 0.62, 2));
        hz *= 1 + 0.18 * occiput;
      }
      headPos.setXYZ(hi, hx, hy, hz);
    }
    if (materialBundle) window.DirectorStageRendering.ensureUv2(headGeo);
    headGeo.computeVertexNormals();
    weldLatheSeam(headGeo, 32);
    var headMesh = new THREE.Mesh(headGeo, headMat);
    headMesh.scale.set(t.headR * headScale[0], t.headR * headScale[1], t.headR * headScale[2]);
    headMesh.position.y = headCY;
    rig.bodyMeshes.push(headMesh);
    head.add(headMesh);
    // 小巧人耳贴近头侧并略靠后；不旋转、不外伸，避免牛角般的横向轮廓。
    [-1, 1].forEach(function (side) {
      var ear = ellip(t.headR * 0.085, t.headR * 0.20, t.headR * 0.105, headMat);
      ear.position.set(
        side * t.headR * headScale[0] * 0.98,
        headCY - t.headR * 0.08,
        -t.headR * headScale[2] * 0.06
      );
      head.add(ear);
    });

    // 肩甲只覆盖肩部上外侧，不再用完整球体充当三角肌。
    var pauldronGeo = new THREE.SphereGeometry(1, 24, 14, 0, Math.PI * 2, 0, Math.PI * 0.64);
    function buildArm(side) {
      var s = side === 'L' ? 1 : -1;
      var uaH = t.upperArmH, uaR = t.upperArmR;
      var sh = joint('shoulder' + side, chest, s * t.shoulderX * 0.90, t.shoulderY, 0);
      // 肩胸柔性连接芯：从胸甲内部伸到肩关节，随肩部一起转动，外露部分尽量短。
      var shoulderLink = new THREE.Mesh(
        new THREE.CylinderGeometry(uaR * 0.72, uaR * 0.82, t.shoulderX * 0.42, 16),
        seamMat
      );
      shoulderLink.rotation.z = Math.PI / 2;
      shoulderLink.position.set(-s * t.shoulderX * 0.21, 0, 0);
      rig.bodyMeshes.push(shoulderLink);
      sh.add(shoulderLink);
      var pauldron = new THREE.Mesh(pauldronGeo, mat);
      pauldron.scale.set(uaR * 1.70, uaR * 1.55, uaR * 1.50);
      pauldron.position.set(s * uaR * 0.10, -uaR * 0.22, 0);
      pauldron.rotation.z = -s * 0.20;
      rig.bodyMeshes.push(pauldron);
      sh.add(pauldron);
      limbSeg(sh, [
        [0.015, uaR * 1.0], [-uaH * 0.12, uaR * 1.26], [-uaH * 0.38, uaR * 1.16],
        [-uaH * 0.72, uaR * 0.92], [-uaH + 0.012, uaR * 0.82], [-uaH - 0.01, uaR * 0.5]
      ]);
      var elbow = joint('elbow' + side, sh, 0, -uaH, 0);
      var laH = t.lowerArmH, laR = t.lowerArmR;
      // 肘甲使用带倒角的硬壳，与关节球/咬合环组成清晰的护甲结构。
      var elbowCap = armorPlate(uaR * 0.70, uaR * 0.82, uaR * 0.30, uaR * 0.22, mat);
      elbowCap.position.set(0, -uaR * 0.05, laR * 0.95);
      elbow.add(elbowCap);
      limbSeg(elbow, [
        [0.012, laR * 0.9], [-laH * 0.18, laR * 1.22], [-laH * 0.5, laR * 0.98],
        [-laH + 0.012, laR * 0.72], [-laH - 0.01, laR * 0.5]
      ]);
      var wrist = joint('wrist' + side, elbow, 0, -laH, 0);
      // 手部 v3：掌体 + 分节四指（有指节轮廓，中指最长）+ 拇指
      var palm = ellip(t.hand[0], t.hand[1] * 0.70, t.hand[2] * 1.12);
      palm.position.y = -t.hand[1] * 0.28;
      wrist.add(palm);
      var fr = t.hand[0] * 0.185;
      var fingerLens = [0.44, 0.62, 0.58, 0.50];
      for (var fi = 0; fi < 4; fi++) {
        var fl = t.hand[1] * fingerLens[fi];
        var fx = s * (fi - 1.5) * fr * 2.05;
        var fseg = new THREE.Mesh(new THREE.CylinderGeometry(fr * 0.80, fr, fl, 8), mat);
        fseg.position.set(fx, -t.hand[1] * 0.58 - fl * 0.5, 0.002);
        wrist.add(fseg);
        var ftip = ball(fr * 0.80);
        ftip.position.set(fx, -t.hand[1] * 0.58 - fl, 0.002);
        wrist.add(ftip);
      }
      var thumb = ellip(t.hand[0] * 0.36, t.hand[1] * 0.44, t.hand[0] * 0.36);
      thumb.position.set(-s * t.hand[0] * 0.42, -t.hand[1] * 0.16, t.hand[2] * 0.62);
      thumb.rotation.x = 0.55;
      thumb.rotation.z = s * 0.3;
      wrist.add(thumb);
    }
    buildArm('L');
    buildArm('R');

    // 脚型与身体同向（脚尖 +Z）：后跟窄、前掌宽、脚背有起伏、底面压平。
    // 不再用鞋底/鞋身/踝领等多个椭球叠罗汉，避免圆饼脚和前后不分。
    var footProfile = [
      [-1.00, 0.04], [-0.96, 0.34], [-0.82, 0.66], [-0.52, 0.82],
      [-0.12, 0.90], [0.30, 0.98], [0.66, 1.00], [0.88, 0.88],
      [1.00, 0.56], [1.06, 0.04]
    ];
    var footPoints = smoothProfile(footProfile, 32).map(function (p) {
      return new THREE.Vector2(Math.max(0.003, p[1]), p[0]);
    });
    var footGeo = new THREE.LatheGeometry(footPoints, 28);
    footGeo.rotateX(Math.PI / 2); // 原 Y 轴轮廓转为 Z 轴，正端为脚尖
    var footPos = footGeo.attributes.position;
    for (var fi = 0; fi < footPos.count; fi++) {
      var fy = footPos.getY(fi), fz = footPos.getZ(fi);
      if (fy < -0.55) fy = -0.55 + (fy + 0.55) * 0.15;
      if (fy > 0) {
        fy *= 1 - 0.18 * clamp((fz - 0.25) / 0.65, 0, 1); // 前掌低于脚踝脚背
        fy *= 1 + 0.10 * Math.exp(-Math.pow((fz + 0.15) / 0.45, 2));
      }
      footPos.setY(fi, fy);
    }
    footGeo.computeVertexNormals();
    weldLatheSeam(footGeo, 28);
    footGeo.computeBoundingBox();

    function buildLeg(side) {
      var s = side === 'L' ? 1 : -1;
      var hip = joint('hip' + side, hipsY, s * t.hipX, t.hipJointY, 0);
      var ulH = t.upperLegH, ulR = t.upperLegR;
      limbSeg(hip, [
        [0.015, ulR * 1.02], [-ulH * 0.25, ulR * 1.14], [-ulH * 0.65, ulR * 0.90],
        [-ulH + 0.012, ulR * 0.76], [-ulH - 0.01, ulR * 0.5]
      ]);
      var knee = joint('knee' + side, hip, 0, -ulH, 0);
      var llH = t.lowerLegH, llR = t.lowerLegR;
      // 膝甲为前侧独立倒角硬壳，关节球只负责咬合与转动。
      var kneeCap = armorPlate(ulR * 0.82, ulR * 0.95, ulR * 0.34, ulR * 0.26, mat);
      kneeCap.position.set(0, -ulR * 0.12, llR * 0.96);
      knee.add(kneeCap);
      limbSeg(knee, [
        [0.012, llR * 0.92], [-llH * 0.22, llR * 1.14], [-llH * 0.55, llR * 0.86],
        [-llH + 0.010, llR * 0.60], [-llH - 0.008, llR * 0.42]
      ]);
      var ankle = joint('ankle' + side, knee, 0, -t.lowerLegH, 0);
      var ankleH = t.hipH + t.hipJointY - t.upperLegH - t.lowerLegH;
      var foot = new THREE.Mesh(footGeo, mat);
      foot.scale.set(t.foot[0], t.foot[1], t.foot[2] * 1.02);
      foot.position.set(
        0,
        -ankleH - footGeo.boundingBox.min.y * t.foot[1],
        t.foot[2] * 0.18
      );
      rig.bodyMeshes.push(foot);
      ankle.add(foot);
    }
    buildLeg('L');
    buildLeg('R');

    rig.bodyMeshes.forEach(function (m) {
      m.castShadow = m.material !== seamMat;
      m.receiveShadow = true;
    });
    return rig;
  }
  // ==== PUPPET_GEOMETRY_END ====

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

  function makeAxisLabel(text, hex) {
    var canvas = document.createElement('canvas');
    canvas.width = 128; canvas.height = 64;
    var ctx = canvas.getContext('2d');
    ctx.font = '700 30px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 5;
    ctx.strokeStyle = 'rgba(0,0,0,0.65)';
    ctx.fillStyle = '#' + ('000000' + hex.toString(16)).slice(-6);
    ctx.strokeText(text, 64, 34);
    ctx.fillText(text, 64, 34);
    var tex = new THREE.CanvasTexture(canvas);
    tex.needsUpdate = true;
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
    sp.scale.set(0.28, 0.14, 1);
    sp.renderOrder = 1002;
    sp.userData._texture = tex;
    return sp;
  }

  // 世界坐标轴箭头：沿本地 +Y 生长，再旋转到 X/Y/Z
  function makeAxisArrow(axis, color, length, label) {
    var g = new THREE.Group();
    g.userData.gizmoAxis = axis;
    var mat = new THREE.MeshBasicMaterial({
      color: color, depthTest: false, transparent: true, opacity: 0.95
    });
    var shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, length, 8), mat);
    shaft.position.y = length * 0.5;
    var head = new THREE.Mesh(new THREE.CylinderGeometry(0, 0.048, 0.12, 12), mat);
    head.position.y = length + 0.055;
    var pick = new THREE.Mesh(
      new THREE.CylinderGeometry(0.055, 0.055, length + 0.16, 8),
      new THREE.MeshBasicMaterial({ visible: false })
    );
    pick.position.y = (length + 0.16) * 0.5;
    [shaft, head, pick].forEach(function (m) {
      m.userData.gizmoAxis = axis;
      m.userData.baseColor = color;
      m.renderOrder = 1000;
      g.add(m);
    });
    pick.userData._pickOnly = true;
    if (label) {
      var sp = makeAxisLabel(label, color);
      sp.position.y = length + 0.20;
      sp.userData.gizmoAxis = axis;
      g.add(sp);
    }
    if (axis === 'x') g.rotation.z = -Math.PI / 2;
    if (axis === 'z') g.rotation.x = Math.PI / 2;
    return g;
  }

  function buildWorldAxisGizmo() {
    var root = new THREE.Group();
    root.userData._isGizmo = true;
    root.add(makeAxisArrow('x', 0xef4444, 0.55, 'X'));
    root.add(makeAxisArrow('y', 0x22c55e, 0.55, 'Y'));
    root.add(makeAxisArrow('z', 0x3b82f6, 0.55, 'Z'));
    var hub = new THREE.Mesh(
      new THREE.SphereGeometry(0.04, 12, 10),
      new THREE.MeshBasicMaterial({ color: 0xe5e7eb, depthTest: false })
    );
    hub.renderOrder = 1000;
    root.add(hub);
    root.visible = false;
    return root;
  }

  function buildFovAxisGizmo() {
    var root = new THREE.Group();
    root.userData._isGizmo = true;
    var arrow = makeAxisArrow('fov', 0xf59e0b, 0.48, '焦距');
    root.add(arrow);
    root.visible = false;
    return root;
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

    this.puppets = [];          // {id,name,color,bodyType,characterId,characterName,rig,jointDeg:{},x,z,rotY,rootYOffset,scale,pose,label}
    this._pendingBodyType = 'man';
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
    // 多机位：机位列表 + 当前激活机位（编辑直接改 virtualCamCfg，落盘时回写激活机位）
    this.cameras = [];          // [{id, name, pos:[x,y,z], target:[x,y,z], fov}]
    this.activeCameraId = null;
    // 录制会话（MediaRecorder 实时录制时间轴播放）
    this._recorder = null;
    this._recordStream = null;
    this.rafId = null;
    this.bound = [];            // [target, event, handler] 便于清理
    this.roObserver = null;
    this.helpersVisible = true;
    this.gridVisible = true;
    this.envSphere = null;
    this.envBackdrop = null;
    this._envHint = '';
    this._envLoading = false;
    this._envFitAbort = null;
    this._envFitToken = 0;
    this._envGridAutoOff = false;
    this._envFitStatus = '';
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
      '<button class="ds-btn" id="dsRecordBtn" title="从头播放时间轴并实时录制镜头画面为视频">⏺ 录制视频</button>' +
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
        '<div class="ds-mode-hint" id="dsModeHint">左键拖人偶=水平移动 · 选中后拖 RGB 轴=单轴移动（绿=高度） · 机位琥珀色轴=焦距 · 空白拖拽=旋转视角</div>' +
        '<div class="ds-drag-banner" id="dsDragBanner"></div>' +
        '<div class="ds-hover-tip" id="dsHoverTip"></div>' +
        '<div class="ds-pip" id="dsPip">' +
          '<div class="ds-pip-header"><span>镜头预览</span><span class="rec-dot"></span></div>' +
          '<canvas id="dsPipCanvas"></canvas>' +
        '</div>' +
        '<div class="ds-selection-tip" id="dsSelectionTip"></div>' +
        '<div class="ds-chat-note" id="dsChatNote" style="display:none;"></div>' +
        '<div class="ds-chatbar" id="dsChatBar">' +
          '<select class="ds-chat-model" id="dsChatModel" title="对话模型"></select>' +
          '<input class="ds-chat-input" id="dsChatInput" type="text" maxlength="300" placeholder="对话调整机位，如：把机位移到人偶正面稍高处" />' +
          '<button class="ds-chat-send" id="dsChatSend">发送</button>' +
        '</div>' +
        '<div class="ds-add-pop" id="dsAddPop">' +
          '<div class="ds-add-pop-head"><span>添加人偶</span><button class="ds-puppet-del" id="dsAddPopClose" style="font-size:16px;">✕</button></div>' +
          '<div class="ds-add-pop-body" id="dsAddPopBody"></div>' +
        '</div>' +
      '</div>' +
      '<div class="ds-right" id="dsPropsPanel"></div>' +
    '</div>' +
    '<div class="ds-timeline" id="dsTimeline"></div>' +
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
    var R = window.DirectorStageRendering || null;
    this.rendering = R;
    this.mainPipeline = null;
    this.pipPipeline = null;
    this.studioEnvironment = null;
    this.studioLights = null;
    // 预览与快照固定完整分辨率；优化 SSAO 不得降低 Beauty 清晰度。
    this.pipPreviewQuality = 1;

    var canvas = this.$('dsCanvas');
    this.renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    if (R) R.configureRenderer(this.renderer, { pixelRatio: Math.min(window.devicePixelRatio || 1, 2) });
    else {
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.outputEncoding = THREE.sRGBEncoding;
    }

    // 驱动级规避：部分显卡驱动的 ANGLE 非 D3D11 后端编译 阴影+带贴图材质 的组合即整进程
    // 崩溃且不可恢复；风险环境从第一帧起关闭阴影（PBR 材质/SSAO/环境光全部保留）。
    this._driverShadowDisabled = false;
    if (R && R.detectDriverShaderRisk && R.detectDriverShaderRisk(this.renderer)) {
      this._driverShadowDisabled = true;
      this.renderer.shadowMap.enabled = false;
      console.warn('导演台：当前显卡 ANGLE 后端无法安全编译阴影着色器，已自动关闭实时阴影（PBR 材质与环境光不受影响）。');
    }

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x14161d);

    if (R) {
      this.studioEnvironment = R.createStudioEnvironment(this.renderer, this.scene);
      this.studioLights = R.createThreePointLights(this.scene);
    } else {
      // 无渲染模块时保留旧灯光和原始渲染路径。
      this.scene.add(new THREE.HemisphereLight(0xb8c6dc, 0x1a1d26, 0.95));
      var key = new THREE.DirectionalLight(0xffffff, 0.9);
      key.position.set(4, 7, 5);
      this.scene.add(key);
      var fill = new THREE.DirectionalLight(0x88aaff, 0.30);
      fill.position.set(-5, 3, -4);
      this.scene.add(fill);
      var rim = new THREE.DirectionalLight(0xc5d4ff, 0.6);
      rim.position.set(-3, 5, -7);
      this.scene.add(rim);
      var rim2 = new THREE.DirectionalLight(0xffffff, 0.35);
      rim2.position.set(6, 3, -6);
      this.scene.add(rim2);
    }

    // 地面
    var ground = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 60),
      new THREE.MeshStandardMaterial({ color: 0x191c24, roughness: 0.95 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.005;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this.groundPlane = ground;

    // 站位圆台（快照保留）
    var disc = new THREE.Mesh(
      new THREE.CircleGeometry(2.6, 48),
      new THREE.MeshStandardMaterial({ color: 0x232734, roughness: 0.9 })
    );
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.001;
    disc.receiveShadow = true;
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

    // 选中机位/焦点时显示的世界 XYZ 轴 + 机位焦距轴
    this.axisGizmo = buildWorldAxisGizmo();
    this.scene.add(this.axisGizmo);
    this.fovGizmo = buildFovAxisGizmo();
    this.scene.add(this.fovGizmo);
    this._gizmoHoverAxis = null;

    // PiP renderer（内部分辨率 = 快照分辨率）
    var ratio = getWorkflowRatio();
    var res = SNAPSHOT_RES[ratio];
    this.pipRenderer = new THREE.WebGLRenderer({ canvas: this.$('dsPipCanvas'), antialias: true, preserveDrawingBuffer: true });
    this.pipRenderer.setSize(res[0], res[1], false);
    if (R) R.configureRenderer(this.pipRenderer, { pixelRatio: 1 });
    else this.pipRenderer.outputEncoding = THREE.sRGBEncoding;
    // configureRenderer 会打开阴影；风险后端必须与主渲染器一致关闭，避免编译阴影程序
    if (this._driverShadowDisabled) this.pipRenderer.shadowMap.enabled = false;
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

    function makePipeline(renderer, camera, quality) {
      if (R) return R.createComposer(renderer, self.scene, camera, { pixelRatio: quality });
      return {
        supported: false,
        render: function () { renderer.render(self.scene, camera); },
        setSize: function () {},
        setQuality: function () {},
        dispose: function () {}
      };
    }
    var self = this;
    if (R) R.prepareSceneColors(this.scene);
    var wrap = this.$('dsViewportWrap');
    this.renderer.setSize(wrap.clientWidth || 800, wrap.clientHeight || 600, false);
    this.viewCam.aspect = (wrap.clientWidth || 800) / (wrap.clientHeight || 600);
    this.viewCam.updateProjectionMatrix();
    this.mainPipeline = makePipeline(this.renderer, this.viewCam, this.renderer.getPixelRatio());
    this.pipPipeline = makePipeline(this.pipRenderer, this.virtualCam, this.pipPreviewQuality);
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

  // 从快照恢复机位列表和当前编辑机位。撤销与重开共用。
  // 必须在 restoreTimeline / serializeData 之前调用：序列化会按 this.cameras
  // 丢掉不在列表里的相机轨，并把 virtualCamCfg 写回「当前」激活机位。
  DirectorEditor.prototype.restoreCamerasFromData = function (d) {
    if (d && Array.isArray(d.cameras) && d.cameras.length) {
      this.cameras = d.cameras
        .filter(function (c) { return c && Array.isArray(c.pos) && Array.isArray(c.target); })
        .map(function (c, i) {
          return {
            id: c.id || ('cam' + (i + 1)),
            name: c.name || ('镜头 ' + (i + 1)),
            pos: [num(c.pos[0]), num(c.pos[1]), num(c.pos[2])],
            target: [num(c.target[0]), num(c.target[1]), num(c.target[2])],
            fov: clamp(num(c.fov) || 35, 10, 120)
          };
        });
    } else if (d && d.camera) {
      this.cameras = [{
        id: 'cam1',
        name: '镜头 1',
        pos: (d.camera.pos || [0, 1.5, 4.2]).slice(),
        target: (d.camera.target || [0, 1.05, 0]).slice(),
        fov: d.camera.fov || 35
      }];
    } else {
      this.cameras = [{ id: 'cam1', name: '镜头 1', pos: [0, 1.5, 4.2], target: [0, 1.05, 0], fov: 35 }];
    }
    if (!this.cameras.length) {
      this.cameras = [{ id: 'cam1', name: '镜头 1', pos: [0, 1.5, 4.2], target: [0, 1.05, 0], fov: 35 }];
    }
    this.activeCameraId = (d && d.activeCameraId && this.cameras.some(function (c) { return c.id === d.activeCameraId; }))
      ? d.activeCameraId
      : this.cameras[0].id;
    // 当前编辑机位 = 激活机位（virtualCamCfg 为运行时唯一编辑对象，渲染链路不变）
    var actCam = this.getActiveCamera();
    this.virtualCamCfg.pos.fromArray(actCam.pos);
    this.virtualCamCfg.target.fromArray(actCam.target);
    this.virtualCamCfg.fov = actCam.fov;
    if (this.virtualCam) {
      this.virtualCam.fov = this.virtualCamCfg.fov;
      this.virtualCam.updateProjectionMatrix();
    }
    if (typeof this.updateCamHelper === 'function') this.updateCamHelper();
  };

  DirectorEditor.prototype.restoreFromData = function () {
    var d = this.node.data && this.node.data.directorData;
    var self = this;

    // 机位列表先恢复：时间轴恢复要用 activeCameraId 决定旧数据相机键的落轨机位
    this.restoreCamerasFromData(d);

    if (d && d.puppets) {
      d.puppets.forEach(function (pd) { self.addPuppet(pd, true); });
    }
    if (!this.puppets.length) {
      this.addPuppet({ name: '人偶 1' }, true);
    }

    // 时间轴（关键帧/时长）：机位已就位，旧数据相机键按 activeCameraId 落轨
    this.restoreTimeline(d);
    // 重开时播放头固定为 0。若上次关闭前停在插值帧，静态站位可能不是 0 秒姿态；
    // 先套用 0 秒位形，避免一打开就在 0 秒打点、用末帧姿态覆盖起始关键帧。
    // 只改运行时位形，不 markDirty；无关键帧时 applyTimelineAt 保持当前编辑位形。
    if (this.camRig && typeof this.applyTimelineAt === 'function') {
      this.applyTimelineAt(0);
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
        bodyType: normalizeBodyType(p.bodyType),
        characterId: p.characterId || null, characterName: p.characterName || '',
        x: round2(p.x), z: round2(p.z), rotY: round2(p.rotY),
        rootYOffset: round2(p.rootYOffset), scale: round2(p.scale),
        pose: p.pose || 'custom',
        joints: serializeJoints(p.jointDeg)
      };
    });
    var env = this.node.data.directorData && this.node.data.directorData.environment;
    // 当前编辑机位回写激活机位（编辑全程直接改 virtualCamCfg，落盘时统一同步）
    var actCam = this.getActiveCamera();
    if (actCam) {
      actCam.pos = [round2(this.virtualCamCfg.pos.x), round2(this.virtualCamCfg.pos.y), round2(this.virtualCamCfg.pos.z)];
      actCam.target = [round2(this.virtualCamCfg.target.x), round2(this.virtualCamCfg.target.y), round2(this.virtualCamCfg.target.z)];
      actCam.fov = Math.round(this.virtualCamCfg.fov);
    }
    return {
      version: 2,
      puppets: puppets,
      environment: (env && env.url) ? {
        url: env.url,
        ratio: env.ratio || '21:9',
        yaw: round2(env.yaw || 0),
        horizonY: typeof env.horizonY === 'number' ? round2(env.horizonY) : 1.5,
        sceneScale: typeof env.sceneScale === 'number' ? round2(env.sceneScale) : 1,
        groundY: typeof env.groundY === 'number' ? round2(env.groundY) : 0,
        autoFitDone: !!env.autoFitDone,
        fitVersion: env.fitVersion || 0
      } : null,
      cameras: this.cameras.map(function (c) {
        return {
          id: c.id,
          name: c.name,
          pos: [round2(c.pos[0]), round2(c.pos[1]), round2(c.pos[2])],
          target: [round2(c.target[0]), round2(c.target[1]), round2(c.target[2])],
          fov: Math.round(c.fov)
        };
      }),
      activeCameraId: this.activeCameraId,
      // 冗余旧字段：兼容旧版前端读取 camera（= 激活机位快照）
      camera: {
        pos: [round2(this.virtualCamCfg.pos.x), round2(this.virtualCamCfg.pos.y), round2(this.virtualCamCfg.pos.z)],
        target: [round2(this.virtualCamCfg.target.x), round2(this.virtualCamCfg.target.y), round2(this.virtualCamCfg.target.z)],
        fov: Math.round(this.virtualCamCfg.fov)
      },
      timeline: this.serializeTimeline()
    };
  };

  function round2(v) { return Math.round(v * 100) / 100; }

  function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : 0; }

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
    // 先恢复机位再恢复时间轴。否则 activeCameraId 仍指向撤销前的镜头，
    // 随后 serializeData 会把快照里的姿态写进错误机位；已删除机位的相机轨也会被丢掉。
    this.restoreCamerasFromData(snap);
    this.clearPuppets();
    (snap.puppets || []).forEach(function (pd) { self.addPuppet(pd, true); });
    if (!this.puppets.length) this.addPuppet({ name: '人偶 1' }, true);
    // 撤销同步恢复时间轴数据并重绘
    this.restoreTimeline(snap);
    if (typeof this.renderTimeline === 'function') this.renderTimeline();
    this.selectedPuppetId = null;
    this.selectedJointKey = null;
    if (snap.environment && snap.environment.url) {
      if (!this.node.data.directorData) this.node.data.directorData = {};
      this.node.data.directorData.environment = snap.environment;
      this.applyEnvHorizon();
      this.applyAllPuppetTransforms();
      this.renderEnvSection();
    }
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
    if (rig.materialBundle) rig.materialBundle.dispose();
    rig.materials.forEach(function (m) {
      if (!rig.materialBundle || rig.materialBundle.materials.indexOf(m) === -1) m.dispose();
    });
  }

  DirectorEditor.prototype.setStatus = function (text) {
    this.$('dsStatusText').textContent = text;
  };

  // ---------- 全景环境管理（与 360全景图节点融合） ----------

  function sampleTextureEdgeColor(texture, fallback) {
    try {
      var img = texture.image;
      if (!img || !img.width) return fallback;
      var c = document.createElement('canvas');
      c.width = 2;
      c.height = 1;
      var ctx = c.getContext('2d');
      var midY = Math.max(0, Math.floor((img.height || 1) / 2));
      ctx.drawImage(img, 0, midY, 1, 1, 0, 0, 1, 1);
      ctx.drawImage(img, Math.max(0, img.width - 1), midY, 1, 1, 1, 0, 1, 1);
      var p = ctx.getImageData(0, 0, 2, 1).data;
      var r = Math.round(((p[0] + p[4]) >> 1) * 0.55);
      var g = Math.round(((p[1] + p[5]) >> 1) * 0.55);
      var b = Math.round(((p[2] + p[6]) >> 1) * 0.55);
      return (r << 16) | (g << 8) | b;
    } catch (e) {
      return fallback;
    }
  }

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
      self.ensureEnvFitDefaults(env);
      self.syncEnvToCamera(self.viewCam || self.virtualCam);
      self.applyAllPuppetTransforms();
      // 环境刚贴上且仍是默认远机位时，收到接近拍摄点的平视，否则脚会对不齐地面
      if (Math.abs(self.orbit.radius - 8.5) < 0.3 && Math.abs(self.orbit.phi - 1.02) < 0.08) {
        self.orbit.phi = 1.40;
        self.orbit.radius = 4.5;
        self.orbit.target.set(0, 0.95, 0);
      }
      if (!self._envGridAutoOff) {
        self.gridVisible = false;
        self._envGridAutoOff = true;
        self.syncGridBtn();
      }

      // 未覆盖的球面用边缘色填充，避免露出编辑器背景
      var edgeColor = sampleTextureEdgeColor(texture, 0x0a0c12);
      var backdropGeo = new THREE.SphereGeometry(51, 32, 24);
      backdropGeo.scale(-1, 1, 1);
      var backdrop = new THREE.Mesh(backdropGeo, new THREE.MeshBasicMaterial({ color: edgeColor }));
      backdrop.renderOrder = -1;
      self.scene.add(backdrop);
      self.envBackdrop = backdrop;

      var hints = [];
      // 21:9 垂直约 154° 是推荐画幅的正常表现，不提示；只在水平未满 360° 时提醒
      if (haov < 359) {
        hints.push('当前画幅水平约 ' + Math.round(haov) + '°，缺口已用边缘色填充。完整环绕请使用 2:1 或 21:9 全景图。');
      }
      if (texture.image && texture.image.width && texture.image.height) {
        var imgRatio = texture.image.width / texture.image.height;
        if (Math.abs(imgRatio - w / h) > 0.15) {
          hints.push('图片实际比例与节点设定不一致，贴面可能有轻微拉伸。');
        }
      }
      self._envHint = hints.join(' ');
      self._envLoading = false;
      self.applyGroundVisibility();
      self.renderEnvSection();
      self.setStatus('全景环境已加载');
      self.fitEnvironment({ auto: true });
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
    if (this.envBackdrop) {
      this.scene.remove(this.envBackdrop);
      this.envBackdrop.geometry.dispose();
      this.envBackdrop.material.dispose();
      this.envBackdrop = null;
    }
    this.abortEnvFit();
    this._envHint = '';
    this._envLoading = false;
    this._envFitStatus = '';
    if (this._envGridAutoOff) {
      this.gridVisible = true;
      this._envGridAutoOff = false;
      this.syncGridBtn();
    }
    this.applyGroundVisibility();
    this.applyAllPuppetTransforms();
    this.renderEnvSection();
  };

  // 有环境时隐藏默认地面/站位圆台（露出全景自带地面）
  DirectorEditor.prototype.applyGroundVisibility = function () {
    var hasEnv = !!this.envSphere;
    if (this.groundPlane) this.groundPlane.visible = !hasEnv;
    if (this.groundDisc) this.groundDisc.visible = !hasEnv;
  };

  DirectorEditor.prototype.syncGridBtn = function () {
    var btn = this.$('dsGridBtn');
    if (btn) btn.classList.toggle('active', this.gridVisible);
    if (this.grid) this.grid.visible = this.gridVisible;
  };

  DirectorEditor.prototype.ensureEnvFitDefaults = function (env) {
    if (!env) return;
    if (typeof env.horizonY !== 'number' || isNaN(env.horizonY)) env.horizonY = 1.5;
    if (typeof env.sceneScale !== 'number' || isNaN(env.sceneScale)) env.sceneScale = 1;
    if (typeof env.groundY !== 'number' || isNaN(env.groundY)) env.groundY = 0;
  };

  DirectorEditor.prototype.getEnvHorizonY = function () {
    var env = this.getEnvData();
    if (env && typeof env.horizonY === 'number' && !isNaN(env.horizonY)) return clamp(env.horizonY, 0, 2.5);
    return 1.5;
  };

  DirectorEditor.prototype.getEnvSceneScale = function () {
    var env = this.getEnvData();
    if (env && typeof env.sceneScale === 'number' && !isNaN(env.sceneScale)) return clamp(env.sceneScale, 0.5, 4);
    return 1;
  };

  DirectorEditor.prototype.getEnvGroundY = function () {
    var env = this.getEnvData();
    if (env && typeof env.groundY === 'number' && !isNaN(env.groundY)) return clamp(env.groundY, -2.5, 1.5);
    return 0;
  };

  DirectorEditor.prototype.applyEnvHorizon = function () {
    this.syncEnvToCamera(this.viewCam || this.virtualCam);
  };

  // 全景是拍摄点看到的方向，不是可走进去的房间。球心必须跟着当前渲染相机，
  // 脚底 y=groundY 与「相机下方的地面」才对得上；钉在世界原点绕开后必悬空。
  DirectorEditor.prototype.syncEnvToCamera = function (cam) {
    if (!this.envSphere || !cam) return;
    var env = this.getEnvData();
    var yaw = env ? (env.yaw || 0) : 0;
    var hy = this.getEnvHorizonY();
    var pitch = deg2rad((1.5 - hy) * 28);
    this.envSphere.position.copy(cam.position);
    this.envSphere.rotation.set(pitch, deg2rad(yaw), 0);
    if (this.envBackdrop) {
      this.envBackdrop.position.copy(cam.position);
      this.envBackdrop.rotation.set(pitch, deg2rad(yaw), 0);
    }
  };

  DirectorEditor.prototype.applyEnvFitParams = function (horizonY, sceneScale, groundY, markFitted) {
    var env = this.getEnvData();
    if (!env) return;
    env.horizonY = clamp(horizonY, 0, 2.5);
    env.sceneScale = clamp(sceneScale, 0.5, 4);
    env.groundY = clamp(typeof groundY === 'number' ? groundY : 0, -2.5, 1.5);
    if (markFitted) {
      env.autoFitDone = true;
      env.fitVersion = 3;
    }
    this.applyEnvHorizon();
    this.applyAllPuppetTransforms();
    this.renderEnvSection();
  };

  DirectorEditor.prototype.abortEnvFit = function () {
    this._envFitToken += 1;
    if (this._envFitAbort) {
      try { this._envFitAbort.abort(); } catch (e) { /* noop */ }
      this._envFitAbort = null;
    }
  };

  DirectorEditor.prototype.fitEnvironment = async function (opts) {
    opts = opts || {};
    var auto = !!opts.auto;
    var env = this.getEnvData();
    if (!env || !this.envSphere) return;
    this.ensureEnvFitDefaults(env);
    if (auto && env.autoFitDone && env.fitVersion === 3) return;

    var token = ++this._envFitToken;
    this._envFitStatus = '识别中…';
    this.renderEnvSection();
    this.setStatus('正在智能对齐人偶与场景…');

    var previewUrl = null;
    try {
      var dataUrl = this.renderSnapshotDataUrl();
      var blob = dataUrlToBlob(dataUrl);
      var file = new File([blob], 'ds_env_fit.jpg', { type: 'image/jpeg' });
      if (typeof uploadFile !== 'function') throw new Error('uploadFile missing');
      previewUrl = await uploadFile(file);
    } catch (err) {
      if (token !== this._envFitToken) return;
      this.fallbackEnvFitManual('预览图上传失败，请手动调节地平线与场景比例');
      return;
    }
    if (token !== this._envFitToken) return;
    if (!previewUrl) {
      this.fallbackEnvFitManual('预览图上传失败，请手动调节地平线与场景比例');
      return;
    }

    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    this._envFitAbort = controller;
    try {
      var headers = { 'Content-Type': 'application/json' };
      if (typeof getAuthToken === 'function') headers['Authorization'] = getAuthToken();
      if (typeof getUserId === 'function') headers['X-User-Id'] = getUserId();
      var resp = await fetch('/api/video-workflow/fit-environment', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          image_url: previewUrl,
          horizon_y: this.getEnvHorizonY(),
          scene_scale: this.getEnvSceneScale(),
          ground_y: this.getEnvGroundY()
        }),
        signal: controller ? controller.signal : undefined
      });
      var result = await resp.json();
      if (token !== this._envFitToken) return;
      if (result && result.success) {
        this.applyEnvFitParams(result.horizonY, result.sceneScale, result.groundY, true);
        this._envFitStatus = result.reason ? ('已对齐：' + result.reason) : '已智能对齐';
        this.renderEnvSection();
        this.markDirty();
        this.setStatus(this._envFitStatus);
      } else {
        this.fallbackEnvFitManual((result && result.error) || '未配置视觉模型，请手动调节地平线与场景比例');
      }
    } catch (err) {
      if (token !== this._envFitToken) return;
      if (err && err.name === 'AbortError') return;
      this.fallbackEnvFitManual('视觉模型不可用，请手动调节地平线与场景比例');
    } finally {
      if (this._envFitAbort === controller) this._envFitAbort = null;
    }
  };

  DirectorEditor.prototype.fallbackEnvFitManual = function (msg) {
    var env = this.getEnvData();
    if (env) {
      env.autoFitDone = true;
      env.fitVersion = 3;
    }
    this._envFitStatus = msg || '请手动调节地平线与场景比例';
    this.renderEnvSection();
    this.setStatus(this._envFitStatus);
    if (typeof showToast === 'function') showToast(this._envFitStatus, 'info');
  };

  // 当前保存的环境数据（随 markDirty 序列化）
  DirectorEditor.prototype.getEnvData = function () {
    var d = this.node.data.directorData;
    return (d && d.environment && d.environment.url) ? d.environment : null;
  };

  // 从画布上相连的 360全景节点重新拉取最新结果（全景重新生成后使用）
  DirectorEditor.prototype.refreshEnvironment = function () {
    var conn = (state.connections || []).find(function (c) {
      if (c.to !== this.nodeId) return false;
      if (c.portType === 'environment') return true;
      var fromNode = state.nodes.find(function (n) { return n.id === c.from; });
      return !!(fromNode && fromNode.type === 'panorama');
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
    if (env.url !== url) env.autoFitDone = false;
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
          (this._envHint ? '<div style="padding:0 10px 8px; font-size:10px; color:#f59e0b; line-height:1.5;">' + esc(this._envHint) + '</div>' : '') +
        '</div>' +
        '<div class="ds-slider-row" style="margin-top:8px;">' +
          '<label title="环境旋转">旋转</label>' +
          '<input type="range" id="dsEnvYaw" min="0" max="360" step="1" value="' + Math.round(env.yaw || 0) + '" />' +
          '<input type="number" class="ds-num" id="dsEnvYawNum" min="0" max="360" value="' + Math.round(env.yaw || 0) + '" />' +
        '</div>' +
        '<div class="ds-slider-row">' +
          '<label title="照片地平线高度">地平线</label>' +
          '<input type="range" id="dsEnvHorizon" min="0" max="2.5" step="0.05" value="' + this.getEnvHorizonY() + '" />' +
          '<input type="number" class="ds-num" id="dsEnvHorizonNum" min="0" max="2.5" step="0.05" value="' + this.getEnvHorizonY() + '" />' +
        '</div>' +
        '<div class="ds-slider-row">' +
          '<label title="人偶相对全景的大小">场景比例</label>' +
          '<input type="range" id="dsEnvScale" min="0.5" max="4" step="0.05" value="' + this.getEnvSceneScale() + '" />' +
          '<input type="number" class="ds-num" id="dsEnvScaleNum" min="0.5" max="4" step="0.05" value="' + this.getEnvSceneScale() + '" />' +
        '</div>' +
        '<div class="ds-slider-row">' +
          '<label title="负值让人偶下落到可见地面">贴地</label>' +
          '<input type="range" id="dsEnvGround" min="-2.5" max="1.5" step="0.05" value="' + this.getEnvGroundY() + '" />' +
          '<input type="number" class="ds-num" id="dsEnvGroundNum" min="-2.5" max="1.5" step="0.05" value="' + this.getEnvGroundY() + '" />' +
        '</div>' +
        '<div style="font-size:10px; color:#6b7280; line-height:1.5; padding:2px 0 6px;">旋转=转房间；地平线=抬/压全景地面；场景比例=人偶大小；贴地=人偶升降。无视觉模型时请手动调节。</div>' +
        (this._envFitStatus ? '<div style="font-size:10px; color:#93c5fd; line-height:1.5; padding:0 0 6px;">' + esc(this._envFitStatus) + '</div>' : '') +
        '<div style="display:flex; gap:6px; margin-top:4px;">' +
          '<button class="ds-mini-btn" id="dsEnvFit" style="flex:1; justify-content:center;"' +
            (this._envFitStatus === '识别中…' ? ' disabled' : '') + '>✧ 智能对齐</button>' +
          '<button class="ds-mini-btn" id="dsEnvRefresh" style="flex:1; justify-content:center;">↻ 刷新</button>' +
          '<button class="ds-mini-btn danger" id="dsEnvRemove" style="flex:1; justify-content:center;">✕ 移除</button>' +
        '</div>';
    }
    wrap.innerHTML = html;

    if (!this._envLoading && env) {
      function liveEnv() {
        var e = self.getEnvData();
        if (e) {
          e.autoFitDone = true;
          e.fitVersion = 3;
        }
        return e;
      }
      var yawSlider = this.$('dsEnvYaw');
      var yawNum = this.$('dsEnvYawNum');
      if (yawSlider) {
        this.on(yawSlider, 'input', function () {
          var e = liveEnv();
          if (!e) return;
          e.yaw = parseFloat(yawSlider.value) || 0;
          if (yawNum) yawNum.value = e.yaw;
          self.syncEnvToCamera(self.viewCam);
          self.markDirty(true);
        });
        this.on(yawSlider, 'change', function () { self.markDirty(); });
      }
      if (yawNum) {
        this.on(yawNum, 'change', function () {
          var e = liveEnv();
          if (!e) return;
          e.yaw = clamp(parseFloat(yawNum.value) || 0, 0, 360);
          if (yawSlider) yawSlider.value = e.yaw;
          self.syncEnvToCamera(self.viewCam);
          self.markDirty();
        });
      }
      var hzSlider = this.$('dsEnvHorizon');
      var hzNum = this.$('dsEnvHorizonNum');
      if (hzSlider) {
        this.on(hzSlider, 'input', function () {
          var e = liveEnv();
          if (!e) return;
          e.horizonY = clamp(parseFloat(hzSlider.value) || 0, 0, 2.5);
          if (hzNum) hzNum.value = e.horizonY;
          self.syncEnvToCamera(self.viewCam);
          self.markDirty(true);
        });
        this.on(hzSlider, 'change', function () { self.markDirty(); });
      }
      if (hzNum) {
        this.on(hzNum, 'change', function () {
          var e = liveEnv();
          if (!e) return;
          e.horizonY = clamp(parseFloat(hzNum.value) || 0, 0, 2.5);
          if (hzSlider) hzSlider.value = e.horizonY;
          self.syncEnvToCamera(self.viewCam);
          self.markDirty();
        });
      }
      var scSlider = this.$('dsEnvScale');
      var scNum = this.$('dsEnvScaleNum');
      if (scSlider) {
        this.on(scSlider, 'input', function () {
          var e = liveEnv();
          if (!e) return;
          e.sceneScale = clamp(parseFloat(scSlider.value) || 1, 0.5, 4);
          self.applyAllPuppetTransforms();
          if (scNum) scNum.value = e.sceneScale;
          self.markDirty(true);
        });
        this.on(scSlider, 'change', function () { self.markDirty(); });
      }
      if (scNum) {
        this.on(scNum, 'change', function () {
          var e = liveEnv();
          if (!e) return;
          e.sceneScale = clamp(parseFloat(scNum.value) || 1, 0.5, 4);
          self.applyAllPuppetTransforms();
          if (scSlider) scSlider.value = e.sceneScale;
          self.markDirty();
        });
      }
      var gdSlider = this.$('dsEnvGround');
      var gdNum = this.$('dsEnvGroundNum');
      if (gdSlider) {
        this.on(gdSlider, 'input', function () {
          var e = liveEnv();
          if (!e) return;
          e.groundY = clamp(parseFloat(gdSlider.value) || 0, -2.5, 1.5);
          self.applyAllPuppetTransforms();
          if (gdNum) gdNum.value = e.groundY;
          self.markDirty(true);
        });
        this.on(gdSlider, 'change', function () { self.markDirty(); });
      }
      if (gdNum) {
        this.on(gdNum, 'change', function () {
          var e = liveEnv();
          if (!e) return;
          e.groundY = clamp(parseFloat(gdNum.value) || 0, -2.5, 1.5);
          self.applyAllPuppetTransforms();
          if (gdSlider) gdSlider.value = e.groundY;
          self.markDirty();
        });
      }
      var fitBtn = this.$('dsEnvFit');
      if (fitBtn) this.on(fitBtn, 'click', function () { self.fitEnvironment({ auto: false }); });
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
    var bodyType = normalizeBodyType(pd.bodyType || this._pendingBodyType || 'man');

    var rig = buildPuppetRig(color, bodyType, this.renderer);
    var puppet = {
      id: pd.id || ('p' + Date.now().toString(36) + Math.floor(Math.random() * 1000)),
      name: pd.name || ('人偶 ' + this.puppetSeq),
      color: color,
      bodyType: bodyType,
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
    label.position.y = rig.labelY || 2.02;
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
      // 时间轴补出新的人偶轨道（多轨道 lane 按 this.puppets 渲染）
      if (typeof this.renderTimeline === 'function') this.renderTimeline();
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
    // 同步移除时间轴上的人偶轨道显示（轨道数据在序列化时剔除）
    if (typeof this.renderTimeline === 'function') this.renderTimeline();
    this.markDirty();
    this.setStatus('已删除人偶');
  };

  DirectorEditor.prototype.setPuppetBodyType = function (p, bodyType) {
    if (!p) return;
    bodyType = normalizeBodyType(bodyType);
    if (p.bodyType === bodyType && p.rig && p.rig.bodyType === bodyType) return;
    var selected = this.selectedPuppetId === p.id;
    var jointKey = this.selectedJointKey;
    this.scene.remove(p.rig.root);
    disposeRig(p.rig);
    if (p.label && p.label.userData._texture) p.label.userData._texture.dispose();
    p.bodyType = bodyType;
    p.rig = buildPuppetRig(p.color, bodyType, this.renderer);
    var self = this;
    p.rig.bodyMeshes.forEach(function (m) { m.userData.puppetId = p.id; });
    p.label = makeLabelSprite(p.name);
    p.label.position.y = p.rig.labelY || 2.02;
    p.rig.root.add(p.label);
    this.scene.add(p.rig.root);
    this.applyPuppetTransform(p);
    this.applyJointDeg(p);
    if (selected) {
      this.selectedPuppetId = p.id;
      this.selectedJointKey = jointKey;
    }
    this.updateSelectionVisuals();
  };

  DirectorEditor.prototype.applyPuppetTransform = function (p) {
    p.rig.root.position.set(p.x, this.getEnvGroundY(), p.z);
    p.rig.root.rotation.y = deg2rad(p.rotY);
    p.rig.root.scale.setScalar(p.scale * this.getEnvSceneScale());
    p.rig.hipsY.position.y = ((p.rig.hipH || HIP_H) + p.rootYOffset);
  };

  // 选中人偶后，方向键按当前观察方向在地面平移；Shift 加速。
  DirectorEditor.prototype.nudgeSelectedPuppet = function (key, fast) {
    var p = this.getPuppet(this.selectedPuppetId);
    if (!p) return false;
    var direction = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]
    }[key];
    if (!direction) return false;
    if (this.tl && this.tl.playing && typeof this.pauseTimeline === 'function') this.pauseTimeline();

    var theta = this.orbit && isFinite(this.orbit.theta) ? this.orbit.theta : 0;
    var forwardX = -Math.sin(theta), forwardZ = -Math.cos(theta);
    var rightX = Math.cos(theta), rightZ = -Math.sin(theta);
    var step = fast ? 0.25 : 0.05;
    var moveX = (direction[0] * rightX + direction[1] * forwardX) * step;
    var moveZ = (direction[0] * rightZ + direction[1] * forwardZ) * step;
    p.x = clamp(p.x + moveX, -GROUND_LIMIT, GROUND_LIMIT);
    p.z = clamp(p.z + moveZ, -GROUND_LIMIT, GROUND_LIMIT);

    this.applyPuppetTransform(p);
    this.updateAxisGizmo();
    this.syncPuppetAxisSliders(p);
    this.markDirty();
    this.setStatus('已平移「' + p.name + '」' + (fast ? '（加速）' : ''));
    return true;
  };

  DirectorEditor.prototype.getPuppetWorldScale = function (p) {
    var s = (p && p.scale ? p.scale : 1) * this.getEnvSceneScale();
    return s > 1e-6 ? s : 1;
  };

  DirectorEditor.prototype.getPuppetGizmoOrigin = function (p) {
    // hipsY 在已缩放的 root 下，世界高度 = 地面 + (髋高+离地) * scale
    var s = this.getPuppetWorldScale(p);
    var localH = ((p.rig && p.rig.hipH) ? p.rig.hipH : HIP_H) + (p.rootYOffset || 0);
    return new THREE.Vector3(p.x, this.getEnvGroundY() + localH * s, p.z);
  };

  DirectorEditor.prototype.applyAllPuppetTransforms = function () {
    var self = this;
    this.puppets.forEach(function (p) { self.applyPuppetTransform(p); });
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

    // 相机 / 对焦中心选中高亮：机身红→橙、视锥线加亮、地面显示橙色选中环、对焦十字与视线虚线变青；显示轴向把手
    var camSel = this.selectedCamTarget === 'camera';
    var focusSel = this.selectedCamTarget === 'focus';
    this.updateAxisGizmo();
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
      tip.textContent = sel.name + jointLabel + ' — 拖 RGB 轴单轴移动（绿=高度）';
      tip.classList.add('show');
    } else if (camSel) {
      tip.textContent = '🎥 机位 — 拖 RGB 轴单轴移动（绿=高度），琥珀色轴调焦距';
      tip.classList.add('show');
    } else if (focusSel) {
      tip.textContent = '🎯 对焦中心 — 拖 RGB 轴单轴移动，绿轴调节高度';
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
      var typeLabel = getBodyType(p.bodyType).label;
      return '<div class="ds-puppet-item' + (p.id === self.selectedPuppetId ? ' selected' : '') + '" data-pid="' + esc(p.id) + '">' +
        '<span class="ds-puppet-color" style="background:' + esc(p.color) + '"></span>' +
        '<span class="ds-puppet-name" title="' + esc(p.name) + '">' + esc(p.name) + '</span>' +
        '<span class="ds-puppet-type">' + esc(typeLabel) + '</span>' +
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
      '<div class="ds-prop-label"><span>体型</span></div>' +
      '<div class="ds-bodytype-grid compact">' +
        BODY_TYPE_ORDER.map(function (k) {
          var active = normalizeBodyType(p.bodyType) === k ? ' active' : '';
          return '<button type="button" class="ds-bodytype-item' + active + '" data-bodytype="' + k + '">' + esc(BODY_TYPES[k].label) + '</button>';
        }).join('') +
      '</div>' +
    '</div>';
    html += '<div class="ds-prop-group">' +
      sliderRow('朝向', 'rotY', -180, 180, 1, fmt(p.rotY), 'dsPupRotY') +
      sliderRow('身高', 'scale', 0.75, 1.25, 0.01, fmt(p.scale), 'dsPupScale') +
      sliderRow('离地高度', 'yOff', PUPPET_Y_MIN, PUPPET_Y_MAX, 0.01, fmt(p.rootYOffset), 'dsPupYOff') +
    '</div>';
    html += '<div class="ds-prop-group">' +
      '<div class="ds-prop-label"><span>位置 XYZ</span><span class="ds-prop-value" id="dsPupPos">' + fmt(p.x) + ', ' + fmt(p.rootYOffset) + ', ' + fmt(p.z) + '</span></div>' +
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
      p.label.position.y = p.rig.labelY || 2.02;
      p.rig.root.add(p.label);
      self.renderPuppetList();
      self.updateSelectionVisuals();
      self.markDirty();
    });

    // 朝向 / 身高 / 离地
    panel.querySelectorAll('.ds-bodytype-item').forEach(function (btn) {
      self.on(btn, 'click', function () {
        self.setPuppetBodyType(p, btn.dataset.bodytype);
        self.renderPuppetList();
        self.renderPropsPanel();
        self.markDirty();
        self.setStatus('体型：' + getBodyType(p.bodyType).label);
      });
    });

    bindTransformSlider.call(this, 'rotY', function (v) { p.rotY = v; self.applyPuppetTransform(p); }, -180, 180);
    bindTransformSlider.call(this, 'scale', function (v) { p.scale = v; self.applyPuppetTransform(p); }, 0.75, 1.25);
    bindTransformSlider.call(this, 'yOff', function (v) {
      p.rootYOffset = v;
      self.applyPuppetTransform(p);
      self.updateAxisGizmo();
    }, PUPPET_Y_MIN, PUPPET_Y_MAX);

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

  DirectorEditor.prototype.buildCamerasGroupHtml = function () {
    var self = this;
    var rows = this.cameras.map(function (c) {
      var active = c.id === self.activeCameraId;
      return '<div class="ds-cam-item' + (active ? ' active' : '') + '" data-cam-id="' + esc(c.id) + '" title="点击切换为当前编辑机位">' +
        '<span class="ds-cam-name">' + (active ? '● ' : '') + esc(c.name) + '</span>' +
        '<button type="button" class="ds-tl-lane-btn" data-cam-act="update" title="把当前相机配置存入该机位">更新</button>' +
        '<button type="button" class="ds-tl-lane-btn" data-cam-act="del" title="删除该机位">✕</button>' +
      '</div>';
    }).join('');
    return '<div class="ds-prop-group"><div class="ds-prop-label"><span>机位（多个镜头）</span>' +
      '<button type="button" class="ds-mini-btn" id="dsAddCamBtn" title="以当前相机配置新建机位">＋添加</button></div>' +
      '<div class="ds-cam-list">' + rows + '</div></div>';
  };

  DirectorEditor.prototype.buildCameraPropsHtml = function () {
    var c = this.virtualCamCfg;
    var html = '';
    html += '<div class="ds-section-head"><span>镜头设置</span>' +
      '<button class="ds-mini-btn" id="dsSwitchPuppetProps">人偶属性</button></div>';
    html += this.buildCamerasGroupHtml();
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

    // 机位列表：整行点击=切换为当前编辑机位；「更新」= 当前相机存入该机位；✕=删除
    panel.querySelectorAll('.ds-cam-item').forEach(function (item) {
      self.on(item, 'click', function (e) {
        var act = e.target && e.target.dataset ? e.target.dataset.camAct : null;
        var id = item.dataset.camId;
        if (act === 'update') self.updateCameraSlot(id);
        else if (act === 'del') self.removeCameraSlot(id);
        else self.applyCameraSlot(id);
      });
    });
    this.on(panel.querySelector('#dsAddCamBtn'), 'click', function () {
      self.addCameraSlot();
    });

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

  // ---------- 对话改机位（/api/video-workflow/camera-chat） ----------

  DirectorEditor.prototype._showChatNote = function (text, kind) {
    var note = this.$('dsChatNote');
    if (!note) return;
    note.style.display = 'block';
    note.textContent = text;
    note.className = 'ds-chat-note is-' + (kind || 'info');
    clearTimeout(this._chatNoteTimer);
    if (kind !== 'error') {
      this._chatNoteTimer = setTimeout(function () { note.style.display = 'none'; }, 6000);
    }
  };

  DirectorEditor.prototype.loadChatModels = function () {
    var self = this;
    var sel = this.$('dsChatModel');
    if (!sel) return;
    var headers = {};
    if (typeof getAuthToken === 'function') headers['Authorization'] = getAuthToken();
    if (typeof getUserId === 'function') headers['X-User-Id'] = getUserId();
    Promise.all([
      fetch('/api/models?scene=llm.script_split', { headers: headers })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .catch(function () { return {}; }),
      fetch('/api/vendors', { headers: headers })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .catch(function () { return {}; }),
    ]).then(function (results) {
      var models = (results[0] && results[0].success && results[0].models) || [];
      var vendors = (results[1] && results[1].success && results[1].vendors) || [];
      var vendorNames = {};
      vendors.forEach(function (v) { vendorNames[v.id] = v.vendor_name || v.name || ('供应商' + v.id); });
      self._chatModels = models.map(function (m) {
        return {
          model: m.name || m.model || '',
          model_id: m.model_id || m.id,
          vendor_id: m.vendor_id,
          vendor_name: vendorNames[m.vendor_id] || '',
        };
      }).filter(function (m) { return m.model && m.model_id != null; });
      sel.innerHTML = '';
      self._chatModels.forEach(function (m, i) {
        var opt = document.createElement('option');
        opt.value = String(i);
        opt.textContent = m.model + (m.vendor_name ? ' · ' + m.vendor_name : '');
        sel.appendChild(opt);
      });
      // 恢复上次选择
      var saved = null;
      try { saved = JSON.parse(localStorage.getItem('ds_chat_model') || 'null'); } catch (e) { saved = null; }
      if (saved) {
        for (var i = 0; i < self._chatModels.length; i++) {
          if (self._chatModels[i].model_id === saved.model_id && self._chatModels[i].vendor_id === saved.vendor_id) {
            sel.value = String(i);
            break;
          }
        }
      }
    });
  };

  DirectorEditor.prototype.sendCameraChat = function () {
    var self = this;
    if (this._chatBusy) return;
    var input = this.$('dsChatInput');
    var send = this.$('dsChatSend');
    if (!input || !send) return;
    var message = (input.value || '').trim();
    if (!message) return;
    var sel = this.$('dsChatModel');
    var model = (this._chatModels || [])[parseInt(sel && sel.value, 10)];
    if (!model) {
      this.setStatus('请先选择对话模型');
      this._showChatNote('请先选择对话模型', 'error');
      return;
    }

    var cfg = this.virtualCamCfg;
    var entities = this.puppets.map(function (p) {
      return { name: p.name, kind: 'actor', x: p.x, z: p.z, facing: p.rotY };
    });

    this._chatBusy = true;
    send.disabled = true;
    input.disabled = true;
    send.textContent = '思考中…';
    this._showChatNote('正在根据指令计算新机位…', 'info');

    var headers = { 'Content-Type': 'application/json' };
    if (typeof getAuthToken === 'function') headers['Authorization'] = getAuthToken();
    if (typeof getUserId === 'function') headers['X-User-Id'] = getUserId();

    fetch('/api/video-workflow/camera-chat', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        message: message,
        current_camera: {
          eye: [cfg.pos.x, cfg.pos.y, cfg.pos.z],
          target: [cfg.target.x, cfg.target.y, cfg.target.z],
          fov: cfg.fov,
        },
        entities: entities,
        model: model.model,
        model_id: model.model_id,
        vendor_id: model.vendor_id,
      }),
    }).then(function (resp) { return resp.json().catch(function () { return {}; }); })
      .then(function (data) {
        // 服务端返回扁平 {success, eye, target, fov, reason}；兼容嵌套 camera:{} 形态
        var cam = data && (data.camera || data);
        if (data && data.success && cam && cam.eye && cam.target) {
          var pos = Array.isArray(cam.eye) ? cam.eye : [cam.eye.x, cam.eye.y, cam.eye.z];
          var tgt = Array.isArray(cam.target) ? cam.target : [cam.target.x, cam.target.y, cam.target.z];
          // 与滑杆同范围约束，保持 UI 一致
          cfg.pos.set(clamp(num(pos[0]), -30, 30), clamp(num(pos[1]), 0.2, 8), clamp(num(pos[2]), -30, 30));
          cfg.target.set(clamp(num(tgt[0]), -9.5, 9.5), clamp(num(tgt[1]), 0, 4), clamp(num(tgt[2]), -9.5, 9.5));
          cfg.fov = clamp(num(cam.fov), 15, 90);
          self.updateCamHelper();
          self.renderPropsPanel();
          self.markDirty();
          try { localStorage.setItem('ds_chat_model', JSON.stringify(model)); } catch (e) { /* ignore */ }
          self._showChatNote('✓ ' + (data.reason || '机位已更新'), 'ok');
          input.value = '';
          self.setStatus('机位：对话调整');
        } else {
          self._showChatNote((data && data.error) || '机位调整失败，请重试', 'error');
        }
      })
      .catch(function (err) {
        self._showChatNote((err && err.message) || '机位调整失败，请重试', 'error');
      })
      .then(function () {
        self._chatBusy = false;
        send.disabled = false;
        input.disabled = false;
        send.textContent = '发送';
      });
  };

  // ---------- 多机位（机位列表） ----------

  DirectorEditor.prototype.getActiveCamera = function () {
    for (var i = 0; i < this.cameras.length; i++) {
      if (this.cameras[i].id === this.activeCameraId) return this.cameras[i];
    }
    return this.cameras[0] || null;
  };

  // 切换激活机位：把机位配置载入当前编辑相机（PiP/图标/gizmo 立即跟随）
  DirectorEditor.prototype.applyCameraSlot = function (id) {
    var cam = null;
    for (var i = 0; i < this.cameras.length; i++) {
      if (this.cameras[i].id === id) { cam = this.cameras[i]; break; }
    }
    if (!cam) return;
    this.activeCameraId = cam.id;
    this.virtualCamCfg.pos.fromArray(cam.pos);
    this.virtualCamCfg.target.fromArray(cam.target);
    this.virtualCamCfg.fov = cam.fov;
    if (typeof this.updateCamHelper === 'function') this.updateCamHelper();
    if (typeof this.syncCameraPanelSliders === 'function') this.syncCameraPanelSliders();
    this.renderPropsPanel();
    this.markDirty();
    this.setStatus('已切换到「' + cam.name + '」');
  };

  // 把当前编辑相机配置存进指定机位
  DirectorEditor.prototype.updateCameraSlot = function (id) {
    var cam = null;
    for (var i = 0; i < this.cameras.length; i++) {
      if (this.cameras[i].id === id) { cam = this.cameras[i]; break; }
    }
    if (!cam) return;
    cam.pos = [round2(this.virtualCamCfg.pos.x), round2(this.virtualCamCfg.pos.y), round2(this.virtualCamCfg.pos.z)];
    cam.target = [round2(this.virtualCamCfg.target.x), round2(this.virtualCamCfg.target.y), round2(this.virtualCamCfg.target.z)];
    cam.fov = Math.round(this.virtualCamCfg.fov);
    this.markDirty();
    this.setStatus('已把当前相机存入「' + cam.name + '」');
  };

  DirectorEditor.prototype.addCameraSlot = function () {
    var id = 'cam' + Date.now().toString(36) + Math.floor(Math.random() * 1000);
    var cam = {
      id: id,
      name: '镜头 ' + (this.cameras.length + 1),
      pos: [round2(this.virtualCamCfg.pos.x), round2(this.virtualCamCfg.pos.y), round2(this.virtualCamCfg.pos.z)],
      target: [round2(this.virtualCamCfg.target.x), round2(this.virtualCamCfg.target.y), round2(this.virtualCamCfg.target.z)],
      fov: Math.round(this.virtualCamCfg.fov)
    };
    this.cameras.push(cam);
    this.activeCameraId = id;
    this.renderPropsPanel();
    // 时间轴新增该机位的相机轨 lane
    if (typeof this.renderTimeline === 'function') this.renderTimeline();
    this.markDirty();
    this.setStatus('已添加「' + cam.name + '」（复制当前相机配置）');
  };

  DirectorEditor.prototype.removeCameraSlot = function (id) {
    if (this.cameras.length <= 1) {
      this.setStatus('至少保留一个机位');
      return;
    }
    var idx = -1;
    for (var i = 0; i < this.cameras.length; i++) {
      if (this.cameras[i].id === id) { idx = i; break; }
    }
    if (idx < 0) return;
    var removed = this.cameras.splice(idx, 1)[0];
    // 删除的是激活机位：切到剩余第一个并载入
    if (this.activeCameraId === id) {
      var next = this.cameras[0];
      this.activeCameraId = next.id;
      this.virtualCamCfg.pos.fromArray(next.pos);
      this.virtualCamCfg.target.fromArray(next.target);
      this.virtualCamCfg.fov = next.fov;
      if (typeof this.updateCamHelper === 'function') this.updateCamHelper();
      if (typeof this.syncCameraPanelSliders === 'function') this.syncCameraPanelSliders();
    }
    this.renderPropsPanel();
    // 时间轴移除该机位的相机轨 lane
    if (typeof this.renderTimeline === 'function') this.renderTimeline();
    this.markDirty();
    this.setStatus('已删除「' + removed.name + '」');
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
    var headY = (p.rig && p.rig.labelY) ? p.rig.labelY * 0.78 : 1.58;
    pos.y = headY;
    var target = new THREE.Vector3(p.x, 0, p.z)
      .add(back.clone().multiplyScalar(-2.5));
    target.y = headY * 0.85;
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

    this.updateAxisGizmo();
  };

  DirectorEditor.prototype.updateAxisGizmo = function () {
    if (!this.axisGizmo) return;
    var camSel = this.selectedCamTarget === 'camera';
    var focusSel = this.selectedCamTarget === 'focus';
    var puppet = this.getPuppet(this.selectedPuppetId);
    var helpersOn = !this.camRig || this.camRig.visible;
    var show = (camSel || focusSel || !!puppet) && helpersOn;
    this.axisGizmo.visible = !!show;
    if (this.fovGizmo) this.fovGizmo.visible = !!(show && camSel);
    if (!show) return;
    var origin;
    if (puppet) origin = this.getPuppetGizmoOrigin(puppet);
    else if (camSel) origin = this.virtualCamCfg.pos;
    else origin = this.virtualCamCfg.target;
    this.axisGizmo.position.copy(origin);
    var dist = this.viewCam ? this.viewCam.position.distanceTo(origin) : 6;
    var s = clamp(dist * 0.11, 0.5, 1.7);
    this.axisGizmo.scale.setScalar(s);
    if (this.fovGizmo && camSel) {
      this.fovGizmo.position.copy(this.virtualCamCfg.pos);
      this.fovGizmo.scale.setScalar(s);
      var look = new THREE.Vector3().subVectors(this.virtualCamCfg.target, this.virtualCamCfg.pos);
      if (look.lengthSq() < 1e-8) look.set(0, 0, -1);
      look.normalize();
      this.fovGizmo.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), look);
    }
  };

  DirectorEditor.prototype.highlightGizmoAxis = function (axis) {
    function paint(root) {
      if (!root) return;
      root.traverse(function (o) {
        if (!o.userData || !o.userData.gizmoAxis) return;
        if (o.userData._pickOnly || !o.material || !o.material.color) return;
        if (typeof o.userData.baseColor !== 'number') return;
        var hot = !!(axis && o.userData.gizmoAxis === axis);
        o.material.color.setHex(hot ? 0xffffff : o.userData.baseColor);
      });
    }
    paint(this.axisGizmo);
    paint(this.fovGizmo);
    this._gizmoHoverAxis = axis || null;
  };

  DirectorEditor.prototype.gizmoAxisDir = function (axis) {
    if (axis === 'x') return new THREE.Vector3(1, 0, 0);
    if (axis === 'y') return new THREE.Vector3(0, 1, 0);
    if (axis === 'z') return new THREE.Vector3(0, 0, 1);
    var look = new THREE.Vector3().subVectors(this.virtualCamCfg.target, this.virtualCamCfg.pos);
    if (look.lengthSq() < 1e-8) look.set(0, 0, -1);
    return look.normalize();
  };

  DirectorEditor.prototype.intersectAxisPlane = function (e, origin, axisDir) {
    this.raycaster.setFromCamera(this.ndcAt(e), this.viewCam);
    var viewDir = this.raycaster.ray.direction;
    var n = new THREE.Vector3().crossVectors(axisDir, viewDir);
    if (n.lengthSq() < 1e-10) {
      n.crossVectors(axisDir, new THREE.Vector3(0, 1, 0));
      if (n.lengthSq() < 1e-10) n.set(1, 0, 0);
    }
    n.cross(axisDir);
    if (n.lengthSq() < 1e-10) return null;
    n.normalize();
    var plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, origin);
    var hit = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(plane, hit) ? hit : null;
  };

  DirectorEditor.prototype.applyGizmoDrag = function (d, e) {
    var hit = this.intersectAxisPlane(e, d.origin, d.dir);
    if (!hit) return;
    var delta = hit.dot(d.dir) - d.startAlong;
    if (d.kind === 'puppet' && d.puppet) {
      var pup = d.puppet;
      if (d.axis === 'x') pup.x = clamp(d.startPos.x + delta, -GROUND_LIMIT, GROUND_LIMIT);
      else if (d.axis === 'z') pup.z = clamp(d.startPos.z + delta, -GROUND_LIMIT, GROUND_LIMIT);
      else if (d.axis === 'y') {
        // 鼠标 delta 是世界米；rootYOffset 是未缩放的局部高度，需除以世界缩放
        var ws = d.worldScale || this.getPuppetWorldScale(pup);
        pup.rootYOffset = clamp(d.startRootY + delta / ws, PUPPET_Y_MIN, PUPPET_Y_MAX);
      }
      this.applyPuppetTransform(pup);
      this.updateAxisGizmo();
      this.syncPuppetAxisSliders(pup);
      return;
    }
    if (d.axis === 'fov') {
      this.virtualCamCfg.fov = clamp(d.startFov - delta * 22, 15, 90);
    } else {
      var p = d.startPos.clone().addScaledVector(d.dir, delta);
      p.x = clamp(p.x, -GROUND_LIMIT, GROUND_LIMIT);
      p.z = clamp(p.z, -GROUND_LIMIT, GROUND_LIMIT);
      if (d.kind === 'camera') {
        p.y = clamp(p.y, 0.2, 8);
        this.virtualCamCfg.pos.copy(p);
      } else {
        p.y = clamp(p.y, 0, 6);
        this.virtualCamCfg.target.copy(p);
      }
    }
    this.updateCamHelper();
    this.syncCameraPanelSliders();
  };

  DirectorEditor.prototype.syncPuppetAxisSliders = function (p) {
    var panel = this.$('dsPropsPanel');
    if (!panel || this._panelMode !== 'puppet') return;
    var posEl = this.$('dsPupPos');
    if (posEl) posEl.textContent = fmt(p.x) + ', ' + fmt(p.rootYOffset) + ', ' + fmt(p.z);
    this.syncSlider(panel, 'yOff', p.rootYOffset);
    this.syncNum(panel, 'yOff', fmt(p.rootYOffset));
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

  function resolveGizmoAxis(obj) {
    var o = obj;
    while (o) {
      if (o.userData && o.userData.gizmoAxis) return o.userData.gizmoAxis;
      o = o.parent;
    }
    return null;
  }

  // 射线拾取：轴向把手 → 关节球 → 人偶 body → 焦点 / 相机
  DirectorEditor.prototype.pickAt = function (e) {
    this.raycaster.setFromCamera(this.ndcAt(e), this.viewCam);
    // 0. 选中机位/焦点时优先拾取轴向把手
    var gizmos = [];
    if (this.axisGizmo && this.axisGizmo.visible) gizmos.push(this.axisGizmo);
    if (this.fovGizmo && this.fovGizmo.visible) gizmos.push(this.fovGizmo);
    if (gizmos.length) {
      var gz = this.raycaster.intersectObjects(gizmos, true);
      if (gz.length) {
        var axis = resolveGizmoAxis(gz[0].object);
        if (axis) {
          var kind = this.selectedCamTarget || (this.selectedPuppetId ? 'puppet' : null);
          return { type: 'gizmo', axis: axis, kind: kind };
        }
      }
    }
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
        text = '🧍 ' + hit.puppet.name + ' — 拖身体水平移动，或拖 RGB 轴单轴移动';
      } else if (hit.type === 'camera') {
        cursor = 'move';
        text = '🎥 虚拟相机 — 拖机身水平移动，或拖 RGB 轴单轴移动';
      } else if (hit.type === 'focus') {
        cursor = 'move';
        text = '🎯 对焦中心 — 拖绿轴调节高度，红/蓝轴水平移动';
      } else if (hit.type === 'gizmo') {
        cursor = 'ns-resize';
        var axisName = { x: 'X 轴', y: 'Y 轴（高度）', z: 'Z 轴', fov: '焦距 / FOV' }[hit.axis] || hit.axis;
        text = '↕ ' + axisName + ' — 按住只沿此轴拖动';
        this.highlightGizmoAxis(hit.axis);
      }
    }
    if (!hit || hit.type !== 'gizmo') this.highlightGizmoAxis(null);
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
      camera: '🎥 移动机位 — 水平拖动；高度请拖绿色 Y 轴',
      focus: '🎯 移动对焦中心 — 水平拖动；高度请拖绿色 Y 轴',
      gizmo: '↕ 单轴拖动' + (extra ? '：' + extra : '')
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
          var gp = groundPoint(e, self.getEnvGroundY());
          if (gp) {
            self.dragging = {
              mode: 'puppet', puppet: hit.puppet,
              offX: gp.x - hit.puppet.x, offZ: gp.z - hit.puppet.z
            };
            self.showDragBanner('puppet', hit.puppet.name);
          }
          return;
        }
        if (hit.type === 'gizmo') {
          var kind = hit.kind || self.selectedCamTarget || (self.selectedPuppetId ? 'puppet' : 'camera');
          self.highlightGizmoAxis(hit.axis);
          var origin, dir, ah;
          if (kind === 'puppet') {
            var pup = self.getPuppet(self.selectedPuppetId);
            if (!pup || hit.axis === 'fov') return;
            origin = self.getPuppetGizmoOrigin(pup);
            dir = self.gizmoAxisDir(hit.axis);
            ah = self.intersectAxisPlane(e, origin, dir);
            self.dragging = {
              mode: 'gizmo',
              axis: hit.axis,
              kind: 'puppet',
              puppet: pup,
              origin: origin,
              dir: dir,
              startAlong: ah ? ah.dot(dir) : 0,
              startPos: { x: pup.x, z: pup.z },
              startRootY: pup.rootYOffset || 0,
              worldScale: self.getPuppetWorldScale(pup)
            };
          } else {
            if (kind !== 'camera' && kind !== 'focus') kind = 'camera';
            self.selectCamera(kind);
            origin = (kind === 'camera' ? self.virtualCamCfg.pos : self.virtualCamCfg.target).clone();
            dir = self.gizmoAxisDir(hit.axis);
            ah = self.intersectAxisPlane(e, origin, dir);
            self.dragging = {
              mode: 'gizmo',
              axis: hit.axis,
              kind: kind,
              origin: origin,
              dir: dir,
              startAlong: ah ? ah.dot(dir) : 0,
              startPos: origin.clone(),
              startFov: self.virtualCamCfg.fov
            };
          }
          var axisLabel = { x: 'X', y: 'Y 高度', z: 'Z', fov: '焦距' }[hit.axis] || hit.axis;
          self.showDragBanner('gizmo', axisLabel);
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
        var gp = groundPoint(e, self.getEnvGroundY());
        if (gp) {
          d.puppet.x = clamp(gp.x - d.offX, -GROUND_LIMIT, GROUND_LIMIT);
          d.puppet.z = clamp(gp.z - d.offZ, -GROUND_LIMIT, GROUND_LIMIT);
          self.applyPuppetTransform(d.puppet);
          self.updateAxisGizmo();
          self.syncPuppetAxisSliders(d.puppet);
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
      } else if (d.mode === 'gizmo') {
        self.applyGizmoDrag(d, e);
      }
    });

    this.on(canvas, 'pointerup', function (e) {
      var d = self.dragging;
      self.dragging = null;
      self.hideDragBanner();
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
      if (!d) return;
      if ((d.mode === 'puppet' || d.mode === 'camera' || d.mode === 'focus' || d.mode === 'gizmo')) {
        self.highlightGizmoAxis(null);
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
      self.syncGridBtn();
    });
    this.on(this.$('dsResetViewBtn'), 'click', function () {
      // 必须原地修改 orbit 对象：startLoop 渲染循环缓存了 this.orbit 引用，
      // 整体替换对象会导致循环继续渲染旧视角（画面定死、鼠标控制失效）
      self.orbit.theta = 0.55;
      self.orbit.phi = 1.02;
      self.orbit.radius = 8.5;
      self.orbit.target.set(0, 1.0, 0);
    });

    // 尺寸自适应
    this.roObserver = new ResizeObserver(function () {
      var w = wrap.clientWidth, h = wrap.clientHeight;
      if (w > 0 && h > 0) {
        self.renderer.setSize(w, h, false);
        self.viewCam.aspect = w / h;
        self.viewCam.updateProjectionMatrix();
        if (self.mainPipeline) self.mainPipeline.setSize(w, h);
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

    function bodyTypeGridHtml(selected) {
      return '<div class="ds-bodytype-grid">' +
        BODY_TYPE_ORDER.map(function (k) {
          var active = selected === k ? ' active' : '';
          return '<button type="button" class="ds-bodytype-item' + active + '" data-pick-type="' + k + '">' + esc(BODY_TYPES[k].label) + '</button>';
        }).join('') +
      '</div>' +
      '<div class="ds-add-type-hint">先选体型，再点下方添加</div>';
    }

    this.on(this.$('dsAddPuppetBtn'), 'click', async function () {
      body.innerHTML = '<div style="color:#6b7280; font-size:12px; padding:8px 0;">加载中…</div>';
      pop.classList.add('show');
      if (!self._pendingBodyType) self._pendingBodyType = 'man';
      var items = [
        bodyTypeGridHtml(self._pendingBodyType),
        '<div class="ds-char-item" data-blank="1"><span class="ds-char-placeholder">🧍</span><span>空白人偶</span></div>'
      ];
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
              items.push('<div class="ds-char-item" data-cid="' + esc(String(c.id)) + '" data-cname="' + esc(c.name || '') +
                '" data-cage="' + esc(c.age || '') + '" data-cidentity="' + esc(c.identity || '') + '">' +
                thumb + '<span>' + esc(c.name || ('角色 ' + c.id)) + '</span></div>');
            });
          }
        } else {
          items.push('<div style="color:#6b7280; font-size:11px; padding:4px 0;">未选择世界，仅可添加空白人偶</div>');
        }
      } catch (err) {
        items.push('<div style="color:#f87171; font-size:11px; padding:4px 0;">角色列表加载失败</div>');
      }
      body.innerHTML = items.join('');

      body.querySelectorAll('[data-pick-type]').forEach(function (btn) {
        self.on(btn, 'click', function (e) {
          e.stopPropagation();
          self._pendingBodyType = btn.dataset.pickType;
          body.querySelectorAll('[data-pick-type]').forEach(function (b) {
            b.classList.toggle('active', b.dataset.pickType === self._pendingBodyType);
          });
        });
      });

      body.querySelectorAll('.ds-char-item').forEach(function (item) {
        self.on(item, 'click', function () {
          var p;
          var bodyType = self._pendingBodyType || 'man';
          if (item.dataset.blank) {
            var typeLabel = getBodyType(bodyType).label;
            var sameCount = self.puppets.filter(function (x) { return x.bodyType === bodyType; }).length;
            p = self.addPuppet({
              name: typeLabel + ' ' + (sameCount + 1),
              bodyType: bodyType
            });
          } else {
            bodyType = inferBodyType(item.dataset.cname, item.dataset.cage, item.dataset.cidentity) || bodyType;
            p = self.addPuppet({
              name: item.dataset.cname || '角色人偶',
              characterId: parseInt(item.dataset.cid, 10) || null,
              characterName: item.dataset.cname || '',
              bodyType: bodyType
            });
          }
          closePop();
          self.setStatus('已添加「' + p.name + '」（' + getBodyType(p.bodyType).label + '）');
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
    try {
      // 预览和快照都使用完整采样率，避免 SSAO 后处理造成画面模糊。
      if (this.pipPipeline.supported) this.pipPipeline.setQuality(1);
      this.pipPipeline.render();
      return this.pipRenderer.domElement.toDataURL('image/jpeg', 0.92);
    } finally {
      if (this.pipPipeline.supported) this.pipPipeline.setQuality(this.pipPreviewQuality);
      this.setHelpersVisible(true);
    }
  };

  DirectorEditor.prototype.setHelpersVisible = function (visible) {
    this.grid.visible = visible && this.gridVisible;
    this.camRig.visible = visible;
    if (this.focusMarker) this.focusMarker.visible = visible;
    if (this.sightLine) this.sightLine.visible = visible;
    if (this.axisGizmo) this.axisGizmo.visible = visible && !!(this.selectedCamTarget === 'camera' || this.selectedCamTarget === 'focus' || this.selectedPuppetId);
    if (this.fovGizmo) this.fovGizmo.visible = visible && this.selectedCamTarget === 'camera';
    this.updateCamSelectRing();
    if (visible) this.updateAxisGizmo();
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

  // ---------- 录制视频（MediaRecorder 实时录制时间轴播放） ----------

  DirectorEditor.prototype._syncRecordBtn = function () {
    var btn = this.$('dsRecordBtn');
    if (!btn) return;
    var rec = !!this._recorder;
    btn.textContent = rec ? '⏹ 结束录制' : '⏺ 录制视频';
    btn.classList.toggle('recording', rec);
  };

  // 开始录制：时间轴回 0 从头播放，镜头画面（PiP canvas）实时编码；
  // 播放结束自动停止，也可点「⏹ 结束录制」提前结束（保留已录部分）
  DirectorEditor.prototype.startRecording = function () {
    if (this._recorder) return;
    if (!this.tl || !this.tl.tracks.length || !this.tl.tracks.some(function (tr) { return tr.keys.length; })) {
      this.setStatus('请先记录关键帧，再录制视频');
      return;
    }
    if (typeof MediaRecorder === 'undefined' || !this.pipRenderer || !this.pipRenderer.domElement.captureStream) {
      this.setStatus('当前浏览器不支持录制（MediaRecorder/captureStream 不可用）');
      return;
    }
    var canvas = this.pipRenderer.domElement;
    var stream;
    try {
      stream = canvas.captureStream(30);
    } catch (err) {
      this.setStatus('录制启动失败: ' + (err && err.message ? err.message : err));
      return;
    }
    var mime = '';
    ['video/mp4', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].forEach(function (m) {
      if (!mime && MediaRecorder.isTypeSupported(m)) mime = m;
    });
    var rec;
    try {
      rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 8000000 } : undefined);
    } catch (err) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      this.setStatus('录制启动失败: ' + (err && err.message ? err.message : err));
      return;
    }
    var chunks = [];
    var self = this;
    rec.ondataavailable = function (e) {
      if (e.data && e.data.size) chunks.push(e.data);
    };
    rec.onstop = function () {
      self._recorder = null;
      self._recordStream = null;
      stream.getTracks().forEach(function (t) { t.stop(); });
      self._syncRecordBtn();
      var blob = new Blob(chunks, { type: mime || 'video/webm' });
      if (blob.size < 1000) {
        self.setStatus('录制已取消（无画面数据）');
        return;
      }
      self._uploadRecording(blob, mime);
    };
    // 从头开始播放。注意顺序：先 stopTimeline（此时 _recorder 尚未挂载，
    // 不会触发 stopRecording），再挂载 recorder 并 start，最后开播。
    this.stopTimeline();
    this._recorder = rec;
    this._recordStream = stream;
    rec.start(250);
    this.togglePlay();
    this._syncRecordBtn();
    this.setStatus('录制中：播放结束自动停止；也可点「⏹ 结束录制」提前结束');
  };

  // 结束录制（提前或播完自动调用），在 onstop 中上传
  DirectorEditor.prototype.stopRecording = function () {
    if (!this._recorder) return;
    if (this._recorder.state !== 'inactive') {
      try { this._recorder.stop(); } catch (e) { /* noop */ }
    }
  };

  // 关闭编辑器时丢弃未完成的录制
  DirectorEditor.prototype.discardRecording = function () {
    if (!this._recorder) return;
    var rec = this._recorder;
    this._recorder = null;
    rec.onstop = null;
    rec.ondataavailable = null;
    try { if (rec.state !== 'inactive') rec.stop(); } catch (e) { /* noop */ }
    if (this._recordStream) {
      this._recordStream.getTracks().forEach(function (t) { t.stop(); });
      this._recordStream = null;
    }
    this._syncRecordBtn();
  };

  DirectorEditor.prototype._uploadRecording = async function (blob, mime) {
    this.setStatus('录制完成，正在上传…');
    var ext = (mime || '').indexOf('mp4') >= 0 ? 'mp4' : 'webm';
    try {
      var file = new File([blob], 'director_record.' + ext, { type: mime || 'video/webm' });
      if (typeof uploadFile !== 'function') throw new Error('uploadFile missing');
      var url = await uploadFile(file);
      if (!url) throw new Error('上传失败');
      this.node.data.recordUrl = url;
      this.updateNodeShell();
      // 画布上生成视频节点并连线（可接入后续流程/时间轴）
      var vidNodeId = null;
      if (typeof window.createDirectorStageVideoNode === 'function') {
        vidNodeId = window.createDirectorStageVideoNode(this.node, url, file.name);
      }
      if (typeof safeAutoSave === 'function') safeAutoSave();
      this.setStatus(vidNodeId ? '录制已上传，已在画布生成视频节点' : '录制已上传并更新节点数据');
      if (typeof showToast === 'function') showToast('导演台视频已导出', 'success');
    } catch (err) {
      console.error('录制上传失败:', err);
      this.setStatus('录制上传失败: ' + (err && err.message ? err.message : err));
      if (typeof showToast === 'function') showToast('录制上传失败', 'error');
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

      var tNow = (window.performance && performance.now) ? performance.now() / 1000 : Date.now() / 1000;
      self.tickTimeline(tNow);

      // 编辑视角
      var sp = Math.sin(o.phi), cp = Math.cos(o.phi);
      self.viewCam.position.set(
        o.target.x + o.radius * sp * Math.sin(o.theta),
        o.target.y + o.radius * cp,
        o.target.z + o.radius * sp * Math.cos(o.theta)
      );
      self.viewCam.lookAt(o.target);
      self.syncEnvToCamera(self.viewCam);

      // 虚拟相机姿态
      self.virtualCam.position.copy(self.virtualCamCfg.pos);
      self.virtualCam.lookAt(self.virtualCamCfg.target);
      self.virtualCam.fov = self.virtualCamCfg.fov;
      self.virtualCam.updateProjectionMatrix();

      // 对焦十字呼吸动画 + 选中放大
      if (self.focusMarker) {
        var fBase = self.selectedCamTarget === 'focus' ? 0.32 : 0.22;
        var fPulse = 1 + 0.05 * Math.sin(tNow * 3);
        self.focusMarker.scale.set(fBase * fPulse, fBase * fPulse, 1);
      }
      self.updateAxisGizmo();

      self.mainPipeline.render();

      // PiP（隐藏 helper 再渲染；环境球改跟虚拟相机，保证快照里脚也贴地）
      self.setHelpersVisible(false);
      self.syncEnvToCamera(self.virtualCam);
      self.pipPipeline.render();
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
    this.setupTimeline();
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
    this.on(this.$('dsRecordBtn'), 'click', function () {
      if (self._recorder) self.stopRecording();
      else self.startRecording();
    });
    // 对话改机位（与故事板 3D 预览同款交互，走 /api/video-workflow/camera-chat）
    this.on(this.$('dsChatSend'), 'click', function () { self.sendCameraChat(); });
    this.on(this.$('dsChatInput'), 'keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        self.sendCameraChat();
      }
    });
    this.loadChatModels();
    // 必须用原生 'keydown'。'keydown.directorStage' 不会被 addEventListener 识别，
    // 监听从未挂上，Delete/Backspace 会冒泡到画布并删掉仍处于选中态的导演台节点。
    this.on(document, 'keydown', function (e) {
      if (!self.overlay || !self.overlay.classList.contains('show')) return;
      var tag = document.activeElement && document.activeElement.tagName;
      var inField = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
        (document.activeElement && document.activeElement.isContentEditable);
      if (e.key === 'Escape') {
        // 输入框聚焦时 Esc 仅退出聚焦（对话输入条内不应关闭整个导演台）
        if (inField && document.activeElement && document.activeElement.blur) {
          document.activeElement.blur();
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        self.close(true);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        if (inField) return;
        e.preventDefault();
        e.stopPropagation();
        self.undo();
        return;
      }
      if (e.key.indexOf('Arrow') === 0) {
        if (inField) return;
        // 方向键平移选中的人偶：按当前观察方向移动，Shift 加速。
        // 仅在确实移动成功时阻止默认行为，未选中人偶时不拦截画布等其它监听。
        if (self.nudgeSelectedPuppet(e.key, e.shiftKey)) {
          e.preventDefault();
          e.stopPropagation();
        }
        return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (inField) return;
        // 吞掉按键：节点仍在 selectedNodeIds 中，若冒泡到 window，会确认删除画布节点，
        // close() 不走，录制与两个 WebGLRenderer 都不会释放。
        e.preventDefault();
        e.stopPropagation();
        if (e.key === 'Delete' && self.selectedPuppetId) {
          self.removePuppet(self.selectedPuppetId);
        }
      }
    });
  };

  DirectorEditor.prototype.close = function (flush) {
    this.abortEnvFit();
    // 录制中关闭：丢弃未完成的录制
    this.discardRecording();
    // 停止时间轴播放并恢复关节姿态，避免步态摆动残留在 rig 上
    if (typeof this.stopTimelineForClose === 'function') this.stopTimelineForClose();
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

    // 先释放后处理、灯光与环境，再释放两个 renderer，避免反复打开导演台累积 GPU 资源。
    if (this.mainPipeline) this.mainPipeline.dispose();
    if (this.pipPipeline) this.pipPipeline.dispose();
    if (this.studioLights) this.studioLights.dispose();
    if (this.studioEnvironment) this.studioEnvironment.dispose();
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
    function disposeGizmo(g) {
      if (!g) return;
      if (g.parent) g.parent.remove(g);
      g.traverse(function (o) {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          if (o.material.map) o.material.map.dispose();
          o.material.dispose();
        }
        if (o.userData && o.userData._texture) o.userData._texture.dispose();
      });
    }
    disposeGizmo(this.axisGizmo);
    disposeGizmo(this.fovGizmo);
    this.axisGizmo = null;
    this.fovGizmo = null;

    if (this.overlay) this.overlay.remove();
    ed = null;
  };

  // ============ 对外 API ============

  // 时间轴能力（关键帧/播放）由独立模块挂载原型方法（director_stage_timeline.js）
  if (window.DirectorStageTimelineModule && typeof window.DirectorStageTimelineModule.attach === 'function') {
    window.DirectorStageTimelineModule.attach(DirectorEditor, {
      clamp: clamp,
      round2: round2,
      deg2rad: deg2rad
    });
  }

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

  function syncDirectorStageEnvironment(nodeId) {
    if (!ed || !isDirectorStageEditorOpen()) return;
    if (nodeId != null && ed.nodeId !== nodeId) return;
    var env = ed.getEnvData();
    if (env && env.url) ed.setupEnvironment(env);
    else ed.removeEnvironment();
  }

  // GLTFLoader 在 video_workflow.html 中先于本模块加载，此处预载男性人台，
  // 用户打开导演台时通常已就绪；未就绪/失败时 buildPuppetRig 自动回退程序化人偶。
  preloadMaleBaseMesh();

  window.DirectorStageEditor = {
    open: openDirectorStageEditor,
    isOpen: isDirectorStageEditorOpen,
    syncEnvironment: syncDirectorStageEnvironment,
    getInstance: function () { return ed; }
  };
})();
