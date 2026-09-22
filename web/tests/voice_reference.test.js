/**
 * 参考生视频角色音色注入测试（voice_reference.js）。
 *
 * 行为测试：vm 沙箱加载脚本（mock window.TaskConfig 能力位），验证
 * 收集/去重/上限/绝对 URL/说明文案/幂等追加；
 * 接线测试：三类节点提交处与 task_config.js 透传、video_workflow.html 引脚本。
 */

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (p) => fs.readFileSync(path.join(root, p), 'utf8');

function loadVoiceModule(taskConfigs) {
  const context = {
    window: {
      TaskConfig: {
        isLoaded: () => true,
        getModelConfigs: () => taskConfigs,
      },
    },
    location: { origin: 'http://test.local' },
    URL, // 浏览器内建，vm 沙箱需显式注入
    showToast: () => {},
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(readSource('web/js/voice_reference.js'), context);
  return context;
}

const CHARACTERS = [
  { name: '林悦', default_voice: '/upload/character/voice/linyue.wav' },
  { name: '张三', default_voice: '/upload/character/voice/zhangsan.wav' },
  { name: '无音色', default_voice: '' },
  { name: '王五', default_voice: '/upload/character/voice/wangwu.wav' },
];

describe('collectVoiceReferences 行为', () => {
  it('模型不支持音色输入（grok 等）时不注入任何内容', () => {
    const m = loadVoiceModule({ grok: { supports_voice_input: false }, seedance_2_0: { supports_voice_input: true } });
    expect(m.collectVoiceReferences('grok', CHARACTERS, '')).toEqual({
      enabled: false,
      voiceUrls: [],
      names: [],
      promptNote: '',
    });
    // TaskConfig 未加载时同样按不支持处理
    const unloaded = (() => {
      const context = {
        window: { TaskConfig: { isLoaded: () => false, getModelConfigs: () => ({}) } },
        location: { origin: 'http://test.local' },
      };
      context.globalThis = context;
      vm.createContext(context);
      vm.runInContext(readSource('web/js/voice_reference.js'), context);
      return context;
    })();
    expect(unloaded.collectVoiceReferences('seedance_2_0', CHARACTERS, '').enabled).toBe(false);
  });

  it('支持的模型收集角色音色：跳过无音色、上限 2 条、相对路径转绝对 URL', () => {
    const m = loadVoiceModule({ seedance_2_0: { supports_voice_input: true } });
    const refs = m.collectVoiceReferences('seedance_2_0', CHARACTERS, '');
    expect(refs.enabled).toBe(true);
    expect(refs.voiceUrls).toEqual([
      'http://test.local/upload/character/voice/linyue.wav',
      'http://test.local/upload/character/voice/zhangsan.wav',
    ]);
    expect(refs.names).toEqual(['林悦', '张三']);
    expect(refs.promptNote).toBe(
      '参考音频说明：音频1是角色：林悦的音色样本，音频2是角色：张三的音色样本，角色说话时请保持相同音色。'
    );
  });

  it('与用户已携带音频按 URL 去重，说明序号对齐最终合并位置', () => {
    const m = loadVoiceModule({ minimax_h3_r2v: { supports_voice_input: true } });
    const refs = m.collectVoiceReferences(
      'minimax_h3_r2v',
      CHARACTERS,
      'http://cdn.existing.wav,http://test.local/upload/character/voice/linyue.wav'
    );
    expect(refs.voiceUrls).toEqual([
      'http://test.local/upload/character/voice/zhangsan.wav',
      'http://test.local/upload/character/voice/wangwu.wav',
    ]);
    expect(refs.promptNote).toContain('音频3是角色：张三的音色样本');
    expect(refs.promptNote).toContain('音频4是角色：王五的音色样本');
  });

  it('appendVoiceReferencePrompt 幂等追加，notifyVoiceReferences 不抛错', () => {
    const m = loadVoiceModule({ seedance_2_0: { supports_voice_input: true } });
    const refs = m.collectVoiceReferences('seedance_2_0', CHARACTERS.slice(0, 1), '');
    const prompt = m.appendVoiceReferencePrompt('镜头内容', refs.promptNote);
    expect(prompt).toBe('镜头内容\n\n' + refs.promptNote);
    expect(m.appendVoiceReferencePrompt(prompt, refs.promptNote)).toBe(prompt);
    expect(() => m.notifyVoiceReferences(1)).not.toThrow();
  });
});

describe('画布三类节点接线', () => {
  it('task_config.js 透传 supports_voice_input 能力位', () => {
    expect(readSource('web/js/task_config.js')).toContain(
      'supports_voice_input: task.supports_voice_input === true'
    );
  });

  it('video_workflow.html 引入 voice_reference.js（先于 shot_frame_video_generator.js）', () => {
    const html = readSource('web/video_workflow.html');
    const voiceAt = html.indexOf('/js/voice_reference.js');
    const consumerAt = html.indexOf('/js/shot_frame_video_generator.js');
    expect(voiceAt).toBeGreaterThan(-1);
    expect(consumerAt).toBeGreaterThan(voiceAt);
  });

  it('生视频节点：multi_reference 提交时注入连线角色音色', () => {
    const src = readSource('web/js/image_to_video_node.js');
    expect(src).toContain("currentImageMode === 'multi_reference' && typeof collectVoiceReferences === 'function'");
    expect(src).toContain("collectVoiceReferences(videoModel, voiceCharacters, allAudioUrls.join(','))");
  });

  it('分镜节点：参考模式消费 voiceCharacters 并写入 audio_urls', () => {
    const collector = readSource('web/js/shot_frame_generator.js');
    expect(collector).toContain('const voiceCharacters = [];');
    expect(collector).toContain("return { referenceImageUrls, promptSuffix, missingCharacters, voiceCharacters, characterRefUrls };");

    const generator = readSource('web/js/shot_frame_video_generator.js');
    expect(generator).toContain('voiceCharacters, characterRefUrls } = await collectShotFrameRefImages(node)');
    expect(generator).toContain("collectVoiceReferences(videoModel, voiceCharacters || [], '')");
    expect(generator).toContain("form.append('audio_urls', voiceRefs.voiceUrls.join(','))");
  });

  it('分镜组节点：参考模式消费 gridVoiceCharacters 并写入 audio_urls', () => {
    const src = readSource('web/js/nodes.js');
    expect(src).toContain('voiceCharacters: _voiceCharacters, characterRefUrls: _characterRefUrls } = await collectReferenceImagesForGrid(shotFrameNodes)');
    expect(src).toContain('collectVoiceReferences(videoModel || \'wan22\', gridVoiceCharacters, \'\')');
  });
});
