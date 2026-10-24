/**
 * 分镜 3D 空间布局预览（three.js）。
 *
 * 空间表达载体是 LLM 直出的 three.js 场景代码（每镜 three_scene_code）：
 * - 空间序列首镜以 startScene(...) 构建极简空间（场景体块 + 角色站位），
 *   空间关系保持的后续镜基于上一镜增量调整（moveActor 人物运动等），
 *   每镜必须 setCamera(...) 确定镜头位置；
 * - 本模块把序列内 startScene 到当前镜的代码按顺序在沙箱内重放执行，
 *   得到该镜的完整空间状态后渲染，并提供「镜头视角」画中画取景器；
 * - 机位可编辑（手动：主视图拖拽机位方块/焦点球 + 侧栏滑杆/预设；
 *   对话：弹窗底部输入条走 /scene/{id}/camera-chat 单轮 LLM 参数提取）。
 *   所有修改统一经 rewriteSetCamera 写回本镜 three_scene_code 的 setCamera
 *   行并保存（three.js 代码是机位唯一真源，纯函数见 spatial_camera_edit.js）；
 * - 存量分镜只有结构化 spatial_layout（旧 JSON 方案）时回退确定性渲染，
 *   不开放机位编辑。
 *
 * 代码在 Function 作用域沙箱内执行：只注入 THREE / scene / camera /
 * actors / props / stage 与构建 helper，不暴露 window/document。
 * three.min.js（r128 UMD）懒加载；弹窗 DOM 自管理，关闭时完整 dispose。
 */
import state, { resolveSelectedLlmModel } from './state.js';
import { getSpatialPreviews, updateScenePrompt, cameraChat } from './api.js';
import { showToast } from './utils.js';
import {
    CAMERA_LIMITS,
    CAMERA_PRESETS,
    applyCameraPreset,
    aspectFromRatio,
    cameraSeesActors,
    clampCamera,
    findLastSetCameraCall,
    normalizeCamera,
    rewriteSetCamera,
} from './spatial_camera_edit.js';

// 转义统一收敛到 web/js/escape.js（window.escapeHtml，经典 script 先于本 module 执行）
const escapeHtml = (typeof window !== 'undefined' && typeof window.escapeHtml === 'function')
    ? window.escapeHtml
    : ((text) => String(text == null ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;'));

// ============ 常量 ============

const THREE_SRC = `/assets/vendor/three.min.js${window.__STATIC_VERSION ? `?v=${window.__STATIC_VERSION}` : ''}`;
// 归一化坐标（约 [-1,1]）→ 展示米制（仅旧 JSON 渲染路径使用）
const SCALE = 3.0;
const COLORS = {
    primary: 0x4f8ef7,
    visible: 0x4f8ef7,
    partial: 0x4dc3e8,
    offscreen: 0x8d9aa8,
    occluded: 0xe8b34d,
    prop: 0x34c38f,
    anchor: 0xb57de8,
    camera: 0xf76f5e,
    stage: 0x9aa7b8,
    actorA: 0x4f8ef7,
    actorB: 0xe8915a,
    actorC: 0x34c38f,
};
const ACTOR_PALETTE = [COLORS.actorA, COLORS.actorB, COLORS.actorC, 0xb57de8, 0xe8b34d];

// ============ 模块状态 ============

let threeLoading = null;       // Promise<THREE> 单例
let previewCache = null;       // { storyboardId, previews: [] }
let activePreview = null;      // 当前打开的预览会话（见 openSpatial3dPreview）

// ============ 数据获取 ============

/** 分镜是否携带空间数据（three.js 代码或存量 spatial_layout，决定 3D 入口按钮）。 */
export function hasSpatialLayout(scene) {
    const prompt = scene && scene._fullPrompt;
    if (!prompt) return false;
    if (typeof prompt.three_scene_code === 'string' && prompt.three_scene_code.trim()) {
        return true;
    }
    return !!(typeof prompt.spatial_layout === 'object' && prompt.spatial_layout);
}

async function fetchSpatialPreviews(storyboardId) {
    if (previewCache && previewCache.storyboardId === storyboardId) {
        return previewCache.previews;
    }
    let result;
    try {
        // 走 api.js 统一认证（authHeaders：X-User-Id + Bearer token），
        // 直连 fetch 不带头会被 require_permission 拒 400/401
        result = await getSpatialPreviews(storyboardId);
    } catch (error) {
        if (error && error.status === 403) {
            throw new Error(error.message || '3D 空间预览为商业版效果模式专属功能');
        }
        throw error;
    }
    const previews = (result && result.previews) || [];
    if (!Array.isArray(previews)) {
        throw new Error('获取空间预览数据失败');
    }
    previewCache = { storyboardId, previews };
    return previews;
}

/** 前端手动更新过 spatial 数据后可调用，使下次打开重新拉取。 */
export function invalidateSpatialPreviewCache() {
    previewCache = null;
}

// ============ three.js 懒加载 ============

function loadThree() {
    if (threeLoading) return threeLoading;
    threeLoading = new Promise((resolve, reject) => {
        if (window.THREE) {
            resolve(window.THREE);
            return;
        }
        const script = document.createElement('script');
        script.src = THREE_SRC;
        script.onload = () => {
            if (window.THREE) resolve(window.THREE);
            else reject(new Error('three.js 加载异常'));
        };
        script.onerror = () => {
            threeLoading = null;
            reject(new Error('three.js 加载失败，请刷新页面重试'));
        };
        document.head.appendChild(script);
    });
    return threeLoading;
}

// ============ 公共构件（Canvas 纹理标签 / 旧 JSON 路径复用） ============

/** Canvas 文字标签（Sprite）。文字绘制在 canvas 纹理上，不经 innerHTML。 */
function makeLabel(THREE, text, { color = '#1f2937', bg = 'rgba(255,255,255,0.92)' } = {}) {
    const canvas = document.createElement('canvas');
    const fontSize = 44;
    const pad = 18;
    const ctx = canvas.getContext('2d');
    const font = `600 ${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`;
    ctx.font = font;
    const textWidth = ctx.measureText(text).width;
    canvas.width = Math.ceil(textWidth) + pad * 2;
    canvas.height = Math.ceil(fontSize * 1.3);
    // canvas.width/height 赋值会重置 ctx 全部状态（含字体），绘制前必须重设
    ctx.font = font;
    ctx.fillStyle = bg;
    const radius = 16;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(0, 0, canvas.width, canvas.height, radius);
    else ctx.rect(0, 0, canvas.width, canvas.height);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.textBaseline = 'middle';
    ctx.fillText(text, pad, canvas.height / 2);

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
    const sprite = new THREE.Sprite(material);
    const height = 0.42;
    sprite.scale.set(height * (canvas.width / canvas.height), height, 1);
    sprite.userData.isLabel = true;
    return sprite;
}

// ============ 代码重放沙箱（three_scene_code 方案核心） ============

/**
 * LibTV 风格人偶（与导演台人偶同风格）：胶囊四肢 + 球形关节接缝 +
 * 蛋形无脸头 + 面甲深色带指示朝向。root 在脚底，身高约 1.55m。
 * 纯静态站姿（预览不做姿态编辑），几何体每偶独立，随预览 dispose。
 */
function buildMannequin(THREE, color, name, facing) {
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.0 });
    const seamMat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(color).multiplyScalar(0.78), roughness: 0.55, metalness: 0.0,
    });
    const group = new THREE.Group();
    const body = new THREE.Group();
    group.add(body);
    const sphere = new THREE.SphereGeometry(1, 20, 16);

    const ellip = (rx, ry, rz, m2) => {
        const mesh = new THREE.Mesh(sphere, m2 || mat);
        mesh.scale.set(rx, ry, rz);
        body.add(mesh);
        return mesh;
    };
    const seg = (rTop, rBottom, h, y) => {
        const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rTop, rBottom, h, 14), mat);
        mesh.position.y = y;
        body.add(mesh);
        return mesh;
    };
    const ballAt = (r, x, y, z) => {
        const mesh = new THREE.Mesh(sphere, seamMat);
        mesh.scale.set(r, r, r);
        mesh.position.set(x, y, z);
        body.add(mesh);
        return mesh;
    };

    // 腿：深色鞋底 + 脚 → 小腿 → 膝（髌骨板）→ 大腿 → 髋关节
    for (const s of [1, -1]) {
        const sole = ellip(0.055, 0.011, 0.098, seamMat);
        sole.position.set(s * 0.082, 0.009, 0.02);
        const foot = ellip(0.052, 0.026, 0.095);
        foot.position.set(s * 0.082, 0.037, 0.02);
        seg(0.040, 0.046, 0.36, 0.24);
        ballAt(0.048, s * 0.082, 0.43, 0);
        const kneeCap = ellip(0.036, 0.041, 0.017, seamMat);
        kneeCap.position.set(s * 0.082, 0.415, 0.042);
        seg(0.058, 0.048, 0.36, 0.61);
        ballAt(0.054, s * 0.082, 0.80, 0);
    }
    // 躯干：骨盆（+短裤腰线）→ 腹 → 胸 → 肩线（光滑一体，凸块呈"包子"感已移除）
    ellip(0.135, 0.10, 0.095).position.y = 0.885;
    const waistBand = ellip(0.130, 0.022, 0.092, seamMat);
    waistBand.position.y = 0.905;
    body.add(waistBand);
    ellip(0.125, 0.075, 0.09).position.y = 0.985;
    ellip(0.15, 0.125, 0.10).position.y = 1.095;
    ellip(0.165, 0.05, 0.055).position.y = 1.20;
    // 臂：肩 → 上臂 → 肘（壳板）→ 前臂 → 手（连指+拇指）
    for (const s of [1, -1]) {
        ballAt(0.05, s * 0.165, 1.195, 0);
        const arm = new THREE.Group();
        arm.position.set(s * 0.165, 1.19, 0);
        arm.rotation.z = s * 0.09;
        const upper = new THREE.Mesh(new THREE.CylinderGeometry(0.042, 0.038, 0.24, 12), mat);
        upper.position.y = -0.12;
        const elbow = new THREE.Mesh(sphere, seamMat);
        elbow.scale.set(0.040, 0.040, 0.040);
        elbow.position.y = -0.245;
        const elbowCap = ellip(0.025, 0.030, 0.013, seamMat);
        elbowCap.position.set(0, -0.242, 0.032);
        const lower = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.030, 0.22, 12), mat);
        lower.position.y = -0.355;
        const hand = new THREE.Mesh(sphere, mat);
        hand.scale.set(0.032, 0.048, 0.022);
        hand.position.y = -0.50;
        const thumb = new THREE.Mesh(sphere, mat);
        thumb.scale.set(0.012, 0.022, 0.012);
        thumb.position.set(-s * 0.011, -0.458, 0.015);
        thumb.rotation.x = 0.5;
        arm.add(upper, elbow, elbowCap, lower, hand, thumb);
        body.add(arm);
    }
    // 颈 + 蛋形头（下颌融合）+ 头部雕塑（眉/鼻/唇/耳）+ 面甲深色带（朝向指示，正面 = +Z）
    const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.032, 0.034, 0.07, 12), mat);
    neck.position.y = 1.26;
    body.add(neck);
    const head = new THREE.Mesh(sphere, mat);
    head.scale.set(0.087, 0.103, 0.092);
    head.position.y = 1.395;
    body.add(head);
    const jaw = new THREE.Mesh(sphere, mat);
    jaw.scale.set(0.062, 0.048, 0.06);
    jaw.position.set(0, 1.345, 0.016);
    body.add(jaw);
    // 头部雕塑 v7（与导演台同款，尺寸按 0.79 缩放）
    const brow = ellip(0.042, 0.007, 0.014);
    brow.position.set(0, 1.416, 0.070);
    const nose = ellip(0.012, 0.019, 0.017);
    nose.position.set(0, 1.388, 0.080);
    const lipUp = ellip(0.018, 0.0035, 0.007);
    lipUp.position.set(0, 1.363, 0.066);
    const lipDn = ellip(0.015, 0.004, 0.007);
    lipDn.position.set(0, 1.354, 0.064);
    const earL = ellip(0.007, 0.015, 0.009);
    earL.position.set(0.079, 1.393, -0.004);
    const earR = ellip(0.007, 0.015, 0.009);
    earR.position.set(-0.079, 1.393, -0.004);
    body.add(brow, nose, lipUp, lipDn, earL, earR);
    const visor = new THREE.Mesh(sphere, seamMat);
    visor.scale.set(0.058, 0.026, 0.016);
    visor.position.set(0, 1.408, 0.078);
    body.add(visor);

    const label = makeLabel(THREE, name);
    label.position.y = 1.62;
    group.add(label);
    group.rotation.y = (Number(facing) || 0) * Math.PI / 180;
    return group;
}


/** 故事板画幅宽高比（跟随 workflowRatio，9:16 竖屏故事板不能按 16:9 取景）。 */
function previewAspect() {
    return aspectFromRatio(state.workflowRatio, 16 / 9);
}

/**
 * 创建一次重放会话：root 承载世界对象，registries 是暴露给代码的
 * actors/props/stage 对象表，shotCamera 是本镜相机（画中画取景器使用）。
 * helper 集合与 LLM prompt 契约（llm/script_parser.py THREE_SCENE_CODE_REQUIREMENTS）
 * 一一对应，两端需同步修改。
 */
function createReplayContext(THREE, aspect) {
    const ar = Number.isFinite(aspect) && aspect > 0 ? aspect : 16 / 9;
    const ctx = {
        THREE,
        root: new THREE.Group(),
        actors: {},
        props: {},
        stage: {},
        shotCamera: new THREE.PerspectiveCamera(50, ar, 0.05, 200),
        cameraInfo: null,       // setCamera 记录 {eye, target, fov}
        sceneLabel: '',
        actorColorIndex: 0,
        replayErrors: [],
    };

    const disposeChildren = (object) => {
        for (const child of [...object.children]) {
            object.remove(child);
            child.traverse((node) => {
                if (node.geometry) node.geometry.dispose();
                const materials = Array.isArray(node.material) ? node.material : [node.material];
                for (const material of materials) {
                    if (!material) continue;
                    if (material.map) material.map.dispose();
                    material.dispose();
                }
            });
        }
    };

    const requireEntry = (table, name, api) => {
        const entry = table[name];
        if (!entry) throw new Error(`${api}("${name}")：对象不存在（须先 make 创建或名称拼写一致）`);
        return entry;
    };

    const helpers = {
        startScene(label = '') {
            disposeChildren(ctx.root);
            // 原地清空注册表：沙箱参数绑定的是对象引用，重赋值会破坏后续 actors.X 读取
            for (const key of Object.keys(ctx.actors)) delete ctx.actors[key];
            for (const key of Object.keys(ctx.props)) delete ctx.props[key];
            for (const key of Object.keys(ctx.stage)) delete ctx.stage[key];
            ctx.sceneLabel = String(label || '');
            ctx.actorColorIndex = 0;
            const grid = new THREE.GridHelper(12, 24, 0xcbd5e1, 0xe5eaf1);
            ctx.root.add(grid);
        },
        makeStage(name, width = 2, depth = 2, x = 0, z = 0, options = {}) {
            const h = Number(options.h != null ? options.h : 1);
            const y = Number(options.y != null ? options.y : 0);
            const mesh = new THREE.Mesh(
                new THREE.BoxGeometry(Math.max(width, 0.05), Math.max(h, 0.05), Math.max(depth, 0.05)),
                new THREE.MeshLambertMaterial({
                    color: Number(options.color != null ? options.color : COLORS.stage),
                    transparent: true,
                    opacity: 0.55,
                }),
            );
            mesh.position.set(x, y + h / 2, z);
            ctx.root.add(mesh);
            ctx.stage[name] = mesh;
            return mesh;
        },
        makeActor(name, x = 0, z = 0, options = {}) {
            const color = Number(options.color != null
                ? options.color
                : ACTOR_PALETTE[ctx.actorColorIndex++ % ACTOR_PALETTE.length]);
            const group = buildMannequin(THREE, color, String(name), Number(options.facing) || 0);
            group.position.set(x, 0, z);
            ctx.root.add(group);
            ctx.actors[name] = group;
            return group;
        },
        makeProp(name, x = 0, z = 0, options = {}) {
            const group = new THREE.Group();
            const y = Number(options.y != null ? options.y : 0.3);
            const mesh = new THREE.Mesh(
                new THREE.SphereGeometry(0.16, 18, 14),
                new THREE.MeshLambertMaterial({ color: COLORS.prop }),
            );
            mesh.position.y = y;
            const label = makeLabel(THREE, String(name), { color: '#0f6b4f' });
            label.position.y = y + 0.38;
            group.add(mesh, label);
            group.position.set(x, 0, z);
            ctx.root.add(group);
            ctx.props[name] = group;
            return group;
        },
        moveActor(name, x, z, options = {}) {
            const group = requireEntry(ctx.actors, name, 'moveActor');
            group.position.set(Number(x), 0, Number(z));
            if (options.facing != null) group.rotation.y = Number(options.facing) * Math.PI / 180;
            return group;
        },
        moveProp(name, x, z, options = {}) {
            const group = requireEntry(ctx.props, name, 'moveProp');
            group.position.set(Number(x), 0, Number(z));
            if (options.y != null) {
                const mesh = group.children[0];
                if (mesh) mesh.position.y = Number(options.y);
            }
            return group;
        },
        setCamera(ex, ey, ez, tx, ty, tz, fov = 50) {
            ctx.shotCamera.fov = Number(fov) || 50;
            ctx.shotCamera.position.set(Number(ex), Number(ey), Number(ez));
            ctx.shotCamera.lookAt(Number(tx), Number(ty), Number(tz));
            ctx.shotCamera.updateProjectionMatrix();
            ctx.cameraInfo = {
                eye: { x: Number(ex), y: Number(ey), z: Number(ez) },
                target: { x: Number(tx), y: Number(ty), z: Number(tz) },
                fov: Number(fov) || 50,
            };
        },
    };
    return { ctx, helpers };
}

/** 在 Function 作用域沙箱内执行一镜代码；异常记录到 ctx.replayErrors。 */
function runThreeCode(THREE, ctx, helpers, code, shotLabel) {
    try {
        const runner = new Function(
            'THREE', 'scene', 'camera', 'actors', 'props', 'stage',
            'startScene', 'makeStage', 'makeActor', 'makeProp',
            'moveActor', 'moveProp', 'setCamera',
            `"use strict";\n${code}`,
        );
        runner(
            THREE, ctx.root, ctx.shotCamera,
            ctx.actors, ctx.props, ctx.stage,
            helpers.startScene, helpers.makeStage, helpers.makeActor, helpers.makeProp,
            helpers.moveActor, helpers.moveProp, helpers.setCamera,
        );
    } catch (error) {
        ctx.replayErrors.push({
            shot: shotLabel,
            message: (error && error.message) ? error.message : String(error),
        });
    }
}

/** 判定预览载荷是否为 three.js 代码方案。 */
function isCodePreview(preview) {
    return !!(preview && preview.three_scene && preview.three_scene.kind === 'three_code');
}

/**
 * 从当前镜往前找最近的序列起点（startScene），顺序重放到当前镜。
 * 存量 JSON 镜头（无代码）是链边界：从边界后第一镜开始重放。
 * 返回 {ctx, chainStart, chainLength}。
 */
function replayToIndex(THREE, previews, index) {
    let i = index;
    while (
        i >= 0
        && isCodePreview(previews[i])
        && !previews[i].three_scene.is_sequence_start
    ) {
        i--;
    }
    const start = (i >= 0 && isCodePreview(previews[i])) ? i : i + 1;
    const { ctx, helpers } = createReplayContext(THREE, previewAspect());
    let chainLength = 0;
    for (let j = start; j <= index; j++) {
        if (!isCodePreview(previews[j])) continue;
        runThreeCode(THREE, ctx, helpers, previews[j].three_scene.code, previews[j].title || `#${j + 1}`);
        chainLength++;
    }
    // 代码直接操作 camera.position/lookAt（未走 setCamera）时机位兜底：
    // 用相机朝向前方固定距离点作为 target，供机位视锥展示。
    if (!ctx.cameraInfo) {
        const forward = new THREE.Vector3();
        ctx.shotCamera.getWorldDirection(forward);
        const eye = ctx.shotCamera.position;
        const target = eye.clone().addScaledVector(forward, 2.5);
        ctx.cameraInfo = {
            eye: { x: eye.x, y: eye.y, z: eye.z },
            target: { x: target.x, y: target.y, z: target.z },
            fov: ctx.shotCamera.fov,
        };
    }
    return { ctx, chainStart: start, chainLength };
}

/** 机位视锥 + 朝向箭头（代码方案：米制坐标，直接使用）。
 * aspect 为本镜取景宽高比（跟随故事板画幅）；
 * 机位方块 userData.dragKind='camera'、焦点球 'focus'，主视图可直接拖拽编辑。 */
function makeCameraGizmoFromInfo(THREE, cameraInfo, aspect = 16 / 9) {
    const group = new THREE.Group();
    const { eye, target } = cameraInfo;
    if (!eye || !target) return group;

    const mat = new THREE.LineBasicMaterial({ color: COLORS.camera });
    const fovRad = ((cameraInfo.fov || 50) * Math.PI) / 180;
    const dist = Math.hypot(target.x - eye.x, target.y - eye.y, target.z - eye.z) || 1;
    const halfH = Math.tan(fovRad / 2) * dist;
    const halfW = halfH * aspect;

    const frame = new THREE.Mesh(
        new THREE.PlaneGeometry(halfW * 2, halfH * 2),
        new THREE.MeshBasicMaterial({
            color: COLORS.camera, transparent: true, opacity: 0.1, side: THREE.DoubleSide,
        }),
    );
    frame.position.set(target.x, target.y, target.z);
    frame.lookAt(eye.x, eye.y, eye.z);
    group.add(frame);

    const corners = [
        new THREE.Vector3(-halfW, halfH, 0), new THREE.Vector3(halfW, halfH, 0),
        new THREE.Vector3(halfW, -halfH, 0), new THREE.Vector3(-halfW, -halfH, 0),
    ].map((local) => frame.localToWorld(local.clone()));
    const eyeVec = new THREE.Vector3(eye.x, eye.y, eye.z);
    const frustumGeo = new THREE.BufferGeometry().setFromPoints([
        eyeVec, corners[0], eyeVec, corners[1], eyeVec, corners[2], eyeVec, corners[3],
        corners[0], corners[1], corners[1], corners[2], corners[2], corners[3], corners[3], corners[0],
    ]);
    group.add(new THREE.LineSegments(frustumGeo, mat));

    const camBody = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.14, 0.28),
        new THREE.MeshLambertMaterial({ color: COLORS.camera }),
    );
    camBody.position.copy(eyeVec);
    camBody.lookAt(target.x, target.y, target.z);
    camBody.userData.dragKind = 'camera';
    group.add(camBody);

    // 焦点球（对焦中心，黄色，可直接拖拽改变朝向；仿导演台）
    const focusBall = new THREE.Mesh(
        new THREE.SphereGeometry(0.11, 14, 12),
        new THREE.MeshLambertMaterial({ color: 0xe8b34d }),
    );
    focusBall.position.set(target.x, target.y, target.z);
    focusBall.userData.dragKind = 'focus';
    group.add(focusBall);

    const label = makeLabel(THREE, '机位', { color: '#7a2e20' });
    label.position.set(eye.x, eye.y + 0.4, eye.z);
    group.add(label);
    return group;
}

// ============ 存量 JSON 渲染路径（旧 spatial_layout 方案兼容） ============

/** schema Z-up 归一化坐标 → three Y-up 米制展示坐标。 */
function toThree(pos) {
    if (!pos || typeof pos !== 'object') return null;
    const { x, y, z } = pos;
    if (![x, y, z].every((v) => Number.isFinite(v))) return null;
    return { x: x * SCALE, y: (z || 0) * SCALE, z: -(y || 0) * SCALE };
}

function entityColor(entity) {
    if (entity.kind === 'prop') return COLORS.prop;
    const key = String(entity.visibility || 'visible').toLowerCase();
    if (COLORS[key] !== undefined) return COLORS[key];
    return COLORS.visible;
}

function makeEntityMesh(THREE, entity) {
    const group = new THREE.Group();
    const color = entityColor(entity);
    const isProp = entity.kind === 'prop';
    const opacity = String(entity.visibility || '').toLowerCase() === 'offscreen' ? 0.38 : 0.92;

    if (isProp) {
        const mesh = new THREE.Mesh(
            new THREE.SphereGeometry(0.16, 18, 14),
            new THREE.MeshLambertMaterial({ color, transparent: opacity < 1, opacity }),
        );
        mesh.position.y = 0.16;
        group.add(mesh);
    } else {
        const body = new THREE.Mesh(
            new THREE.CylinderGeometry(0.15, 0.19, 0.85, 16),
            new THREE.MeshLambertMaterial({ color, transparent: opacity < 1, opacity }),
        );
        body.position.y = 0.5;
        const head = new THREE.Mesh(
            new THREE.SphereGeometry(0.14, 18, 14),
            new THREE.MeshLambertMaterial({ color, transparent: opacity < 1, opacity }),
        );
        head.position.y = 1.08;
        group.add(body, head);
    }

    const label = makeLabel(THREE, entity.name || entity.id || '?');
    label.position.y = isProp ? 0.55 : 1.5;
    group.add(label);
    return group;
}

function makeCameraGizmo(THREE, camera) {
    const pos = { x: camera.eye.x, y: camera.eye.y, z: camera.eye.z };
    const target = { x: camera.target.x, y: camera.target.y, z: camera.target.z };
    const mapped = toThree(pos) || pos;
    const mappedTarget = toThree(target) || target;
    return makeCameraGizmoFromInfo(THREE, {
        eye: mapped,
        target: mappedTarget,
        fov: camera.fov_deg || 50,
    }, previewAspect());
}

/** 按后端 three_scene JSON 构建 three.js 场景内容（不含灯光与观察相机）。 */
function buildWorldGroup(THREE, threeScene) {
    const group = new THREE.Group();

    const grid = new THREE.GridHelper(SCALE * 2.4, 24, 0xcbd5e1, 0xe5eaf1);
    grid.position.y = -0.001;
    group.add(grid);

    for (const anchor of threeScene.anchors || []) {
        const pos = toThree(anchor.position);
        if (!pos) continue;
        const mesh = new THREE.Mesh(
            new THREE.OctahedronGeometry(0.11),
            new THREE.MeshLambertMaterial({ color: COLORS.anchor }),
        );
        mesh.position.set(pos.x, pos.y + 0.11, pos.z);
        group.add(mesh);
        const label = makeLabel(THREE, anchor.name || anchor.id || '', { color: '#5b21b6' });
        label.position.set(pos.x, pos.y + 0.42, pos.z);
        group.add(label);
    }

    for (const entity of threeScene.entities || []) {
        const pos = toThree(entity.position);
        if (!pos) continue;
        const mesh = makeEntityMesh(THREE, entity);
        mesh.position.set(pos.x, pos.y, pos.z);
        group.add(mesh);
    }

    if (threeScene.camera && threeScene.camera.eye) {
        group.add(makeCameraGizmo(THREE, threeScene.camera));
    }
    return group;
}

// ============ 弹窗与交互 ============

function previewShellHtml() {
    return `
        <div class="spatial3d-overlay" data-spatial3d-overlay>
            <div class="spatial3d-dialog" role="dialog" aria-label="分镜 3D 空间布局预览">
                <header class="spatial3d-header">
                    <div class="spatial3d-title">
                        <span data-spatial3d-scene-title></span>
                        <span class="spatial3d-diag-badge" data-spatial3d-diag-badge hidden></span>
                    </div>
                    <div class="spatial3d-nav">
                        <button type="button" class="btn-ghost" data-spatial3d-prev>‹ 上一镜</button>
                        <span class="spatial3d-nav-pos" data-spatial3d-pos></span>
                        <button type="button" class="btn-ghost" data-spatial3d-next>下一镜 ›</button>
                    </div>
                    <button type="button" class="spatial3d-close" data-spatial3d-close aria-label="关闭">×</button>
                </header>
                <div class="spatial3d-viewport" data-spatial3d-viewport>
                    <div class="spatial3d-loading" data-spatial3d-loading>正在加载 3D 引擎…</div>
                    <div class="spatial3d-pip-frame" data-spatial3d-pip hidden>
                        <span>镜头视角（本镜 setCamera）</span>
                    </div>
                    <div class="spatial3d-chat-note" data-spatial3d-chat-note hidden></div>
                    <div class="spatial3d-chatbar" data-spatial3d-chat hidden>
                        <input type="text" data-spatial3d-chat-input
                            placeholder="对话调整机位，如：把机位移到角色正面稍高处"
                            maxlength="300">
                        <button type="button" class="spatial3d-chat-send" data-spatial3d-chat-send>发送</button>
                    </div>
                </div>
                <aside class="spatial3d-side">
                    <section class="spatial3d-section" data-spatial3d-camctl hidden></section>
                    <section class="spatial3d-section" data-spatial3d-entities></section>
                    <section class="spatial3d-section" data-spatial3d-code hidden></section>
                    <section class="spatial3d-section" data-spatial3d-diagnostics></section>
                    <section class="spatial3d-legend">
                        <span><i style="background:#4f8ef7"></i>角色</span>
                        <span><i style="background:#34c38f"></i>道具</span>
                        <span><i style="background:#9aa7b8"></i>场景体块</span>
                        <span><i style="background:#f76f5e"></i>机位</span>
                        <span><i style="background:#e8b34d"></i>焦点</span>
                    </section>
                </aside>
            </div>
        </div>`;
}

function entitiesHtml(preview, replayCtx) {
    if (replayCtx) {
        const rows = [];
        for (const [name, group] of Object.entries(replayCtx.actors)) {
            const p = group.position;
            rows.push(`<li>
                <span class="spatial3d-entity-name">${escapeHtml(name)}（角色）</span>
                <span class="spatial3d-entity-meta"><span>站位 x=${p.x.toFixed(2)}, z=${p.z.toFixed(2)}</span></span>
            </li>`);
        }
        for (const [name, group] of Object.entries(replayCtx.props)) {
            const p = group.position;
            rows.push(`<li>
                <span class="spatial3d-entity-name">${escapeHtml(name)}（道具）</span>
                <span class="spatial3d-entity-meta"><span>位置 x=${p.x.toFixed(2)}, z=${p.z.toFixed(2)}</span></span>
            </li>`);
        }
        for (const [name] of Object.entries(replayCtx.stage)) {
            rows.push(`<li>
                <span class="spatial3d-entity-name">${escapeHtml(name)}（场景体块）</span>
            </li>`);
        }
        if (!rows.length) return '<h4>空间对象</h4><p class="spatial3d-empty">无空间对象（代码未构建）</p>';
        return `<h4>空间对象</h4><ul class="spatial3d-entity-list">${rows.join('')}</ul>`;
    }
    const entities = (preview.three_scene && preview.three_scene.entities) || [];
    if (!entities.length) return '<h4>空间实体</h4><p class="spatial3d-empty">无空间实体数据</p>';
    const rows = entities.map((e) => {
        const derived = e.derived_screen_position
            ? `投影：${escapeHtml(e.derived_screen_position)}` : '投影：—';
        const written = e.screen_position ? `声明：${escapeHtml(e.screen_position)}` : '';
        const container = e.container && e.container.name
            ? `${escapeHtml(e.container.name)} / ${escapeHtml(e.container.slot || e.container.slot_id || '')}` : '';
        return `<li>
            <span class="spatial3d-entity-name">${escapeHtml(e.name || e.id || '?')}</span>
            <span class="spatial3d-entity-meta">${[container, written, derived].filter(Boolean).map((t) => `<span>${t}</span>`).join('')}</span>
        </li>`;
    }).join('');
    return `<h4>空间实体</h4><ul class="spatial3d-entity-list">${rows}</ul>`;
}

function codeHtml(preview, chainStart, chainLength, total) {
    const code = (preview.three_scene && preview.three_scene.code) || '';
    const isStart = preview.three_scene && preview.three_scene.is_sequence_start;
    const chainNote = isStart
        ? '本镜为空间序列首镜（startScene 完整构建）'
        : `空间关系保持：基于第 ${chainStart + 1} 镜场景，累计重放 ${chainLength} 段代码（人物运动等增量调整）`;
    return `
        <h4>本镜 three.js 代码</h4>
        <p class="spatial3d-chain-note">${escapeHtml(chainNote)}</p>
        <pre class="spatial3d-code">${escapeHtml(code)}</pre>`;
}

function diagnosticsHtml(preview, replayCtx, cameraDiag) {
    const diags = [...(preview.three_scene && preview.three_scene.diagnostics) || []];
    if (cameraDiag) {
        // 空镜诊断（LLM 产出的机位与站位矛盾，前端重放后校验，见 §8 已知边界）
        diags.unshift({ severity: 'warning', message: cameraDiag });
    }
    for (const err of (replayCtx && replayCtx.replayErrors) || []) {
        diags.push({
            severity: 'error',
            message: `[${err.shot}] 代码执行失败：${err.message}`,
        });
    }
    const header = '<h4>一致性诊断</h4>';
    if (!diags.length) return `${header}<p class="spatial3d-ok">✓ 未发现空间矛盾</p>`;
    const items = diags.map((d) => `
        <li class="spatial3d-diag severity-${escapeHtml(d.severity || 'warning')}">
            <b>${d.severity === 'error' ? '矛盾' : '提示'}</b> ${escapeHtml(d.message || '')}
        </li>`).join('');
    return `${header}<ul class="spatial3d-diag-list">${items}</ul>`;
}

// ============ 机位编辑（手动：拖拽 / 滑杆 / 预设；对话：camera-chat） ============

const CAM_SLIDERS = [
    { key: 'fov', label: '视场角 FOV', min: 15, max: 120, step: 1 },
    { key: 'eyeY', label: '机位高度', min: 0.2, max: 8, step: 0.05 },
    { key: 'targetY', label: '焦点高度', min: 0, max: 4, step: 0.05 },
    { key: 'targetZ', label: '焦点前后', min: -9.5, max: 9.5, step: 0.1 },
    { key: 'targetX', label: '焦点左右', min: -9.5, max: 9.5, step: 0.1 },
];

function camControlHtml(info) {
    const cam = normalizeCamera(info);
    const sliders = CAM_SLIDERS.map((s) => {
        const value = s.key === 'fov' ? Math.round(cam.fov)
            : s.key === 'eyeY' ? cam.eye.y
                : s.key === 'targetY' ? cam.target.y
                    : s.key === 'targetZ' ? cam.target.z : cam.target.x;
        return `<label class="spatial3d-slider-row">
            <span>${escapeHtml(s.label)}</span>
            <input type="range" min="${s.min}" max="${s.max}" step="${s.step}" value="${value}"
                data-camslider="${s.key}">
            <b data-camslider-val="${s.key}">${value}</b>
        </label>`;
    }).join('');
    const presets = CAMERA_PRESETS.map((p) => `
        <button type="button" class="spatial3d-preset-btn" data-campreset="${escapeHtml(p.id)}">${escapeHtml(p.label)}</button>
    `).join('');
    return `
        <h4>机位控制</h4>
        <div class="spatial3d-slider-group">${sliders}</div>
        <div class="spatial3d-preset-grid">${presets}</div>
        <p class="spatial3d-camhint">主视图中可直接拖拽红色机位方块（水平移动）与黄色焦点球（改变朝向）。</p>`;
}

class Spatial3dSession {
    constructor(THREE, previews, startIndex) {
        this.THREE = THREE;
        this.previews = previews;
        this.index = startIndex;
        this.rafId = 0;
        this.orbit = { theta: 0.7, phi: 1.05, radius: 7.5, target: null };
        this.dragging = null;
        this.worldGroup = null;
        this.shotCamera = null;        // 代码方案：本镜相机（画中画）
        this.shotCameraInfo = null;    // 本镜机位参数 {eye, target, fov}（编辑真源）
        this.replayCtx = null;         // 本镜重放上下文（对象清单 / 对话上下文用）
        this.gizmoGroup = null;        // 机位视锥（应用机位后整组重建）
        this.camDirty = false;         // 机位已改、待保存
        this.camBusy = false;          // 对话改机位请求进行中
        this._saveTimer = 0;

        document.body.insertAdjacentHTML('beforeend', previewShellHtml());
        this.overlay = document.querySelector('[data-spatial3d-overlay]');
        this.el = {
            title: this.overlay.querySelector('[data-spatial3d-scene-title]'),
            badge: this.overlay.querySelector('[data-spatial3d-diag-badge]'),
            viewport: this.overlay.querySelector('[data-spatial3d-viewport]'),
            loading: this.overlay.querySelector('[data-spatial3d-loading]'),
            pip: this.overlay.querySelector('[data-spatial3d-pip]'),
            pos: this.overlay.querySelector('[data-spatial3d-pos]'),
            camctl: this.overlay.querySelector('[data-spatial3d-camctl]'),
            entities: this.overlay.querySelector('[data-spatial3d-entities]'),
            code: this.overlay.querySelector('[data-spatial3d-code]'),
            diagnostics: this.overlay.querySelector('[data-spatial3d-diagnostics]'),
            prev: this.overlay.querySelector('[data-spatial3d-prev]'),
            next: this.overlay.querySelector('[data-spatial3d-next]'),
            close: this.overlay.querySelector('[data-spatial3d-close]'),
            chat: this.overlay.querySelector('[data-spatial3d-chat]'),
            chatInput: this.overlay.querySelector('[data-spatial3d-chat-input]'),
            chatSend: this.overlay.querySelector('[data-spatial3d-chat-send]'),
            chatNote: this.overlay.querySelector('[data-spatial3d-chat-note]'),
        };

        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        this.renderer.autoClear = false;
        this.el.viewport.appendChild(this.renderer.domElement);
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 300);
        this.scene.add(new THREE.HemisphereLight(0xffffff, 0xdfe6ef, 1.05));
        const dir = new THREE.DirectionalLight(0xffffff, 0.55);
        dir.position.set(4, 8, 3);
        this.scene.add(dir);

        this._bindEvents();
        this.show(this.index);
        this._animate();
    }

    _bindEvents() {
        this._onClose = () => this.destroy();
        this.el.close.addEventListener('click', this._onClose);
        this._onOverlayClick = (event) => {
            if (event.target === this.overlay) this.destroy();
        };
        this.overlay.addEventListener('click', this._onOverlayClick);
        this._onKey = (event) => {
            const tag = event.target && event.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') {
                if (event.key === 'Escape') event.target.blur();
                return; // 输入框内按键不切镜/不关闭
            }
            if (event.key === 'Escape') this.destroy();
            if (event.key === 'ArrowLeft') this.show(this.index - 1);
            if (event.key === 'ArrowRight') this.show(this.index + 1);
        };
        document.addEventListener('keydown', this._onKey);
        this.el.prev.addEventListener('click', () => this.show(this.index - 1));
        this.el.next.addEventListener('click', () => this.show(this.index + 1));

        const dom = this.renderer.domElement;
        this._onDown = (event) => {
            // 左键优先拾取机位 gizmo（机位方块 / 焦点球），命中进入拖拽编辑
            if (event.button === 0 && this.shotCameraInfo && this.gizmoGroup) {
                const kind = this._pickGizmoKind(event);
                if (kind) {
                    const info = this.shotCameraInfo;
                    const planeY = kind === 'camera' ? info.eye.y : info.target.y;
                    const plane = new this.THREE.Plane(new this.THREE.Vector3(0, 1, 0), -planeY);
                    const raycaster = new this.THREE.Raycaster();
                    raycaster.setFromCamera(this._ndcFromEvent(event), this.camera);
                    const hit = new this.THREE.Vector3();
                    const current = kind === 'camera'
                        ? new this.THREE.Vector3(info.eye.x, info.eye.y, info.eye.z)
                        : new this.THREE.Vector3(info.target.x, info.target.y, info.target.z);
                    if (raycaster.ray.intersectPlane(plane, hit)) {
                        this.dragging = {
                            mode: kind === 'camera' ? 'drag-camera' : 'drag-focus',
                            plane,
                            offset: new this.THREE.Vector3().subVectors(current, hit).setY(0),
                        };
                        event.preventDefault();
                        return;
                    }
                }
            }
            this.dragging = {
                mode: event.button === 2 ? 'pan' : 'orbit',
                x: event.clientX, y: event.clientY,
            };
            event.preventDefault();
        };
        this._onMove = (event) => {
            if (!this.dragging) return;
            if (this.dragging.mode === 'drag-camera' || this.dragging.mode === 'drag-focus') {
                const raycaster = new this.THREE.Raycaster();
                raycaster.setFromCamera(this._ndcFromEvent(event), this.camera);
                const hit = new this.THREE.Vector3();
                if (raycaster.ray.intersectPlane(this.dragging.plane, hit)) {
                    hit.add(this.dragging.offset);
                    const cam = normalizeCamera(this.shotCameraInfo);
                    if (this.dragging.mode === 'drag-camera') {
                        cam.eye.x = hit.x; cam.eye.z = hit.z;
                    } else {
                        cam.target.x = hit.x; cam.target.z = hit.z;
                    }
                    this._applyShotCamera(cam);
                }
                return;
            }
            const dx = event.clientX - this.dragging.x;
            const dy = event.clientY - this.dragging.y;
            this.dragging.x = event.clientX;
            this.dragging.y = event.clientY;
            if (this.dragging.mode === 'orbit') {
                this.orbit.theta -= dx * 0.006;
                this.orbit.phi = Math.min(Math.max(this.orbit.phi - dy * 0.005, 0.12), 1.5);
            } else {
                const scale = this.orbit.radius * 0.0016;
                const right = new this.THREE.Vector3(Math.cos(this.orbit.theta), 0, -Math.sin(this.orbit.theta));
                const forward = new this.THREE.Vector3(-Math.sin(this.orbit.theta), 0, -Math.cos(this.orbit.theta));
                this.orbit.target.addScaledVector(right, -dx * scale);
                this.orbit.target.addScaledVector(forward, dy * scale);
            }
        };
        this._onUp = () => {
            if (this.dragging && (this.dragging.mode === 'drag-camera' || this.dragging.mode === 'drag-focus')) {
                this._scheduleSaveCamera();
            }
            this.dragging = null;
        };
        this._onWheel = (event) => {
            this.orbit.radius = Math.min(Math.max(this.orbit.radius * (1 + event.deltaY * 0.0012), 2), 40);
            event.preventDefault();
        };
        this._onContext = (event) => event.preventDefault();
        dom.addEventListener('mousedown', this._onDown);
        window.addEventListener('mousemove', this._onMove);
        window.addEventListener('mouseup', this._onUp);
        dom.addEventListener('wheel', this._onWheel, { passive: false });
        dom.addEventListener('contextmenu', this._onContext);

        this._bindCamControl();
        this._bindChatBar();

        this._onResize = () => this._resize();
        window.addEventListener('resize', this._onResize);
        this._resize();
    }

    // ---- 机位编辑：滑杆 / 预设（侧栏事件委托） ----

    _bindCamControl() {
        this.el.camctl.addEventListener('input', (event) => {
            const slider = event.target.closest('input[data-camslider]');
            if (!slider || !this.shotCameraInfo) return;
            const value = parseFloat(slider.value);
            const cam = normalizeCamera(this.shotCameraInfo);
            const key = slider.dataset.camslider;
            if (key === 'fov') cam.fov = value;
            else if (key === 'eyeY') cam.eye.y = value;
            else if (key === 'targetY') cam.target.y = value;
            else if (key === 'targetZ') cam.target.z = value;
            else if (key === 'targetX') cam.target.x = value;
            this._applyShotCamera(cam);
        });
        this.el.camctl.addEventListener('change', (event) => {
            if (event.target.closest('input[data-camslider]')) this._scheduleSaveCamera();
        });
        this.el.camctl.addEventListener('click', (event) => {
            const btn = event.target.closest('[data-campreset]');
            if (!btn || !this.shotCameraInfo) return;
            const preset = CAMERA_PRESETS.find((p) => p.id === btn.dataset.campreset);
            if (!preset) return;
            const focal = this.orbit.target || new this.THREE.Vector3(0, 0.8, 0);
            const cam = applyCameraPreset(preset, focal, this._contentRadius || 4.5);
            if (cam) this._applyShotCamera(cam, { commit: true });
        });
    }

    // ---- 机位编辑：对话输入条 ----

    _bindChatBar() {
        this.el.chatSend.addEventListener('click', () => this._sendCameraChat());
        this.el.chatInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                this._sendCameraChat();
            }
        });
    }

    async _sendCameraChat() {
        if (this.camBusy || !this.shotCameraInfo) return;
        const message = (this.el.chatInput.value || '').trim();
        if (!message) return;
        const llm = resolveSelectedLlmModel();
        const model = typeof llm === 'string' ? llm : ((llm && (llm.model || llm.name)) || '');
        const modelId = typeof llm === 'object' ? (llm && (llm.model_id || llm.id)) : null;
        const vendorId = typeof llm === 'object' ? (llm && llm.vendor_id) : null;
        if (!model || modelId == null) {
            showToast('请先在故事板顶部选择对话模型', 'error');
            return;
        }
        const preview = this.previews[this.index];
        this.camBusy = true;
        this.el.chatSend.disabled = true;
        this.el.chatInput.disabled = true;
        this.el.chatSend.textContent = '思考中…';
        this._showChatNote('正在根据指令计算新机位…', 'info');
        try {
            const result = await cameraChat(preview.scene_id, {
                message,
                current_camera: this.shotCameraInfo,
                entities: this._collectEntities(),
                model,
                model_id: modelId,
                vendor_id: vendorId,
            });
            // 服务端返回扁平结构 {success, eye, target, fov, reason}；兼容嵌套 camera:{} 形态
            const cam = result && (result.camera || result);
            if (result && result.success && cam && cam.eye && cam.target) {
                this._applyShotCamera({ eye: cam.eye, target: cam.target, fov: cam.fov }, { commit: true });
                this._showChatNote(result.reason ? `✓ ${result.reason}` : '✓ 机位已更新', 'ok');
                this.el.chatInput.value = '';
            } else {
                this._showChatNote((result && result.error) || '机位调整失败，请重试', 'error');
            }
        } catch (error) {
            this._showChatNote(error.message || '机位调整失败，请重试', 'error');
        } finally {
            this.camBusy = false;
            this.el.chatSend.disabled = false;
            this.el.chatInput.disabled = false;
            this.el.chatSend.textContent = '发送';
        }
    }

    _collectEntities() {
        const ctx = this.replayCtx;
        if (!ctx) return [];
        const entities = [];
        const deg = (rad) => Math.round((rad * 180) / Math.PI);
        for (const [name, group] of Object.entries(ctx.actors || {})) {
            entities.push({ name, kind: 'actor', x: group.position.x, z: group.position.z, facing: deg(group.rotation.y) });
        }
        for (const [name, group] of Object.entries(ctx.props || {})) {
            entities.push({ name, kind: 'prop', x: group.position.x, z: group.position.z });
        }
        for (const [name, mesh] of Object.entries(ctx.stage || {})) {
            entities.push({ name, kind: 'stage', x: mesh.position.x, z: mesh.position.z });
        }
        return entities;
    }

    _showChatNote(text, kind) {
        this.el.chatNote.hidden = false;
        this.el.chatNote.textContent = text;
        this.el.chatNote.className = `spatial3d-chat-note is-${kind}`;
        clearTimeout(this._chatNoteTimer);
        if (kind !== 'error') {
            this._chatNoteTimer = setTimeout(() => { this.el.chatNote.hidden = true; }, 4000);
        }
    }

    // ---- 机位编辑：应用 / gizmo / 保存 ----

    /** 空镜诊断：机位视锥内没有任何角色时给出提示（LLM 产出机位与站位矛盾的常见症状）。 */
    _computeCameraDiag() {
        if (!this.replayCtx || !this.shotCameraInfo) return null;
        const actorList = Object.values(this.replayCtx.actors).map((g) => ({ x: g.position.x, z: g.position.z }));
        if (!actorList.length) return null;
        const seen = cameraSeesActors(this.shotCameraInfo, actorList, previewAspect());
        if (seen.visible) return null;
        const t = this.shotCameraInfo.target;
        return `机位视野内无角色（注视点约 (${t.x.toFixed(2)}, ${t.y.toFixed(2)}, ${t.z.toFixed(2)})，所有角色均在视锥外），镜头画面将为空景；可调整机位`;
    }

    _refreshDiagnostics() {
        this._cameraDiag = this._computeCameraDiag();
        this.el.diagnostics.innerHTML = diagnosticsHtml(this.previews[this.index], this.replayCtx, this._cameraDiag);
        // 角标同步（含空镜诊断计数）
        const preview = this.previews[this.index];
        const summary = preview.diagnostic_summary || { errors: 0, warnings: 0 };
        const totalWarnings = summary.warnings + (this._cameraDiag ? 1 : 0);
        const badge = this.el.badge;
        if (summary.errors || totalWarnings) {
            badge.hidden = false;
            badge.textContent = summary.errors ? `矛盾 ${summary.errors}` : `提示 ${totalWarnings}`;
            badge.className = `spatial3d-diag-badge ${summary.errors ? 'has-error' : 'has-warning'}`;
        } else {
            badge.hidden = true;
        }
    }

    /** 应用新机位到本镜相机 + gizmo + 侧栏显示；commit=true 时调度保存。 */
    _applyShotCamera(rawCam, { commit = false } = {}) {
        if (!this.shotCamera) return;
        const cam = clampCamera(rawCam);
        this.shotCameraInfo = cam;
        this.shotCamera.fov = cam.fov;
        this.shotCamera.position.set(cam.eye.x, cam.eye.y, cam.eye.z);
        this.shotCamera.lookAt(cam.target.x, cam.target.y, cam.target.z);
        this.shotCamera.updateProjectionMatrix();
        this._rebuildGizmo();
        this._syncCamSliders();
        this._refreshCodeSection();
        this._refreshDiagnostics();
        if (commit) this._scheduleSaveCamera();
    }

    _rebuildGizmo() {
        if (!this.worldGroup || !this.shotCameraInfo) return;
        if (this.gizmoGroup) {
            this.worldGroup.remove(this.gizmoGroup);
            this._disposeObject(this.gizmoGroup);
        }
        this.gizmoGroup = makeCameraGizmoFromInfo(this.THREE, this.shotCameraInfo, previewAspect());
        this.worldGroup.add(this.gizmoGroup);
    }

    _syncCamSliders() {
        if (this.el.camctl.hidden || !this.shotCameraInfo) return;
        const cam = this.shotCameraInfo;
        const values = {
            fov: Math.round(cam.fov),
            eyeY: cam.eye.y,
            targetY: cam.target.y,
            targetZ: cam.target.z,
            targetX: cam.target.x,
        };
        for (const [key, value] of Object.entries(values)) {
            const slider = this.el.camctl.querySelector(`input[data-camslider="${key}"]`);
            if (slider) slider.value = value;
            const label = this.el.camctl.querySelector(`[data-camslider-val="${key}"]`);
            if (label) label.textContent = Math.round(value * 100) / 100;
        }
    }

    _refreshCodeSection() {
        if (this.el.code.hidden) return;
        const preview = this.previews[this.index];
        const { chainStart = this.index, chainLength = 1 } = this._chainInfo || {};
        this.el.code.innerHTML = codeHtml(preview, chainStart, chainLength);
    }

    _scheduleSaveCamera() {
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => {
            this._saveTimer = 0;
            this._saveCameraNow();
        }, 600);
    }

    /** 切镜 / 关闭前把挂起的机位修改立即保存（防串镜）。 */
    _flushSaveCamera() {
        if (!this._saveTimer) return;
        clearTimeout(this._saveTimer);
        this._saveTimer = 0;
        this._saveCameraNow();
    }

    async _saveCameraNow() {
        const preview = this.previews[this.index];
        if (!preview || !isCodePreview(preview) || !this.shotCameraInfo) return;
        const sceneId = preview.scene_id;
        const oldCode = preview.three_scene.code || '';
        const newCode = rewriteSetCamera(oldCode, this.shotCameraInfo);
        if (newCode === oldCode) return;
        const scene = state.scenes.find((item) => item.id === sceneId);
        if (!scene || !scene._fullPrompt) {
            showToast('机位保存失败：分镜数据缺失', 'error');
            return;
        }
        const payload = { ...scene._fullPrompt, three_scene_code: newCode };
        preview.three_scene.code = newCode;
        try {
            await updateScenePrompt(sceneId, payload);
            scene._fullPrompt = payload;
            this._refreshCodeSection(); // 代码区显示与落库后的 setCamera 行保持一致
        } catch (error) {
            // 回滚缓存，保持与库一致；用户可重试
            preview.three_scene.code = oldCode;
            this._refreshCodeSection();
            showToast(error.message || '机位保存失败', 'error');
        }
    }

    // ---- gizmo 拾取 ----

    _ndcFromEvent(event) {
        const rect = this.renderer.domElement.getBoundingClientRect();
        return new this.THREE.Vector2(
            ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1,
            -((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1,
        );
    }

    _pickGizmoKind(event) {
        if (!this.gizmoGroup) return null;
        const raycaster = new this.THREE.Raycaster();
        raycaster.setFromCamera(this._ndcFromEvent(event), this.camera);
        const hits = raycaster.intersectObject(this.gizmoGroup, true);
        for (const hit of hits) {
            if (hit.object && hit.object.userData && hit.object.userData.dragKind) {
                return hit.object.userData.dragKind;
            }
        }
        return null;
    }

    _resize() {
        const rect = this.el.viewport.getBoundingClientRect();
        const width = Math.max(rect.width, 1);
        const height = Math.max(rect.height, 1);
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    }

    _animate() {
        this.rafId = requestAnimationFrame(() => this._animate());
        const rect = this.el.viewport.getBoundingClientRect();
        const width = Math.max(rect.width, 1);
        const height = Math.max(rect.height, 1);

        this.renderer.setScissorTest(false);
        this.renderer.setViewport(0, 0, width, height);
        this.renderer.clear();
        const { theta, phi, radius } = this.orbit;
        const target = this.orbit.target || new this.THREE.Vector3(0, 0.8, 0);
        this.camera.position.set(
            target.x + radius * Math.sin(phi) * Math.sin(theta),
            target.y + radius * Math.cos(phi),
            target.z + radius * Math.sin(phi) * Math.cos(theta),
        );
        this.camera.lookAt(target);
        this.renderer.render(this.scene, this.camera);

        // 镜头视角画中画：用本镜 setCamera 的相机从机位看向场景
        // （画幅跟随故事板 workflowRatio：9:16 竖屏故事板 PiP 亦为竖屏）
        if (this.shotCamera) {
            const pipW = Math.max(Math.round(width * 0.3), 120);
            const pipH = Math.round(pipW / previewAspect());
            const margin = 12;
            this.shotCamera.aspect = pipW / pipH;
            this.shotCamera.updateProjectionMatrix();
            this.renderer.setClearColor(0x101826, 0.92);
            this.renderer.setScissorTest(true);
            this.renderer.setViewport(width - pipW - margin, margin, pipW, pipH);
            this.renderer.setScissor(width - pipW - margin, margin, pipW, pipH);
            this.renderer.clear(true, true, false);
            this.renderer.render(this.scene, this.shotCamera);
            this.renderer.setScissorTest(false);
            this.renderer.setClearColor(0x000000, 0);
            this.renderer.setViewport(0, 0, width, height);
        }
    }

    _disposeObject(obj) {
        obj.traverse((node) => {
            if (node.geometry) node.geometry.dispose();
            const materials = Array.isArray(node.material) ? node.material : [node.material];
            for (const material of materials) {
                if (!material) continue;
                if (material.map) material.map.dispose();
                material.dispose();
            }
        });
    }

    show(index) {
        const total = this.previews.length;
        if (!total) return;
        // 切镜前先保存上一镜挂起的机位修改（保存按 this.index 定位，必须先落盘）
        this._flushSaveCamera();
        this.index = (index + total) % total;
        const preview = this.previews[this.index];

        if (this.worldGroup) {
            this._disposeObject(this.worldGroup);
            this.scene.remove(this.worldGroup);
        }
        this.shotCamera = null;
        this.shotCameraInfo = null;
        this.replayCtx = null;
        this.gizmoGroup = null;
        this._chainInfo = null;

        let replayCtx = null;
        let chainStart = this.index;
        let chainLength = 1;
        if (isCodePreview(preview)) {
            // three.js 代码方案：重放序列内 startScene → 本镜的代码链
            const replay = replayToIndex(this.THREE, this.previews, this.index);
            replayCtx = replay.ctx;
            chainStart = replay.chainStart;
            chainLength = replay.chainLength;
            this.worldGroup = replayCtx.root;
            this.replayCtx = replayCtx;
            this._chainInfo = { chainStart, chainLength };
            this.shotCamera = replayCtx.shotCamera;
            this.shotCameraInfo = normalizeCamera(replayCtx.cameraInfo);
            this.gizmoGroup = makeCameraGizmoFromInfo(this.THREE, this.shotCameraInfo, previewAspect());
            this.worldGroup.add(this.gizmoGroup);
        } else {
            this.worldGroup = buildWorldGroup(this.THREE, preview.three_scene);
        }
        this.scene.add(this.worldGroup);

        // 观察焦点：取实体/机位的包围盒中心
        const box = new this.THREE.Box3().setFromObject(this.worldGroup);
        const center = box.isEmpty() ? new this.THREE.Vector3(0, 0.8, 0) : box.getCenter(new this.THREE.Vector3());
        const size = box.isEmpty() ? 4 : box.getSize(new this.THREE.Vector3()).length();
        this.orbit.target = center;
        this.orbit.radius = Math.min(Math.max(size * 1.1, 3.5), 22);
        this._contentRadius = Math.min(Math.max(size * 0.35, 2.2), 12);

        this.el.title.textContent = `${preview.title || '分镜'}`;
        // 空镜诊断（_refreshDiagnostics 内计算并渲染，含角标）
        this._cameraDiag = null;

        const summary = preview.diagnostic_summary || { errors: 0, warnings: 0 };
        const totalWarnings = summary.warnings + (this._cameraDiag ? 1 : 0);
        const badge = this.el.badge;
        if (summary.errors || totalWarnings) {
            badge.hidden = false;
            badge.textContent = summary.errors ? `矛盾 ${summary.errors}` : `提示 ${totalWarnings}`;
            badge.className = `spatial3d-diag-badge ${summary.errors ? 'has-error' : 'has-warning'}`;
        } else {
            badge.hidden = true;
        }
        this.el.pos.textContent = `${this.index + 1} / ${total}`;
        this.el.prev.disabled = total <= 1;
        this.el.next.disabled = total <= 1;
        this.el.entities.innerHTML = entitiesHtml(preview, replayCtx);
        if (isCodePreview(preview)) {
            this.el.code.hidden = false;
            this.el.code.innerHTML = codeHtml(preview, chainStart, chainLength, total);
        } else {
            this.el.code.hidden = true;
        }
        this.el.diagnostics.innerHTML = diagnosticsHtml(preview, replayCtx, this._computeCameraDiag());

        // 机位编辑（手动 + 对话）仅代码方案分镜可用
        const editable = isCodePreview(preview) && !!this.shotCameraInfo;
        this.el.camctl.hidden = !editable;
        this.el.chat.hidden = !editable;
        if (editable) {
            this.el.camctl.innerHTML = camControlHtml(this.shotCameraInfo);
            this._syncCamSliders();
        }
        this.el.chatNote.hidden = true;
        // PiP 边框与实际渲染画幅一致（9:16 竖屏故事板 → 竖长条画中画）
        const ar = previewAspect();
        this.el.pip.style.aspectRatio = String(ar);
        this.el.pip.hidden = !this.shotCamera;
        if (this.el.loading) this.el.loading.hidden = true;
    }

    destroy() {
        if (activePreview !== this) return;
        activePreview = null;
        // 关闭前落盘挂起的机位修改（fire-and-forget，请求自身处理失败提示）
        this._flushSaveCamera();
        clearTimeout(this._chatNoteTimer);
        cancelAnimationFrame(this.rafId);
        document.removeEventListener('keydown', this._onKey);
        window.removeEventListener('mousemove', this._onMove);
        window.removeEventListener('mouseup', this._onUp);
        window.removeEventListener('resize', this._onResize);
        this.overlay.removeEventListener('click', this._onOverlayClick);
        if (this.worldGroup) this._disposeObject(this.worldGroup);
        this.renderer.dispose();
        this.overlay.remove();
    }
}

/** 打开分镜 3D 空间预览（入口：分镜卡片「3D 空间」按钮）。 */
export async function openSpatial3dPreview(sceneId) {
    if (activePreview) return;
    const scene = state.scenes.find((item) => item.id === sceneId);
    if (!scene || !state.storyboardId) return;

    let previews;
    try {
        previews = await fetchSpatialPreviews(state.storyboardId);
    } catch (error) {
        showToast(error.message || '获取空间预览失败', 'error');
        return;
    }
    if (!previews.length) {
        showToast('当前故事板没有分镜携带空间数据（需效果模式拆分）', 'error');
        return;
    }
    const startIndex = Math.max(0, previews.findIndex((item) => item.scene_id === sceneId));
    try {
        const THREE = await loadThree();
        activePreview = new Spatial3dSession(THREE, previews, startIndex);
    } catch (error) {
        showToast(error.message || '3D 预览初始化失败', 'error');
    }
}
