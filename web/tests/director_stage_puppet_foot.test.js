/**
 * 导演台人偶脚部几何回归测试。
 *
 * 每只脚必须是单一连续脚型（外加踝关节球/环），具有明确 +Z 脚尖方向，
 * 默认站姿下脚底落在地面 y=0，禁止回退为多个椭球叠加的圆饼靴。
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
    `${match[1]}
return { BODY_TYPES, buildPuppetRig };`)(THREE, 'idle', null, undefined, undefined);
}

const { BODY_TYPES, buildPuppetRig } = loadPuppetGeometry();

describe('导演台：符合人体方向与比例的脚型', () => {
  for (const bodyType of Object.keys(BODY_TYPES)) {
    it(`${bodyType} 双脚为单一连续曲面、脚尖朝前且默认贴地`, () => {
      const rig = buildPuppetRig('#4f8ef7', bodyType);
      rig.root.updateMatrixWorld(true);

      for (const side of ['L', 'R']) {
        const ankle = rig.joints[`ankle${side}`];
        const visibleMeshes = ankle.children.filter((part) => part.isMesh && part.visible);
        // 踝关节球 + 咬合环 + 一只脚，不再出现鞋底/鞋身/后跟/踝领等叠加件。
        expect(visibleMeshes).toHaveLength(3);
        const feet = visibleMeshes.filter((part) => part.geometry.type === 'LatheGeometry');
        expect(feet).toHaveLength(1);

        const foot = feet[0];
        const bounds = new THREE.Box3().setFromObject(foot);
        const size = bounds.getSize(new THREE.Vector3());
        expect(bounds.min.y).toBeCloseTo(0, 5);
        expect(size.z / size.x).toBeGreaterThan(1.6);
        expect(bounds.max.z / -bounds.min.z).toBeGreaterThan(1.3);
        expect(foot.material).toBe(rig.materials[0]);
      }
    });
  }
});
