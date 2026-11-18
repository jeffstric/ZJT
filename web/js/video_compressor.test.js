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

  test('keeps the old compression method name as a compatibility alias', () => {
    const compressor = loadCompressor();

    expect(typeof compressor.compressVideoForReference).toBe('function');
    expect(typeof compressor.compressVideoTo480p).toBe('function');
  });
});

describe('VIDEO_COMPRESSOR buildRecorderResult (0 字节回退)', () => {
  const dims = { duration: 12, effectiveDuration: 10, outW: 854, outH: 480 };
  const videoInfo = { width: 1280, height: 720, duration: 12 };
  const originalFile = { name: 'src.mp4', size: 12345 };

  test('empty chunks (360极速浏览器等 MediaRecorder 异常) falls back to the original file', () => {
    const compressor = loadCompressor();

    const result = compressor.buildRecorderResult([], 'video/webm;codecs=vp8,opus', originalFile, videoInfo, dims);

    expect(result.compressed).toBe(false);
    expect(result.fallbackToOriginal).toBe(true);
    expect(result.blob).toBe(originalFile);
    expect(result.info).toBe(videoInfo);
  });

  test('non-empty chunks returns the compressed blob with output metadata', () => {
    const compressor = loadCompressor();
    const chunk = new Blob(['frame-data'], { type: 'video/webm' });

    const result = compressor.buildRecorderResult([chunk], 'video/webm;codecs=vp8,opus', originalFile, videoInfo, dims);

    expect(result.compressed).toBe(true);
    expect(result.blob.size).toBeGreaterThan(0);
    expect(result.blob.type).toBe('video/webm');
    expect(result.truncated).toBe(true);
    expect(result.info.outputWidth).toBe(854);
    expect(result.info.outputDuration).toBe(10);
  });
});

describe('VIDEO_COMPRESSOR vp8RetryMime (0 字节 VP8 降级重试)', () => {
  afterEach(() => {
    delete globalThis.MediaRecorder;
  });

  test('preferred vp9 (360极速浏览器场景) falls back to the first supported vp8 variant', () => {
    const compressor = loadCompressor();
    globalThis.MediaRecorder = {
      isTypeSupported: (m) => m.includes('vp8') || m.includes('vp9') || m === 'video/webm' || m === 'video/mp4',
    };

    expect(compressor.vp8RetryMime('video/webm;codecs=vp9,opus')).toBe('video/webm;codecs=vp8,opus');
  });

  test('preferred mime already in the vp8/webm family returns null (retry is pointless)', () => {
    const compressor = loadCompressor();
    globalThis.MediaRecorder = { isTypeSupported: () => true };

    expect(compressor.vp8RetryMime('video/webm;codecs=vp8,opus')).toBeNull();
    expect(compressor.vp8RetryMime('video/webm')).toBeNull();
  });

  test('no supported vp8 variant (Safari mp4-only scenario) returns null', () => {
    const compressor = loadCompressor();
    globalThis.MediaRecorder = { isTypeSupported: (m) => m === 'video/mp4' };

    expect(compressor.vp8RetryMime('video/mp4')).toBeNull();
  });

  test('MediaRecorder unavailable returns null', () => {
    const compressor = loadCompressor();

    expect(compressor.vp8RetryMime('video/webm;codecs=vp9,opus')).toBeNull();
  });
});
