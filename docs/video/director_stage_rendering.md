# 导演台专业级人偶渲染架构

本文对应 `web/js/director_stage_rendering.js` 的实际实现，说明如何在 **Three.js r128 UMD** 下，用几何微调、PBR/贴图、三点布光、PMREM 和 SSAO 提升基础几何人台的质感。

核心边界：

- 不合并整只人偶，不破坏关节父子层级、raycast 拾取、姿态和时间轴。
- 不做 subdivision。轮廓靠 Lathe 分段和 RoundedBox 倒角。
- normal/AO 只改变受光，**不会改变模型轮廓**；下巴、鼻尖和肩甲外形仍需要合适的基础几何。
- 主视口、PiP 和快照必须走同一套后处理，否则导出会“货不对板”。

## 1. 总体结构与加载顺序

```text
video_workflow.html
  three.min.js (r128)
  CopyShader
  EffectComposer（r128 内含 Pass / FullScreenQuad）
  ShaderPass / RenderPass
  SimplexNoise / SSAOShader / SSAOPass
  GammaCorrectionShader
  RoomEnvironment
  RoundedBoxGeometry
  director_stage_rendering.js
  director_stage_editor.js
```

`director_stage_rendering.js` 暴露 `window.DirectorStageRendering`：

- `configureRenderer`：sRGB、ACES、曝光、PCFSoftShadowMap。
- `createResinMaterials`：body/torso/head/seam 分部位材质、异步贴图与资源释放。
- `prepareSceneColors`：背景和材质只做一次 sRGB→Linear。
- `createStudioEnvironment`：PMREM + RoomEnvironment。
- `createThreePointLights`：Key / Fill / Rim。
- `createComposer` / `syncComposerCamera`：SSAO、FOV、尺寸和质量管理。
- 几何工具：`roundedJoint`、`ensureUv2`。程序化躯干和四肢的 Lathe 在 `director_stage_editor.js` 的 `buildPuppetRig` 里直接生成。

所有 example 文件来自官方 **r128** 包，位于 `web/assets/vendor/three-examples/`，不依赖 CDN，也不混用新版模块。

## 2. 程序化人偶几何

男人体型优先使用 `male_base_mesh.glb`。女人、小孩、胖子、瘦子，以及 GLB 未就绪或构建失败时，由 `buildPuppetRig` 按体型 profile 拼装。关节 Group 保持独立，不把整只人偶合并成一个网格，否则姿态旋转轴会失效。

躯干、四肢、头、脚使用 `LatheGeometry`。Lathe 在 phi 接缝处顶点是两份，`weldLatheSeam` 把两侧法线焊平。肘甲和膝甲走 `roundedJoint()`。

### 2.1 倒角关节

肘/膝甲使用 r128 `RoundedBoxGeometry`，而不是靠法线假装倒角：

```js
const geometry = new THREE.RoundedBoxGeometry(width, height, depth, 4, radius);
```

项目通过 `roundedJoint()` 同时补齐 `uv2`。没有该组件时保留椭球回退，不让导演台打不开。

## 3. PBR 材质、Normal Map 与 AO Map

### 3.1 哑光树脂参数

body 的实际基准值：

```js
new THREE.MeshPhysicalMaterial({
  color,
  roughness: 0.56,
  metalness: 0,
  clearcoat: 0.16,
  clearcoatRoughness: 0.72,
  envMapIntensity: 0.65,
  normalMap: neutralNormal,
  aoMap: neutralAO,
  aoMapIntensity: 0.65
});
```

torso/head 单独建材质，roughness/clearcoat 只做微调；seam 更深、更粗糙、反射更弱。这样不会把胸腹贴图错误套到头或四肢。

### 3.2 外部贴图管线

资源位于 `web/assets/puppet/`：

- `resin_normal.png`：极轻微树脂微纹理。
- `torso_normal.png` / `torso_ao.png`：低强度胸腹宽起伏和胸腹分界遮蔽。
- `head_normal.png` / `head_ao.png`：轻微下巴/鼻梁和头颈接触遮蔽。

可用以下命令确定性重建（只用 Pillow）：

```bash
python scripts/generate_puppet_textures.py
```

高度场中心差分生成法线，正面围绕 Lathe 的 `u=0/1` 接缝对称，背面 `u=0.5` 保持中性。PNG 顶行对应 `v=1`，匹配 `TextureLoader.flipY=true`。

运行时异步加载，加载前使用 `(128,128,255)` 中性 normal 和白色 AO，页面无需等待；加载完成后仅替换材质贴图并设置 `needsUpdate`。关闭编辑器后，迟到的回调只负责释放纹理，不重新启用材质。

### 3.3 AO 的 uv2 与颜色空间

r128 的 `aoMap` 使用 `uv2`：

```js
geometry.setAttribute('uv2', geometry.attributes.uv.clone());
```

normal/AO 使用 LinearEncoding；解剖贴图 ClampToEdge，树脂微纹理才 Repeat，anisotropy 上限 4。

**限制必须明确**：normal map 可以暗示鼻梁、胸腹起伏，AO 可以加深接缝，但两者都不会改变侧脸、下颌、肩部或脚尖的真实 silhouette。

## 4. 电影级三点布光与环境反射

### 4.1 Key / Fill / Rim

`createThreePointLights(scene)` 的实际配置：

- **Key DirectionalLight**：`(3.5, 6, 4)`，强度 `1.10`。
  - 唯一 `castShadow=true`；2048 shadow map；正交范围 ±3m；near/far `0.5/20`。
  - `bias=-0.00015`、`normalBias=0.025`，减少自阴影 acne。
- **Fill DirectionalLight**：冷色、强度 `0.25`，不投影。
- **Rim SpotLight**：`(-3, 4, -4)`，target `(0,1,0)`。
  - `angle=0.50`、`penumbra=0.85`、`distance=18`，不投影，勾勒背部和肩部轮廓。
- 半球光强度仅 `0.18`，避免冲淡 SSAO 和接触阴影。

外甲和肢体 cast/receive shadow，地面 receive；helper、网格和标注不投影。

### 4.2 PMREM + RoomEnvironment

```js
const pmrem = new THREE.PMREMGenerator(renderer);
pmrem.compileCubemapShader();
const room = new THREE.RoomEnvironment();
const target = pmrem.fromScene(room, 0.04);
scene.environment = target.texture;
```

`scene.environment` 只负责 PBR 反射，背景仍是深色。render target、PMREM 和 RoomEnvironment 子资源都纳入 dispose。

### 4.3 r128 色彩管理

composer 中使用 render target + GammaCorrection 时，背景和材质颜色必须显式执行一次 `convertSRGBToLinear()`，否则画面会整体泛白。`prepareSceneColors` 用标记保证幂等，禁止每次初始化或每帧重复转换。

## 5. SSAO、EffectComposer 与快照一致性

### 5.1 r128 的正确 Pass 链

```js
const composer = new THREE.EffectComposer(renderer);
composer.addPass(new THREE.RenderPass(scene, camera));
composer.addPass(new THREE.SSAOPass(scene, camera, width, height));
composer.addPass(new THREE.ShaderPass(THREE.GammaCorrectionShader));
```

r128 没有新版 `OutputPass`，所以使用 `GammaCorrectionShader`，不要照搬新版示例。

SSAO 初始参数以 1.7m 人台为尺度，单位是米：

```js
ssao.kernelRadius = 0.05;
ssao.minDistance = 0.0008;
ssao.maxDistance = 0.025;
ssao.output = THREE.SSAOPass.OUTPUT.Default;
```

不能把默认 8m 的 kernelRadius 直接用于厘米级关节，否则会出现大面积脏黑。采样半径取 5cm，只覆盖关节缝和脚底接触。

r128 自带的 `SSAOShader` 把 `minDistance` / `maxDistance` 拿去和 0–1 正交深度比较。导演台相机 `near=0.1`、`far=100` 时，`0.0008` / `0.025` 会放大成大约 8cm / 2.5m。采样球因此在手臂外侧的地面上留下一圈脱离身体的手形暗斑。`patchSsaoDistanceToViewMeters` 在创建 `SSAOPass` 之前把遮挡判断改成视空间米：`delta = surfaceViewZ - samplePoint.z`，表面比采样点更近且距离落在 0.8mm–2.5cm 之间才计遮挡。

远平面清空值（原始深度 > 0.999）直接输出「无遮挡」。透视深度在 far 附近的量化噪声有几厘米到几米，会把整片空背景随机记成遮挡。

距离改成米之后，掠射地面仍会误遮挡：视线几乎贴着地板时，几厘米的深度差落进 `minDistance`–`maxDistance`，地平线一整条变暗。人体挡住这些采样的像素不再变暗，肩膀和手臂两侧就露出更亮的扇形残影。补丁在遮挡累加后乘上 `smoothstep(0.40, 0.58, ndotv)`，`ndotv` 是表面法线与“指向相机”方向的夹角余弦。掠射地面权重降到 0，正对镜头的身体和近处脚底接触仍然保留。`patchSsaoBlurDepthAware` 让 5×5 模糊只混合原始深度差不超过 0.02 的邻域，避免把人体边缘的遮挡抹进背景。

### 5.2 双 composer

主视口和 PiP 各自拥有 composer，但共用 `createComposer`：

- 主视口 pixelRatio 跟随 `renderer.getPixelRatio()`；PiP 预览质量固定 `1`，主视口/PiP/快照全分辨率渲染，不以降低 Beauty 分辨率换性能。
- WebGL2 且 `THREE.WebGLMultisampleRenderTarget` 可用时，把 `ssao.beautyRenderTarget` 替换为 `WebGLMultisampleRenderTarget`（`samples=4`）并同步 `ssaoMaterial.uniforms.tDiffuse.value`、释放旧 target；否则 SSAO 自己渲染的 beauty 会绕开 composer 的抗锯齿，画面发糊、锯齿明显。
- `renderSnapshotDataUrl()` 不再临时切质量，仅在 `finally` 中恢复 helper。
- FOV 变化只调用 `syncComposerCamera` 更新 projection/inverse uniforms，不每帧重建 render target。
- ResizeObserver 同步主 composer 尺寸（`setSize`/`setQuality` 均为**整链重建**而非热调整：r128 的 `RenderTarget.setSize`/热调 pixelRatio 会损坏 SSAOPass 的 DepthTexture 附件，深度采样恒为 0，SSAO 输出噪声斑块/"尾影"；导演台 resize 低频，重建开销可忽略）。
- 缺组件或深度纹理时回退原始 `renderer.render(scene, camera)`，仅警告一次。

渲染路径：

```text
主视口：scene + viewCam     → mainComposer → canvas
PiP：scene + virtualCam     → pipComposer  → PiP canvas
快照：scene + virtualCam    → pipComposer（与预览同质量）→ JPEG dataURL
```

`close()` 先释放两个 composer、灯光、PMREM 和全部人偶纹理，再释放两个 renderer，避免反复打开导演台累积 GPU 资源。

### 5.3 显卡驱动兼容性规避（ANGLE 后端检测）

部分显卡驱动（已复现：NVIDIA RTX 40 系笔记本 + Chrome 155 的 ANGLE Vulkan/OpenGL 后端）在编译「阴影程序 + 带贴图的标准族材质程序」的组合时驱动级崩溃，并拖垮整个 GPU 进程的着色器编译：此后任何上下文的任何程序都链接失败（`LINK_STATUS=false`、日志为空、unmasked renderer 查询返回空串），**无法运行恢复**（关阴影、换后处理、换新上下文均无效）。Windows 上 Chrome 默认稳定后端是 Direct3D11，Vulkan/OpenGL 属于可选/回退后端。

因此不做运行时探测（探测本身即触发崩溃），改为 `detectDriverShaderRisk(renderer)` 静态识别：

- 仅对 Windows 生效（`navigator.userAgent` 含 `Windows`）；macOS/Linux 后端无此复现，不干预。
- 通过 `WEBGL_debug_renderer_info` 取 unmasked renderer 字符串（只读查询，不编译任何着色器）：包含 `Direct3D11` → 正常；Vulkan/OpenGL 或取不到串 → 风险环境。
- 风险环境下编辑器从第一帧起关闭实时阴影（主渲染器与 PiP 渲染器同步），PBR 材质（清漆/法线/AO）、SSAO、环境光全部保留。关闭阴影后同一后端所有程序链接正常（已实测验证）。

`findFailedPrograms(renderers)` 收集 `renderer.info.programs` 中带 `diagnostics` 的链接失败程序，是上述诊断与回归测试的底层工具。编辑器接线见 `web/js/director_stage_editor.js` 的 `_driverShadowDisabled`。

## 6. 性能与验收清单

- 不合并整只 rig，不为每盏灯开启阴影。
- 不以降低 Beauty 分辨率换性能：主视口/PiP/快照全分辨率；只允许 DPR 上限、单主光阴影、MSAA 或 SSAO 降级/关闭。
- 贴图异步加载，不在 Web 接口或事件循环中同步等待。
- 检查正/侧/背、3/4、T-Pose、胸/头/关节近景。
- 检查 UV 接缝、AO 脏黑、shadow acne、内外甲穿插和肩胸连接。
- 对比主视口、PiP、实际快照的曝光、AO 和材质是否一致。
- 反复打开/关闭导演台，确认纹理、render target、灯光和环境均释放。
- 自动化：`web/tests/director_stage_rendering.test.js` 覆盖材质、几何、灯光、composer、颜色幂等、回退和编辑器接线。
