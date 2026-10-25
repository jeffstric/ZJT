/**
 * 导演台人偶头部几何回归测试。
 *
 * 头部契约（无五官连续头型）：一个连续 LatheGeometry 头型 + 两只贴近头侧的小人耳。
 * 不叠加眉/眼/鼻/唇等任何五官网格（五官方向已放弃，男人体型使用 GLB 人台，
 * 见 buildGlbPuppetRig 与 web/tests/director_stage_rendering.test.js 的 GLB 接线断言）。
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
  // GLB 相关变量声明在提取块外，作为参数注入；node 无 GLB 缓存，'idle' 使构建走程序化人偶路径
  return new Function('THREE', 'MALE_BASE_MESH_STATE', 'maleBaseMeshGltf', 'GLB_JOINT_BONES', 'GLB_JOINT_PARENTS',
    `${match[1]}\nreturn { BODY_TYPES, buildPuppetRig };`)(THREE, 'idle', null, undefined, undefined);
}

const { BODY_TYPES, buildPuppetRig } = loadPuppetGeometry();

describe('导演台：无五官人偶头部', () => {
  for (const bodyType of Object.keys(BODY_TYPES)) {
    it(`${bodyType} 使用连续头型，仅保留两只竖向小耳`, () => {
      const type = BODY_TYPES[bodyType];
      const rig = buildPuppetRig('#34c38f', bodyType);
      const visibleMeshes = rig.joints.head.children.filter((part) => part.isMesh && part.visible);

      // 头、左耳、右耳；任何眉/鼻/唇/下颌附加网格都会使此断言失败。
      expect(visibleMeshes).toHaveLength(3);
      const headMesh = visibleMeshes.find((part) => part.geometry.type === 'LatheGeometry');
      expect(headMesh).toBeDefined();
      const ears = visibleMeshes.filter((part) => part !== headMesh);
      expect(ears).toHaveLength(2);

      expect(ears[0].position.x).toBeCloseTo(-ears[1].position.x, 8);
      expect(ears[0].position.y).toBeCloseTo(ears[1].position.y, 8);
      expect(ears[0].position.z).toBeCloseTo(ears[1].position.z, 8);
      for (const ear of ears) {
        expect(ear.scale.x).toBeLessThan(type.headR * 0.1);
        expect(ear.scale.y).toBeGreaterThan(ear.scale.x * 1.8);
        expect(Math.abs(ear.position.z)).toBeLessThan(type.headR * 0.1);
        expect(ear.material.color.getHex()).toBe(headMesh.material.color.getHex());
      }

      // 非结构性深色细节不得侵入头部；LatheGeometry 躯干内芯/装甲属于正常身体结构。
      rig.root.updateMatrixWorld(true);
      const headBottom = new THREE.Box3().setFromObject(headMesh).min.y;
      const misplacedParts = rig.bodyMeshes.filter((part) => (
        part.material === rig.materials[1] && part.geometry.type !== 'LatheGeometry' &&
        new THREE.Box3().setFromObject(part).max.y > headBottom + 0.001
      ));
      expect(misplacedParts).toEqual([]);

      const positions = headMesh.geometry.attributes.position;
      for (let i = 0; i < positions.count; i++) {
        expect(Number.isFinite(positions.getX(i))).toBe(true);
        expect(Number.isFinite(positions.getY(i))).toBe(true);
        expect(Number.isFinite(positions.getZ(i))).toBe(true);
      }

      // +Z 为平缓面部，-Z 为饱满后脑；禁止退回前后对称的球状头。
      headMesh.geometry.computeBoundingBox();
      const headBounds = headMesh.geometry.boundingBox;
      expect(headBounds.max.z).toBeLessThan(0.85);
      expect(-headBounds.min.z).toBeGreaterThan(headBounds.max.z * 1.35);
    });
  }
});
