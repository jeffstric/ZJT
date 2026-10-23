/**
 * 故事板 3D 预览「机位编辑」纯函数测试。
 *
 * 覆盖 spatial_camera_edit.js：setCamera 定位/改写、机位 clamp、
 * 预设机位计算。改写语义：three_scene_code 的 setCamera 行是机位唯一
 * 真源（见 docs/storyboard/spatial_3d_preview_design.md §机位编辑）。
 */

import { describe, expect, it } from 'vitest';

import {
  CAMERA_LIMITS,
  CAMERA_PRESETS,
  applyCameraPreset,
  clampCamera,
  findLastSetCameraCall,
  normalizeCamera,
  rewriteSetCamera,
} from '../js/storyboard/spatial_camera_edit.js';

describe('findLastSetCameraCall', () => {
  it('定位唯一的 setCamera 调用并解析数字参数', () => {
    const code = "makeActor('李卫国', 0.3, -0.3, {facing: 180});\nsetCamera(-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50);";
    const call = findLastSetCameraCall(code);
    expect(call).not.toBeNull();
    expect(code.slice(call.start, call.end + 1)).toBe('setCamera(-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50)');
    expect(call.args).toEqual([-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50]);
  });

  it('有多个调用时定位最后一个（增量链可能只调一次，防御多调）', () => {
    const code = 'setCamera(0, 1, 5, 0, 1, 0, 50);\nmoveActor("A", 1, 1);\nsetCamera(1, 2, 3, 0, 1, 0, 45);';
    const call = findLastSetCameraCall(code);
    expect(call.args[0]).toBe(1);
    expect(call.args[6]).toBe(45);
  });

  it('参数跨行 / fov 省略均可解析', () => {
    const crossLine = 'setCamera(\n  1, 2, 3,\n  0, 1, 0\n);';
    expect(findLastSetCameraCall(crossLine).args.slice(0, 6)).toEqual([1, 2, 3, 0, 1, 0]);

    const noFov = 'setCamera(1, 2, 3, 0, 1, 0);';
    expect(findLastSetCameraCall(noFov).args.length).toBe(6);
  });

  it('不误匹配 resetCamera 等含 setCamera 子串的调用', () => {
    const code = 'resetCamera(1, 2, 3, 0, 0, 0, 50);';
    expect(findLastSetCameraCall(code)).toBeNull();
  });

  it('无调用返回 null', () => {
    expect(findLastSetCameraCall('makeStage("地面", 10, 10, 0, 0);')).toBeNull();
    expect(findLastSetCameraCall('')).toBeNull();
  });
});

describe('rewriteSetCamera', () => {
  const camera = {
    eye: { x: 1.234, y: 2, z: -3.456 },
    target: { x: 0, y: 1.05, z: 0.5 },
    fov: 47.6,
  };

  it('替换最后一个 setCamera 参数，其余代码保持不变', () => {
    const code = "startScene('保安岗亭');\nmakeActor('赵志高', -0.5, 0.5, {facing: 0});\nsetCamera(-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50);";
    const next = rewriteSetCamera(code, camera);
    expect(next).toContain("makeActor('赵志高', -0.5, 0.5, {facing: 0});");
    expect(next).toContain('setCamera(1.23, 2, -3.46, 0, 1.05, 0.5, 48);');
    expect(next.startsWith(code.split('\n')[0])).toBe(true);
  });

  it('代码无 setCamera 时在末尾追加（保持每镜必须 setCamera 契约）', () => {
    const code = "startScene('天台');\nmakeActor('苏雨晴', 0, 4, {facing: 0});";
    const next = rewriteSetCamera(code, camera);
    expect(findLastSetCameraCall(next)).not.toBeNull();
    expect(next).toContain('setCamera(1.23, 2, -3.46, 0, 1.05, 0.5, 48);');
  });

  it('改写后代码可再解析并得到相同参数（幂等链路）', () => {
    const code = "setCamera(-0.6, 1.5, 1.8, 0.2, 0.8, -0.2, 50);";
    const once = rewriteSetCamera(code, camera);
    const twice = rewriteSetCamera(once, camera);
    expect(twice).toBe(once);
    expect(findLastSetCameraCall(twice).args).toEqual([1.23, 2, -3.46, 0, 1.05, 0.5, 48]);
  });
});

describe('clampCamera / normalizeCamera', () => {
  it('超界机位被约束到 CAMERA_LIMITS', () => {
    const cam = clampCamera({
      eye: { x: 99, y: 50, z: -99 },
      target: { x: 0, y: -8, z: 0 },
      fov: 200,
    });
    expect(cam.eye.x).toBe(CAMERA_LIMITS.posAbsMax);
    expect(cam.eye.y).toBe(CAMERA_LIMITS.eyeYMax);
    expect(cam.eye.z).toBe(-CAMERA_LIMITS.posAbsMax);
    expect(cam.target.y).toBe(CAMERA_LIMITS.targetYMin);
    expect(cam.fov).toBe(CAMERA_LIMITS.fovMax);
  });

  it('字段缺失 / 非法值给默认值不抛错', () => {
    const cam = normalizeCamera(null);
    expect(cam.eye).toEqual({ x: 0, y: 1.5, z: 0 });
    expect(cam.target).toEqual({ x: 0, y: 1, z: 0 });
    expect(cam.fov).toBe(CAMERA_LIMITS.fovDefault);
  });
});

describe('applyCameraPreset', () => {
  const focal = { x: 2, y: 0.8, z: -1 };

  it('正面预设：机位位于焦点 +dir 方向，注视点回到焦点', () => {
    const preset = CAMERA_PRESETS.find((p) => p.id === 'eye_front');
    const cam = applyCameraPreset(preset, focal, 4.5);
    expect(cam.eye.x).toBeCloseTo(2, 5);
    expect(cam.eye.y).toBe(preset.eyeY);
    expect(cam.eye.z).toBeCloseTo(-1 + 4.5, 5);
    expect(cam.target.x).toBe(2);
    expect(cam.target.z).toBe(-1);
    expect(cam.fov).toBe(preset.fov);
  });

  it('定距预设（近景）使用 preset.dist 而非场景半径', () => {
    const preset = CAMERA_PRESETS.find((p) => p.id === 'closeup_front');
    const cam = applyCameraPreset(preset, focal, 9);
    expect(cam.eye.z).toBeCloseTo(-1 + 2.0, 5);
  });

  it('顶摄 x/z 接近焦点，机位高度为预设值', () => {
    const preset = CAMERA_PRESETS.find((p) => p.id === 'top_down');
    const cam = applyCameraPreset(preset, focal, 4.5);
    expect(cam.eye.y).toBe(7.5);
    expect(Math.abs(cam.eye.x - focal.x)).toBeLessThan(0.5);
  });

  it('非法 preset 返回 null', () => {
    expect(applyCameraPreset(null, focal)).toBeNull();
  });
});

import { cameraSeesActors } from '../js/storyboard/spatial_camera_edit.js';

describe('cameraSeesActors 空镜检查', () => {
  // 语义约定：eye 在原点前方 4m 看 target（原点方向），两角色在 (±1.2, ±0.4)
  const camera = { eye: [0, 1.5, 4], target: [0, 1.0, 0], fov: 50 };

  it('角色在视锥内 → visible>0；背对机位 → visible=0', () => {
    const front = cameraSeesActors(camera, [{ x: 0.5, z: -0.5 }, { x: -1, z: 0.5 }]);
    expect(front.total).toBe(2);
    expect(front.visible).toBe(2); // 站在机位正前方区域

    // 同样两个角色，机位看向完全相反方向（+z 深处）
    const behind = cameraSeesActors(
      { eye: [0, 1.5, 4], target: [0, 1.0, 12], fov: 50 },
      [{ x: 0.5, z: -0.5 }, { x: -1, z: 0.5 }],
    );
    expect(behind.visible).toBe(0);
  });

  it('分镜5 实测数据复现：机位朝右前空地、角色均在左后 → 空镜', () => {
    const cam5 = { eye: [2, 1.65, 2.6], target: [3.9, 1.45, -1.1], fov: 50 };
    const res = cameraSeesActors(cam5, [{ x: -1.8, z: 1.2 }, { x: -1.0, z: 1.0 }]);
    expect(res.visible).toBe(0);
  });

  it('角色在相机正后方 → 不可见；fov 越大视野越宽', () => {
    // 机位在原点看 +z，角色在 -z（身后）
    const back = cameraSeesActors(
      { eye: [0, 1.5, 0], target: [0, 1.0, 5], fov: 50 },
      [{ x: 0, z: -3 }],
    );
    expect(back.visible).toBe(0);

    // 同一站位：窄 fov 看不到，宽 fov 能容纳
    const far = { x: 3.2, z: 4.5 };
    const narrow = cameraSeesActors({ eye: [0, 1.5, 0], target: [0, 1.0, 5], fov: 30 }, [far]);
    const wide = cameraSeesActors({ eye: [0, 1.5, 0], target: [0, 1.0, 5], fov: 100 }, [far]);
    expect(wide.visible).toBeGreaterThanOrEqual(narrow.visible);
  });

  it('入参异常安全：空 actors / 缺字段返回 visible=0 不抛错', () => {
    expect(cameraSeesActors(null, [{ x: 0, z: 0 }])).toEqual({ visible: 0, total: 1 });
    expect(cameraSeesActors(camera, []).total).toBe(0);
    expect(cameraSeesActors(camera, [{ x: NaN, z: 1 }]).visible).toBe(0);
  });
});
