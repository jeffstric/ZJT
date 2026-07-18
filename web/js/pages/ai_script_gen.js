  const AIScriptGen = {
    name: 'AIScriptGen',
    data() {
      return {
        image1: null,
        image2: null,
        image3: null,
        image4: null,
        image5: null,
        previews: [null, null, null, null, null],
        extraPrompt: '',
        addDetail: '否',
        needNarration: '是',
        loading: false,
        error: '',
        scriptResult: null,
        scenes: [],
        sceneJsons: [],
        authToken: localStorage.getItem('auth_token') || '',
        videoLoading: false,
        videoError: '',
        videoProjectIds: [],
        videoProjectId: '',
        videoStatus: '',
        videoResults: [],
        videoStatusTimer: null,
        videoCount: 1,
        editingSceneIndex: null,
        editingSceneText: '',
        progressPercent: 0,
        progressTimer: null,
        estimatedTime: 300, // 5 minutes in seconds
        elapsedTime: 0,
        showHistory: false,
        historyList: [],
        historyLoading: false,
        historyPage: 1,
        historyTotal: 0,
        timelineAiToolId: null,
        videoRatio: '9:16',
        enhancingVideos: {}, 
        enhanceTaskIds: {},
        enhanceStatusTimers: {},
        oneClickLoading: false,
        taskTypeConfig: null  // 从接口获取的任务类型配置
      };
    },
    computed: {
      canSubmit() {
        return !!this.image1 && !this.loading;
      }
    },
    mounted() {
      // 获取任务类型配置
      this.fetchTaskTypeConfig();
    },
    methods: {
      async fetchTaskTypeConfig() {
        try {
          await TaskConfig.load();
          this.taskTypeConfig = TaskConfig.getTaskTypeConfig();
        } catch (error) {
          console.error('获取任务类型配置异常:', error);
        }
      },

      onFileChange(e, index) {
        const file = e.target.files[0] || null;
        const key = `image${index}`;
        const currentUrl = this.previews[index - 1];
        if (currentUrl) {
          URL.revokeObjectURL(currentUrl);
        }
        this[key] = file;
        if (file) {
          const previewUrl = URL.createObjectURL(file);
          this.previews.splice(index - 1, 1, previewUrl);
        } else {
          this.previews.splice(index - 1, 1, null);
        }
        e.target.value = '';
      },
      async submit() {
        if (!this.canSubmit) {
          if (!this.image1) {
            alert('请上传图片');
          }
          return;
        }
        this.loading = true;
        this.error = '';
        this.scriptResult = null;
        this.scenes = [];
        this.sceneJsons = [];
        this.startProgress();
        try {
          const form = new FormData();
          form.append('image1', this.image1);
          if (this.image2) form.append('image2', this.image2);
          if (this.image3) form.append('image3', this.image3);
          if (this.image4) form.append('image4', this.image4);
          if (this.image5) form.append('image5', this.image5);
          form.append('extra_prompt', this.extraPrompt);
          form.append('add_detail', this.addDetail);
          form.append('need_narration', this.needNarration);
          const userId = localStorage.getItem('user_id');
          if (userId) {
            form.append('user_id', userId);
          }
          if (this.authToken) {
            form.append('auth_token', this.authToken);
          }

          const res = await axios.post('/api/ai-script-generate', form, {
            headers: { 'Content-Type': 'multipart/form-data' }
          });
          this.scriptResult = res.data.script;
          if (this.scriptResult && Array.isArray(this.scriptResult.ScriptScenes)) {
            this.scenes = this.scriptResult.ScriptScenes;
            this.sceneJsons = this.scriptResult.ScriptScenes.map(scene => JSON.stringify(scene, null, 2));
          } else {
            this.scenes = [];
            this.sceneJsons = [];
          }
          this.completeProgress();
        } catch (err) {
          console.error(err);
          this.error = err?.response?.data?.detail || err?.message || '请求失败';
          this.stopProgress();
        } finally {
          this.loading = false;
        }
      },
      
      async oneClickGenerateVideo() {
        if (!this.canSubmit) {
          if (!this.image1) {
            alert('请上传图片');
          }
          return;
        }
        
        this.oneClickLoading = true;
        this.loading = true;
        this.error = '';
        this.videoError = '';
        this.scriptResult = null;
        this.scenes = [];
        this.sceneJsons = [];
        this.videoResults = [];
        this.videoStatus = '';
        this.videoProjectIds = [];
        this.videoProjectId = '';
        this.startProgress();
        
        try {
          // Step 1: Generate script
          const scriptForm = new FormData();
          scriptForm.append('image1', this.image1);
          if (this.image2) scriptForm.append('image2', this.image2);
          if (this.image3) scriptForm.append('image3', this.image3);
          if (this.image4) scriptForm.append('image4', this.image4);
          if (this.image5) scriptForm.append('image5', this.image5);
          scriptForm.append('extra_prompt', this.extraPrompt);
          scriptForm.append('add_detail', this.addDetail);
          scriptForm.append('need_narration', this.needNarration);
          const userId = localStorage.getItem('user_id');
          if (userId) {
            scriptForm.append('user_id', userId);
          }
          if (this.authToken) {
            scriptForm.append('auth_token', this.authToken);
          }

          const scriptRes = await axios.post('/api/ai-script-generate', scriptForm, {
            headers: { 'Content-Type': 'multipart/form-data' }
          });
          
          this.scriptResult = scriptRes.data.script;
          if (this.scriptResult && Array.isArray(this.scriptResult.ScriptScenes)) {
            this.scenes = this.scriptResult.ScriptScenes;
            this.sceneJsons = this.scriptResult.ScriptScenes.map(scene => JSON.stringify(scene, null, 2));
          } else {
            this.scenes = [];
            this.sceneJsons = [];
            throw new Error('脚本生成失败，无法继续生成视频');
          }
          
          this.completeProgress();
          this.loading = false;
          
          // Step 2: Automatically generate video
          this.videoLoading = true;
          this.clearVideoStatusPolling();
          
          const videoForm = new FormData();
          
          // Add all uploaded images
          [this.image1, this.image2, this.image3, this.image4, this.image5].forEach(file => {
            if (file) videoForm.append('images', file);
          });
          
          // Combine all scene Text content
          const sceneTexts = this.scenes
            .map(scene => scene.Text || scene.SceneDescription || '')
            .filter(text => text && text.trim())
            .join(' ');
          
          videoForm.append('prompt', sceneTexts || '根据上传图片生成视频');
          videoForm.append('ratio', this.videoRatio);
          videoForm.append('duration_seconds', 15);
          videoForm.append('count', this.videoCount);
          
          if (userId) videoForm.append('user_id', userId);
          if (this.authToken) videoForm.append('auth_token', this.authToken);
          
          const videoRes = await axios.post('/api/ai-app-run-image', videoForm);
          
          // Handle multiple project IDs
          this.videoProjectIds = videoRes.data.project_ids || [];
          this.videoProjectId = this.videoProjectIds.join(', ');
          this.videoStatus = videoRes.data.status || '';
          
          if (this.videoProjectIds.length > 0) {
            this.checkVideoStatus();
          }
          
        } catch (err) {
          console.error(err);
          const errorMsg = err?.response?.data?.detail || err?.message || '一键生成失败';
          if (this.loading) {
            this.error = errorMsg;
            this.stopProgress();
          } else {
            this.videoError = errorMsg;
          }
          this.loading = false;
          this.videoLoading = false;
        } finally {
          this.oneClickLoading = false;
        }
      },
      startProgress() {
        this.progressPercent = 0;
        this.elapsedTime = 0;
        this.clearProgressTimer();
        this.progressTimer = setInterval(() => {
          this.elapsedTime += 0.1;
          // Progress increases gradually, slowing down as it approaches 95%
          const targetProgress = Math.min((this.elapsedTime / this.estimatedTime) * 100, 95);
          this.progressPercent = Math.min(this.progressPercent + (targetProgress - this.progressPercent) * 0.1, 95);
        }, 100);
      },
      completeProgress() {
        this.progressPercent = 100;
        this.clearProgressTimer();
      },
      stopProgress() {
        this.clearProgressTimer();
        this.progressPercent = 0;
        this.elapsedTime = 0;
      },
      clearProgressTimer() {
        if (this.progressTimer) {
          clearInterval(this.progressTimer);
          this.progressTimer = null;
        }
      },
      updateScene(index, field, value) {
        if (this.scenes[index]) {
          this.$set ? this.$set(this.scenes[index], field, value) : (this.scenes[index][field] = value);
          this.sceneJsons[index] = JSON.stringify(this.scenes[index], null, 2);
        }
      },
      formatSceneTitle(scene) {
        if (!scene) return '';
        return `${scene.SceneNumber || ''}${scene.SceneName ? ' - ' + scene.SceneName : ''}`;
      },
      cleanupPreviews() {
        this.previews.forEach(url => {
          if (url) URL.revokeObjectURL(url);
        });
      },
      startEditScene(index) {
        this.editingSceneIndex = index;
        this.editingSceneText = this.scenes[index].Text || this.scenes[index].SceneDescription || '';
      },
      saveEditScene(index) {
        if (this.editingSceneText.trim()) {
          this.scenes[index].Text = this.editingSceneText.trim();
          this.sceneJsons[index] = JSON.stringify(this.scenes[index], null, 2);
        }
        this.editingSceneIndex = null;
        this.editingSceneText = '';
      },
      cancelEditScene() {
        this.editingSceneIndex = null;
        this.editingSceneText = '';
      },

      async enhanceVideo(item, index) {
        const videoUrl = item?.file_url || item?.result_url;
        if (!videoUrl) {
          alert('暂无可增强的视频');
          return;
        }
        if (this.enhancingVideos[index]) {
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
          form.append('enhance_type', '6'); // 高清放大任务类型

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
            alert('视频高清放大任务已提交');
          } else {
            throw new Error('任务提交失败');
          }
        } catch (err) {
          console.error(err);
          alert(err?.response?.data?.detail || err?.message || '高清放大失败');
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
            this.enhanceStatusTimers[taskId] = setTimeout(() => this.pollEnhanceStatus(item, index), 5000);
          }
        } catch (err) {
          this.enhanceStatusTimers[taskId] = setTimeout(() => this.pollEnhanceStatus(item, index), 5000);
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
          const authToken = localStorage.getItem('auth_token') || this.authToken;
          
          // 如果没有获取到任务类型配置，先获取
          if (!this.taskTypeConfig) {
            await this.fetchTaskTypeConfig();
          }
          
          // 使用后端返回的图生视频类型列表，如果没有则使用默认值
          const imageToVideoTypes = this.taskTypeConfig?.image_to_video_types || [3, 10, 11, 12, 14, 15, 19, 20];
          const typesStr = imageToVideoTypes.join(',');
          
          const response = await axios.get('/api/ai-tools/history', {
            params: {
              user_id: parseInt(userId, 10),
              page: this.historyPage,
              page_size: 20,
              types: typesStr,
              auth_token: authToken || undefined
            }
          });

          if (response.data.success) {
            const newData = response.data.data?.data || [];
            this.historyList = append ? [...this.historyList, ...newData] : newData;
            this.historyTotal = response.data.data?.total || 0;
            this.showHistory = true;
          } else {
            alert(response.data.message || '获取历史记录失败');
          }
        } catch (err) {
          console.error(err);
          alert(err?.response?.data?.message || '获取历史记录失败');
          this.showHistory = true;
        } finally {
          this.historyLoading = false;
        }
      },
      async loadMoreHistory() {
        if (this.historyLoading || this.historyList.length >= this.historyTotal) {
          return;
        }
        this.historyPage += 1;
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

      getHistoryTypeText(type) {
        // 使用后端返回的任务类型名称映射
        return this.taskTypeConfig?.task_type_name_map?.[type] || '未知类型';
      },

      getModelLabel(item) {
        console.log('AIScriptGen getModelLabel:', { item, videoRatio: this.videoRatio });
        const modelMap = {
          '9:16': '竖屏',
          '16:9': '横屏'
        };
        const resolved = item.ratio || this.videoRatio;
        const result = modelMap[resolved] || resolved || '未知';
        console.log('AIScriptGen getModelLabel result:', { resolved, result });
        return result;
      },
    
      getDurationText(item) {
         const duration = item?.original_duration ?? item?.duration ?? item?.video_duration ?? 15;
         return duration ? `${duration}秒` : '未知';
      },

      async generateVideo() {
        if (!this.scenes.length || !this.image1) {
          alert('请先上传图片并生成脚本');
          return;
        }
        
        this.videoError = '';
        this.videoResults = [];
        this.videoStatus = '';
        this.videoProjectIds = [];
        this.videoProjectId = '';
        this.videoLoading = true;
        this.clearVideoStatusPolling();
 
        
        try {
          const form = new FormData();
          
          // Add all uploaded images
          [this.image1, this.image2, this.image3, this.image4, this.image5].forEach(file => {
            if (file) form.append('images', file);
          });
          
          // Combine all scene Text content
          const sceneTexts = this.scenes
            .map(scene => scene.Text || scene.SceneDescription || '')
            .filter(text => text && text.trim())
            .join(' ');
          
          form.append('prompt', sceneTexts || '根据上传图片生成视频');
          form.append('ratio', this.videoRatio);
          form.append('duration_seconds', 15);
          form.append('count', this.videoCount);
          
          const userId = localStorage.getItem('user_id');
          if (userId) form.append('user_id', userId);
          if (this.authToken) form.append('auth_token', this.authToken);
          
          const res = await axios.post('/api/ai-app-run-image', form);
          
          // Handle multiple project IDs
          this.videoProjectIds = res.data.project_ids || [];
          this.videoProjectId = this.videoProjectIds.join(', ');
          this.videoStatus = res.data.status || '';
          
          if (this.videoProjectIds.length > 0) {
            this.checkVideoStatus();
          }
        } catch (err) {
          console.error(err);
          this.videoError = err?.response?.data?.detail || err?.message || '视频生成请求失败';
          this.videoLoading = false;
        }
      },
      async checkVideoStatus() {
        if (!this.videoProjectIds || this.videoProjectIds.length === 0) return;
        
        try {
          const authToken = localStorage.getItem('auth_token');
          const params = authToken ? { auth_token: authToken } : {};
          
          // Batch query all project IDs
          const projectIdsStr = this.videoProjectIds.join(',');
          const res = await axios.get('/api/get-status/' + projectIdsStr, { params });
          const payload = res?.data;

          if (!payload) {
            console.error('Invalid status response:', payload);
            this.videoStatusTimer = setTimeout(() => this.checkVideoStatus(), 10000);
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
                task.results.forEach(item => {
                  const baseItem = typeof item === 'string' ? { file_url: item } : item;
                  allResults.push({ ...baseItem, enhancedVideo: null });
                });
              }
            });
            
            this.videoResults = allResults.filter(item => !!item.file_url);
            
            if (allSuccess) {
              this.videoStatus = 'SUCCESS';
              this.videoLoading = false;
              this.clearVideoStatusPolling();
            } else if (anyFailed && !anyRunning) {
              // All done but some failed
              const failedTasks = tasks.filter(t => t.status === 'FAILED');
              this.videoError = `${failedTasks.length} 个任务失败`;
              this.videoStatus = 'FAILED';
              this.videoLoading = false;
              this.clearVideoStatusPolling();
            } else {
              // Still running
              this.videoStatus = 'RUNNING';
              this.videoStatusTimer = setTimeout(() => this.checkVideoStatus(), 10000);
            }
          } else {
            // Single task response (backward compatibility)
            this.videoStatus = payload.status || '';
            
            if (this.videoStatus === 'SUCCESS') {
              const rawResults = payload.results || [];
              this.videoResults = rawResults.map(item => {
                const baseItem = typeof item === 'string' ? { file_url: item } : item;
                return { ...baseItem, enhancedVideo: null };
              }).filter(item => !!item.file_url);
              this.videoLoading = false;
              this.clearVideoStatusPolling();
            } else if (this.videoStatus === 'FAILED') {
              this.videoError = payload.reason || '视频生成失败';
              this.videoLoading = false;
              this.clearVideoStatusPolling();
            } else {
              this.videoStatusTimer = setTimeout(() => this.checkVideoStatus(), 10000);
            }
          }
        } catch (err) {
          console.error(err);
          this.videoError = '查询视频状态失败';
          this.videoLoading = false;
          this.clearVideoStatusPolling();
        }
      },
      clearVideoStatusPolling() {
        if (this.videoStatusTimer) {
          clearTimeout(this.videoStatusTimer);
          this.videoStatusTimer = null;
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
          const prefix = isEnhanced ? 'ai_script_video_enhanced' : 'ai_script_video';
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
    },
    beforeUnmount() {
      this.cleanupPreviews();
      this.clearVideoStatusPolling();
      this.clearProgressTimer();
      Object.values(this.enhanceTaskIds).forEach(taskId => {
        const timer = this.enhanceStatusTimers?.[taskId];
        if (timer) clearTimeout(timer);
      });
    },
    template: `
  <div>
    <div class="form">
      <div class="field">
        <label class="label">上传图片 (最多5张)</label>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 8px;">
          <div class="upload-card" v-for="slot in 5" :key="slot">
            <input type="file" accept="image/*" :id="'script-image-' + slot" style="display:none" @change="e => onFileChange(e, slot)" />
            <label :for="'script-image-' + slot" class="upload-card-body" style="cursor: pointer; display: flex; align-items: center; justify-content: center; border: 1px dashed rgba(255,255,255,0.25); border-radius: 12px; background: rgba(16,24,48,0.85); height: 160px; position: relative; overflow: hidden; transition: border-color 0.2s ease, transform 0.2s ease;">
              <template v-if="previews[slot - 1]">
                <img :src="previews[slot - 1]" :alt="'图片' + slot + '预览'" style="width: 100%; height: 100%; object-fit: cover;" />
                <div style="position: absolute; bottom: 0; left: 0; right: 0; background: linear-gradient(180deg, transparent, rgba(0,0,0,0.6)); padding: 6px 10px; font-size: 12px; color: #fff; text-align: right;">点击重新上传</div>
              </template>
              <template v-else>
                <div style="text-align: center; color: var(--muted);">
                  <div style="width: 48px; height: 48px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.15); margin: 0 auto 12px; display: flex; align-items: center; justify-content: center; font-size: 28px; color: var(--primary);">＋</div>
                  <div style="font-weight: 600; color: var(--text);">上传图片</div>
                  <div style="font-size: 12px; margin-top: 6px;">{{ slot === 1 ? '图片1（必传）' : ('图片' + slot + '（可选）') }}</div>
                </div>
              </template>
            </label>
            <div style="text-align: center; margin-top: 6px; font-size: 12px; color: var(--muted);">
              {{ slot === 1 ? '图片1（必传）' : ('图片' + slot + '（可选）') }}
            </div>
          </div>
        </div>
        <div style="margin-top: 12px; padding: 10px 12px; border-radius: 6px; color: rgb(122 116 116); font-size: 13px; line-height: 1.4;">
          ⚠️ 注意：1.请勿上传真人图片 2.不要侵犯版权
        </div>
      </div>
      <div class="field">
        <label class="label">额外提示词（可选）</label>
        <textarea class="textarea" v-model.trim="extraPrompt" placeholder="请输入想补充的需求，例如：加入品牌故事等"></textarea>
      </div>
      <div class="field">
        <label class="label">是否添加细节描写</label>
        <select class="input" v-model="addDetail">
          <option value="否">否</option>
          <option value="是">是</option>
        </select>
      </div>
      <div class="field">
        <label class="label">是否需要旁白</label>
        <select class="input" v-model="needNarration">
          <option value="否">否</option>
          <option value="是">是</option>
        </select>
      </div>
      <div class="field">
        <label class="label">视频比例</label>
        <select class="input" v-model="videoRatio">
          <option value="9:16">竖屏 (9:16)</option>
          <option value="16:9">横屏 (16:9)</option>
        </select>
        <div style="margin-top: 6px; font-size: 13px; color: var(--muted);">视频时长15秒</div>
      </div>
      <div class="field">
        <label class="label">生成数量</label>
        <select class="input" v-model.number="videoCount">
          <option :value="1">1个</option>
          <option :value="2">2个</option>
          <option :value="3">3个</option>
          <option :value="4">4个</option>
        </select>
      </div>
      <div class="field">
        <div class="row">
          <button class="btn" :disabled="!canSubmit || loading || videoLoading" @click="oneClickGenerateVideo">
            {{ oneClickLoading ? '一键生成中…' : '一键生成视频' }}
          </button>
          <button class="btn secondary" :disabled="!canSubmit || oneClickLoading || videoLoading" @click="submit">{{ loading && !oneClickLoading ? '生成中…' : 'AI生成脚本' }}</button>
          <button class="btn secondary" @click="fetchHistory" :disabled="historyLoading">{{ historyLoading ? '加载中...' : '历史记录' }}</button>
        </div>
      </div>
      <div v-if="loading" class="progress-container">
        <div class="progress-bar-wrapper">
          <div class="progress-bar" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <div class="progress-text">
          预计时间：<span class="progress-time">5分钟</span> | 当前进度：
          <span class="progress-time">{{ Math.round(progressPercent) }}%</span>
        </div>
      </div>
    </div>
    <div class="status danger" v-if="error">{{ error }}</div>
    <div v-if="scriptResult" style="margin-top: 24px;">
      <div v-if="scenes.length" style="margin-top: 16px; padding:18px">
        <h3 style="color: var(--primary); margin-bottom: 12px; font-size: 14px;">脚本场景（共 {{ scenes.length }} 个）</h3>
        <div class="scene-card" v-for="(scene, idx) in scenes" :key="idx" style="max-width: 720px; margin: 0 0 16px;">
          <div class="scene-card-header" style="margin-bottom: 6px;">
            <h4 style="font-size: 14px; font-weight: 600; margin: 0; color: var(--text);">{{ formatSceneTitle(scene) }}</h4>
          </div>
          <div class="scene-layout">
            <textarea
              class="textarea scene-textarea-left"
              :value="editingSceneIndex === idx ? editingSceneText : (scene.Text || '')"
              @input="editingSceneIndex === idx ? (editingSceneText = $event.target.value) : null"
              :readonly="editingSceneIndex !== idx"
              style="min-height: 180px;"
            ></textarea>
            <div class="scene-buttons-right">
              <template v-if="editingSceneIndex !== idx">
                <button class="btn secondary" @click="startEditScene(idx)">修改</button>
              </template>
              <template v-else>
                <button class="btn" @click="saveEditScene(idx)">保存</button>
                <button class="btn secondary" @click="cancelEditScene">取消</button>
              </template>
            </div>
          </div>
        </div>
      </div>
      <div v-if="scenes.length" style="margin-top: 16px; padding-right: 18px;">
        <div class="field" style="display: flex; justify-content: flex-end; margin-bottom: 0; padding-left: 18px;">
          <button class="btn btn-full" :disabled="videoLoading" @click="generateVideo" style="padding: 14px 32px; font-size: 18px;">
            {{ videoLoading ? '生成中…' : '生成视频' }}
          </button>
        </div>
      </div>
      <div class="status" v-if="videoProjectId" style="margin-top: 16px;">任务 ID：{{ videoProjectId }}</div>
      <div v-if="videoLoading" class="status" style="margin-top: 16px;">
        视频生成中，请稍候... 状态: {{ videoStatus }}
      </div>
      <div v-if="videoError" class="status danger" style="margin-top: 16px;">
        {{ videoError }}
      </div>
      <div v-if="videoResults.length" style="margin-top: 16px; padding:18px;">
        <h3 style="color: var(--primary); margin-bottom: 12px; font-size: 14px;">生成的视频（共 {{ videoResults.length }} 个）</h3>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px;">
          <div v-for="(result, idx) in videoResults" :key="idx" style="border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: #0b1220;">
            <div style="margin-bottom: 12px; font-size: 14px; font-weight: bold; color: var(--muted);">视频 #{{ idx + 1 }}</div>
            
            <!-- 原视频 -->
            <div style="margin-bottom: 16px;">
              <div style="margin-bottom: 8px; font-weight: bold; color: var(--primary); text-align: center;">原视频</div>
              <video :src="result.file_url" controls style="width: 100%; border-radius: 8px;"></video>
              <div style="padding: 8px; text-align: center;">
                <button class="btn secondary" @click="downloadVideo(result.file_url, idx)" style="font-size: 12px; padding: 6px 12px;">下载视频</button>
                <button class="btn" @click="enhanceVideo(result, idx)" :disabled="enhancingVideos[idx]" style="font-size: 12px; padding: 6px 12px; margin-left: 8px;">
                  {{ enhancingVideos[idx] ? '处理中...' : '高清放大' }}
                </button>
              </div>
            </div>

            <!-- 高清视频 -->
            <div v-if="result.enhancedVideo" style="border-top: 1px solid var(--border); padding-top: 16px;">
              <div style="margin-bottom: 8px; font-weight: bold; color: #10b981; text-align: center;">高清视频</div>
              <video :src="result.enhancedVideo.file_url || result.enhancedVideo" controls style="width: 100%; border-radius: 8px;"></video>
              <div style="padding: 8px; text-align: center;">
                <button class="btn secondary" @click="downloadVideo(result.enhancedVideo.file_url || result.enhancedVideo, idx, true)" style="font-size: 12px; padding: 6px 12px;">
                  下载高清视频
                </button>
                <div class="muted" style="margin-top: 4px; font-size: 11px;">
                  耗时: {{ result.enhancedVideo.task_cost_time || '未知' }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="modal-overlay" v-if="showHistory" @click.self="closeHistory">
      <div class="modal" style="max-width: 800px; max-height: 80vh; overflow-y: auto;" @scroll="handleHistoryScroll">
        <div class="modal-sticky-header">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; padding-right: 40px; margin-bottom: 12px;">
            <div style="display: flex; align-items: flex-start; gap: 12px;">
              <div class="modal-title">历史记录 (共 {{ historyTotal }} 条)</div>
              <button
                class="btn secondary"
                @click="fetchHistory(false)"
                :disabled="historyLoading"
                style="display: inline-flex; align-items: center; justify-content: center; padding: 4px 12px; font-size: 12px;"
              >
                {{ historyLoading ? '刷新中...' : '刷新' }}
              </button>
            </div>
            <button class="modal-close" @click="closeHistory">×</button>
          </div>
        </div>
        <div v-if="historyList.length === 0" style="padding: 40px; text-align: center; color: var(--muted);">
          暂无历史记录
        </div>
        <div v-else style="padding: 16px;">
          <div v-for="item in historyList" :key="item.id" style="margin-bottom: 16px; padding: 12px; background: #0b1220; border: 1px solid var(--border); border-radius: 8px;">
            <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
              <div>
                <strong>提示词:</strong> {{ item.prompt }}
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
              <span>类型: {{ getHistoryTypeText(item.type) }}</span>
              <span>模式: {{ getModelLabel(item) }}</span>
              <span>时长: {{ getDurationText(item) }}</span>
              <span>创建时间: {{ item.create_time ? new Date(item.create_time).toLocaleString('zh-CN') : '未知' }}</span>
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
              <a :href="item.result_url" target="_blank" class="btn secondary" style="display: inline-block; text-decoration: none;">查看结果</a>
              <button v-if="item.status == 2 && item.type == 3" class="btn" @click="enhanceVideo(item, item.id)" :disabled="enhancingVideos[item.id]" style="margin-left: 8px;">
                {{ enhancingVideos[item.id] ? '已修复' : '生成高清视频' }}
              </button>
            </div>
            <div style="margin-top: 8px;">
              <button class="btn secondary" @click="timelineAiToolId = item.id">{{ $t('view_timeline') }}</button>
            </div>
          </div>
          <div v-if="historyLoading" style="text-align: center; padding: 20px; color: var(--muted);">
            加载中...
          </div>
          <div v-else-if="historyList.length >= historyTotal" style="text-align: center; padding: 20px; color: var(--muted);">
            已加载全部数据
          </div>
        </div>
      </div>
    </div>
    <timeline-modal v-if="timelineAiToolId" :ai-tool-id="timelineAiToolId" @close="timelineAiToolId = null"></timeline-modal>
  </div>
`
  };

if (typeof window !== "undefined") window.AIScriptGen = AIScriptGen;
