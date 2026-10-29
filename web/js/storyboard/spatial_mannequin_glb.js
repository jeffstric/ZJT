/**
 * 分镜 3D 空间预览的 GLB 人偶（与工作流导演台同款形象）。
 *
 * 导演台（director_stage_editor.js buildGlbPuppetRig）用 male_base_mesh.glb
 * 蒙皮人台替换了程序化人偶；本模块把同一形象移植到故事板 3D 预览：
 * SkeletonUtils.clone 共享模板 → 换染色树脂材质（r128 需显式 skinning）→
 * 归一化（面向 +Z、身高 1.75m、脚底贴地、水平居中）→ 上臂从 T-pose 旋成
 * 立正垂臂（与导演台同一目标向量）。预览人偶是纯静态站姿，不需要导演台
 * 的关节组重挂与头骨手术。
 *
 * 模板加载幂等且自管理依赖脚本（three.min.js → GLTFLoader/SkeletonUtils
 * → GLB），失败返回 null，调用方回退程序化人偶（buildMannequin）。
 *
 * dispose 契约：克隆实例共享模板 geometry（userData.isGlbMannequin 标记），
 * 销毁时只 dispose 每偶独立的材质与贴图，禁止 dispose 共享 geometry。
 */
import { loadThree } from './spatial_3d_preview.js';

const GLB_URL = '/assets/puppet/male_base_mesh.glb';
const GLTF_LOADER_SRC = `/assets/vendor/three-examples/loaders/GLTFLoader.js${window.__STATIC_VERSION ? `?v=${window.__STATIC_VERSION}` : ''}`;
const SKELETON_UTILS_SRC = `/assets/vendor/three-examples/utils/SkeletonUtils.js${window.__STATIC_VERSION ? `?v=${window.__STATIC_VERSION}` : ''}`;

// 与导演台 buildGlbPuppetRig 一致：身高 1.75m，标签挂在头顶上方
export const GLB_MANNEQUIN_HEIGHT = 1.75;
export const GLB_MANNEQUIN_LABEL_Y = GLB_MANNEQUIN_HEIGHT + 0.12;
// 导演台立正姿态的目标方向：垂直向下微外张（面向 +Z 时左臂外侧为 +X）
const ARM_TARGET_Z_OUT = 0.07;

// ============ 模板加载（幂等单例） ============

let templatePromise = null;
let readyTemplate = null;   // 就绪后同步可读（沙箱 makeActor 无法 await）

/**
 * 同步获取已就绪模板；未就绪/失败返回 null。
 * 必须先调用过 ensureMannequinTemplate()（弹窗/快照链路入口都会调）。
 */
export function getReadyMannequinTemplate() {
    return readyTemplate;
}

function injectScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error(`脚本加载失败: ${src}`));
        document.head.appendChild(script);
    });
}

async function loadTemplateOnce() {
    try {
        const THREE = await loadThree();
        if (!window.THREE.GLTFLoader) await injectScript(GLTF_LOADER_SRC);
        if (!window.THREE.SkeletonUtils) await injectScript(SKELETON_UTILS_SRC);
        if (!window.THREE.GLTFLoader || !window.THREE.SkeletonUtils) return null;
        const gltf = await new Promise((resolve, reject) => {
            new window.THREE.GLTFLoader().load(GLB_URL, resolve, undefined, reject);
        });
        if (!gltf || !gltf.scene) return null;
        readyTemplate = { THREE, gltf };
        return readyTemplate;
    } catch (error) {
        console.warn('[spatial-mannequin] GLB 人偶模板加载失败，回退程序化人偶:', error);
        return null;
    }
}

/**
 * 确保人偶模板就绪，返回 { THREE, gltf }；任何一环失败返回 null
 * （调用方回退程序化人偶，不阻塞预览）。多次调用共享同一次加载；
 * 失败后允许下次调用重新加载（临时文件缺失等场景可自愈）。
 */
export function ensureMannequinTemplate() {
    if (!templatePromise) {
        templatePromise = loadTemplateOnce().then((result) => {
            // 失败（null）不永久缓存：清空单例让下一次调用重试
            if (!result) templatePromise = null;
            return result;
        });
    }
    return templatePromise;
}

// ============ 人偶构建（静态立正） ============

/** 染色树脂材质（与导演台 createResinMaterials 的 body 同参数，无贴图简版）。 */
function makeResinMaterial(THREE, colorHex) {
    return new THREE.MeshPhysicalMaterial({
        color: new THREE.Color(colorHex).convertSRGBToLinear(),
        roughness: 0.56,
        metalness: 0,
        clearcoat: 0.16,
        clearcoatRoughness: 0.72,
        envMapIntensity: 0.65,
    });
}

/**
 * 用 GLB 模板构建一个静态立正人偶 Group。
 * 返回带 userData.isGlbMannequin=true 的 Group（脚底 y=0，label 挂头顶上方）。
 * 模板未就绪时抛错（调用方负责回退）。
 */
export function buildGlbMannequin(template, { color = 0x4f8ef7, name = '', facing = 0, makeLabel = null } = {}) {
    const { THREE, gltf } = template;
    if (!THREE.SkeletonUtils || !gltf.scene) throw new Error('GLB 人偶模板不完整');

    const mat = makeResinMaterial(THREE, color);
    // r128 蒙皮由 material.skinning 开关控制，自定义材质必须显式打开
    mat.skinning = true;

    const model = THREE.SkeletonUtils.clone(gltf.scene);
    model.updateMatrixWorld(true);
    let skinned = null;
    model.traverse((o) => { if (o.isSkinnedMesh) skinned = o; });
    if (!skinned) throw new Error('male_base_mesh.glb 缺少 SkinnedMesh');
    skinned.material = mat;
    skinned.frustumCulled = false;
    skinned.castShadow = true;
    skinned.receiveShadow = true;

    // —— 归一化：面向 +Z（模型原面向 +X）、1.75m、脚底贴地、水平居中 ——
    const container = new THREE.Group();
    container.add(model);
    container.rotation.y = -Math.PI / 2;
    container.updateMatrixWorld(true);
    const b1 = new THREE.Box3().setFromObject(container);
    const rawH = b1.max.y - b1.min.y;
    const s = GLB_MANNEQUIN_HEIGHT / rawH;
    container.scale.set(s, s, s);
    container.updateMatrixWorld(true);
    const b2 = new THREE.Box3().setFromObject(container);
    container.position.set(
        -(b2.min.x + b2.max.x) / 2,
        -b2.min.y,
        -(b2.min.z + b2.max.z) / 2,
    );

    // —— 立正姿态：上臂从 T-pose 旋到体侧下垂（与导演台同一目标向量与算法） ——
    const findBone = (boneName) => {
        let found = null;
        model.traverse((o) => { if (o.isBone && o.name === boneName) found = o; });
        return found;
    };
    for (const suffix of ['L', 'R']) {
        const ua = findBone(`upper_arm${suffix}`);
        if (!ua) continue;
        ua.updateWorldMatrix(true, false);
        const pivot = new THREE.Vector3().setFromMatrixPosition(ua.matrixWorld);
        const forearm = ua.children[0];
        if (!forearm) continue;
        const dir = new THREE.Vector3().setFromMatrixPosition(forearm.matrixWorld).sub(pivot).normalize();
        const outSign = suffix === 'L' ? 1 : -1;
        const target = new THREE.Vector3(0, -1, ARM_TARGET_Z_OUT * outSign).normalize();
        const axis = new THREE.Vector3().crossVectors(dir, target);
        const axisLen = axis.length();
        const angle = Math.atan2(axisLen, dir.dot(target));
        if (axisLen > 1e-6 && angle > 1e-4) {
            axis.normalize();
            const world = new THREE.Matrix4()
                .makeTranslation(pivot.x, pivot.y, pivot.z)
                .multiply(new THREE.Matrix4().makeRotationAxis(axis, angle))
                .multiply(new THREE.Matrix4().makeTranslation(-pivot.x, -pivot.y, -pivot.z))
                .multiply(ua.matrixWorld);
            const local = new THREE.Matrix4().copy(ua.parent.matrixWorld).invert().multiply(world);
            local.decompose(ua.position, ua.quaternion, ua.scale);
        }
    }

    const group = new THREE.Group();
    group.add(container);
    group.rotation.y = (Number(facing) || 0) * Math.PI / 180;
    // 整棵子树打标记：预览销毁时 traverse 逐节点判断，共享模板 geometry
    // 一律不 dispose（只回收每偶独立的材质/贴图）
    group.traverse((o) => { o.userData.isGlbMannequin = true; });
    group.userData.mannequinMaterial = mat;

    if (typeof makeLabel === 'function') {
        const label = makeLabel(name);
        if (label) {
            label.position.y = GLB_MANNEQUIN_LABEL_Y;
            group.add(label);
        }
    }
    return group;
}
