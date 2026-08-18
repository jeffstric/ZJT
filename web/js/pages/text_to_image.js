  const TextToImage = {
    name: 'TextToImage',
    data() {
      return {
        prompt: '',
        model: 'gemini',  // 简短 key，对应 gemini_image_edit
        aspectRatio: '9:16',
        imageSize: '1K',
        count: 1,
        loading: false,
        error: '',
        results: [],
        projectIds: [],
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
        driverStatus: {},  // 驱动可用状态
        taskTypeConfig: null,  // 从后端获取的任务类型配置
        modelConfigs: {},  // 从后端获取的模型配置
        configLoaded: false  // 配置是否已加载
      }
    },
    mounted() {
      this.authToken = localStorage.getItem('auth_token') || '';
      // 获取驱动状态
      this.fetchDriverStatus();
      // 获取任务类型配置
      this.fetchTaskTypeConfig();
      // 获取模型配置
      this.fetchModelConfigs();
    },
    computed: {
      canSubmit() { return !!this.prompt.trim() && !this.loading },
      modelOptions() {
        // 依赖 configLoaded 触发重新计算
        if (!this.configLoaded) return [];
        // 动态从配置获取文生图模型列表
        const allOptions = TaskConfig.getModelOptionsForCategory('text_to_image');
        return allOptions.map(opt => {
          const isAvailable = !this.driverStatus || !this.driverStatus[opt.taskType] || this.driverStatus[opt.taskType].available !== false;
          return {
            value: opt.value,
            label: isAvailable ? opt.label : opt.label + ' (未配置)',
            disabled: !isAvailable,
            track: opt.track || null,
          };
        });
      },
      imageTrack() {
        if (!window.ModelCatalog) return 'custom';
        return window.ModelCatalog.inferTrack('image.text_to_image', this.model, null);
      },
      aspectRatioOptions() {
        const config = this.modelConfigs[this.model];
        if (!config || !config.ratios) {
          return [
            { value: '1:1', label: '1:1' },
            { value: '9:16', label: '9:16 (竖屏)' },
            { value: '16:9', label: '16:9 (横屏)' }
          ];
        }
        const labelMap = {
          '9:16': '9:16 (竖屏)',
          '16:9': '16:9 (横屏)',
          '1:1': '1:1',
          '3:4': '3:4',
          '4:3': '4:3',
          '3:2': '3:2',
          '2:3': '2:3',
          '21:9': '21:9',
          '4:5': '4:5',
          '5:4': '5:4'
        };
        return config.ratios.map(ratio => ({
          value: ratio,
          label: labelMap[ratio] || ratio
        }));
      },
      imageSizeOptions() {
        const config = this.modelConfigs[this.model];
        if (!config || !config.image_sizes) {
          return [
            { value: '1K', label: '1K' },
            { value: '2K', label: '2K' }
          ];
        }
        return config.image_sizes.map(size => ({
          value: size,
          label: size
        }));
      },
      countOptions() {
        return [
          { value: 1, label: '1张' },
          { value: 2, label: '2张' },
          { value: 3, label: '3张' },
          { value: 4, label: '4张' }
        ];
      },
      statusText() {
        switch(this.status) {
          case 'submitted': return '任务已提交，等待处理...';
          case 'QUEUED': return '任务排队中...';
          case 'RUNNING': return '正在生成图片...';
          case 'SUCCESS': return '生成完成！';
          case 'FAILED': return '任务失败';
          default: return '';
        }
      }
    },
    watch: {
      model(newModel) {
        // 切换模型时，更新默认值
        const config = this.modelConfigs[newModel];
        if (config) {
          if (config.default_ratio && !config.ratios.includes(this.aspectRatio)) {
            this.aspectRatio = config.default_ratio;
          }
          if (config.default_image_size && config.image_sizes && !config.image_sizes.includes(this.imageSize)) {
            this.imageSize = config.default_image_size;
          }
        }
      }
    },
    methods: {
      async fetchDriverStatus() {
        try {
          const response = await axios.get('/api/computing-power-config');
          if (response.data.success && response.data.data.driver_status) {
            this.driverStatus = response.data.data.driver_status;
          }
        } catch (error) {
          console.error('获取驱动状态异常:', error);
        }
      },

      async fetchTaskTypeConfig() {
        try {
          await TaskConfig.load();
          this.taskTypeConfig = TaskConfig.getTaskTypeConfig();
        } catch (err) {
          console.error('获取任务类型配置失败:', err);
        }
      },

      selectImageTrack(track) {
        if (!window.ModelCatalog) return;
        const hit = window.ModelCatalog.findTaskByTrack(
          this.modelOptions, 'image.text_to_image', null, track
        );
        if (hit && !hit.disabled) this.model = hit.value;
      },

      async fetchModelConfigs() {
        try {
          await TaskConfig.load();
          this.modelConfigs = TaskConfig.getModelConfigs();
          this.configLoaded = true;  // 标记配置已加载
          
          // 检查当前 model 是否在可用选项中，如果不在则选择第一个
          const allOptions = TaskConfig.getModelOptionsForCategory('text_to_image');
          const validValues = allOptions.map(opt => opt.value);
          const valueOpt = allOptions.find((opt) => opt.track === 'value' && validValues.includes(opt.value));
          if (!validValues.includes(this.model) && (valueOpt || allOptions.length > 0)) {
            this.model = (valueOpt || allOptions[0]).value;
          }
          
          // 设置初始默认值
          const config = this.modelConfigs[this.model];
          if (config) {
            if (config.default_ratio) this.aspectRatio = config.default_ratio;
            if (config.default_image_size) this.imageSize = config.default_image_size;
          }
        } catch (err) {
          console.error('获取模型配置失败:', err);
        }
      },

      async submit(){
        if(!this.canSubmit) return;
        
        const userId = localStorage.getItem('user_id');
        if (!userId) {
          this.error = '请先登录后再使用文生图功能';
          return;
        }
        
        this.loading = true; 
        this.error=''; 
        this.results=[]; 
        this.projectIds=[]; 
        this.projectId=''; 
        this.status='';
        this.clearStatusCheck();
        
        try {
          const form = new FormData();
          form.append('prompt', this.prompt);
          form.append('aspect_ratio', this.aspectRatio);
          form.append('count', this.count);
          form.append('user_id', userId);
          
          // 根据 model 获取 task_id
          const taskId = TaskConfig.getTaskIdByKey(this.model, 'text_to_image');
          if (!taskId) {
            throw new Error(`未找到模型 ${this.model} 对应的任务配置`);
          }
          form.append('task_id', taskId);
          
          if (this.imageSize) {
            form.append('image_size', this.imageSize);
          }
          
          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const res = await axios.post('/api/text-to-image', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
          
          this.projectIds = res.data.project_ids || [];
          this.projectId = this.projectIds.join(', ');
          this.status = res.data.status || 'submitted';
          
          this.startStatusCheck();
          
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
          
          const projectIdsStr = this.projectIds.join(',');
          const res = await axios.get(`/api/get-status/${projectIdsStr}`, { params });
          
          if (res.data.tasks) {
            const tasks = res.data.tasks;
            const allSuccess = tasks.every(t => t.status === 'SUCCESS');
            const anyFailed = tasks.some(t => t.status === 'FAILED');
            const anyRunning = tasks.some(t => t.status === 'RUNNING');
            
            const allResults = [];
            tasks.forEach((task, taskIndex) => {
              if (task.results && task.results.length > 0) {
                task.results.forEach(result => {
                  allResults.push({
                    ...result,
                    project_id: this.projectIds[taskIndex]
                  });
                });
              }
            });
            
            this.results = allResults;
            
            if (allSuccess) {
              this.status = 'SUCCESS';
              this.loading = false;
              this.clearStatusCheck();
            } else if (anyFailed && !anyRunning) {
              const failedTasks = tasks.filter(t => t.status === 'FAILED');
              this.error = `${failedTasks.length} 个任务失败`;
              this.status = 'FAILED';
              this.loading = false;
              this.clearStatusCheck();
            } else {
              this.status = 'RUNNING';
            }
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
      
      isWechatBrowser() {
        const ua = navigator.userAgent.toLowerCase();
        return /micromessenger/.test(ua);
      },
      
      downloadImage(url, index) {
        const now = new Date();
        const dateStr = now.getFullYear().toString() +
                       (now.getMonth() + 1).toString().padStart(2, '0') +
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') +
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `text_to_image_${dateStr}_${timeStr}_${index + 1}.png`;
        const downloadUrl = buildDownloadUrl(url, filename);
        
        if (this.isWechatBrowser()) {
          window.open(downloadUrl, '_blank');
          setTimeout(() => {
            alert('请长按图片，然后选择"保存图片"');
          }, 500);
        } else {
          const link = document.createElement('a');
          link.href = downloadUrl;
          link.download = filename;
          link.target = '_blank';
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
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
          // 如果没有获取到任务类型配置，先获取
          if (!this.taskTypeConfig) {
            await this.fetchTaskTypeConfig();
          }
          // 文生图界面只查询文生图类型
          const textToImageTypes = this.taskTypeConfig?.text_to_image_types || [16];
          const typesStr = textToImageTypes.join(',');

          const response = await axios.get('/api/ai-tools/history', {
            params: {
              user_id: parseInt(userId),
              page: this.historyPage,
              page_size: 20,
              types: typesStr,
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
      
      getAspectRatioLabel(value) {
        const option = this.aspectRatioOptions.find(opt => opt.value === value);
        return option ? option.label : value || '未知';
      },

    },

    beforeUnmount() {
      this.clearStatusCheck();
    },
    template: `
      <div>
        <div class="form">
          <div class="field">
            <label class="label">{{ $t('prompt') }} <span style="color: red;">*</span></label>
            <textarea class="textarea" v-model.trim="prompt" :placeholder="$t('prompt_placeholder')" rows="4"></textarea>
          </div>

          <div class="field">
            <label class="label">{{ $t('model_selection') }}</label>
            <div class="model-track-toggle" v-if="modelOptions.length">
              <button type="button" class="model-track-btn" :class="{ 'is-active': imageTrack === 'value' }" @click="selectImageTrack('value')">性价比</button>
              <button type="button" class="model-track-btn" :class="{ 'is-active': imageTrack === 'quality' }" @click="selectImageTrack('quality')">效果</button>
            </div>
            <select class="input" v-model="model">
              <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value" :disabled="opt.disabled">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('aspect_ratio') }}</label>
            <select class="input" v-model="aspectRatio">
              <option v-for="opt in aspectRatioOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field" v-if="imageSizeOptions.length > 0">
            <label class="label">{{ $t('resolution') }}</label>
            <select class="input" v-model="imageSize">
              <option v-for="opt in imageSizeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('number_of_images') }}</label>
            <select class="input" v-model.number="count">
              <option v-for="opt in countOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field">
            <div class="row">
              <button class="btn" :disabled="!canSubmit" @click="submit">{{ loading ? $t('generating') : $t('start_generating') }}</button>
              <button class="btn secondary" @click="fetchHistory" :disabled="historyLoading">{{ historyLoading ? $t('loading_more') : $t('history') }}</button>
            </div>
          </div>
        </div>

        <div class="status" v-if="projectId">任务 ID：{{ projectId }}</div>
        <div class="status" v-if="statusText">{{ statusText }}</div>
        <div class="status danger" v-if="error">{{ error }}</div>

        <div class="preview" v-if="results.length">
          <div class="imgbox" v-for="(result, i) in results" :key="i">
            <div style="margin-bottom: 8px; font-weight: bold; color: var(--primary); text-align: center;">{{ $t('generation_result') }} #{{ i + 1 }}</div>
            <img :src="result.file_url" :alt="'result-'+i" />
            <div style="padding: 8px; text-align: center;">
              <button class="btn secondary" @click="downloadImage(result.file_url, i)">{{ $t('download_image') }}</button>
              <div class="muted" style="margin-top: 4px; font-size: 11px;" v-if="result.task_cost_time">{{ $t('time_cost') }}: {{ result.task_cost_time }}s</div>
            </div>
          </div>
        </div>
        
        <!-- History Modal -->
        <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
          <div class="modal" style="max-width: 800px; max-height: 80vh; overflow-y: auto;" @scroll="handleHistoryScroll">
            <div class="modal-sticky-header">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; padding-right: 40px; margin-bottom: 12px;">
                <div style="display: flex; align-items: flex-start; gap: 12px;">
                  <div class="modal-title">{{ $t('history_modal_title') }} ({{ $t('total_records') }} {{ historyTotal }})</div>
                  <button
                    class="btn secondary"
                    @click="fetchHistory(false)"
                    :disabled="historyLoading"
                    style="display: inline-flex; align-items: center; justify-content: center; padding: 4px 12px; font-size: 12px;"
                  >
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
                    <strong>{{ $t('prompt_label') }}</strong> {{ item.prompt }}
                  </div>
                  <span :style="{ padding: '4px 12px', borderRadius: '4px', fontSize: '12px', fontWeight: 'bold', backgroundColor: getStatusColor(item.status) + '20', color: getStatusColor(item.status), border: '1px solid ' + getStatusColor(item.status), cursor: item.status == -1 && item.message ? 'help' : 'default' }" :title="item.status == -1 && item.message ? item.message : ''">
                    {{ getStatusText(item.status) }}
                  </span>
                </div>
                <div style="display: flex; gap: 16px; font-size: 13px; color: var(--muted); margin-bottom: 8px;">
                  <span>{{ $t('type_label') }}: {{ $t('text_to_image') }}</span>
                  <span>{{ $t('aspect_ratio_label') }}: {{ getAspectRatioLabel(item.ratio) }}</span>
                  <span v-if="item.model_name">{{ $t('model') }}: {{ item.model_name }}</span>
                  <span v-if="item.implementation_name">{{ $t('driver') }}: {{ item.implementation_name }}</span>
                  <span>{{ $t('created_at') }}: {{ item.create_time ? new Date(item.create_time).toLocaleString('zh-CN') : $t('unknown') }}</span>
                </div>
                <div v-if="item.result_url" style="margin-top: 8px;">
                  <a :href="item.result_url" target="_blank" class="btn secondary" style="display: inline-block; text-decoration: none;">{{ $t('view_result') }}</a>
                </div>
                <div style="margin-top: 8px;">
                  <button class="btn secondary" @click="timelineAiToolId = item.id">{{ $t('view_timeline') }}</button>
                </div>
              </div>
              
              <div v-if="historyLoading" style="text-align: center; padding: 20px; color: var(--muted);">
                {{ $t('loading_more') }}
              </div>

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

if (typeof window !== "undefined") window.TextToImage = TextToImage;
