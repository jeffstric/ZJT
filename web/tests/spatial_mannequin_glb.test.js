/**
 * GLB 人偶（spatial_mannequin_glb）单元测试。
 *
 * 与工作流导演台同款形象的移植层：
 * - 模板加载：幂等单例、就绪后同步可读、失败返回 null 且允许重试；
 * - buildGlbMannequin：克隆模板、染色树脂材质（r128 skinning 显式开）、
 *   归一化（-90° 转向、1.75m 缩放、脚底贴地）、上臂 T-pose→立正、
 *   整棵子树打 isGlbMannequin 标记（dispose 契约）、label 挂头顶上方；
 * - 接线：3D 预览 makeActor 优先 GLB 回退程序化、dispose 跳过共享
 *   geometry、弹窗/快照链路预载模板。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const loadThreeMock = vi.fn();
vi.mock('../js/storyboard/spatial_3d_preview.js', () => ({
  loadThree: (...args) => loadThreeMock(...args),
}));

const root = path.resolve(import.meta.dirname, '..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

// ============ 记录型 fake THREE（仅覆盖 buildGlbMannequin 用面） ============

function makeFakeThree() {
  class Vec3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
    setFromMatrixPosition(m) { const p = m.__position || { x: 0, y: 0, z: 0 }; return this.set(p.x, p.y, p.z); }
    sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this; }
    copy(v) { return this.set(v.x, v.y, v.z); }
    length() { return Math.hypot(this.x, this.y, this.z); }
    normalize() {
      const len = this.length();
      if (len > 1e-9) { this.x /= len; this.y /= len; this.z /= len; }
      return this;
    }
    dot(v) { return this.x * v.x + this.y * v.y + this.z * v.z; }
    crossVectors(a, b) {
      this.x = a.y * b.z - a.z * b.y;
      this.y = a.z * b.x - a.x * b.z;
      this.z = a.x * b.y - a.y * b.x;
      return this;
    }
  }
  class Mat4 {
    constructor() {
      this.__position = { x: 0, y: 0, z: 0 };
      this.__ops = [];
    }
    makeTranslation(x, y, z) { this.__ops.push(['makeTranslation', x, y, z]); return this; }
    makeRotationAxis(axis, angle) { this.__ops.push(['makeRotationAxis', axis, angle]); return this; }
    multiply(m) { this.__ops.push(['multiply', m]); return this; }
    copy(m) { this.__src = m; this.__ops.push(['copy', m]); return this; }
    invert() { this.__ops.push(['invert']); return this; }
    // 记录分解目标：断言「立正旋转写入了 ua.quaternion」
    decompose(position, quaternion, scale) {
      this.__ops.push(['decompose']);
      if (quaternion) quaternion.__written = true;
      if (position) { position.x = this.__position.x; position.y = this.__position.y; position.z = this.__position.z; }
    }
  }
  class Obj3d {
    constructor() {
      this.children = [];
      this.parent = null;
      this.userData = {};
      this.position = new Vec3();
      this.scale = new Vec3(1, 1, 1);
      this.rotation = { x: 0, y: 0, z: 0 };
      this.quaternion = {};
      this.matrixWorld = new Mat4();
    }
    add(child) {
      if (child.parent) {
        const at = child.parent.children.indexOf(child);
        if (at >= 0) child.parent.children.splice(at, 1);
      }
      child.parent = this;
      this.children.push(child);
      return this;
    }
    traverse(fn) {
      fn(this);
      for (const child of [...this.children]) child.traverse(fn);
    }
    updateMatrixWorld() {}
    updateWorldMatrix() {}
  }
  return {
    Vector3: Vec3,
    Matrix4: Mat4,
    Group: class extends Obj3d {},
    Bone: class extends Obj3d { constructor() { super(); this.isBone = true; } },
    Box3: class {
      setFromObject() { return { min: { x: -0.5, y: 0.1, z: -0.25 }, max: { x: 0.5, y: 2.1, z: 0.25 } }; }
    },
    Color: class { constructor(hex) { this.hex = hex; } convertSRGBToLinear() { return this; } },
    MeshPhysicalMaterial: class { constructor(params) { Object.assign(this, params); } },
    SkeletonUtils: {
      clone(source) {
        const cloneObj = (obj) => {
          const copy = new (obj.constructor)();
          // is* 类型标志 + 渲染属性随克隆复制（真实 SkeletonUtils.clone 语义）
          for (const key of Object.keys(obj)) {
            if (/^(is[A-Z]|name|material|geometry|frustumCulled)/.test(key)) copy[key] = obj[key];
          }
          // 绑定姿态矩阵跟随克隆（蒙皮骨骼的世界位置在立正计算中读取）
          copy.matrixWorld.__position = obj.matrixWorld.__position || { x: 0, y: 0, z: 0 };
          Object.assign(copy.userData, obj.userData);
          for (const child of obj.children) copy.add(cloneObj(child));
          return copy;
        };
        return cloneObj(source);
      },
    },
  };
}

/** 构造模板：scene 含 SkinnedMesh + 左右上臂/前臂骨骼（matrixWorld 可设位置）。 */
function makeTemplate(THREE, { withSkinned = true } = {}) {
  const scene = new THREE.Group();
  const skinned = new THREE.Group();
  skinned.isSkinnedMesh = !!withSkinned;
  skinned.material = { __original: true };
  skinned.geometry = { __shared: true };
  scene.add(skinned);

  const armPos = { L: [1, 0, 0], R: [-1, 0, 0] };
  for (const suffix of ['L', 'R']) {
    const ua = new THREE.Bone();
    ua.name = `upper_arm${suffix}`;
    ua.matrixWorld.__position = { x: armPos[suffix][0], y: armPos[suffix][1], z: armPos[suffix][2] };
    const forearm = new THREE.Bone();
    forearm.name = `forearm${suffix}`;
    // 前臂在肩外侧 +2X（T-pose 横举）
    forearm.matrixWorld.__position = { x: armPos[suffix][0] + (suffix === 'L' ? 2 : -2), y: 0, z: 0 };
    ua.add(forearm);
    scene.add(ua);
  }
  return { THREE, gltf: { scene } };
}

async function loadMod() {
  return await import('../js/storyboard/spatial_mannequin_glb.js');
}

beforeEach(() => {
  vi.resetModules();
  loadThreeMock.mockReset();
  delete window.THREE;
});

describe('ensureMannequinTemplate 模板加载', () => {
  function fakeWindowThree({ loaderFails = false } = {}) {
    let constructed = 0;
    window.THREE = {
      GLTFLoader: class {
        constructor() { constructed += 1; }
        load(url, onLoad, _progress, onError) {
          if (loaderFails) onError(new Error('glb 404'));
          else onLoad({ scene: { __gltfScene: true } });
        }
      },
      SkeletonUtils: { clone: (s) => s },
    };
    return { constructed: () => constructed };
  }

  it('加载成功返回模板且同步可读', async () => {
    const stats = fakeWindowThree();
    const mod = await loadMod();
    const template = await mod.ensureMannequinTemplate();
    expect(template).not.toBeNull();
    expect(template.gltf.scene.__gltfScene).toBe(true);
    expect(stats.constructed()).toBe(1);
    expect(mod.getReadyMannequinTemplate()).toBe(template);
  });

  it('并发调用共享同一次加载（GLTFLoader 只实例化一次）', async () => {
    const stats = fakeWindowThree();
    const mod = await loadMod();
    const [a, b] = await Promise.all([
      mod.ensureMannequinTemplate(),
      mod.ensureMannequinTemplate(),
    ]);
    expect(a).toBe(b);
    expect(stats.constructed()).toBe(1);
  });

  it('失败返回 null，且下次调用允许重试', async () => {
    let fails = true;
    let constructed = 0;
    window.THREE = {
      GLTFLoader: class {
        constructor() { constructed += 1; }
        load(url, onLoad, _p, onError) {
          if (fails) onError(new Error('network'));
          else onLoad({ scene: {} });
        }
      },
      SkeletonUtils: { clone: (s) => s },
    };
    const mod = await loadMod();
    await expect(mod.ensureMannequinTemplate()).resolves.toBeNull();
    expect(mod.getReadyMannequinTemplate()).toBeNull();
    // 失败不永久缓存：修复后重试成功
    fails = false;
    const template = await mod.ensureMannequinTemplate();
    expect(template).not.toBeNull();
    expect(constructed).toBe(2);
  });
});

describe('buildGlbMannequin 构建（记录型 fake THREE）', () => {
  it('克隆模板、染色蒙皮材质、归一化、立正、子树标记、label 位置', async () => {
    const mod = await loadMod();
    const THREE = makeFakeThree();
    const template = makeTemplate(THREE);
    const labels = [];
    const group = mod.buildGlbMannequin(template, {
      color: 0x123456,
      name: '李卫国',
      facing: 90,
      makeLabel: (text) => {
        const label = new THREE.Group();
        label.__isLabel = text;
        labels.push(label);
        return label;
      },
    });

    // facing 旋转与形象标记
    expect(group.rotation.y).toBeCloseTo(Math.PI / 2);
    expect(group.userData.isGlbMannequin).toBe(true);
    // 整棵子树（含 SkinnedMesh/Bone）都有 dispose 契约标记
    let marked = 0;
    group.traverse((o) => { if (o.userData.isGlbMannequin) marked += 1; });
    expect(marked).toBeGreaterThan(3);

    // SkinnedMesh：材质替换为染色蒙皮材质 + 关闭视锥剔除
    let skinned = null;
    group.traverse((o) => { if (o.isSkinnedMesh) skinned = o; });
    expect(skinned).not.toBeNull();
    expect(skinned.material.skinning).toBe(true);
    expect(skinned.material.color.hex).toBe(0x123456);
    expect(skinned.frustumCulled).toBe(false);
    // 共享 geometry 未被克隆替换（dispose 契约：模板几何体共享）
    expect(skinned.geometry.__shared).toBe(true);

    // 归一化容器：面向 +Z（-90°）、1.75m 缩放（rawH=2.0 → 0.875）、脚底贴地
    const container = group.children[0];
    expect(container.rotation.y).toBeCloseTo(-Math.PI / 2);
    expect(container.scale.y).toBeCloseTo(1.75 / 2.0);
    expect(container.position.y).toBeCloseTo(-0.1);

    // 立正姿态：双臂骨骼 quaternion 均被 decompose 写入
    let armCount = 0;
    group.traverse((o) => {
      if (o.isBone && /^upper_arm[LR]$/.test(o.name)) {
        armCount += 1;
        expect(o.quaternion.__written).toBe(true);
      }
    });
    expect(armCount).toBe(2);

    // label 挂头顶上方（1.75 + 0.12）
    expect(labels).toHaveLength(1);
    expect(labels[0].position.y).toBeCloseTo(1.87);
  });

  it('模板缺 SkinnedMesh 抛错（调用方回退程序化人偶）', async () => {
    const mod = await loadMod();
    const THREE = makeFakeThree();
    const template = makeTemplate(THREE, { withSkinned: false });
    expect(() => mod.buildGlbMannequin(template, {})).toThrow(/SkinnedMesh/);
  });

  it('不传 makeLabel 不挂标签也不抛错', async () => {
    const mod = await loadMod();
    const THREE = makeFakeThree();
    const group = mod.buildGlbMannequin(makeTemplate(THREE), {});
    expect(group.children).toHaveLength(1);
  });
});

describe('接线断言（3D 预览链路）', () => {
  const previewSrc = readSource('js/storyboard/spatial_3d_preview.js');

  it('预览 makeActor 优先 GLB 人偶，模板未就绪回退程序化', () => {
    expect(previewSrc).toContain("from './spatial_mannequin_glb.js'");
    expect(previewSrc).toContain('function buildPreviewMannequin');
    expect(previewSrc).toContain('getReadyMannequinTemplate()');
    expect(previewSrc).toContain('buildGlbMannequin(template,');
    expect(previewSrc).toContain('return buildMannequin(THREE, color, name, facing)');
    expect(previewSrc).toContain('const group = buildPreviewMannequin(THREE, color, String(name)');
  });

  it('dispose 跳过 GLB 共享 geometry（模板复用不可销毁）', () => {
    expect(previewSrc).toContain('!isGlbMannequin');
  });

  it('弹窗打开预载模板', () => {
    expect(previewSrc).toContain('await ensureMannequinTemplate()');
  });
});
