    function createScriptNode(opts){
      // i18n：缺失 key 时 window.t 常回退为 key 本身，需再用中文 fallback
      const st = (key, fallback) => {
        try {
          if (typeof window.t === 'function') {
            const v = window.t(key);
            if (v && v !== key) return v;
          }
        } catch (_) { /* ignore */ }
        return fallback;
      };
      const id = state.nextNodeId++;
      const scriptId = (opts && typeof opts.scriptId === 'number') ? opts.scriptId : state.nextScriptId++;
      if(opts && typeof opts.scriptId === 'number' && opts.scriptId >= state.nextScriptId) {
        state.nextScriptId = opts.scriptId + 1;
      }
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);
      const node = {
        id,
        type: 'script',
        title: `剧本 ${scriptId}`,
        x,
        y,
        data: {
          scriptId,
          file: null,
          url: '',
          name: '',
          scriptContent: '',
          parsedData: null,
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port output" title="${window.t ? window.t('script_output_port') : '输出（拆分为幕）'}"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M9 5H7C5.89543 5 5 5.89543 5 7V19C5 20.1046 5.89543 21 7 21H17C18.1046 21 19 20.1046 19 19V7C19 5.89543 18.1046 5 17 5H15"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>剧本 ${scriptId}</div>
          <button class="icon-btn" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body script-node-body">
          <!-- 第1部分：剧本内容 -->
          <div class="script-section">
            <div class="script-section-header">
              <span class="script-section-number">1</span>
              <span class="script-section-title" data-i18n="script_section_1">${window.t ? window.t('script_section_1') : '剧本内容'}</span>
            </div>
            <div class="field field-always-visible script-info-field" style="display:none;">
              <div class="gen-meta script-name"></div>
              <div class="gen-meta script-length"></div>
            </div>
            <div class="field field-always-visible">
              <div style="display: flex; justify-content: flex-end; align-items: center; gap: 6px; margin-bottom: 4px;">
                <span class="script-char-count" style="color: #666; font-size: 12px;">0/30000</span>
                <button class="mini-btn script-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="${window.t ? window.t('script_expand_btn') : '放大编辑'}" data-i18n="script_expand_btn:title">⤢</button>
              </div>
              <textarea class="script-textarea" rows="16" maxlength="30000" placeholder="${window.t ? window.t('script_placeholder') : '在此输入剧本内容，或上传文件（最多30000字符）'}" data-i18n="script_placeholder:placeholder"></textarea>
            </div>
            <div class="field field-always-visible" style="margin-top: auto; padding-top: 8px;">
              <div style="display: flex; gap: 6px;">
                <button class="gen-btn gen-btn-white script-upload-btn" type="button" style="border-radius: 8px; flex: 1; padding: 7px 0; font-size: 12px;" data-i18n="script_upload_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>${window.t ? window.t('script_upload_btn') : '上传'}</button>
                <button class="gen-btn gen-btn-green script-load-btn" type="button" style="border-radius: 8px; flex: 1; padding: 7px 0; font-size: 12px;" data-i18n="script_load_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>${window.t ? window.t('script_load_btn') : '加载'}</button>
              </div>
              <input class="script-file" type="file" accept=".txt,.md" style="display:none;" />
            </div>
            <div class="field field-always-visible script-warning-field" style="display:none;">
              <div class="gen-meta" style="color: #f59e0b;" data-i18n="script_file_truncated">${window.t ? window.t('script_file_truncated') : '文件内容超过30000字符，已自动截取前30000字符。建议将剧本分段处理。'}</div>
            </div>
          </div>

          <!-- 第2部分：参数配置（分组折叠，降低纵向拥挤） -->
          <div class="script-section script-section-params">
            <div class="script-section-header">
              <span class="script-section-number">2</span>
              <span class="script-section-title" data-i18n="script_section_2">${st('script_section_2', '参数配置')}</span>
            </div>

            <!-- 常驻：拆分核心 -->
            <div class="script-param-core">
              <div class="field field-always-visible">
                <div class="label" data-i18n="script_sequence_mode_label">${st('script_sequence_mode_label', '分镜拆分模式')}</div>
                <select class="script-sequence-mode" title="${st('script_sequence_mode_hint', '均衡：质量与效率折中；速度：先出结果；效果：影院级一致性（商业版）')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                  <option value="balanced" data-i18n="script_sequence_mode_balanced">${st('script_sequence_mode_balanced', '均衡模式（推荐）')}</option>
                  <option value="speed" data-i18n="script_sequence_mode_speed">${st('script_sequence_mode_speed', '速度模式')}</option>
                  <option value="quality" data-i18n="script_sequence_mode_quality">${st('script_sequence_mode_quality', '效果模式（商业版）')}</option>
                </select>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="script_split_model_label">${st('script_split_model_label', '拆分模型')}</div>
                <select class="script-split-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                  <option value="" data-i18n="script_loading">${st('script_loading', '加载中...')}</option>
                </select>
              </div>
              <div class="field field-always-visible script-thinking-mode-field" style="display: none;">
                <div class="label" data-i18n="script_thinking_mode_label">${st('script_thinking_mode_label', '思考模式')}</div>
                <div class="script-thinking-row">
                  <label class="script-inline-check">
                    <input type="checkbox" class="script-enable-thinking" style="cursor: pointer;" />
                    <span data-i18n="script_enable_thinking">${st('script_enable_thinking', '深度思考')}</span>
                  </label>
                  <select class="script-thinking-effort" style="display: none; padding: 4px 6px; border: 1px solid #ddd; border-radius: 4px; background: white; font-size: 12px;">
                    <option value="low" data-i18n="thinking_effort_low">${st('thinking_effort_low', '低')}</option>
                    <option value="medium" selected data-i18n="thinking_effort_medium">${st('thinking_effort_medium', '中')}</option>
                    <option value="high" data-i18n="thinking_effort_high">${st('thinking_effort_high', '高')}</option>
                  </select>
                </div>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="script_duration_label">${st('script_duration_label', '镜头组时长')}</div>
                <select class="script-duration-select" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                  <option value="5" data-i18n="duration_5s">${st('duration_5s', '5秒')}</option>
                  <option value="8" data-i18n="duration_8s">${st('duration_8s', '8秒')}</option>
                  <option value="10" data-i18n="duration_10s">${st('duration_10s', '10秒')}</option>
                  <option value="15" selected data-i18n="duration_15s">${st('duration_15s', '15秒')}</option>
                </select>
              </div>
              <div class="script-checkbox-group script-checkbox-group-compact">
                <label class="script-inline-check">
                  <input type="checkbox" class="script-force-medium-shot" style="cursor: pointer;" checked />
                  <span data-i18n="script_force_medium_shot">${st('script_force_medium_shot', '对话禁止全景')}</span>
                </label>
                <label class="script-inline-check">
                  <input type="checkbox" class="script-no-bg-music" style="cursor: pointer;" checked />
                  <span data-i18n="script_no_bg_music">${st('script_no_bg_music', '不生成背景音乐')}</span>
                </label>
                <label class="script-inline-check">
                  <input type="checkbox" class="script-split-multi-dialogue" style="cursor: pointer;" />
                  <span data-i18n="script_split_multi_dialogue">${st('script_split_multi_dialogue', '拆分多人对话镜头')}</span>
                </label>
              </div>
            </div>

            <!-- 折叠：宫格与视频 -->
            <div class="script-param-group" data-script-group="gridVideo">
              <button type="button" class="script-param-group-toggle" aria-expanded="false">
                <span class="script-param-group-chevron" aria-hidden="true">▶</span>
                <span class="script-param-group-title" data-i18n="script_group_grid_video">${st('script_group_grid_video', '宫格与视频')}</span>
                <span class="script-param-group-summary script-grid-video-summary"></span>
              </button>
              <div class="script-param-group-body" hidden>
                <div class="field field-always-visible">
                  <div class="label" data-i18n="script_grid_model_label">${st('script_grid_model_label', '宫格生图模型')}</div>
                  <select class="script-grid-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;"></select>
                </div>
                <div class="field field-always-visible">
                  <div class="label" data-i18n="script_grid_layout_label">${st('script_grid_layout_label', '宫格类型')}</div>
                  <select class="script-grid-layout" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                    <option value="auto" data-i18n="script_grid_layout_auto">${st('script_grid_layout_auto', '自动选择')}</option>
                    <option value="4" data-i18n="script_grid_layout_4">${st('script_grid_layout_4', '4宫格 (2x2)')}</option>
                    <option value="9" data-i18n="script_grid_layout_9">${st('script_grid_layout_9', '9宫格 (3x3)')}</option>
                  </select>
                </div>
                <div class="field field-always-visible">
                  <div class="label" data-i18n="script_video_model_label">${st('script_video_model_label', '视频生成模型')}</div>
                  <select class="script-video-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;"></select>
                </div>
              </div>
            </div>

            <!-- 折叠：语言 -->
            <div class="script-param-group" data-script-group="language">
              <button type="button" class="script-param-group-toggle" aria-expanded="false">
                <span class="script-param-group-chevron" aria-hidden="true">▶</span>
                <span class="script-param-group-title" data-i18n="script_group_language">${st('script_group_language', '语言')}</span>
                <span class="script-param-group-summary script-language-summary"></span>
              </button>
              <div class="script-param-group-body" hidden>
                <div class="field field-always-visible">
                  <div class="label" data-i18n="script_dialogue_language_label">${st('script_dialogue_language_label', '对话语言')}</div>
                  <select class="script-dialogue-language" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                    <option value="" data-i18n="script_language_default">${st('script_language_default', '中文（默认）')}</option>
                    <option value="English">English</option>
                    <option value="Deutsch">Deutsch</option>
                    <option value="Français">Français</option>
                    <option value="Русский">Русский</option>
                    <option value="__custom__" data-i18n="script_language_custom">${st('script_language_custom', '自定义语言...')}</option>
                  </select>
                  <input type="text" class="script-dialogue-language-custom" placeholder="${st('script_language_custom', '或输入自定义语言...')}" style="display: none; width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white; margin-top: 4px;" />
                </div>
                <div class="field field-always-visible">
                  <div class="label" data-i18n="script_prompt_language_label">${st('script_prompt_language_label', '提示词语言')}</div>
                  <select class="script-prompt-language" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                    <option value="" data-i18n="script_language_default">${st('script_language_default', '中文（默认）')}</option>
                    <option value="English">English</option>
                    <option value="Deutsch">Deutsch</option>
                    <option value="Français">Français</option>
                    <option value="Русский">Русский</option>
                    <option value="__custom__" data-i18n="script_language_custom">${st('script_language_custom', '自定义语言...')}</option>
                  </select>
                  <input type="text" class="script-prompt-language-custom" placeholder="${st('script_language_custom', '或输入自定义语言...')}" style="display: none; width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white; margin-top: 4px;" />
                </div>
              </div>
            </div>

            <!-- 折叠：高级 / 质检 -->
            <div class="script-param-group" data-script-group="advanced">
              <button type="button" class="script-param-group-toggle" aria-expanded="false">
                <span class="script-param-group-chevron" aria-hidden="true">▶</span>
                <span class="script-param-group-title" data-i18n="script_group_advanced">${st('script_group_advanced', '高级 · 质检')}</span>
                <span class="script-param-group-summary script-advanced-summary"></span>
              </button>
              <div class="script-param-group-body" hidden>
                <div class="script-checkbox-group">
                  <label class="script-inline-check">
                    <input type="checkbox" class="script-enable-split-qc" style="cursor: pointer;" />
                    <span>
                      <span data-i18n="script_enable_split_qc">${st('script_enable_split_qc', '开启拆分质检')}</span>
                      <span class="script-split-qc-free-badge" aria-label="质检次数限时免费">限时免费</span>
                    </span>
                  </label>
                  <div class="gen-meta script-qc-hint" title="${st('script_enable_split_qc_hint', '会显著增加时间与算力消耗')}" data-i18n="script_enable_split_qc_hint">${st('script_enable_split_qc_hint', '会显著增加时间与算力消耗')}</div>
                </div>
                <div class="field field-always-visible script-qc-rounds-field" style="display: none;">
                  <div class="label script-split-qc-rounds-heading">
                    <span data-i18n="script_qc_max_rounds_label">${st('script_qc_max_rounds_label', '质检最大循环次数')}</span>
                  </div>
                  <select class="script-qc-max-rounds" title="${st('script_qc_max_rounds_hint', '拆分→质检最多循环 N 次；仍不通过则强制采用最后一轮结果')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                    <option value="1">1 次</option>
                    <option value="2" selected>2 次</option>
                    <option value="3">3 次</option>
                    <option value="4">4 次</option>
                    <option value="5">5 次</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          <!-- 第3部分：执行操作 -->
          <div class="script-section script-section-actions">
            <div class="script-section-header">
              <span class="script-section-number">3</span>
              <span class="script-section-title" data-i18n="script_section_3">${window.t ? window.t('script_section_3') : '执行操作'}</span>
            </div>
            <div class="field field-always-visible">
              <div style="display: flex; gap: 6px;">
                <button class="gen-btn gen-btn-white script-split-btn" type="button" style="border-radius: 8px; flex: 1; padding: 18px 0;" disabled data-i18n="script_split_btn">${window.t ? window.t('script_split_btn') : '拆分幕'}</button>
                <button class="gen-btn gen-btn-white script-grid-only-btn" type="button" style="border-radius: 8px; flex: 1; padding: 18px 0;" data-i18n="script_grid_only_btn">${window.t ? window.t('script_grid_only_btn') : '宫格生图'}</button>
              </div>
              <div class="gen-meta script-status" style="display:none; margin-top: 6px;"></div>
              <div class="gen-meta script-grid-only-status" style="display:none; margin-top: 6px;"></div>
            </div>
            <div class="field field-always-visible">
              <button class="gen-btn gen-btn-green script-split-grid-btn" type="button" style="border-radius: 8px; width: 100%; padding: 18px 0;" data-i18n="script_split_grid_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>${window.t ? window.t('script_split_grid_btn') : '拆分幕 + 宫格生图'}</button>
              <div class="gen-meta script-grid-status" style="display:none; margin-top: 6px;"></div>
            </div>
            <div class="field field-always-visible">
              <button class="gen-btn gen-btn-blue script-batch-generate-btn" type="button" style="border-radius: 8px; width: 100%; background: #3b82f6; color: white; padding: 18px 0;" data-i18n="script_batch_generate_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><polygon points="5 3 19 12 5 21 5 3"/></svg>${window.t ? window.t('script_batch_generate_btn') : '逐个生成视频'}</button>
              <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;" data-i18n="script_batch_info">${window.t ? window.t('script_batch_info') : '支持所有模型，逐个生成可能浪费时长'}</div>
              <div class="gen-meta script-batch-status" style="display:none; margin-top: 6px;"></div>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const outputPort = el.querySelector('.port.output');
      const textareaEl = el.querySelector('.script-textarea');
      const fileEl = el.querySelector('.script-file');
      const loadBtn = el.querySelector('.script-load-btn');
      const expandBtn = el.querySelector('.script-expand-btn');
      const durationSelectEl = el.querySelector('.script-duration-select');
      const forceMediumShotEl = el.querySelector('.script-force-medium-shot');
      const noBgMusicEl = el.querySelector('.script-no-bg-music');
      const splitMultiDialogueEl = el.querySelector('.script-split-multi-dialogue');
      const sequenceModeSelectEl = el.querySelector('.script-sequence-mode');
      const enableSplitQcEl = el.querySelector('.script-enable-split-qc');
      const qcRoundsFieldEl = el.querySelector('.script-qc-rounds-field');
      const qcMaxRoundsSelectEl = el.querySelector('.script-qc-max-rounds');
      const dialogueLanguageSelectEl = el.querySelector('.script-dialogue-language');
      const dialogueLanguageCustomEl = el.querySelector('.script-dialogue-language-custom');
      const promptLanguageSelectEl = el.querySelector('.script-prompt-language');
      const promptLanguageCustomEl = el.querySelector('.script-prompt-language-custom');
      const infoField = el.querySelector('.script-info-field');
      const nameEl = el.querySelector('.script-name');
      const lengthEl = el.querySelector('.script-length');
      const splitBtn = el.querySelector('.script-split-btn');
      const statusEl = el.querySelector('.script-status');
      const charCountEl = el.querySelector('.script-char-count');
      const warningField = el.querySelector('.script-warning-field');
      const videoModelSelect = el.querySelector('.script-video-model');
      const gridModelSelect = el.querySelector('.script-grid-model');
      const splitGridBtn = el.querySelector('.script-split-grid-btn');
      const gridStatusEl = el.querySelector('.script-grid-status');
      const gridOnlyBtn = el.querySelector('.script-grid-only-btn');
      const gridOnlyStatusEl = el.querySelector('.script-grid-only-status');
      const batchGenerateBtn = el.querySelector('.script-batch-generate-btn');
      const batchStatusEl = el.querySelector('.script-batch-status');
      const uploadBtn = el.querySelector('.script-upload-btn');
      const splitModelSelect = el.querySelector('.script-split-model');
      const enableThinkingEl = el.querySelector('.script-enable-thinking');
      const thinkingEffortEl = el.querySelector('.script-thinking-effort');
      const thinkingModeFieldEl = el.querySelector('.script-thinking-mode-field');

      // 上传按钮点击时触发隐藏的文件输入框
      if(uploadBtn && fileEl) {
        uploadBtn.addEventListener('click', () => fileEl.click());
      }

      // 动态填充视频模型选项
      function populateScriptVideoModelOptions() {
        if(!videoModelSelect) return;

        function renderOptions() {
          if(!videoModelSelect) return;
          videoModelSelect.innerHTML = '';

          // 从后端配置获取第一个视频模型作为默认值
          let firstVideoModelValue = 'wan22';
          if(window.TaskConfig && window.TaskConfig.isLoaded()) {
            // 使用 getAllTasks 获取完整任务数据（含 provider 字段）
            const allTasks = window.TaskConfig.getAllTasks();
            let tasks = allTasks.filter(t =>
              !t.hidden &&
              (t.category === 'image_to_video' || t.categories?.includes('image_to_video'))
            ).map(t => ({
              ...t,
              value: t.short_key || t.key,
              taskType: t.id,
            }));
            if (typeof filterVideoOptionsByDriver === 'function') {
              tasks = filterVideoOptionsByDriver(tasks);
            } else if (window.TaskConfig.filterAvailableModelOptions) {
              const driverStatus = typeof getDriverStatusConfig === 'function' ? getDriverStatusConfig() : {};
              tasks = window.TaskConfig.filterAvailableModelOptions(tasks, driverStatus);
            }

            // 从 providers 获取显示名称映射（动态来自后端，无硬编码）
            const providers = window.TaskConfig.getProviders() || {};
            const providerIcons = { duomi: '☁️', runninghub: '🚀', vidu: '🎬', volcengine: '🌋', local: '💻' };

            // 按 provider 分组
            const providerGroups = {};
            const providerOrder = [];

            tasks.forEach(task => {
              const provider = task.provider || 'unknown';
              if (!providerGroups[provider]) {
                providerGroups[provider] = [];
                providerOrder.push(provider);
              }
              providerGroups[provider].push(task);
            });

            // 按 provider 分组渲染
            providerOrder.forEach(provider => {
              const optGroup = document.createElement('optgroup');
              const icon = providerIcons[provider] || '📦';
              const providerName = providers[provider] || provider;
              optGroup.label = `${icon} ${providerName}`;

              providerGroups[provider].forEach(task => {
                const shortKey = task.short_key || task.key;
                const power = typeof task.computing_power === 'object'
                  ? Object.values(task.computing_power)[0]
                  : task.computing_power;
                const optEl = document.createElement('option');
                optEl.value = shortKey;
                optEl.textContent = `${task.name} (${power}算力)`;
                optGroup.appendChild(optEl);
              });

              if (optGroup.children.length) {
                videoModelSelect.appendChild(optGroup);
              }
            });

            if (tasks.length > 0) {
              firstVideoModelValue = tasks[0].value || tasks[0].short_key || tasks[0].key;
            }
            if (window.ModelCatalog) {
              const valueHit = window.ModelCatalog.findTaskByTrack(tasks, 'video.image_to_video', null, 'value');
              if (valueHit && (valueHit.value || valueHit.short_key)) {
                firstVideoModelValue = valueHit.value || valueHit.short_key;
              }
            }
          } else {
            // 回退：硬编码选项
            const fallbackOptions = [
              { value: 'wan22', label: 'Wan2.2' },
              { value: 'sora2', label: 'Sora2' },
              { value: 'ltx2', label: 'LTX2.0' },
              { value: 'kling', label: '可灵' },
              { value: 'vidu', label: 'Vidu' },
              { value: 'veo3', label: 'VEO3.1' }
            ];
            fallbackOptions.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              videoModelSelect.appendChild(optEl);
            });
          }

          // 恢复之前的选择，默认使用后端配置的第一个模型（与分镜组节点和图生图片节点一致）
          const currentValue = node.data.videoModel || firstVideoModelValue;
          // 确保已保存的视频模型值在下拉框中可见（防止TaskConfig未加载时硬编码选项不包含已保存值）
          ensureSelectHasSavedOption(videoModelSelect, currentValue);
          const selectedOption = videoModelSelect.querySelector(`option[value="${currentValue}"]`);
          if(selectedOption) {
            videoModelSelect.value = currentValue;
          } else {
            videoModelSelect.value = firstVideoModelValue;
            node.data.videoModel = firstVideoModelValue;
          }
          if (typeof applyDriverStatusToSelect === 'function') {
            applyDriverStatusToSelect(videoModelSelect, node.data.videoModel);
          }
        }

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          renderOptions();
        } else if(window.TaskConfig) {
          videoModelSelect.innerHTML = '<option value="">加载中...</option>';
          window.TaskConfig.onLoaded(() => {
            renderOptions();
            if(typeof updateParamGroupSummaries === 'function') updateParamGroupSummaries();
          });
        } else {
          renderOptions();
        }
      }

      // 初始化视频模型
      populateScriptVideoModelOptions();
      node.populateScriptVideoModelOptions = populateScriptVideoModelOptions;
      
      // 视频模型切换事件
      if(videoModelSelect) {
        videoModelSelect.addEventListener('change', () => {
          node.data.videoModel = videoModelSelect.value;
          if(typeof updateParamGroupSummaries === 'function') updateParamGroupSummaries();
          console.log(`[剧本节点] 视频模型切换为: ${videoModelSelect.value}`);
        });
      }

      // 拆分模型：加载可用模型列表
      async function populateScriptSplitModelOptions() {
        if(!splitModelSelect) return;

        // 如果已经加载过（全局缓存），直接使用
        if(window._scriptSplitModels && window._scriptSplitModels.length > 0) {
          renderSplitModelOptions(window._scriptSplitModels, window._vendorIcons);
          return;
        }

        try {
          // 加载供应商列表及图标
          const vendorResponse = await fetch('/api/vendors');
          const vendorData = await vendorResponse.json();
          const vendorIcons = {};
          if(vendorData.success && vendorData.vendors) {
            vendorData.vendors.forEach(v => {
              vendorIcons[v.vendor_name.toLowerCase()] = v.icon || '📦';
            });
          }
          window._vendorIcons = vendorIcons;

          const response = await fetch('/api/models?scene=llm.script_split', {
            headers: getAuthHeaders()
          });
          const data = await response.json();

          window._scriptSplitCatalog = data.catalog || null;
          if(!data.success || !data.models || data.models.length === 0) {
            // 加载失败时使用默认模型
            if(splitModelSelect) {
              splitModelSelect.innerHTML = '<option value="deepseek-v4-flash">DeepSeek V4 Flash (默认)</option>';
            }
            return;
          }

          // 按指定顺序排序：deepseek-v4 > qwen3.5 > qwen3.6 > flash-3.0 > flash-3.5 > flash > gemini-3-flash > gemini-3.1-flash-lite > 其他
          const sortOrder = ['deepseek-v4', 'qwen3.5', 'qwen3.6', 'flash-3.0', 'flash-3.5', 'flash', 'gemini-3-flash', 'gemini-3.1-flash-lite'];
          const sortedModels = [...data.models].sort((a, b) => {
            const nameA = (a.model_name || a.name || '').toLowerCase();
            const nameB = (b.model_name || b.name || '').toLowerCase();
            const indexA = sortOrder.findIndex(k => nameA.startsWith(k.toLowerCase()));
            const indexB = sortOrder.findIndex(k => nameB.startsWith(k.toLowerCase()));
            if (indexA !== -1 && indexB !== -1) return indexA - indexB;
            if (indexA !== -1) return -1;
            if (indexB !== -1) return 1;
            return 0;
          });

          // 缓存到全局变量
          window._scriptSplitModels = sortedModels;
          renderSplitModelOptions(sortedModels, vendorIcons);

        } catch (error) {
          console.error('加载拆分模型列表失败:', error);
          if(splitModelSelect) {
            splitModelSelect.innerHTML = '<option value="deepseek-v4-flash">DeepSeek V4 Flash (默认)</option>';
          }
        }
      }

      function appendSplitOption(parent, model, labelOverride) {
        const option = document.createElement('option');
        const modelName = model.model_name || model.name || '';
        const modelDesc = model.note || model.description || '';
        option.value = modelName;
        option.textContent = labelOverride || (modelDesc ? `${modelName} - ${modelDesc}` : modelName);
        const modelId = model.id ?? model.model_id ?? '';
        if(modelId) option.dataset.modelId = modelId;
        option.dataset.vendorId = model.vendor_id || 1;
        option.dataset.vendorName = model.vendor_name || 'unknown';
        option.dataset.supportsThinking = model.supports_thinking ? 'true' : 'false';
        if(model.context_window) option.dataset.contextWindow = model.context_window;
        parent.appendChild(option);
        return option;
      }

      function renderSplitModelOptions(models, vendorIcons = {}) {
        if(!splitModelSelect) return;
        splitModelSelect.innerHTML = '';

        let firstEnabled = null;
        const catalogApi = window.ModelCatalog;
        const collapsed = catalogApi
          ? catalogApi.collapseLlmModels(models, 'llm.script_split', window._scriptSplitCatalog || null)
          : [];

        if (collapsed.length) {
          const recGroup = document.createElement('optgroup');
          recGroup.label = '推荐';
          collapsed.filter((item) => item.track === 'value' || item.track === 'quality').forEach((item) => {
            const route = item.defaultRoute || item.routes[0];
            const badge = item.track === 'value' ? '性价比' : '效果';
            const opt = appendSplitOption(recGroup, route, `${item.name}（${badge}）`);
            if (!firstEnabled) firstEnabled = opt;
          });
          if (recGroup.children.length) splitModelSelect.appendChild(recGroup);

          const families = {};
          collapsed.forEach((item) => {
            if (item.track === 'value' || item.track === 'quality') return;
            const family = item.family || '其它';
            if (!families[family]) families[family] = [];
            families[family].push(item);
          });
          Object.keys(families).forEach((family) => {
            const g = document.createElement('optgroup');
            g.label = family;
            families[family].forEach((item) => {
              const opt = appendSplitOption(g, item.defaultRoute || item.routes[0]);
              if (!firstEnabled) firstEnabled = opt;
            });
            splitModelSelect.appendChild(g);
          });

          const extras = document.createElement('optgroup');
          extras.label = '换供应商';
          collapsed.forEach((item) => {
            const def = item.defaultRoute;
            (item.routes || []).forEach((route) => {
              if (!def) return;
              if (String(route.vendor_id) === String(def.vendor_id)
                && String(route.model_id || route.id) === String(def.model_id || def.id)) return;
              appendSplitOption(extras, route, `${route.name || route.model_name}（${route.vendor_name}）`);
            });
          });
          if (extras.children.length) splitModelSelect.appendChild(extras);
        } else {
          models.forEach((model) => {
            const opt = appendSplitOption(splitModelSelect, model);
            if (!firstEnabled) firstEnabled = opt;
          });
        }

        if (catalogApi && splitModelSelect.parentElement) {
          catalogApi.bindSelectTrack(splitModelSelect.parentElement, splitModelSelect, 'llm.script_split', 'llm');
        }

        // 恢复已保存的拆分模型选择，若无保存值则按优先级选择默认模型
        const savedSplitModel = node.data.splitModel;
        let restored = false;
        if(savedSplitModel) {
          const savedOption = splitModelSelect.querySelector(`option[value="${savedSplitModel}"]`);
          if(savedOption && !savedOption.disabled) {
            savedOption.selected = true;
            node.data.splitModelId = savedOption.dataset.modelId || '';
            node.data.splitModelVendorId = savedOption.dataset.vendorId || '';
            node.data.splitModelVendorName = savedOption.dataset.vendorName || '';
            restored = true;
          }
        }
        if(!restored) {
          const allOptions = splitModelSelect.querySelectorAll('option');
          let defaultOption = null;
          if (window.ModelCatalog) {
            const tracks = window.ModelCatalog.tracksFromCatalog(null, 'llm.script_split');
            defaultOption = Array.from(allOptions).find((opt) => (
              !opt.disabled && opt.value && window.ModelCatalog.matchCanonical(opt.value, tracks.value)
              && (opt.dataset.vendorName || '') === 'deepseek'
            )) || Array.from(allOptions).find((opt) => (
              !opt.disabled && opt.value && window.ModelCatalog.matchCanonical(opt.value, tracks.value)
            )) || null;
          }
          if (!defaultOption) {
            defaultOption = Array.from(allOptions).find((opt) => (
              !opt.disabled && opt.value && opt.value.includes('deepseek-v4-flash')
              && opt.dataset.vendorName === 'deepseek'
            )) || null;
          }
          if (!defaultOption && firstEnabled) {
            defaultOption = firstEnabled;
            console.log(`[剧本节点-拆分模型] 未找到推荐模型，选择第一个启用的模型: ${firstEnabled.value}`);
          }

          if (defaultOption) {
            defaultOption.selected = true;
            node.data.splitModel = defaultOption.value;
            node.data.splitModelId = defaultOption.dataset.modelId || '';
            node.data.splitModelVendorId = defaultOption.dataset.vendorId || '';
            node.data.splitModelVendorName = defaultOption.dataset.vendorName || '';
          }
        }
      }

      // 初始化拆分模型
      if(node.data.enableThinking === undefined) node.data.enableThinking = false;
      if(!node.data.thinkingEffort) node.data.thinkingEffort = 'medium';
      if(node.data.thinkingExplicitlyDisabled === undefined) node.data.thinkingExplicitlyDisabled = false;

      // 思考模式对齐 script_writer / storyboard：
      // - supports_thinking 或 DeepSeek：显示「开启思考」开关
      // - 仅豆包（volcengine / doubao*）在开启后显示 低/中/高 effort
      // - DeepSeek 只支持开关，不展示 effort
      function isThinkingModelOption(option) {
        if(!option) return false;
        const vendorName = (option.dataset.vendorName || '').toLowerCase();
        const modelValue = (option.value || '').toLowerCase();
        const textValue = (option.textContent || '').toLowerCase();
        return option.dataset.supportsThinking === 'true'
          || vendorName === 'deepseek'
          || modelValue.includes('deepseek')
          || textValue.includes('deepseek');
      }

      function isDeepSeekModelOption(option) {
        if(!option) return false;
        const vendorName = (option.dataset.vendorName || '').toLowerCase();
        const modelValue = (option.value || '').toLowerCase();
        const textValue = (option.textContent || '').toLowerCase();
        return vendorName === 'deepseek'
          || modelValue.includes('deepseek')
          || textValue.includes('deepseek');
      }

      function isDoubaoEffortModelOption(option) {
        if(!option) return false;
        const vendorName = (option.dataset.vendorName || '').toLowerCase();
        const modelValue = (option.value || '').toLowerCase();
        const textValue = (option.textContent || '').toLowerCase();
        // 与 script_writer.updateThinkingEffortVisibility / storyboard isDoubaoEffort 一致
        return vendorName === 'volcengine'
          || modelValue.startsWith('doubao')
          || modelValue.includes('doubao')
          || textValue.includes('doubao')
          || textValue.includes('豆包');
      }

      function updateThinkingModeVisibility() {
        if(!splitModelSelect || !thinkingModeFieldEl) return;
        const selected = splitModelSelect.options[splitModelSelect.selectedIndex];
        const supportsThinking = isThinkingModelOption(selected);
        thinkingModeFieldEl.style.display = supportsThinking ? 'block' : 'none';
        if(thinkingEffortEl) {
          const showEffort = supportsThinking
            && enableThinkingEl
            && enableThinkingEl.checked
            && isDoubaoEffortModelOption(selected);
          thinkingEffortEl.style.display = showEffort ? 'inline-block' : 'none';
        }
      }

      function syncThinkingModeFromSelectedModel() {
        if(!splitModelSelect) return;
        const selected = splitModelSelect.options[splitModelSelect.selectedIndex];
        const supportsThinking = isThinkingModelOption(selected);
        const shouldDefaultEnable = supportsThinking
          && isDeepSeekModelOption(selected)
          && !node.data.thinkingExplicitlyDisabled;

        if(!supportsThinking) {
          node.data.enableThinking = false;
        } else if(shouldDefaultEnable) {
          node.data.enableThinking = true;
        }

        if(enableThinkingEl) enableThinkingEl.checked = node.data.enableThinking === true;
        if(thinkingEffortEl) thinkingEffortEl.value = node.data.thinkingEffort || 'medium';
        updateThinkingModeVisibility();
      }

      if(enableThinkingEl) {
        enableThinkingEl.checked = node.data.enableThinking === true;
        enableThinkingEl.addEventListener('change', () => {
          node.data.enableThinking = enableThinkingEl.checked;
          node.data.thinkingExplicitlyDisabled = !enableThinkingEl.checked;
          updateThinkingModeVisibility();
        });
      }

      if(thinkingEffortEl) {
        thinkingEffortEl.value = node.data.thinkingEffort || 'medium';
        thinkingEffortEl.addEventListener('change', () => {
          node.data.thinkingEffort = thinkingEffortEl.value;
        });
      }

      populateScriptSplitModelOptions();
      syncThinkingModeFromSelectedModel();

      // 拆分模型切换事件
      if(splitModelSelect) {
        splitModelSelect.addEventListener('change', () => {
          const selected = splitModelSelect.options[splitModelSelect.selectedIndex];
          node.data.splitModel = splitModelSelect.value;
          node.data.splitModelId = selected.dataset.modelId || '';
          node.data.splitModelVendorId = selected.dataset.vendorId || '';
          node.data.splitModelVendorName = selected.dataset.vendorName || '';
          syncThinkingModeFromSelectedModel();
          console.log(`[剧本节点] 拆分模型切换为: ${splitModelSelect.value}, modelId: ${node.data.splitModelId}, vendor: ${node.data.splitModelVendorName}`);
        });
      }

      // 动态填充宫格生图模型选项
      function populateScriptGridModelOptions() {
        if(!gridModelSelect) return;

        function renderOptions() {
          if(!gridModelSelect) return;
          node.data.gridModel = populateGridImageModelSelect(gridModelSelect, node.data.gridModel);
          if(typeof updateParamGroupSummaries === 'function') updateParamGroupSummaries();
        }

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          renderOptions();
        } else if(window.TaskConfig) {
          node.data.gridModel = populateGridImageModelSelect(gridModelSelect, node.data.gridModel);
          window.TaskConfig.onLoaded(() => {
            renderOptions();
          });
        } else {
          renderOptions();
        }
      }

      // 初始化宫格生图模型
      populateScriptGridModelOptions();
      
      // 初始化节点数据中的最大时长和选项（仅设置默认值，不覆盖已保存的值）
      if(node.data.maxGroupDuration === undefined) node.data.maxGroupDuration = 15;
      if(node.data.forceMediumShot === undefined) node.data.forceMediumShot = true;
      if(node.data.noBgMusic === undefined) node.data.noBgMusic = true;
      if(node.data.splitMultiDialogue === undefined) node.data.splitMultiDialogue = false;
      // 与故事板默认一致：均衡模式；质检默认关闭
      if(!['speed', 'balanced', 'quality'].includes(node.data.sequenceMode)) {
        node.data.sequenceMode = 'balanced';
      }
      if(node.data.enableScriptSplitQc === undefined) node.data.enableScriptSplitQc = false;
      if(![1, 2, 3, 4, 5].includes(Number(node.data.scriptSplitQcMaxRounds))) {
        node.data.scriptSplitQcMaxRounds = 2;
      } else {
        node.data.scriptSplitQcMaxRounds = Number(node.data.scriptSplitQcMaxRounds);
      }
      if(!node.data.dialogueLanguage) node.data.dialogueLanguage = node.data.language || '';
      if(!node.data.promptLanguage) node.data.promptLanguage = node.data.language || '';
      if(!node.data.gridModel) node.data.gridModel = 'auto';
      if(!node.data.splitModelVendorId) node.data.splitModelVendorId = '';
      if(!node.data.splitModelVendorName) node.data.splitModelVendorName = '';
      // 参数区分组折叠态（默认全部折叠；开启质检时 advanced 自动展开）
      if(!node.data.uiSections || typeof node.data.uiSections !== 'object') {
        node.data.uiSections = { gridVideo: false, language: false, advanced: false };
      } else {
        node.data.uiSections = {
          gridVideo: node.data.uiSections.gridVideo === true,
          language: node.data.uiSections.language === true,
          advanced: node.data.uiSections.advanced === true || node.data.enableScriptSplitQc === true,
        };
      }

      function isEnterpriseEdition() {
        return state.editionInfo && state.editionInfo.mode === 'enterprise';
      }

      function setParamGroupOpen(groupKey, open) {
        const groupEl = el.querySelector(`.script-param-group[data-script-group="${groupKey}"]`);
        if(!groupEl) return;
        const toggle = groupEl.querySelector('.script-param-group-toggle');
        const body = groupEl.querySelector('.script-param-group-body');
        const chevron = groupEl.querySelector('.script-param-group-chevron');
        const isOpen = open === true;
        groupEl.classList.toggle('is-open', isOpen);
        if(toggle) toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        if(body) body.hidden = !isOpen;
        if(chevron) chevron.textContent = isOpen ? '▼' : '▶';
        if(!node.data.uiSections) node.data.uiSections = {};
        node.data.uiSections[groupKey] = isOpen;
      }

      function selectOptionLabel(selectEl) {
        if(!selectEl || selectEl.selectedIndex < 0) return '';
        const opt = selectEl.options[selectEl.selectedIndex];
        return (opt && (opt.textContent || opt.label) || '').trim();
      }

      function languageSummaryText(value) {
        if(!value) return st('script_language_default', '中文（默认）');
        return value;
      }

      function updateParamGroupSummaries() {
        const gridSummary = el.querySelector('.script-grid-video-summary');
        if(gridSummary) {
          const gridLabel = selectOptionLabel(gridModelSelect) || (node.data.gridModel || '');
          const videoLabel = selectOptionLabel(videoModelSelect) || (node.data.videoModel || '');
          const parts = [];
          if(gridLabel) parts.push(gridLabel);
          if(videoLabel) parts.push(videoLabel);
          gridSummary.textContent = parts.length ? parts.join(' · ') : '';
          gridSummary.title = parts.join(' · ');
        }
        const langSummary = el.querySelector('.script-language-summary');
        if(langSummary) {
          const d = languageSummaryText(node.data.dialogueLanguage || '');
          const p = languageSummaryText(node.data.promptLanguage || '');
          const text = d === p ? d : `${d} / ${p}`;
          langSummary.textContent = text;
          langSummary.title = text;
        }
        const advSummary = el.querySelector('.script-advanced-summary');
        if(advSummary) {
          if(node.data.enableScriptSplitQc) {
            const n = node.data.scriptSplitQcMaxRounds || 2;
            advSummary.textContent = `质检开 · ${n} 次`;
          } else {
            advSummary.textContent = '质检关';
          }
        }
      }

      function syncQcRoundsVisibility() {
        if(!qcRoundsFieldEl || !enableSplitQcEl) return;
        qcRoundsFieldEl.style.display = enableSplitQcEl.checked ? 'block' : 'none';
      }

      function syncSequenceModeUi() {
        if(!sequenceModeSelectEl) return;
        // 社区版禁止选中效果模式
        if(node.data.sequenceMode === 'quality' && !isEnterpriseEdition()) {
          node.data.sequenceMode = 'balanced';
        }
        sequenceModeSelectEl.value = node.data.sequenceMode || 'balanced';
        const qualityOpt = sequenceModeSelectEl.querySelector('option[value="quality"]');
        if(qualityOpt) {
          qualityOpt.disabled = !isEnterpriseEdition();
        }
      }

      // 绑定参数分组折叠
      el.querySelectorAll('.script-param-group').forEach((groupEl) => {
        const key = groupEl.dataset.scriptGroup;
        if(!key) return;
        const toggle = groupEl.querySelector('.script-param-group-toggle');
        if(toggle) {
          toggle.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const nextOpen = !(node.data.uiSections && node.data.uiSections[key]);
            setParamGroupOpen(key, nextOpen);
          });
          // 阻止拖拽节点时误触
          toggle.addEventListener('mousedown', (e) => e.stopPropagation());
        }
        setParamGroupOpen(key, !!(node.data.uiSections && node.data.uiSections[key]));
      });
      // 暴露给重载逻辑
      node.setParamGroupOpen = setParamGroupOpen;
      node.updateParamGroupSummaries = updateParamGroupSummaries;

      if(sequenceModeSelectEl) {
        syncSequenceModeUi();
        sequenceModeSelectEl.addEventListener('change', () => {
          const next = sequenceModeSelectEl.value;
          if(next === 'quality' && !isEnterpriseEdition()) {
            showToast(st('script_sequence_mode_quality_locked', '效果模式仅商业版支持，请购买商业版后使用'), 'warning');
            sequenceModeSelectEl.value = node.data.sequenceMode || 'balanced';
            return;
          }
          if(['speed', 'balanced', 'quality'].includes(next)) {
            node.data.sequenceMode = next;
          }
        });
      }

      if(enableSplitQcEl) {
        enableSplitQcEl.checked = node.data.enableScriptSplitQc === true;
        syncQcRoundsVisibility();
        enableSplitQcEl.addEventListener('change', () => {
          node.data.enableScriptSplitQc = enableSplitQcEl.checked;
          syncQcRoundsVisibility();
          if(enableSplitQcEl.checked) {
            setParamGroupOpen('advanced', true);
          }
          updateParamGroupSummaries();
        });
      }
      if(qcMaxRoundsSelectEl) {
        qcMaxRoundsSelectEl.value = String(node.data.scriptSplitQcMaxRounds || 2);
        qcMaxRoundsSelectEl.addEventListener('change', () => {
          const n = parseInt(qcMaxRoundsSelectEl.value, 10);
          if([1, 2, 3, 4, 5].includes(n)) {
            node.data.scriptSplitQcMaxRounds = n;
            updateParamGroupSummaries();
          }
        });
      }

      // 确保已保存的宫格模型值在下拉框中可见，并恢复选中状态
      if(gridModelSelect) {
        node.data.gridModel = normalizeGridImageModelValue(node.data.gridModel);
        ensureSelectHasSavedOption(gridModelSelect, node.data.gridModel);
        gridModelSelect.value = node.data.gridModel;
      }

      // 应用驱动状态禁用未配置的宫格生图模型选项
      if(gridModelSelect) applyDriverStatusToSelect(gridModelSelect);

      // 更新字符计数器
      function updateCharCount(length) {
        charCountEl.textContent = `${length}/30000`;
        if(length > 28500) {
          charCountEl.style.color = '#dc2626';
        } else if(length > 25500) {
          charCountEl.style.color = '#f59e0b';
        } else {
          charCountEl.style.color = '#666';
        }
      }

      // 更新剧本内容和按钮状态
      function updateScriptContent(content, source) {
        node.data.scriptContent = content;
        updateCharCount(content.length);
        
        if(content && content.trim().length > 0) {
          splitBtn.disabled = false;
          nameEl.textContent = source;
          lengthEl.textContent = `长度: ${content.length} 字符`;
          infoField.style.display = 'block';
        } else {
          splitBtn.disabled = true;
          infoField.style.display = 'none';
        }
      }

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      // 时长选择监听
      durationSelectEl.addEventListener('change', () => {
        node.data.maxGroupDuration = parseInt(durationSelectEl.value);
      });

      // 对话强制中景选项监听
      forceMediumShotEl.addEventListener('change', () => {
        node.data.forceMediumShot = forceMediumShotEl.checked;
      });

      // 不生成背景音乐选项监听
      noBgMusicEl.addEventListener('change', () => {
        node.data.noBgMusic = noBgMusicEl.checked;
      });

      // 拆分多人对话选项监听
      splitMultiDialogueEl.addEventListener('change', () => {
        node.data.splitMultiDialogue = splitMultiDialogueEl.checked;
      });


      // 语言选择监听 - 对话语言
      function bindLanguageSelect(selectEl, customEl, dataKey) {
        if(!selectEl) return;
        selectEl.addEventListener('change', () => {
          if(selectEl.value === '__custom__') {
            customEl.style.display = 'block';
            customEl.focus();
            node.data[dataKey] = customEl.value;
          } else {
            customEl.style.display = 'none';
            node.data[dataKey] = selectEl.value;
          }
          updateParamGroupSummaries();
        });
        customEl.addEventListener('input', () => {
          node.data[dataKey] = customEl.value;
          updateParamGroupSummaries();
        });
        // 恢复之前的选择
        if(node.data[dataKey]) {
          const presetValues = ['', 'English', 'Deutsch', 'Français', 'Русский'];
          if(presetValues.includes(node.data[dataKey])) {
            selectEl.value = node.data[dataKey];
            customEl.style.display = 'none';
          } else {
            selectEl.value = '__custom__';
            customEl.style.display = 'block';
            customEl.value = node.data[dataKey];
          }
        }
      }
      bindLanguageSelect(dialogueLanguageSelectEl, dialogueLanguageCustomEl, 'dialogueLanguage');
      bindLanguageSelect(promptLanguageSelectEl, promptLanguageCustomEl, 'promptLanguage');

      // 监听右上角语言切换，联动更新剧本提示词语言
      if(window.ZJTi18n && promptLanguageSelectEl) {
        const _localeChangedHandler = ({ locale }) => {
          // 根据界面语言自动设置提示词语言
          const localeToLanguage = {
            'en': 'English',
            'zh-CN': ''
          };
          const newLanguage = localeToLanguage[locale];
          if(newLanguage !== undefined) {
            // 更新节点数据
            node.data.promptLanguage = newLanguage;
            // 更新下拉框显示
            const presetValues = ['', 'English', 'Deutsch', 'Français', 'Русский'];
            if(presetValues.includes(newLanguage)) {
              promptLanguageSelectEl.value = newLanguage;
              promptLanguageCustomEl.style.display = 'none';
            } else {
              promptLanguageSelectEl.value = '__custom__';
              promptLanguageCustomEl.style.display = 'block';
              promptLanguageCustomEl.value = newLanguage;
            }
          }
        };
        window.ZJTi18n.on('locale-changed', _localeChangedHandler);
        if (el._cleanupHandlers) {
          el._cleanupHandlers.push(function() { window.ZJTi18n.off('locale-changed', _localeChangedHandler); });
        }
      }

      // 宫格模型选择监听
      if(gridModelSelect) {
        gridModelSelect.addEventListener('change', () => {
          node.data.gridModel = gridModelSelect.value;
          updateParamGroupSummaries();
        });
      }

      // 宫格类型选择监听
      const gridLayoutSelect = el.querySelector('.script-grid-layout');
      if(!node.data.gridLayout){
        node.data.gridLayout = 'auto';
      }
      if(gridLayoutSelect){
        gridLayoutSelect.value = node.data.gridLayout;
        gridLayoutSelect.addEventListener('change', () => {
          node.data.gridLayout = gridLayoutSelect.value;
          updateParamGroupSummaries();
        });
      }

      // 初始化折叠摘要
      updateParamGroupSummaries();

      // 文本框输入监听
      textareaEl.addEventListener('input', () => {
        const content = textareaEl.value;
        updateScriptContent(content, '来源: 文本输入');
      });

      // 加载剧本按钮监听
      loadBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await showScriptSelectionModal(node, textareaEl, updateScriptContent, warningField);
      });

      // 放大按钮监听
      expandBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showScriptExpandModal(textareaEl, updateScriptContent, charCountEl);
      });

      // 文件上传监听
      fileEl.addEventListener('change', async () => {
        const file = fileEl.files && fileEl.files[0];
        if(!file) return;
        
        try {
          let content = await file.text();
          node.data.file = file;
          node.data.name = file.name;
          
          // 检查是否超过30000字符
          const originalLength = content.length;
          const isTruncated = originalLength > 30000;
          if(isTruncated) {
            content = content.substring(0, 30000);
            warningField.style.display = 'block';
            showToast(window.t ? window.t('file_content_truncated').replace('${originalLength}', originalLength) : `文件内容已截取至30000字符（原${originalLength}字符）`, 'warning');
          } else {
            warningField.style.display = 'none';
            showToast(window.t ? window.t('script_file_load_success') : '剧本文件加载成功', 'success');
          }

          // 更新文本框内容
          textareaEl.value = content;
          updateScriptContent(content, `来源: ${file.name}${isTruncated ? ' (已截取)' : ''}`);

          fileEl.value = '';
        } catch(error) {
          console.error('读取文件失败:', error);
          showToast(window.t ? window.t('file_read_error') : '读取文件失败', 'error');
        }
      });

      splitBtn.addEventListener('click', async (e) => {
        e.stopPropagation();

        if(!node.data.scriptContent) {
          showToast(window.t ? window.t('upload_script_file_first') : '请先上传剧本文件', 'error');
          return;
        }

        // 检查是否已有分镜组节点
        const existingShotGroups = state.connections.filter(c => c.from === id);
        if(existingShotGroups.length > 0) {
          const hasShotGroupNode = existingShotGroups.some(conn => {
            const targetNode = state.nodes.find(n => n.id === conn.to);
            return targetNode && targetNode.type === 'shot_group';
          });

          if(hasShotGroupNode) {
            showToast(window.t ? window.t('duplicate_shot_group_warning') : '已有幕，请勿重复点击', 'warning');
            return;
          }
        }

        if(!state.defaultWorldId){
          const confirmed = await showConfirmModal('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？', { title: '提示' });
          if(!confirmed){
            return;
          }
        }

        splitBtn.disabled = true;
        splitGridBtn.disabled = true;
        statusEl.style.display = 'block';
        setStatusEl(statusEl, '正在调用LLM解析剧本...', '#666');

        try {
          // 异步任务：提交后立即返回 task_id，前端轮询直到完成再物化节点。
          // 见 docs/script/script_parser_incremental_split_design.md §14。
          const submitData = await window.ScriptSplitTask.submitSplitTask(node.data, state.defaultWorldId);
          const taskId = submitData.task_id;
          node.data.splitTaskId = taskId;
          node.data.splitTaskMode = 'split';
          node.data.splitTaskResultApplied = false;
          safeAutoSave();

          window.ScriptSplitTask.pollScriptSplitTask(taskId, {
            onUpdate: (status) => {
              setStatusEl(statusEl, status.message || '拆分中…', '#666');
            },
            onComplete: async (parsedData) => {
              try {
                await applyParsedData(parsedData);
                node.data.splitTaskResultApplied = true;
                safeAutoSave();
              } catch (e) {
                console.error('应用拆分结果失败:', e);
                setStatusEl(statusEl, '应用结果失败: ' + (e.message || ''), '#dc2626');
              } finally {
                splitBtn.disabled = false;
                splitGridBtn.disabled = false;
              }
            },
            onPaused: (status) => {
              // paused / waiting_auth：显示继续按钮，不自动重启用
              setStatusEl(statusEl, status.error_message || status.message || '任务暂停，等待处理', '#d97706');
              splitBtn.disabled = false;
              splitGridBtn.disabled = false;
            },
            onError: (error) => {
              console.error('剧本拆分失败:', error);
              setStatusEl(statusEl, '拆分失败: ' + (error.message || '未知错误'), '#dc2626');
              showToast(window.t ? window.t('script_parse_error') : '剧本解析失败', 'error');
              splitBtn.disabled = false;
              splitGridBtn.disabled = false;
            },
          });
        } catch(error) {
          console.error('提交拆分任务失败:', error);
          setStatusEl(statusEl, '提交失败: ' + (error.message || '未知错误'), '#dc2626');
          showToast(window.t ? window.t('script_parse_error') : '剧本解析失败', 'error');
          splitBtn.disabled = false;
          splitGridBtn.disabled = false;
        }
      });

      // 将拆分结果物化为柱子、分镜组节点和分镜帧。
      // 提取为局部函数，供拆分幕、宫格生图、刷新恢复复用（幂等：跳过已存在节点）。
      async function applyParsedData(parsedData, opts) {
        opts = opts || {};
        const autoGenerateFrames = opts.autoGenerateFrames !== false;
        if (!parsedData || !parsedData.shot_groups || parsedData.shot_groups.length === 0) {
          setStatusEl(statusEl, '解析结果无分镜组', '#dc2626');
          return;
        }
        node.data.parsedData = parsedData;
        const groupCount = parsedData.shot_groups.length;
        setStatusEl(statusEl, `解析成功！共${groupCount}个幕`, '#16a34a');
        if (window.TaskConfig && !window.TaskConfig.isLoaded()) {
          await window.TaskConfig.load();
        }

        // 幂等：已有分镜组节点则跳过创建
        const hasExistingShotGroup = state.nodes.some(
          n => n.type === 'shot_group' && n.data && n.data.scriptNodeId === id
        );
        if (hasExistingShotGroup) {
          setStatusEl(statusEl, `已完成：已有 ${groupCount} 个幕`, '#16a34a');
          return;
        }

        const scriptId = id;
        const maxGroupDuration = parsedData.max_group_duration || 15;
        // 预创建柱子
        parsedData.shot_groups.forEach((shotGroup) => {
          if (shotGroup.shots && Array.isArray(shotGroup.shots)) {
            shotGroup.shots.forEach((shot) => {
              if (shot.shot_number) {
                createOrUpdatePillar(scriptId, shot.shot_number, shot.duration || maxGroupDuration);
              }
            });
          }
        });

        const createdShotGroupNodes = [];
        const SPLIT_NODE_GAP_Y = 120;
        let cumulativeY = 0;
        parsedData.shot_groups.forEach((shotGroup) => {
          const shotGroupNodeId = createShotGroupNode({
            x: node.x + 800,
            y: node.y + cumulativeY,
            shotGroupData: shotGroup,
            scriptData: parsedData,
            scriptNodeId: id,  // 关联的剧本节点 ID
            scriptContent: node.data.scriptContent || ''  // 原始剧本内容
          });
          const shotGroupEl = canvasEl.querySelector(`.node[data-node-id="${shotGroupNodeId}"]`);
          const actualHeight = shotGroupEl ? shotGroupEl.offsetHeight : 300;
          cumulativeY += actualHeight + SPLIT_NODE_GAP_Y;
          if (shotGroupNodeId) {
            state.connections.push({ id: state.nextConnId++, from: id, to: shotGroupNodeId });
            createdShotGroupNodes.push(shotGroupNodeId);
          }
        });

        renderTimeline();
        if (!state.timeline.visible) flashExpandButton();
        renderAllConnections();
        renderMinimap();
        safeAutoSave();

        if (autoGenerateFrames) {
          statusEl.textContent = '正在自动生成分镜...';
          for (const shotGroupNodeId of createdShotGroupNodes) {
            const shotGroupNode = state.nodes.find(n => n.id === shotGroupNodeId);
            if (shotGroupNode) {
              await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
            }
          }
        }
        setStatusEl(statusEl, `已完成：${createdShotGroupNodes.length}个幕` + (autoGenerateFrames ? '，所有分镜已自动生成' : ''), '#16a34a');
        showToast(window.t ? window.t('script_split_complete') : '剧本拆分成功！所有分镜已自动生成', 'success');
        // 暴露给宫格按钮后续流程
        return createdShotGroupNodes;
      }

      // 暴露 applyParsedData 给宫格按钮和恢复逻辑（挂在闭包局部变量上）
      node.applyParsedData = applyParsedData;

      // 宫格生图按钮监听
      console.log('[宫格生图] 正在绑定事件监听器，按钮元素:', splitGridBtn);
      console.log('[宫格生图] 按钮是否禁用:', splitGridBtn ? splitGridBtn.disabled : 'N/A');
      
      if(!splitGridBtn) {
        console.error('[宫格生图] 错误：找不到宫格生图按钮元素！');
      }
      
      splitGridBtn.addEventListener('click', async (e) => {
        e.stopPropagation();

        if(splitGridBtn.disabled) return;
        // 宫格相关操作时展开对应分组，便于核对模型/类型
        if(typeof setParamGroupOpen === 'function') setParamGroupOpen('gridVideo', true);
        splitGridBtn.disabled = true;
        splitBtn.disabled = true;

        console.log('[宫格生图] 按钮被点击');
        
        if(!node.data.scriptContent) {
          console.log('[宫格生图] 没有剧本内容');
          showToast('请先上传剧本文件', 'error');
          splitGridBtn.disabled = false;
          splitBtn.disabled = false;
          return;
        }

        // 检查是否已有分镜组节点
        const existingShotGroupConnections = state.connections.filter(c => c.from === id);
        const existingShotGroupNodes = existingShotGroupConnections
          .map(conn => state.nodes.find(n => n.id === conn.to))
          .filter(n => n && n.type === 'shot_group');
        
        console.log(`[宫格生图] 找到 ${existingShotGroupNodes.length} 个已存在的分镜组节点`);
        
        // 检查这些分镜组是否已有分镜节点
        if(existingShotGroupNodes.length > 0) {
          const shotGroupsWithFrames = existingShotGroupNodes.filter(shotGroupNode => {
            const shotFrameConnections = state.connections.filter(c => c.from === shotGroupNode.id);
            const hasShotFrames = shotFrameConnections.some(c => {
              const targetNode = state.nodes.find(n => n.id === c.to);
              return targetNode && targetNode.type === 'shot_frame';
            });
            return hasShotFrames;
          });
          
          console.log(`[宫格生图] 其中 ${shotGroupsWithFrames.length} 个分镜组有分镜节点`);
          
          if(shotGroupsWithFrames.length > 0) {
            showToast('已有幕和分镜节点，请勿重复点击', 'warning');
            splitGridBtn.disabled = false;
            splitBtn.disabled = false;
            return;
          }
          
          // 如果分镜组存在但没有分镜节点，直接使用现有分镜组生成分镜节点
          if(existingShotGroupNodes.length > 0) {
            console.log(`[宫格生图] 分镜组已存在但无分镜节点，将复用现有分镜组`);
            gridStatusEl.style.display = 'block';
            gridStatusEl.style.color = '#666';
            gridStatusEl.textContent = '正在生成分镜节点...';
            
            try {
              const allShotFrameNodes = [];
              
              for(const shotGroupNode of existingShotGroupNodes) {
                console.log(`[宫格生图] 处理分镜组 ${shotGroupNode.id}`);
                const shotFrameNodeIds = await generateShotFramesIndependentAsync(shotGroupNode.id, shotGroupNode);
                console.log(`[宫格生图] 分镜组 ${shotGroupNode.id} 返回的节点ID: ${shotFrameNodeIds}`);
                if(shotFrameNodeIds && shotFrameNodeIds.length > 0) {
                  const shotNodes = shotFrameNodeIds.map(nid => state.nodes.find(n => n.id === nid)).filter(Boolean);
                  console.log(`[宫格生图] 找到 ${shotNodes.length} 个有效的分镜节点`);
                  allShotFrameNodes.push(...shotNodes);
                }
              }
              
              console.log(`[宫格生图] 总共收集到 ${allShotFrameNodes.length} 个分镜节点`);
              if(allShotFrameNodes.length === 0) {
                throw new Error('未生成分镜节点');
              }
              
              // 收集参考图片URL（角色、场景、道具）
              gridStatusEl.textContent = '正在收集参考图片...';
              const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
              console.log(`[宫格生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);
              
              // 跳转到第四步：根据分镜数量决定宫格大小
              const shotCount = allShotFrameNodes.length;
              if(shotCount === 1) {
                gridStatusEl.style.color = '#f59e0b';
                gridStatusEl.textContent = '只有1个分镜，无需宫格生图';
                showToast('只有1个分镜，无需宫格生图', 'warning');
                splitGridBtn.disabled = false;
                splitBtn.disabled = false;
                return;
              }

              const gridModel = normalizeGridImageModelValue(node.data.gridModel);
              const gridLayoutPref = node.data.gridLayout || 'auto';

              // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
              const forceEnhancedModel = referenceImageUrls.length > 5;
              if(forceEnhancedModel) {
                console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
              }

              const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

              // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
              const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
              if(referenceImageUrls.length > maxRefImages) {
                console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
                referenceImageUrls.splice(maxRefImages);
                promptSuffix.splice(maxRefImages);
              }

              node.data.gridModel = finalModel;

              const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
              const imageCount = Math.ceil(shotCount / gridSize);
              const totalPower = imageCount * imagePower;

              // 获取模型显示名称
              const taskInfo = TaskConfig.getTaskByKey(finalModel);
              const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

              const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
              const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
                `分镜数量：${shotCount}个\n` +
                `模型：${modelDisplayName}${refImageInfo}\n` +
                `预计消耗算力：${totalPower}\n\n` +
                `确认生成吗？`;
              
              if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
                gridStatusEl.style.color = '#666';
                gridStatusEl.textContent = '已取消';
                splitGridBtn.disabled = false;
                splitBtn.disabled = false;
                return;
              }

              // 第五步：拼接提示词并调用API
              gridStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
              
              const gridTasks = [];
              for(let i = 0; i < imageCount; i++) {
                const startIdx = i * gridSize;
                const endIdx = Math.min(startIdx + gridSize, shotCount);
                const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
                
                const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
                
                gridTasks.push({
                  batchNodes,
                  gridPrompt,
                  startIdx
                });
              }

              // 构建参考图片说明后缀
              const refSuffixText = promptSuffix.length > 0 ? `\n\n${promptSuffix.join('，')}。` : '';
              
              const apiPromises = gridTasks.map(async (task) => {
                const form = new FormData();
                
                // 添加参考图片说明到提示词
                let finalGridPrompt = task.gridPrompt;
                if(refSuffixText) {
                  try {
                    const promptObj = JSON.parse(task.gridPrompt);
                    promptObj.reference_images_description = promptSuffix.join('，') + '。';
                    finalGridPrompt = JSON.stringify(promptObj);
                  } catch(e) {
                    finalGridPrompt = task.gridPrompt + refSuffixText;
                  }
                }
                
                form.append('prompt', finalGridPrompt);
                form.append('count', '1');
                appendAuthToForm(form);
                
                if(finalModel === 'gemini-3-pro-image-preview') {
                  form.append('image_size', '4K');
                }
                
                let apiUrl, res;
                console.log('[DEBUG-宫格生图] state.ratio:', state.ratio, 'ratioSelectEl.value:', ratioSelectEl.value, '发送比例:', state.ratio || '16:9', '模型:', finalModel);
                if(referenceImageUrls.length > 0) {
                  // 有参考图片URL，使用图片编辑API，直接传URL
                  const taskId1 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
                  if(!taskId1) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
                  form.append('task_id', taskId1);
                  form.append('ref_image_urls', referenceImageUrls.join(','));
                  form.append('ratio', state.ratio || '16:9');
                  apiUrl = '/api/image-edit';
                } else {
                  // 无参考图片，使用文生图API
                  const taskId2 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
                  if(!taskId2) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
                  form.append('task_id', taskId2);
                  form.append('aspect_ratio', state.ratio || '16:9');
                  apiUrl = '/api/text-to-image';
                }
                
                res = await fetch(apiUrl, {
                  method: 'POST',
                  body: form
                });
                
                const resText = await res.text();
                let data;
                try { data = JSON.parse(resText); } catch(e) {
                  throw new Error(`API返回异常 (HTTP ${res.status}): ${resText.slice(0, 200) || '空响应'}`);
                }
                
                if(!res.ok) {
                  const errorMsg = typeof data.detail === 'string' ? data.detail : 
                                   typeof data.message === 'string' ? data.message :
                                   JSON.stringify(data.detail || data.message || '提交任务失败');
                  throw new Error(errorMsg);
                }
                
                if(!data.project_ids || data.project_ids.length === 0) {
                  throw new Error('提交任务失败：未返回项目ID');
                }
                
                return {
                  ...task,
                  aiToolsId: data.project_ids[0]
                };
              });

              const completedTasks = await Promise.all(apiPromises);
              
              gridStatusEl.textContent = '正在创建分镜图节点...';
              
              const aiToolsMap = {};
              completedTasks.forEach((task) => {
                aiToolsMap[String(task.aiToolsId)] = {
                  batchNodes: task.batchNodes,
                  gridSize: gridSize
                };
                
                task.batchNodes.forEach((shotFrameNode, idx) => {
                  const gridIndex = idx + 1;
                  const gridImageNodeId = createImageNode({
                    x: shotFrameNode.x + 380,
                    y: shotFrameNode.y,
                    checkCollision: true
                  });
                  
                  const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
                  if(gridImageNode) {
                    gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                    gridImageNode.data.project_id = task.aiToolsId;
                    gridImageNode.data.aiToolsId = task.aiToolsId;
                    gridImageNode.data.gridIndex = gridIndex;
                    gridImageNode.data.gridSize = gridSize;
                    gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                    gridImageNode.data.isSplit = true;
                    gridImageNode.data.status = 'pending';
                    gridImageNode.title = gridImageNode.data.name;
                    
                    const nodeEl = canvasEl.querySelector(`.node[data-node-id="${gridImageNodeId}"]`);
                    if(nodeEl) {
                      const titleEl = nodeEl.querySelector('.node-title');
                      if(titleEl) titleEl.textContent = gridImageNode.title;
                    }
                    
                    state.connections.push({
                      id: state.nextConnId++,
                      from: shotFrameNode.id,
                      to: gridImageNodeId
                    });
                  }
                });
              });


              renderAllConnections();
              renderMinimap();

              safeAutoSave()

              gridStatusEl.style.color = '#16a34a';
              gridStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，正在轮询状态...`;
              showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');

              const allAiToolsIds = completedTasks.map(t => t.aiToolsId);
              
              pollVideoStatus(
                allAiToolsIds,
                (progressText) => {
                  gridStatusEl.textContent = progressText;
                },
                async (statusResult) => {
                  if(statusResult.tasks) {
                    for(const taskInfo of statusResult.tasks) {
                      const aiToolsId = String(taskInfo.project_id);
                      const taskData = aiToolsMap[aiToolsId];
                      
                      if(!taskData) continue;
                      
                      if(taskInfo.status === 'SUCCESS') {
                        console.log(`[宫格生图] AI工具 ${aiToolsId} 生成成功，标记节点等待拆分`);
                        
                        for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                          const gridIndex = idx + 1;
                          const gridNode = state.nodes.find(n => 
                            n.type === 'image' && 
                            String(n.data.aiToolsId) === aiToolsId && 
                            n.data.gridIndex === gridIndex
                          );
                          if(gridNode) {
                            gridNode.data.status = 'splitting';
                          }
                        }
                      } else if(taskInfo.status === 'FAILED') {
                        console.warn(`[宫格生图] AI工具 ${aiToolsId} 生成失败: ${taskInfo.reason || '未知原因'}`);
                        
                        state.nodes.forEach(gridNode => {
                          if(gridNode.type === 'image' && String(gridNode.data.aiToolsId) === aiToolsId) {
                            gridNode.data.status = 'failed';
                          }
                        });
                      }
                    }
                  }
                  
                  safeAutoSave();
                  
                  gridStatusEl.style.color = '#16a34a';
                  gridStatusEl.textContent = '宫格图片生成完成，正在拆分...';
                  showToast('宫格图片生成完成，正在拆分', 'success');
                  
                  // 立即触发一次拆分（不等 60 秒轮询周期）
                  pollWorkflowNodeStatus();
                },
                (errorMsg) => {
                  gridStatusEl.style.color = '#dc2626';
                  gridStatusEl.textContent = errorMsg;
                  showToast(errorMsg, 'error');
                }
              );
              
            } catch(error) {
              console.error('[宫格生图] 失败:', error);
              gridStatusEl.style.color = '#dc2626';
              gridStatusEl.textContent = '失败: ' + (error.message || '未知错误');
              showToast('宫格生图失败: ' + (error.message || '未知错误'), 'error');
            } finally {
              splitGridBtn.disabled = false;
              splitBtn.disabled = false;
            }
            return;
          }
        }

        if(!state.defaultWorldId){
          const confirmed = await showConfirmModal('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？', { title: '提示' });
          if(!confirmed){
            splitGridBtn.disabled = false;
            splitBtn.disabled = false;
            return;
          }
        }

        gridStatusEl.style.display = 'block';
        gridStatusEl.style.color = '#666';
        gridStatusEl.textContent = '正在调用LLM解析剧本...';

        try {
          // 异步任务：提交拆分 → 轮询 → 完成后执行宫格流程。
          // 见 docs/script/script_parser_incremental_split_design.md §14。
          const submitData = await window.ScriptSplitTask.submitSplitTask(node.data, state.defaultWorldId);
          const taskId = submitData.task_id;
          node.data.splitTaskId = taskId;
          node.data.splitTaskMode = 'split_and_generate_grid';
          node.data.splitTaskResultApplied = false;
          node.data.splitTaskPostActionStarted = false;
          safeAutoSave();

          window.ScriptSplitTask.pollScriptSplitTask(taskId, {
            onUpdate: (status) => {
              gridStatusEl.style.color = '#666';
              gridStatusEl.textContent = status.message || '拆分中…';
            },
            onComplete: async (parsedData) => {
              if (node.data.splitTaskPostActionStarted) {
                // 刷新恢复时已启动过宫格流程，不重复
                return;
              }
              node.data.splitTaskPostActionStarted = true;
              try {
                await runGridFlow(parsedData);
                node.data.splitTaskResultApplied = true;
                safeAutoSave();
              } catch (e) {
                gridStatusEl.style.color = '#dc2626';
                gridStatusEl.textContent = '失败: ' + (e.message || '未知错误');
                showToast('宫格生图失败: ' + (e.message || '未知错误'), 'error');
              } finally {
                splitGridBtn.disabled = false;
                splitBtn.disabled = false;
              }
            },
            onPaused: (status) => {
              gridStatusEl.style.color = '#d97706';
              gridStatusEl.textContent = status.error_message || status.message || '任务暂停，等待处理';
              splitGridBtn.disabled = false;
              splitBtn.disabled = false;
            },
            onError: (error) => {
              gridStatusEl.style.color = '#dc2626';
              gridStatusEl.textContent = '失败: ' + (error.message || '未知错误');
              showToast('宫格生图失败: ' + (error.message || '未知错误'), 'error');
              splitGridBtn.disabled = false;
              splitBtn.disabled = false;
            },
          });

          // runGridFlow: 解析成功后的完整宫格流程（创建节点→生成分镜→收集参考图→宫格提交）。
          // 提取为局部 async 函数，供轮询 onComplete 和刷新恢复复用。
          async function runGridFlow(parsedData) {
            node.data.parsedData = parsedData;
            const groupCount = parsedData.shot_groups ? parsedData.shot_groups.length : 0;
            gridStatusEl.style.color = '#16a34a';
            gridStatusEl.textContent = `解析成功！共${groupCount}个幕`;

            if (!parsedData.shot_groups || parsedData.shot_groups.length === 0) {
              throw new Error('未生成幕');
            }

            // 幂等：已有分镜组节点则跳过创建
            const hasExistingShotGroup = state.nodes.some(
              n => n.type === 'shot_group' && n.data && n.data.scriptNodeId === id
            );
            const scriptId = id;
            const maxGroupDuration = parsedData.max_group_duration || 15;

            let createdShotGroupNodes = [];
            if (!hasExistingShotGroup) {
              parsedData.shot_groups.forEach((shotGroup) => {
                if (shotGroup.shots && Array.isArray(shotGroup.shots)) {
                  shotGroup.shots.forEach((shot) => {
                    if (shot.shot_number) {
                      createOrUpdatePillar(scriptId, shot.shot_number, shot.duration || maxGroupDuration);
                    }
                  });
                }
              });

              let cumulativeY = 0;
              parsedData.shot_groups.forEach((shotGroup) => {
                const offsetX = 800;
                const shotCount = (shotGroup.shots && shotGroup.shots.length) || 1;
                const shotGroupNodeId = createShotGroupNode({
                  x: node.x + offsetX,
                  y: node.y + cumulativeY,
                  shotGroupData: shotGroup,
                  scriptData: parsedData,
                  scriptNodeId: id,  // 关联的剧本节点 ID
                  scriptContent: node.data.scriptContent || ''  // 原始剧本内容
                });
                cumulativeY += shotCount * 700;
                if (shotGroupNodeId) {
                  state.connections.push({ id: state.nextConnId++, from: id, to: shotGroupNodeId });
                  createdShotGroupNodes.push(shotGroupNodeId);
                }
              });

              renderTimeline();
              if (!state.timeline.visible) flashExpandButton();
              renderAllConnections();
              renderMinimap();
            } else {
              // 恢复时复用已有节点
              createdShotGroupNodes = state.nodes
                .filter(n => n.type === 'shot_group' && n.data && n.data.scriptNodeId === id)
                .map(n => n.id);
            }

            // 第三步：生成分镜节点并收集提示词
            gridStatusEl.textContent = '正在生成分镜节点...';
            console.log(`[宫格生图] 开始生成分镜节点，分镜组数量: ${createdShotGroupNodes.length}`);
            const allShotFrameNodes = [];

            for (const shotGroupNodeId of createdShotGroupNodes) {
              const shotGroupNode = state.nodes.find(n => n.id === shotGroupNodeId);
              if (shotGroupNode) {
                console.log(`[宫格生图] 处理分镜组 ${shotGroupNodeId}`);
                const shotFrameNodeIds = await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
                console.log(`[宫格生图] 分镜组 ${shotGroupNodeId} 返回的节点ID: ${shotFrameNodeIds}`);
                if (shotFrameNodeIds && shotFrameNodeIds.length > 0) {
                  const shotNodes = shotFrameNodeIds.map(nid => state.nodes.find(n => n.id === nid)).filter(Boolean);
                  console.log(`[宫格生图] 找到 ${shotNodes.length} 个有效的分镜节点`);
                  allShotFrameNodes.push(...shotNodes);
                } else {
                  console.warn(`[宫格生图] 分镜组 ${shotGroupNodeId} 没有返回任何节点ID`);
                }
              }
            }

            console.log(`[宫格生图] 总共收集到 ${allShotFrameNodes.length} 个分镜节点`);
            if (allShotFrameNodes.length === 0) {
              throw new Error('未生成分镜节点');
            }

            // 收集参考图片URL（角色、场景、道具）
            gridStatusEl.textContent = '正在收集参考图片...';
            const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
            console.log(`[宫格生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);

            // 第四步：根据分镜数量决定宫格大小
            const shotCount = allShotFrameNodes.length;
            if (shotCount === 1) {
            gridStatusEl.style.color = '#f59e0b';
            gridStatusEl.textContent = '只有1个分镜，无需宫格生图';
            showToast('只有1个分镜，无需宫格生图', 'warning');
            return;
          }

          const gridModel = normalizeGridImageModelValue(node.data.gridModel);
          const gridLayoutPref = node.data.gridLayout || 'auto';

          // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
          const forceEnhancedModel = referenceImageUrls.length > 5;
          if(forceEnhancedModel) {
            console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
          }

          const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

          // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
          const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
          if(referenceImageUrls.length > maxRefImages) {
            console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
            referenceImageUrls.splice(maxRefImages);
            promptSuffix.splice(maxRefImages);
          }
          
          node.data.gridModel = finalModel;
          const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
          const imageCount = Math.ceil(shotCount / gridSize);
          const totalPower = imageCount * imagePower;

          // 获取模型显示名称
          const taskInfo = TaskConfig.getTaskByKey(finalModel);
          const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

          // 确认生成
          const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
          const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
            `分镜数量：${shotCount}个\n` +
            `模型：${modelDisplayName}${refImageInfo}\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认生成吗？`;
          
          if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
            gridStatusEl.style.color = '#666';
            gridStatusEl.textContent = '已取消';
            return;
          }

          // 第五步：拼接提示词并调用API
          gridStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
          
          const gridTasks = [];
          for(let i = 0; i < imageCount; i++) {
            const startIdx = i * gridSize;
            const endIdx = Math.min(startIdx + gridSize, shotCount);
            const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
            
            const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
            
            gridTasks.push({
              batchNodes,
              gridPrompt,
              startIdx
            });
          }

          // 构建参考图片说明后缀
          const refSuffixText = promptSuffix.length > 0 ? `\n\n${promptSuffix.join('，')}。` : '';
          
          // 并行调用图片编辑API
          const apiPromises = gridTasks.map(async (task) => {
            const form = new FormData();
            
            // 添加参考图片说明到提示词
            let finalGridPrompt = task.gridPrompt;
            if(refSuffixText) {
              try {
                const promptObj = JSON.parse(task.gridPrompt);
                promptObj.reference_images_description = promptSuffix.join('，') + '。';
                finalGridPrompt = JSON.stringify(promptObj);
              } catch(e) {
                finalGridPrompt = task.gridPrompt + refSuffixText;
              }
            }
            
            form.append('prompt', finalGridPrompt);
            form.append('count', '1');
            appendAuthToForm(form);
            
            // 加强版模型需要传入4K图片大小
            if(finalModel === 'gemini-3-pro-image-preview') {
              form.append('image_size', '4K');
            }
            
            let apiUrl, res;
            if(referenceImageUrls.length > 0) {
              // 有参考图片URL，使用图片编辑API，直接传URL
              const taskId3 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
              if(!taskId3) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId3);
              form.append('ref_image_urls', referenceImageUrls.join(','));
              form.append('ratio', state.ratio || '16:9');
              apiUrl = '/api/image-edit';
            } else {
              // 无参考图片，使用文生图API
              const taskId4 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
              if(!taskId4) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId4);
              form.append('aspect_ratio', state.ratio || '16:9');
              apiUrl = '/api/text-to-image';
            }
            
            res = await fetch(apiUrl, {
              method: 'POST',
              body: form
            });
            
            const resText2 = await res.text();
            let data;
            try { data = JSON.parse(resText2); } catch(e) {
              throw new Error(`API返回异常 (HTTP ${res.status}): ${resText2.slice(0, 200) || '空响应'}`);
            }
            
            if(!res.ok) {
              const errorMsg = typeof data.detail === 'string' ? data.detail : 
                               typeof data.message === 'string' ? data.message :
                               JSON.stringify(data.detail || data.message || '提交任务失败');
              throw new Error(errorMsg);
            }
            
            if(!data.project_ids || data.project_ids.length === 0) {
              throw new Error('提交任务失败：未返回项目ID');
            }
            
            return {
              ...task,
              aiToolsId: data.project_ids[0]
            };
          });

          const completedTasks = await Promise.all(apiPromises);
          
          // 第六步：为每个分镜节点创建分镜图子节点
          gridStatusEl.textContent = '正在创建分镜图节点...';
          
          // 创建节点映射：aiToolsId -> {batchNodes, gridSize}
          const aiToolsMap = {};
          completedTasks.forEach((task) => {
            // 确保key是字符串类型
            aiToolsMap[String(task.aiToolsId)] = {
              batchNodes: task.batchNodes,
              gridSize: gridSize
            };
            
            task.batchNodes.forEach((shotFrameNode, idx) => {
              const gridIndex = idx + 1;
              const gridImageNodeId = createImageNode({
                x: shotFrameNode.x + 380,
                y: shotFrameNode.y,
                checkCollision: true
              });
              
              const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
              if(gridImageNode) {
                gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                gridImageNode.data.project_id = task.aiToolsId;
                gridImageNode.data.aiToolsId = task.aiToolsId;
                gridImageNode.data.gridIndex = gridIndex;
                gridImageNode.data.gridSize = gridSize;
                gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                gridImageNode.data.isSplit = true;
                gridImageNode.data.status = 'pending';
                gridImageNode.title = gridImageNode.data.name;
                
                const nodeEl = canvasEl.querySelector(`.node[data-node-id="${gridImageNodeId}"]`);
                if(nodeEl) {
                  const titleEl = nodeEl.querySelector('.node-title');
                  if(titleEl) titleEl.textContent = gridImageNode.title;
                }
                
                state.connections.push({
                  id: state.nextConnId++,
                  from: shotFrameNode.id,
                  to: gridImageNodeId
                });
              }
            });
          });

          renderAllConnections();
          renderMinimap();
          safeAutoSave()

          gridStatusEl.style.color = '#16a34a';
          gridStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，正在轮询状态...`;
          showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');

          // 收集所有 aiToolsId 用于轮询
          const allAiToolsIds = completedTasks.map(t => t.aiToolsId);
          
          // 复用 pollVideoStatus 进行轮询
          pollVideoStatus(
            allAiToolsIds,
            (progressText) => {
              gridStatusEl.textContent = progressText;
            },
            async (statusResult) => {
              // 所有任务完成，处理每个任务
              if(statusResult.tasks) {
                for(const taskInfo of statusResult.tasks) {
                  // 确保类型一致（字符串）
                  const aiToolsId = String(taskInfo.project_id);
                  const taskData = aiToolsMap[aiToolsId];
                  
                  if(!taskData) continue;
                  
                  if(taskInfo.status === 'SUCCESS') {
                    console.log(`[宫格生图] AI工具 ${aiToolsId} 生成成功，标记节点等待拆分`);
                    
                    for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                      const gridIndex = idx + 1;
                      const gridNode = state.nodes.find(n => 
                        n.type === 'image' && 
                        String(n.data.aiToolsId) === aiToolsId && 
                        n.data.gridIndex === gridIndex
                      );
                      if(gridNode) {
                        gridNode.data.status = 'splitting';
                      }
                    }
                  } else if(taskInfo.status === 'FAILED') {
                    console.warn(`[宫格生图] AI工具 ${aiToolsId} 生成失败: ${taskInfo.reason || '未知原因'}`);
                    
                    state.nodes.forEach(gridNode => {
                      if(gridNode.type === 'image' && String(gridNode.data.aiToolsId) === aiToolsId) {
                        gridNode.data.status = 'failed';
                      }
                    });
                  }
                }
              }
              
              // 保存工作流
              safeAutoSave();
              
              gridStatusEl.style.color = '#16a34a';
              gridStatusEl.textContent = '宫格图片生成完成，正在拆分...';
              showToast('宫格图片生成完成，正在拆分', 'success');
              
              // 立即触发一次拆分（不等 60 秒轮询周期）
              pollWorkflowNodeStatus();
            },
            (errorMsg) => {
              gridStatusEl.style.color = '#dc2626';
              gridStatusEl.textContent = errorMsg;
              showToast(errorMsg, 'error');
            }
          );
          } // end of runGridFlow

        } catch(error) {
          // 仅处理提交/启动轮询阶段的错误；轮询中和宫格流程的错误由各自回调处理
          console.error('提交宫格拆分任务失败:', error);
          gridStatusEl.style.color = '#dc2626';
          gridStatusEl.textContent = '失败: ' + (error.message || '未知错误');
          showToast('宫格生图失败: ' + (error.message || '未知错误'), 'error');
          splitGridBtn.disabled = false;
          splitBtn.disabled = false;
        }
      });

      // 批量生成视频按钮监听
      batchGenerateBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(typeof setParamGroupOpen === 'function') setParamGroupOpen('gridVideo', true);
        
        batchStatusEl.style.display = 'block';
        batchStatusEl.style.color = '#666';
        batchStatusEl.textContent = '正在检查分镜节点...';
        
        try {
          // 查找连接到此剧本节点的分镜组
          const shotGroupConnections = state.connections.filter(c => c.from === id);
          const shotGroupNodes = shotGroupConnections
            .map(conn => state.nodes.find(n => n.id === conn.to))
            .filter(n => n && n.type === 'shot_group');
          
          if(shotGroupNodes.length === 0) {
            batchStatusEl.style.color = '#dc2626';
            batchStatusEl.textContent = '未找到幕节点，请先拆分幕';
            showToast('未找到幕节点，请先拆分幕', 'error');
            return;
          }
          
          // 收集所有分镜节点并计算算力消耗
          let totalShotFrames = 0;
          let totalPower = 0;
          const shotGroupsWithFrames = [];
          
          for(const sgNode of shotGroupNodes) {
            const sfConnections = state.connections.filter(c => c.from === sgNode.id);
            const sfNodes = sfConnections
              .map(conn => state.nodes.find(n => n.id === conn.to))
              .filter(n => n && n.type === 'shot_frame');
            
            if(sfNodes.length > 0) {
              // 检查就绪的分镜（有预览图或启用参考图模式）
              const readyNodes = sfNodes.filter(n => {
                const nodeMode = n.data.videoMode || 'first_last_frame';
                return nodeMode === 'multi_reference' || n.data.previewImageUrl || n.data.imageUrl;
              });

              if(readyNodes.length > 0) {
                shotGroupsWithFrames.push({
                  shotGroupNode: sgNode,
                  shotFrameNodes: readyNodes
                });

                // 计算每个分镜的算力消耗
                // 模型优先级：分镜节点 > 分镜组 > 剧本节点 > 默认wan22
                readyNodes.forEach(sfNode => {
                  const videoModel = sfNode.data.videoModel || sgNode.data.videoModel || node.data.videoModel || 'wan22';
                  const duration = sfNode.data.videoDuration || sfNode.data.duration || 5;
                  const drawCount = sfNode.data.videoDrawCount || 1;
                  
                  const singlePower = calculateVideoGenerationPower(videoModel, duration);
                  totalPower += singlePower * drawCount;
                  totalShotFrames++;
                });
              }
            }
          }
          
          if(shotGroupsWithFrames.length === 0) {
            batchStatusEl.style.color = '#dc2626';
            batchStatusEl.textContent = '幕下未找到有预览图的分镜节点';
            showToast('幕下未找到有预览图的分镜节点，请先生成分镜图', 'error');
            return;
          }
          
          // 显示确认弹窗
          const confirmMsg = `即将为整个剧本的所有分镜生成视频\n` +
            `幕数量：${shotGroupsWithFrames.length}个\n` +
            `分镜数量：${totalShotFrames}个\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认开始生成吗？`;
          
          if(!await showConfirmModal(confirmMsg, { title: '批量生成视频确认', confirmText: '开始生成' })) {
            batchStatusEl.style.color = '#666';
            batchStatusEl.textContent = '已取消';
            return;
          }
          
          // 首次使用提示
          const batchTipKey = 'script_batch_tip_shown';
          if(!localStorage.getItem(batchTipKey)) {
            showToast('逐个生成：为整个剧本的所有分镜生成视频，支持所有模型但可能浪费时长', 'info', 5000);
            localStorage.setItem(batchTipKey, 'true');
          }
          
          setBtnLoading(batchGenerateBtn, '批量生成中...');
          
          let successCount = 0;
          let failCount = 0;
          
          for(let i = 0; i < shotGroupsWithFrames.length; i++) {
            const { shotGroupNode, shotFrameNodes } = shotGroupsWithFrames[i];
            
            batchStatusEl.textContent = `正在生成 ${i + 1}/${shotGroupsWithFrames.length} 个幕的视频...`;
            showToast(`正在生成 ${i + 1}/${shotGroupsWithFrames.length} 个幕的视频...`, 'info');
            
            try {
              // 将剧本节点的视频模型同步到分镜组节点（修复剧本节点视频模型选择不生效的bug）
              if(node.data.videoModel) {
                shotGroupNode.data.videoModel = node.data.videoModel;
              }
              // 为每个分镜组调用批量生成函数
              await generateAllShotFrameVideos(shotGroupNode.id, shotGroupNode);
              successCount++;
            } catch(error) {
              console.error(`生成幕视频失败:`, error);
              failCount++;
            }
          }
          
          setBtnReady(batchGenerateBtn, '逐个生成视频');
          
          const resultMsg = `批量生成完成！成功 ${successCount} 个幕，失败 ${failCount} 个`;
          batchStatusEl.style.color = successCount > 0 ? '#22c55e' : '#dc2626';
          batchStatusEl.textContent = resultMsg;
          showToast(resultMsg, successCount > 0 ? 'success' : 'warning');
          
          safeAutoSave()
        } catch(error) {
          console.error('Generate script videos error:', error);
          showToast(`批量生成失败: ${error.message}`, 'error');
          
          setBtnReady(batchGenerateBtn, '逐个生成视频');
          batchStatusEl.style.color = '#dc2626';
          batchStatusEl.textContent = `失败: ${error.message}`;
        }
      });

      // 宫格生图（仅生图，不拆分）按钮监听
      gridOnlyBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(typeof setParamGroupOpen === 'function') setParamGroupOpen('gridVideo', true);
        
        gridOnlyStatusEl.style.display = 'block';
        gridOnlyStatusEl.style.color = '#666';
        gridOnlyStatusEl.textContent = '正在检查分镜节点...';
        
        try {
          // 查找连接到此剧本节点的分镜组
          const shotGroupConnections = state.connections.filter(c => c.from === id);
          const shotGroupNodes = shotGroupConnections
            .map(conn => state.nodes.find(n => n.id === conn.to))
            .filter(n => n && n.type === 'shot_group');
          
          if(shotGroupNodes.length === 0) {
            gridOnlyStatusEl.style.color = '#dc2626';
            gridOnlyStatusEl.textContent = '未找到幕节点，请先拆分幕';
            showToast('未找到幕节点，请先拆分幕', 'error');
            return;
          }
          
          // 收集所有分镜节点
          const allShotFrameNodes = [];
          for(const sgNode of shotGroupNodes) {
            const sfConnections = state.connections.filter(c => c.from === sgNode.id);
            const sfNodes = sfConnections
              .map(conn => state.nodes.find(n => n.id === conn.to))
              .filter(n => n && n.type === 'shot_frame');
            allShotFrameNodes.push(...sfNodes);
          }
          
          if(allShotFrameNodes.length === 0) {
            gridOnlyStatusEl.style.color = '#dc2626';
            gridOnlyStatusEl.textContent = '幕下未找到分镜节点，请先拆分幕';
            showToast('幕下未找到分镜节点', 'error');
            return;
          }
          
          const shotCount = allShotFrameNodes.length;
          if(shotCount === 1) {
            gridOnlyStatusEl.style.color = '#f59e0b';
            gridOnlyStatusEl.textContent = '只有1个分镜，无需宫格生图';
            showToast('只有1个分镜，无需宫格生图', 'warning');
            return;
          }
          
          gridOnlyStatusEl.textContent = '正在收集参考图片...';
          
          // 收集参考图片
          const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
          console.log(`[宫格生图-仅生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);
          
          // 决定宫格大小和模型
          const gridModel = normalizeGridImageModelValue(node.data.gridModel);
          const gridLayoutPref = node.data.gridLayout || 'auto';
          const forceEnhancedModel = referenceImageUrls.length > 5;

          const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

          // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
          const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
          if(referenceImageUrls.length > maxRefImages) {
            referenceImageUrls.splice(maxRefImages);
            promptSuffix.splice(maxRefImages);
          }
          
          node.data.gridModel = finalModel;

          const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
          const imageCount = Math.ceil(shotCount / gridSize);
          const totalPower = imageCount * imagePower;

          // 获取模型显示名称
          const taskInfo = TaskConfig.getTaskByKey(finalModel);
          const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

          const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
          const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
            `分镜数量：${shotCount}个\n` +
            `模型：${modelDisplayName}${refImageInfo}\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认生成吗？`;
          
          if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
            gridOnlyStatusEl.style.color = '#666';
            gridOnlyStatusEl.textContent = '已取消';
            return;
          }
          
          // 拼接提示词并调用API
          gridOnlyStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
          
          const gridTasks = [];
          for(let i = 0; i < imageCount; i++) {
            const startIdx = i * gridSize;
            const endIdx = Math.min(startIdx + gridSize, shotCount);
            const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
            
            const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
            
            gridTasks.push({
              batchNodes,
              gridPrompt,
              startIdx
            });
          }
          
          // 构建参考图片说明后缀
          const refSuffixText = promptSuffix.length > 0 ? `\n\n${promptSuffix.join('，')}。` : '';
          
          const apiPromises = gridTasks.map(async (task) => {
            const form = new FormData();
            
            let finalGridPrompt = task.gridPrompt;
            if(refSuffixText) {
              try {
                const promptObj = JSON.parse(task.gridPrompt);
                promptObj.reference_images_description = promptSuffix.join('，') + '。';
                finalGridPrompt = JSON.stringify(promptObj);
              } catch(e) {
                finalGridPrompt = task.gridPrompt + refSuffixText;
              }
            }
            
            form.append('prompt', finalGridPrompt);
            form.append('count', '1');
            appendAuthToForm(form);
            
            if(finalModel === 'gemini-3-pro-image-preview') {
              form.append('image_size', '4K');
            }
            
            let apiUrl, res;
            if(referenceImageUrls.length > 0) {
              const taskId5 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
              if(!taskId5) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId5);
              form.append('ref_image_urls', referenceImageUrls.join(','));
              form.append('ratio', state.ratio || '16:9');
              apiUrl = '/api/image-edit';
            } else {
              const taskId6 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
              if(!taskId6) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId6);
              form.append('aspect_ratio', state.ratio || '16:9');
              apiUrl = '/api/text-to-image';
            }
            
            res = await fetch(apiUrl, {
              method: 'POST',
              body: form
            });
            
            const resText3 = await res.text();
            let data;
            try { data = JSON.parse(resText3); } catch(e) {
              throw new Error(`API返回异常 (HTTP ${res.status}): ${resText3.slice(0, 200) || '空响应'}`);
            }
            
            if(!res.ok) {
              const errorMsg = typeof data.detail === 'string' ? data.detail : 
                               typeof data.message === 'string' ? data.message :
                               JSON.stringify(data.detail || data.message || '提交任务失败');
              throw new Error(errorMsg);
            }
            
            if(!data.project_ids || data.project_ids.length === 0) {
              throw new Error('提交任务失败：未返回项目ID');
            }
            
            return {
              ...task,
              aiToolsId: data.project_ids[0]
            };
          });
          
          const completedTasks = await Promise.all(apiPromises);
          
          gridOnlyStatusEl.textContent = '正在创建分镜图节点...';
          
          const aiToolsMap = {};
          completedTasks.forEach((task) => {
            aiToolsMap[String(task.aiToolsId)] = {
              batchNodes: task.batchNodes,
              gridSize: gridSize
            };
            
            task.batchNodes.forEach((shotFrameNode, idx) => {
              const gridIndex = idx + 1;
              const gridImageNodeId = createImageNode({
                x: shotFrameNode.x + 380,
                y: shotFrameNode.y,
                checkCollision: true
              });
              
              const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
              if(gridImageNode) {
                gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                gridImageNode.data.project_id = task.aiToolsId;
                gridImageNode.data.aiToolsId = task.aiToolsId;
                gridImageNode.data.gridIndex = gridIndex;
                gridImageNode.data.gridSize = gridSize;
                gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                gridImageNode.data.isSplit = true;
                gridImageNode.data.status = 'pending';
                gridImageNode.title = gridImageNode.data.name;
                
                const nodeEl = canvasEl.querySelector(`.node[data-node-id="${gridImageNodeId}"]`);
                if(nodeEl) {
                  const titleEl = nodeEl.querySelector('.node-title');
                  if(titleEl) titleEl.textContent = gridImageNode.title;
                }
                
                state.connections.push({
                  id: state.nextConnId++,
                  from: shotFrameNode.id,
                  to: gridImageNodeId
                });
              }
            });
          });
          
          renderAllConnections();
          renderMinimap();
          safeAutoSave()

          gridOnlyStatusEl.style.color = '#16a34a';
          gridOnlyStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，正在轮询状态...`;
          showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');

          const allAiToolsIds = completedTasks.map(t => t.aiToolsId);

          pollVideoStatus(
            allAiToolsIds,
            (progressText) => {
              gridOnlyStatusEl.textContent = progressText;
            },
            async (statusResult) => {
              if(statusResult.tasks) {
                for(const taskInfo of statusResult.tasks) {
                  const aiToolsId = String(taskInfo.project_id);
                  const taskData = aiToolsMap[aiToolsId];
                  
                  if(!taskData) continue;
                  
                  if(taskInfo.status === 'SUCCESS') {
                    for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                      const gridIndex = idx + 1;
                      const gridNode = state.nodes.find(n => 
                        n.type === 'image' && 
                        String(n.data.aiToolsId) === aiToolsId && 
                        n.data.gridIndex === gridIndex
                      );
                      if(gridNode) {
                        gridNode.data.status = 'splitting';
                      }
                    }
                  } else if(taskInfo.status === 'FAILED') {
                    state.nodes.forEach(gridNode => {
                      if(gridNode.type === 'image' && String(gridNode.data.aiToolsId) === aiToolsId) {
                        gridNode.data.status = 'failed';
                      }
                    });
                  }
                }
              }
              
              safeAutoSave();

              gridOnlyStatusEl.style.color = '#16a34a';
              gridOnlyStatusEl.textContent = '宫格图片生成完成，正在拆分...';
              showToast('宫格图片生成完成，正在拆分', 'success');
              
              pollWorkflowNodeStatus();
            },
            (errorMsg) => {
              gridOnlyStatusEl.style.color = '#dc2626';
              gridOnlyStatusEl.textContent = errorMsg;
              showToast(errorMsg, 'error');
            }
          );
          
        } catch(error) {
          console.error('[宫格生图-仅生图] 失败:', error);
          gridOnlyStatusEl.style.color = '#dc2626';
          gridOnlyStatusEl.textContent = '失败: ' + (error.message || '未知错误');
          showToast('宫格生图失败: ' + (error.message || '未知错误'), 'error');
        }
      });

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }
