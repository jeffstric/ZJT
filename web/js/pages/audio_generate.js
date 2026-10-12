  const AudioGenerate = {
    name: 'AudioGenerate',
    data() {
      return {
        // 合成引擎：voice_library=火山音色库（快速合成，扣算力）；
        // clone=参考音频克隆（IndexTTS，异步任务，免费）。默认音色库（零门槛+秒级）。
        engine: 'voice_library',
        // —— 音色库（火山）模式 ——
        voiceId: null,
        selectedVoice: null,
        speedRatio: 1.0,
        powerTiers: [],
        maxTextLength: 2000,
        // —— 克隆（IndexTTS）模式（原有字段，勿动） ——
        text: '',
        refAudioFile: null,
        // 克隆参考音频来源：upload=本地上传；library=从音色库选择（用其样例音频作克隆参考）
        refSource: 'upload',
        cloneVoiceId: null,
        cloneVoices: [],
        cloneVoicesLoading: false,
        clonePreviewing: false,
        emoRefAudioFile: null,
        emoRefType: 'file',
        emoRefVideoUrl: '',
        emoText: '',
        emoWeight: 1,
        emoControlMethod: 0,
        emoVec: [0, 0, 0, 0, 0, 0, 0, 0],
        loading: false,
        error: '',
        result: null,
        audioId: null,
        status: '',
        statusInterval: null,
        authToken: '',
        resultAudioUrl: '',
      }
    },
    mounted() {
      this.authToken = localStorage.getItem('auth_token') || '';
    },
    computed: {
      // 音色库模式：文本 + 已选音色
      canSubmitVoiceLibrary() {
        return !!(this.text.trim() && this.voiceId && !this.loading);
      },
      canSubmit() {
        if (this.engine === 'voice_library') return this.canSubmitVoiceLibrary;
        if (!this.text.trim() || this.loading) return false;
        // 克隆参考来源为音色库时必须已选音色
        if (this.refSource === 'library' && !this.cloneVoiceId) return false;
        if (this.emoControlMethod === 2 && !this.emoVecValid) return false;
        return true;
      },
      estimatedPower() {
        return window.VoiceLibraryApi
          ? window.VoiceLibraryApi.estimatePower(this.text.trim().length, this.powerTiers)
          : 0;
      },
      textTooLong() {
        return this.text.trim().length > this.maxTextLength;
      },
      emoControlOptions() {
        return [
          { value: 0, label: this.$t('same_as_reference') },
          { value: 1, label: this.$t('use_emotion_reference') },
          { value: 2, label: this.$t('use_emotion_vector') },
          { value: 3, label: this.$t('use_emotion_description') }
        ];
      },
      emoVecLabels() {
        return ['喜', '怒', '哀', '惧', '厌恶', '低落', '惊喜', '平静'];
      },
      emoVecSum() {
        return this.emoVec.reduce((sum, val) => sum + val, 0);
      },
      emoVecValid() {
        return this.emoVecSum <= 1.5;
      },
      statusText() {
        if (this.status === 'submitted') return this.$t('audio_submit_text');
        if (this.loading) return this.$t('audio_generating');
        if (this.result) return this.$t('audio_generate_complete');
        return '';
      }
    },
    methods: {
      // —— 音色库（火山快速合成）——
      onVoiceSelected(voice) {
        this.selectedVoice = voice;
      },

      async submitVoiceLibrary() {
        if (!this.canSubmitVoiceLibrary) return;
        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = '请先登录后再使用音频生成功能';
          return;
        }
        this.loading = true;
        this.error = '';
        this.result = null;
        this.clearResultAudioUrl();
        this.audioId = null;
        this.status = '';
        this.clearStatusCheck();
        try {
          const data = await window.VoiceLibraryApi.synthesize({
            text: this.text.trim(),
            voice_id: this.voiceId,
            speed_ratio: this.speedRatio,
          });
          this.audioId = data.audio_id;
          this.result = { file_url: data.audio_url };
          this.setResultAudioUrl(data.audio_url);
          this.status = 'SUCCESS';
        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || err?.message || '请求失败';
          this.status = 'FAILED';
        } finally {
          this.loading = false;
        }
      },

      // —— 克隆模式：从音色库选择参考声音 ——
      async fetchCloneVoices() {
        if (this.cloneVoices.length || !window.VoiceLibraryApi) return;
        this.cloneVoicesLoading = true;
        try {
          const data = await window.VoiceLibraryApi.listVoices({ page_size: 300 });
          const locale = (window.ZJTi18n && window.ZJTi18n.getLocale) ? window.ZJTi18n.getLocale() : (localStorage.getItem('zjt_locale') || 'zh-CN');
          const wantLang = String(locale).toLowerCase().indexOf('en') === 0 ? 'en' : 'zh';
          const all = data.voices || [];
          // 界面语言对应的音色排前，其余语言跟后（保持完整可选列表）
          this.cloneVoices = all.slice().sort((a, b) => (b.language === wantLang) - (a.language === wantLang));
        } catch (e) {
          console.error('克隆音色列表加载失败:', e);
        } finally {
          this.cloneVoicesLoading = false;
        }
      },

      async playClonePreview() {
        if (!this.cloneVoiceId || this.clonePreviewing || !window.VoiceLibraryApi) return;
        this.clonePreviewing = true;
        try {
          const data = await window.VoiceLibraryApi.previewVoice(this.cloneVoiceId);
          if (data.audio_url) new Audio(data.audio_url).play();
        } catch (e) {
          alert((e && e.message) || '试听失败');
        } finally {
          this.clonePreviewing = false;
        }
      },

      // —— 克隆模式（IndexTTS，原有逻辑勿动） ——
      validateAudioDuration(file, label) {
        return new Promise((resolve) => {
          const audio = new Audio();
          const url = URL.createObjectURL(file);
          audio.onloadedmetadata = () => {
            URL.revokeObjectURL(url);
            if (audio.duration > 20) {
              this.error = label + '时长不能超过20秒，当前时长：' + audio.duration.toFixed(1) + '秒';
              resolve(false);
            } else {
              resolve(true);
            }
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            this.error = label + '文件无法播放，请确认是有效的音频文件';
            resolve(false);
          };
          audio.src = url;
        });
      },
      async onRefAudioFile(e) {
        const file = e.target.files[0] || null;
        if (!file) { this.refAudioFile = null; return; }
        const valid = await this.validateAudioDuration(file, '参考音频');
        this.refAudioFile = valid ? file : null;
        if (!valid) e.target.value = '';
      },
      async onEmoRefAudioFile(e) {
        const file = e.target.files[0] || null;
        if (!file) { this.emoRefAudioFile = null; return; }
        const valid = await this.validateAudioDuration(file, '情感参考音频');
        this.emoRefAudioFile = valid ? file : null;
        if (!valid) e.target.value = '';
      },

      submit() {
        if (this.engine === 'voice_library') {
          return this.submitVoiceLibrary();
        }
        return this.submitClone();
      },

      async submitClone() {
        if (!this.canSubmit) return;

        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = '请先登录后再使用音频生成功能';
          return;
        }

        this.loading = true;
        this.error = '';
        this.result = null;
        this.clearResultAudioUrl();
        this.audioId = null;
        this.status = '';
        this.clearStatusCheck();

        try {
          const form = new FormData();
          form.append('text', this.text);
          form.append('user_id', userId);
          form.append('emo_control_method', this.emoControlMethod);

          if (this.refSource === 'library' && this.cloneVoiceId) {
            // 音色库声音作克隆参考：取该音色的样例音频 URL（服务端缓存，免费）
            const preview = await window.VoiceLibraryApi.previewVoice(this.cloneVoiceId);
            form.append('ref_audio_url', preview.audio_url);
          } else if (this.refAudioFile) {
            form.append('ref_audio', this.refAudioFile);
          }

          if (this.emoRefType === 'file' && this.emoRefAudioFile) {
            form.append('emo_ref_audio', this.emoRefAudioFile);
          } else if (this.emoRefType === 'video_url' && this.emoRefVideoUrl) {
            form.append('emo_ref_video_url', this.emoRefVideoUrl);
          }

          if (this.emoText) {
            form.append('emo_text', this.emoText);
          }

          if (this.emoWeight !== null) {
            form.append('emo_weight', this.emoWeight);
          }

          if (this.emoControlMethod === 2) {
            form.append('emo_vec', this.emoVec.join(','));
          }

          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const res = await axios.post('/api/audio-generate', form, {
            headers: {
              'Content-Type': 'multipart/form-data',
              // 权限装饰器只认 Authorization 头（FormData 里的 auth_token 是旧版遗留）
              ...(this.authToken ? { Authorization: 'Bearer ' + this.authToken } : {}),
            },
          });

          this.audioId = res.data.audio_id;
          this.status = res.data.status || 'submitted';

          if (this.audioId) {
            this.startStatusCheck();
          }

        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || err?.message || '请求失败';
          this.loading = false;
        }
      },

      async checkStatus() {
        if (!this.audioId) return;

        try {
          const authToken = localStorage.getItem('auth_token');
          const params = authToken ? { auth_token: authToken } : {};

          const res = await axios.get(`/api/audio-status/${this.audioId}`, {
            params
          });

          const payload = res.data;

          if (!payload) {
            console.error('Invalid status response:', payload);
            return;
          }

          const status = typeof payload.status === 'string' ? payload.status.toUpperCase() : payload.status;

          if (status === 'SUCCESS' || status === 2) {
            this.result = payload.result_url ? { file_url: payload.result_url } : null;
            if (payload.result_url) {
              this.setResultAudioUrl(payload.result_url);
            }
            this.status = 'SUCCESS';
            this.loading = false;
            this.clearStatusCheck();
          } else if (status === 'FAILED' || status === -1) {
            this.error = payload.reason || payload.message || '任务失败';
            this.status = 'FAILED';
            this.loading = false;
            this.clearStatusCheck();
          } else {
            this.status = 'RUNNING';
          }
        } catch (err) {
          console.error('Status check failed:', err);
        }
      },

      startStatusCheck() {
        this.statusInterval = setInterval(() => {
          this.checkStatus();
        }, 10000);
      },

      clearStatusCheck() {
        if (this.statusInterval) {
          clearInterval(this.statusInterval);
          this.statusInterval = null;
        }
      },

      setResultAudioUrl(url) {
        this.clearResultAudioUrl();
        this.resultAudioUrl = url;
      },

      clearResultAudioUrl() {
        // 仅清理 blob URL；http(s) URL 是服务器地址，revoke 无意义且误伤
        if (this.resultAudioUrl && this.resultAudioUrl.startsWith('blob:')) {
          URL.revokeObjectURL(this.resultAudioUrl);
        }
        this.resultAudioUrl = '';
      },

      generateAudioFilename(url) {
        const now = new Date();
        const dateStr = now.getFullYear().toString() +
                       (now.getMonth() + 1).toString().padStart(2, '0') +
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') +
                       now.getMinutes().toString().padStart(2, '0');
        const ext = /\.(mp3|wav|aac|ogg|m4a)(\?|$)/i.exec(url || '')?.[1] || 'mp3';
        return `audio_${dateStr}_${timeStr}.${ext}`;
      },

      async downloadAudio(url) {
        if (!url) return;
        const filename = this.generateAudioFilename(url);
        try {
          await downloadWithAuth(url, filename);
        } catch (e) {
          if (e && e.status === 401) return;
          alert((e && e.message) || '下载失败');
        }
      }
    },
    beforeUnmount() {
      this.clearStatusCheck();
      this.clearResultAudioUrl();
    },
    template: `
      <div class="form">
        <!-- 合成模式切换 -->
        <div class="field">
          <div style="display: flex; gap: 8px;">
            <button class="btn" :style="engine === 'voice_library' ? '' : 'background: transparent; color: var(--text); border: 1px solid var(--border);'"
              style="flex: 1;" @click="engine = 'voice_library'">{{ $t('tts_mode_voice_library') }}</button>
            <button class="btn" :style="engine === 'clone' ? '' : 'background: transparent; color: var(--text); border: 1px solid var(--border);'"
              style="flex: 1;" @click="engine = 'clone'">{{ $t('tts_mode_clone') }}</button>
          </div>
          <div class="muted" style="margin-top: 6px;">
            {{ engine === 'voice_library' ? $t('tts_mode_voice_library_tip') : $t('tts_mode_clone_tip') }}
          </div>
        </div>

        <div class="field">
          <label class="label">{{ $t('generate_text') }} <span style="color: red;">*</span></label>
          <textarea class="input" v-model="text" :placeholder="$t('enter_text_to_speech')" rows="4"></textarea>
          <div v-if="engine === 'voice_library'" class="muted" style="margin-top: 4px;">
            {{ text.trim().length }} / {{ maxTextLength }} {{ textTooLong ? '· ' + $t('tts_text_too_long') : '' }}
          </div>
        </div>

        <!-- ============ 音色库（火山快速合成）模式 ============ -->
        <template v-if="engine === 'voice_library'">
          <div class="field">
            <label class="label">{{ $t('tts_select_voice') }} <span style="color: red;">*</span></label>
            <voice-picker v-model="voiceId" :loading="loading" @voice-selected="onVoiceSelected"></voice-picker>
          </div>

          <div class="field">
            <label class="label">{{ $t('tts_speed_ratio') }} ({{ speedRatio }}x)</label>
            <input type="range" v-model.number="speedRatio" min="0.5" max="2" step="0.1" style="width: 100%;" />
          </div>

          <div class="field">
            <button class="btn" @click="submit" :disabled="!canSubmit || textTooLong">
              {{ loading ? $t('generating') : $t('start_generating') }}
            </button>
            <div v-if="text.trim() && voiceId" class="muted" style="margin-top: 6px;">
              <template v-if="estimatedPower > 0">{{ $t('tts_estimated_cost', { power: estimatedPower }) }}</template>
              <template v-else>{{ $t('tts_cost_unavailable') }}</template>
            </div>
          </div>
        </template>

        <!-- ============ 参考音频克隆（IndexTTS，原有表单） ============ -->
        <template v-else>
          <div class="field">
            <label class="label">{{ $t('reference_audio') }}（{{ $t('optional') }}）</label>
            <div style="display: flex; gap: 8px; margin-bottom: 8px;">
              <button type="button" class="btn secondary" style="padding: 2px 12px; font-size: 13px;"
                :style="refSource === 'library' ? 'border-color: var(--primary); color: var(--primary);' : ''"
                :disabled="loading" @click="refSource = 'library'; fetchCloneVoices()">{{ $t('tts_ref_source_library') }}</button>
              <button type="button" class="btn secondary" style="padding: 2px 12px; font-size: 13px;"
                :style="refSource === 'upload' ? 'border-color: var(--primary); color: var(--primary);' : ''"
                :disabled="loading" @click="refSource = 'upload'">{{ $t('tts_ref_source_upload') }}</button>
            </div>

            <template v-if="refSource === 'library'">
              <div style="display: flex; gap: 8px; align-items: center;">
                <select class="input" v-model="cloneVoiceId" style="flex: 1;" :disabled="loading || cloneVoicesLoading">
                  <option :value="null">{{ cloneVoicesLoading ? $t('tts_voice_loading') : $t('tts_voice_placeholder') }}</option>
                  <option v-for="v in cloneVoices" :key="v.id" :value="v.id">{{ v.name }}（{{ v.style }}）</option>
                </select>
                <button type="button" class="btn secondary" style="flex-shrink: 0; padding: 4px 10px; font-size: 13px;"
                  :disabled="!cloneVoiceId || clonePreviewing" @click="playClonePreview">
                  {{ clonePreviewing ? $t('tts_preview_playing') : '▶ ' + $t('tts_preview') }}
                </button>
              </div>
              <div class="muted" style="margin-top: 4px;">{{ $t('tts_ref_source_library_tip') }}</div>
            </template>

            <template v-else>
              <input type="file" @change="onRefAudioFile" accept="audio/*" class="input" :disabled="loading">
              <div class="muted" style="margin-top: 4px;">{{ $t('audio_cloning_tip') }}（{{ $t('max_20_seconds') }}）</div>
            </template>
          </div>

          <div class="field">
            <label class="label">{{ $t('emotion_control_method') }}</label>
            <select class="input" v-model="emoControlMethod">
              <option v-for="opt in emoControlOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field" v-if="emoControlMethod === 1">
            <label class="label">情感参考音频</label>
            <div style="margin-bottom: 8px;">
              <label style="display: inline-flex; align-items: center; margin-right: 16px; cursor: pointer;">
                <input type="radio" v-model="emoRefType" value="file" style="margin-right: 4px;" :disabled="loading">
                <span>{{ $t('upload_audio_file') }}</span>
              </label>
              <label style="display: inline-flex; align-items: center; cursor: pointer;">
                <input type="radio" v-model="emoRefType" value="video_url" style="margin-right: 4px;" :disabled="loading">
                <span>{{ $t('video_link') }}</span>
              </label>
            </div>
            <input v-if="emoRefType === 'file'" type="file" @change="onEmoRefAudioFile" accept="audio/*" class="input" :disabled="loading">
            <input v-if="emoRefType === 'video_url'" type="text" v-model="emoRefVideoUrl" :placeholder="$t('enter_video_url')" class="input" :disabled="loading">
            <div class="muted" style="margin-top: 4px;" v-if="emoRefType === 'file'">{{ $t('emotion_reference_audio') }}</div>
            <div class="muted" style="margin-top: 4px;" v-if="emoRefType === 'video_url'">{{ $t('extract_audio_auto') }}</div>
          </div>

          <div class="field" v-if="emoControlMethod === 2">
            <label class="label">{{ $t('emotion_vector_control') }}</label>
            <div style="margin-bottom: 16px;">
              <div v-for="(label, idx) in emoVecLabels" :key="idx" style="margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                  <span style="font-size: 14px;">{{ label }}</span>
                  <span style="font-size: 14px; color: var(--primary);">{{ emoVec[idx].toFixed(2) }}</span>
                </div>
                <input type="range" v-model.number="emoVec[idx]" min="0" max="1.5" step="0.01" style="width: 100%;" />
              </div>
            </div>
            <div class="muted" style="margin-top: 8px;">
              {{ $t('emotion_sum') }}: <span :style="{color: emoVecValid ? 'var(--success)' : 'var(--danger)', fontWeight: 'bold'}">{{ emoVecSum.toFixed(2) }}</span> / 1.5
              <span v-if="!emoVecValid" style="color: var(--danger); margin-left: 8px;">{{ $t('emotion_exceeded') }}</span>
            </div>
          </div>

          <div class="field" v-if="emoControlMethod === 3">
            <label class="label">{{ $t('description') }}</label>
            <input class="input" v-model="emoText" :placeholder="$t('emotion_description_text')" />
          </div>

          <div class="field" v-if="emoControlMethod === 1">
            <label class="label">{{ $t('emotion_weight') }} ({{ emoWeight }})</label>
            <input type="range" v-model.number="emoWeight" min="0" max="1.6" step="0.1" style="width: 100%;" />
            <div class="muted" style="margin-top: 4px;">{{ $t('emotion_strength') }}</div>
          </div>

          <div class="field">
            <button class="btn" @click="submit" :disabled="!canSubmit">
              {{ loading ? $t('generating') : $t('start_generating') }}
            </button>
            <div class="muted" style="margin-top: 6px;">{{ $t('tts_mode_clone_free') }}</div>
          </div>
        </template>

        <div v-if="statusText" class="status" :class="{'success': result, 'danger': status==='FAILED'}">
          {{ statusText }}
        </div>

        <div v-if="error && !loading" class="status danger">{{ error }}</div>

        <div v-if="result" class="results" style="display: block; padding: 16px;">
          <div class="result-title" style="margin-bottom: 12px; font-weight: 600;">{{ $t('generate_result') }}</div>
          <div class="result-item" style="display: block; width: 100%;">
            <audio :src="result.file_url" controls style="width:50%; max-width:50%; display:block; margin-bottom:12px;"></audio>
            <button class="btn secondary" @click="downloadAudio(result.file_url)">{{ $t('download_audio') }}</button>
          </div>
        </div>
      </div>
    `
  };

if (typeof window !== "undefined") window.AudioGenerate = AudioGenerate;
