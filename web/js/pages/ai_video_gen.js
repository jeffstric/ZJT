  const AIVideoGen = {
    name: 'AIVideoGen',
    data() {
      return {
        prompt: '',
        videoModel: null,  // 选中的视频模型 ID
        model: '9:16',
        videoResolution: '',
        durationSeconds: 15,
        count: 1,
        loading: false,
        error: '',
        results: [],
        projectIds: [],
        projectId: '',
        status: '',
        authToken: '',
        showHistory: false,
        historyList: [],
        historyLoading: false,
        historyPage: 1,
        historyTotal: 0,
        timelineAiToolId: null,
        enhancingVideos: {},  // Track enhancement status by item id
        enhanceTaskIds: {},
        enhanceStatusTimers: {},
        enhanceTaskId: '',  // Track current enhancement task ID
        enhanceStatusInterval: null,  // Interval for polling enhancement status
        modelConfigs: {},  // From TaskConfig
        configLoaded: false,  // Configuration loaded flag
        typeNameMap: {},  // Task type ID to name mapping
      }
    },
    mounted() {
      // Get auth_token from localStorage (set by App component)
      this.authToken = localStorage.getItem('auth_token') || '';

      // Load task configs using global TaskConfig
      this.fetchModelConfigs();
    },

    computed: {
      currentModel() {
        return this.modelConfigs[this.videoModel];
      },

      canSubmit() { return !!this.prompt.trim() && !!this.videoModel && !this.loading },
      statusText() {
        if (['SUCCESS', 'completed'].includes(this.status)) return '生成完成！';
        if (['FAILED'].includes(this.status)) return this.error || '任务失败';
        if (['QUEUED', 'RUNNING'].includes(this.status) || this.loading) return '正在生成视频，请稍候...';
        return '';
      },
      videoModelOptions() {
        if (!this.configLoaded) return [];
        return TaskConfig.getModelOptionsForCategory('text_to_video');
      },
      modelOptions() {
        if (!this.currentModel) return [
          { value: '9:16', label: '竖屏' },
          { value: '16:9', label: '横屏' }
        ];

        const ratios = this.currentModel.ratios || ['9:16', '16:9'];
        const ratioMap = {
          '9:16': '竖屏',
          '16:9': '横屏',
          '1:1': '正方形',
          '2:3': '2:3',
          '3:2': '3:2',
          '3:4': '3:4',
          '4:3': '4:3',
          '21:9': '超宽屏'
        };
        return ratios.map(r => ({ value: r, label: ratioMap[r] || r }));
      },
      durationOptions() {
        if (!this.currentModel) return [
          { value: 10, label: '10秒' },
          { value: 15, label: '15秒' }
        ];

        const durations = this.currentModel.durations || [10];
        return durations.map(d => ({ value: d, label: `${d}秒` }));
      },
      videoResolutionOptions() {
        if (!this.configLoaded || !this.videoModel || !window.TaskConfig || typeof TaskConfig.getVideoResolutionOptions !== 'function') {
          return [];
        }
        return TaskConfig.getVideoResolutionOptions(this.videoModel);
      },
      countOptions() {
        return [
          { value: 1, label: '1个' },
          { value: 2, label: '2个' },
          { value: 3, label: '3个' },
          { value: 4, label: '4个' }
        ];
      },
      computingPower() {
        // 使用 TaskConfig API 动态获取算力（自动适配新增模型）
        if (!this.configLoaded || !this.videoModel) {
          return 0;  // 配置未加载或模型未选择时返回0
        }

        // 使用 TaskConfig.getComputingPower 动态获取算力
        // 该方法会自动处理固定算力和按时长计费两种情况
        const context = {};
        if (this.videoResolution) {
          context.resolution = this.videoResolution;
        }
        return TaskConfig.getComputingPower(this.videoModel, this.durationSeconds, context);
      },
      totalComputingPower() {
        // 总算力 = 单个算力 × 生成数量
        return this.computingPower * this.count;
      }
    },

    watch: {
      videoModel(newVal) {
        if (newVal && this.currentModel) {
          const config = this.currentModel;

          // Update model (ratio) to first supported option if current is not supported
          const supportedRatios = config.ratios || ['9:16'];
          if (!supportedRatios.includes(this.model)) {
            this.model = config.default_ratio || supportedRatios[0];
          }

          // Update duration to first supported option if current is not supported
          const supportedDurations = config.durations || [10];
          if (!supportedDurations.includes(this.durationSeconds)) {
            this.durationSeconds = config.default_duration || supportedDurations[0];
          }

          this.ensureVideoResolution();
        }
      }
    },

    methods: {
      async fetchModelConfigs() {
        try {
          await TaskConfig.load();
          this.modelConfigs = TaskConfig.getModelConfigs();

          // Load task type name mapping
          const taskTypeConfig = TaskConfig.getTaskTypeConfig();
          this.typeNameMap = taskTypeConfig.task_type_name_map || {};

          this.configLoaded = true;

          // Set default model - first text_to_video model available
          const videoModelOptions = TaskConfig.getModelOptionsForCategory('text_to_video');
          console.log('Available text_to_video models:', videoModelOptions);
          if (videoModelOptions.length > 0) {
            this.videoModel = videoModelOptions[0].value;
            console.log('Default video model set to:', this.videoModel);

            // Set default ratio and duration based on the first model
            const defaultConfig = this.modelConfigs[this.videoModel];
            if (defaultConfig) {
              if (defaultConfig.default_ratio) {
                this.model = defaultConfig.default_ratio;
              }
              if (defaultConfig.default_duration) {
                this.durationSeconds = defaultConfig.default_duration;
              }
              this.ensureVideoResolution();
            }
          }
        } catch (err) {
          console.error('Failed to load model configs:', err);
        }
      },

      ensureVideoResolution() {
        if (!window.TaskConfig || typeof TaskConfig.getVideoResolutionOptions !== 'function') {
          this.videoResolution = '';
          return;
        }
        const options = TaskConfig.getVideoResolutionOptions(this.videoModel);
        if (!options.length) {
          this.videoResolution = '';
          return;
        }
        const values = options.map(opt => opt.value);
        if (!this.videoResolution || !values.includes(this.videoResolution)) {
          this.videoResolution = (
            typeof TaskConfig.getDefaultVideoResolution === 'function'
              ? TaskConfig.getDefaultVideoResolution(this.videoModel)
              : null
          ) || options[0].value;
        }
      },

      async submit(){
        if(!this.canSubmit) return;
        this.loading = true;
        this.error='';
        this.results=[];
        this.projectIds=[];
        this.projectId='';
        this.status='';

        try {
          // Get task_id from model key
          const taskId = TaskConfig.getTaskIdByKey(this.videoModel, 'text_to_video');
          if (!taskId) {
            throw new Error(`未找到文生视频模型 ${this.videoModel} 对应的任务配置`);
          }

          const form = new FormData();
          form.append('prompt', this.prompt);
          form.append('task_id', taskId);  // Pass task_id (not model key)
          form.append('ratio', this.model);
          if (this.videoResolution) {
            form.append('resolution', this.videoResolution);
          }
          form.append('duration_seconds', this.durationSeconds);
          form.append('count', this.count);
          form.append('timeout', '900'); // 15 minutes timeout

          // Add user_id from localStorage
          const userId = localStorage.getItem('user_id');
          if (userId) {
            form.append('user_id', userId);
          }

          // Add auth_token if available
          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const res = await axios.post('/api/ai-app-run', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
          
          // Handle multiple project IDs
          this.projectIds = res.data.project_ids || [];
          this.projectId = this.projectIds.join(', ');
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
            // Single task response (backward compatibility)
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
          // Don't stop polling on temporary errors, just log and continue
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
        const filename = `ai_video_gen_${dateStr}_${timeStr}_${index + 1}.mp4`;
        const downloadUrl = buildDownloadUrl(url, filename);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = filename;
        link.target = '_blank';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      },
      downloadHistoryResult(item) {
        if (!item.result_url) {
          alert('暂无可下载的结果');
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
        const prefix = item.type === 5 ? 'ai_video_enhance' : 'ai_video_gen';
        const filename = `${prefix}_${dateStr}_${timeStr}.mp4`;
        const downloadUrl = buildDownloadUrl(item.result_url, filename);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = filename;
        link.target = '_blank';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      },
      async enhanceVideo(item, index) {
        console.log('enhanceVideo called with:', { item, index, enhancingVideos: this.enhancingVideos });
        const videoUrl = item?.file_url || item?.result_url;
        if (!videoUrl) {
          console.log('Early return: missing videoUrl for enhancement');
          alert('暂无可增强的视频');
          return;
        }
        if (this.enhancingVideos[index]) {
          console.log('Early return: enhancingVideos[index]=', this.enhancingVideos[index]);
          return;
        }

        const userId = localStorage.getItem('user_id');
        if (!userId) {
          alert('请先登录');
          return;
        }

        try {
          this.$set ? this.$set(this.enhancingVideos, index, true) : (this.enhancingVideos[index] = true);

          const form = new FormData();
          form.append('video_url', videoUrl);
          form.append('user_id', userId);
          form.append('enhance_type', '5'); // Type 5 for AI视频生成

          const authToken = localStorage.getItem('auth_token');
          if (authToken) {
            form.append('auth_token', authToken);
          }

          const res = await axios.post('/api/video-enhance', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });

          if (res.data.status === 'submitted' && res.data.project_id) {
            this.enhanceTaskIds = this.enhanceTaskIds || {};
            this.enhanceTaskIds[index] = res.data.project_id;
            this.pollEnhanceStatus(item, index);
            alert('视频修复任务已提交');
          } else {
            throw new Error('任务提交失败');
          }
        } catch (err) {
          console.error(err);
          alert(err?.response?.data?.detail || err?.message || '视频修复失败');
          this.$set ? this.$set(this.enhancingVideos, index, false) : (this.enhancingVideos[index] = false);
        }
      },
      
      async pollEnhanceStatus(item, index) {
        const taskId = this.enhanceTaskIds?.[index];
        if (!taskId) {
          return;
        }

        try {
          const authToken = localStorage.getItem('auth_token');
          const params = authToken ? { auth_token: authToken } : {};
          const res = await axios.get(`/api/runninghub-status/${taskId}`, { params });
          if (res.data.status === 'SUCCESS') {
            if (res.data.results && res.data.results.length > 0) {
              this.$set ? this.$set(item, 'enhancedVideo', res.data.results[0]) : (item.enhancedVideo = res.data.results[0]);
            } else {
              console.warn('No results in SUCCESS response');
            }
            this.$set ? this.$set(this.enhancingVideos, index, false) : (this.enhancingVideos[index] = false);
            delete this.enhanceTaskIds[index];
          } else if (res.data.status === 'FAILED') {
            alert('视频增强失败');
            this.$set ? this.$set(this.enhancingVideos, index, false) : (this.enhancingVideos[index] = false);
            delete this.enhanceTaskIds[index];
          } else {
            this.enhanceStatusTimers[index] = setTimeout(() => this.pollEnhanceStatus(item, index), 5000);
          }
        } catch (err) {
          this.enhanceStatusTimers[index] = setTimeout(() => this.pollEnhanceStatus(item, index), 5000);
        }
      },

      async fetchHistory(append = false) {
        const userId = localStorage.getItem('user_id');
        if (!userId) {
          alert('请先登录');
          return;
        }

        if (!append) {
          this.historyPage = 1;
          this.historyList = [];
        }

        this.historyLoading = true;
        try {
          const authToken = localStorage.getItem('auth_token');

          // 获取文生视频任务类型列表
          let textToVideoTypes = [2];  // 默认 Sora2 TEXT_TO_VIDEO = 2
          try {
            // 尝试从 TaskConfig 中获取
            await TaskConfig.load();
            const types = TaskConfig.getTaskTypeIdsByCategory('text_to_video');
            if (types && types.length > 0) {
              textToVideoTypes = types;
            }
          } catch (err) {
            console.warn('Failed to get text_to_video types from TaskConfig, using default:', err);
          }
          const typesStr = textToVideoTypes.join(',');

          const response = await axios.get('/api/ai-tools/history', {
            params: {
              user_id: parseInt(userId),
              page: this.historyPage,
              page_size: 20,
              types: typesStr,  // 使用后端配置的所有文生视频类型
              auth_token: authToken || undefined
            }
          });
          
          if (response.data.success) {
            const newData = response.data.data.data || [];
            if (append) {
              this.historyList = [...this.historyList, ...newData];
            } else {
              this.historyList = newData;
            }
            this.historyTotal = response.data.data.total || 0;
            this.showHistory = true;
          } else {
            alert(response.data.message || '获取历史记录失败');
          }
        } catch (err) {
          console.error(err);
          alert(err?.response?.data?.message || '获取历史记录失败');
        } finally {
          this.historyLoading = false;
        }
      },
      
      getHistoryPrompt(item) {
        return item.prompt || '无提示词';
      },
      
      getHistoryTypeText(type) {
        return this.typeNameMap[type] || '未知类型';
      },
      
      async loadMoreHistory() {
        if (this.historyLoading || this.historyList.length >= this.historyTotal) {
          return;
        }
        this.historyPage++;
        await this.fetchHistory(true);
      },
      
      handleHistoryScroll(event) {
        const element = event.target;
        const scrollBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
        if (scrollBottom < 100) {
          this.loadMoreHistory();
        }
      },
      
      closeHistory() {
        this.showHistory = false;
        this.historyPage = 1;
        this.historyList = [];
      },
      
      getStatusText(status) {
        const statusMap = {
          0: '未处理',
          1: '处理中',
          2: '处理完成',
          3: '排队处理中',
          '-1': '处理失败'
        };
        return statusMap[status] || '未知';
      },
      
      getStatusColor(status) {
        const colorMap = {
          0: '#888',
          1: '#3b82f6',
          2: '#10b981',
          '-1': '#ef4444'
        };
        return colorMap[status] || '#888';
      },
      
      getModelLabel(value) {
        const modelMap = {
          '9:16': '竖屏',
          '16:9': '横屏'
        };
        const resolved = value || this.model;
        return modelMap[resolved] || resolved || '未知';
      },

      getDurationText(item) {
        const duration = item?.original_duration ?? item?.duration ?? item?.video_duration ?? (typeof this.durationSeconds === 'number' ? this.durationSeconds : null);
        return duration ? `${duration}秒` : '未知';
      },

      getGenerationMode(item) {
        return getGenerationModeLabel(item);
      }
    },
    
    beforeUnmount() {
      this.clearStatusCheck();
      // 清理所有增强状态轮询定时器
      Object.values(this.enhanceStatusTimers || {}).forEach(timer => {
        if (timer) clearTimeout(timer);
      });
    },
    
    template: `
      <div>
        <div class="form">
          <div class="field">
            <label class="label">{{ $t('video_prompt') }}</label>
            <textarea class="textarea" v-model.trim="prompt" :placeholder="$t('describe_video_content')"></textarea>
          </div>

          <div class="field">
            <label class="label">{{ $t('model_selection') }}</label>
            <select class="input" v-model="videoModel">
              <option value="">-- {{ $t('model_selection') }} --</option>
              <option v-for="opt in videoModelOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('aspect_ratio') }}</label>
            <select class="input" v-model="model">
              <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="field" v-if="videoResolutionOptions.length">
            <label class="label">{{ $t('video_resolution') || '分辨率' }}</label>
            <select class="input" v-model="videoResolution">
              <option v-for="opt in videoResolutionOptions" :key="opt.value" :value="opt.value">
                {{ opt.label || opt.value }}
              </option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('duration_label') }}</label>
            <select class="input" v-model="durationSeconds">
              <option v-for="opt in durationOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('number_of_images') }}</label>
            <select class="input" v-model.number="count">
              <option v-for="opt in countOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field" style="background: #1a1f2e; padding: 12px; border-radius: 8px; border: 1px solid var(--border);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: var(--muted); font-size: 14px;">{{ $t('power_consumption') }}：</span>
              <span style="color: #60a5fa; font-weight: bold; font-size: 16px;">{{ totalComputingPower }} {{ $t('power_unit') }}</span>
            </div>
            <div style="margin-top: 6px; font-size: 12px; color: var(--muted);">
              {{ $t('single') }} {{ computingPower }} {{ $t('power_unit') }} × {{ count }} {{ $t('items') }} = {{ totalComputingPower }} {{ $t('power_unit') }}
            </div>
          </div>

          <div class="field">
            <div class="row">
              <button class="btn" :disabled="!canSubmit" @click="submit">{{ loading ? $t('generating') : $t('start_generating') }}</button>
              <button class="btn secondary" @click="fetchHistory" :disabled="historyLoading">{{ historyLoading ? $t('loading') : $t('history') }}</button>
            </div>
          </div>
        </div>

        <div class="status" v-if="projectId">{{ $t('task_id') }}：{{ projectId }}</div>
        <div class="status" v-if="statusText">{{ statusText }}</div>
        <div class="status danger" v-if="error">{{ error }}</div>

        <div class="preview" v-if="results.length">
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px;">
            <div v-for="(result, i) in results" :key="i" style="border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: #0b1220;">
              <div style="margin-bottom: 12px; font-size: 14px; font-weight: bold; color: var(--muted);">{{ $t('video') }} #{{ i + 1 }}</div>

              <!-- 原视频 -->
              <div style="margin-bottom: 16px;">
                <div style="margin-bottom: 8px; font-weight: bold; color: var(--primary); text-align: center;">{{ $t('original_image') }}</div>
                <video :src="result.file_url" controls style="width: 100%; border-radius: 8px;"></video>
                <div style="padding: 8px; text-align: center;">
                  <button class="btn secondary" @click="downloadVideo(result.file_url, i)" style="font-size: 12px; padding: 6px 12px;">{{ $t('download_video') }}</button>
                  <button class="btn" @click="enhanceVideo(result, i)" :disabled="enhancingVideos[i]" style="font-size: 12px; padding: 6px 12px; margin-left: 8px;">
                    {{ enhancingVideos[i] ? $t('processing') : $t('download_image_hd') }}
                  </button>
                  <div class="muted" style="margin-top: 4px; font-size: 11px;">{{ $t('cost_time') }}: {{ result.task_cost_time || $t('unknown') }}</div>
                </div>
              </div>

              <!-- 高清视频 -->
              <div v-if="result.enhancedVideo" style="border-top: 1px solid var(--border); padding-top: 16px;">
                <div style="margin-bottom: 8px; font-weight: bold; color: #10b981; text-align: center;">{{ $t('hd_video') }}</div>
                <video :src="result.enhancedVideo.file_url || result.enhancedVideo" controls style="width: 100%; border-radius: 8px;"></video>
                <div style="padding: 8px; text-align: center;">
                  <button class="btn secondary" @click="downloadVideo(result.enhancedVideo.file_url || result.enhancedVideo, i, true)" style="font-size: 12px; padding: 6px 12px;">
                    {{ $t('download_hd_video') }}
                  </button>
                  <div class="muted" style="margin-top: 4px; font-size: 11px;">{{ $t('cost_time') }}: {{ result.enhancedVideo.task_cost_time || $t('unknown') }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- History Modal -->
        <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
          <div class="modal" style="max-width: 800px; max-height: 80vh; overflow-y: auto;" @scroll="handleHistoryScroll">
            <div style="position: relative;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; padding-right: 40px; margin-bottom: 12px;">
                <div style="display: flex; align-items: flex-start; gap: 12px;">
                  <div class="modal-title">{{ $t('history') }} ({{ $t('total_records') }} {{ historyTotal }} {{ $t('items') }})</div>
                  <button class="btn secondary" @click="fetchHistory(false)" :disabled="historyLoading" style="display: inline-flex; align-items: center; justify-content: center; padding: 4px 12px; font-size: 12px;">
                    {{ historyLoading ? $t('refreshing') : $t('refresh') }}
                  </button>
                </div>
                <button class="modal-close" @click="closeHistory">×</button>
              </div>
            </div>

            <div v-if="historyList.length === 0" style="padding: 40px; text-align: center; color: var(--muted);">
              {{ $t('no_history') }}
            </div>

            <div v-else style="padding: 16px;">
              <div v-for="item in historyList" :key="item.id" style="margin-bottom: 16px; padding: 12px; background: #0b1220; border: 1px solid var(--border); border-radius: 8px;">
                <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                  <div>
                    <strong>{{ $t('prompt_label') }}</strong> {{ getHistoryPrompt(item) }}
                  </div>
                  <span :style="{ padding: '4px 12px', borderRadius: '4px', fontSize: '12px', fontWeight: 'bold', backgroundColor: getStatusColor(item.status) + '20', color: getStatusColor(item.status), border: '1px solid ' + getStatusColor(item.status), cursor: item.status == -1 && item.message ? 'help' : 'default' }" :title="item.status == -1 && item.message ? item.message : ''">
                    {{ getStatusText(item.status) }}
                  </span>
                </div>
                <div style="display: flex; gap: 16px; font-size: 13px; color: var(--muted); margin-bottom: 8px;">
                  <span>{{ $t('type_label') }}: {{ getHistoryTypeText(item.type) }}</span>
                  <span>{{ $t('mode_switch') }}: {{ getModelLabel(item.ratio) }}</span>
                  <span>生成模式: {{ getGenerationMode(item) }}</span>
                  <span>{{ $t('duration_label') }}: {{ getDurationText(item) }}</span>
                  <span>{{ $t('create_time') }}: {{ item.create_time ? new Date(item.create_time).toLocaleString('zh-CN') : $t('unknown') }}</span>
                </div>
                <div v-if="item.video_path" style="margin-top: 12px; padding: 12px; background: #0f1620; border-radius: 8px; border: 1px solid var(--border);">
                  <div style="font-size: 12px; color: var(--muted); margin-bottom: 8px;">{{ $t('reference_video_label') || '参考视频' }}:</div>
                  <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                    <template v-for="(video, vidx) in item.video_path.split(',')" :key="vidx">
                      <div v-if="video">
                        <a :href="'/video-viewer.html?url=' + encodeURIComponent(video.trim())" target="_blank" class="btn secondary" style="font-size: 12px; padding: 4px 12px; text-decoration: none;">{{ $t('view_original') || '查看原视频' }}</a>
                      </div>
                    </template>
                  </div>
                </div>
                <div v-if="item.result_url" style="margin-top: 8px;">
                  <button class="btn secondary" @click="downloadHistoryResult(item)" style="display: inline-block; margin-right: 8px;">{{ $t('view_result') }}</button>
                  <button v-if="item.status == 2 && item.type == 2" class="btn" @click="enhanceVideo(item, item.id)" :disabled="enhancingVideos[item.id]" style="display: inline-block;">{{ enhancingVideos[item.id] ? $t('fixed') : $t('generate_hd_video') }}</button>
                </div>
                <div style="margin-top: 8px;">
                  <button class="btn secondary" @click="timelineAiToolId = item.id">{{ $t('view_timeline') }}</button>
                </div>
              </div>

              <!-- Loading indicator -->
              <div v-if="historyLoading" style="text-align: center; padding: 20px; color: var(--muted);">
                {{ $t('loading') }}
              </div>

              <!-- End indicator -->
              <div v-else-if="historyList.length >= historyTotal" style="text-align: center; padding: 20px; color: var(--muted);">
                {{ $t('all_data_loaded') }}
              </div>
            </div>
          </div>
        </div>
        <timeline-modal v-if="timelineAiToolId" :ai-tool-id="timelineAiToolId" @close="timelineAiToolId = null"></timeline-modal>
      </div>
    `
  };

if (typeof window !== "undefined") window.AIVideoGen = AIVideoGen;
