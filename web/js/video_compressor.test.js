import { describe, expect, test } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

function loadCompressor() {
  const source = fs.readFileSync(path.resolve('web/js/video_compressor.js'), 'utf8');
  return new Function(`${source}; return VIDEO_COMPRESSOR;`)();
}

describe('VIDEO_COMPRESSOR reference video dimensions', () => {
  test('upscales 640x368 reference video to the Seedance minimum pixel count', () => {
    const compressor = loadCompressor();

    const dims = compressor.calculateOutputDimensions({ width: 640, height: 368 });

    expect(dims.width % 2).toBe(0);
    expect(dims.height % 2).toBe(0);
    expect(dims.width * dims.height).toBeGreaterThanOrEqual(409600);
    expect(dims.width / dims.height).toBeCloseTo(640 / 368, 1);
  });

  test('keeps 16:9 480p output above the minimum pixel count', () => {
    const compressor = loadCompressor();

    const dims = compressor.calculateOutputDimensions({ width: 1280, height: 720 });

    expect(dims).toEqual({ width: 854, height: 480 });
    expect(dims.width * dims.height).toBeGreaterThanOrEqual(409600);
  });
});
