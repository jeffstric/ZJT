/**
 * 音色库选择器（Vue 3 组件，仅 index.html 声音页使用）
 *
 * - 卡片网格：音色名 + 人设描述 + 标签（性别/语言/风格）
 * - 筛选：全部 / 女声 / 男声 / 方言
 * - 试听：调服务端缓存接口（固定示例句，免费），前端内存去重防连点
 * - v-model：选中的 voice_id（null=未选）
 *
 * 数据渲染全部使用 {{ }} 插值（Vue 自动转义），音色文案来自后端运营配置，
 * 不做任何 v-html（前端安全红线，见 AGENTS.md X 系列）。
 */
(function (global) {
  'use strict';

  var GENDER_LABELS = { female: '女声', male: '男声', child: '童声' };
  var LANGUAGE_LABELS = { zh: '中文', 'zh-dialect': '方言', en: '英文', ja: '日语' };

  var VoicePicker = {
    name: 'VoicePicker',
    props: {
      modelValue: { type: Number, default: null },
      loading: { type: Boolean, default: false },
    },
    emits: ['update:modelValue'],
    data: function () {
      return {
        voices: [],
        powerTiers: [],
        maxTextLength: 2000,
        configured: true,
        loadError: '',
        loadingVoices: false,
        filter: 'all',
        previewingId: null,
        previewAudio: null,
        previewCache: {},   // voice_id -> audio_url（后端也有缓存，这里是防连点）
        previewError: '',
      };
    },
    computed: {
      filteredVoices: function () {
        if (this.filter === 'all') return this.voices;
        return this.voices.filter(function (v) {
          return v.gender === this.filter;
        }, this);
      },
      genderLabel: function () {
        return function (v) { return GENDER_LABELS[v.gender] || ''; };
      },
      langLabel: function () {
        return function (v) { return LANGUAGE_LABELS[v.language] || ''; };
      },
    },
    mounted: function () {
      this.fetchVoices();
    },
    beforeUnmount: function () {
      this.stopPreview();
    },
    methods: {
      fetchVoices: async function () {
        this.loadingVoices = true;
        this.loadError = '';
        try {
          var data = await global.VoiceLibraryApi.listVoices({ page_size: 200 });
          this.voices = data.voices || [];
          this.powerTiers = data.power_tiers || [];
          this.maxTextLength = data.max_text_length || 2000;
          this.configured = !!data.configured;
        } catch (e) {
          this.loadError = (e && e.message) || '音色库加载失败';
        } finally {
          this.loadingVoices = false;
        }
      },
      select: function (voice) {
        if (!voice || voice.id === this.modelValue) return;
        this.$emit('update:modelValue', voice.id);
        this.$emit('voice-selected', voice);
      },
      estimateCost: function (charCount) {
        return global.VoiceLibraryApi.estimatePower(charCount, this.powerTiers);
      },
      stopPreview: function () {
        if (this.previewAudio) {
          this.previewAudio.pause();
          this.previewAudio = null;
        }
      },
      playPreview: async function (voice) {
        this.previewError = '';
        if (this.previewingId === voice.id) { this.stopPreview(); this.previewingId = null; return; }
        this.stopPreview();
        this.previewingId = voice.id;
        try {
          var url;
          if (this.previewCache[voice.id]) {
            url = this.previewCache[voice.id];
          } else {
            var data = await global.VoiceLibraryApi.previewVoice(voice.id);
            url = data.audio_url;
            this.previewCache[voice.id] = url;
          }
          if (this.previewingId !== voice.id) return; // 已切换目标，丢弃
          var audio = new Audio(url);
          var self = this;
          audio.onended = function () { self.previewingId = null; };
          audio.onerror = function () { self.previewingId = null; self.previewError = '试听失败，请稍后重试'; };
          this.previewAudio = audio;
          audio.play();
        } catch (e) {
          this.previewingId = null;
          this.previewError = (e && e.message) || '试听失败';
        }
      },
    },
    template: `
      <div class="voice-picker">
        <div v-if="!configured" class="status danger" style="margin-bottom: 8px;">
          火山语音合成尚未配置，请联系管理员填写 volcengine_tts 配置
        </div>
        <div v-if="loadError" class="status danger" style="margin-bottom: 8px;">{{ loadError }}</div>
        <div v-if="loadingVoices" class="muted" style="padding: 12px 0;">音色库加载中...</div>

        <template v-else>
          <div style="display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap;">
            <button v-for="opt in [{k:'all',t:'全部'},{k:'female',t:'女声'},{k:'male',t:'男声'}]"
              :key="opt.k" class="btn secondary" style="padding: 2px 12px; font-size: 13px;"
              :style="filter === opt.k ? 'border-color: var(--primary); color: var(--primary);' : ''"
              @click="filter = opt.k">{{ opt.t }}</button>
          </div>

          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; max-height: 320px; overflow-y: auto; padding: 2px;">
            <div v-for="v in filteredVoices" :key="v.id"
              style="border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; position: relative;"
              :style="modelValue === v.id ? 'border-color: var(--primary); background: rgba(25,118,210,0.06);' : ''"
              @click="select(v)">
              <div v-if="modelValue === v.id"
                style="position: absolute; top: 6px; right: 8px; color: var(--primary); font-weight: 700;">✓</div>
              <div style="font-weight: 600; font-size: 14px; margin-bottom: 4px; padding-right: 16px;">{{ v.name }}</div>
              <div style="font-size: 12px; color: var(--muted); line-height: 1.4; height: 2.8em; overflow: hidden;">{{ v.description }}</div>
              <div style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px;">
                <span style="font-size: 11px; background: var(--border); border-radius: 8px; padding: 0 6px;">{{ genderLabel(v) }}</span>
                <span style="font-size: 11px; background: var(--border); border-radius: 8px; padding: 0 6px;">{{ v.style }}</span>
                <span v-if="langLabel(v)" style="font-size: 11px; background: var(--border); border-radius: 8px; padding: 0 6px;">{{ langLabel(v) }}</span>
              </div>
              <button class="btn secondary" style="width: 100%; margin: 8px 0 0; padding: 2px 0; font-size: 12px;"
                :disabled="previewingId === v.id"
                @click.stop="playPreview(v)">
                {{ previewingId === v.id ? '播放中…' : '▶ 试听' }}
              </button>
            </div>
          </div>
          <div v-if="previewError" class="status danger" style="margin-top: 8px;">{{ previewError }}</div>
          <div v-if="!filteredVoices.length" class="muted" style="padding: 12px 0;">暂无音色</div>
        </template>
      </div>
    `,
  };

  global.VoicePicker = VoicePicker;
})(window);
