/**
 * 分镜 3D 预览「机位编辑」纯函数模块。
 *
 * three.js 代码（three_scene_code 的 setCamera 行）是机位唯一真源：
 * 手动拖拽 / 滑杆 / 预设 / 对话产出的新机位都经 rewriteSetCamera 写回
 * 本镜代码，再走 PUT /scene/{id}/prompt 保存（见
 * docs/storyboard/spatial_3d_preview_design.md §机位编辑）。
 *
 * 本模块不依赖 DOM / three.js，可被 vitest 直接 import 测试。
 */

// 与 services/storyboard_camera_chat.py 的 clamp 范围一致
export const CAMERA_LIMITS = {
    posAbsMax: 30,
    eyeYMin: 0.05,
    eyeYMax: 12,
    targetYMin: -2,
    targetYMax: 12,
    fovMin: 15,
    fovMax: 120,
    fovDefault: 50,
};

function toPoint(raw, defaultY) {
    const src = raw && typeof raw === 'object' ? raw : {};
    const out = { x: Number(src.x), y: Number(src.y), z: Number(src.z) };
    if (!Number.isFinite(out.x)) out.x = 0;
    if (!Number.isFinite(out.y)) out.y = defaultY;
    if (!Number.isFinite(out.z)) out.z = 0;
    return out;
}

/** 归一化机位对象：{eye:{x,y,z}, target:{x,y,z}, fov}，字段缺失给默认值。 */
export function normalizeCamera(raw) {
    const src = raw && typeof raw === 'object' ? raw : {};
    const fov = Number(src.fov);
    return {
        eye: toPoint(src.eye, 1.5),
        target: toPoint(src.target, 1.0),
        fov: Number.isFinite(fov) && fov > 0 ? fov : CAMERA_LIMITS.fovDefault,
    };
}

function clampNum(value, lo, hi) {
    return Math.min(Math.max(value, lo), hi);
}

/** 机位范围约束（与后端 parse_camera_json 的 clamp 一致）。 */
export function clampCamera(raw) {
    const cam = normalizeCamera(raw);
    const { posAbsMax, eyeYMin, eyeYMax, targetYMin, targetYMax, fovMin, fovMax } = CAMERA_LIMITS;
    const clampXZ = (p) => ({
        x: clampNum(p.x, -posAbsMax, posAbsMax),
        y: p.y,
        z: clampNum(p.z, -posAbsMax, posAbsMax),
    });
    return {
        eye: { ...clampXZ(cam.eye), y: clampNum(cam.eye.y, eyeYMin, eyeYMax) },
        target: { ...clampXZ(cam.target), y: clampNum(cam.target.y, targetYMin, targetYMax) },
        fov: clampNum(cam.fov, fovMin, fovMax),
    };
}

/**
 * 在代码中定位最后一个 setCamera(...) 调用。
 * 返回 {start, end, args}（start/end 为 "setCamera(" 与 ")" 的原文下标，
 * args 为解析出的数字参数数组）；无调用返回 null。
 */
export function findLastSetCameraCall(code) {
    const src = String(code || '');
    const nameRe = /(?<![A-Za-z0-9_$])setCamera\s*\(/g;
    let match;
    let last = null;
    while ((match = nameRe.exec(src)) !== null) {
        const argsStart = match.index + match[0].length;
        let depth = 1;
        let i = argsStart;
        for (; i < src.length && depth > 0; i++) {
            const ch = src[i];
            if (ch === '(') depth++;
            else if (ch === ')') depth--;
        }
        if (depth !== 0) continue; // 括号不配对，跳过
        // 循环结束时 i 指向 ")" 的下一个字符，closeIdx 才是 ")" 本身
        const closeIdx = i - 1;
        last = { start: match.index, callStart: argsStart, end: closeIdx, argsText: src.slice(argsStart, closeIdx) };
    }
    if (!last) return null;
    last.args = last.argsText
        .split(',')
        .map((part) => Number(part.trim()))
        .map((v) => (Number.isFinite(v) ? v : null));
    return last;
}

function fmtNum(value) {
    return String(Math.round(value * 100) / 100);
}

/**
 * 把新机位写回代码：替换最后一个 setCamera 的参数（保持每镜必须
 * setCamera 的契约）；代码中没有 setCamera 时在末尾追加一行。
 */
export function rewriteSetCamera(code, camera) {
    const src = String(code || '');
    const cam = clampCamera(camera);
    const fov = Math.round(cam.fov);
    const argsText = [
        fmtNum(cam.eye.x), fmtNum(cam.eye.y), fmtNum(cam.eye.z),
        fmtNum(cam.target.x), fmtNum(cam.target.y), fmtNum(cam.target.z),
        String(fov),
    ].join(', ');
    const call = findLastSetCameraCall(src);
    if (!call) {
        const trimmed = src.replace(/\s+$/, '');
        return `${trimmed}\nsetCamera(${argsText});\n`;
    }
    return src.slice(0, call.callStart) + argsText + src.slice(call.end);
}

/**
 * 预设机位（移植导演台 CAMERA_PRESETS 并适配任意焦点）：
 * dir 是焦点→机位的地面方向（未归一化的 [x,z]），dist 缺省用场景半径。
 */
export const CAMERA_PRESETS = [
    { id: 'eye_front', label: '正面·平视', fov: 35, dir: [0, 1], dist: null, eyeY: 1.5, targetY: 1.05 },
    { id: 'closeup_front', label: '正面·近景', fov: 32, dir: [0, 1], dist: 2.0, eyeY: 1.55, targetY: 1.5 },
    { id: 'wide_front', label: '正面·全景', fov: 40, dir: [0, 1], dist: null, eyeY: 1.7, targetY: 1.0 },
    { id: 'three_quarter_left', label: '3/4左侧', fov: 35, dir: [-0.7, 0.7], dist: null, eyeY: 1.5, targetY: 1.05 },
    { id: 'three_quarter_right', label: '3/4右侧', fov: 35, dir: [0.7, 0.7], dist: null, eyeY: 1.5, targetY: 1.05 },
    { id: 'side_left', label: '左侧', fov: 35, dir: [-1, 0.05], dist: null, eyeY: 1.45, targetY: 1.0 },
    { id: 'side_right', label: '右侧', fov: 35, dir: [1, 0.05], dist: null, eyeY: 1.45, targetY: 1.0 },
    { id: 'back', label: '背面', fov: 35, dir: [0, -1], dist: null, eyeY: 1.5, targetY: 1.05 },
    { id: 'low_angle', label: '仰拍', fov: 48, dir: [0.2, 0.95], dist: null, eyeY: 0.35, targetY: 1.7 },
    { id: 'high_angle', label: '俯拍', fov: 42, dir: [0.2, 0.85], dist: null, eyeY: 4.6, targetY: 0.9 },
    { id: 'top_down', label: '顶摄', fov: 45, dir: [0, 0.02], dist: null, eyeY: 7.5, targetY: 0 },
];

/**
 * 计算预设机位。focal：焦点世界坐标 {x,y,z}（通常取场景内容中心）；
 * radius：默认拍摄半径（米）。返回 clampCamera 后的机位对象。
 */
export function applyCameraPreset(preset, focal, radius = 4.5) {
    if (!preset || !Array.isArray(preset.dir)) return null;
    const center = toPoint(focal, 0.8);
    const dist = preset.dist != null ? preset.dist : Math.min(Math.max(radius, 2.2), 10);
    const len = Math.hypot(preset.dir[0], preset.dir[1]) || 1;
    const eye = {
        x: center.x + (preset.dir[0] / len) * dist,
        y: preset.eyeY,
        z: center.z + (preset.dir[1] / len) * dist,
    };
    const target = { x: center.x, y: preset.targetY, z: center.z };
    return clampCamera({ eye, target, fov: preset.fov });
}
