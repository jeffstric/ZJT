/**
 * 分镜 3D 空间布局预览（three.js）。
 *
 * 空间表达载体是 LLM 直出的 three.js 场景代码（每镜 three_scene_code）：
 * - 空间序列首镜以 startScene(...) 构建极简空间（场景体块 + 角色站位），
 *   空间关系保持的后续镜基于上一镜增量调整（moveActor 人物运动等），
 *   每镜必须 setCamera(...) 确定镜头位置；
 * - 本模块把序列内 startScene 到当前镜的代码按顺序在沙箱内重放执行，
 *   得到该镜的完整空间状态后渲染，并提供「镜头视角」画中画取景器；
 * - 存量分镜只有结构化 spatial_layout（旧 JSON 方案）时回退确定性渲染。
 *
 * 代码在 Function 作用域沙箱内执行：只注入 THREE / scene / camera /
 * actors / props / stage 与构建 helper，不暴露 window/document。
 * three.min.js（r128 UMD）懒加载；弹窗 DOM 自管理，关闭时完整 dispose。
 */
import state from './state.js';
import { getSpatialPreviews } from './api.js';
import { showToast } from './utils.js';

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
 * 创建一次重放会话：root 承载世界对象，registries 是暴露给代码的
 * actors/props/stage 对象表，shotCamera 是本镜相机（画中画取景器使用）。
 * helper 集合与 LLM prompt 契约（llm/script_parser.py THREE_SCENE_CODE_REQUIREMENTS）
 * 一一对应，两端需同步修改。
 */
function createReplayContext(THREE) {
    const ctx = {
        THREE,
        root: new THREE.Group(),
        actors: {},
        props: {},
        stage: {},
        shotCamera: new THREE.PerspectiveCamera(50, 16 / 9, 0.05, 200),
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
            const group = new THREE.Group();
            const body = new THREE.Mesh(
                new THREE.CylinderGeometry(0.16, 0.2, 0.9, 16),
                new THREE.MeshLambertMaterial({ color }),
            );
            body.position.y = 0.53;
            const head = new THREE.Mesh(
                new THREE.SphereGeometry(0.15, 18, 14),
                new THREE.MeshLambertMaterial({ color }),
            );
            head.position.y = 1.14;
            const nose = new THREE.Mesh(
                new THREE.ConeGeometry(0.05, 0.16, 8),
                new THREE.MeshBasicMaterial({ color: 0xf76f5e }),
            );
            nose.rotation.x = Math.PI / 2;
            nose.position.set(0, 1.14, 0.16);
            const label = makeLabel(THREE, String(name));
            label.position.y = 1.56;
            group.add(body, head, nose, label);
            group.position.set(x, 0, z);
            if (options.facing != null) group.rotation.y = Number(options.facing) * Math.PI / 180;
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
    const { ctx, helpers } = createReplayContext(THREE);
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

/** 机位视锥 + 朝向箭头（代码方案：米制坐标，直接使用）。 */
function makeCameraGizmoFromInfo(THREE, cameraInfo) {
    const group = new THREE.Group();
    const { eye, target } = cameraInfo;
    if (!eye || !target) return group;

    const mat = new THREE.LineBasicMaterial({ color: COLORS.camera });
    const fovRad = ((cameraInfo.fov || 50) * Math.PI) / 180;
    const dist = Math.hypot(target.x - eye.x, target.y - eye.y, target.z - eye.z) || 1;
    const halfH = Math.tan(fovRad / 2) * dist;
    const halfW = halfH * 16 / 9;

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
    group.add(camBody);

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
    });
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
                </div>
                <aside class="spatial3d-side">
                    <section class="spatial3d-section" data-spatial3d-entities></section>
                    <section class="spatial3d-section" data-spatial3d-code hidden></section>
                    <section class="spatial3d-section" data-spatial3d-diagnostics></section>
                    <section class="spatial3d-legend">
                        <span><i style="background:#4f8ef7"></i>角色</span>
                        <span><i style="background:#34c38f"></i>道具</span>
                        <span><i style="background:#9aa7b8"></i>场景体块</span>
                        <span><i style="background:#f76f5e"></i>机位</span>
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

function diagnosticsHtml(preview, replayCtx) {
    const diags = [...(preview.three_scene && preview.three_scene.diagnostics) || []];
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

class Spatial3dSession {
    constructor(THREE, previews, startIndex) {
        this.THREE = THREE;
        this.previews = previews;
        this.index = startIndex;
        this.rafId = 0;
        this.orbit = { theta: 0.7, phi: 1.05, radius: 7.5, target: null };
        this.dragging = null;
        this.worldGroup = null;
        this.shotCamera = null;   // 代码方案：本镜相机（画中画）

        document.body.insertAdjacentHTML('beforeend', previewShellHtml());
        this.overlay = document.querySelector('[data-spatial3d-overlay]');
        this.el = {
            title: this.overlay.querySelector('[data-spatial3d-scene-title]'),
            badge: this.overlay.querySelector('[data-spatial3d-diag-badge]'),
            viewport: this.overlay.querySelector('[data-spatial3d-viewport]'),
            loading: this.overlay.querySelector('[data-spatial3d-loading]'),
            pip: this.overlay.querySelector('[data-spatial3d-pip]'),
            pos: this.overlay.querySelector('[data-spatial3d-pos]'),
            entities: this.overlay.querySelector('[data-spatial3d-entities]'),
            code: this.overlay.querySelector('[data-spatial3d-code]'),
            diagnostics: this.overlay.querySelector('[data-spatial3d-diagnostics]'),
            prev: this.overlay.querySelector('[data-spatial3d-prev]'),
            next: this.overlay.querySelector('[data-spatial3d-next]'),
            close: this.overlay.querySelector('[data-spatial3d-close]'),
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
            if (event.key === 'Escape') this.destroy();
            if (event.key === 'ArrowLeft') this.show(this.index - 1);
            if (event.key === 'ArrowRight') this.show(this.index + 1);
        };
        document.addEventListener('keydown', this._onKey);
        this.el.prev.addEventListener('click', () => this.show(this.index - 1));
        this.el.next.addEventListener('click', () => this.show(this.index + 1));

        const dom = this.renderer.domElement;
        this._onDown = (event) => {
            this.dragging = {
                mode: event.button === 2 ? 'pan' : 'orbit',
                x: event.clientX, y: event.clientY,
            };
            event.preventDefault();
        };
        this._onMove = (event) => {
            if (!this.dragging) return;
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
        this._onUp = () => { this.dragging = null; };
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

        this._onResize = () => this._resize();
        window.addEventListener('resize', this._onResize);
        this._resize();
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
        if (this.shotCamera) {
            const pipW = Math.max(Math.round(width * 0.3), 120);
            const pipH = Math.round(pipW * 9 / 16);
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
        this.index = (index + total) % total;
        const preview = this.previews[this.index];

        if (this.worldGroup) {
            this._disposeObject(this.worldGroup);
            this.scene.remove(this.worldGroup);
        }
        this.shotCamera = null;

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
            this.worldGroup.add(makeCameraGizmoFromInfo(this.THREE, replayCtx.cameraInfo));
            this.shotCamera = replayCtx.shotCamera;
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

        this.el.title.textContent = `${preview.title || '分镜'}`;
        const summary = preview.diagnostic_summary || { errors: 0, warnings: 0 };
        const badge = this.el.badge;
        if (summary.errors || summary.warnings) {
            badge.hidden = false;
            badge.textContent = summary.errors ? `矛盾 ${summary.errors}` : `提示 ${summary.warnings}`;
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
        this.el.diagnostics.innerHTML = diagnosticsHtml(preview, replayCtx);
        this.el.pip.hidden = !this.shotCamera;
        if (this.el.loading) this.el.loading.hidden = true;
    }

    destroy() {
        if (activePreview !== this) return;
        activePreview = null;
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
