  const ImageEdit = {
    name: 'ImageEdit',
    data() {
      return {
        files: [],
        prompt: '',
        ratio: '9:16',
        count: 1,
        model: 'gemini',  // 简短 key，对应 gemini_image_edit
        imageSize: '1K',
        refAudioFiles: [],
        refVideoFiles: [],
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
        upscalingImages: {},
        upscaleProjectIds: {},
        upscaleResults: {},
        upscaleStatusIntervals: {},
        driverStatus: {},  // 驱动可用状态
        taskTypeConfig: null,  // 从后端获取的任务类型配置
        modelConfigs: {},  // 从后端获取的模型配置
        configLoaded: false  // 配置是否已加载
      }
    },
    mounted() {
      // Get auth_token from localStorage (set by App component)
      this.authToken = localStorage.getItem('auth_token') || '';
      // 获取驱动状态
      this.fetchDriverStatus();
      // 获取任务类型配置
      this.fetchTaskTypeConfig();
      // 获取模型配置
      this.fetchModelConfigs();
    },
    computed: {
      canSubmit() { return this.files.length > 0 && this.files.length <= 5 && !!this.prompt && !this.loading },
      ratioOptions() {
        const config = this.modelConfigs[this.model];
        if (!config || !config.ratios) {
          return [
            { value: '9:16', label: '竖屏 (9:16)' },
            { value: '16:9', label: '横屏 (16:9)' },
            { value: '1:1', label: '正方形 (1:1)' },
            { value: '3:4', label: '竖屏 (3:4)' },
            { value: '4:3', label: '横屏 (4:3)' }
          ];
        }
        const labelMap = {
          '9:16': '竖屏 (9:16)',
          '16:9': '横屏 (16:9)',
          '1:1': '正方形 (1:1)',
          '3:4': '竖屏 (3:4)',
          '4:3': '横屏 (4:3)',
          '3:2': '3:2',
          '2:3': '2:3',
          '21:9': '21:9'
        };
        return config.ratios.map(ratio => ({
          value: ratio,
          label: labelMap[ratio] || ratio
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
      modelOptions() {
        // 依赖 configLoaded 触发重新计算
        if (!this.configLoaded) return [];
        // 动态从配置获取图片编辑模型列表
        const allOptions = TaskConfig.getModelOptionsForCategory('image_edit');
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
        return window.ModelCatalog.inferTrack('image.image_edit', this.model, null);
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
      statusText() {
        switch(this.status) {
          case 'submitted': return '任务已提交，等待处理...';
          case 'QUEUED': return '任务排队中...';
          case 'RUNNING': return '正在生成图片...';
          case 'SUCCESS': return '生成完成！';
          case 'FAILED': return '任务失败';
          default: return '';
        }
      },
      currentModelConfig() {
        return this.modelConfigs[this.model] || {};
      },
      supportsRefAudioVideo() {
        // 确保配置已加载，且当前模型支持
        if (!this.configLoaded) return false;
        return this.currentModelConfig.supports_ref_audio_video === true;
      }
    },
    watch: {
      model(newModel) {
        // 切换模型时，更新默认值
        const config = this.modelConfigs[newModel];
        if (config) {
          if (config.default_ratio && !config.ratios.includes(this.ratio)) {
            this.ratio = config.default_ratio;
          }
          if (config.default_image_size && config.image_sizes && !config.image_sizes.includes(this.imageSize)) {
            this.imageSize = config.default_image_size;
          }
        }
      }
    },
    methods: {
      selectImageTrack(track) {
        if (!window.ModelCatalog) return;
        const hit = window.ModelCatalog.findTaskByTrack(
          this.modelOptions, 'image.image_edit', null, track
        );
        if (hit && !hit.disabled) this.model = hit.value;
      },
      parseReferenceImages(item) {
        try {
          if (item.reference_images) return JSON.parse(item.reference_images);
        } catch (e) { /* malformed JSON */ }
        if (item.image_path) return item.image_path.split(',');
        return [];
      },
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

      async fetchModelConfigs() {
        try {
          await TaskConfig.load();
          this.modelConfigs = TaskConfig.getModelConfigs();
          this.configLoaded = true;  // 标记配置已加载
          
          // 检查当前 model 是否在可用选项中，如果不在则选择第一个
          const allOptions = TaskConfig.getModelOptionsForCategory('image_edit');
          const validValues = allOptions.map(opt => opt.value);
          const valueOpt = window.ModelCatalog
            ? window.ModelCatalog.findTaskByTrack(allOptions, 'image.image_edit', null, 'value')
            : allOptions.find((opt) => opt.track === 'value');
          if (!validValues.includes(this.model) && (valueOpt || allOptions.length > 0)) {
            this.model = (valueOpt && valueOpt.value) || allOptions[0].value;
          }
          
          // 设置初始默认值
          const config = this.modelConfigs[this.model];
          if (config) {
            if (config.default_ratio) this.ratio = config.default_ratio;
            if (config.default_image_size) this.imageSize = config.default_image_size;
          }
        } catch (err) {
          console.error('获取模型配置失败:', err);
        }
      },

      onFile(e){ 
        const selectedFiles = Array.from(e.target.files || []);
        const remainingSlots = 5 - this.files.length;
        
        if (remainingSlots <= 0) {
          alert('已达到最大数量5张图片，请先删除一些图片');
          e.target.value = ''; // 清空input
          return;
        }
        
        if (selectedFiles.length > remainingSlots) {
          alert(`最多还能添加${remainingSlots}张图片，已自动截取前${remainingSlots}张`);
          this.files = [...this.files, ...selectedFiles.slice(0, remainingSlots)];
        } else {
          this.files = [...this.files, ...selectedFiles];
        }
        
        e.target.value = ''; // 清空input，允许重复选择同一文件
      },
      
      removeFile(index) {
        this.files.splice(index, 1);
      },
      
      clearAllFiles() {
        this.files = [];
      },

      onRefAudioFile(e) {
        const selectedFiles = Array.from(e.target.files || []);
        this.refAudioFiles = [...this.refAudioFiles, ...selectedFiles];
        e.target.value = '';
      },

      onRefVideoFile(e) {
        const selectedFiles = Array.from(e.target.files || []);
        this.refVideoFiles = [...this.refVideoFiles, ...selectedFiles];
        e.target.value = '';
      },

      removeRefAudioFile(index) {
        this.refAudioFiles.splice(index, 1);
      },

      removeRefVideoFile(index) {
        this.refVideoFiles.splice(index, 1);
      },

      clearAllRefAudioFiles() {
        this.refAudioFiles = [];
      },

      clearAllRefVideoFiles() {
        this.refVideoFiles = [];
      },

      async submit(){
        if(!this.canSubmit) return;
        this.loading = true; this.error=''; this.results=[]; this.projectIds=[]; this.projectId=''; this.status='';
        this.clearStatusCheck();
        
        try {
          const form = new FormData();
          // Append all images
          this.files.forEach(file => {
            form.append('image', file);
          });
          form.append('prompt', this.prompt);
          form.append('ratio', this.ratio);
          form.append('count', this.count);
          form.append('image_size', this.imageSize);

          // 添加参考音频和视频（仅当模型支持时）
          if (this.supportsRefAudioVideo) {
            // 添加参考音频文件
            if (this.refAudioFiles && this.refAudioFiles.length > 0) {
              this.refAudioFiles.forEach(file => {
                form.append('audio_files', file);
              });
            }
            // 添加参考视频文件
            if (this.refVideoFiles && this.refVideoFiles.length > 0) {
              this.refVideoFiles.forEach(file => {
                form.append('video_files', file);
              });
            }
          }

          // 根据 model 获取 task_id
          const taskId = TaskConfig.getTaskIdByKey(this.model, 'image_edit');
          if (!taskId) {
            throw new Error(`未找到模型 ${this.model} 对应的任务配置`);
          }
          form.append('task_id', taskId);
          
          // Add user_id from localStorage
          const userId = localStorage.getItem('user_id');
          if (userId) {
            form.append('user_id', userId);
          }
          
          // Add auth_token if available
          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const res = await axios.post('/api/image-edit', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
          
          // Handle multiple project IDs
          this.projectIds = res.data.project_ids || [];
          this.projectId = this.projectIds.join(', ');
          this.status = res.data.status || 'submitted';
          
          // Start polling for status
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
          
          // Batch query all project IDs
          const projectIdsStr = this.projectIds.join(',');
          const res = await axios.get(`/api/get-status/${projectIdsStr}`, { params });
          
          // Handle batch response
          if (res.data.tasks) {
            // Multiple tasks response
            const tasks = res.data.tasks;
            const allSuccess = tasks.every(t => t.status === 'SUCCESS');
            const anyFailed = tasks.some(t => t.status === 'FAILED');
            const anyRunning = tasks.some(t => t.status === 'RUNNING');
            
            // Collect all successful results with their project_ids
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
              // All done but some failed
              const failedTasks = tasks.filter(t => t.status === 'FAILED');
              this.error = `${failedTasks.length} 个任务失败`;
              this.status = 'FAILED';
              this.loading = false;
              this.clearStatusCheck();
            } else {
              // Still running
              this.status = 'RUNNING';
            }
          }
        } catch (err) {
          console.error('Status check error:', err);
          // Continue checking, don't stop on temporary errors
        }
      },
      
      startStatusCheck() {
        this.statusInterval = setInterval(() => {
          this.checkStatus();
        }, 10000); // Check every 10 seconds
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
        const filename = `image_${dateStr}_${timeStr}_${index + 1}.png`;
        const downloadUrl = buildDownloadUrl(url, filename);
        
        // 微信浏览器中直接打开图片，用户可以长按保存
        if (this.isWechatBrowser()) {
          window.open(downloadUrl, '_blank');
          // 提示用户如何保存
          setTimeout(() => {
            alert('请长按图片，然后选择“保存图片”');
          }, 500);
        } else {
          // 非微信浏览器使用标准下载方式
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
          // 图片编辑界面只查询图片编辑类型
          const imageEditTypes = this.taskTypeConfig?.image_edit_types || [1, 7];
          const typesStr = imageEditTypes.join(',');

          const response = await axios.get('/api/ai-tools/history', {
            params: {
              user_id: parseInt(userId),
              page: this.historyPage,
              page_size: 20,
              types: typesStr,
              has_image_path: true,
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
      
      getRatioLabel(value) {
        const ratioMap = {
          '9:16': '竖屏 (9:16)',
          '16:9': '横屏 (16:9)',
          '1:1': '正方形 (1:1)',
          '3:4': '竖屏 (3:4)',
          '4:3': '横屏 (4:3)'
        };
        return ratioMap[value] || value || '未知';
      },
      
      async upscaleImage(projectId, index) {
        if (!projectId) return;
        
        this.upscalingImages[index] = true;
        this.error = '';
        
        try {
          const form = new FormData();
          form.append('project_id', projectId);
          form.append('user_id', localStorage.getItem('user_id') || '');
          form.append('auth_token', this.authToken);
          
          const res = await axios.post('/api/image-upscale', form);
          
          if (res.data.success) {
            this.upscaleProjectIds[index] = res.data.data.project_id;
            this.startUpscaleStatusCheck(index);
          } else {
            this.error = res.data.message || '高清放大失败';
            this.upscalingImages[index] = false;
          }
        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || err?.message || '高清放大请求失败';
          this.upscalingImages[index] = false;
        }
      },
      
      startUpscaleStatusCheck(index) {
        this.checkUpscaleStatus(index);
      },
      
      async checkUpscaleStatus(index) {
        const projectId = this.upscaleProjectIds[index];
        if (!projectId) return;
        
        try {
          const authToken = localStorage.getItem('auth_token');
          const params = authToken ? { auth_token: authToken } : {};
          const res = await axios.get(`/api/runninghub-status/${projectId}`, { params });
          
          // Add defensive check for null response
          if (!res || !res.data) {
            console.error('Invalid response from server:', res);
            const timer = setTimeout(() => this.checkUpscaleStatus(index), 3000);
            this.upscaleStatusIntervals[index] = timer;
            return;
          }
          
          if (res.data.status === 'SUCCESS') {
            const rawResults = res.data.results || [];
            if (rawResults.length > 0) {
              this.upscaleResults[index] = rawResults[0];
            }
            this.upscalingImages[index] = false;
            this.clearUpscaleStatusCheck(index);
          } else if (res.data.status === 'FAILED') {
            this.error = '高清放大失败';
            this.upscalingImages[index] = false;
            this.clearUpscaleStatusCheck(index);
          } else {
            // RUNNING or QUEUED status
            const timer = setTimeout(() => this.checkUpscaleStatus(index), 3000);
            this.upscaleStatusIntervals[index] = timer;
          }
        } catch (err) {
          console.error(err);
          this.error = '查询高清放大状态失败';
          this.upscalingImages[index] = false;
          this.clearUpscaleStatusCheck(index);
        }
      },
      
      clearUpscaleStatusCheck(index) {
        if (this.upscaleStatusIntervals[index]) {
          clearTimeout(this.upscaleStatusIntervals[index]);
          delete this.upscaleStatusIntervals[index];
        }
      },
      
      async upscaleHistoryImage(item) {
        if (!item.project_id) return;
        
        try {
          const form = new FormData();
          form.append('project_id', item.project_id);
          form.append('user_id', localStorage.getItem('user_id') || '');
          form.append('auth_token', this.authToken);
          
          const res = await axios.post('/api/image-upscale', form);
          
          if (res.data.success) {
            alert('高清放大任务已创建，请稍后在历史记录中查看结果');
            // Refresh history to show the new upscale task
            await this.fetchHistory();
          } else {
            alert(res.data.message || '高清放大失败');
          }
        } catch (err) {
          console.error(err);
          alert(err?.response?.data?.detail || err?.message || '高清放大请求失败');
        }
      }
    },
    
    beforeUnmount() {
      this.clearStatusCheck();
      // 清理所有高清放大状态轮询定时器
      if (this.upscaleStatusIntervals) {
        Object.keys(this.upscaleStatusIntervals).forEach(index => {
          this.clearUpscaleStatusCheck(Number(index));
        });
      }
    },
    template: `
      <div>
        <div class="form">
          <div class="field">
            <label class="label">{{ $t('upload_image_max') }}</label>
            <input class="input" type="file" accept="image/*" multiple @change="onFile" />
            <div v-if="files.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('selected_images') }} {{ files.length }}/5 {{ $t('upload_image_tips') }}</div>
                <button @click="clearAllFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(file, index) in files" :key="index" style="position: relative; display: inline-block; padding: 6px 12px; background: #0b1220; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;">
                  <span>{{ file.name }}</span>
                  <button @click="removeFile(index)" style="margin-left: 8px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
          </div>

          <div class="field">
            <label class="label">{{ $t('prompt') }}</label>
            <textarea class="textarea" v-model.trim="prompt" :placeholder="$t('edit_instruction')"></textarea>
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
            <select class="input" v-model="ratio">
              <option v-for="opt in ratioOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
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

          <div class="field" v-if="supportsRefAudioVideo">
            <label class="label">{{ $t('reference_audio') }}（{{ $t('optional') }}）</label>
            <input type="file" @change="onRefAudioFile" accept="audio/*" multiple class="input" :disabled="loading">
            <div class="muted" style="margin-top: 4px;">{{ $t('upload_image_tips') }}</div>
            <div v-if="refAudioFiles.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('selected_images') }} {{ refAudioFiles.length }} {{ $t('audio') }}:</div>
                <button @click="clearAllRefAudioFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(file, index) in refAudioFiles" :key="index" style="position: relative; display: inline-block; padding: 6px 12px; background: #0b1220; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;">
                  <span>{{ file.name }}</span>
                  <button @click="removeRefAudioFile(index)" style="margin-left: 8px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
          </div>

          <div class="field" v-if="supportsRefAudioVideo">
            <label class="label">{{ $t('video') }}（{{ $t('optional') }}）</label>
            <input type="file" @change="onRefVideoFile" accept="video/*" multiple class="input" :disabled="loading">
            <div class="muted" style="margin-top: 4px;">{{ $t('upload_video_tips') }}</div>
            <div v-if="refVideoFiles.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('selected_images') }} {{ refVideoFiles.length }} {{ $t('video') }}:</div>
                <button @click="clearAllRefVideoFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(file, index) in refVideoFiles" :key="index" style="position: relative; display: inline-block; padding: 6px 12px; background: #0b1220; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;">
                  <span>{{ file.name }}</span>
                  <button @click="removeRefVideoFile(index)" style="margin-left: 8px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
          </div>

          <div class="field">
            <div class="row">
              <button class="btn" :disabled="!canSubmit" @click="submit">{{ loading ? $t('uploading') : $t('submit_task') }}</button>
              <button class="btn secondary" @click="fetchHistory" :disabled="historyLoading">{{ historyLoading ? $t('loading') : $t('history') }}</button>
            </div>
          </div>
        </div>

        <div class="status" v-if="projectId">{{ $t('task_id') }}：{{ projectId }}</div>
        <div class="status" v-if="statusText">{{ statusText }}</div>
        <div class="status danger" v-if="error">{{ error }}</div>

        <div class="preview" v-if="results.length">
          <div class="imgbox" v-for="(result, i) in results" :key="i">
            <!-- Original Image -->
            <div style="margin-bottom: 8px; font-weight: bold; color: var(--primary); text-align: center;">{{ $t('original_image') }} #{{ i + 1 }}</div>
            <img :src="result.file_url" :alt="'result-'+i" />
            <div style="padding: 8px; text-align: center;">
              <button class="btn secondary" @click="downloadImage(result.file_url, i)">{{ $t('download_image') }}</button>
              <button class="btn" @click="upscaleImage(result.project_id, i)" :disabled="upscalingImages[i]" style="margin-left: 8px; display: none;">
                {{ upscalingImages[i] ? $t('upscaling') : $t('download_image_hd') }}
              </button>
              <div class="muted" style="margin-top: 4px; font-size: 11px;">{{ $t('cost_time') }}: {{ result.task_cost_time }}s</div>
            </div>

            <!-- Upscaled Image (shown below original) -->
            <div v-if="upscaleResults[i]" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); display: none;">
              <div style="margin-bottom: 8px; font-weight: bold; color: #10b981; text-align: center;">{{ $t('upscale_result') }}</div>
              <img :src="upscaleResults[i].file_url" :alt="'upscale-result-'+i" />
              <div style="padding: 8px; text-align: center;">
                <button class="btn secondary" @click="downloadImage(upscaleResults[i].file_url, i)">{{ $t('download_hd_image') }}</button>
                <div class="muted" style="margin-top: 4px; font-size: 11px;">{{ $t('cost_time') }}: {{ upscaleResults[i].task_cost_time }}s</div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- History Modal -->
        <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
          <div class="modal" style="max-width: 900px; max-height: 80vh; overflow-y: auto; overflow-x: hidden;" @scroll="handleHistoryScroll">
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
                  <span v-if="item.type == 1">{{ $t('type_label') }}: {{ $t('type_image_edit') }}</span>
                  <span v-else-if="item.type == 4">{{ $t('type_label') }}: {{ $t('type_upscale') }}</span>
                  <span>{{ $t('ratio') }}: {{ getRatioLabel(item.ratio) }}</span>
                  <span>{{ $t('create_time') }}: {{ item.create_time ? new Date(item.create_time).toLocaleString('zh-CN') : $t('unknown') }}</span>
                  <span v-if="item.model_name">{{ $t('model') }}: {{ item.model_name }}</span>
                  <span v-if="item.implementation_name">{{ $t('driver') }}: {{ item.implementation_name }}</span>
                </div>
                <div v-if="item.reference_images || item.image_path || item.audio_path || item.video_path" style="margin-top: 8px;">
                  <span style="font-size: 13px; color: var(--muted);">{{ $t('reference_materials') }}:</span>
                  <div style="display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; align-items: center;">
                    <template v-for="(img, idx) in parseReferenceImages(item)" :key="idx">
                      <img v-if="img" :src="img" style="width: 60px; height: 60px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); cursor: pointer;"
                           @click="window.open(img, '_blank')" />
                    </template>
                    <div v-if="item.audio_path" style="padding: 4px 10px; background: #1a2530; border: 1px solid #10b981; border-radius: 4px; font-size: 12px;">
                      <span style="color: #34d399;">{{ $t('audio') }}</span>
                      <a :href="item.audio_path" target="_blank" style="color: #60a5fa; margin-left: 4px; text-decoration: none;">{{ $t('view') }}</a>
                    </div>
                    <div v-if="item.video_path" style="padding: 4px 10px; background: #1a2530; border: 1px solid #f59e0b; border-radius: 4px; font-size: 12px;">
                      <span style="color: #fbbf24;">{{ $t('video') }}</span>
                      <a :href="item.video_path" target="_blank" style="color: #60a5fa; margin-left: 4px; text-decoration: none;">{{ $t('view') }}</a>
                    </div>
                  </div>
                </div>
                <div v-if="item.result_url" style="margin-top: 8px;">
                  <a :href="item.result_url" target="_blank" class="btn secondary" style="display: inline-block; text-decoration: none;">{{ $t('view_result') }}</a>
                  <button v-if="item.type == 1" class="btn" @click="upscaleHistoryImage(item)" style="margin-left: 8px; display: none;">{{ $t('download_image_hd') }}</button>
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

if (typeof window !== "undefined") window.ImageEdit = ImageEdit;
