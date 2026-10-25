/**
 * 导演台人偶装甲式躯干回归测试。
 *
 * 骨盆甲、腹甲、胸甲均为独立 LatheGeometry 外壳，下面是连续深色内芯。
 * 窄缝只来自这三块结构分件，禁止重新叠加腰线/胸线/腹肌线/锁骨装饰椭球。
 */

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const require = createRequire(import.meta.url);
const THREE = require(path.join(root, 'web/assets/vendor/three.min.js'));
const src = fs.readFileSync(path.join(root, 'web/js/director_stage_editor.js'), 'utf8');

function loadPuppetGeometry() {
  const match = src.match(/\/\/ ==== PUPPET_GEOMETRY_BEGIN ====([\s\S]*?)\/\/ ==== PUPPET_GEOMETRY_END ====/);
  expect(match).not.toBeNull();
  return new Function('THREE', `${match[1]}\nreturn { BODY_TYPES, buildPuppetRig };`)(THREE);
}

const { BODY_TYPES, buildPuppetRig } = loadPuppetGeometry();
const visibleMeshes = (group) => group.children.filter((part) => part.isMesh && part.visible);

describe('导演台：分件式盔甲人偶', () => {
  for (const bodyType of Object.keys(BODY_TYPES)) {
    it(`${bodyType} 具有骨盆/腹/胸外甲、连续内芯和肩甲`, () => {
      const rig = buildPuppetRig('#4f8ef7', bodyType);
      const outerMat = rig.materials[0];
      const coreMat = rig.materials[1];
      const segments = [rig.hipsY, rig.joints.spine, rig.joints.chest];

      for (const segment of segments) {
        const meshes = visibleMeshes(segment);
        // 每段只允许一块结构外甲和一个内芯；额外装饰线会破坏此契约。
        expect(meshes).toHaveLength(2);
        expect(meshes.every((part) => part.geometry.type === 'LatheGeometry')).toBe(true);
        expect(meshes.some((part) => part.material === outerMat)).toBe(true);
        expect(meshes.some((part) => part.material === coreMat)).toBe(true);
      }

      rig.root.updateMatrixWorld(true);
      const chestPlate = visibleMeshes(rig.joints.chest).find((part) => part.material === outerMat);
      const chestBox = new THREE.Box3().setFromObject(chestPlate);
      for (const side of ['L', 'R']) {
        const shoulder = rig.joints[`shoulder${side}`];
        const pauldrons = shoulder.children.filter((part) => (
          part.isMesh && part.visible && part.geometry.type === 'SphereGeometry' &&
          part.geometry.parameters.thetaLength < Math.PI
        ));
        expect(pauldrons).toHaveLength(1);
        const link = shoulder.children.find((part) => part.isMesh && part.geometry.type === 'CylinderGeometry');
        expect(link).toBeDefined();
        // 默认站姿下连接芯必须同时嵌入胸甲与肩甲，不能出现手臂悬空。
        const linkBox = new THREE.Box3().setFromObject(link);
        expect(linkBox.intersectsBox(chestBox)).toBe(true);
        expect(linkBox.intersectsBox(new THREE.Box3().setFromObject(pauldrons[0]))).toBe(true);
      }

      // 肘甲/膝甲位置必须使用已初始化尺寸，不能产生 NaN 而消失。
      for (const part of rig.bodyMeshes) {
        expect(Number.isFinite(part.position.x)).toBe(true);
        expect(Number.isFinite(part.position.y)).toBe(true);
        expect(Number.isFinite(part.position.z)).toBe(true);
      }
    });
  }
});
