/** 导演台 PBR / 环境 / 灯光 / SSAO 渲染架构回归测试。 */

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const require = createRequire(import.meta.url);
const vendorFiles = [
  'shaders/CopyShader.js',
  'postprocessing/EffectComposer.js',
  'postprocessing/ShaderPass.js',
  'postprocessing/RenderPass.js',
  'math/SimplexNoise.js',
  'shaders/SSAOShader.js',
  'postprocessing/SSAOPass.js',
  'shaders/GammaCorrectionShader.js',
  'environments/RoomEnvironment.js',
  'geometries/RoundedBoxGeometry.js',
  'utils/BufferGeometryUtils.js'
];

function loadRendering() {
  const window = { THREE: require(path.join(root, 'web/assets/vendor/three.min.js')) };
  const context = { window, THREE: window.THREE, document: undefined, Image: undefined, console };
  vm.createContext(context);
  for (const file of vendorFiles) {
    vm.runInContext(fs.readFileSync(path.join(root, 'web/assets/vendor/three-examples', file), 'utf8'), context, { filename: file });
  }
  vm.runInContext(fs.readFileSync(path.join(root, 'web/js/director_stage_rendering.js'), 'utf8'), context, { filename: 'director_stage_rendering.js' });
  return { R: window.DirectorStageRendering, THREE: window.THREE };
}

function fakeRenderer(THREE) {
  return {
    capabilities: { isWebGL2: true, getMaxAnisotropy: () => 8 },
    extensions: { has: () => true },
    renderCount: 0,
    getSize: (v) => v.set(800, 600),
    getPixelRatio: () => 1,
    getRenderTarget: () => null,
    setRenderTarget: () => {},
    render: function () { this.renderCount++; }
  };
}

describe('导演台渲染：PBR 材质与几何工具', () => {
  it('分部位 MeshPhysicalMaterial、线性颜色、中性贴图与释放', () => {
    const { R, THREE } = loadRendering();
    const bundle = R.createResinMaterials('#3579c6', fakeRenderer(THREE));
    expect(bundle.body.isMeshPhysicalMaterial).toBe(true);
    expect(bundle.torso.isMeshPhysicalMaterial).toBe(true);
    expect(bundle.head.isMeshPhysicalMaterial).toBe(true);
    expect(bundle.body).not.toBe(bundle.torso);
    expect(bundle.torso).not.toBe(bundle.head);
    expect(bundle.body.roughness).toBe(0.56);
    expect(bundle.body.clearcoat).toBe(0.16);
    expect(bundle.body.clearcoatRoughness).toBe(0.72);
    expect(bundle.body.color.getHex()).toBe(new THREE.Color('#3579c6').convertSRGBToLinear().getHex());
    expect(bundle.body.normalMap.isDataTexture).toBe(true);
    expect(bundle.body.aoMap.isDataTexture).toBe(true);
    // 无 DOM 的测试环境不发起图片请求，仅使用中性 fallback。
    expect(bundle.textures).toHaveLength(2);

    const geometry = new THREE.BoxGeometry(1, 1, 1);
    R.ensureUv2(geometry);
    expect(geometry.attributes.uv2).toBeDefined();
    expect(bundle.dispose).not.toThrow();
  });

  it('RoundedBox / Lathe 胶囊 / 刚体合并保持正确结构', () => {
    const { R, THREE } = loadRendering();
    const rounded = R.roundedJoint(0.1, 0.2, 0.05, 0.02);
    expect(rounded instanceof THREE.RoundedBoxGeometry).toBe(true);
    expect(rounded.attributes.uv2).toBeDefined();

    const capsule = R.createCapsuleLathe(0.05, 0.2, 12);
    capsule.computeBoundingBox();
    expect(capsule.boundingBox.max.y - capsule.boundingBox.min.y).toBeCloseTo(0.3, 5);
    expect(capsule.attributes.uv2).toBeDefined();

    const material = new THREE.MeshStandardMaterial();
    const a = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material);
    const b = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material);
    b.position.x = 2;
    const merged = R.mergeRigidMeshes([a, b]);
    expect(merged).not.toBeNull();
    expect(merged.material).toBe(material);
    expect(merged.geometry.attributes.position.count).toBe(
      a.geometry.attributes.position.count + b.geometry.attributes.position.count
    );
  });
});

describe('导演台渲染：灯光、环境与后处理', () => {
  it('三点布光只有主光投影，Rim 使用 SpotLight', () => {
    const { R, THREE } = loadRendering();
    const scene = new THREE.Scene();
    const lights = R.createThreePointLights(scene);
    expect(lights.key.isDirectionalLight).toBe(true);
    expect(lights.key.castShadow).toBe(true);
    expect(lights.key.shadow.mapSize.x).toBe(2048);
    expect(lights.key.shadow.normalBias).toBe(0.025);
    expect(lights.fill.castShadow).toBe(false);
    expect(lights.rim.isSpotLight).toBe(true);
    expect(lights.rim.angle).toBe(0.5);
    expect(lights.rim.penumbra).toBe(0.85);
    expect(lights.hemi.intensity).toBe(0.18);
    expect(scene.children).toContain(lights.rim.target);
    lights.dispose();
    expect(scene.children).toHaveLength(0);
  });

  it('SSAO 预渲染走逐对象材质（蒙皮残影修复）', () => {
    const { R, THREE } = loadRendering();
    const renderer = fakeRenderer(THREE);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 4 / 3, 0.1, 100);
    const pipeline = R.createComposer(renderer, scene, camera, { pixelRatio: 1 });
    // 法线材质必须开 skinning，且 renderOverride 必须被补丁成逐网格换材质
    expect(pipeline.ssao.normalMaterial.skinning).toBe(true);
    expect(pipeline.ssao.renderOverride).not.toBe(THREE.SSAOPass.prototype.renderOverride);
    expect(pipeline.dispose).not.toThrow();
  });

  it('composer 使用 RenderPass → SSAOPass → GammaCorrection，并支持质量/FOV/尺寸同步', () => {
    const { R, THREE } = loadRendering();
    const renderer = fakeRenderer(THREE);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 4 / 3, 0.1, 100);
    const pipeline = R.createComposer(renderer, scene, camera, { pixelRatio: 1 });
    expect(pipeline.supported).toBe(true);
    expect(pipeline.composer.passes).toHaveLength(3);
    expect(pipeline.composer.passes[0] instanceof THREE.RenderPass).toBe(true);
    expect(pipeline.composer.passes[1] instanceof THREE.SSAOPass).toBe(true);
    expect(pipeline.composer.passes[2] instanceof THREE.ShaderPass).toBe(true);
    expect(pipeline.ssao.kernelRadius).toBe(0.18);
    expect(pipeline.ssao.minDistance).toBe(0.0008);
    expect(pipeline.ssao.maxDistance).toBe(0.025);
    expect(pipeline.ssao.beautyRenderTarget instanceof THREE.WebGLMultisampleRenderTarget).toBe(true);
    expect(pipeline.ssao.beautyRenderTarget.samples).toBe(4);
    expect(pipeline.ssao.ssaoMaterial.uniforms.tDiffuse.value).toBe(pipeline.ssao.beautyRenderTarget.texture);

    pipeline.setQuality(0.75);
    expect(pipeline.composer._pixelRatio).toBe(0.75);
    pipeline.setSize(1024, 768);
    expect(pipeline.composer.renderTarget1.width).toBe(768);
    expect(pipeline.composer.renderTarget1.height).toBe(576);
    camera.fov = 50;
    camera.updateProjectionMatrix();
    R.syncComposerCamera(pipeline.ssao, camera);
    expect(pipeline.ssao.ssaoMaterial.uniforms.cameraProjectionMatrix.value.equals(camera.projectionMatrix)).toBe(true);
    expect(pipeline.dispose).not.toThrow();
  });

  it('缺少深度纹理时回退原始 renderer', () => {
    const { R, THREE } = loadRendering();
    const renderer = fakeRenderer(THREE);
    renderer.capabilities.isWebGL2 = false;
    renderer.extensions.has = () => false;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const pipeline = R.createComposer(renderer, scene, camera, {});
    expect(pipeline.supported).toBe(false);
    pipeline.render();
    expect(renderer.renderCount).toBe(1);
  });

  it('场景材质与背景只做一次 sRGB→Linear 转换', () => {
    const { R, THREE } = loadRendering();
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x14161d);
    const material = new THREE.MeshStandardMaterial({ color: 0x3579c6 });
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(), material));
    R.prepareSceneColors(scene);
    const backgroundHex = scene.background.getHex();
    const materialHex = material.color.getHex();
    R.prepareSceneColors(scene);
    expect(scene.background.getHex()).toBe(backgroundHex);
    expect(material.color.getHex()).toBe(materialHex);
  });
});

describe('导演台渲染：驱动兼容性规避', () => {
  it('findFailedPrograms 只收集带 diagnostics 的失败程序', () => {
    const { R } = loadRendering();
    const renderer = {
      info: { programs: [
        { cacheKey: 'a' },
        { cacheKey: 'b', diagnostics: { runnable: false } },
        { cacheKey: 'c' },
        { cacheKey: 'd', diagnostics: { runnable: false } }
      ] }
    };
    const failed = R.findFailedPrograms([renderer, null]);
    expect(failed).toHaveLength(2);
    expect(failed[0].renderer).toBe(0);
    expect(failed[0].key).toBe('b');
    expect(failed[1].key).toBe('d');
  });

  it('detectDriverShaderRisk：仅 Windows 非 D3D11 后端判定为风险', () => {
    const threePath = path.join(root, 'web/assets/vendor/three.min.js');
    const moduleSrc = fs.readFileSync(path.join(root, 'web/js/director_stage_rendering.js'), 'utf8');
    function riskWith(agent, unmasked, extAvailable) {
      const THREE = require(threePath);
      const gl = {
        getExtension: () => (extAvailable === false ? null : { UNMASKED_RENDERER_WEBGL: 0x9246 }),
        getParameter: () => unmasked
      };
      const renderer = { getContext: () => gl };
      const context = { window: {}, THREE, console, navigator: { userAgent: agent } };
      context.window = context;
      vm.createContext(context);
      vm.runInContext(moduleSrc, context, { filename: 'director_stage_rendering.js' });
      return context.DirectorStageRendering.detectDriverShaderRisk(renderer);
    }
    const WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155.0';
    const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/155.0';
    // 稳定后端：保留阴影
    expect(riskWith(WIN, 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)')).toBe(false);
    // 风险后端：Vulkan / OpenGL
    expect(riskWith(WIN, 'ANGLE (NVIDIA, Vulkan 1.4.303 (NVIDIA))')).toBe(true);
    expect(riskWith(WIN, 'ANGLE (NVIDIA OpenGL Engine)')).toBe(true);
    // 取不到后端串：保守判定为风险
    expect(riskWith(WIN, '')).toBe(true);
    expect(riskWith(WIN, '', false)).toBe(true);
    // 非 Windows 平台不受影响（macOS Metal / Linux 无此复现）
    expect(riskWith(MAC, 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unmasked Renderer: Apple M1)')).toBe(false);
  });

  it('编辑器接线：GLB 人台替换（骨骼映射/材质蒙皮/脚本挂载）', () => {
    const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');
    // 预载与状态机
    expect(src).toContain("var MALE_BASE_MESH_URL = '/assets/puppet/male_base_mesh.glb';");
    expect(src).toContain('preloadMaleBaseMesh();');
    // 男人体型走 GLB，其余体型保留程序化
    expect(src).toContain("label: '男人', hipH: 0.92, labelY: 2.00, jointR: 0.036, useGlb: true,");
    expect(src).toContain("t.useGlb === true && MALE_BASE_MESH_STATE === 'ready'");
    // GLTFLoader 会去掉节点名中的 "."，映射表必须使用加载后的骨骼名
    expect(src).toContain("spine: 'spine001', chest: 'spine003', neck: 'spine005'");
    expect(src).toContain("shoulderL: 'upper_armL', elbowL: 'forearmL', wristL: 'handL'");
    expect(src).toContain("hipL: 'thighL', kneeL: 'shinL', ankleL: 'footL'");
    // r128 蒙皮由 material.skinning 开关控制，自定义材质必须显式打开
    expect(src).toContain('mat.skinning = true;');
    // 头骨增权手术：新 Bone + 转移 spine005 头侧权重
    expect(src).toContain("findBone('spine005')");
    expect(src).toContain("headBone.name = 'head.glb'");
    // 骨骼重挂载：attach 保持世界变换，关节组局部坐标 = 骨骼头世界坐标 - 父组世界坐标
    expect(src).toContain('var local = headW.clone().sub(parentW);');
    expect(src).toContain('rig.joints[attachPlan[i][0]].attach(attachPlan[i][1]);');
    const html = fs.readFileSync(path.join(root, 'web/video_workflow.html'), 'utf8');
    expect(html).toContain('/assets/vendor/three-examples/loaders/GLTFLoader.js');
    expect(html).toContain('/assets/vendor/three-examples/utils/SkeletonUtils.js');
  });

  it('编辑器接线：风险后端预关阴影并同步 PiP 渲染器', () => {
    const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');
    expect(src).toContain('detectDriverShaderRisk');
    expect(src).toContain('this._driverShadowDisabled = true;');
    expect(src).toContain('this.renderer.shadowMap.enabled = false;');
    expect(src).toContain('if (this._driverShadowDisabled) this.pipRenderer.shadowMap.enabled = false;');
  });
});

describe('导演台渲染：编辑器接线', () => {
  it('主视口/PiP/快照统一管线，并释放全部资源', () => {
    const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');
    expect(src).toContain('self.mainPipeline.render()');
    expect(src).toContain('self.pipPipeline.render()');
    expect(src).toContain('this.pipPreviewQuality = 1;');
    expect(src).toContain('this.mainPipeline = makePipeline(this.renderer, this.viewCam, this.renderer.getPixelRatio())');
    expect(src).toContain('this.pipPipeline.setQuality(1)');
    expect(src).toContain('this.pipPipeline.setQuality(this.pipPreviewQuality)');
    expect(src).toContain('this.mainPipeline.dispose()');
    expect(src).toContain('this.pipPipeline.dispose()');
    expect(src).toContain('this.studioLights.dispose()');
    expect(src).toContain('this.studioEnvironment.dispose()');
    expect(src).toContain('R.prepareSceneColors(this.scene)');
  });
});
