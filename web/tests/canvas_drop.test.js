/**
 * 画布拖放：tif/tiff 白名单与超限 TIFF 不走前端压缩。
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

function makeFile(name, { type = '', size = 100 } = {}) {
  return { name, type, size };
}

function loadCanvasDrop({ compressResult } = {}) {
  const listeners = {};
  const container = {
    classList: { add() {}, remove() {} },
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    addEventListener: (type, handler) => {
      listeners[type] = handler;
    },
  };
  const created = { image: [], video: [] };
  const toasts = [];
  const compressImageFile = vi.fn(async (file) => (
    compressResult === undefined ? file : compressResult
  ));

  const context = {
    window: {
      t: (key) => `i18n:${key}`,
      isTiffFile: undefined,
    },
    document: {
      getElementById: (id) => (id === 'canvasContainer' ? container : null),
    },
    state: { panX: 0, panY: 0, zoom: 1 },
    MIN_NODE_Y: 0,
    canvasEl: { querySelector: () => null },
    createImageNode: (opts) => {
      created.image.push(opts);
      return `img-${created.image.length}`;
    },
    createVideoNode: (opts) => {
      created.video.push(opts);
      return `vid-${created.video.length}`;
    },
    showToast: (msg, kind) => {
      toasts.push({ msg, kind });
    },
    compressImageFile,
    console,
  };
  context.globalThis = context;
  context.window.isTiffFile = undefined;
  vm.createContext(context);
  vm.runInContext(readSource('web/js/tiff_support.js'), context);
  vm.runInContext(readSource('web/js/canvas_drop.js'), context);
  return { listeners, created, toasts, compressImageFile, context };
}

async function dropFiles(mod, files, extra = {}) {
  const event = {
    preventDefault() {},
    clientX: 40,
    clientY: 40,
    target: extra.target || null,
    dataTransfer: {
      types: ['Files'],
      files,
      dropEffect: 'copy',
    },
  };
  await mod.listeners.drop(event);
}

describe('canvas_drop TIFF 白名单', () => {
  it('源码白名单含 tif/tiff，且超限 TIFF 不调用 compressImageFile', () => {
    const src = readSource('web/js/canvas_drop.js');
    expect(src).toContain("'tif', 'tiff'");
    expect(src).toContain('isTiffUpload(file)');
    expect(src).toMatch(/if \(isTiffUpload\(file\)\) \{[\s\S]*canvas_drop_image_too_large/);
  });

  it('Windows 空 MIME 的 .tiff 按图片建节点，不提示不支持', async () => {
    const mod = loadCanvasDrop();
    await dropFiles(mod, [makeFile('scan.tiff', { type: '' })]);
    expect(mod.created.image).toHaveLength(1);
    expect(mod.toasts.some((t) => String(t.msg).includes('canvas_drop_only_media'))).toBe(false);
    expect(mod.compressImageFile).not.toHaveBeenCalled();
  });

  it('空 MIME 的 .tif 同样按图片建节点', async () => {
    const mod = loadCanvasDrop();
    await dropFiles(mod, [makeFile('scan.tif', { type: '' })]);
    expect(mod.created.image).toHaveLength(1);
  });

  it('超限 TIFF 直接拒绝，不走 compressImageFile', async () => {
    const mod = loadCanvasDrop({ compressResult: makeFile('fake.png', { type: 'image/png' }) });
    await dropFiles(mod, [makeFile('huge.tiff', { type: '', size: 12 * 1024 * 1024 })]);
    expect(mod.created.image).toHaveLength(0);
    expect(mod.compressImageFile).not.toHaveBeenCalled();
    expect(mod.toasts.some((t) => String(t.msg).includes('canvas_drop_image_too_large'))).toBe(true);
  });

  it('未识别扩展名仍提示仅支持图片/视频', async () => {
    const mod = loadCanvasDrop();
    await dropFiles(mod, [makeFile('notes.txt', { type: 'text/plain' })]);
    expect(mod.created.image).toHaveLength(0);
    expect(mod.created.video).toHaveLength(0);
    expect(mod.toasts.some((t) => String(t.msg).includes('canvas_drop_only_media'))).toBe(true);
  });
});
