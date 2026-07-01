  const SkillConfig = {
    name: 'SkillConfig',
    data() {
      return {
        skills: [],
        loading: false,
        error: '',
        // 编辑弹窗
        showEditModal: false,
        editingSkill: null,
        editPrompt: '',
        editLoading: false,
        editError: '',
        // 原始内容（用于检测变化）
        originalPrompt: '',
      }
    },
    mounted() {
      this.loadSkills();
    },
    computed: {
      userId() {
        return localStorage.getItem('user_id') || '';
      },
      authToken() {
        return localStorage.getItem('auth_token') || '';
      },
      hasChanges() {
        return this.editPrompt !== this.originalPrompt;
      },
      promptSize() {
        return new Blob([this.editPrompt]).size;
      }
    },
    methods: {
      async loadSkills() {
        if (!this.userId) {
          this.error = '请先登录后再使用此功能';
          return;
        }
        this.loading = true;
        this.error = '';
        try {
          const res = await axios.get('/api/skills', {
            params: { user_id: this.userId, auth_token: this.authToken },
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (res.data.success) {
            this.skills = res.data.skills;
          } else {
            this.error = res.data.error || '加载失败';
          }
        } catch (e) {
          this.error = '加载技能列表失败：' + (e.response?.data?.error || e.message);
        } finally {
          this.loading = false;
        }
      },
      formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
      },
      async openEditor(skill) {
        if (!this.userId) {
          alert('请先登录');
          return;
        }
        this.editingSkill = skill;
        this.editLoading = true;
        this.editError = '';
        this.showEditModal = true;
        try {
          const res = await axios.get(`/api/skills/${skill.skill_name}`, {
            params: { user_id: this.userId, auth_token: this.authToken },
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (res.data.success) {
            this.editPrompt = res.data.skill.prompt_content || '';
            this.originalPrompt = this.editPrompt;
          } else {
            this.editError = res.data.error || '加载失败';
          }
        } catch (e) {
          this.editError = '加载技能详情失败：' + (e.response?.data?.error || e.message);
        } finally {
          this.editLoading = false;
        }
      },
      closeEditor() {
        this.showEditModal = false;
        this.editingSkill = null;
        this.editPrompt = '';
        this.originalPrompt = '';
        this.editError = '';
      },
      async saveSkill() {
        if (!this.editingSkill || !this.userId) return;
        this.editLoading = true;
        this.editError = '';
        try {
          const res = await axios.put(`/api/skills/${this.editingSkill.skill_name}`, {
            prompt_content: this.editPrompt,
            auth_token: this.authToken
          }, {
            params: { user_id: this.userId },
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (res.data.success) {
            this.closeEditor();
            this.loadSkills();
          } else {
            this.editError = res.data.error || '保存失败';
          }
        } catch (e) {
          this.editError = '保存失败：' + (e.response?.data?.error || e.message);
        } finally {
          this.editLoading = false;
        }
      },
      async resetSkill(skill) {
        if (!this.userId) { alert('请先登录'); return; }
        if (!confirm(`确定要将「${skill.display_name || skill.skill_name}」恢复为默认配置吗？`)) return;
        try {
          const res = await axios.delete(`/api/skills/${skill.skill_name}`, {
            params: { user_id: this.userId, auth_token: this.authToken },
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (res.data.success) {
            this.loadSkills();
          } else {
            alert(res.data.error || '重置失败');
          }
        } catch (e) {
          alert('重置失败：' + (e.response?.data?.error || e.message));
        }
      },
      handleTabKey(e) {
        e.preventDefault();
        const textarea = e.target;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        this.editPrompt = this.editPrompt.substring(0, start) + '\t' + this.editPrompt.substring(end);
        this.$nextTick(() => {
          textarea.selectionStart = textarea.selectionEnd = start + 1;
        });
      }
    },
    template: `
      <div class="skill-config-page">
        <div class="skill-config-header">
          <button class="back-btn" @click="$router.push({name:'list'})">← {{ $t('back') }}</button>
          <h1>{{ $t('skill_config_tool') }}</h1>
        </div>
        <p class="skill-config-desc">{{ $t('skill_config_desc') }}</p>

        <div v-if="loading" class="skill-loading">
          <div class="loading-spinner"></div>
          <span>{{ $t('loading') }}</span>
        </div>

        <div v-else-if="error" class="skill-error">
          {{ error }}
          <button v-if="!userId" class="skill-btn primary" style="margin-left:12px;" @click="$root.showLoginModal=true">{{ $t('login') }}</button>
        </div>

        <div v-else class="skill-list">
          <div v-for="skill in skills" :key="skill.skill_name" class="skill-card">
            <div class="skill-card-info">
              <div class="skill-card-name">{{ skill.display_name || skill.skill_name }}</div>
              <div class="skill-card-id">{{ skill.skill_name }}</div>
              <div class="skill-card-desc">{{ skill.description }}</div>
            </div>
            <div class="skill-card-meta">
              <span class="skill-size">{{ formatFileSize(skill.file_size) }}</span>
              <span v-if="skill.has_custom" class="skill-badge custom">{{ $t('customized') }}</span>
              <span v-else class="skill-badge default">{{ $t('default_config') }}</span>
            </div>
            <div class="skill-card-actions">
              <button class="skill-btn primary" @click="openEditor(skill)">{{ $t('edit_skill') }}</button>
              <button v-if="skill.has_custom" class="skill-btn" @click="resetSkill(skill)">{{ $t('reset_skill') }}</button>
            </div>
          </div>
        </div>

        <!-- 编辑弹窗 -->
        <div v-if="showEditModal" class="skill-modal-overlay" @click.self="closeEditor">
          <div class="skill-modal">
            <div class="skill-modal-header">
              <h2>{{ $t('edit_skill') }} - {{ editingSkill?.display_name || editingSkill?.skill_name }}</h2>
              <button class="skill-modal-close" @click="closeEditor">&times;</button>
            </div>

            <div v-if="editLoading && !editPrompt" class="skill-modal-loading">
              <div class="loading-spinner"></div>
              <span>{{ $t('loading') }}</span>
            </div>

            <template v-else>
              <div class="skill-modal-info">
                <span class="skill-modal-label">{{ $t('skill_name') }}：</span>
                <span>{{ editingSkill?.skill_name }}</span>
                <span v-if="editingSkill?.has_custom" class="skill-badge custom" style="margin-left:8px;">{{ $t('customized') }}</span>
              </div>

              <div v-if="editError" class="skill-error" style="margin:0 20px;">{{ editError }}</div>

              <div class="skill-modal-body">
                <textarea
                  v-model="editPrompt"
                  class="skill-textarea"
                  :placeholder="$t('prompt_placeholder')"
                  @keydown.tab="handleTabKey"
                ></textarea>
                <div class="skill-textarea-info">
                  <span>{{ editPrompt.length }} {{ $t('characters') }} | {{ formatFileSize(promptSize) }}</span>
                  <span v-if="hasChanges" class="skill-changed">* {{ $t('changed') }}</span>
                </div>
              </div>

              <div class="skill-modal-footer">
                <button class="skill-btn" @click="closeEditor">{{ $t('cancel_edit') }}</button>
                <button
                  class="skill-btn primary"
                  @click="saveSkill"
                  :disabled="editLoading || !hasChanges"
                >
                  {{ editLoading ? $t('save_loading') : $t('save') }}
                </button>
              </div>
            </template>
          </div>
        </div>
      </div>
    `
  };

if (typeof window !== "undefined") window.SkillConfig = SkillConfig;
