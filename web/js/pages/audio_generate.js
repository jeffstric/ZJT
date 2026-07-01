  const AudioGenerate = {
    name: 'AudioGenerate',
    data() {
      return {
        text: '',
        refAudioFile: null,
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
      canSubmit() { 
        if (!this.text.trim() || this.loading) return false;
        if (this.emoControlMethod === 2 && !this.emoVecValid) return false;
        return true;
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
      
      async submit() {
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
          
          if (this.refAudioFile) {
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
            headers: { 'Content-Type': 'multipart/form-data' },
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
        if (this.resultAudioUrl) {
          URL.revokeObjectURL(this.resultAudioUrl);
          this.resultAudioUrl = '';
        }
      },
      
      generateAudioFilename() {
        const now = new Date();
        const dateStr = now.getFullYear().toString() + 
                       (now.getMonth() + 1).toString().padStart(2, '0') + 
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + 
                       now.getMinutes().toString().padStart(2, '0');
        return `audio_${dateStr}_${timeStr}.wav`;
      },

      downloadAudio(url) {
        if (!url) return;
        const filename = this.generateAudioFilename();
        
        if (url.startsWith('blob:')) {
          const link = document.createElement('a');
          link.href = url;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        } else {
          const downloadUrl = buildDownloadUrl(url, filename);
          window.open(downloadUrl, '_blank');
        }
      }
    },
    beforeUnmount() {
      this.clearStatusCheck();
      this.clearResultAudioUrl();
    },
    template: `
      <div class="form">
        <div class="field">
          <label class="label">{{ $t('generate_text') }} <span style="color: red;">*</span></label>
          <textarea class="input" v-model="text" :placeholder="$t('enter_text_to_speech')" rows="4"></textarea>
        </div>

        <div class="field">
          <label class="label">{{ $t('reference_audio') }}（{{ $t('optional') }}）</label>
          <input type="file" @change="onRefAudioFile" accept="audio/*" class="input" :disabled="loading">
          <div class="muted" style="margin-top: 4px;">{{ $t('audio_cloning_tip') }}（{{ $t('max_20_seconds') }}）</div>
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
        </div>

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
