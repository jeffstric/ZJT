/**
 * 营销智能体剪贴板媒体提取（0b7c8cf9 配套）。
 *
 * 契约：
 * - clipboardData.files 与 items 双来源合并（Chromium Windows 多文件复制时
 *   items 可能为空，chromium:41071856），按 名字|大小|修改时间 去重
 * - 截图/复制出的无名媒体按 MIME 重建带扩展名 File（图片上传校验按扩展名判断）
 * - 纯文本/非媒体类型不提取（不拦截默认粘贴行为）
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

const start = source.indexOf("const PASTE_IMAGE_EXTENSIONS");
const end = source.indexOf('// 剪贴板粘贴：含媒体文件时拦截默认行为');
const snippet = source.slice(start, end);
const factory = new Function(`${snippet}; return extractClipboardMediaFiles;`);
const extract = factory();

const makeFile = (name, type, size = 100, lastModified = 1700000000000) =>
  new File([new Uint8Array(size)], name, { type, lastModified });

const fakeItem = (file) => ({
  kind: 'file',
  getAsFile: () => file,
});

describe('extractClipboardMediaFiles', () => {
  it('files 与 items 双来源去重（同一文件只保留一份）', () => {
    const shared = makeFile('a.png', 'image/png', 120);
    const other = makeFile('b.png', 'image/png', 80);
    const result = extract({ files: [shared, other], items: [fakeItem(shared)] });
    expect(result).toHaveLength(2);
  });

  it('files 为空时仍能从 items 提取', () => {
    const img = makeFile('shot.png', 'image/png');
    const result = extract({ files: [], items: [fakeItem(img)] });
    expect(result).toHaveLength(1);
    expect(result[0]).toBe(img);
  });

  it('截图缺合法扩展名时按 MIME 重建为 clipboard_*.png', () => {
    // Chromium 截图文件名形如 image.png，但某些工具给出无扩展名/未知扩展名
    const shot = makeFile('image', 'image/png');
    const result = extract({ files: [shot], items: [] });
    expect(result).toHaveLength(1);
    expect(result[0].name).toMatch(/^clipboard_\d+_1\.png$/);
    expect(result[0].type).toBe('image/png');
  });

  it('带合法扩展名的图片不重建', () => {
    const img = makeFile('photo.jpg', 'image/jpeg');
    const result = extract({ files: [img], items: [] });
    expect(result[0]).toBe(img);
  });

  it('视频缺扩展名时按 MIME 重建（.mp4）', () => {
    const vid = makeFile('video', 'video/mp4', 2048);
    const result = extract({ files: [vid], items: [] });
    expect(result[0].name).toMatch(/^clipboard_\d+_1\.mp4$/);
  });

  it('带扩展名的视频不重建', () => {
    const vid = makeFile('clip.mp4', 'video/mp4', 2048);
    expect(extract({ files: [vid], items: [] })[0]).toBe(vid);
  });

  it('音频媒体同样提取', () => {
    const audio = makeFile('voice', 'audio/mpeg', 512);
    const result = extract({ files: [audio], items: [] });
    expect(result[0].name).toMatch(/^clipboard_\d+_1\.mp3$/);
  });

  it('纯文本条目（kind=string）不提取', () => {
    const result = extract({
      files: [],
      items: [{ kind: 'string' }],
    });
    expect(result).toEqual([]);
  });

  it('非媒体 MIME 类型跳过', () => {
    const pdf = makeFile('doc.pdf', 'application/pdf');
    expect(extract({ files: [pdf], items: [] })).toEqual([]);
  });

  it('clipboardData 为空返回空数组', () => {
    expect(extract(null)).toEqual([]);
    expect(extract(undefined)).toEqual([]);
  });
});

describe('handleDocumentPaste 拦截契约（源码断言）', () => {
  it('仅含媒体时 preventDefault 并走统一上传链路', () => {
    const body = source.slice(
      source.indexOf('function handleDocumentPaste'),
      source.indexOf('function selectType')
    );
    expect(body).toContain('extractClipboardMediaFiles(e.clipboardData)');
    expect(body).toContain('if (files.length === 0) return');
    expect(body).toContain('e.preventDefault()');
    expect(body).toContain('processSelectedFiles(files)');
  });
});
