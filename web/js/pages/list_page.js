  const ListPage = {
    name: 'ListPage',
    data() {
      return {
        aiToolsExpanded: false
      };
    },
    template: `
      <div class="homepage-container">
        <!-- 短剧模式内容 -->
        <!-- 当前模式显示 -->
          <div class="current-mode-bar">
            <span class="current-mode-label">{{ $t('current_mode') }}</span>
            <span class="current-mode-value" v-if="$root.creationMode === 'marketing'">🎯 {{ $t('mode_marketing') }}</span>
            <span class="current-mode-value" v-else>🎬 {{ $t('mode_short_drama') }}</span>
            <button class="mode-switch-btn" @click.stop="$root.showModeSelectModal = true">{{ $t('switch_mode') }}</button>
          </div>

          <!-- 开始创作大横幅 -->
          <div class="start-creation-banner" @click="handleStartCreation">
            <div class="banner-content">
              <template v-if="$root.creationMode === 'marketing'">
                <div class="banner-title-row">
                  <span class="banner-sparkle">🎯</span>
                  <h1 class="banner-title">{{ $t('banner_title_marketing') }}</h1>
                  <span class="banner-sparkle">🎯</span>
                </div>
                <p class="banner-desc">{{ $t('banner_desc_marketing') }}</p>
                <p class="banner-subtitle">{{ $t('banner_subtitle_marketing') }}</p>
              </template>
              <template v-else>
                <div class="banner-title-row">
                  <span class="banner-sparkle">✨</span>
                  <h1 class="banner-title">{{ $t('start_creation') }}</h1>
                  <span class="banner-sparkle">✨</span>
                </div>
                <p class="banner-desc">{{ $t('creation_desc') }}</p>
                <p class="banner-subtitle">→ {{ $t('click_start_journey') }}</p>
              </template>
            </div>
          </div>

          <!-- 工作流入口卡片 -->
          <div class="feature-cards" v-if="$root.creationMode !== 'marketing'">
            <div class="feature-card" @click="handleVideoWorkflowClick">
              <div class="feature-card-header">
                <div class="feature-card-icon blue">📹</div>
                <div class="feature-card-info">
                  <div class="feature-card-title">{{ $t('video_workflow') }}</div>
                  <div class="feature-card-subtitle">{{ $t('video_workflow_desc') }}</div>
                </div>
              </div>
              <div class="feature-card-body">
                <p class="feature-card-desc">{{ $t('video_workflow_detail') }}</p>
              </div>
              <div class="feature-card-footer">
                <span class="feature-card-link">→</span>
              </div>
            </div>
            <div class="feature-card" @click="handleScriptWriterClick">
              <div class="feature-card-header">
                <div class="feature-card-icon purple">✨</div>
                <div class="feature-card-info">
                  <div class="feature-card-title">{{ $t('script_system') }}</div>
                  <div class="feature-card-subtitle">{{ $t('script_system_desc') }}</div>
                </div>
              </div>
              <div class="feature-card-body">
                <p class="feature-card-desc">{{ $t('script_system_detail') }}</p>
              </div>
              <div class="feature-card-footer">
                <span class="feature-card-link">→</span>
              </div>
            </div>
            <div class="feature-card" @click="handleStoryboardListClick">
              <div class="feature-card-header">
                <div class="feature-card-icon storyboard">▦</div>
                <div class="feature-card-info">
                  <div class="feature-card-title">{{ $t('storyboard_system') }}</div>
                  <div class="feature-card-subtitle">{{ $t('storyboard_system_desc') }}</div>
                </div>
              </div>
              <div class="feature-card-body">
                <p class="feature-card-desc">{{ $t('storyboard_system_detail') }}</p>
              </div>
              <div class="feature-card-footer">
                <span class="feature-card-link">→</span>
              </div>
            </div>
          </div>

          <!-- AI工具区域 -->
          <div class="ai-tools-section">
            <div class="ai-tools-header" @click="aiToolsExpanded = !aiToolsExpanded">
              <div class="ai-tools-left">
                <div class="ai-tools-icon">🤖</div>
                <div class="ai-tools-info">
                  <span class="ai-tools-title">{{ $t('ai_toolbox') }}</span>
                  <span class="ai-tools-subtitle" v-if="!aiToolsExpanded">{{ $t('ai_toolbox_desc') }}</span>
                </div>
              </div>
              <div class="ai-tools-toggle" :class="{expanded: aiToolsExpanded}">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M6 9l6 6 6-6"/>
                </svg>
              </div>
            </div>
            <div class="ai-tools-content" v-show="aiToolsExpanded">
              <div class="ai-tools-grid">
                <div class="tool-card" @click="$router.push({name:'image-edit'})">
                  <div class="tool-card-icon blue">🖼️</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('image_edit') }}</div>
                    <div class="tool-card-desc">{{ $t('image_edit_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'text-to-image'})">
                  <div class="tool-card-icon purple">🎨</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('ai_text_to_image') }}</div>
                    <div class="tool-card-desc">{{ $t('ai_text_to_image_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'ai-video-gen'})">
                  <div class="tool-card-icon orange">📹</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('ai_video_generation') }}</div>
                    <div class="tool-card-desc">{{ $t('ai_video_generation_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'image-to-video'})">
                  <div class="tool-card-icon green">🎬</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('image_to_video') }}</div>
                    <div class="tool-card-desc">{{ $t('image_to_video_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'video-enhance'})">
                  <div class="tool-card-icon yellow">✨</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('video_enhance') }}</div>
                    <div class="tool-card-desc">{{ $t('video_enhance_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'audio-generate'})">
                  <div class="tool-card-icon purple">🎵</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('audio_generation') }}</div>
                    <div class="tool-card-desc">{{ $t('audio_generation_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'digital-human'})">
                  <div class="tool-card-icon pink">👤</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('digital_human') }}</div>
                    <div class="tool-card-desc">{{ $t('digital_human_desc') }}</div>
                  </div>
                </div>
                <div class="tool-card" @click="$router.push({name:'skill-config'})">
                  <div class="tool-card-icon teal">⚙️</div>
                  <div class="tool-card-info">
                    <div class="tool-card-title">{{ $t('skill_config') }}</div>
                    <div class="tool-card-desc">{{ $t('skill_config_desc') }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
      </div>
    `,
    methods: {
      goHome() {
        this.$router.push({name:'list'});
      },
      handleStartCreation() {
        if (this.$root.creationMode === 'marketing') {
          const userId = localStorage.getItem('user_id') || '';
          window.location.href = '/marketing-inspiration?user_id=' + encodeURIComponent(userId);
        } else {
          // 跳转到工作流列表页面并自动打开新建表单，加随机数防止缓存
          window.location.href = '/video-workflow-list?action=create&_t=' + Date.now();
        }
      },
      handleVideoWorkflowClick() {
        window.location.href = '/video-workflow-list';
      },
      handleStoryboardListClick() {
        const authToken = localStorage.getItem('auth_token');
        const userId = localStorage.getItem('user_id');

        if (!authToken || !userId) {
          alert(this.$t('need_login') || '请先登录');
          return;
        }

        window.location.href = '/storyboard-list';
      },
      handleScriptWriterClick() {
        const authToken = localStorage.getItem('auth_token');
        const userId = localStorage.getItem('user_id');

        if (!authToken || !userId) {
          alert(this.$t('need_login') || '请先登录');
          return;
        }

        // auth_token 已在 localStorage 中，无需通过 URL 传递
        const url = `/script-writer?user_id=${encodeURIComponent(userId)}`;
        window.location.href = url;
      },
    }
  };

if (typeof window !== "undefined") window.ListPage = ListPage;
