  const routes = [
    { path: '/', name: 'list', component: ListPage },
    { path: '/image-edit', name: 'image-edit', component: ImageEdit },
    { path: '/text-to-image', name: 'text-to-image', component: TextToImage },
    { path: '/ai-video-gen', name: 'ai-video-gen', component: AIVideoGen },
    { path: '/image-to-video', name: 'image-to-video', component: ImageToVideo },
    { path: '/ai-script-gen', name: 'ai-script-gen', component: AIScriptGen },
    { path: '/video-enhance', name: 'video-enhance', component: VideoEnhance },
    { path: '/audio-generate', name: 'audio-generate', component: AudioGenerate },
    { path: '/digital-human', name: 'digital-human', component: DigitalHuman },
    { path: '/skill-config', name: 'skill-config', component: SkillConfig }
  ];
  const router = VueRouter.createRouter({
    history: VueRouter.createWebHistory(),
    routes,
  });

  const App = {
    data(){ return { 
      tools: [
        {name:'图片编辑', path:'/image-edit'},
        {name:'AI视频生成', path:'/ai-video-gen'},
        {name:'图片生成视频', path:'/image-to-video'},
        {name:'智能图片生成视频', path:'/ai-script-gen'},
        {name:'小红书笔记修改', path:'http://ssh.perseids.cn:15678/form/8cd1955c-5cf6-4111-a3a4-406001d7e3b2'}
      ],
      authToken: '',
      userPhone: '',
      userEmail: '',
      inviteCode: '',
      computingPower: null,
      invitationStats: null,
      // 佣金中心（商业版；社区版接口403自动隐藏）
      showCommission: false,
      commissionSummary: { available: 0, frozen: 0, withdrawn: 0, total: 0 },
      commissionRate: 0,
      commissionRateInput: 0,
      maxCommissionRate: 50,
      commissionRecords: [],
      commissionWithdrawals: [],
      commissionSaving: false,
      // 提现表单
      showWithdrawForm: false,
      withdrawForm: { method: 'alipay', alipay_account: '', bank_card_no: '', bank_account_name: '', bank_name: '', apply_note: '' },
      commissionWithdrawing: false,
      showLoginModal: false,
      showInviteModal: false,
      showComputingPowerLogsModal: false,
      showRechargePowerModal: false,
      showFeedbackModal: false,
      showWechatChannelsModal: false,
      // 官方微信群引导
      wxGroupGuideEnabled: false,
      wxGroupQrUrl: '',           // 配置中的原始地址（可能是远端 http）
      wxGroupQrProxyPath: '/api/system/wx-group-qr',
      showWxGroupSoftPanel: false,
      showWxGroupModal: false,
      wxGroupDontShowAgain: false,
      _wxGroupSoftTimer: null,
      authMode: 'login', // 'login' or 'register'
      loginForm: {
        phone: '',
        password: '',
        termsAgreed: false
      },
      loginLoading: false,
      loginError: '',
      registerForm: {
        phone: '',
        email: '',
        code: '',
        password: '',
        inviteCode: '',
        termsAgreed: false
      },
      registerType: 'phone',
      registerLoading: false,
      registerError: '',
      codeSending: false,
      codeCountdown: 0,
      countdownTimer: null,
      resetForm: {
        phone: '',
        email: '',
        code: '',
        newPassword: '',
        confirmPassword: ''
      },
      resetType: 'phone',
      resetLoading: false,
      resetError: '',
      resetCodeSending: false,
      resetCodeCountdown: 0,
      resetCountdownTimer: null,
      loginShowTerms: false,
      userId: '',
      showTermsModal: false,
      termsContent: '',
      showWechatGuideModal: false,
      rechargePackages: [],
      rechargePackagesLoading: false,
      selectedPackage: null,
      paymentLoading: false,
      paymentQrCode: '',
      paymentOrderId: '',
      paymentError: '',
      wechatOpenid: '',
      userIp: '',
      nativeCodeUrl: '',
      showAdminSwitchModal: false,
      adminSwitchToken: '',
      adminSwitchPhone: '',
      adminSwitchUserId: '',
      adminSwitchLoading: false,
      adminSwitchError: '',
      adminSwitchSuccess: '',
      isAdminMode: false,
      userRole: '',
      // 模式选择相关
      showModeSelectModal: false,
      creationMode: '',
      // 本地模式配置
      isLocal: false,
      // 邮箱功能开关
      emailEnabled: false,
      // CAPTCHA 人机验证
      captchaEnabled: false,
      captchaPrefix: '',
      captchaSceneId: '',
      captchaInstance: null,
      captchaAction: null,  // 'register_code' | 'reset_code'
      captchaVerifyParam: null,
      // 网站底部配置
      footerConfig: {
        copyright: '',
        icp_number: '',
        icp_url: 'https://beian.miit.gov.cn/',
        police_number: '',
        police_url: ''
      },
      // 用户设置模态框
      showUserSettingsModalFlag: false,
      userSettingsLoading: false,
      userSettingsError: '',
      userSettingsSuccess: '',
      userSettingsTab: 'preferences', // 'preferences' | 'apitoken'
      // 用户偏好数据
      userPreferences: {},
      availableImplementations: {},
      isCommunityEdition: false,
      isEditionLoaded: false,
      zjtTokenEnabled: false, // 管理员是否开启了智剧通Token
      // API Token 数据
      apiTokenData: {
        has_token: false,
        token: ''
      },
      apiTokenLoading: false,
      apiTokenError: '',
      apiTokenNewToken: '', // 仅在生成时显示一次
      // 签到相关
      checkinStatus: { checked_in_today: false, streak_days: 0, checkin_enabled: true, base_reward: 10, days_to_next_reward: null, next_reward_amount: null },
      checkinLoading: false,
      checkinToast: { show: false, reward: 0, streak_days: 0, nextRewardText: '' },
      checkinToastTimer: null,
      showAgentConnectionModal: false,
      agentConnectionTab: 'connection', // connection | cliMediaPref
      agentConnectionLoading: false,
      agentConnectionError: '',
      agentConnectionCopied: false,
      agentConnectionInfo: null,
      agentConnectionText: '',
      // CLI 媒体模型偏好（storyboard_cli surface）
      cliMediaPrefLoading: false,
      cliMediaPrefError: '',
      cliMediaPrefSuccess: '',
      cliMediaPrefWorlds: [],
      cliMediaPrefWorldId: null,
      cliMediaPrefProfiles: {},
      cliMediaPrefSelected: {},
      cliMediaPrefModels: {},
      cliMediaPrefSaving: {},
      cliMediaPrefSaved: {},
      cliMediaPrefRowError: {},
      cliMediaPrefModelsLoaded: false,
      _cliMediaPrefModelsCache: null,
      _cliMediaPrefSuccessTimer: null,
      cliMediaPrefGroups: [
        {
          key: 'image',
          title: '图片',
          slots: [
            {
              key: 'image.text_to_image',
              mediaType: 'image',
              mode: 'text_to_image',
              label: '文生图',
              hint: '只根据文字生成图片',
              modelListKey: 'text_to_image_models',
              fallbackListKey: 'image_models',
            },
            {
              key: 'image.image_edit',
              mediaType: 'image',
              mode: 'image_edit',
              label: '图片编辑',
              hint: '有参考图时改图、修图',
              modelListKey: 'image_edit_models',
              fallbackListKey: 'image_models',
            },
          ],
        },
        {
          key: 'video',
          title: '视频',
          slots: [
            {
              key: 'video.text_to_video',
              mediaType: 'video',
              mode: 'text_to_video',
              label: '文生视频',
              hint: '只根据文字生成视频',
              modelListKey: 'text_to_video_models',
              fallbackListKey: 'video_models',
            },
            {
              key: 'video.image_to_video',
              mediaType: 'video',
              mode: 'image_to_video',
              label: '图生视频',
              hint: '用首帧图片生成视频',
              modelListKey: 'image_to_video_models',
              fallbackListKey: 'video_models',
            },
            {
              key: 'video.reference_to_video',
              mediaType: 'video',
              mode: 'reference_to_video',
              label: '参考视频',
              hint: '用多张参考图或音视频素材',
              modelListKey: 'image_to_video_models',
              fallbackListKey: 'video_models',
              referenceOnly: true,
            },
          ],
        },
      ],
    } },
    mounted() {
      // Extract auth_token from URL query parameters at app level
      const urlParams = new URLSearchParams(window.location.search);
      
      // 优先处理 login=1 参数（通常表示认证过期需要重新登录）
      if (urlParams.get('login') === '1') {
        // 清除可能已过期的本地认证信息
        localStorage.removeItem('auth_token');
        localStorage.removeItem('phone');
        localStorage.removeItem('user_id');
        localStorage.removeItem('invite_code');
        
        // 处理登录后跳转的目标路径（仅允许路径，不允许完整URL）
        const redirectUrl = urlParams.get('redirect_url');
        if (redirectUrl) {
          // 验证是否为有效的路径（不包含协议和域名）
          if (!redirectUrl.includes('://') && !redirectUrl.includes('//')) {
            // 确保路径以 / 开头
            const targetPath = redirectUrl.startsWith('/') ? redirectUrl : '/' + redirectUrl;
            localStorage.setItem('redirect_after_login', targetPath);
          }
        }
      }
      
      this.authToken = urlParams.get('auth_token') || '';
      this.userPhone = urlParams.get('phone') || '';
      this.userEmail = urlParams.get('email') || '';
      this.userId = urlParams.get('user_id') || '';
      this.inviteCode = urlParams.get('invite_code') || '';
      
      // 处理微信授权回调
      const wechatCode = urlParams.get('code');
      if (wechatCode) {
        this.handleWechatAuthCallback(wechatCode);
      }
      
      if (this.authToken) {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('phone');
        localStorage.removeItem('email');
        localStorage.removeItem('user_id');
        localStorage.removeItem('invite_code');
        // Store in localStorage for persistence across sessions
        localStorage.setItem('auth_token', this.authToken);
        localStorage.setItem('phone', this.userPhone);
        localStorage.setItem('email', this.userEmail);
        localStorage.setItem('user_id', this.userId);
        localStorage.setItem('invite_code', this.inviteCode);
      } else {
        // Try to restore from localStorage
        this.authToken = localStorage.getItem('auth_token') || '';
        this.userPhone = localStorage.getItem('phone') || '';
        this.userEmail = localStorage.getItem('email') || '';
        this.userId = localStorage.getItem('user_id') || '';
        // URL 带的邀请码优先，localStorage 仅兜底（避免未登录时被空值覆盖、丢失 URL 邀请码）
        this.inviteCode = this.inviteCode || localStorage.getItem('invite_code') || '';
      }

      // URL/本地存储带有的邀请码，自动代入注册表单（支持 ?invite_code=xxx 打开即带入）
      if (this.inviteCode) {
        this.registerForm.inviteCode = this.inviteCode;
      }

      // 尝试从localStorage恢复openid
      this.wechatOpenid = localStorage.getItem('wechat_openid') || '';

      // 获取服务器配置（is_local）
      this.fetchServerConfig();

      // 获取用户IP地址
      this.fetchUserIp();
      
      // Fetch computing power if logged in
      if (this.authToken) {
        this.fetchComputingPower();
        this.fetchUserRole();
        this.fetchCheckinStatus();
      }
      
      // 检查是否需要自动弹出登录窗口
      // 方式1: 从工作流页面跳转过来（localStorage标记）
      const redirectAfterLogin = localStorage.getItem('redirect_after_login');
      if (redirectAfterLogin && !this.authToken) {
        this.showLoginModal = true;
      }
      
      // 方式2: 通过URL参数触发登录框（支持跨域跳转）
      if (urlParams.get('login') === '1' && !this.authToken) {
        this.showLoginModal = true;
      }
      
      // Load terms of service
      this.loadTermsContent();

      // 监听语言切换事件，重新加载对应语言的服务条款
      this._localeChangedHandler = (data) => {
        this.loadTermsContent();
      };
      if (window.ZJTi18n) {
        window.ZJTi18n.on('locale-changed', this._localeChangedHandler);
      }

      // 设置 axios 响应拦截器，全局处理认证错误
      this._axiosInterceptorId = axios.interceptors.response.use(
        response => response,
        error => {
          // 调用认证错误处理方法
          this.handleAuthError(error);
          // 继续抛出错误，让各个接口的 catch 也能处理
          return Promise.reject(error);
        }
      );

      // 添加管理员快捷键监听 (Ctrl+Shift+A)
      this._adminKeyHandler = (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'A') {
          e.preventDefault();
          this.showAdminSwitchModal = true;
        }
      };
      document.addEventListener('keydown', this._adminKeyHandler);
      
      // 检查是否处于管理员模式
      this.isAdminMode = localStorage.getItem('admin_mode') === 'true';
      
      // 已登录用户检查创作模式
      if (this.authToken && (this.userPhone || this.userEmail)) {
        this.checkCreationMode();
      }
    },
    computed: {
      route(){ return this.$route },
      mainTitle(){
        if (this.route.name === 'list') return (window.__BRANDING_SITE_NAME__ || '智剧通');
        if (this.route.name === 'image-edit') return this.$t('page_title_image_edit');
        if (this.route.name === 'ai-video-gen') return this.$t('page_title_ai_video_gen');
        if (this.route.name === 'image-to-video') return this.$t('page_title_image_to_video');
        if (this.route.name === 'ai-script-gen') return this.$t('page_title_ai_script_gen');
        if (this.route.name === 'video-enhance') return this.$t('page_title_video_enhance');
        if (this.route.name === 'audio-generate') return this.$t('page_title_audio_generate');
        return this.$t('page_title_ai_tools');
      },
      isLoggedIn() {
        return !!(this.authToken && (this.userPhone || this.userEmail));
      },
      /**
       * 实际用于 <img src> 的二维码地址：
       * - 页面为 HTTPS 且配置为 http:// 外链时，走后端同源代理，避免混合内容拦截
       * - 同源相对路径 / http 页面下的 http 图：直接使用
       */
      wxGroupQrDisplayUrl() {
        return this.resolveWxGroupQrDisplayUrl(this.wxGroupQrUrl);
      },
      maskedPhone() {
        // 邮箱用户显示掩码后的邮箱
        if (!this.userPhone && this.userEmail) {
          return this.maskEmail(this.userEmail);
        }
        if (!this.userPhone || this.userPhone.length !== 11) {
          // 如果有邮箱则显示掩码邮箱，否则显示原始值
          return this.userPhone || (this.userEmail ? this.maskEmail(this.userEmail) : '');
        }
        // 管理员模式下显示完整手机号
        if (this.isAdminMode) {
          return '🔧 ' + this.userPhone + ' (管理员模式)';
        }
        // 隐藏中间4位：138****5678
        return this.userPhone.substring(0, 3) + '****' + this.userPhone.substring(7);
      },
      maskedToken() {
        const token = this.apiTokenData.token;
        if (!token || token.length < 10) {
          return token;
        }
        return token.substring(0, 6) + '****' + token.substring(token.length - 4);
      },
      /** 扁平化五槽位，供简洁列表渲染（不展示分组标题 / mode 码） */
      cliMediaPrefFlatSlots() {
        return (this.cliMediaPrefGroups || []).flatMap((group) => group.slots || []);
      },
    },
    watch: {
      showLoginModal(newVal) {
        if (newVal && this.captchaEnabled && this.captchaPrefix) {
          this.$nextTick(() => { this.loadCaptchaSdk(); });
        }
      }
    },
    methods: {
      goHome(){ this.$router.push({name:'list'}); },

      openAgentConnectionModal() {
        // CLI / 智能体连接仅服务故事板（短剧模式），营销模式不提供入口
        if (this.creationMode !== 'short_drama') {
          return;
        }
        this.showAgentConnectionModal = true;
        this.agentConnectionTab = 'connection';
        this.agentConnectionError = '';
        this.agentConnectionCopied = false;
        this.cliMediaPrefError = '';
        this.cliMediaPrefSuccess = '';
        if (!this.isEditionLoaded) {
          this.fetchServerConfig();
        }
      },

      closeAgentConnectionModal() {
        this.showAgentConnectionModal = false;
        this.agentConnectionTab = 'connection';
        this.agentConnectionError = '';
        this.agentConnectionCopied = false;
        this.cliMediaPrefError = '';
        this.cliMediaPrefSuccess = '';
        if (this._cliMediaPrefSuccessTimer) {
          clearTimeout(this._cliMediaPrefSuccessTimer);
          this._cliMediaPrefSuccessTimer = null;
        }
      },

      switchAgentConnectionTab(tab) {
        this.agentConnectionTab = tab;
        if (tab === 'cliMediaPref') {
          this.ensureCliMediaPreferencesLoaded();
        }
      },

      buildAgentConnectionText(data) {
        const payload = {
          skill: 'storyboard-agent-api',
          base_url: data.base_url,
          agent_token: data.agent_token,
          api_version: data.api_version,
          app_version: data.app_version,
          environment: data.environment,
          token_type: data.token_type,
          expires_at: data.expires_at,
          note: 'Use the fixed v1 endpoints documented in the storyboard-agent-api skill. Exchange agent_token for auth_token first, then discover worlds, scripts, characters, locations, props, and storyboard scenes before creating, splitting, generating, or polling storyboard tasks. If using CLI fallback, set comfyui_env to the environment value before running commands.',
        };
        return [
          '请使用 $storyboard-agent-api 协助处理我的智剧通分镜：可查看世界列表、世界下的剧本、主角/角色、场景、道具和分镜场次，并按需创建分镜、拆分剧本、生成分镜图/视频、查询任务状态。',
          '连接信息如下，请不要把 token 放进 URL：',
          '环境说明：请以 JSON 中的 environment 为准；如改用本地 CLI fallback，请先设置 comfyui_env 为该值。',
          JSON.stringify(payload, null, 2),
        ].join('\n');
      },

      async generateAgentConnection() {
        if (!this.authToken) {
          this.agentConnectionError = '请先登录后再生成智能体连接信息';
          return;
        }
        this.agentConnectionLoading = true;
        this.agentConnectionError = '';
        this.agentConnectionCopied = false;
        try {
          const response = await axios.post('/api/agent-auth/storyboard-connection', {}, {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (!response.data || response.data.success === false) {
            this.agentConnectionError = response.data?.error || response.data?.message || '生成连接信息失败';
            return;
          }
          const info = {
            ...response.data,
            base_url: window.location.origin,
          };
          this.agentConnectionInfo = info;
          this.agentConnectionText = this.buildAgentConnectionText(info);
          await this.copyText(this.agentConnectionText);
          this.agentConnectionCopied = true;
          setTimeout(() => { this.agentConnectionCopied = false; }, 3000);
        } catch (error) {
          console.error('Generate agent connection error:', error);
          this.agentConnectionError = error?.response?.data?.error || error?.response?.data?.detail || '生成连接信息失败，请稍后重试';
        } finally {
          this.agentConnectionLoading = false;
        }
      },

      cliAuthHeaders() {
        const headers = {
          'Authorization': `Bearer ${this.authToken}`,
        };
        if (this.userId) {
          headers['X-User-Id'] = String(this.userId);
        }
        return headers;
      },

      formatCliMediaModelLabel(model) {
        if (!model) return '';
        const name = model.name || model.key || '未命名模型';
        const cp = Number(model.computing_power) || 0;
        if (cp <= 0) return name;
        if (model.computing_power_mode === 'by_duration') {
          const range = model.computing_power_range;
          if (Array.isArray(range) && range.length === 2 && range[0] !== range[1]) {
            return `${name}（${range[0]}-${range[1]} 算力）`;
          }
          return `${name}（${cp}+ 算力）`;
        }
        return `${name}（${cp} 算力）`;
      },

      filterCliReferenceModels(models) {
        return (models || []).filter((m) => {
          const modes = m.supported_image_modes || [];
          return modes.includes('multi_reference') || m.supports_ref_audio_video === true;
        });
      },

      buildCliMediaPrefModelsMap(rawModels) {
        const map = {};
        for (const group of this.cliMediaPrefGroups) {
          for (const slot of group.slots) {
            let list = rawModels?.[slot.modelListKey] || rawModels?.[slot.fallbackListKey] || [];
            if (slot.referenceOnly) {
              list = this.filterCliReferenceModels(list);
            }
            map[slot.key] = list;
          }
        }
        return map;
      },

      applyCliMediaPrefProfiles(profiles) {
        const selected = {};
        for (const group of this.cliMediaPrefGroups) {
          for (const slot of group.slots) {
            const profile = profiles?.[slot.key] || {};
            const models = this.cliMediaPrefModels[slot.key] || [];
            let taskId = profile.task_id;
            if (taskId != null && taskId !== '') {
              const exists = models.some((m) => String(m.task_id) === String(taskId));
              if (!exists && models.length) {
                taskId = models[0].task_id;
              }
            } else if (models.length) {
              taskId = models[0].task_id;
            } else {
              taskId = '';
            }
            selected[slot.key] = taskId === '' || taskId == null ? '' : String(taskId);
          }
        }
        this.cliMediaPrefProfiles = profiles || {};
        this.cliMediaPrefSelected = selected;
      },

      async ensureCliMediaPreferencesLoaded() {
        if (!this.authToken) {
          this.cliMediaPrefError = '请先登录后再配置 CLI 模型偏好';
          return;
        }
        if (this.cliMediaPrefLoading) return;
        this.cliMediaPrefLoading = true;
        this.cliMediaPrefError = '';
        try {
          await Promise.all([
            this.loadCliMediaPrefWorlds(),
            this.loadCliMediaPrefModels(),
          ]);
          if (this.cliMediaPrefWorldId) {
            await this.loadCliMediaPreferences(this.cliMediaPrefWorldId);
          }
        } catch (error) {
          console.error('Load CLI media preferences failed:', error);
          this.cliMediaPrefError = error?.message || '加载 CLI 模型偏好失败';
        } finally {
          this.cliMediaPrefLoading = false;
        }
      },

      async loadCliMediaPrefWorlds() {
        const response = await axios.get('/api/worlds?page=1&page_size=100', {
          headers: this.cliAuthHeaders(),
        });
        const payload = response.data || {};
        let worlds = [];
        if (payload.code === 0 && payload.data) {
          worlds = payload.data.data || payload.data.items || payload.data || [];
        } else if (Array.isArray(payload.data)) {
          worlds = payload.data;
        } else if (Array.isArray(payload.items)) {
          worlds = payload.items;
        }
        if (!Array.isArray(worlds)) worlds = [];
        this.cliMediaPrefWorlds = worlds;
        const stored = localStorage.getItem('cli_media_pref_world_id');
        const storedId = stored ? Number(stored) : null;
        const hasStored = worlds.some((w) => Number(w.id) === storedId);
        if (hasStored) {
          this.cliMediaPrefWorldId = storedId;
        } else if (worlds.length) {
          this.cliMediaPrefWorldId = Number(worlds[0].id);
        } else {
          this.cliMediaPrefWorldId = null;
        }
      },

      async loadCliMediaPrefModels() {
        if (this.cliMediaPrefModelsLoaded && this._cliMediaPrefModelsCache) {
          this.cliMediaPrefModels = this.buildCliMediaPrefModelsMap(this._cliMediaPrefModelsCache);
          return;
        }
        const response = await axios.get('/api/storyboard/models', {
          headers: this.cliAuthHeaders(),
        });
        if (!response.data || response.data.success === false) {
          throw new Error(response.data?.error || '加载模型列表失败');
        }
        this._cliMediaPrefModelsCache = response.data;
        this.cliMediaPrefModelsLoaded = true;
        this.cliMediaPrefModels = this.buildCliMediaPrefModelsMap(response.data);
      },

      async loadCliMediaPreferences(worldId) {
        if (!worldId) return;
        const response = await axios.get(
          `/api/storyboard/cli/media-preferences?world_id=${encodeURIComponent(worldId)}`,
          { headers: this.cliAuthHeaders() }
        );
        if (!response.data || response.data.success === false) {
          const err = response.data?.error;
          throw new Error(
            (err && (err.message || err.code)) || response.data?.message || '读取 CLI 偏好失败'
          );
        }
        this.applyCliMediaPrefProfiles(response.data.profiles || {});
        this.cliMediaPrefRowError = {};
        this.cliMediaPrefSaved = {};
      },

      async onCliMediaPrefWorldChange(value) {
        const worldId = value === '' || value == null ? null : Number(value);
        this.cliMediaPrefWorldId = worldId;
        this.cliMediaPrefError = '';
        this.cliMediaPrefSuccess = '';
        if (worldId != null) {
          localStorage.setItem('cli_media_pref_world_id', String(worldId));
        } else {
          localStorage.removeItem('cli_media_pref_world_id');
          this.cliMediaPrefProfiles = {};
          this.cliMediaPrefSelected = {};
          return;
        }
        this.cliMediaPrefLoading = true;
        try {
          await this.loadCliMediaPreferences(worldId);
        } catch (error) {
          console.error('Switch CLI media pref world failed:', error);
          this.cliMediaPrefError = error?.response?.data?.error?.message
            || error?.response?.data?.error
            || error?.message
            || '切换世界失败';
        } finally {
          this.cliMediaPrefLoading = false;
        }
      },

      async onCliMediaPrefModelChange(slot, value) {
        if (!slot || !this.cliMediaPrefWorldId) return;
        const taskId = value === '' || value == null ? null : Number(value);
        if (!taskId) return;
        const previous = this.cliMediaPrefSelected[slot.key];
        this.cliMediaPrefSelected = {
          ...this.cliMediaPrefSelected,
          [slot.key]: String(taskId),
        };
        this.cliMediaPrefSaving = { ...this.cliMediaPrefSaving, [slot.key]: true };
        this.cliMediaPrefRowError = { ...this.cliMediaPrefRowError, [slot.key]: '' };
        this.cliMediaPrefSaved = { ...this.cliMediaPrefSaved, [slot.key]: false };
        try {
          const response = await axios.put(
            '/api/storyboard/cli/media-preferences',
            {
              world_id: this.cliMediaPrefWorldId,
              media_type: slot.mediaType,
              mode: slot.mode,
              profile: { task_id: taskId },
            },
            { headers: this.cliAuthHeaders() }
          );
          if (!response.data || response.data.success === false) {
            const err = response.data?.error;
            throw new Error(
              (typeof err === 'object' ? (err.message || err.code) : err)
              || response.data?.message
              || '保存失败'
            );
          }
          const profile = response.data.profile || { task_id: taskId };
          this.cliMediaPrefProfiles = {
            ...this.cliMediaPrefProfiles,
            [slot.key]: profile,
          };
          this.cliMediaPrefSelected = {
            ...this.cliMediaPrefSelected,
            [slot.key]: String(profile.task_id),
          };
          this.cliMediaPrefSaved = { ...this.cliMediaPrefSaved, [slot.key]: true };
          setTimeout(() => {
            if (this.cliMediaPrefSaved[slot.key]) {
              this.cliMediaPrefSaved = { ...this.cliMediaPrefSaved, [slot.key]: false };
            }
          }, 2000);
        } catch (error) {
          console.error('Save CLI media preference failed:', error);
          this.cliMediaPrefSelected = {
            ...this.cliMediaPrefSelected,
            [slot.key]: previous,
          };
          const msg = error?.response?.data?.error?.message
            || error?.response?.data?.error
            || error?.message
            || '保存失败';
          this.cliMediaPrefRowError = {
            ...this.cliMediaPrefRowError,
            [slot.key]: typeof msg === 'string' ? msg : JSON.stringify(msg),
          };
        } finally {
          this.cliMediaPrefSaving = { ...this.cliMediaPrefSaving, [slot.key]: false };
        }
      },

      buildCliMediaPrefCommands() {
        const userId = this.userId || '<user_id>';
        const worldId = this.cliMediaPrefWorldId || '<world_id>';
        const lines = [];
        for (const group of this.cliMediaPrefGroups) {
          for (const slot of group.slots) {
            const taskId = this.cliMediaPrefSelected[slot.key];
            if (!taskId) continue;
            lines.push(
              `python scripts/storyboard_agent_cli.py preference media set --user-id ${userId} --world-id ${worldId} --media-type ${slot.mediaType} --mode ${slot.mode} --task-id ${taskId}`
            );
          }
        }
        return lines.join('\n');
      },

      async copyCliMediaPrefCommands() {
        const text = this.buildCliMediaPrefCommands();
        if (!text) {
          this.cliMediaPrefError = '当前没有可复制的偏好配置';
          return;
        }
        try {
          await this.copyText(text);
          this.cliMediaPrefError = '';
          this.cliMediaPrefSuccess = '已复制 CLI 设置命令到剪贴板';
          if (this._cliMediaPrefSuccessTimer) {
            clearTimeout(this._cliMediaPrefSuccessTimer);
          }
          this._cliMediaPrefSuccessTimer = setTimeout(() => {
            this.cliMediaPrefSuccess = '';
            this._cliMediaPrefSuccessTimer = null;
          }, 3000);
        } catch (error) {
          this.cliMediaPrefError = '复制失败，请手动选择文本';
        }
      },

      async copyText(text) {
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          try {
            await navigator.clipboard.writeText(text);
            return;
          } catch (err) {
            console.warn('Clipboard API failed, fallback copy will be used', err);
          }
        }
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
          document.execCommand('copy');
        } finally {
          document.body.removeChild(textarea);
        }
      },
      
      maskEmail(email) {
        if (!email || !email.includes('@')) return email || '';
        const [local, domain] = email.split('@');
        if (local.length <= 2) {
          return local[0] + '***@' + domain;
        }
        return local.substring(0, 2) + '***@' + domain;
      },
      
      handleAuthError(error) {
        // 检查错误响应中是否包含认证过期信息
        const detail = error?.response?.data?.detail || '';
        if (detail.includes('无效或已过期的认证信息')) {
          // 清除本地存储的认证信息
          localStorage.removeItem('auth_token');
          localStorage.removeItem('phone');
          localStorage.removeItem('email');
          localStorage.removeItem('user_id');
          localStorage.removeItem('invite_code');
          
          // 清除当前状态
          this.authToken = '';
          this.userPhone = '';
          this.userEmail = '';
          this.userId = '';
          this.inviteCode = '';
          this.computingPower = null;
          this.userRole = '';
          
          // 设置错误信息并显示登录框
          this.loginError = '登录已过期，请重新登录';
          this.showLoginModal = true;
          this.authMode = 'login';
          
          return true; // 表示已处理该错误
        }
        return false; // 表示不是认证错误
      },
      
      switchAuthMode(mode) {
        this.authMode = mode;
        this.loginError = '';
        this.registerError = '';
        this.resetError = '';
      },
      
      closeModal() {
        this.showLoginModal = false;
        this.authMode = 'login';
        this.loginError = '';
        this.registerError = '';
        this.resetError = '';
        this.loginForm.phone = '';
        this.loginForm.password = '';
        this.loginForm.termsAgreed = false;
        this.loginShowTerms = false;
        this.registerForm.phone = '';
        this.registerForm.email = '';
        this.registerForm.code = '';
        this.registerForm.password = '';
        this.registerForm.inviteCode = this.inviteCode || '';
        this.registerForm.termsAgreed = false;
        this.registerType = 'phone';
        this.resetForm.phone = '';
        this.resetForm.email = '';
        this.resetForm.code = '';
        this.resetForm.newPassword = '';
        this.resetForm.confirmPassword = '';
        this.resetType = 'phone';
        this.captchaAction = null;
        this.captchaVerifyParam = null;
        this._pendingSendPayload = null;
      },
      
      async handleLogin() {
        this.loginError = '';
        this.loginLoading = true;
        try {
          // 验证输入
          if (!this.loginForm.phone || !this.loginForm.password) {
            this.loginError = this.emailEnabled ? '请输入手机号/邮箱和密码' : '请输入手机号和密码';
            this.loginLoading = false;
            return;
          }
          
          // 判断是手机号还是邮箱
          const identifier = this.loginForm.phone;
          const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(identifier);
          const isPhone = /^1[3-9]\d{9}$/.test(identifier);
          
          // 邮箱功能关闭时，不允许邮箱登录
          if (isEmail && !this.emailEnabled) {
            this.loginError = '邮箱登录未启用，请使用手机号登录';
            this.loginLoading = false;
            return;
          }
          
          if (!isEmail && !isPhone) {
            this.loginError = this.emailEnabled ? '请输入正确的手机号或邮箱地址' : '请输入正确的手机号';
            this.loginLoading = false;
            return;
          }
          
          // 构建登录参数
          const loginPayload = {
            password: this.loginForm.password,
            agent: 'default',
            terms_agreed: this.loginForm.termsAgreed ? 1 : 0
          };
          if (isEmail) {
            loginPayload.email = identifier;
          } else {
            loginPayload.phone = identifier;
          }
          
          // 调用登录 API
          const response = await axios.post('/api/auth/login', loginPayload);
          
          if (response.data.success) {
            // 登录成功，先清除旧数据，再保存新 token
            if (response.data.data && response.data.data.token) {
              // 清除旧的登录数据
              localStorage.removeItem('auth_token');
              localStorage.removeItem('phone');
              localStorage.removeItem('user_id');
              localStorage.removeItem('invite_code');
              
              this.authToken = response.data.data.token;
              this.userPhone = response.data.data.phone || '';
              this.userEmail = response.data.data.email || '';
              this.userId = response.data.data.user_id;
              this.inviteCode = response.data.data.invite_code;
              localStorage.setItem('auth_token', this.authToken);
              localStorage.setItem('phone', this.userPhone);
              localStorage.setItem('email', this.userEmail);
              localStorage.setItem('user_id', this.userId);
              localStorage.setItem('invite_code', this.inviteCode);

              await Promise.all([
                this.fetchComputingPower(),
                this.fetchUserRole(),
                this.fetchCheckinStatus()
              ]);
              
              // 检查是否需要跳转回原页面（仅允许相对路径，防止开放重定向）
              const redirectUrl = localStorage.getItem('redirect_after_login');
              if(redirectUrl && redirectUrl.startsWith('/') && !redirectUrl.includes('://') && !redirectUrl.includes('//')){
                localStorage.removeItem('redirect_after_login');
                window.location.href = redirectUrl;
                return;
              } else if(redirectUrl){
                localStorage.removeItem('redirect_after_login');
              }
              
              // 登录成功后留在首页，检查模式选择
              this.checkCreationMode();
              // 注册后的官方微信群轻量引导（不阻塞主路径）
              this.maybeShowWxGroupSoftGuide();
            }
            
            // 关闭模态框并清空表单
            this.closeModal();
            
          } else {
            this.loginError = response.data.message || '登录失败';
          }
          
        } catch (error) {
          console.error('Login error:', error);
          this.loginError = error?.response?.data?.message || '登录失败，请重试';
          if (this.loginError === '请阅读并同意AI工具服务使用条款') {
              this.loginShowTerms = true;
              this.loginLoading = false;
              return;
          }
        } finally {
          this.loginLoading = false;
        }
      },
      
      async sendVerificationCode() {
        this.registerError = '';
        
        // 根据注册类型验证
        if (this.registerType === 'email') {
          if (!this.registerForm.email) {
            this.registerError = '请输入邮箱';
            return;
          }
          if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.registerForm.email)) {
            this.registerError = '请输入正确的邮箱地址';
            return;
          }
        } else {
          if (!this.registerForm.phone) {
            this.registerError = '请输入手机号';
            return;
          }
          if (!/^1[3-9]\d{9}$/.test(this.registerForm.phone)) {
            this.registerError = '请输入正确的手机号';
            return;
          }
        }
        
        // 构建请求参数
        const sendPayload = { type: 'register', agent: 'default' };
        if (this.registerType === 'email') {
          sendPayload.email = this.registerForm.email;
        } else {
          sendPayload.phone = this.registerForm.phone;
        }
        
        // 邮箱模式 + CAPTCHA 启用：触发人机验证
        if (this.registerType === 'email' && this.captchaEnabled && this.captchaPrefix) {
          this.triggerCaptchaForEmail('register_code', sendPayload);
          return;
        }
        
        this.codeSending = true;
        
        try {
          // 调用发送验证码 API
          const response = await axios.post('/api/auth/send_verify_code', sendPayload);
          
          if (response.data.success) {
            // 开始倒计时
            this.codeCountdown = 60;
            this.countdownTimer = setInterval(() => {
              this.codeCountdown--;
              if (this.codeCountdown <= 0) {
                clearInterval(this.countdownTimer);
                this.countdownTimer = null;
              }
            }, 1000);
          } else {
            this.registerError = response.data.message || '发送验证码失败';
          }
          
        } catch (error) {
          console.error('Send code error:', error);
          this.registerError = error?.response?.data?.message || '发送验证码失败，请重试';
        } finally {
          this.codeSending = false;
        }
      },
      
      async handleRegister() {
        this.registerError = '';
        this.registerLoading = true;
        
        try {
          // 根据注册类型验证
          if (this.registerType === 'email') {
            if (!this.registerForm.email || !this.registerForm.code || !this.registerForm.password) {
              this.registerError = '请填写完整信息';
              this.registerLoading = false;
              return;
            }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.registerForm.email)) {
              this.registerError = '请输入正确的邮箱地址';
              this.registerLoading = false;
              return;
            }
          } else {
            if (!this.registerForm.phone || !this.registerForm.code || !this.registerForm.password) {
              this.registerError = '请填写完整信息';
              this.registerLoading = false;
              return;
            }
            if (!/^1[3-9]\d{9}$/.test(this.registerForm.phone)) {
              this.registerError = '请输入正确的手机号';
              this.registerLoading = false;
              return;
            }
          }
          
          if (!this.registerForm.termsAgreed) {
            this.registerError = '请勾选《AI工具服务使用条款》';
            this.registerLoading = false;
            return;
          }
          
          // 验证密码长度
          if (this.registerForm.password.length < 6) {
            this.registerError = '密码长度不能少于6位';
            this.registerLoading = false;
            return;
          }
          
          // 构建注册参数
          const registerPayload = {
            code: this.registerForm.code,
            password: this.registerForm.password,
            agent: 'default',
            invite_code: this.registerForm.inviteCode || undefined
          };
          if (this.registerType === 'email') {
            registerPayload.email = this.registerForm.email;
          } else {
            registerPayload.phone = this.registerForm.phone;
          }
          
          // 调用注册 API
          const response = await axios.post('/api/auth/register', registerPayload);
          
          if (response.data.success) {
            // 检查是否需要管理员审核
            const pendingApproval = response.data.data && response.data.data.pending_approval;
            if (pendingApproval) {
              // 待审核：提示用户并切换到登录表单
              this.registerError = '';
              this.authMode = 'login';
              this.showLoginModal = true;
              this.loginForm.phone = this.registerForm.phone || this.registerForm.email;
              this.registerForm = { phone: '', email: '', code: '', password: '', inviteCode: '', termsAgreed: false };
              const pendingMsg = response.data.message || '注册成功，请等待管理员审核通过后登录';
              // 功能开启时附带可点的社群提示（不自动弹窗）
              if (this.wxGroupGuideEnabled) {
                const joinTip = this.$t ? this.$t('wx_group_pending_tip') : '也可先加入官方微信群了解产品';
                alert(`${pendingMsg}\n\n${joinTip}`);
              } else {
                alert(pendingMsg);
              }
              return;
            }

            // 检查是否是首个管理员
            const isFirstAdmin = response.data.data && response.data.data.is_first_admin;
            if (isFirstAdmin) {
              // 保存标记，登录后跳转到快速配置（主路径优先，不挡后台）
              localStorage.setItem('redirect_after_login', '/admin?quick_config=1');
              // 首管：配置完成后再在 admin 手册弹窗中展示微信群（展示时再校验开关）
              sessionStorage.setItem('pending_wx_group_guide', 'admin_after_config');
            } else {
              // 普通用户：登录进首页后展示轻量浮层（展示时再校验开关）
              sessionStorage.setItem('pending_wx_group_guide', 'home_soft');
            }

            // 注册成功后自动登录
            this.showLoginModal = true;
            this.authMode = 'login';
            this.loginShowTerms = true;
            this.loginForm.phone = this.registerForm.phone || this.registerForm.email;
            this.loginForm.password = this.registerForm.password;
            this.loginForm.termsAgreed = true;
            await this.handleLogin();
          } else {
            this.registerError = response.data.message || '注册失败';
          }
          
        } catch (error) {
          console.error('Register error:', error);
          this.registerError = error?.response?.data?.message || '注册失败，请重试';
        } finally {
          this.registerLoading = false;
        }
      },
      
      async handleLogout() {
        try {
          // 调用后端登出API
          const response = await axios.post('/api/auth/logout', {
            auth_token: this.authToken
          });
          
          if (response.data.success) {
            // 登出成功，清除登录状态
            this.authToken = '';
            this.userPhone = '';
            this.userEmail = '';
            this.computingPower = null;
            this.userRole = '';
            this.inviteCode = '';
            localStorage.removeItem('auth_token');
            localStorage.removeItem('phone');
            localStorage.removeItem('email');
            localStorage.removeItem('user_id');
            localStorage.removeItem('invite_code');
            localStorage.removeItem('admin_mode');
            this.isAdminMode = false;
          } else {
            // 即使后端登出失败，也清除本地状态
            console.error('Logout error:', response.data.message);
            this.authToken = '';
            this.userPhone = '';
            this.userEmail = '';
            this.computingPower = null;
            this.userRole = '';
            this.inviteCode = '';
            localStorage.removeItem('auth_token');
            localStorage.removeItem('phone');
            localStorage.removeItem('email');
            localStorage.removeItem('user_id');
            localStorage.removeItem('invite_code');
            localStorage.removeItem('admin_mode');
            this.isAdminMode = false;
          }
        } catch (error) {
          console.error('Logout error:', error);
          // 发生错误时也清除本地状态
          this.authToken = '';
          this.userPhone = '';
          this.userEmail = '';
          this.computingPower = null;
          this.userRole = '';
          localStorage.removeItem('auth_token');
          localStorage.removeItem('phone');
          localStorage.removeItem('email');
          localStorage.removeItem('user_id');
          localStorage.removeItem('invite_code');
          localStorage.removeItem('admin_mode');
          this.isAdminMode = false;
        }
      },

      // ==================== 用户设置方法 ====================

      showUserSettingsModal() {
        this.showUserSettingsModalFlag = true;
        this.userSettingsError = '';
        this.userSettingsSuccess = '';
        this.userSettingsTab = 'preferences';
        this.apiTokenNewToken = '';
        this.apiTokenError = '';
        this.loadImplementationPreferences();
      },

      switchToApiTokenTab() {
        this.userSettingsTab = 'apitoken';
        this.apiTokenError = '';
        this.apiTokenNewToken = '';
        this.loadApiToken();
      },

      closeUserSettingsModal() {
        this.showUserSettingsModalFlag = false;
        this.userSettingsError = '';
        this.userSettingsSuccess = '';
      },

      async loadImplementationPreferences() {
        this.userSettingsLoading = true;
        this.userSettingsError = '';

        try {
          const response = await axios.get('/api/user/implementation-preferences', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.code === 0) {
            this.userPreferences = response.data.data.preferences || {};
            this.availableImplementations = response.data.data.available_implementations || {};
            this.isCommunityEdition = response.data.data.is_community_edition || false;
            this.isEditionLoaded = true;
          } else {
            this.userSettingsError = response.data.message || '加载偏好设置失败';
          }
        } catch (error) {
          console.error('Load implementation preferences error:', error);
          this.userSettingsError = error?.response?.data?.detail || '加载偏好设置失败，请重试';
        } finally {
          this.userSettingsLoading = false;
        }

        // 单独获取智剧通Token配置
        this.loadZjtTokenConfig();
      },

      async loadZjtTokenConfig() {
        try {
          const response = await axios.get('/api/user/zjt-token-config', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.code === 0) {
            this.zjtTokenEnabled = response.data.data.enabled || false;
          }
        } catch (error) {
          console.error('Load ZJT token config error:', error);
          this.zjtTokenEnabled = false;
        }
      },

      async handlePreferenceChange(taskKey) {
        const implementation = this.userPreferences[taskKey];
        this.userSettingsError = '';
        this.userSettingsSuccess = '';

        try {
          if (implementation) {
            // 设置偏好
            const response = await axios.put('/api/user/implementation-preference', {
              task_key: taskKey,
              implementation_name: implementation
            }, {
              headers: {
                'Authorization': `Bearer ${this.authToken}`
              }
            });

            if (response.data.code === 0) {
              this.userSettingsSuccess = '偏好设置已保存';
              setTimeout(() => { this.userSettingsSuccess = ''; }, 2000);
            } else {
              this.userSettingsError = response.data.message || '保存失败';
            }
          } else {
            // 清除偏好
            const response = await axios.delete('/api/user/implementation-preference', {
              params: { task_key: taskKey },
              headers: {
                'Authorization': `Bearer ${this.authToken}`
              }
            });

            if (response.data.code === 0) {
              this.userSettingsSuccess = '已恢复默认设置';
              setTimeout(() => { this.userSettingsSuccess = ''; }, 2000);
            } else {
              this.userSettingsError = response.data.message || '清除失败';
            }
          }
        } catch (error) {
          console.error('Save implementation preference error:', error);
          this.userSettingsError = error?.response?.data?.detail || '保存失败，请重试';
        }
      },

      // ==================== API Token 方法 ====================

      async loadApiToken() {
        console.log('loadApiToken called');
        this.apiTokenLoading = true;
        this.apiTokenError = '';
        this.apiTokenNewToken = '';
        console.log('apiTokenLoading set to true');

        try {
          console.log('Making request to /api/user/api-token');
          const response = await axios.get('/api/user/api-token', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          console.log('Response received:', response.data);
          if (response.data.code === 0) {
            this.apiTokenData = response.data.data || { has_token: false, token: '' };
            console.log('apiTokenData updated:', this.apiTokenData);
          } else {
            this.apiTokenError = response.data.detail || '加载Token失败';
            console.log('Error set:', this.apiTokenError);
          }
        } catch (error) {
          console.error('Load API token error:', error);
          this.apiTokenError = error?.response?.data?.detail || '加载Token失败';
        } finally {
          this.apiTokenLoading = false;
          console.log('apiTokenLoading set to false');
        }
      },

      confirmRegenerateToken() {
        if (confirm('重新生成Token将导致当前Token失效，确定要继续吗？')) {
          this.generateApiToken();
        }
      },

      async generateApiToken() {
        this.apiTokenLoading = true;
        this.apiTokenError = '';
        this.apiTokenNewToken = '';

        try {
          const response = await axios.post('/api/user/api-token', {}, {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.code === 0) {
            this.apiTokenNewToken = response.data.data.token;
            this.apiTokenData.has_token = true;
            this.apiTokenData.token = response.data.data.token;
          } else {
            this.apiTokenError = response.data.detail || '生成Token失败';
          }
        } catch (error) {
          console.error('Generate API token error:', error);
          this.apiTokenError = error?.response?.data?.detail || '生成Token失败';
        } finally {
          this.apiTokenLoading = false;
        }
      },

      async deleteApiToken() {
        this.apiTokenLoading = true;
        this.apiTokenError = '';

        try {
          const response = await axios.delete('/api/user/api-token', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.code === 0) {
            this.apiTokenData = { has_token: false, masked_token: '' };
            this.apiTokenNewToken = '';
          } else {
            this.apiTokenError = response.data.detail || '删除Token失败';
          }
        } catch (error) {
          console.error('Delete API token error:', error);
          this.apiTokenError = error?.response?.data?.detail || '删除Token失败';
        } finally {
          this.apiTokenLoading = false;
        }
      },

      copyApiToken() {
        const textToCopy = this.apiTokenNewToken || this.apiTokenData.token;
        if (!textToCopy) {
          this.apiTokenError = '没有可复制的Token';
          setTimeout(() => { this.apiTokenError = ''; }, 2000);
          return;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(textToCopy).then(() => {
            this.userSettingsSuccess = 'Token已复制到剪贴板';
            setTimeout(() => { this.userSettingsSuccess = ''; }, 3000);
          }).catch(err => {
            console.error('Copy failed:', err);
            this.fallbackCopyApiToken(textToCopy);
          });
        } else {
          this.fallbackCopyApiToken(textToCopy);
        }
      },

      fallbackCopyApiToken(textToCopy) {
        const textarea = document.createElement('textarea');
        textarea.value = textToCopy;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
          document.execCommand('copy');
          this.userSettingsSuccess = 'Token已复制到剪贴板';
          setTimeout(() => { this.userSettingsSuccess = ''; }, 3000);
        } catch (err) {
          console.error('Fallback copy failed:', err);
          this.apiTokenError = '复制失败，请手动复制';
          setTimeout(() => { this.apiTokenError = ''; }, 2000);
        }
        document.body.removeChild(textarea);
      },

      // 演示数据生成方法（仅社区版使用）
      getDemoSuccessRate(index) {
        const rates = [95, 92, 88, 85, 78, 75, 70];
        return rates[index % rates.length];
      },

      getDemoAvgTime(index) {
        const times = ['45秒', '1分12秒', '1分35秒', '2分8秒', '2分45秒', '3分20秒', '4分15秒'];
        return times[index % times.length];
      },

      // 获取真实成功率（商业版）
      getRealSuccessRate(impl) {
        if (!impl.stats || impl.stats.total_count === 0 || impl.stats.success_rate == null) {
          return '暂无数据';
        }
        return impl.stats.success_rate.toFixed(1);
      },

      // 获取真实平均时间（商业版）
      getRealAvgTime(impl) {
        if (!impl.stats || impl.stats.total_count === 0 || impl.stats.avg_duration_ms == null) {
          return '暂无数据';
        }
        return this.formatDuration(impl.stats.avg_duration_ms);
      },

      // 格式化时长（毫秒转为可读格式）
      formatDuration(ms) {
        if (!ms || ms === 0) return '0秒';
        const seconds = Math.floor(ms / 1000);
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        
        if (minutes > 0) {
          return remainingSeconds > 0 ? `${minutes}分${remainingSeconds}秒` : `${minutes}分钟`;
        }
        return `${seconds}秒`;
      },

      // 获取显示的成功率（自动区分社区版和商业版）
      getDisplaySuccessRate(impl, index) {
        if (this.isCommunityEdition) {
          return this.getDemoSuccessRate(index);
        }
        return this.getRealSuccessRate(impl);
      },

      // 获取显示的平均时间（自动区分社区版和商业版）
      getDisplayAvgTime(impl, index) {
        if (this.isCommunityEdition) {
          return this.getDemoAvgTime(index);
        }
        return this.getRealAvgTime(impl);
      },

      getSuccessRateColor(rate) {
        // 处理"暂无数据"等非数字字符串
        if (typeof rate === 'string' && isNaN(parseFloat(rate))) return 'var(--muted)';
        // 将字符串数字转换为数值
        const numRate = typeof rate === 'string' ? parseFloat(rate) : rate;
        if (numRate >= 90) return '#10b981';
        if (numRate >= 70) return '#3b82f6';
        if (numRate >= 50) return '#f59e0b';
        return '#ef4444';
      },

      // 获取平均时间颜色（商业版）
      getAvgTimeColor(impl) {
        if (this.isCommunityEdition) return 'var(--muted)';
        if (!impl.stats || impl.stats.total_count === 0) return 'var(--muted)';
        const seconds = impl.stats.avg_duration_ms / 1000;
        if (seconds <= 30) return '#10b981';  // 快速 - 绿色
        if (seconds <= 60) return '#3b82f6';   // 正常 - 蓝色
        if (seconds <= 120) return '#f59e0b';  // 较慢 - 橙色
        return '#ef4444';                        // 很慢 - 红色
      },

      closeAdminSwitchModal() {
        this.showAdminSwitchModal = false;
        this.adminSwitchToken = '';
        this.adminSwitchPhone = '';
        this.adminSwitchUserId = '';
        this.adminSwitchError = '';
        this.adminSwitchSuccess = '';
      },
      
      handleAdminSwitchUser() {
        this.adminSwitchError = '';
        this.adminSwitchSuccess = '';
        
        const token = this.adminSwitchToken.trim();
        const phone = this.adminSwitchPhone.trim();
        const userId = this.adminSwitchUserId.trim();
        
        if (!token) {
          this.adminSwitchError = '请输入用户token';
          return;
        }
        
        if (!phone) {
          this.adminSwitchError = '请输入用户手机号';
          return;
        }
        
        // 验证手机号格式
        if (!/^1[3-9]\d{9}$/.test(phone)) {
          this.adminSwitchError = '请输入正确的手机号格式';
          return;
        }
        
        this.adminSwitchLoading = true;
        
        // 清除旧的登录数据
        localStorage.removeItem('auth_token');
        localStorage.removeItem('phone');
        localStorage.removeItem('user_id');
        localStorage.removeItem('invite_code');
        
        // 保存新的用户信息
        this.authToken = token;
        this.userPhone = phone;
        this.userId = userId || '';
        
        localStorage.setItem('auth_token', token);
        localStorage.setItem('phone', phone);
        if (userId) {
          localStorage.setItem('user_id', userId);
        }
        localStorage.setItem('admin_mode', 'true');
        this.isAdminMode = true;
        
        this.adminSwitchSuccess = '切换成功！页面即将刷新...';
        
        // 延迟刷新页面
        setTimeout(() => {
          window.location.reload();
        }, 800);
      },
      
      async fetchComputingPower() {
        if (!this.authToken) {
          return;
        }
        
        try {
          const response = await axios.get('/api/user/computing_power', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.success) {
            this.computingPower = response.data.data.computing_power;
          } else {
            console.log("Computing power response:", response.data.message);
            if (response.data.message === '无效或已过期的认证信息') {
              this.computingPower = null;
              alert('登录过期，请重新登录');
            } else {
              this.computingPower = 0;
              console.error('Failed to fetch computing power:', response.data.message);
            }
          }
        } catch (error) {
          console.error('Fetch computing power error:', error);
          if (!this.handleAuthError(error)) {
            this.computingPower = 0;
          }
        }
      },
      
      async fetchCheckinStatus() {
        if (!this.authToken) return;
        try {
          const response = await axios.get('/api/user/checkin/status', {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.success) {
            this.checkinStatus = response.data.data;
          }
        } catch (error) {
          if (error.response && error.response.status === 403) {
            this.checkinStatus.checkin_enabled = false;
          }
          console.error('Fetch checkin status error:', error);
        }
      },

      async performCheckin() {
        if (!this.authToken || this.checkinLoading) return;
        this.checkinLoading = true;
        try {
          const response = await axios.post('/api/user/checkin', {}, {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.success) {
            const data = response.data.data;
            this.checkinStatus.checked_in_today = true;
            this.checkinStatus.streak_days = data.streak_days;
            // 刷新算力
            this.fetchComputingPower();
            // 显示 Toast
            const nextRewardText = (this.checkinStatus.days_to_next_reward)
              ? `再签${this.checkinStatus.days_to_next_reward}天领${this.checkinStatus.next_reward_amount}算力`
              : '';
            this.checkinToast = {
              show: true,
              reward: data.reward_amount,
              streak_days: data.streak_days,
              nextRewardText: nextRewardText
            };
            if (this.checkinToastTimer) clearTimeout(this.checkinToastTimer);
            this.checkinToastTimer = setTimeout(() => {
              this.checkinToast.show = false;
            }, 3000);
          } else {
            alert(response.data.message || '签到失败');
            if (response.data.data && response.data.data.checked_in_today) {
              this.checkinStatus.checked_in_today = true;
            }
          }
        } catch (error) {
          console.error('Checkin error:', error);
          if (!this.handleAuthError(error)) {
            alert('签到请求失败，请稍后重试');
          }
        } finally {
          this.checkinLoading = false;
        }
      },

      async fetchUserRole() {
        if (!this.authToken) {
          this.userRole = '';
          return;
        }
        
        try {
          const response = await axios.get('/api/user/role', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.code === 0) {
            this.userRole = response.data.data.role || '';
          }
        } catch (error) {
          console.error('Fetch user role error:', error);
          this.userRole = '';
        }
      },
      
      async fetchInvitationInfo() {
        if (!this.authToken) {
          return;
        }
        
        try {
          const response = await axios.get('/api/user/invitation_info', {
            headers: {
              'Authorization': `Bearer ${this.authToken}`
            }
          });
          if (response.data.success) {
            this.invitationStats = response.data.data;
          } else {
            console.error('Failed to fetch invitation info:', response.data.message);
            this.invitationStats = null;
          }
        } catch (error) {
          console.error('Fetch invitation info error:', error);
          this.invitationStats = null;
        }
      },

      // ===== 佣金中心（商业版）=====
      async fetchCommissionInfo() {
        if (!this.authToken) return;
        await Promise.all([
          this.fetchCommissionSummary(),
          this.fetchCommissionRate(),
          this.fetchCommissionRecords(),
          this.fetchCommissionWithdrawals()
        ]);
      },

      async fetchCommissionSummary() {
        if (!this.authToken) return;
        try {
          const response = await axios.get('/api/commission/summary', {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.commissionSummary = response.data.data;
            this.showCommission = true;
          } else {
            this.showCommission = false;
          }
        } catch (error) {
          // 社区版/未启用 -> 403，隐藏佣金区块
          this.showCommission = false;
        }
      },

      async fetchCommissionRecords() {
        if (!this.authToken) return;
        try {
          const response = await axios.get('/api/commission/records?page=1&page_size=20', {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.commissionRecords = (response.data.data && response.data.data.records) || [];
          }
        } catch (error) {
          // 忽略
        }
      },

      async fetchCommissionWithdrawals() {
        if (!this.authToken) return;
        try {
          const response = await axios.get('/api/commission/withdrawals?page=1&page_size=20', {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.commissionWithdrawals = (response.data.data && response.data.data.withdrawals) || [];
          }
        } catch (error) {
          // 忽略
        }
      },

      async fetchCommissionRate() {
        if (!this.authToken) return;
        try {
          const response = await axios.get('/api/commission/rate', {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.commissionRate = response.data.data.rate || 0;
            this.commissionRateInput = Math.round(this.commissionRate * 100);
            // 动态获取管理员设置的上限（百分比整数）
            if (response.data.data.max_rate != null) {
              this.maxCommissionRate = Math.round(response.data.data.max_rate * 100);
            }
          }
        } catch (error) {
          // 忽略
        }
      },

      async saveCommissionRate() {
        if (!this.authToken) return;
        // 确保不超过上限
        if (this.commissionRateInput > this.maxCommissionRate) {
          this.commissionRateInput = this.maxCommissionRate;
        }
        this.commissionSaving = true;
        try {
          const rate = (Number(this.commissionRateInput) / 100).toFixed(2);
          const response = await axios.put('/api/commission/rate?rate=' + rate, null, {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.commissionRate = response.data.data.rate;
            this.commissionRateInput = Math.round(this.commissionRate * 100);
            alert('佣金比例已保存：' + this.commissionRateInput + '%');
          } else {
            alert(response.data.detail || response.data.message || '保存失败');
          }
        } catch (error) {
          alert(error?.response?.data?.detail || '保存失败');
        } finally {
          this.commissionSaving = false;
        }
      },

      openWithdrawForm() {
        const available = Number(this.commissionSummary.available || 0);
        if (available < 10) {
          alert('可提现佣金不满 ¥10，暂无法提现');
          return;
        }
        this.showWithdrawForm = true;
      },

      async submitWithdraw() {
        if (!this.authToken) return;
        const f = this.withdrawForm;
        // 前端基础校验（后端也会校验）
        if (f.method === 'alipay' && !f.alipay_account) { alert('请填写支付宝账号'); return; }
        if (f.method === 'bank' && !(f.bank_card_no && f.bank_account_name && f.bank_name)) {
          alert('请完整填写银行卡号、开户姓名、开户银行'); return;
        }
        const available = Number(this.commissionSummary.available || 0);
        if (!confirm('确认提现 ¥' + available.toFixed(2) + ' 到您填写的'
          + (f.method === 'alipay' ? '支付宝' : '银行卡') + '？\n申请后进入管理员审核。')) return;
        this.commissionWithdrawing = true;
        try {
          const response = await axios.post('/api/commission/withdraw', f, {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            alert('提现申请已提交，单号：' + response.data.data.withdraw_no +
                  '，金额 ¥' + Number(response.data.data.amount).toFixed(2) + '，等待审核。');
            this.showWithdrawForm = false;
            // 重置表单
            this.withdrawForm = { method: 'alipay', alipay_account: '', bank_card_no: '', bank_account_name: '', bank_name: '', apply_note: '' };
            this.fetchCommissionSummary();
            this.fetchCommissionWithdrawals();
          } else {
            alert(response.data.detail || response.data.message || '提现失败');
          }
        } catch (error) {
          alert(error?.response?.data?.detail || '提现失败');
        } finally {
          this.commissionWithdrawing = false;
        }
      },
      
      async sendResetCode() {
        this.resetError = '';
        
        // 根据重置类型验证
        if (this.resetType === 'email') {
          if (!this.resetForm.email) {
            this.resetError = '请输入邮箱';
            return;
          }
          if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.resetForm.email)) {
            this.resetError = '请输入正确的邮箱地址';
            return;
          }
        } else {
          if (!this.resetForm.phone) {
            this.resetError = '请输入手机号';
            return;
          }
          if (!/^1[3-9]\d{9}$/.test(this.resetForm.phone)) {
            this.resetError = '请输入正确的手机号';
            return;
          }
        }
        
        // 构建请求参数
        const sendPayload = { type: 'reset_password', agent: 'default' };
        if (this.resetType === 'email') {
          sendPayload.email = this.resetForm.email;
        } else {
          sendPayload.phone = this.resetForm.phone;
        }
        
        // 邮箱模式 + CAPTCHA 启用：触发人机验证
        if (this.resetType === 'email' && this.captchaEnabled && this.captchaPrefix) {
          this.triggerCaptchaForEmail('reset_code', sendPayload);
          return;
        }
        
        this.resetCodeSending = true;
        
        try {
          // 调用发送验证码 API
          const response = await axios.post('/api/auth/send_verify_code', sendPayload);
          
          if (response.data.success) {
            // 开始倒计时
            this.resetCodeCountdown = 60;
            this.resetCountdownTimer = setInterval(() => {
              this.resetCodeCountdown--;
              if (this.resetCodeCountdown <= 0) {
                clearInterval(this.resetCountdownTimer);
                this.resetCountdownTimer = null;
              }
            }, 1000);
          } else {
            this.resetError = response.data.message || '发送验证码失败';
          }
          
        } catch (error) {
          console.error('Send reset code error:', error);
          this.resetError = error?.response?.data?.message || '发送验证码失败，请重试';
        } finally {
          this.resetCodeSending = false;
        }
      },
      
      async handleResetPassword() {
        this.resetError = '';
        this.resetLoading = true;
        
        try {
          // 根据重置类型验证
          const hasIdentifier = this.resetType === 'email' ? this.resetForm.email : this.resetForm.phone;
          if (!hasIdentifier || !this.resetForm.code || 
              !this.resetForm.newPassword || !this.resetForm.confirmPassword) {
            this.resetError = '请填写完整信息';
            this.resetLoading = false;
            return;
          }
          
          if (this.resetType === 'email') {
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.resetForm.email)) {
              this.resetError = '请输入正确的邮箱地址';
              this.resetLoading = false;
              return;
            }
          } else {
            if (!/^1[3-9]\d{9}$/.test(this.resetForm.phone)) {
              this.resetError = '请输入正确的手机号';
              this.resetLoading = false;
              return;
            }
          }
          
          // 验证密码长度
          if (this.resetForm.newPassword.length < 6) {
            this.resetError = '密码长度不能少于6位';
            this.resetLoading = false;
            return;
          }
          
          // 验证两次密码是否一致
          if (this.resetForm.newPassword !== this.resetForm.confirmPassword) {
            this.resetError = '两次输入的密码不一致';
            this.resetLoading = false;
            return;
          }
          
          // 构建重置密码参数
          const resetPayload = {
            code: this.resetForm.code,
            new_password: this.resetForm.newPassword
          };
          if (this.resetType === 'email') {
            resetPayload.email = this.resetForm.email;
          } else {
            resetPayload.phone = this.resetForm.phone;
          }
          
          // 调用重置密码 API
          const response = await axios.post('/api/auth/reset_password', resetPayload);
          
          if (response.data.success) {
            // 重置密码成功
            this.closeModal();
            alert('密码重置成功，请使用新密码登录！');
            // 切换到登录模式
            this.authMode = 'login';
          } else {
            this.resetError = response.data.message || '重置密码失败';
          }
          
        } catch (error) {
          console.error('Reset password error:', error);
          this.resetError = error?.response?.data?.message || '重置密码失败，请重试';
        } finally {
          this.resetLoading = false;
        }
      },
      
      async loadTermsContent() {
        try {
          const locale = localStorage.getItem('zjt_locale') || 'zh-CN';
          // 优先使用商业版后台上传的服务条款（由 server.py SSR 注入到 window.__BRANDING_TERMS__）
          // 社区版或未配置时回退默认 files/*.txt
          const defaultTermsZh = '/files/AI工具服务使用条款.txt';
          const defaultTermsEn = '/files/AI Tool Service Terms.txt';
          const brandingTerms = (window.__BRANDING_TERMS__ || {});
          const termsFile = locale === 'en'
            ? (brandingTerms.en || defaultTermsEn)
            : (brandingTerms.zh || defaultTermsZh);
          const response = await axios.get(termsFile);
          // Convert markdown-like text to HTML
          // First escape HTML entities in raw text to prevent XSS, then apply markdown
          let raw = response.data
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
          let html = raw
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')  // Bold text
            .replace(/^# (.*?)$/gm, '<h1>$1</h1>')  // H1 headers
            .replace(/^## (.*?)$/gm, '<h2>$1</h2>')  // H2 headers
            .replace(/\n\n/g, '</p><p>')  // Paragraphs
            .replace(/\n/g, '<br>');  // Line breaks

          this.termsContent = '<p>' + html + '</p>';
        } catch (error) {
          console.error('Failed to load terms:', error);
          const locale = localStorage.getItem('zjt_locale') || 'zh-CN';
          this.termsContent = locale === 'en'
            ? '<p>Failed to load terms of service. Please try again later.</p>'
            : '<p>加载使用条款失败，请稍后重试。</p>';
        }
      },
      
      openInviteModal() {
        this.showInviteModal = true;
        this.fetchInvitationInfo();
        this.fetchCommissionInfo();
      },
      
      openComputingPowerLogs() {
        if (!this.authToken) {
          alert('请先登录');
          return;
        }
        
        // 打开算力日志模态框
        this.showComputingPowerLogsModal = true;
      },
      
      buildInviteShareText() {
        // 拼接待 host 的注册链接：对方点击即可带邀请码注册。
        // 使用运行时访问地址(window.location.origin)作为 host——即 config 中 server.host 对应的前端可达地址，
        // 比 config 示例值(可能为 localhost)更可靠。
        const origin = window.location.origin;
        const path = window.location.pathname || '/';
        const base = origin + path;
        const url = base + (base.indexOf('?') >= 0 ? '&' : '?') + 'invite_code=' + encodeURIComponent(this.inviteCode);
        return '邀请你加入' + (window.__BRANDING_SITE_NAME__ || '智剧通') + '，点击链接直接注册：' + url;
      },

      copyInviteCode() {
        if (!this.inviteCode) {
          alert('邀请码加载中，请稍后再试');
          return;
        }

        const textToCopy = this.buildInviteShareText();
        // 使用 Clipboard API 复制
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(textToCopy).then(() => {
            alert('邀请链接已复制，快发送给好友吧！');
          }).catch(err => {
            console.error('复制失败:', err);
            this.fallbackCopy();
          });
        } else {
          this.fallbackCopy();
        }
      },

      fallbackCopy() {
        // 降级方案：创建临时 textarea 元素
        const textToCopy = this.buildInviteShareText();
        const textarea = document.createElement('textarea');
        textarea.value = textToCopy;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
          document.execCommand('copy');
          alert('邀请链接已复制，快发送给好友吧！');
        } catch (err) {
          console.error('复制失败:', err);
          alert('复制失败，请手动复制：' + textToCopy);
        }
        document.body.removeChild(textarea);
      },
      
      isWechatBrowser() {
        const ua = navigator.userAgent.toLowerCase();
        return /micromessenger/.test(ua);
      },
      
      async fetchRechargePackages() {
        this.rechargePackagesLoading = true;
        try {
          const response = await axios.get('/api/recharge/packages', {
            params: {
              auth_token: this.authToken
            }
          });
          if (response.data.success) {
            this.rechargePackages = response.data.packages || [];
          } else {
            console.error('Failed to fetch recharge packages:', response.data);
          }
        } catch (error) {
          console.error('Error fetching recharge packages:', error);
          this.handleAuthError(error);
        } finally {
          this.rechargePackagesLoading = false;
        }
      },
      
      async selectPackage(pkg) {
        if (!this.authToken || !this.userId) {
          alert('请先登录');
          this.showRechargePowerModal = false;
          this.showLoginModal = true;
          return;
        }
        
        this.selectedPackage = pkg;
        this.paymentError = '';
        this.paymentQrCode = '';
        this.paymentOrderId = '';
        this.nativeCodeUrl = '';
        
        // 如果是微信浏览器且没有openid，先获取openid
        if (this.isWechatBrowser() && !this.wechatOpenid) {
          this.requestWechatAuth();
          return;
        }
        
        await this.createPaymentOrder();
      },
      
      async handleWechatAuthCallback(code) {
        try {
          const response = await axios.get('/api/wechat/get-openid', {
            params: { code }
          });
          
          if (response.data.success) {
            this.wechatOpenid = response.data.openid;
            localStorage.setItem('wechat_openid', this.wechatOpenid);
            console.log('成功获取openid');
            
            // 如果有选中的套餐，继续创建支付订单
            if (this.selectedPackage) {
              await this.createPaymentOrder();
            }
          } else {
            console.error('获取openid失败:', response.data.message);
          }
        } catch (error) {
          console.error('处理微信授权回调失败:', error);
        }
      },
      
      requestWechatAuth() {
        // 获取微信公众号AppID（需要从配置中获取）
        const appId = 'wxfcf09f56c3d2b2b8'; // TODO: 从后端配置获取
        const redirectUri = encodeURIComponent(window.location.href);
        const scope = 'snsapi_base'; // 静默授权，只获取openid

        // 跳转到微信授权页面
        const authUrl = `https://open.weixin.qq.com/connect/oauth2/authorize?appid=${appId}&redirect_uri=${redirectUri}&response_type=code&scope=${scope}&state=STATE#wechat_redirect`;
        window.location.href = authUrl;
      },

      async fetchServerConfig() {
        try {
          const response = await axios.get('/api/system/server-config');
          if (response.data.code === 0) {
            this.isLocal = response.data.data.is_local || false;
            if (typeof response.data.data.is_enterprise === 'boolean') {
              this.isCommunityEdition = !response.data.data.is_enterprise;
              this.isEditionLoaded = true;
            }
            this.emailEnabled = response.data.data.email_enabled || false;
            this.captchaEnabled = response.data.data.captcha_enabled || false;
            this.captchaPrefix = response.data.data.captcha_prefix || '';
            this.captchaSceneId = response.data.data.captcha_scene_id || '';
            this.wxGroupGuideEnabled = !!response.data.data.wx_group_guide_enabled;
            this.wxGroupQrUrl = response.data.data.wx_group_qr_url || '';
            this.wxGroupQrProxyPath = response.data.data.wx_group_qr_proxy_path
              || '/api/system/wx-group-qr';
            if (response.data.data.footer) {
              this.footerConfig = response.data.data.footer;
            }
            if (response.data.data.version) {
              this.footerConfig.version = response.data.data.version;
            }

            // CAPTCHA SDK 不在此处加载，延迟到登录弹框出现时再初始化
          }
        } catch (error) {
          console.error('Failed to fetch server config:', error);
        }
      },

      // ==================== 官方微信群引导 ====================

      isWxGroupGuideDismissed() {
        return localStorage.getItem('wx_group_guide_dismissed') === '1';
      },

      /**
       * 解析二维码展示 URL。
       * HTTPS 页面加载 HTTP 外链图会被浏览器拦截，改为同源后端代理。
       */
      resolveWxGroupQrDisplayUrl(url) {
        if (!url) return '';
        // 同源相对路径可直接用
        if (url.startsWith('/')) return url;
        try {
          const isHttpsPage = typeof window !== 'undefined'
            && window.location
            && window.location.protocol === 'https:';
          const isHttpRemote = /^http:\/\//i.test(url);
          if (isHttpsPage && isHttpRemote) {
            return this.wxGroupQrProxyPath || '/api/system/wx-group-qr';
          }
        } catch (e) {
          // ignore
        }
        return url;
      },

      /** 注册成功且进入首页后，按 session 标记展示一次轻量浮层 */
      maybeShowWxGroupSoftGuide() {
        if (!this.wxGroupGuideEnabled || this.isWxGroupGuideDismissed()) {
          sessionStorage.removeItem('pending_wx_group_guide');
          return;
        }
        const pending = sessionStorage.getItem('pending_wx_group_guide');
        if (pending !== 'home_soft') {
          return;
        }
        sessionStorage.removeItem('pending_wx_group_guide');
        if (this._wxGroupSoftTimer) {
          clearTimeout(this._wxGroupSoftTimer);
        }
        // 稍晚出现，避免与登录框关闭动画抢焦点
        this._wxGroupSoftTimer = setTimeout(() => {
          this.showWxGroupSoftPanel = true;
          this._wxGroupSoftTimer = null;
        }, 600);
      },

      openWxGroupModal() {
        if (!this.wxGroupGuideEnabled || !this.wxGroupQrDisplayUrl) {
          return;
        }
        this.showWxGroupModal = true;
      },

      dismissWxGroupSoftPanel({ permanent = false } = {}) {
        this.showWxGroupSoftPanel = false;
        if (permanent || this.wxGroupDontShowAgain) {
          localStorage.setItem('wx_group_guide_dismissed', '1');
        }
      },

      dismissWxGroupSoftPanelPermanent() {
        this.wxGroupDontShowAgain = true;
        this.dismissWxGroupSoftPanel({ permanent: true });
      },

      // ==================== CAPTCHA 人机验证 ====================

      loadCaptchaSdk() {
        // 防止重复加载
        if (document.getElementById('aliyun-captcha-sdk')) return;
        const script = document.createElement('script');
        script.id = 'aliyun-captcha-sdk';
        script.type = 'text/javascript';
        script.src = 'https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js';
        script.onload = () => {
          console.log('Aliyun CAPTCHA SDK loaded');
          this.$nextTick(() => { this.initCaptcha(); });
        };
        script.onerror = () => {
          console.error('Failed to load Aliyun CAPTCHA SDK');
        };
        document.head.appendChild(script);
      },

      initCaptcha() {
        if (!this.captchaEnabled || !this.captchaPrefix || !window.initAliyunCaptcha) return;

        // 确保 CAPTCHA 按钮存在
        const captchaBtn = document.getElementById('captcha-verify-btn');
        if (!captchaBtn) {
          console.warn('CAPTCHA button element not found');
          return;
        }

        try {
          const self = this;
          window.initAliyunCaptcha({
            prefix: this.captchaPrefix,
            SceneId: this.captchaSceneId,
            mode: 'popup',
            element: '#captcha-verify-btn',
            button: '#captcha-verify-btn',
            // 验证通过回调：captchaVerifyParam 已是字符串，直接传递
            success: async function(captchaVerifyParam) {
              await self._captchaSuccess(captchaVerifyParam);
            },
            // 验证失败回调
            fail: function(result) {
              console.error('CAPTCHA verify failed:', result);
              self._handleCodeSendError('人机验证失败，请重试');
            },
            // 绑定验证码实例
            getInstance: function(instance) {
              self.captchaInstance = instance;
            },
            // 关闭弹窗回调
            onClose: function() {
              // 用户关闭验证弹窗时清理状态
            },
            language: 'cn',
          }).then(function() {
            console.log('Aliyun CAPTCHA initialized');
          }).catch(function(err) {
            console.error('CAPTCHA init error:', err);
          });
        } catch (e) {
          console.error('Failed to init CAPTCHA:', e);
        }
      },

      // CAPTCHA 验证成功回调
      async _captchaSuccess(captchaVerifyParam) {
        try {
          const captchaResponse = await axios.post('/api/auth/send_verify_code', {
            ...(this._pendingSendPayload || {}),
            captcha_verify_param: captchaVerifyParam
          });

          if (captchaResponse.data.success) {
            this._handleCodeSendSuccess();
          } else {
            this._handleCodeSendError(captchaResponse.data.message || '发送验证码失败');
          }
        } catch (error) {
          console.error('CAPTCHA verify callback error:', error);
          const msg = error?.response?.data?.message || '发送验证码失败，请重试';
          this._handleCodeSendError(msg);
        }
      },

      triggerCaptchaForEmail(action, payload) {
        // 保存待发送的数据
        this._pendingSendPayload = payload;
        this.captchaAction = action;

        // 触发 CAPTCHA 验证按钮
        const captchaBtn = document.getElementById('captcha-verify-btn');
        if (captchaBtn) {
          captchaBtn.click();
        } else {
          console.error('CAPTCHA button not found');
          this._handleCodeSendError('人机验证组件未加载');
        }
      },

      _handleCodeSendSuccess() {
        if (this.captchaAction === 'register_code') {
          this.codeCountdown = 60;
          this.countdownTimer = setInterval(() => {
            this.codeCountdown--;
            if (this.codeCountdown <= 0) {
              clearInterval(this.countdownTimer);
              this.countdownTimer = null;
            }
          }, 1000);
        } else if (this.captchaAction === 'reset_code') {
          this.resetCodeCountdown = 60;
          this.resetCountdownTimer = setInterval(() => {
            this.resetCodeCountdown--;
            if (this.resetCodeCountdown <= 0) {
              clearInterval(this.resetCountdownTimer);
              this.resetCountdownTimer = null;
            }
          }, 1000);
        }
        this._pendingSendPayload = null;
        this.captchaAction = null;
      },

      _handleCodeSendError(message) {
        if (this.captchaAction === 'register_code') {
          this.registerError = message;
        } else if (this.captchaAction === 'reset_code') {
          this.resetError = message;
        }
        this._pendingSendPayload = null;
        this.captchaAction = null;
      },

      handleRechargeClick() {
        if (this.isLocal) {
          alert(this.$t('local_recharge_tip'));
        } else {
          this.showRechargePowerModal = true;
          this.fetchRechargePackages();
        }
      },

      async fetchUserIp() {
        try {
          // 使用公共IP查询API获取用户IP
          const response = await axios.get('https://api.ipify.org?format=json', { timeout: 5000 });
          this.userIp = response.data.ip;
          console.log('User IP:', this.userIp);
        } catch (error) {
          console.error('Failed to fetch user IP:', error);
          // 如果获取失败，使用默认值
          this.userIp = '0.0.0.0';
        }
      },
      
      async createPaymentOrder() {
        if (!this.selectedPackage) return;
        this.paymentLoading = true;
        this.paymentError = '';
        this.nativeCodeUrl = '';
        this.paymentQrCode = '';
        
        const isWechat = this.isWechatBrowser();
        if (!this.userIp) {
          await this.fetchUserIp();
        }
        
        try {
          const requestData = {
            package_id: this.selectedPackage.package_id,
            user_id: parseInt(this.userId, 10),
            auth_token: this.authToken,
            is_wechat_browser: isWechat,
            payment_ip: this.userIp || '0.0.0.0'
          };
          
          if (isWechat && this.wechatOpenid) {
            requestData.openid = this.wechatOpenid;
          }
          
          const response = await axios.post('/api/recharge/wechat-pay', requestData);
          
          if (response.data.success) {
            this.paymentOrderId = response.data.order_id;
            const paymentType = response.data.payment_type;
            
            if (paymentType === 'JSAPI') {
              this.invokeWechatJSAPI(response.data.jsapi_params);
            } else if (paymentType === 'NATIVE') {
              const codeUrl = response.data.code_url;
              if (!codeUrl) {
                this.paymentError = '未获取到支付二维码，请重试';
              } else {
                this.nativeCodeUrl = codeUrl;
                this.paymentQrCode = `https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=${encodeURIComponent(codeUrl)}`;
              }
            } else {
              this.paymentError = '未知的支付方式，请重试';
            }
          } else {
            this.paymentError = response.data.message || '创建支付订单失败';
          }
        } catch (error) {
          console.error('Error creating payment order:', error);
          this.paymentError = error?.response?.data?.detail || '创建支付订单失败，请重试';
        } finally {
          this.paymentLoading = false;
        }
      },
      
      invokeWechatJSAPI(jsapiParams) {
        // 检查是否在微信环境中
        if (typeof WeixinJSBridge === 'undefined') {
          this.paymentError = '请在微信中打开';
          return;
        }
        
        // 调用微信支付JSAPI
        WeixinJSBridge.invoke(
          'getBrandWCPayRequest',
          {
            appId: jsapiParams.appId,
            timeStamp: jsapiParams.timeStamp,
            nonceStr: jsapiParams.nonceStr,
            package: jsapiParams.package,
            signType: jsapiParams.signType,
            paySign: jsapiParams.paySign
          },
          (res) => {
            if (res.err_msg === 'get_brand_wcpay_request:ok') {
              // 支付成功
              alert('支付成功！算力将在几秒内到账');
              this.closeRechargeModal();
              // 刷新算力
              setTimeout(() => {
                this.fetchComputingPower();
              }, 2000);
            } else if (res.err_msg === 'get_brand_wcpay_request:cancel') {
              // 用户取消支付
              this.paymentError = '支付已取消';
            } else {
              // 支付失败
              this.paymentError = '支付失败: ' + res.err_msg;
            }
          }
        );
      },
      
      backToPackageSelection() {
        this.selectedPackage = null;
        this.paymentQrCode = '';
        this.paymentOrderId = '';
        this.paymentError = '';
        this.nativeCodeUrl = '';
      },
      
      retryPayment() {
        this.createPaymentOrder();
      },
      
      closeRechargeModal() {
        this.showRechargePowerModal = false;
        this.selectedPackage = null;
        this.paymentQrCode = '';
        this.paymentOrderId = '';
        this.paymentError = '';
        this.nativeCodeUrl = '';
        this.rechargePackages = [];
      },
      
      // 检查创作模式
      checkCreationMode() {
        const savedMode = localStorage.getItem('creation_mode');
        if (savedMode) {
          this.creationMode = savedMode;
        } else {
          // 未选择模式，默认短剧模式
          this.creationMode = 'short_drama';
          localStorage.setItem('creation_mode', 'short_drama');
        }
      },
      
      // 选择创作模式
      selectCreationMode(mode) {
        this.creationMode = mode;
        localStorage.setItem('creation_mode', mode);
        this.showModeSelectModal = false;
        // 切换到营销模式时关闭智能体连接弹窗（CLI 仅支持故事板/短剧）
        if (mode !== 'short_drama' && this.showAgentConnectionModal) {
          this.closeAgentConnectionModal();
        }
      },
      
    },
    
    beforeUnmount() {
      // 清理倒计时定时器
      if (this.countdownTimer) {
        clearInterval(this.countdownTimer);
      }
      if (this.resetCountdownTimer) {
        clearInterval(this.resetCountdownTimer);
      }
      if (this.checkinToastTimer) {
        clearTimeout(this.checkinToastTimer);
      }
      if (this._wxGroupSoftTimer) {
        clearTimeout(this._wxGroupSoftTimer);
        this._wxGroupSoftTimer = null;
      }
      // 移除语言切换事件监听
      if (window.ZJTi18n && this._localeChangedHandler) {
        window.ZJTi18n.off('locale-changed', this._localeChangedHandler);
      }
      // 移除 axios 响应拦截器
      if (this._axiosInterceptorId != null) {
        axios.interceptors.response.eject(this._axiosInterceptorId);
      }
      // 移除管理员快捷键监听
      if (this._adminKeyHandler) {
        document.removeEventListener('keydown', this._adminKeyHandler);
      }
    }
  };

if (typeof window !== "undefined") { window.routes = routes; window.router = router; window.App = App; }
