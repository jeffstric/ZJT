/**
 * 不 mock spatial_3d_preview：验证 loadThree 真实从 ESM 图导出。
 * spatial_mannequin_glb.test.js 用 vi.mock 提供假导出，原先缺 export 时仍绿。
 */
import { describe, expect, it } from 'vitest';

describe('spatial_3d_preview ESM 导出', () => {
  it('loadThree 可被静态导入（缺 export 会在本文件 collect 阶段 SyntaxError）', async () => {
    const preview = await import('../js/storyboard/spatial_3d_preview.js');
    expect(typeof preview.loadThree).toBe('function');
    expect(typeof preview.hasSpatialLayout).toBe('function');
    expect(typeof preview.invalidateSpatialPreviewCache).toBe('function');
  });
});
