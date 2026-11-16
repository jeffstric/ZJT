  // 视频编辑（当前工具：视频人物替换，task_type=54）
  // 用角色参考图替换参考视频中的对应角色：动作/运镜/原声跟随视频，只换身份。
  // 链路：POST /api/video-character-replace 落库入队 → 轮询 /api/get-status/{id}。
  const VideoEdit = {
    name: 'VideoEdit',
    data() {
      return {
        // 参考视频（必填）
        file: null,
        // 角色参考图（1-9 张）：[{ file, previewUrl }]
        images: [],
        // 输出时长：null=跟随视频时长（服务端 ffprobe 探测定档）；数字=用户指定（5-25）
        duration: null,
        // 替换说明（选填）：指定谁换谁 / 保留什么 / 替换后走向
        prompt: '',
        // 检测主体类型（选填，必须英文，留空=默认 person）
        subject: '',
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
        // 算力预估：按视频时长吸附档位后从 task-configs 计算（与服务端计费口径一致）
        estimateTier: null,
        estimatePower: null,
        durationNote: ''
      }
    },
    mounted() {
      this.authToken = localStorage.getItem('auth_token') || '';
    },
    computed: {
      canSubmit() {
        return !!this.file && this.images.length > 0 && !this.loading;
      },
      statusText() {
        switch(this.status) {
          case 'submitted': return this.$t('video_edit_status_submitted') || '任务已提交，等待处理...';
          case 'QUEUED': return this.$t('video_edit_status_queued') || '任务排队中...';
          case 'RUNNING': return this.$t('video_edit_status_running') || '正在替换视频角色...';
          case 'SUCCESS': return this.$t('video_edit_status_success') || '替换完成！';
          case 'FAILED': return this.$t('video_edit_status_failed') || '任务失败';
          default: return '';
        }
      }
    },
    methods: {
      onVideoFile(e){
        this.file = e.target.files[0] || null;
        this.estimateTier = null;
        this.estimatePower = null;
        this.durationNote = '';
        if (this.file) this.probeDuration(this.file);
      },

      // 参考图选择（多选，最多 9 张）；超出上限时截断并提示
      onImageFiles(e){
        const files = Array.from(e.target.files || []);
        e.target.value = '';  // 允许重复选择同一文件
        if (!files.length) return;
        const room = 9 - this.images.length;
        if (room <= 0) {
          this.durationNote = this.$t('video_edit_max_images') || '角色参考图最多 9 张';
          return;
        }
        const accepted = files.slice(0, room);
        if (files.length > room) {
          this.durationNote = (this.$t('video_edit_max_images') || '角色参考图最多 9 张');
        } else {
          this.durationNote = '';
        }
        accepted.forEach(f => {
          this.images.push({ file: f, previewUrl: URL.createObjectURL(f) });
        });
        this.refreshEstimate();
      },

      removeImage(idx){
        const item = this.images[idx];
        if (item && item.previewUrl) {
          try { URL.revokeObjectURL(item.previewUrl); } catch (_) {}
        }
        this.images.splice(idx, 1);
      },

      // 用户指定输出时长（5-25）；清空=跟随视频时长
      onDurationInput(e){
        const v = parseInt(e.target.value, 10);
        this.duration = (v && v > 0) ? v : null;
        this.refreshEstimate();
      },

      // 读取本地视频时长预估算力：时长吸附口径与服务端一致
      // （向上取整、钳 5-25，见 server.py /api/video-character-replace）；
      // 档位算力取 task-configs 的 video_character_replace.computing_power。
      async probeDuration(file){
        const url = URL.createObjectURL(file);
        const video = document.createElement('video');
        video.preload = 'metadata';
        const clearUrl = () => { try { URL.revokeObjectURL(url); } catch (_) {} };
        video.onloadedmetadata = async () => {
          clearUrl();
          const dur = video.duration;
          if (!dur || !isFinite(dur) || dur <= 0) {
            this.durationNote = this.$t('video_edit_duration_unknown') || '无法读取视频时长，将以服务端探测为准';
            return;
          }
          this.refreshEstimate(Math.ceil(dur));
        };
        video.onerror = () => {
          clearUrl();
          this.durationNote = this.$t('video_edit_duration_unknown') || '无法读取视频时长，将以服务端探测为准';
        };
        video.src = url;
      },

      // 算力预估：优先用户指定时长，其次视频探测时长（向上取整），钳 5-25
      async refreshEstimate(probedSeconds){
        let tier = this.duration || (probedSeconds ? Math.ceil(probedSeconds) : null);
        if (!tier) { this.estimateTier = null; this.estimatePower = null; return; }
        tier = Math.max(5, Math.min(25, tier));
        this.estimateTier = tier;
        try { await TaskConfig.load(); } catch (_) {}
        const power = TaskConfig.getComputingPower('video_character_replace', tier);
        this.estimatePower = power > 0 ? power : null;
      },

      async submit(){
        if(!this.canSubmit) return;

        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = this.$t('video_edit_login_required') || '请先登录后再使用视频编辑功能';
          return;
        }

        this.loading = true; this.error=''; this.results=[]; this.projectId=''; this.status='';
        this.clearStatusCheck();

        try {
          const form = new FormData();
          form.append('video', this.file);
          this.images.forEach((item) => form.append('images', item.file));
          form.append('user_id', userId);
          if (this.duration) form.append('duration_seconds', String(this.duration));
          if (this.prompt.trim()) form.append('prompt', this.prompt.trim());
          if (this.subject.trim()) form.append('subject', this.subject.trim());
          if (this.authToken) form.append('auth_token', this.authToken);

          const res = await axios.post('/api/video-character-replace', form, {
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
          // 认证走 Authorization 头（cookie 会话由服务端中间件自动翻译），
          // 禁止 auth_token 拼 URL query（X3 红线：Referer/日志泄漏）
          const authToken = localStorage.getItem('auth_token') || '';
          const res = await axios.get(`/api/get-status/${this.projectId}`, {
            headers: { Authorization: 'Bearer ' + authToken }
          });
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
        const filename = `replaced_${dateStr}_${timeStr}_${index + 1}.mp4`;
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
        const filename = `replaced_history_${dateStr}_${timeStr}_${index + 1}.mp4`;
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
              type: 54,  // TaskTypeId.VIDEO_CHARACTER_REPLACE（视频人物替换）
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
          '-1': '处理失败',
          '-2': '已取消'
        };
        return statusMap[status] || '未知';
      },

      getHistoryStatusColor(status) {
        const colorMap = {
          0: '#888',
          1: '#3b82f6',
          2: '#10b981',
          3: '#f59e0b',
          '-1': '#ef4444',
          '-2': '#9ca3af'
        };
        return colorMap[status] || '#888';
      },
    },
    beforeUnmount() {
      this.clearStatusCheck();
      this.images.forEach(item => {
        if (item.previewUrl) { try { URL.revokeObjectURL(item.previewUrl); } catch (_) {} }
      });
    },
    template: `
      <div>
        <div class="form">
          <div class="field">
            <label class="label">{{ $t('video_edit_upload_video') || '上传参考视频' }}</label>
            <input type="file" @change="onVideoFile" accept="video/*" class="input" :disabled="loading">
            <div style="color: #9ca3af; font-size: 12px; margin-top: 4px;">
              {{ $t('video_edit_video_hint') || '视频中的动作、运镜和原声将完整保留，仅替换角色形象' }}
            </div>
          </div>

          <div class="field">
            <label class="label">{{ $t('video_edit_upload_images') || '角色参考图（1-9 张）' }}</label>
            <input type="file" @change="onImageFiles" accept="image/*" multiple class="input" :disabled="loading">
            <div style="color: #9ca3af; font-size: 12px; margin-top: 4px;">
              {{ $t('video_edit_images_hint') || '图 1 替换视频里第 1 个角色，图 2 替换第 2 个……从左到右对应；不写说明时默认替换主要角色' }}
            </div>
            <div v-if="images.length" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;">
              <div v-for="(img, idx) in images" :key="idx" style="position: relative; width: 72px; height: 72px;">
                <img :src="img.previewUrl" style="width: 100%; height: 100%; object-fit: cover; border-radius: 6px; border: 1px solid var(--border);">
                <div style="position: absolute; top: 2px; left: 2px; background: rgba(0,0,0,0.6); color: #fff; font-size: 11px; padding: 0 4px; border-radius: 3px;">{{ idx + 1 }}</div>
                <button @click="removeImage(idx)" :disabled="loading"
                  style="position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; border-radius: 50%; border: none; background: #ef4444; color: #fff; font-size: 12px; line-height: 1; cursor: pointer;">×</button>
              </div>
            </div>
          </div>

          <div class="field">
            <label class="label">{{ $t('video_edit_duration') || '输出时长（秒，5-25，留空跟随视频）' }}</label>
            <input type="number" min="5" max="25" :value="duration" @input="onDurationInput" class="input" :disabled="loading"
              :placeholder="$t('video_edit_duration_placeholder') || '跟随参考视频时长'">
          </div>

          <div class="field">
            <label class="label">{{ $t('video_edit_prompt') || '替换说明（选填）' }}</label>
            <textarea v-model="prompt" class="input" rows="3" maxlength="2048" :disabled="loading"
              :placeholder="$t('video_edit_prompt_hint') || '例如：图1换左边穿黑甲的；右边穿白背心的伴舞不换；保留手里的话筒'"></textarea>
          </div>

          <div class="field">
            <label class="label">{{ $t('video_edit_subject') || '检测主体类型（选填，英文）' }}</label>
            <input type="text" v-model="subject" class="input" :disabled="loading"
              :placeholder="$t('video_edit_subject_hint') || '默认 person（人），可填 dog / car / robot 等'">
          </div>

          <div class="field" v-if="estimatePower !== null">
            <div style="color: #60a5fa; font-size: 13px;">
              {{ $t('video_edit_estimate_power') || '预计消耗算力' }}：{{ estimatePower }}（{{ estimateTier }}{{ $t('video_edit_estimate_tier_suffix') || ' 秒档' }}）
            </div>
          </div>
          <div class="field" v-if="durationNote" style="color: #9ca3af; font-size: 12px;">{{ durationNote }}</div>

          <div class="field">
            <div class="row">
              <button class="btn" :disabled="!canSubmit" @click="submit">
                {{ loading ? ($t('video_edit_processing') || '处理中...') : ($t('video_edit_start') || '开始替换') }}
              </button>
              <button class="btn secondary" @click="showHistory = true; fetchHistory()" :disabled="historyLoading">
                {{ historyLoading ? ($t('loading') || '加载中...') : ($t('video_edit_history') || '历史记录') }}
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
                    <strong>{{ $t('type_label') || '类型' }}:</strong> {{ $t('video_edit_tool') || '视频人物替换' }}
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
                  <button class="btn secondary" @click="downloadHistoryVideo(item, idx)" style="display: inline-block; text-decoration: none; margin-top: 8px;">{{ $t('download_replaced_video') || '下载替换视频' }}</button>
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

  if (typeof window !== "undefined") window.VideoEdit = VideoEdit;
