  const ImageToVideo = {
    name: 'ImageToVideo',
    data() {
      return {
        files: [],
        prompt: '',
        videoModel: 'wan22',
        model: '9:16',
        durationSeconds: 5,
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
        enhancingVideos: {},  // Track enhancement status by index
        enhanceTaskIds: {},   // Track enhancement task IDs by index
        enhanceStatusTimers: {},  // Track enhancement polling timers by index
        taskComputingPower: {},  // 从接口获取的算力配置
        taskTypeConfig: null,  // 从接口获取的任务类型配置
        driverStatus: {},  // 驱动可用状态
        modelConfigs: {},  // 从后端获取的模型配置
        configLoaded: false,  // 配置是否已加载
        // 图片模式相关
        imageMode: 'first_last_frame',  // 图片模式: first_last_frame, multi_reference, first_last_with_ref
        referenceFiles: [],  // 参考图文件（仅 first_last_with_ref 模式使用）
        // 统一媒体管理（替代 audioFiles/videoFiles，files 保留用于图片）
        mediaItems: [],  // { id, displayName, type, fileUrl, thumbnailUrl, originalFile, uploading }
        mediaCounters: { image: 0, video: 0, audio: 0 },
        // @ 引用下拉框状态
        mentionDropdown: { visible: false, query: '', queryStart: -1, selectedIndex: 0 },
        // 媒体验证相关
        audioValidationError: '',  // 音频验证错误信息
        videoValidationError: '',  // 视频验证错误信息
        mediaValidating: false  // 正在验证媒体文件
      }
    },
    mounted() {
      // Get auth_token from localStorage (set by App component)
      this.authToken = localStorage.getItem('auth_token') || '';
      // 获取算力配置（包含驱动状态）
      this.fetchComputingPowerConfig();
      // 获取任务类型配置
      this.fetchTaskTypeConfig();
      // 获取模型配置
      this.fetchModelConfigs();
    },
    watch: {
      videoModel(newModel, oldModel) {
        // 切换模型时，更新默认值
        const config = this.modelConfigs[newModel];
        if (config) {
          // 更新比例
          if (config.default_ratio && config.ratios && !config.ratios.includes(this.model)) {
            this.model = config.default_ratio;
          }
          // 更新时长
          if (config.durations && !config.durations.includes(this.durationSeconds)) {
            this.durationSeconds = config.default_duration || config.durations[0] || 5;
          }
        }
        // 如果不支持尾帧且当前有2张图片，移除尾帧
        const supportsLastFrame = config?.supports_last_frame !== false;
        if (!supportsLastFrame && this.imageMediaItems.length > 1) {
          // 只保留第一张图片
          const firstImageId = this.imageMediaItems[0].id;
          this.mediaItems = this.mediaItems.filter(m => m.type !== 'image' || m.id === firstImageId);
          this.mediaItems = [...this.mediaItems];
        }
      },
      imageMode(newMode, oldMode) {
        // 切换图片模式时，检查当前模型是否支持新模式
        const config = this.modelConfigs[this.videoModel];
        const supportedModes = config?.supported_image_modes || ['first_last_frame'];
        if (!supportedModes.includes(newMode)) {
          // 当前模型不支持新模式，切换到支持该模式的第一个模型
          const allOptions = TaskConfig.getModelOptionsForCategory('image_to_video');
          for (const opt of allOptions) {
            const optConfig = this.modelConfigs[opt.value];
            const optModes = optConfig?.supported_image_modes || ['first_last_frame'];
            const isAvailable = !this.driverStatus || !this.driverStatus[opt.taskType] || this.driverStatus[opt.taskType].available !== false;
            if (optModes.includes(newMode) && isAvailable) {
              this.videoModel = opt.value;
              break;
            }
          }
        }
        // 模式切换时清空文件
        this.mediaItems = [];
        this.mediaCounters = { image: 0, video: 0, audio: 0 };
        this.referenceFiles = [];
      }
    },
    computed: {
      imageMediaItems() { return this.mediaItems.filter(m => m.type === 'image'); },
      audioMediaItems() { return this.mediaItems.filter(m => m.type === 'audio'); },
      videoMediaItems() { return this.mediaItems.filter(m => m.type === 'video'); },
      // 向后兼容：files 用于图片数量检查和 submit
      audioFiles() { return this.audioMediaItems; },
      videoFiles() { return this.videoMediaItems; },
      // @ 引用可选项
      mentionableItems() {
        return this.mediaItems.filter(m => m.fileUrl && !m.uploading).map(m => ({
          id: m.id,
          displayName: m.displayName,
          type: m.type,
          thumbnailUrl: m.thumbnailUrl
        }));
      },
      filteredMentionItems() {
        if (!this.mentionDropdown.query) return this.mentionableItems;
        const q = this.mentionDropdown.query.toLowerCase();
        return this.mentionableItems.filter(item =>
          item.displayName.toLowerCase().includes(q) ||
          (item.type === 'image' ? '图片' : item.type === 'video' ? '视频' : '音频').includes(q)
        );
      },
      supportsLastFrame() {
        const config = this.modelConfigs[this.videoModel];
        return config?.supports_last_frame !== false;
      },
      supportsRefAudioVideo() {
        // 确保配置已加载，且当前模型支持，且处于多参考图模式
        if (!this.configLoaded) return false;
        // 参考音频/视频仅在多参考图模式下有意义，首尾帧模式下不显示
        if (this.imageMode !== 'multi_reference') return false;
        const config = this.modelConfigs[this.videoModel];
        return config?.supports_ref_audio_video === true;
      },
      canSubmit() {
        // 如果有媒体验证错误，不允许提交
        if (this.audioValidationError || this.videoValidationError) {
          return false;
        }
        // 如果有媒体正在上传或验证中，不允许提交
        if (this.mediaItems.some(m => m.uploading || m.validating)) {
          return false;
        }

        // 根据模式验证图片数量
        const imgCount = this.imageMediaItems.length;
        if (this.imageMode === 'first_last_frame') {
          const maxFiles = this.supportsLastFrame ? 2 : 1;
          return imgCount >= 1 && imgCount <= maxFiles && !!this.prompt.trim() && !this.loading;
        } else if (this.imageMode === 'multi_reference') {
          return imgCount >= 1 && imgCount <= this.maxFilesForMode && !!this.prompt.trim() && !this.loading;
        } else if (this.imageMode === 'first_last_with_ref') {
          return imgCount >= 1 && imgCount <= 2 && this.referenceFiles.length <= 3 && !!this.prompt.trim() && !this.loading;
        }
        return false;
      },
      imageModeOptions() {
        // 显示图片模式供用户选择
        return [
          { value: 'first_last_frame', label: this.$t('first_last_frame_mode') || '首尾帧模式', desc: this.$t('first_last_frame_desc') || '第一张为首帧，第二张为尾帧（可选）' },
          { value: 'multi_reference', label: this.$t('multi_reference_mode') || '多参考图模式', desc: this.$t('multi_reference_desc') || '所有图片作为风格参考' }
          // { value: 'first_last_with_ref', label: '首尾帧+参考图', desc: '首尾帧控制动作，参考图控制风格' }  // 暂无模型支持
        ];
      },
      maxFilesForMode() {
        if (this.imageMode === 'first_last_frame') return this.supportsLastFrame ? 2 : 1;
        if (this.imageMode === 'multi_reference') {
          const config = this.modelConfigs[this.videoModel];
          return config?.max_multi_ref_images || 5;
        }
        if (this.imageMode === 'first_last_with_ref') return 2;
        return 5;
      },
      filesLabel() {
        if (this.imageMode === 'first_last_frame') return this.supportsLastFrame ? (this.$t('first_last_frame_mode') || '上传首尾帧图片 (1-2张)') : (this.$t('upload_image') || '上传首帧图片 (1张)');
        if (this.imageMode === 'multi_reference') return `${this.$t('reference_images_label') || '上传参考图片'} (1-${this.maxFilesForMode}${this.$t('images') || '张'})`;
        if (this.imageMode === 'first_last_with_ref') return this.$t('upload_image_to_video') || '上传首尾帧图片 (1-2张)';
        return this.$t('upload_image') || '上传图片';
      },
      filesHint() {
        if (this.imageMode === 'first_last_frame') return this.supportsLastFrame ? (this.$t('first_last_frame_desc') || '第一张为首帧，第二张（可选）为尾帧') : (this.$t('files_hint') || '该模型仅支持首帧图');
        if (this.imageMode === 'multi_reference') return this.$t('multi_reference_desc') || '多张图片将作为风格参考';
        if (this.imageMode === 'first_last_with_ref') return this.$t('first_last_frame_desc') || '第一张为首帧，第二张（可选）为尾帧';
        return '';
      },
      statusText() {
        if (this.status === 'completed') return '生成完成！';
        if (this.loading) return '正在生成视频，请稍候...';
        return '';
      },
      videoModelOptions() {
        // 依赖 configLoaded 触发重新计算
        if (!this.configLoaded) return [];
        // 动态从配置获取图生视频模型列表
        const allOptions = TaskConfig.getModelOptionsForCategory('image_to_video');
        // 根据当前选中的图片模式过滤支持该模式的模型
        return allOptions.map(opt => {
          const config = this.modelConfigs[opt.value];
          const supportedModes = config?.supported_image_modes || ['first_last_frame'];
          const supportsCurrentMode = supportedModes.includes(this.imageMode);
          const isAvailable = !this.driverStatus || !this.driverStatus[opt.taskType] || this.driverStatus[opt.taskType].available !== false;
          return {
            value: opt.value,
            label: isAvailable ? opt.label : opt.label + ' (未配置)',
            disabled: !isAvailable || !supportsCurrentMode,
            supportsMode: supportsCurrentMode
          };
        });
      },
      modelOptions() {
        const config = this.modelConfigs[this.videoModel];
        if (!config || !config.ratios) {
          return [
            { value: '9:16', label: this.$t('vertical_screen') || '竖屏' },
            { value: '16:9', label: this.$t('horizontal_screen') || '横屏' }
          ];
        }
        const labelMap = {
          '9:16': this.$t('vertical_screen') || '竖屏',
          '16:9': this.$t('horizontal_screen') || '横屏',
          '1:1': this.$t('square') || '正方形'
        };
        return config.ratios.map(ratio => ({
          value: ratio,
          label: labelMap[ratio] || ratio
        }));
      },
      durationOptions() {
        const config = this.modelConfigs[this.videoModel];
        if (!config || !config.durations) {
          return [
            { value: 5, label: this.$t('duration_seconds', { dur: 5 }) || '5秒' },
            { value: 10, label: this.$t('duration_seconds', { dur: 10 }) || '10秒' }
          ];
        }
        // LTX2 特殊标签
        const ltx2Labels = {
          5: `${this.$t('duration_seconds', { dur: 5 }) || '5秒'} (121${this.$t('images') || '帧'})`,
          8: `${this.$t('duration_seconds', { dur: 8 }) || '8秒'} (201${this.$t('images') || '帧'})`,
          10: `${this.$t('duration_seconds', { dur: 10 }) || '10秒'} (241${this.$t('images') || '帧'})`
        };
        return config.durations.map(duration => ({
          value: duration,
          label: this.videoModel === 'ltx2' ? (ltx2Labels[duration] || this.$t('duration_seconds', { dur: duration }) || `${duration}秒`) : (this.$t('duration_seconds', { dur: duration }) || `${duration}秒`)
        }));
      },
      countOptions() {
        return [
          { value: 1, label: `1${this.$t('items') || '个'}` },
          { value: 2, label: `2${this.$t('items') || '个'}` },
          { value: 3, label: `3${this.$t('items') || '个'}` },
          { value: 4, label: `4${this.$t('items') || '个'}` }
        ];
      },
      computingPower() {
        // 使用 TaskConfig API 动态获取算力（自动适配新增模型）
        if (!this.configLoaded) {
          return 0;  // 配置未加载时返回0
        }

        // 根据 image_mode 和图片数量构建 context，用于算力修饰符计算
        const context = {};
        if (this.imageMode) {
          // 首尾帧模式且有2张图时，使用 first_last_with_tail
          if (this.imageMode === 'first_last_frame' && this.imageMediaItems.length > 1) {
            context['image_mode'] = 'first_last_with_tail';
          } else {
            context['image_mode'] = this.imageMode;
          }
        }

        // 使用 TaskConfig.getComputingPower 动态获取算力
        // 该方法会自动处理固定算力和按时长计费两种情况，以及应用修饰符
        return TaskConfig.getComputingPower(this.videoModel, this.durationSeconds, context);
      },
      totalComputingPower() {
        // 总算力 = 单个算力 × 生成数量
        return this.computingPower * this.count;
      }
    },
    methods: {
      parseReferenceImages(ref) {
        if (!ref) return [];
        if (Array.isArray(ref)) return ref;
        try { return JSON.parse(ref); } catch(e) { return []; }
      },
      async fetchComputingPowerConfig() {
        try {
          const response = await axios.get('/api/computing-power-config');
          if (response.data.success) {
            this.taskComputingPower = response.data.data.task_computing_power;
            // 保存驱动状态
            if (response.data.data.driver_status) {
              this.driverStatus = response.data.data.driver_status;
            }
          } else {
            console.error('获取算力配置失败:', response.data.message);
          }
        } catch (error) {
          console.error('获取算力配置异常:', error);
        }
      },
      
      async fetchTaskTypeConfig() {
        try {
          await TaskConfig.load();
          this.taskTypeConfig = TaskConfig.getTaskTypeConfig();
        } catch (error) {
          console.error('获取任务类型配置异常:', error);
        }
      },

      async fetchModelConfigs() {
        try {
          await TaskConfig.load();
          this.modelConfigs = TaskConfig.getModelConfigs();
          this.configLoaded = true;  // 标记配置已加载
          // 设置初始默认值
          const config = this.modelConfigs[this.videoModel];
          if (config) {
            if (config.default_ratio) this.model = config.default_ratio;
            if (config.default_duration) this.durationSeconds = config.default_duration;
          }
        } catch (err) {
          console.error('获取模型配置失败:', err);
        }
      },
      
      getDurationText(item) {
        const duration = item?.original_duration ?? item?.duration ?? item?.video_duration ?? (typeof this.durationSeconds === 'number' ? this.durationSeconds : null);
        return duration ? `${duration}秒` : '未知';
      },

      async enhanceVideo(item, index) {
      if ((!item.file_url && !item.result_url) || this.enhancingVideos[index]) return;

       const userId = localStorage.getItem('user_id');
      if (!userId) {
        alert('请先登录');
        return;
      }

      try {
        this.$set ? this.$set(this.enhancingVideos, index, true) : (this.enhancingVideos[index] = true);

        const form = new FormData();
        form.append('video_url', item.file_url || item.result_url);
        form.append('user_id', userId);
        form.append('enhance_type', '6'); // 高清放大任务类型为6

        const authToken = localStorage.getItem('auth_token');
        if (authToken) {
          form.append('auth_token', authToken);
        }

        const res = await axios.post('/api/video-enhance', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });

        if (res.data.status === 'submitted' && res.data.project_id) {
          this.enhanceTaskIds = { ...this.enhanceTaskIds, [index]: res.data.project_id };
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
      if (!taskId) return;
      
      try {
        const authToken = localStorage.getItem('auth_token');
        const params = authToken ? { auth_token: authToken } : {};
        const res = await axios.get(`/api/runninghub-status/${taskId}`, { params });
        
        if (res.data.status === 'SUCCESS') {
          if (res.data.results && res.data.results.length > 0) {
            this.$set ? this.$set(item, 'enhancedVideo', res.data.results[0]) : (item.enhancedVideo = res.data.results[0]);
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

      onFile(e){
        const selectedFiles = Array.from(e.target.files || []);
        const maxFiles = this.maxFilesForMode;
        const remainingSlots = maxFiles - this.imageMediaItems.length;

        if (remainingSlots <= 0) {
          alert(`已达到最大数量${maxFiles}张图片，请先删除一些图片`);
          e.target.value = '';
          return;
        }

        const filesToAdd = selectedFiles.slice(0, remainingSlots);
        if (selectedFiles.length > remainingSlots) {
          alert(`最多还能添加${remainingSlots}张图片，已自动截取前${remainingSlots}张`);
        }

        // 即时上传每张图片
        filesToAdd.forEach(file => {
          this.uploadAndAddMedia(file, 'image');
        });

        e.target.value = '';
      },
      
      onReferenceFile(e) {
        const selectedFiles = Array.from(e.target.files || []);
        const maxRefFiles = 3;
        const remainingSlots = maxRefFiles - this.referenceFiles.length;
        
        if (remainingSlots <= 0) {
          alert('参考图最多3张，请先删除一些图片');
          e.target.value = '';
          return;
        }
        
        if (selectedFiles.length > remainingSlots) {
          alert(`最多还能添加${remainingSlots}张参考图，已自动截取前${remainingSlots}张`);
          this.referenceFiles = [...this.referenceFiles, ...selectedFiles.slice(0, remainingSlots)];
        } else {
          this.referenceFiles = [...this.referenceFiles, ...selectedFiles];
        }

        e.target.value = '';
      },

      removeFile(index) {
        const item = this.imageMediaItems[index];
        if (item) this.removeMediaItem(item.id);
      },

      removeReferenceFile(index) {
        this.referenceFiles.splice(index, 1);
      },
      
      clearAllReferenceFiles() {
        this.referenceFiles = [];
      },

      onAudioFile(e) {
        const selectedFiles = Array.from(e.target.files || []);
        selectedFiles.forEach(file => {
          this.uploadAndAddMedia(file, 'audio');
        });
        e.target.value = '';
      },

      onVideoFile(e) {
        const selectedFiles = Array.from(e.target.files || []);
        selectedFiles.forEach(file => {
          this.uploadAndAddMedia(file, 'video');
        });
        e.target.value = '';
      },

      async uploadAndAddMedia(file, type) {
        const typeLabel = type === 'image' ? '图片' : type === 'video' ? '视频' : '音频';
        const existingCount = this.mediaItems.filter(m => m.type === type).length;
        const displayName = `${typeLabel}${existingCount + 1}`;
        const id = `${type[0]}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;

        const mediaItem = {
          id,
          displayName,
          type,
          fileUrl: null,
          thumbnailUrl: null,
          originalFile: file,
          uploading: true
        };
        this.mediaItems.push(mediaItem);

        // 音频/视频添加后验证
        if (type !== 'image') {
          // 上传完成后再验证
        }

        try {
          const form = new FormData();
          form.append('file', file);
          form.append('media_type', type);

          const headers = { 'Content-Type': 'multipart/form-data' };
          const userId = localStorage.getItem('user_id');
          if (userId) headers['X-User-Id'] = userId;
          if (this.authToken) headers['Authorization'] = this.authToken;

          const res = await axios.post('/api/image-to-video/upload-media', form, { headers });

          if (res.data.code === 0) {
            const idx = this.mediaItems.findIndex(m => m.id === id);
            if (idx >= 0) {
              this.mediaItems[idx].fileUrl = res.data.data.file_url;
              this.mediaItems[idx].thumbnailUrl = res.data.data.thumbnail_url;
              this.mediaItems[idx].uploading = false;
              // 只有音频/视频需要验证时长
              this.mediaItems[idx].validating = type !== 'image';
              // 触发 Vue 响应性
              this.mediaItems = [...this.mediaItems];
            }
            // 上传完成后，如果是音频/视频，验证时长
            if (type !== 'image') {
              const valid = await this.validateMediaDuration();
              // 验证不通过，移除刚上传的文件
              const currentIdx = this.mediaItems.findIndex(m => m.id === id);
              if (currentIdx >= 0) {
                if (valid) {
                  this.mediaItems[currentIdx].validating = false;
                  this.mediaItems = [...this.mediaItems];
                } else {
                  // 验证失败，从列表中删除该文件
                  this.mediaItems.splice(currentIdx, 1);
                  this.mediaItems = [...this.mediaItems];
                }
              }
            }
          } else {
            throw new Error(res.data.message || '上传失败');
          }
        } catch (err) {
          console.error('媒体上传失败:', err);
          const idx = this.mediaItems.findIndex(m => m.id === id);
          if (idx >= 0) this.mediaItems.splice(idx, 1);
          alert(`${displayName} 上传失败: ${err?.response?.data?.detail || err.message}`);
        }
      },

      removeMediaItem(itemId) {
        const idx = this.mediaItems.findIndex(m => m.id === itemId);
        if (idx >= 0) {
          const item = this.mediaItems[idx];
          this.mediaItems.splice(idx, 1);
          this.mediaItems = [...this.mediaItems];
          if (item.type === 'audio' || item.type === 'video') {
            this.validateMediaDuration();
          }
        }
      },

      removeAudioFile(index) {
        const item = this.audioMediaItems[index];
        if (item) this.removeMediaItem(item.id);
      },

      removeVideoFile(index) {
        const item = this.videoMediaItems[index];
        if (item) this.removeMediaItem(item.id);
      },

      clearAllAudioFiles() {
        this.mediaItems = this.mediaItems.filter(m => m.type !== 'audio');
        this.mediaItems = [...this.mediaItems];
        this.validateMediaDuration();
      },

      clearAllVideoFiles() {
        this.mediaItems = this.mediaItems.filter(m => m.type !== 'video');
        this.mediaItems = [...this.mediaItems];
        this.validateMediaDuration();
      },

      clearAllFiles() {
        this.mediaItems = this.mediaItems.filter(m => m.type !== 'image');
        this.mediaItems = [...this.mediaItems];
      },

      onImageModeChange() {
        this.mediaItems = [];
        this.mediaCounters = { image: 0, video: 0, audio: 0 };
        this.referenceFiles = [];
      },

      // @ 引用相关方法
      onPromptInput(e) {
        const textarea = e.target;
        const cursorPos = textarea.selectionStart;
        const text = this.prompt;
        const textBeforeCursor = text.substring(0, cursorPos);
        const atMatch = textBeforeCursor.match(/@([^@\s]*)$/);

        if (atMatch) {
          this.mentionDropdown.visible = true;
          this.mentionDropdown.query = atMatch[1];
          this.mentionDropdown.queryStart = cursorPos - atMatch[0].length;
          this.mentionDropdown.selectedIndex = 0;
        } else {
          this.mentionDropdown.visible = false;
        }
      },

      onPromptKeydown(e) {
        if (!this.mentionDropdown.visible) return;

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          const max = this.filteredMentionItems.length - 1;
          this.mentionDropdown.selectedIndex = Math.min(this.mentionDropdown.selectedIndex + 1, max);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          this.mentionDropdown.selectedIndex = Math.max(this.mentionDropdown.selectedIndex - 1, 0);
        } else if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          if (this.filteredMentionItems.length > 0) {
            this.insertMention(this.filteredMentionItems[this.mentionDropdown.selectedIndex]);
          }
        } else if (e.key === 'Escape') {
          e.preventDefault();
          this.mentionDropdown.visible = false;
        }
      },

      onPromptBlur() {
        setTimeout(() => { this.mentionDropdown.visible = false; }, 200);
      },

      insertMention(item) {
        const textarea = this.$refs.promptTextarea;
        const start = this.mentionDropdown.queryStart;
        const end = start + 1 + this.mentionDropdown.query.length;
        const before = this.prompt.substring(0, start);
        const after = this.prompt.substring(end);
        const insertText = `@${item.displayName}`;

        this.prompt = before + insertText + ' ' + after;
        this.mentionDropdown.visible = false;

        this.$nextTick(() => {
          const newCursorPos = start + insertText.length + 1;
          textarea.setSelectionRange(newCursorPos, newCursorPos);
          textarea.focus();
        });
      },

      async validateMediaDuration() {
        // 如果没有音频或视频文件，清除错误
        if (this.audioMediaItems.length === 0 && this.videoMediaItems.length === 0) {
          this.audioValidationError = '';
          this.videoValidationError = '';
          return true;
        }

        // 检查是否都上传完成
        const allUploaded = [...this.audioMediaItems, ...this.videoMediaItems].every(m => m.fileUrl);
        if (!allUploaded) {
          // 不设置错误，等待上传完成
          return false;
        }

        this.mediaValidating = true;
        try {
          const form = new FormData();

          // 优先使用 URL，回退到文件
          const audioUrls = this.audioMediaItems.map(m => m.fileUrl).filter(Boolean);
          const videoUrls = this.videoMediaItems.map(m => m.fileUrl).filter(Boolean);

          if (audioUrls.length > 0) {
            form.append('audio_urls', audioUrls.join(','));
          } else {
            this.audioMediaItems.forEach(m => {
              if (m.originalFile) form.append('audio_files', m.originalFile);
            });
          }

          if (videoUrls.length > 0) {
            form.append('video_urls', videoUrls.join(','));
          } else {
            this.videoMediaItems.forEach(m => {
              if (m.originalFile) form.append('video_files', m.originalFile);
            });
          }

          form.append('max_duration_seconds', 15);

          const res = await axios.post('/api/media/validate-duration', form, {
            headers: { 'Content-Type': 'multipart/form-data' }
          });

          const data = res.data.data;
          if (data.valid) {
            this.audioValidationError = '';
            this.videoValidationError = '';
            return true;
          } else {
            // 根据后端返回的数据，分别设置音频和视频的错误
            this.audioValidationError = data.audio_duration > data.max_duration
              ? `音频总时长 ${data.audio_duration}秒，超过限制 ${data.max_duration}秒`
              : '';
            this.videoValidationError = data.video_duration > data.max_duration
              ? `视频总时长 ${data.video_duration}秒，超过限制 ${data.max_duration}秒`
              : '';
            return false;
          }
        } catch (err) {
          console.error('媒体验证失败:', err);
          const errMsg = err?.response?.data?.detail || '媒体验证失败';
          // 无法区分时，两个都设上
          this.audioValidationError = this.audioMediaItems.length > 0 ? errMsg : '';
          this.videoValidationError = this.videoMediaItems.length > 0 ? errMsg : '';
          return false;
        } finally {
          this.mediaValidating = false;
        }
      },

      handleSubmit() {
        if (this.loading) {
          alert('正在生成中，请稍候...');
          return;
        }
        if (this.mediaItems.some(m => m.uploading)) {
          alert('媒体文件正在上传中，请等待上传完成');
          return;
        }
        if (this.mediaItems.some(m => m.validating)) {
          alert('媒体文件正在验证中，请稍候');
          return;
        }
        if (this.audioValidationError || this.videoValidationError) {
          alert(this.audioValidationError || this.videoValidationError);
          return;
        }
        if (this.imageMediaItems.length === 0) {
          alert('请先上传至少一张图片');
          return;
        }
        if (!this.prompt.trim()) {
          alert('请输入视频提示词');
          return;
        }
        this.submit();
      },

      async submit(){
        if(!this.canSubmit) return;

        // 在提交前，如果有音频或视频文件，再次进行验证
        if (this.audioMediaItems.length > 0 || this.videoMediaItems.length > 0) {
          const isValid = await this.validateMediaDuration();
          if (!isValid) {
            return;
          }
        }

        this.loading = true;
        this.error='';
        this.results=[];
        this.projectIds=[];
        this.projectId='';
        this.status='';

        try {
          const form = new FormData();

          // 优先使用已上传的图片URL
          const imageUrls = this.imageMediaItems.map(m => m.fileUrl).filter(Boolean);
          if (imageUrls.length > 0) {
            form.append('image_urls', imageUrls.join(','));
          } else {
            // 回退：发送原始文件
            this.imageMediaItems.forEach(m => {
              if (m.originalFile) form.append('images', m.originalFile);
            });
          }

          // 添加参考图（仅 first_last_with_ref 模式）
          if (this.imageMode === 'first_last_with_ref' && this.referenceFiles.length > 0) {
            this.referenceFiles.forEach(file => {
              form.append('reference_images', file);
            });
          }

          // 添加参考音频和视频（仅当模型支持且已选择时）
          if (this.supportsRefAudioVideo) {
            // 优先使用URL
            const audioUrls = this.audioMediaItems.map(m => m.fileUrl).filter(Boolean);
            if (audioUrls.length > 0) {
              form.append('audio_urls', audioUrls.join(','));
            }
            const videoUrls = this.videoMediaItems.map(m => m.fileUrl).filter(Boolean);
            if (videoUrls.length > 0) {
              form.append('video_urls', videoUrls.join(','));
            }
          }

          form.append('prompt', this.prompt);
          form.append('ratio', this.model);
          form.append('duration_seconds', this.durationSeconds);
          form.append('count', this.count);
          form.append('image_mode', this.imageMode);

          // 发送媒体引用映射（用于 @ 引用解析）
          const mediaReferences = this.mediaItems.filter(m => m.fileUrl).map(m => ({
            displayName: m.displayName,
            fileUrl: m.fileUrl,
            type: m.type
          }));
          if (mediaReferences.length > 0) {
            form.append('media_references', JSON.stringify(mediaReferences));
          }

          // 根据 videoModel 获取 task_id
          const taskId = TaskConfig.getTaskIdByKey(this.videoModel, 'image_to_video');
          if (!taskId) {
            throw new Error(`未找到视频模型 ${this.videoModel} 对应的任务配置`);
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

          const res = await axios.post('/api/ai-app-run-image', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
          
          // Handle multiple project IDs
          this.projectIds = res.data.project_ids || [];
          this.projectId = this.projectIds.join(', ');
          this.status = res.data.status || '';
          
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
              // Still running, check again after 10 seconds
              this.statusInterval = setTimeout(() => this.checkStatus(), 10000);
            }
          }
        } catch (err) {
          console.error(err);
          this.error = '查询状态失败';
          this.loading = false;
          this.clearStatusCheck();
        }
      },
      
      clearStatusCheck() {
        if (this.statusInterval) {
          clearTimeout(this.statusInterval);
          this.statusInterval = null;
        }
      },
      
      downloadVideo(url, index, isEnhanced = false) {
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
        const prefix = isEnhanced ? 'image_to_video_enhanced' : 'image_to_video';
        const filename = `${prefix}_${dateStr}_${timeStr}_${index + 1}.mp4`;
        const downloadUrl = buildDownloadUrl(url, filename);
  
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = filename;
        link.target = '_blank';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
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
          
          // 使用后端返回的图生视频类型列表，如果没有则使用默认值
          const imageToVideoTypes = this.taskTypeConfig?.image_to_video_types || [3, 10, 11, 12, 14, 15, 19, 20];
          const typesStr = imageToVideoTypes.join(',');
          
          const response = await axios.get('/api/ai-tools/history', {
            params: {
              user_id: parseInt(userId),
              page: this.historyPage,
              page_size: 20,
              types: typesStr,  // 使用后端配置的所有图生视频类型
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
      
      getHistoryTypeText(type) {
        // 使用后端返回的任务类型名称映射
        return this.taskTypeConfig?.task_type_name_map?.[type] || '未知类型';
      },

      getModelLabel(item) {
        const modelMap = {
          '9:16': '竖屏',
          '16:9': '横屏'
        };
        const resolved = item.ratio || this.model;
        return modelMap[resolved] || resolved || '未知';
      },

      getGenerationMode(item) {
        return getGenerationModeLabel(item);
      },
      
      goToCharacterCard(projectId) {
        window.location.href = '/character_card.html?task_id=' + projectId;
      },
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
          <!-- 图片模式选择 -->
          <div class="field">
            <label class="label">{{ $t('image_mode_label') || '图片模式' }}</label>
            <select class="input" v-model="imageMode" @change="onImageModeChange">
              <option v-for="opt in imageModeOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <div class="muted" style="margin-top:6px; color: var(--muted);">
              {{ imageModeOptions.find(o => o.value === imageMode)?.desc || '' }}
            </div>
          </div>

          <!-- 首尾帧/主图片上传 -->
          <div class="field">
            <label class="label">{{ filesLabel }}</label>
            <input class="input" type="file" accept="image/*" multiple @change="onFile" />
            <div class="muted" v-if="videoModel === 'sora2'" style="margin-top:6px; color: #fca5a5;">⚠️ {{ $t('sora2_warning_images') || '注意：请勿上传真人图片' }}</div>
            <div class="muted" style="margin-top:6px; color: var(--muted);">{{ filesHint }}</div>
            <div v-if="imageMediaItems.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('selected_count') || '已选择' }} {{ imageMediaItems.length }}/{{ maxFilesForMode }} {{ $t('images') || '张图片' }}:</div>
                <button @click="clearAllFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') || '清空全部' }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(item, index) in imageMediaItems" :key="item.id" style="position: relative; display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; background: #0b1220; border: 1px solid var(--border); border-radius: 8px; font-size: 12px;">
                  <div v-if="item.uploading" style="width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: #1a2530; border-radius: 4px;">
                    <span style="color: var(--muted); font-size: 14px;">...</span>
                  </div>
                  <img v-else-if="item.thumbnailUrl" :src="item.thumbnailUrl" style="width: 32px; height: 32px; border-radius: 4px; object-fit: cover;" />
                  <div v-else style="width: 32px; height: 32px; background: #1a2530; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 14px;">🖼</div>
                  <span>{{ imageMode === 'first_last_frame' ? (index === 0 ? '首帧: ' : (index === 1 ? '尾帧: ' : '')) : '' }}{{ item.displayName }}</span>
                  <button @click="removeFile(index)" style="margin-left: 4px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 参考音频上传 -->
          <div class="field" v-if="supportsRefAudioVideo">
            <label class="label">{{ $t('reference_audio_label') || '参考音频（可选）' }}</label>
            <input type="file" @change="onAudioFile" accept="audio/*" multiple class="input" :disabled="loading">
            <div class="muted" style="margin-top: 4px;">{{ $t('reference_audio_multiple') || '可上传多个参考音频文件' }}</div>
            <div v-if="audioMediaItems.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('audio_count') || '已选择' }} {{ audioMediaItems.length }} {{ $t('audio_items') || '个音频' }}:</div>
                <button @click="clearAllAudioFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') || '清空全部' }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(item, index) in audioMediaItems" :key="item.id" :style="{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 10px', background: '#0b1220', border: '1px solid var(--border)', borderRadius: '8px', fontSize: '12px', opacity: item.validating ? 0.6 : 1 }">
                  <div v-if="item.uploading" style="width: 32px; height: 32px; background: #1a2530; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 14px;">...</div>
                  <div v-else style="width: 32px; height: 32px; background: #1a2530; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 14px;">🎵</div>
                  <span>{{ item.displayName }}{{ item.validating ? ' (验证中...)' : '' }}</span>
                  <button @click="removeAudioFile(index)" style="margin-left: 4px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
            <div v-if="audioValidationError" style="margin-top: 8px; padding: 8px 12px; background: #7f1d1d; border: 1px solid #dc2626; border-radius: 6px; color: #fca5a5; font-size: 13px;">
              ⚠️ {{ audioValidationError }}
            </div>
          </div>

          <!-- 参考视频上传 -->
          <div class="field" v-if="supportsRefAudioVideo">
            <label class="label">{{ $t('reference_video_label') || '参考视频（可选）' }}</label>
            <input type="file" @change="onVideoFile" accept="video/*" multiple class="input" :disabled="loading">
            <div class="muted" style="margin-top: 4px;">{{ $t('reference_video_multiple') || '可上传多个参考视频文件' }}</div>
            <div v-if="videoMediaItems.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('video_count') || '已选择' }} {{ videoMediaItems.length }} {{ $t('video_items') || '个视频' }}:</div>
                <button @click="clearAllVideoFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') || '清空全部' }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(item, index) in videoMediaItems" :key="item.id" :style="{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 10px', background: '#0b1220', border: '1px solid var(--border)', borderRadius: '8px', fontSize: '12px', opacity: item.validating ? 0.6 : 1 }">
                  <div v-if="item.uploading" style="width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: #1a2530; border-radius: 4px;">
                    <span style="color: var(--muted); font-size: 14px;">...</span>
                  </div>
                  <img v-else-if="item.thumbnailUrl" :src="item.thumbnailUrl" style="width: 32px; height: 32px; border-radius: 4px; object-fit: cover;" />
                  <div v-else style="width: 32px; height: 32px; background: #1a2530; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 14px;">🎬</div>
                  <span>{{ item.displayName }}{{ item.validating ? ' (验证中...)' : '' }}</span>
                  <button @click="removeVideoFile(index)" style="margin-left: 4px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
            <div v-if="videoValidationError" style="margin-top: 8px; padding: 8px 12px; background: #7f1d1d; border: 1px solid #dc2626; border-radius: 6px; color: #fca5a5; font-size: 13px;">
              ⚠️ {{ videoValidationError }}
            </div>
          </div>

          <!-- 参考图上传（仅 first_last_with_ref 模式显示） -->
          <div class="field" v-if="imageMode === 'first_last_with_ref'">
            <label class="label">{{ $t('reference_images_label') || '上传参考图 (0-3张，用于风格参考)' }}</label>
            <input class="input" type="file" accept="image/*" multiple @change="onReferenceFile" />
            <div class="muted" style="margin-top:6px; color: var(--muted);">{{ $t('reference_images_desc') || '参考图用于控制视频风格，可选' }}</div>
            <div v-if="referenceFiles.length > 0" style="margin-top: 10px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 13px; color: var(--muted);">{{ $t('reference_images_count') || '已选择' }} {{ referenceFiles.length }}{{ $t('reference_images_max') || '/3' }} {{ $t('reference_images_display') || '张参考图' }}:</div>
                <button @click="clearAllReferenceFiles" class="btn secondary" style="font-size: 12px; padding: 4px 10px;">{{ $t('clear_all') || '清空全部' }}</button>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <div v-for="(file, index) in referenceFiles" :key="'ref-'+index" style="position: relative; display: inline-block; padding: 6px 12px; background: #1a2530; border: 1px solid #3b82f6; border-radius: 6px; font-size: 12px;">
                  <span style="color: #60a5fa;">参考{{ index + 1 }}: {{ file.name }}</span>
                  <button @click="removeReferenceFile(index)" style="margin-left: 8px; background: transparent; border: none; color: #ef4444; cursor: pointer; font-weight: bold;">×</button>
                </div>
              </div>
            </div>
          </div>

          <div class="field" style="position: relative;">
            <label class="label">{{ $t('video_prompt_label') || '视频提示词' }}</label>
            <div style="position: relative;">
              <textarea ref="promptTextarea" class="textarea" v-model.trim="prompt" :placeholder="$t('video_prompt_placeholder') || '请输入视频内容描述，输入 @ 引用媒体文件...'" @input="onPromptInput" @keydown="onPromptKeydown" @blur="onPromptBlur"></textarea>
              <!-- @ 引用下拉框 -->
              <div v-if="mentionDropdown.visible && filteredMentionItems.length > 0" class="mention-dropdown" @mousedown.prevent>
                <div v-for="(item, idx) in filteredMentionItems" :key="item.id"
                     class="mention-dropdown-item"
                     :class="{ selected: idx === mentionDropdown.selectedIndex }"
                     @click="insertMention(item)"
                     @mouseenter="mentionDropdown.selectedIndex = idx">
                  <img v-if="item.thumbnailUrl" :src="item.thumbnailUrl" style="width: 28px; height: 28px; border-radius: 4px; object-fit: cover; flex-shrink: 0;" />
                  <div v-else style="width: 28px; height: 28px; border-radius: 4px; background: #1a2530; display: flex; align-items: center; justify-content: center; font-size: 12px; flex-shrink: 0;">🎵</div>
                  <span style="flex: 1; font-size: 13px; color: #e2e8f0;">{{ item.displayName }}</span>
                  <span style="font-size: 11px; color: var(--muted); padding: 2px 6px; border-radius: 3px; background: rgba(255,255,255,0.05);">{{ item.type === 'image' ? '图片' : item.type === 'video' ? '视频' : '音频' }}</span>
                </div>
              </div>
            </div>
            <div class="muted" style="margin-top:6px; color: var(--muted); font-size: 12px;">{{ $t('at_reference_hint') }}</div>
            <div class="muted" v-if="videoModel === 'sora2'" style="margin-top:6px; color: #fca5a5;">⚠️ {{ $t('sora2_warning_content') || '注意：1 不要有 有拟人化的内容  2 不要侵犯版权' }}</div>
          </div>

          <div class="field">
            <label class="label">{{ $t('video_model_label') || '视频模型' }}</label>
            <select class="input" v-model="videoModel">
              <option v-for="opt in videoModelOptions" :key="opt.value" :value="opt.value" :disabled="opt.disabled">
                {{ opt.label }}{{ !opt.supportsMode ? ' (' + ($t('unsupported_mode') || '不支持当前模式') + ')' : '' }}
              </option>
            </select>
            <div class="muted" v-if="videoModelOptions.filter(o => o.supportsMode).length === 0" style="margin-top:6px; color: #fca5a5;">
              {{ $t('no_model_support_mode') || '⚠️ 当前没有模型支持所选的图片模式' }}
            </div>
          </div>

          <div class="field" v-if="videoModel !== 'vidu'">
            <label class="label">{{ $t('video_mode_label') || '视频模式' }}</label>
            <select class="input" v-model="model">
              <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('duration_label') || '视频时长' }}</label>
            <select class="input" v-model.number="durationSeconds">
              <option v-for="opt in durationOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label class="label">{{ $t('generation_count_label') || '生成数量' }}</label>
            <select class="input" v-model.number="count">
              <option v-for="opt in countOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="field" style="background: #1a1f2e; padding: 12px; border-radius: 8px; border: 1px solid var(--border);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: var(--muted); font-size: 14px;">{{ $t('power_consumption_label') || '算力消耗：' }}</span>
              <span style="color: #60a5fa; font-weight: bold; font-size: 16px;">{{ totalComputingPower }} {{ $t('power_unit') || '算力' }}</span>
            </div>
            <div style="margin-top: 6px; font-size: 12px; color: var(--muted);">
              {{ $t('single_power') || '单个' }} {{ computingPower }} {{ $t('power_unit') || '算力' }} × {{ count }} {{ $t('multiply_count') || '个' }} = {{ totalComputingPower }} {{ $t('total_power') || '算力' }}
            </div>
          </div>

          <div class="field">
            <div class="row">
              <button class="btn" :class="{ 'btn-disabled': !canSubmit }" @click="handleSubmit">{{ loading ? ($t('generating') || '生成中…') : ($t('start_generate_button') || '开始生成') }}</button>
              <button class="btn secondary" @click="fetchHistory" :disabled="historyLoading">{{ historyLoading ? ($t('loading') || '加载中...') : ($t('history') || '历史记录') }}</button>
            </div>
          </div>
        </div>

        <div class="status" v-if="projectId">{{ $t('task_id_display') || '任务 ID：' }}{{ projectId }}</div>
        <div class="status" v-if="statusText">{{ statusText }}</div>
        <div class="status danger" v-if="error">{{ error }}</div>

        <div class="preview" v-if="results.length">
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px;">
            <div v-for="(result, i) in results" :key="i" style="border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: #0b1220;">
              <div style="margin-bottom: 12px; font-size: 14px; font-weight: bold; color: var(--muted);">{{ $t('hd_video') || '视频' }} #{{ i + 1 }}</div>

              <!-- 原视频 -->
              <div style="margin-bottom: 16px;">
                <div style="margin-bottom: 8px; font-weight: bold; color: var(--primary); text-align: center;">{{ $t('original_image') || '原视频' }}</div>
                <video :src="result.file_url" controls style="width: 100%; border-radius: 8px;"></video>
                <div style="padding: 8px; text-align: center;">
                  <button class="btn secondary" @click="downloadVideo(result.file_url, i)" style="font-size: 12px; padding: 6px 12px;">{{ $t('download_original_video') || '下载视频' }}</button>
                  <button class="btn" @click="enhanceVideo(result, i)" :disabled="enhancingVideos[i]" style="font-size: 12px; padding: 6px 12px; margin-left: 8px;">
                    {{ enhancingVideos[i] ? ($t('enhance_processing') || '处理中...') : ($t('enhance_button') || '高清放大') }}
                  </button>
                  <div class="muted" style="margin-top: 4px; font-size: 11px;">{{ $t('cost_time') || '耗时' }}: {{ result.task_cost_time || ($t('unknown') || '未知') }}</div>
                </div>
              </div>

              <!-- 高清视频 -->
              <div v-if="result.enhancedVideo" style="border-top: 1px solid var(--border); padding-top: 16px;">
                <div style="margin-bottom: 8px; font-weight: bold; color: #10b981; text-align: center;">{{ $t('hd_video') || '高清视频' }}</div>
                <video :src="result.enhancedVideo.file_url || result.enhancedVideo" controls style="width: 100%; border-radius: 8px;"></video>
                <div style="padding: 8px; text-align: center;">
                  <button class="btn secondary" @click="downloadVideo(result.enhancedVideo.file_url || result.enhancedVideo, i, true)" style="font-size: 12px; padding: 6px 12px;">
                    {{ $t('download_enhanced_video') || '下载高清视频' }}
                  </button>
                  <div class="muted" style="margin-top: 4px; font-size: 11px;">{{ $t('cost_time') || '耗时' }}: {{ result.enhancedVideo.task_cost_time || ($t('unknown') || '未知') }}</div>
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
                  <div class="modal-title">{{ $t('history') || '历史记录' }} ({{ $t('total_records') || '共' }} {{ historyTotal }} {{ $t('items') || '条' }})</div>
                  <button class="btn secondary" @click="fetchHistory(false)" :disabled="historyLoading" style="display: inline-flex; align-items: center; justify-content: center; padding: 4px 12px; font-size: 12px;">
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
                  <span>{{ $t('type_label') || '类型' }}: {{ getHistoryTypeText(item.type) }}</span>
                  <span>{{ $t('mode_display') || '模式' }}: {{ getModelLabel(item) }}</span>
                  <span>生成模式: {{ getGenerationMode(item) }}</span>
                  <span>{{ $t('duration_label') || '时长' }}: {{ getDurationText(item) }}</span>
                  <span>{{ $t('created_time_display') || '创建时间' }}: {{ item.create_time ? new Date(item.create_time).toLocaleString('zh-CN') : ($t('unknown') || '未知') }}</span>
                </div>
                <div v-if="item.image_path" style="margin-top: 12px; padding: 12px; background: #0f1620; border-radius: 8px; border: 1px solid var(--border);">
                  <div style="font-size: 12px; color: var(--muted); margin-bottom: 8px;">{{ $t('input_images_label') || '输入图片' }}:</div>
                  <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                    <template v-for="(img, idx) in item.image_path.split(',')" :key="idx">
                      <div v-if="img" style="display: flex; align-items: center; gap: 12px;">
                        <img :src="img" style="max-width: 120px; max-height: 80px; border-radius: 6px; object-fit: cover; border: 1px solid var(--border);" />
                        <a :href="img" target="_blank" class="btn secondary" style="font-size: 12px; padding: 4px 12px; text-decoration: none;">{{ $t('view_original') || '查看原图' }}</a>
                      </div>
                    </template>
                  </div>
                </div>
                <div v-if="item.reference_images" style="margin-top: 12px; padding: 12px; background: #0f1620; border-radius: 8px; border: 1px solid var(--border);">
                  <div style="font-size: 12px; color: var(--muted); margin-bottom: 8px;">{{ $t('reference_images_display') || '参考图' }}:</div>
                  <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                    <template v-for="(img, idx) in parseReferenceImages(item.reference_images)" :key="idx">
                      <div v-if="img" style="display: flex; align-items: center; gap: 12px;">
                        <img :src="img" style="max-width: 120px; max-height: 80px; border-radius: 6px; object-fit: cover; border: 1px solid var(--border);" />
                        <a :href="img" target="_blank" class="btn secondary" style="font-size: 12px; padding: 4px 12px; text-decoration: none;">{{ $t('view_original') || '查看原图' }}</a>
                      </div>
                    </template>
                  </div>
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
                  <a :href="item.result_url" target="_blank" class="btn secondary" style="display: inline-block; text-decoration: none;">{{ $t('view_result') }}</a>
                  <button v-if="item.status == 2 && item.type == 3" class="btn" @click="enhanceVideo(item, item.id)" :disabled="enhancingVideos[item.id]" style="margin-left: 8px;">{{ enhancingVideos[item.id] ? ($t('enhanced_button') || '已修复') : ($t('generate_hd_video') || '生成高清视频') }}</button>
                  <button v-if="item.status == 2 && item.project_id" class="btn" @click="goToCharacterCard(item.project_id)" style="margin-left: 8px;">{{ $t('create_character_card') || '创建角色卡' }}</button>
                </div>
                <div style="margin-top: 8px;">
                  <button class="btn secondary" @click="timelineAiToolId = item.id">{{ $t('view_timeline') }}</button>
                </div>
              </div>

              <!-- Loading indicator -->
              <div v-if="historyLoading" style="text-align: center; padding: 20px; color: var(--muted);">
                {{ $t('loading') || '加载中...' }}
              </div>

              <!-- End indicator -->
              <div v-else-if="historyList.length >= historyTotal" style="text-align: center; padding: 20px; color: var(--muted);">
                {{ $t('all_data_loaded') || '已加载全部数据' }}
              </div>
            </div>
          </div>
        </div>
        <timeline-modal v-if="timelineAiToolId" :ai-tool-id="timelineAiToolId" @close="timelineAiToolId = null"></timeline-modal>
      </div>
    `
  };

if (typeof window !== "undefined") window.ImageToVideo = ImageToVideo;
