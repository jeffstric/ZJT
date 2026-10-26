// ============================
// director_stage_rendering.js - 导演台 PBR / 灯光 / SSAO 渲染管线
// 依赖 three r128 及本地 three-examples UMD；组件缺失时自动回退原始 renderer。
// ============================

(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  var THREE = window.THREE;
  var TEXTURE_ROOT = '/assets/puppet/';
  var warned = false;

  function warnOnce(message) {
    if (warned || typeof console === 'undefined') return;
    warned = true;
    console.warn(message);
  }

  function configureRenderer(renderer, options) {
    options = options || {};
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = options.exposure == null ? 0.95 : options.exposure;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    if (options.pixelRatio) renderer.setPixelRatio(options.pixelRatio);
    return renderer;
  }

  // r128 在 render target + GammaCorrection 管线中需要显式线性颜色，避免整体发亮。
  function toLinearColor(color) {
    return new THREE.Color(color).convertSRGBToLinear();
  }

  function prepareSceneColors(scene) {
    if (scene.background && scene.background.isColor && !scene.userData._dsLinearBackground) {
      scene.background.convertSRGBToLinear();
      scene.userData._dsLinearBackground = true;
    }
    scene.traverse(function (object) {
      if (!object.material) return;
      var materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach(function (material) {
        if (material.color && !material.userData._dsLinearColor) {
          material.color.convertSRGBToLinear();
          material.userData._dsLinearColor = true;
        }
      });
    });
  }

  function ensureUv2(geometry) {
    if (geometry && geometry.attributes && geometry.attributes.uv && !geometry.attributes.uv2) {
      geometry.setAttribute('uv2', geometry.attributes.uv.clone());
    }
    return geometry;
  }

  function makeSolidTexture(rgba) {
    var texture = new THREE.DataTexture(new Uint8Array(rgba), 1, 1, THREE.RGBAFormat);
    texture.needsUpdate = true;
    return texture;
  }

  function createResinMaterials(colorHex, renderer) {
    var disposed = false;
    var textures = [
      makeSolidTexture([128, 128, 255, 255]),
      makeSolidTexture([255, 255, 255, 255])
    ];
    var neutralNormal = textures[0];
    var neutralAo = textures[1];
    var anisotropy = renderer && renderer.capabilities ? Math.min(4, renderer.capabilities.getMaxAnisotropy()) : 1;

    function physical(color, roughness, clearcoat, envIntensity) {
      var material = new THREE.MeshPhysicalMaterial({
        color: toLinearColor(color),
        roughness: roughness,
        metalness: 0,
        clearcoat: clearcoat,
        clearcoatRoughness: 0.72,
        envMapIntensity: envIntensity,
        normalMap: neutralNormal,
        normalScale: new THREE.Vector2(0.35, 0.35),
        aoMap: neutralAo,
        aoMapIntensity: 0.65
      });
      material.userData._dsLinearColor = true;
      return material;
    }

    var body = physical(colorHex, 0.56, 0.16, 0.65);
    var torso = physical(colorHex, 0.54, 0.18, 0.65);
    var head = physical(colorHex, 0.55, 0.17, 0.65);
    var seamColor = new THREE.Color(colorHex).multiplyScalar(0.78);
    var seam = physical(seamColor, 0.72, 0.04, 0.35);
    var materials = [body, torso, head, seam];

    function loadTexture(file, repeat, assign) {
      if (typeof document === 'undefined' || typeof Image === 'undefined') return null;
      var texture = new THREE.TextureLoader().load(TEXTURE_ROOT + file, function () {
        if (disposed) {
          texture.dispose();
          return;
        }
        assign(texture);
      }, undefined, function () {
        // 加载失败保留中性 fallback；不阻断导演台。
      });
      texture.wrapS = texture.wrapT = repeat ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
      texture.encoding = THREE.LinearEncoding;
      texture.anisotropy = anisotropy;
      texture.needsUpdate = true;
      textures.push(texture);
      return texture;
    }

    loadTexture('resin_normal.png', true, function (texture) {
      body.normalMap = texture;
      body.normalScale.set(0.16, 0.16);
      body.needsUpdate = true;
    });
    loadTexture('torso_normal.png', false, function (texture) {
      torso.normalMap = texture;
      torso.normalScale.set(0.46, 0.46);
      torso.needsUpdate = true;
    });
    loadTexture('torso_ao.png', false, function (texture) {
      torso.aoMap = texture;
      torso.needsUpdate = true;
    });
    loadTexture('head_normal.png', false, function (texture) {
      head.normalMap = texture;
      head.normalScale.set(0.38, 0.38);
      head.needsUpdate = true;
    });
    loadTexture('head_ao.png', false, function (texture) {
      head.aoMap = texture;
      head.needsUpdate = true;
    });

    return {
      body: body,
      torso: torso,
      head: head,
      seam: seam,
      materials: materials,
      textures: textures,
      dispose: function () {
        if (disposed) return;
        disposed = true;
        materials.forEach(function (material) { material.dispose(); });
        textures.forEach(function (texture) { texture.dispose(); });
      }
    };
  }

  function createStudioEnvironment(renderer, scene) {
    if (!THREE.RoomEnvironment || !THREE.PMREMGenerator) {
      return { texture: null, dispose: function () {} };
    }
    var pmrem = new THREE.PMREMGenerator(renderer);
    pmrem.compileCubemapShader();
    var room = new THREE.RoomEnvironment();
    var target = pmrem.fromScene(room, 0.04);
    scene.environment = target.texture;
    room.traverse(function (object) {
      if (object.geometry) object.geometry.dispose();
      if (object.material) object.material.dispose();
    });
    return {
      texture: target.texture,
      dispose: function () {
        if (scene.environment === target.texture) scene.environment = null;
        target.dispose();
        pmrem.dispose();
      }
    };
  }

  function createThreePointLights(scene) {
    var hemi = new THREE.HemisphereLight(0xb8c6dc, 0x1a1d26, 0.18);
    scene.add(hemi);

    var key = new THREE.DirectionalLight(0xffffff, 1.10);
    key.position.set(3.5, 6, 4);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -3;
    key.shadow.camera.right = 3;
    key.shadow.camera.top = 3;
    key.shadow.camera.bottom = -3;
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 20;
    key.shadow.bias = -0.00015;
    key.shadow.normalBias = 0.025;
    scene.add(key);

    var fill = new THREE.DirectionalLight(0x88aaff, 0.25);
    fill.position.set(-4, 2.5, 4);
    fill.castShadow = false;
    scene.add(fill);

    var rim = new THREE.SpotLight(0xc5d4ff, 1.20, 18, 0.50, 0.85, 1);
    rim.position.set(-3, 4, -4);
    rim.castShadow = false;
    rim.target.position.set(0, 1, 0);
    scene.add(rim);
    scene.add(rim.target);

    return {
      hemi: hemi,
      key: key,
      fill: fill,
      rim: rim,
      dispose: function () {
        [hemi, key, fill, rim, rim.target].forEach(function (light) { scene.remove(light); });
        if (key.shadow && key.shadow.dispose) key.shadow.dispose();
      }
    };
  }

  function syncComposerCamera(ssao, camera) {
    if (!ssao || !ssao.ssaoMaterial) return;
    var uniforms = ssao.ssaoMaterial.uniforms;
    uniforms.cameraProjectionMatrix.value.copy(camera.projectionMatrix);
    uniforms.cameraInverseProjectionMatrix.value.copy(camera.projectionMatrixInverse);
    uniforms.cameraNear.value = camera.near;
    uniforms.cameraFar.value = camera.far;
  }

  function composerSupported(renderer) {
    return !!(
      THREE.EffectComposer && THREE.RenderPass && THREE.ShaderPass && THREE.SSAOPass &&
      THREE.GammaCorrectionShader && THREE.CopyShader && THREE.SimplexNoise && THREE.SSAOShader &&
      renderer && renderer.extensions && (renderer.capabilities.isWebGL2 || renderer.extensions.has('WEBGL_depth_texture'))
    );
  }

  function createComposer(renderer, scene, camera, options) {
    options = options || {};
    var fallback = {
      composer: null,
      ssao: null,
      supported: false,
      render: function () { renderer.render(scene, camera); },
      setSize: function () {},
      setQuality: function () {},
      dispose: function () {}
    };
    if (!composerSupported(renderer)) {
      warnOnce('导演台：SSAO 组件或深度纹理不可用，已回退普通渲染。');
      return fallback;
    }

    var composer = new THREE.EffectComposer(renderer);
    var pixelRatio = options.pixelRatio || renderer.getPixelRatio();
    composer.setPixelRatio(pixelRatio);
    var renderPass = new THREE.RenderPass(scene, camera);
    composer.addPass(renderPass);
    var size = renderer.getSize(new THREE.Vector2());
    var ssao = new THREE.SSAOPass(scene, camera, Math.max(1, size.x * pixelRatio), Math.max(1, size.y * pixelRatio));
    ssao.kernelRadius = options.kernelRadius == null ? 0.18 : options.kernelRadius;
    ssao.minDistance = options.minDistance == null ? 0.0008 : options.minDistance;
    ssao.maxDistance = options.maxDistance == null ? 0.025 : options.maxDistance;
    ssao.output = THREE.SSAOPass.OUTPUT.Default;
    // 蒙皮人偶的 SSAO 残影修复：法线/深度预渲染默认走 scene.overrideMaterial，
    // r128 该路径不会给蒙皮网格上传骨骼纹理——预渲染结果冻结在某一固定姿态，
    // 摆姿后与 beauty 不一致，乘法合成出深色"残影"。skinning 标志必须保留
    // （逐对象渲染时走正常蒙皮路径要用），同时把 overrideMaterial 渲染改为
    // 逐网格临时换材质，与 beauty 完全同一条渲染路径。
    var skinnedNormalMat = ssao.normalMaterial;
    if (skinnedNormalMat) skinnedNormalMat.skinning = true;
    if (skinnedNormalMat && typeof ssao.renderOverride === 'function') {
      // 激活标记：用户可在控制台确认蒙皮预渲染补丁已生效（出现旧缓存 JS 时此日志缺失）
      console.info('[导演台] SSAO 蒙皮预渲染补丁已激活');
      var origRenderOverride = ssao.renderOverride;
      ssao.renderOverride = function (renderer, overrideMaterial, renderTarget, clearColor, clearAlpha) {
        if (overrideMaterial !== skinnedNormalMat || !scene || !scene.traverse) {
          return origRenderOverride.call(ssao, renderer, overrideMaterial, renderTarget, clearColor, clearAlpha);
        }
        var swapped = [];
        scene.traverse(function (o) {
          if ((o.isMesh || o.isLine || o.isPoints) && o.visible && o.material !== skinnedNormalMat) {
            swapped.push([o, o.material]);
            o.material = skinnedNormalMat;
          }
        });
        renderer.getClearColor(ssao.originalClearColor);
        var originalClearAlpha = renderer.getClearAlpha();
        var originalAutoClear = renderer.autoClear;
        renderer.setRenderTarget(renderTarget);
        renderer.autoClear = false;
        clearColor = overrideMaterial.clearColor || clearColor;
        clearAlpha = overrideMaterial.clearAlpha || clearAlpha;
        if (clearColor !== undefined && clearColor !== null) {
          renderer.setClearColor(clearColor);
          renderer.setClearAlpha(clearAlpha || 0.0);
          renderer.clear();
        }
        try {
          renderer.render(scene, ssao.camera);
        } finally {
          for (var i = 0; i < swapped.length; i++) swapped[i][0].material = swapped[i][1];
          renderer.autoClear = originalAutoClear;
          renderer.setClearColor(ssao.originalClearColor);
          renderer.setClearAlpha(originalClearAlpha);
        }
      };
    }
    // SSAOPass 自己渲染 beauty；只给 composer 开 MSAA 无法覆盖这里，必须替换它的 target。
    if (options.msaa !== false && renderer.capabilities.isWebGL2 && THREE.WebGLMultisampleRenderTarget) {
      var originalBeauty = ssao.beautyRenderTarget;
      var beautyMsaa = new THREE.WebGLMultisampleRenderTarget(ssao.width, ssao.height, {
        minFilter: THREE.LinearFilter,
        magFilter: THREE.LinearFilter,
        format: THREE.RGBAFormat
      });
      beautyMsaa.samples = options.msaaSamples || 4;
      beautyMsaa.texture.name = 'DirectorStage.SSAOBeauty.MSAA';
      ssao.beautyRenderTarget = beautyMsaa;
      ssao.ssaoMaterial.uniforms.tDiffuse.value = beautyMsaa.texture;
      originalBeauty.dispose();
    }
    composer.addPass(ssao);
    var gamma = new THREE.ShaderPass(THREE.GammaCorrectionShader);
    composer.addPass(gamma);

    return {
      composer: composer,
      ssao: ssao,
      supported: true,
      render: function () {
        syncComposerCamera(ssao, camera);
        composer.render();
      },
      setSize: function (width, height) { composer.setSize(width, height); },
      setQuality: function (ratio) { composer.setPixelRatio(ratio); },
      dispose: function () {
        if (ssao.ssaoMaterial) ssao.ssaoMaterial.dispose();
        if (ssao.noiseTexture) ssao.noiseTexture.dispose();
        if (ssao.normalRenderTarget && ssao.normalRenderTarget.depthTexture) {
          ssao.normalRenderTarget.depthTexture.dispose();
        }
        [renderPass, ssao, gamma, composer.copyPass].forEach(function (pass) {
          if (pass && pass.dispose) pass.dispose();
          else if (pass && pass.material) pass.material.dispose();
        });
        composer.renderTarget1.dispose();
        composer.renderTarget2.dispose();
      }
    };
  }

  // 仅合并同一刚体内、同材质且 attribute 布局一致的网格；调用方保留关节层级和原始网格生命周期。
  function mergeRigidMeshes(meshes) {
    if (!meshes || meshes.length < 2 || !THREE.BufferGeometryUtils) return null;
    var material = meshes[0].material;
    var geometries = [];
    for (var i = 0; i < meshes.length; i++) {
      if (meshes[i].material !== material) return null;
      meshes[i].updateMatrix();
      var geometry = meshes[i].geometry.clone();
      geometry.applyMatrix4(meshes[i].matrix);
      geometries.push(geometry);
    }
    var merged = THREE.BufferGeometryUtils.mergeBufferGeometries(geometries, false);
    geometries.forEach(function (geometry) { geometry.dispose(); });
    if (!merged) return null;
    var mesh = new THREE.Mesh(merged, material);
    mesh.castShadow = meshes[0].castShadow;
    mesh.receiveShadow = meshes[0].receiveShadow;
    return mesh;
  }

  function smoothStaticGeometry(geometry, subdivisions) {
    var result = geometry;
    if (THREE.BufferGeometryUtils) result = THREE.BufferGeometryUtils.mergeVertices(result);
    if (subdivisions > 0 && THREE.SubdivisionModifier) {
      var modifier = new THREE.SubdivisionModifier(subdivisions);
      var subdivided = modifier.modify(result);
      if (result !== geometry) result.dispose();
      result = subdivided;
    }
    result.computeVertexNormals();
    ensureUv2(result);
    return result;
  }

  function roundedJoint(width, height, depth, radius) {
    if (!THREE.RoundedBoxGeometry) return null;
    return ensureUv2(new THREE.RoundedBoxGeometry(width, height, depth, 4, radius));
  }

  // r128 无 CapsuleGeometry 时的纯 Lathe 胶囊体；length 为中间圆柱段长度。
  function createCapsuleLathe(radius, length, radialSegments) {
    var points = [];
    var capSegments = 10;
    var i, theta;
    for (i = 0; i <= capSegments; i++) {
      theta = -Math.PI / 2 + (i / capSegments) * Math.PI / 2;
      points.push(new THREE.Vector2(Math.max(0.0001, radius * Math.cos(theta)), -length / 2 + radius * Math.sin(theta)));
    }
    points.push(new THREE.Vector2(radius, length / 2));
    for (i = 0; i <= capSegments; i++) {
      theta = (i / capSegments) * Math.PI / 2;
      points.push(new THREE.Vector2(Math.max(0.0001, radius * Math.cos(theta)), length / 2 + radius * Math.sin(theta)));
    }
    var geometry = new THREE.LatheGeometry(points, radialSegments || 24);
    geometry.computeVertexNormals();
    return ensureUv2(geometry);
  }

  function createLatheTorso(profile, radialSegments) {
    var points = profile.map(function (point) {
      return new THREE.Vector2(Math.max(0.0001, point[1]), point[0]);
    });
    var geometry = new THREE.LatheGeometry(points, radialSegments || 32);
    geometry.computeVertexNormals();
    return ensureUv2(geometry);
  }

  // 部分显卡驱动的 ANGLE 后端（如 NVIDIA Vulkan/OpenGL）编译某个高级着色器失败后会拖垮
  // 整个着色器子系统：之后所有程序 LINK_STATUS=false 且日志为空，unmasked renderer 查询返回空串。
  // 通过 program.diagnostics 检测这类链接失败，供编辑器自动降级（先关阴影，再停用后处理）。
  function findFailedPrograms(renderers) {
    var failed = [];
    (renderers || []).forEach(function (renderer, index) {
      var programs = renderer && renderer.info && renderer.info.programs;
      if (!programs) return;
      programs.forEach(function (program) {
        if (program && program.diagnostics) {
          failed.push({ renderer: index, key: String(program.cacheKey).replace(/\s+/g, ' ').slice(0, 120) });
        }
      });
    });
    return failed;
  }

  // 部分显卡驱动（如 NVIDIA 的 ANGLE Vulkan/OpenGL 后端）在编译 阴影程序 + 带贴图的
  // 标准族材质程序 的组合时驱动级崩溃，且会拖垮整个 GPU 进程的着色器编译（此后任何上下文
  // 的任何程序都无法再链接，日志为空、无法恢复；运行时探测等于主动触发崩溃，不可行）。
  // 好在不编译任何阴影程序即可完全规避（同环境关闭阴影后全部程序链接正常）。
  // Windows 上 Chrome 的默认稳定后端是 Direct3D11；Vulkan/OpenGL 后端或取不到后端串时
  // 判定为风险环境，编辑器从第一帧起关闭阴影（PBR 材质/SSAO/环境光全部保留）。
  function detectDriverShaderRisk(renderer) {
    if (typeof navigator === 'undefined' || !navigator.userAgent) return false;
    if (navigator.userAgent.indexOf('Windows') === -1) return false;
    var gl = renderer && renderer.getContext && renderer.getContext();
    if (!gl) return false;
    var info = gl.getExtension('WEBGL_debug_renderer_info');
    var unmasked = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : '';
    if (!unmasked) return true;
    return String(unmasked).indexOf('Direct3D11') === -1;
  }

  window.DirectorStageRendering = {
    configureRenderer: configureRenderer,
    toLinearColor: toLinearColor,
    prepareSceneColors: prepareSceneColors,
    ensureUv2: ensureUv2,
    createResinMaterials: createResinMaterials,
    createStudioEnvironment: createStudioEnvironment,
    createThreePointLights: createThreePointLights,
    createComposer: createComposer,
    syncComposerCamera: syncComposerCamera,
    mergeRigidMeshes: mergeRigidMeshes,
    smoothStaticGeometry: smoothStaticGeometry,
    roundedJoint: roundedJoint,
    createCapsuleLathe: createCapsuleLathe,
    createLatheTorso: createLatheTorso,
    findFailedPrograms: findFailedPrograms,
    detectDriverShaderRisk: detectDriverShaderRisk
  };
})();
