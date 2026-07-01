  const DigitalHuman = {
    name: 'DigitalHuman',
    data() {
      return {
        version: 'v2',
        imageFile: null,
        audioFile: null,
        text: '角色面向镜头深情的说话，固定镜头。',
        aspectRatio: '9:16',
        loading: false,
        error: '',
        results: [],
        projectId: '',
        status: '',
        statusInterval: null,
        authToken: '',
        showHistory: false,
        historyList: [],
        historyLoading: false,
        historyPage: 1,
        historyTotal: 0,
        modelConfigs: {}
      }
    },
    mounted() {
      this.authToken = localStorage.getItem('auth_token') || '';
      this.fetchModelConfigs();
    },
    computed: {
      canSubmit() {
        return !!this.imageFile && !!this.audioFile && !!this.text.trim() && !this.loading && this.text.length <= 1000;
      },
      statusText() {
        if (this.status === 'submitted') return this.$t('task_submitted') + '数字人视频...';
        if (this.status === 'QUEUED') return this.$t('loading');
        if (this.status === 'RUNNING') return '正在生成数字人视频...';
        if (this.status === 'SUCCESS') return '数字人视频生成完成！';
        if (this.status === 'FAILED') return this.$t('error');
        return '';
      },
      configKey() {
        return this.version === 'v1' ? 'digital_human' : 'digital_human_ltx2_3_voice';
      },
      historyType() {
        return this.version === 'v1' ? 13 : 32;
      },
      aspectRatioOptions() {
        const config = this.modelConfigs[this.configKey];
        if (!config || !config.ratios) {
          return [
            { value: '9:16', label: '9:16 (竖屏)' },
            { value: '16:9', label: '16:9 (横屏)' },
            { value: '1:1', label: '1:1 (方形)' }
          ];
        }
        const labelMap = {
          '9:16': '9:16 (竖屏)',
          '16:9': '16:9 (横屏)',
          '1:1': '1:1 (方形)',
          '3:2': '3:2',
          '2:3': '2:3',
          '3:4': '3:4',
          '4:3': '4:3'
        };
        return config.ratios.map(ratio => ({
          value: ratio,
          label: labelMap[ratio] || ratio
        }));
      },
      computingPower() {
        return 12;
      }
    },
    methods: {
      async fetchModelConfigs() {
        try {
          await TaskConfig.load();
          this.modelConfigs = TaskConfig.getModelConfigs();
          const config = this.modelConfigs[this.configKey];
          if (config && config.default_ratio) {
            this.aspectRatio = config.default_ratio;
          }
        } catch (err) {
          console.error('获取模型配置失败:', err);
        }
      },

      switchVersion(v) {
        if (this.loading) return;
        this.version = v;
        this.imageFile = null;
        this.audioFile = null;
        this.text = v === 'v2' ? '角色面向镜头深情的说话，固定镜头。' : '';
        this.error = '';
        this.results = [];
        this.projectId = '';
        this.status = '';
        this.clearStatusCheck();
        const config = this.modelConfigs[this.configKey];
        if (config && config.default_ratio) {
          this.aspectRatio = config.default_ratio;
        }
      },

      onImageFile(e) {
        this.imageFile = e.target.files[0] || null;
      },
      onAudioFile(e) {
        this.audioFile = e.target.files[0] || null;
      },

      async submit() {
        if (!this.canSubmit) return;

        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = '请先登录后再使用数字人生成功能';
          return;
        }

        this.loading = true;
        this.error = '';
        this.results = [];
        this.projectId = '';
        this.status = '';
        this.clearStatusCheck();

        try {
          const form = new FormData();
          form.append('image', this.imageFile);
          form.append('audio', this.audioFile);
          form.append('text', this.text);
          form.append('user_id', userId);

          // v1 需要比例参数
          if (this.version === 'v1') {
            form.append('aspect_ratio', this.aspectRatio);
          }

          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const api = this.version === 'v1' ? '/api/digital-human' : '/api/digital-human-v2';
          const res = await axios.post(api, form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });

          this.projectId = res.data.project_id || '';
          this.status = res.data.status || 'submitted';

          this.startStatusCheck();

        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || err?.message || '请求失败';
          this.loading = false;
        }
      },

      async checkStatus() {
        if (!this.projectId) return;

        try {
          const authToken = localStorage.getItem('auth_token');
          const params = authToken ? { auth_token: authToken } : {};
          const res = await axios.get(`/api/get-status/${this.projectId}`, { params });
          const responseData = res?.data;

          if (!responseData) {
            console.error('Invalid status response:', responseData);
            return;
          }

          let payload;
          if (responseData.tasks && responseData.tasks.length > 0) {
            payload = responseData.tasks[0];
          } else {
            console.error('Invalid status response format:', responseData);
            return;
          }

          if (!payload || typeof payload.status === 'undefined') {
            console.error('Invalid task payload:', payload);
            return;
          }

          this.status = payload.status;

          if (payload.status === 'SUCCESS') {
            this.results = payload.results || [];
            this.loading = false;
            this.clearStatusCheck();
          } else if (payload.status === 'FAILED') {
            this.error = payload.reason || '任务处理失败';
            this.loading = false;
            this.clearStatusCheck();
          }
        } catch (err) {
          console.error('Status check error:', err);
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

      downloadVideo(url, index) {
        if (this.$root.isWechatBrowser()) {
          this.$root.showWechatGuideModal = true;
          return;
        }

        const now = new Date();
        const dateStr = now.getFullYear().toString() +
                       (now.getMonth() + 1).toString().padStart(2, '0') +
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') +
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `digital_human_${dateStr}_${timeStr}_${index + 1}.mp4`;
        const downloadUrl = buildDownloadUrl(url, filename);
        window.open(downloadUrl, '_blank');
      },

      async fetchHistory(reset = true) {
        if (reset) {
          this.historyPage = 1;
          this.historyList = [];
        }

        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = '请先登录';
          this.showHistory = true;
          return;
        }

        this.historyLoading = true;
        try {
          const authToken = localStorage.getItem('auth_token');

          const res = await axios.get('/api/ai-tools/history', {
            params: {
              user_id: parseInt(userId, 10),
              page: this.historyPage,
              page_size: 20,
              type: this.historyType,
              auth_token: authToken || undefined
            }
          });

          if (res.data.success) {
            const payload = res.data.data || {};
            const newItems = payload.data || payload.items || [];
            this.historyList = reset ? newItems : [...this.historyList, ...newItems];
            this.historyTotal = payload.total || 0;
            this.showHistory = true;
          }
        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || '获取历史记录失败';
          this.showHistory = true;
        } finally {
          this.historyLoading = false;
        }
      },

      handleHistoryScroll(e) {
        const { scrollTop, scrollHeight, clientHeight } = e.target;
        if (scrollHeight - scrollTop - clientHeight < 50 && !this.historyLoading) {
          this.loadMoreHistory();
        }
      },

      async loadMoreHistory() {
        if (this.historyList.length >= this.historyTotal) return;
        this.historyPage++;
        await this.fetchHistory(false);
      },

      closeHistory() {
        this.showHistory = false;
        this.historyPage = 1;
        this.historyList = [];
      },

      getHistoryStatusText(status) {
        const statusMap = {
          0: '未处理',
          1: '处理中',
          2: '处理完成',
          3: '排队处理中',
          '-1': '处理失败'
        };
        return statusMap[status] || '未知';
      },

      getHistoryStatusColor(status) {
        const colorMap = {
          0: '#888',
          1: '#3b82f6',
          2: '#10b981',
          3: '#f59e0b',
          '-1': '#ef4444'
        };
        return colorMap[status] || '#888';
      },

      downloadHistoryVideo(item, index) {
        if (!item || !item.result_url) {
          alert('下载链接不可用');
          return;
        }

        if (this.$root.isWechatBrowser()) {
          this.$root.showWechatGuideModal = true;
          return;
        }

        const now = new Date();
        const dateStr = now.getFullYear().toString() +
                       (now.getMonth() + 1).toString().padStart(2, '0') +
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') +
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `digital_human_history_${dateStr}_${timeStr}_${index + 1}.mp4`;
        const downloadUrl = buildDownloadUrl(item.result_url, filename);
        window.open(downloadUrl, '_blank');
      }
    },
    beforeUnmount() {
      this.clearStatusCheck();
    },
    template: `
      <div class="form">
        <div class="field">
          <div style="display: flex; gap: 8px; margin-bottom: 8px;">
            <button
              :class="['btn', version === 'v1' ? '' : 'secondary']"
              style="flex: 1; padding: 8px 12px; font-size: 13px;"
              @click="switchVersion('v1')"
              :disabled="loading">
              wan2.2 数字人
            </button>
            <button
              :class="['btn', version === 'v2' ? '' : 'secondary']"
              style="flex: 1; padding: 8px 12px; font-size: 13px;"
              @click="switchVersion('v2')"
              :disabled="loading">
              LTX2.3 数字人
            </button>
          </div>
        </div>

        <div class="field">
          <label class="label">{{ $t('digital_human_image') }} <span style="color: red;">*</span></label>
          <input class="input" type="file" accept="image/*" @change="onImageFile" :disabled="loading" />
          <div class="muted" style="margin-top: 4px;">{{ $t('digital_human_image_tip') }}</div>
        </div>

        <div class="field">
          <label class="label">{{ version === 'v2' ? $t('prompt_text') : $t('speech_text') }} <span style="color: red;">*</span></label>
          <textarea class="input" v-model="text" :placeholder="version === 'v2' ? $t('dh_video_prompt_placeholder') : $t('max_characters')" rows="5" :disabled="loading"></textarea>
          <div class="muted" style="margin-top: 4px;">
            {{ $t('current_characters') }}: {{ text.length }}/1000
            <span v-if="text.length > 1000" style="color: var(--danger); margin-left: 8px;">{{ $t('text_exceeded') }}</span>
          </div>
        </div>

        <div class="field">
          <label class="label">{{ version === 'v2' ? $t('speaking_audio') : $t('reference_audio') }} <span style="color: red;">*</span></label>
          <input class="input" type="file" accept="audio/*" @change="onAudioFile" :disabled="loading" />
          <div class="muted" style="margin-top: 4px;">{{ version === 'v2' ? $t('speaking_audio_tip') : $t('audio_cloning_tip') }}</div>
        </div>

        <div v-if="version === 'v1'" class="field">
          <label class="label">{{ $t('video_ratio') }}</label>
          <select class="input" v-model="aspectRatio" :disabled="loading">
            <option v-for="opt in aspectRatioOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div class="field" style="background: #1a1f2e; padding: 12px; border-radius: 8px; border: 1px solid var(--border);">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="color: var(--muted); font-size: 14px;">{{ $t('power_consumption') }}：</span>
            <span style="color: #60a5fa; font-weight: bold; font-size: 16px;">{{ computingPower }} {{ $t('power_unit') }}</span>
          </div>
        </div>

        <div class="field">
          <div class="row">
            <button class="btn" :disabled="!canSubmit" @click="submit">
              {{ loading ? $t('generating') : $t('start_generating') }}
            </button>
            <button class="btn secondary" @click="showHistory = true; fetchHistory()" :disabled="historyLoading">
              {{ historyLoading ? $t('loading') : $t('history') }}
            </button>
          </div>
        </div>

        <div v-if="statusText" class="status" :class="{'success': status==='SUCCESS', 'danger': status==='FAILED'}">
          {{ statusText }}
        </div>

        <div v-if="error && !loading" class="status danger">{{ error }}</div>

        <div v-if="results.length" class="results">
          <div class="result-title">{{ $t('generate_result') }}</div>
          <div v-for="(result, idx) in results" :key="idx" class="result-item">
            <video :src="result.file_url" controls style="width:100%; max-height:400px; border-radius:8px;"></video>
            <div style="margin-top:8px; display:flex; gap:8px;">
              <button class="btn secondary" @click="downloadVideo(result.file_url, idx)">{{ $t('download_video') }}</button>
              <span v-if="result.task_cost_time" class="muted">{{ $t('cost_time') }}: {{ result.task_cost_time }}{{ $t('seconds') }}</span>
            </div>
          </div>
        </div>

        <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
          <div class="modal" style="max-width: 800px; max-height: 80vh; overflow-y: auto;" @scroll="handleHistoryScroll">
            <button class="modal-close" @click="closeHistory">×</button>
            <div class="modal-title">{{ $t('digital_human_history') }}</div>
            <div v-if="historyList.length === 0 && !historyLoading" style="text-align: center; padding: 40px; color: var(--muted);">
              {{ $t('no_history_records') }}
            </div>
            <div v-for="(item, idx) in historyList" :key="idx" style="padding: 16px; border-bottom: 1px solid var(--border);">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <div style="flex: 1;">
                  <div style="font-size: 14px; color: var(--text); margin-bottom: 4px;">{{ item.prompt }}</div>
                  <div style="font-size: 12px; color: var(--muted);">{{ $t('ratio') }}: {{ item.ratio || '-' }}</div>
                </div>
                <span :style="{color: getHistoryStatusColor(item.status), fontSize: '12px', fontWeight: '600'}">
                  {{ getHistoryStatusText(item.status) }}
                </span>
              </div>
              <div v-if="item.result_url" style="margin-top: 8px;">
                <video :src="item.result_url" controls style="width: 100%; max-height: 200px; border-radius: 8px;"></video>
                <button class="btn secondary" style="margin-top: 8px; font-size: 12px;" @click="downloadHistoryVideo(item, idx)">{{ $t('download_video') }}</button>
              </div>
              <div style="font-size: 11px; color: var(--muted); margin-top: 8px;">
                {{ $t('create_time') }}: {{ new Date(item.create_time).toLocaleString() }}
              </div>
            </div>
            <div v-if="historyLoading" style="text-align: center; padding: 20px; color: var(--muted);">
              {{ $t('loading') }}
            </div>
          </div>
        </div>
      </div>
    `
  };

if (typeof window !== "undefined") window.DigitalHuman = DigitalHuman;
