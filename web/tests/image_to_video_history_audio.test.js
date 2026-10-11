/**
 * 首页图生视频历史：参考音频按逗号拆开，供播放器逐段使用。
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/pages/image_to_video.js'), 'utf8');

function loadPage() {
  const context = { window: {}, console };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.window.ImageToVideo.methods;
}

describe('image to video history audio', () => {
  it('splits comma-separated audio urls', () => {
    const methods = loadPage();
    expect(methods.parseAudioPaths(
      'http://localhost:13003/upload/a.wav, http://localhost:13003/upload/b.mp3'
    )).toEqual([
      'http://localhost:13003/upload/a.wav',
      'http://localhost:13003/upload/b.mp3',
    ]);
  });

  it('accepts a json array and ignores blanks', () => {
    const methods = loadPage();
    expect(methods.parseAudioPaths('["http://localhost/a.mp3", " "]')).toEqual([
      'http://localhost/a.mp3',
    ]);
    expect(methods.parseAudioPaths('')).toEqual([]);
    expect(methods.parseAudioPaths(null)).toEqual([]);
  });

  it('renders an audio player for each path', () => {
    expect(source).toContain('parseAudioPaths(item.audio_path)');
    expect(source).toContain('<audio :src="audio" controls preload="metadata"');
  });
});
