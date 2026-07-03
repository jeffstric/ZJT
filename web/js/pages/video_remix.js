  const VideoRemix = {
    name: 'VideoRemix',
    data() {
      return {
        videoId: '',
        prompt: '',
        aspectRatio: '16:9',
        duration: 10,
        count: 1,
        loading: false,
        error: '',
        results: [],
        projectIds: [],
        status: '',
        authToken: '',
        showHistory: false,
        historyList: [],
        historyLoading: false,
        historyPage: 1,
        historyTotal: 0,
        timelineAiToolId: null,
        statusInterval: null,
      }
    },
    mounted() {
      this.authToken = localStorage.getItem('auth_token') || '';
    },
    computed: {
      canSubmit() { return !!this.videoId.trim() && !!this.prompt.trim() && !this.loading },
      statusText() {
        if (['SUCCESS', 'completed'].includes(this.status)) return this.$t('remix_complete') || 'Remix完成！';
        if (['FAILED'].includes(this.status)) return this.error || this.$t('remix_task_failed') || '任务失败';
        if (['QUEUED', 'RUNNING'].includes(this.status) || this.loading) return this.$t('remix_video_generating') || '正在Remix视频，请稍候...';
        return '';
      },
      aspectRatioOptions() {
        return [
          { value: '16:9', label: this.$t('screen_16_9') || '16:9 (横屏)' },
          { value: '9:16', label: this.$t('screen_9_16') || '9:16 (竖屏)' },
          { value: '1:1', label: this.$t('screen_1_1') || '1:1 (方形)' }
        ];
      },
      durationOptions() {
        return [
          { value: 10, label: this.$t('duration_10s') || '10秒' },
          { value: 15, label: this.$t('duration_15s') || '15秒' }
        ];
      },
      countOptions() {
        return [
          { value: 1, label: this.$t('count_1') || '1个' },
          { value: 2, label: this.$t('count_2') || '2个' },
          { value: 3, label: this.$t('count_3') || '3个' },
          { value: 4, label: this.$t('count_4') || '4个' }
        ];
      }
    },
    methods: {
      async submit(){
        if(!this.canSubmit) return;
        this.loading = true;
        this.error='';
        this.results=[];
        this.projectIds=[];
        this.status='';

        try {
          const form = new FormData();
          form.append('video_id', this.videoId);
          form.append('prompt', this.prompt);
          form.append('aspect_ratio', this.aspectRatio);
          form.append('duration', this.duration);
          form.append('count', this.count);
          
          // Add user_id from localStorage
          const userId = localStorage.getItem('user_id');
          if (userId) {
            form.append('user_id', userId);
          }
          
          // Add auth_token if available
          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const res = await axios.post('/api/video-remix', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
          
          // Handle multiple project IDs
          this.projectIds = res.data.project_ids || [];
          this.status = res.data.status || 'submitted';
          
          // Start polling for status
          if (this.projectIds.length > 0) {
            this.checkStatus();
          }
          
        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || err?.message || '请求失败';
          this.loading = false;
        }
      },
      
      async checkStatus() {
        if (!this.projectIds || this.projectIds.length === 0) return;
        
        try {
          const authToken = localStorage.getItem('auth_token');
          const params = authToken ? { auth_token: authToken } : {};
          
          // Batch query all project IDs
          const projectIdsStr = this.projectIds.join(',');
          const res = await axios.get(`/api/get-status/${projectIdsStr}`, { params });
          const payload = res?.data;

          if (!payload) {
            console.error('Invalid status response:', payload);
            this.statusInterval = setTimeout(() => this.checkStatus(), 10000);
            return;
          }

          // Handle batch response
          if (payload.tasks) {
            // Multiple tasks response
            const tasks = payload.tasks;
            const allSuccess = tasks.every(t => t.status === 'SUCCESS');
            const anyFailed = tasks.some(t => t.status === 'FAILED');
            const anyRunning = tasks.some(t => t.status === 'RUNNING');
            
            // Collect all successful results
            const allResults = [];
            tasks.forEach(task => {
              if (task.results && task.results.length > 0) {
                allResults.push(...task.results);
              }
            });
            
            this.results = allResults;
            
            if (allSuccess) {
              this.status = 'SUCCESS';
              this.loading = false;
              this.clearStatusCheck();
            } else if (anyFailed && !anyRunning) {
              // All done but some failed
              const failedTasks = tasks.filter(t => t.status === 'FAILED');
              this.error = `${failedTasks.length} 个任务失败`;
              this.status = 'FAILED';
              this.loading = false;
              this.clearStatusCheck();
            } else {
              // Still running
              this.status = 'RUNNING';
              this.statusInterval = setTimeout(() => this.checkStatus(), 10000);
            }
          } else {
            // Single task response
            this.status = payload.status || '';

            if (this.status === 'SUCCESS') {
              this.results = payload.results || [];
              this.loading = false;
              this.clearStatusCheck();
            } else if (this.status === 'FAILED') {
              this.error = payload.reason || '任务失败';
              this.loading = false;
              this.clearStatusCheck();
            } else {
              this.statusInterval = setTimeout(() => this.checkStatus(), 10000);
            }
          }
        } catch (err) {
          console.error('Status check failed:', err);
          this.statusInterval = setTimeout(() => this.checkStatus(), 10000);
        }
      },
      
      clearStatusCheck() {
        if (this.statusInterval) {
          clearTimeout(this.statusInterval);
          this.statusInterval = null;
        }
      },
      
      downloadVideo(url, index) {
        const now = new Date();
        const dateStr = now.getFullYear().toString() + 
                       (now.getMonth() + 1).toString().padStart(2, '0') + 
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + 
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `remix_video_${dateStr}_${timeStr}_${index + 1}.mp4`;
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
              type: 2,
              auth_token: authToken || undefined
            }
          });
          
          if (res.data.success) {
            const payload = res.data.data || {};
            const newItems = payload.data || payload.items || [];
            // Filter to only show remix items
            const remixItems = newItems.filter(item => item.prompt && item.prompt.startsWith('Remix:'));
            this.historyList = reset ? remixItems : [...this.historyList, ...remixItems];
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
        
        const now = new Date();
        const dateStr = now.getFullYear().toString() + 
                       (now.getMonth() + 1).toString().padStart(2, '0') + 
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + 
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `remix_history_${dateStr}_${timeStr}_${index + 1}.mp4`;
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
          <label class="label">{{ $t('video_id_label') || '视频ID' }} <span style="color: red;">*</span></label>
          <input class="input" v-model="videoId" :placeholder="$t('video_id_placeholder') || '输入要重新编辑的视频ID'" />
          <div class="muted" style="margin-top: 4px;">{{ $t('video_id_example') || '例如: 09fe0989-90ce-593a-e9d4-921a62ac617f' }}</div>
        </div>

        <div class="field">
          <label class="label">{{ $t('video_remix_label') || '编辑提示词' }} <span style="color: red;">*</span></label>
          <textarea class="input" v-model="prompt" :placeholder="$t('edit_prompt_placeholder') || '描述你想要的编辑效果，例如：黑夜变白天'" rows="3"></textarea>
        </div>

        <div class="field">
          <label class="label">{{ $t('aspect_ratio_label') || '视频比例' }}</label>
          <select class="input" v-model="aspectRatio">
            <option v-for="opt in aspectRatioOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div class="field">
          <label class="label">{{ $t('video_duration_label') || '视频时长' }}</label>
          <select class="input" v-model="duration">
            <option v-for="opt in durationOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div class="field">
          <label class="label">{{ $t('generation_count_label') || '生成数量' }}</label>
          <select class="input" v-model="count">
            <option v-for="opt in countOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div class="field">
          <div class="row">
            <button class="btn" @click="submit" :disabled="!canSubmit">
              {{ loading ? ($t('remix_processing') || 'Remix中...') : ($t('remix_start') || '开始 Remix') }}
            </button>
            <button class="btn secondary" @click="showHistory = true; fetchHistory()" :disabled="historyLoading">
              {{ historyLoading ? ($t('loading') || '加载中...') : ($t('history') || '历史记录') }}
            </button>
          </div>
        </div>

        <div v-if="statusText" class="status" :class="{'success': status==='SUCCESS', 'danger': status==='FAILED'}">
          {{ statusText }}
        </div>

        <div v-if="error && !loading" class="status danger">{{ error }}</div>

        <div v-if="results.length" class="results">
          <div class="result-title">{{ $t('generation_results') || '生成结果' }} ({{ results.length }}{{ $t('items') || '个' }})</div>
          <div v-for="(r, idx) in results" :key="idx" class="result-item">
            <video :src="r.file_url" controls style="width:100%; max-height:400px; border-radius:8px;"></video>
            <div style="margin-top:8px; display:flex; gap:8px;">
              <button class="btn secondary" @click="downloadVideo(r.file_url, idx)">{{ $t('download_video_button') || '下载视频' }}</button>
              <span v-if="r.task_cost_time" class="muted">{{ $t('cost_time') || '耗时' }}: {{ r.task_cost_time }}{{ $t('seconds') || '秒' }}</span>
            </div>
          </div>
        </div>
        
        <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
          <div class="modal" style="max-width: 800px; max-height: 80vh; overflow-y: auto;" @scroll="handleHistoryScroll">
            <button class="modal-close" @click="closeHistory">×</button>
            <div class="modal-title">{{ $t('remix_history') || 'Remix 历史记录' }}</div>
            <div v-if="historyList.length === 0 && !historyLoading" style="text-align: center; padding: 40px; color: var(--muted);">
              {{ $t('no_history') || '暂无历史记录' }}
            </div>
            <div v-for="(item, idx) in historyList" :key="idx" style="padding: 16px; border-bottom: 1px solid var(--border);">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <div style="flex: 1;">
                  <div style="font-size: 14px; color: var(--text); margin-bottom: 4px;">{{ item.prompt }}</div>
                  <div style="font-size: 12px; color: var(--muted);">{{ item.message }}</div>
                  <div style="font-size: 12px; color: var(--muted); margin-top: 4px;">
                    {{ $t('aspect_ratio_label') || '比例' }}: {{ item.ratio || '-' }} | {{ $t('duration_label') || '时长' }}: {{ item.duration || '-' }}{{ $t('seconds') || '秒' }}
                  </div>
                </div>
                <span :style="{color: getHistoryStatusColor(item.status), fontSize: '12px', fontWeight: '600'}">
                  {{ getHistoryStatusText(item.status) }}
                </span>
              </div>
              <div v-if="item.result_url" style="margin-top: 8px;">
                <video :src="item.result_url" controls style="width: 100%; max-height: 200px; border-radius: 8px;"></video>
                <button class="btn secondary" style="margin-top: 8px; font-size: 12px;" @click="downloadHistoryVideo(item, idx)">{{ $t('download_video_button') || '下载视频' }}</button>
              </div>
              <div style="font-size: 11px; color: var(--muted); margin-top: 8px;">
                {{ $t('created_time_display') || '创建时间' }}: {{ new Date(item.create_time).toLocaleString() }}
              <div style="margin-top: 8px;">
                <button class="btn secondary" @click="timelineAiToolId = item.id">{{ $t('view_timeline') }}</button>
              </div>
              </div>
            </div>
            <div v-if="historyLoading" style="text-align: center; padding: 20px; color: var(--muted);">
              {{ $t('loading') || '加载中...' }}
            </div>
          </div>
        </div>
        <timeline-modal v-if="timelineAiToolId" :ai-tool-id="timelineAiToolId" @close="timelineAiToolId = null"></timeline-modal>
      </div>
    `
  };

if (typeof window !== "undefined") window.VideoRemix = VideoRemix;
