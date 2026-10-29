  const VideoEnhance = {
    name: 'VideoEnhance',
    data() {
      return {
        file: null,
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
        timelineAiToolId: null,
        // 参数 schema（来自 task-configs 的 params_schema）与当前选中值（key -> value）
        paramsSchema: [],
        paramValues: {},
        // 算力预估：按选中视频时长吸附档位后从 task-configs 计算（与服务端计费口径一致）
        estimateTier: null,
        estimatePower: null,
        durationNote: '',
        durationTooLong: false
      }
    },
    mounted() {
      this.authToken = localStorage.getItem('auth_token') || '';
      this.loadParamsSchema();
    },
    computed: {
      canSubmit() { return !!this.file && !this.loading && !this.durationTooLong },
      statusText() {
        switch(this.status) {
          case 'submitted': return this.$t('video_enhance_status_submitted') || '任务已提交，等待处理...';
          case 'QUEUED': return this.$t('video_enhance_status_queued') || '任务排队中...';
          case 'RUNNING': return this.$t('video_enhance_status_running') || '正在修复视频...';
          case 'SUCCESS': return this.$t('video_enhance_status_success') || '修复完成！';
          case 'FAILED': return this.$t('video_enhance_status_failed') || '任务失败';
          default: return '';
        }
      }
    },
    methods: {
      onFile(e){
        this.file = e.target.files[0] || null;
        this.estimateTier = null;
        this.estimatePower = null;
        this.durationNote = '';
        this.durationTooLong = false;
        if (this.file) this.probeDuration(this.file);
      },

      // 读取本地视频时长并预估算力：时长吸附口径与服务端
      // _snap_duration_to_enhance_tier 一致（向上取整、下限 4 秒、上限 15 秒，
      // 上限见 config/constant.py VIDEO_ENHANCE_MAX_DURATION_SECONDS）；
      // 档位算力取 task-configs 的 video_enhance.computing_power（同服务端计费表）。
      // TaskConfig.load 有 promise 缓存，重复调用安全（loadParamsSchema 与本方法可能并发触发）。
      async probeDuration(file){
        const url = URL.createObjectURL(file);
        const video = document.createElement('video');
        video.preload = 'metadata';
        const clearUrl = () => { try { URL.revokeObjectURL(url); } catch (_) {} };
        video.onloadedmetadata = async () => {
          clearUrl();
          const dur = video.duration;
          if (!dur || !isFinite(dur) || dur <= 0) {
            this.durationNote = this.$t('video_enhance_duration_unknown') || '无法读取视频时长，将以服务端探测为准';
            return;
          }
          const tier = Math.max(4, Math.ceil(dur));
          if (tier > 15) {
            this.durationTooLong = true;
            return;
          }
          this.estimateTier = tier;
          try { await TaskConfig.load(); } catch (_) {}
          const power = TaskConfig.getComputingPower('video_enhance', tier);
          this.estimatePower = power > 0 ? power : null;
        };
        video.onerror = () => {
          clearUrl();
          this.durationNote = this.$t('video_enhance_duration_unknown') || '无法读取视频时长，将以服务端探测为准';
        };
        video.src = url;
      },

      // 从 task-configs 加载 video_enhance 的参数 schema（配置驱动渲染参数表单）。
      // 取不到 schema 时保持现状（不显示参数区、不传 params），保证向后兼容。
      async loadParamsSchema(){
        try {
          await TaskConfig.load();
          const task = TaskConfig.getTaskByKey('video_enhance');
          const schema = (task && Array.isArray(task.params_schema)) ? task.params_schema : [];
          // 本期只支持 select 类型控件
          this.paramsSchema = schema.filter(p => p && p.key && p.type === 'select');
          this.paramValues = {};
          this.paramsSchema.forEach(p => { this.paramValues[p.key] = p.default; });
        } catch (e) {
          console.error('加载视频修复参数配置失败:', e);
          this.paramsSchema = [];
          this.paramValues = {};
        }
      },

      // schema 字段名属不可信内容，渲染必须走 window.escapeHtml（web/js/escape.js）
      paramLabelHtml(label){
        return window.escapeHtml(label);
      },

      async submit(){
        if(!this.canSubmit) return;

        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = this.$t('video_enhance_login_required') || '请先登录后再使用视频修复功能';
          return;
        }

        this.loading = true; this.error=''; this.results=[]; this.projectId=''; this.status='';
        this.clearStatusCheck();
        
        try {
          const form = new FormData();
          form.append('video', this.file);
          form.append('user_id', userId);
          
          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          // 用户选择的参数（key->value，键值均来自后端 schema）；服务端仍会按 schema 再校验
          if (this.paramsSchema.length) {
            form.append('params', JSON.stringify(this.paramValues));
          }

          const res = await axios.post('/api/video-enhance', form, {
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
          const payload = res?.data?.tasks?.[0];

          if (!payload || typeof payload.status === 'undefined') {
            console.error('Invalid status response:', payload);
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
      
      async downloadVideo(url, index) {
        // Check if WeChat browser
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
        const filename = `enhanced_${dateStr}_${timeStr}_${index + 1}.mp4`;
        try {
          await downloadWithAuth(url, filename);
        } catch (e) {
          if (e && e.status === 401) return;
          alert((e && e.message) || '下载失败');
        }
      },

      async downloadHistoryVideo(item, index) {
        if (!item || !item.result_url) {
          alert('下载链接不可用');
          return;
        }
        
        // Check if WeChat browser
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
        const filename = `enhanced_history_${dateStr}_${timeStr}_${index + 1}.mp4`;
        try {
          await downloadWithAuth(item.result_url, filename);
        } catch (e) {
          if (e && e.status === 401) return;
          alert((e && e.message) || '下载失败');
        }
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
              type: 5,  // TaskTypeId.VIDEO_ENHANCE（视频高清修复）
            },
            headers: { Authorization: 'Bearer ' + (authToken || '') }
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
    },
    beforeUnmount() {
      this.clearStatusCheck();
    },
    template: `
      <div>
        <div class="form">
          <div class="field">
            <label class="label">{{ $t('upload_video') || '上传视频' }}</label>
            <input type="file" @change="onFile" accept="video/*" class="input" :disabled="loading">
          </div>

          <div class="field" v-for="param in paramsSchema" :key="param.key">
            <label class="label" v-html="paramLabelHtml(param.label)"></label>
            <select class="input" v-model="paramValues[param.key]" :disabled="loading">
              <option v-for="opt in (param.options || [])" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field" v-if="estimatePower !== null">
            <div style="color: #60a5fa; font-size: 13px;">
              {{ $t('video_enhance_estimate_power') || '预计消耗算力' }}：{{ estimatePower }}（{{ estimateTier }}{{ $t('video_enhance_estimate_tier_suffix') || ' 秒档' }}）
            </div>
          </div>
          <div class="field" v-if="durationTooLong">
            <div class="status danger">{{ $t('video_enhance_duration_too_long') || '视频时长超过 15 秒上限，请截取后再上传' }}</div>
          </div>
          <div class="field" v-if="durationNote" style="color: #9ca3af; font-size: 12px;">{{ durationNote }}</div>

          <div class="field">
            <div class="row">
              <button class="btn" :disabled="!canSubmit" @click="submit">
                {{ loading ? ($t('video_enhance_processing') || '处理中...') : ($t('video_enhance_start') || '开始修复') }}
              </button>
              <button class="btn secondary" @click="showHistory = true; fetchHistory()" :disabled="historyLoading">
                {{ historyLoading ? ($t('loading') || '加载中...') : ($t('video_enhance_history') || '历史记录') }}
              </button>
            </div>
          </div>
        </div>

        <div class="status" v-if="statusText">{{ statusText }}</div>
        <div class="status danger" v-if="error">{{ error }}</div>

        <div class="preview" v-if="results.length">
          <div class="imgbox" v-for="(result, idx) in results" :key="idx">
            <video :src="result.file_url" controls style="max-width: 100%; border-radius: 8px;"></video>
            <div style="padding: 8px; text-align: center;">
              <button class="btn secondary" @click="downloadVideo(result.file_url, idx)">下载视频</button>
            </div>
          </div>
        </div>
        
        <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
          <div class="modal" style="max-width: 800px; max-height: 80vh; overflow-y: auto;" @scroll="handleHistoryScroll">
            <div class="modal-sticky-header">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; padding-right: 40px; margin-bottom: 12px;">
                <div style="display: flex; align-items: flex-start; gap: 12px;">
                  <div class="modal-title">{{ $t('history') || '历史记录' }} ({{ $t('total_records') || '共' }} {{ historyTotal }} {{ $t('items') || '条' }})</div>
                  <button
                    class="btn secondary"
                    @click="fetchHistory(true)"
                    :disabled="historyLoading"
                    style="display: inline-flex; align-items: center; justify-content: center; padding: 4px 12px; font-size: 12px;"
                  >
                    {{ historyLoading ? ($t('refreshing') || '刷新中...') : ($t('refresh') || '刷新') }}
                  </button>
                </div>
                <button class="modal-close" @click="closeHistory">×</button>
              </div>
            </div>
            
            <div v-if="historyList.length === 0" style="padding: 40px; text-align: center; color: var(--muted);">
              {{ $t('no_history') }}
            </div>
            
            <div v-else style="padding: 16px;">
              <div v-for="(item, idx) in historyList" :key="item.id" style="margin-bottom: 16px; padding: 12px; background: #0b1220; border: 1px solid var(--border); border-radius: 8px;">
                <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                  <div>
                    <strong>{{ $t('type_label') || '类型' }}:</strong> {{ $t('video_enhance_type') || '视频高清修复' }}
                  </div>
                  <span :style="{
                    padding: '4px 12px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    backgroundColor: getHistoryStatusColor(item.status) + '20',
                    color: getHistoryStatusColor(item.status),
                    border: '1px solid ' + getHistoryStatusColor(item.status),
                    cursor: item.status == -1 && item.message ? 'help' : 'default'
                  }" :title="item.status == -1 && item.message ? item.message : ''">
                    {{ getHistoryStatusText(item.status) }}
                  </span>
                </div>
                <div style="display: flex; gap: 16px; font-size: 13px; color: var(--muted); margin-bottom: 8px;">
                  <span>{{ $t('created_time_display') || '创建时间' }}: {{ item.create_time ? new Date(item.create_time).toLocaleString('zh-CN') : ($t('unknown') || '未知') }}</span>
                </div>
                <div v-if="item.image_path" style="margin-top: 8px;">
                  <video :src="item.image_path" controls style="max-width: 240px; border-radius: 8px; margin-bottom: 8px;"></video>
                </div>
                <div v-if="item.result_url" style="margin-top: 8px;">
                  <button class="btn secondary" @click="downloadHistoryVideo(item, idx)" style="display: inline-block; text-decoration: none; margin-top: 8px;">{{ $t('download_enhanced_video') || '下载修复视频' }}</button>
                </div>
                <div style="margin-top: 8px;">
                  <button class="btn secondary" @click="timelineAiToolId = item.id">{{ $t('view_timeline') }}</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <timeline-modal v-if="timelineAiToolId" :ai-tool-id="timelineAiToolId" @close="timelineAiToolId = null"></timeline-modal>
      </div>
    `,
  };

if (typeof window !== "undefined") window.VideoEnhance = VideoEnhance;
