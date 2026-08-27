/**
 * 管理后台“接口模块”页面。
 *
 * 大模型只能生成/修改 staging 并执行静态校验；批准、启用、禁用和回滚始终由
 * 当前管理员显式操作。所有请求均复用 admin 根应用中的 Bearer 凭据。
 */
(function () {
    'use strict';

    const API_ROOT = '/api/admin/user-modules';
    const POLL_INTERVAL_MS = 1500;
    const DEFAULT_COMFYUI_BASE_URL = 'http://localhost:8188/';
    const TERMINAL_AGENT_STATES = new Set(['completed', 'failed', 'cancelled', 'done', 'succeeded']);
    const WRITABLE_GENERATION_STATES = new Set(['draft', 'validation_failed', 'validated', 'runtime_validation_failed']);

    function unwrap(response) {
        const body = response && response.data;
        if (body && Object.prototype.hasOwnProperty.call(body, 'success') && body.success === false) {
            throw new Error(body.error || body.detail || 'Operation failed');
        }
        return body && Object.prototype.hasOwnProperty.call(body, 'data') ? body.data : body;
    }

    function arrayFrom(payload, keys) {
        if (Array.isArray(payload)) return payload;
        for (const key of keys) {
            if (Array.isArray(payload && payload[key])) return payload[key];
        }
        return [];
    }

    function apiError(error) {
        return error?.response?.data?.error
            || error?.response?.data?.detail
            || error?.message
            || String(error);
    }

    window.UserModulesAdminMixin = {
        data() {
            return {
                userModules: {
                    modules: [],
                    generations: [],
                    runtime: {},
                    keyword: '',
                    loading: false,
                    loaded: false,
                    busy: false,
                    error: '',
                },
                userModuleCreateModal: {
                    show: false,
                    moduleId: '',
                    requirement: '',
                    modelId: '',
                    models: [],
                    modelsLoading: false,
                    confirmed: false,
                    loading: false,
                    connector: 'http',
                    comfyuiBaseUrl: DEFAULT_COMFYUI_BASE_URL,
                    workflowJson: '',
                    workflowFileName: '',
                },
                userModuleAgentModal: {
                    show: false,
                    taskId: '',
                    generationId: '',
                    status: 'pending',
                    messages: [],
                    lastMessageId: 0,
                    pollTimer: null,
                    polling: false,
                    error: '',
                    drafts: {},
                    pendingQuestionNotified: false,
                },
                userModuleGenerationModal: {
                    show: false,
                    loading: false,
                    actionLoading: false,
                    generation: null,
                    files: [],
                    selectedPath: '',
                    content: '',
                    fileSize: 0,
                    fileLoading: false,
                    validation: null,
                    review: null,
                    secretNames: [],
                    error: '',
                },
                userModuleSecretCatalog: [],
                userModuleDetailModal: {
                    show: false,
                    loading: false,
                    actionLoading: false,
                    module: null,
                    releases: [],
                    error: '',
                },
                userModuleBindings: {
                    bindings: [],
                    targets: null,
                    inactiveHint: false,
                    form: { taskByOperation: {} },
                    loading: false,
                    actionLoading: false,
                    error: '',
                },
                userModuleAgentTasks: [],
                userModuleCodeModal: {
                    show: false,
                    loading: false,
                    moduleId: '',
                    releaseId: 0,
                    version: '',
                    files: [],
                    selectedPath: '',
                    content: '',
                    fileSize: 0,
                    fileLoading: false,
                    error: '',
                },
            };
        },

        computed: {
            filteredUserModules() {
                const keyword = (this.userModules.keyword || '').toLowerCase();
                if (!keyword) return this.userModules.modules;
                return this.userModules.modules.filter((item) => [
                    item.module_id,
                    item.name,
                    item.status,
                    item.active_version,
                    item.version,
                ].some((value) => String(value || '').toLowerCase().includes(keyword)));
            },
            userModuleActiveCount() {
                return this.userModules.modules.filter((item) => item.enabled || item.status === 'active').length;
            },
            userModuleRuntimeCount() {
                const runtime = this.userModules.runtime || {};
                if (runtime.supervisor) return Number(runtime.supervisor.runner_count || 0);
                if (typeof runtime.runner_count === 'number') return runtime.runner_count;
                if (runtime.abi && runtime.core_version) return 0;
                if (Array.isArray(runtime)) {
                    return runtime.filter((item) => item.online !== false && item.status !== 'offline').length;
                }
                const runners = runtime.runners || runtime.modules || runtime;
                return Object.values(runners || {}).filter((item) => {
                    if (typeof item === 'boolean') return item;
                    return item && item.online !== false && item.status !== 'offline';
                }).length;
            },
            canStartUserModuleAgent() {
                const form = this.userModuleCreateModal;
                const idOk = /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$/.test(form.moduleId);
                const modelOk = Boolean(form.modelId);
                const confirmed = Boolean(form.confirmed);
                if (!idOk || !modelOk || !confirmed) return false;
                if (form.connector === 'local_comfyui') {
                    return Boolean(form.comfyuiBaseUrl.trim())
                        && Boolean(form.workflowJson)
                        && form.requirement.length <= 20000;
                }
                return form.requirement.trim().length >= 10 && form.requirement.length <= 20000;
            },
            userModuleAgentTerminal() {
                return TERMINAL_AGENT_STATES.has(String(this.userModuleAgentModal.status || '').toLowerCase());
            },
            hasPendingUserModuleQuestion() {
                return this.userModuleAgentModal.messages.some((message) => this.isPendingUserModuleQuestion(message));
            },
            userModuleAgentDisplayStatus() {
                return this.hasPendingUserModuleQuestion ? 'waiting_admin' : this.userModuleAgentModal.status;
            },
            canApproveUserModuleGeneration() {
                const state = this.userModuleGenerationModal.generation || {};
                const validation = this.userModuleGenerationModal.validation || state.validation;
                const review = this.userModuleGenerationModal.review || state.review;
                const gate = state.review_gate || validation?.review_gate;
                const policy = this.userModules.runtime?.review || {};
                const required = policy.required ?? gate?.required ?? review?.required ?? state.review_required ?? false;
                const rejected = review?.status === 'completed'
                    && (review?.verdict === 'reject' || review?.risk_level === 'high');
                const completedAndSafe = review?.status === 'completed'
                    && review?.verdict === 'approve'
                    && ['low', 'medium'].includes(review?.risk_level);
                const reviewPublishable = !rejected && (
                    required ? (completedAndSafe && (gate?.publishable ?? true)) : true
                );
                return state.status === 'validated'
                    && Boolean(validation && validation.ok)
                    && reviewPublishable;
            },
        },

        unmounted() {
            this.stopUserModuleAgentPolling();
        },

        methods: {
            userModuleReviewRiskClass(review) {
                if (!review) return '';
                if (review.status !== 'completed') return 'warning';
                if (review.verdict === 'reject' || review.risk_level === 'high') return 'failed';
                if (review.risk_level === 'medium') return 'warning';
                return 'passed';
            },
            userModuleReviewVerdict(review) {
                if (!review) return '';
                if (review.status === 'running') return this.t('um_review_running');
                if (review.status === 'skipped') return this.t('um_review_skipped');
                if (review.status === 'error') return this.t('um_review_error');
                if (review.verdict === 'reject' || review.risk_level === 'high') return this.t('um_review_rejected');
                if (review.risk_level === 'medium') return this.t('um_review_medium');
                return this.t('um_review_passed');
            },
            userModuleReviewModelText(review) {
                if (!review?.model) return '';
                const sourceKey = review.model_source === 'dedicated_review_model'
                    ? 'um_review_model_dedicated'
                    : 'um_review_model_generation';
                return `${this.t('um_review_model')}: ${review.model} · ${this.t(sourceKey)}`;
            },
            userModuleHeaders() {
                return { Authorization: `Bearer ${this.authToken}` };
            },
            handleUserModuleError(error, fallbackKey = 'um_operation_failed') {
                const status = error?.response?.status;
                if (status === 401 || status === 403) this.handleAuthError(status);
                return `${this.t(fallbackKey)}: ${apiError(error)}`;
            },
            async loadUserModules() {
                if (!this.authToken || this.userModules.loading) return;
                this.userModules.loading = true;
                this.userModules.error = '';
                try {
                    const [overviewResult, generationResult, runtimeResult, secretCatalogResult, agentTasksResult] = await Promise.allSettled([
                        axios.get(API_ROOT, { headers: this.userModuleHeaders() }),
                        axios.get(`${API_ROOT}/generations`, { headers: this.userModuleHeaders() }),
                        axios.get(`${API_ROOT}/runtime`, { headers: this.userModuleHeaders() }),
                        axios.get(`${API_ROOT}/secret-catalog`, { headers: this.userModuleHeaders() }),
                        axios.get(`${API_ROOT}/agent/tasks`, { params: { limit: 10 }, headers: this.userModuleHeaders() }),
                    ]);
                    if (overviewResult.status === 'fulfilled') {
                        const overview = unwrap(overviewResult.value) || {};
                        this.userModules.modules = arrayFrom(overview, ['modules', 'items', 'list']);
                        if (Array.isArray(overview.generations)) this.userModules.generations = overview.generations;
                        if (overview.runtime) this.userModules.runtime = overview.runtime;
                    } else {
                        throw overviewResult.reason;
                    }
                    if (generationResult.status === 'fulfilled') {
                        this.userModules.generations = arrayFrom(unwrap(generationResult.value), ['generations', 'items', 'list']);
                    } else if (generationResult.reason?.response?.status !== 404) {
                        console.warn('Failed to load user module generations:', generationResult.reason);
                    }
                    if (runtimeResult.status === 'fulfilled') {
                        this.userModules.runtime = unwrap(runtimeResult.value) || {};
                    } else if (runtimeResult.reason?.response?.status !== 404) {
                        console.warn('Failed to load user module runtime:', runtimeResult.reason);
                    }
                    if (secretCatalogResult.status === 'fulfilled') {
                        const payload = unwrap(secretCatalogResult.value) || {};
                        this.userModuleSecretCatalog = payload.catalog || [];
                    } else if (secretCatalogResult.reason?.response?.status !== 404) {
                        console.warn('Failed to load user module secret catalog:', secretCatalogResult.reason);
                    }
                    if (agentTasksResult.status === 'fulfilled') {
                        const payload = unwrap(agentTasksResult.value) || {};
                        this.userModuleAgentTasks = payload.tasks || [];
                    } else if (agentTasksResult.reason?.response?.status !== 404) {
                        console.warn('Failed to load user module agent tasks:', agentTasksResult.reason);
                    }
                    this.userModules.loaded = true;
                } catch (error) {
                    this.userModules.error = this.handleUserModuleError(error, 'um_load_failed');
                } finally {
                    this.userModules.loading = false;
                }
            },
            moduleCapabilities(module) {
                const manifest = module.active_manifest || module.manifest || {};
                return module.capabilities || manifest.capabilities || [];
            },
            moduleRuntimeOnline(moduleId) {
                const runtime = this.userModules.runtime || {};
                if (runtime.supervisor) {
                    if (!runtime.supervisor.healthy) return false;
                    const loadedModules = runtime.supervisor.modules;
                    return Array.isArray(loadedModules) && loadedModules.includes(moduleId);
                }
                if (runtime.abi) return false;
                if (Array.isArray(runtime)) {
                    const item = runtime.find((candidate) => candidate.module_id === moduleId);
                    return Boolean(item && item.online !== false && item.status !== 'offline');
                }
                const runners = runtime.runners || runtime.modules || runtime;
                const item = runners && runners[moduleId];
                if (typeof item === 'boolean') return item;
                return Boolean(item && item.online !== false && item.status !== 'offline');
            },
            userModuleStatusClass(status) {
                const value = String(status || 'unknown').toLowerCase();
                if (['active', 'ready', 'validated', 'completed', 'succeeded', 'compatible'].includes(value)) return 'success';
                if (['failed', 'validation_failed', 'runtime_validation_failed', 'incompatible', 'quarantined'].includes(value)) return 'danger';
                if (['pending', 'draft', 'running', 'runtime_validation', 'staged', 'waiting_admin'].includes(value)) return 'warning';
                return 'neutral';
            },
            userModuleStatusText(status) {
                const value = String(status || 'unknown').toLowerCase();
                const key = `um_status_${value}`;
                const translated = this.t(key);
                return translated === key ? value : translated;
            },
            formatUserModuleDate(value) {
                if (!value) return '-';
                const date = new Date(value);
                return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(this.locale === 'en' ? 'en-US' : 'zh-CN');
            },
            // 草稿卡片只展示需求首句（能力概述），完整需求在审阅弹窗中查看
            userModuleGenerationSummary(requirement) {
                const text = String(requirement || '').trim();
                if (!text) return '';
                let head = text.split('\n')[0].trim();
                const dotIndex = head.indexOf('。');
                if (dotIndex >= 0 && dotIndex <= 80) head = head.slice(0, dotIndex + 1);
                if (head.length > 80) head = `${head.slice(0, 80).trimEnd()}…`;
                return head;
            },
            formatUserModuleBytes(value) {
                const bytes = Number(value || 0);
                if (!bytes) return '0 B';
                if (bytes < 1024) return `${bytes} B`;
                if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
                return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
            },

            async openUserModuleCreateModal() {
                this.userModuleCreateModal.show = true;
                if (!this.userModuleCreateModal.comfyuiBaseUrl
                    || this.userModuleCreateModal.comfyuiBaseUrl === DEFAULT_COMFYUI_BASE_URL) {
                    try {
                        this.userModuleCreateModal.comfyuiBaseUrl =
                            window.localStorage.getItem('zjt_um_comfyui_base_url') || DEFAULT_COMFYUI_BASE_URL;
                    } catch (_err) {
                        this.userModuleCreateModal.comfyuiBaseUrl = DEFAULT_COMFYUI_BASE_URL;
                    }
                }
                if (!this.userModuleCreateModal.models.length) await this.loadUserModuleModels();
            },
            closeUserModuleCreateModal() {
                if (this.userModuleCreateModal.loading) return;
                this.userModuleCreateModal.show = false;
            },
            async loadUserModuleModels() {
                this.userModuleCreateModal.modelsLoading = true;
                try {
                    const response = await axios.get('/api/models', { headers: this.userModuleHeaders() });
                    const payload = response.data || {};
                    this.userModuleCreateModal.models = this.sortUserModuleModels(payload.models || payload.data || []);
                    if (!this.userModuleCreateModal.modelId && this.userModuleCreateModal.models.length) {
                        const preferred = this.pickPreferredUserModuleModel(this.userModuleCreateModal.models);
                        this.userModuleCreateModal.modelId = this.userModuleModelOptionValue(preferred);
                    }
                } catch (error) {
                    this.showToast(this.handleUserModuleError(error, 'um_models_failed'), 'error');
                } finally {
                    this.userModuleCreateModal.modelsLoading = false;
                }
            },
            userModuleModelName(model) {
                return String(model.display_name || model.model_name || model.name || model.model || '').trim();
            },
            userModuleModelVendor(model) {
                return String(model.vendor_name || model.vendor?.name || '').trim().toLowerCase();
            },
            isPreferredUserModuleModel(model) {
                return this.userModuleModelName(model).toLowerCase() === 'deepseek-v4-flash'
                    && this.userModuleModelVendor(model) === 'deepseek';
            },
            pickPreferredUserModuleModel(models) {
                return models.find((item) => this.isPreferredUserModuleModel(item))
                    || models.find((item) => this.userModuleModelName(item).toLowerCase() === 'deepseek-v4-flash')
                    || models[0];
            },
            sortUserModuleModels(models) {
                return [...models].sort((left, right) => {
                    const leftRank = this.isPreferredUserModuleModel(left) ? 0
                        : (this.userModuleModelName(left).toLowerCase() === 'deepseek-v4-flash' ? 1 : 2);
                    const rightRank = this.isPreferredUserModuleModel(right) ? 0
                        : (this.userModuleModelName(right).toLowerCase() === 'deepseek-v4-flash' ? 1 : 2);
                    if (leftRank !== rightRank) return leftRank - rightRank;
                    return this.userModuleModelLabel(left).localeCompare(this.userModuleModelLabel(right), 'zh-CN');
                });
            },
            userModuleModelLabel(model) {
                const name = this.userModuleModelName(model) || model.id;
                const vendor = model.vendor_name || model.vendor?.name;
                const label = vendor ? `${vendor} · ${name}` : String(name);
                return this.isPreferredUserModuleModel(model) ? `${label}（${this.t('um_model_recommended')}）` : label;
            },
            userModuleModelOptionValue(model) {
                return `${model.model_id || model.id}:${model.vendor_id || ''}`;
            },
            onUserModuleWorkflowFile(event) {
                const file = event && event.target && event.target.files && event.target.files[0];
                const form = this.userModuleCreateModal;
                if (!file) {
                    form.workflowJson = '';
                    form.workflowFileName = '';
                    return;
                }
                const reader = new FileReader();
                reader.onload = () => {
                    form.workflowJson = String(reader.result || '');
                    form.workflowFileName = file.name;
                };
                reader.onerror = () => {
                    form.workflowJson = '';
                    form.workflowFileName = '';
                    this.showToast(this.t('um_comfyui_workflow'), 'error');
                };
                reader.readAsText(file, 'utf-8');
            },
            async startUserModuleAgent() {
                if (!this.canStartUserModuleAgent || this.userModuleCreateModal.loading) return;
                this.userModuleCreateModal.loading = true;
                try {
                    const selectedModel = this.userModuleCreateModal.models.find((item) => (
                        this.userModuleModelOptionValue(item) === String(this.userModuleCreateModal.modelId)
                    )) || {};
                    const selectedModelId = Number(selectedModel.model_id || selectedModel.id);
                    if (!selectedModelId) throw new Error(this.t('um_model_placeholder'));
                    const form = this.userModuleCreateModal;
                    const requestBody = {
                        module_id: form.moduleId,
                        requirement: form.requirement.trim(),
                        model_id: selectedModelId,
                        vendor_id: selectedModel.vendor_id ? Number(selectedModel.vendor_id) : null,
                        language: this.locale || 'zh-CN',
                        connector: form.connector || 'http',
                    };
                    if (requestBody.connector === 'local_comfyui') {
                        requestBody.comfyui_base_url = form.comfyuiBaseUrl.trim();
                        requestBody.workflow_json = form.workflowJson;
                        try {
                            window.localStorage.setItem('zjt_um_comfyui_base_url', requestBody.comfyui_base_url);
                        } catch (_err) { /* ignore quota / private mode */ }
                    }
                    const response = await axios.post(`${API_ROOT}/agent/tasks`, requestBody, { headers: this.userModuleHeaders() });
                    const payload = unwrap(response) || {};
                    const taskId = payload.task_id || payload.id;
                    if (!taskId) throw new Error(this.t('um_missing_task_id'));
                    this.userModuleCreateModal.show = false;
                    this.userModuleCreateModal.confirmed = false;
                    this.openUserModuleAgentModal(taskId, payload);
                } catch (error) {
                    this.showToast(this.handleUserModuleError(error, 'um_start_failed'), 'error');
                } finally {
                    this.userModuleCreateModal.loading = false;
                }
            },
            reopenUserModuleAgentTask(task) {
                // 关闭后重新打开：openUserModuleAgentModal 支持从 after_id=0 全量重放消息并恢复轮询
                this.openUserModuleAgentModal(task.task_id, {
                    generation_id: task.generation_id,
                    status: task.status,
                });
            },
            openUserModuleAgentModal(taskId, payload = {}) {
                this.stopUserModuleAgentPolling();
                Object.assign(this.userModuleAgentModal, {
                    show: true,
                    taskId,
                    generationId: payload.generation_id || '',
                    status: payload.status || 'pending',
                    messages: [],
                    lastMessageId: 0,
                    polling: false,
                    error: '',
                    drafts: {},
                    pendingQuestionNotified: false,
                });
                this.pollUserModuleAgent();
            },
            closeUserModuleAgentModal() {
                this.userModuleAgentModal.show = false;
                if (this.userModuleAgentTerminal) this.stopUserModuleAgentPolling();
                else if (this.userModuleAgentModal.taskId) this.showToast(this.t('um_background_notice'), 'success');
            },
            stopUserModuleAgentPolling() {
                if (this.userModuleAgentModal.pollTimer) clearTimeout(this.userModuleAgentModal.pollTimer);
                this.userModuleAgentModal.pollTimer = null;
            },
            scheduleUserModuleAgentPoll() {
                this.stopUserModuleAgentPolling();
                if (!this.userModuleAgentModal.taskId || this.userModuleAgentTerminal) return;
                this.userModuleAgentModal.pollTimer = setTimeout(() => this.pollUserModuleAgent(), POLL_INTERVAL_MS);
            },
            async pollUserModuleAgent() {
                if (!this.userModuleAgentModal.taskId || this.userModuleAgentModal.polling) return;
                this.userModuleAgentModal.polling = true;
                try {
                    const response = await axios.get(`${API_ROOT}/agent/tasks/${encodeURIComponent(this.userModuleAgentModal.taskId)}`, {
                        params: { after_id: this.userModuleAgentModal.lastMessageId },
                        headers: this.userModuleHeaders(),
                    });
                    const payload = unwrap(response) || {};
                    const task = payload.task || payload;
                    const messages = payload.messages || task.messages || [];
                    for (const message of messages) {
                        const normalized = { ...message, _localId: `${Date.now()}-${Math.random()}` };
                        this.userModuleAgentModal.messages.push(normalized);
                        if (Number(message.id) > this.userModuleAgentModal.lastMessageId) this.userModuleAgentModal.lastMessageId = Number(message.id);
                        if (!this.userModuleAgentModal.generationId && message.generation_id) this.userModuleAgentModal.generationId = message.generation_id;
                        if (message.type === 'question' && message.question_id && !this.userModuleAgentModal.drafts[message.question_id]) {
                            this.userModuleAgentModal.drafts[message.question_id] = {
                                selected: '',
                                freeText: '',
                                submitting: false,
                                submitted: false,
                            };
                        }
                    }
                    this.userModuleAgentModal.status = task.status || payload.status || this.userModuleAgentModal.status;
                    this.userModuleAgentModal.generationId = task.generation_id || payload.generation_id || this.userModuleAgentModal.generationId;
                    this.syncUserModuleQuestionDrafts();
                    if (this.hasPendingUserModuleQuestion && !this.userModuleAgentModal.show && !this.userModuleAgentModal.pendingQuestionNotified) {
                        this.userModuleAgentModal.show = true;
                        this.userModuleAgentModal.pendingQuestionNotified = true;
                        this.showToast(this.t('um_agent_pending_banner'), 'success');
                    }
                    if (!this.hasPendingUserModuleQuestion) this.userModuleAgentModal.pendingQuestionNotified = false;
                    const resultText = task.result || task.error;
                    if (resultText && !this.userModuleAgentModal.messages.some((item) => item._terminalSummary)) {
                        this.userModuleAgentModal.messages.push({
                            type: task.error ? 'error' : 'done',
                            content: resultText,
                            _terminalSummary: true,
                            _localId: `terminal-${Date.now()}`,
                        });
                    }
                    this.$nextTick(() => {
                        const feed = this.$refs.userModuleAgentFeed;
                        if (feed) feed.scrollTop = feed.scrollHeight;
                    });
                    if (this.userModuleAgentTerminal) await this.loadUserModules();
                } catch (error) {
                    this.userModuleAgentModal.error = this.handleUserModuleError(error, 'um_agent_poll_failed');
                } finally {
                    this.userModuleAgentModal.polling = false;
                    this.scheduleUserModuleAgentPoll();
                }
            },
            userModuleAgentMessageLabel(message) {
                const type = String(message.type || 'message');
                const key = `um_agent_event_${type}`;
                const translated = this.t(key);
                return translated === key ? type : translated;
            },
            userModuleAgentMessageContent(message) {
                if (message.type === 'answer') {
                    const selected = message.selected ? `${this.t('um_agent_question_selected')}: ${message.selected}` : '';
                    const extra = message.free_text || '';
                    return [selected, extra].filter(Boolean).join('\n') || String(message.content || '');
                }
                if (message.type === 'tool_call') {
                    const names = Array.isArray(message.tool_names) ? message.tool_names.filter(Boolean) : [];
                    if (names.length) return `${this.t('um_agent_event_tool_call')}: ${names.join('、')}`;
                }
                const value = message.content ?? message.message ?? message.step ?? message.error ?? message.result ?? message;
                return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
            },
            userModuleQuestionId(message) {
                return String(message.question_id || message.id || '');
            },
            userModuleAnsweredQuestionIds() {
                const answered = new Set();
                for (const message of this.userModuleAgentModal.messages) {
                    if ((message.type === 'answer' || message.type === 'question_timeout') && message.question_id) {
                        answered.add(String(message.question_id));
                    }
                }
                return answered;
            },
            userModuleQuestionOutcome(message) {
                const questionId = this.userModuleQuestionId(message);
                if (!questionId) return 'pending';
                if (this.userModuleAgentModal.drafts[questionId]?.submitted) return 'answered';
                for (const item of this.userModuleAgentModal.messages) {
                    if (String(item.question_id || '') !== questionId) continue;
                    if (item.type === 'answer') return 'answered';
                    if (item.type === 'question_timeout') return 'timeout';
                }
                return 'pending';
            },
            isPendingUserModuleQuestion(message) {
                return String(message.type || '') === 'question' && this.userModuleQuestionOutcome(message) === 'pending';
            },
            isUserModuleQuestionLocked(message) {
                return !this.isPendingUserModuleQuestion(message);
            },
            userModuleQuestionOptions(message) {
                const options = Array.isArray(message.options) ? message.options : [];
                return options.map((item) => {
                    if (item && typeof item === 'object') {
                        const value = String(item.value ?? item.label ?? '');
                        return { value, label: String(item.label || value) };
                    }
                    return { value: String(item), label: String(item) };
                }).filter((item) => item.value);
            },
            userModuleQuestionDraft(message) {
                const questionId = this.userModuleQuestionId(message);
                if (!questionId) return { selected: '', freeText: '', submitting: false, submitted: false };
                const drafts = this.userModuleAgentModal.drafts;
                if (!drafts[questionId]) {
                    drafts[questionId] = { selected: '', freeText: '', submitting: false, submitted: false };
                }
                return drafts[questionId];
            },
            syncUserModuleQuestionDrafts() {
                const answered = this.userModuleAnsweredQuestionIds();
                for (const questionId of answered) {
                    const draft = this.userModuleAgentModal.drafts[questionId];
                    if (draft) draft.submitted = true;
                }
            },
            selectUserModuleQuestionOption(message, value) {
                if (this.isUserModuleQuestionLocked(message)) return;
                const draft = this.userModuleQuestionDraft(message);
                draft.selected = draft.selected === value ? '' : value;
            },
            async submitUserModuleQuestionAnswer(message) {
                if (!this.userModuleAgentModal.taskId || this.isUserModuleQuestionLocked(message)) return;
                const draft = this.userModuleQuestionDraft(message);
                const selected = String(draft.selected || '').trim();
                const freeText = String(draft.freeText || '').trim();
                if (!selected && !freeText) {
                    this.showToast(this.t('um_agent_question_need_choice'), 'error');
                    return;
                }
                draft.submitting = true;
                try {
                    await axios.post(
                        `${API_ROOT}/agent/tasks/${encodeURIComponent(this.userModuleAgentModal.taskId)}/answers`,
                        {
                            question_id: this.userModuleQuestionId(message),
                            selected: selected || null,
                            free_text: freeText || null,
                        },
                        { headers: this.userModuleHeaders() },
                    );
                    draft.submitted = true;
                    this.pollUserModuleAgent();
                } catch (error) {
                    this.showToast(this.handleUserModuleError(error, 'um_agent_question_submit_failed'), 'error');
                } finally {
                    draft.submitting = false;
                }
            },
            async finishUserModuleAgent() {
                const generationId = this.userModuleAgentModal.generationId;
                this.closeUserModuleAgentModal();
                await this.loadUserModules();
                if (generationId) await this.openUserModuleGeneration({ generation_id: generationId });
            },

            async openUserModuleGeneration(generation) {
                const generationId = generation.generation_id;
                if (!generationId) return;
                Object.assign(this.userModuleGenerationModal, {
                    show: true,
                    loading: true,
                    actionLoading: false,
                    generation: generation,
                    files: [],
                    selectedPath: '',
                    content: '',
                    fileSize: 0,
                    validation: generation.validation || null,
                    review: generation.review || null,
                    secretNames: [],
                    error: '',
                });
                try {
                    const response = await axios.get(`${API_ROOT}/generations/${encodeURIComponent(generationId)}`, { headers: this.userModuleHeaders() });
                    const payload = unwrap(response) || {};
                    this.userModuleGenerationModal.generation = payload;
                    this.userModuleGenerationModal.files = payload.files || [];
                    this.userModuleGenerationModal.validation = payload.validation || null;
                    this.userModuleGenerationModal.review = payload.review || null;
                    this.userModuleGenerationModal.secretNames = this._extractUserModuleSecretNames(payload.validation?.manifest);
                    await this._loadUserModuleSecretNames(generationId);
                    const first = this.userModuleGenerationModal.files.find((item) => item.path === 'manifest.json') || this.userModuleGenerationModal.files[0];
                    if (first) await this.selectUserModuleFile(first);
                } catch (error) {
                    this.userModuleGenerationModal.error = this.handleUserModuleError(error, 'um_generation_load_failed');
                } finally {
                    this.userModuleGenerationModal.loading = false;
                }
            },
            closeUserModuleGenerationModal() {
                if (!this.userModuleGenerationModal.actionLoading) this.userModuleGenerationModal.show = false;
            },
            async selectUserModuleFile(file) {
                if (!file || !this.userModuleGenerationModal.generation?.generation_id) return;
                this.userModuleGenerationModal.selectedPath = file.path;
                this.userModuleGenerationModal.fileSize = file.size || 0;
                this.userModuleGenerationModal.fileLoading = true;
                try {
                    const response = await axios.get(`${API_ROOT}/generations/${encodeURIComponent(this.userModuleGenerationModal.generation.generation_id)}/files/content`, {
                        params: { path: file.path },
                        headers: this.userModuleHeaders(),
                    });
                    const payload = unwrap(response) || {};
                    this.userModuleGenerationModal.content = payload.content || '';
                    this.userModuleGenerationModal.fileSize = payload.size || file.size || 0;
                } catch (error) {
                    this.userModuleGenerationModal.error = this.handleUserModuleError(error, 'um_file_load_failed');
                } finally {
                    this.userModuleGenerationModal.fileLoading = false;
                }
            },
            userModuleFileIcon(path) {
                if (path === 'manifest.json') return '{}';
                if (path.endsWith('.py')) return 'Py';
                if (path.endsWith('.md')) return 'Md';
                return '·';
            },
            _extractUserModuleSecretNames(manifest) {
                const names = manifest?.permissions?.secret_names;
                return Array.isArray(names) ? names.filter((name) => typeof name === 'string') : [];
            },
            async _loadUserModuleSecretNames(generationId) {
                try {
                    const response = await axios.get(`${API_ROOT}/generations/${encodeURIComponent(generationId)}/files/content`, {
                        params: { path: 'manifest.json' },
                        headers: this.userModuleHeaders(),
                    });
                    const manifest = JSON.parse((unwrap(response) || {}).content || '{}');
                    this.userModuleGenerationModal.secretNames = this._extractUserModuleSecretNames(manifest);
                } catch (error) {
                    console.warn('Failed to load manifest secret names:', error);
                }
            },
            userModuleSecretInfo(secretName) {
                return this.userModuleSecretCatalog.find((item) => item.secret_name === secretName) || null;
            },
            async validateUserModuleGeneration() {
                const generation = this.userModuleGenerationModal.generation;
                if (!generation || !WRITABLE_GENERATION_STATES.has(generation.status)) return;
                this.userModuleGenerationModal.actionLoading = true;
                this.userModuleGenerationModal.error = '';
                try {
                    const response = await axios.post(`${API_ROOT}/generations/${encodeURIComponent(generation.generation_id)}/validate`, null, { headers: this.userModuleHeaders() });
                    const validation = unwrap(response) || {};
                    this.userModuleGenerationModal.validation = validation;
                    this.userModuleGenerationModal.review = validation.review || null;
                    this.userModuleGenerationModal.secretNames = this._extractUserModuleSecretNames(validation.manifest);
                    this.userModuleGenerationModal.generation = {
                        ...generation,
                        status: validation.ok ? 'validated' : 'validation_failed',
                        validation,
                        review: validation.review || null,
                        review_gate: validation.review_gate || generation.review_gate,
                    };
                    const reviewBlocked = validation.review_gate?.required && validation.review_gate?.publishable !== true;
                    this.showToast(
                        reviewBlocked
                            ? this.t('um_review_not_completed')
                            : (validation.ok ? this.t('um_validation_passed') : this.t('um_validation_failed')),
                        validation.ok && !reviewBlocked ? 'success' : 'error',
                    );
                    await this.loadUserModules();
                } catch (error) {
                    const validation = error?.response?.data?.data;
                    if (validation) {
                        this.userModuleGenerationModal.validation = validation;
                        this.userModuleGenerationModal.generation.status = 'validation_failed';
                    }
                    this.userModuleGenerationModal.error = this.handleUserModuleError(error, 'um_validate_failed');
                } finally {
                    this.userModuleGenerationModal.actionLoading = false;
                }
            },
            async approveUserModuleGeneration() {
                if (!this.canApproveUserModuleGeneration) return;
                if (!confirm(this.t('um_approve_confirm'))) return;
                const generation = this.userModuleGenerationModal.generation;
                this.userModuleGenerationModal.actionLoading = true;
                try {
                    const response = await axios.post(`${API_ROOT}/generations/${encodeURIComponent(generation.generation_id)}/approve`, null, { headers: this.userModuleHeaders() });
                    const payload = unwrap(response) || {};
                    this.userModuleGenerationModal.generation = { ...generation, ...payload };
                    this.showToast(this.t('um_approve_success'), 'success');
                    this.userModuleGenerationModal.show = false;
                    await this.loadUserModules();
                    const module = this.userModules.modules.find((item) => item.module_id === generation.module_id) || { module_id: generation.module_id };
                    await this.openUserModuleDetail(module);
                } catch (error) {
                    await this.refreshUserModuleGenerationAfterFailure();
                    this.userModuleGenerationModal.error = this.handleUserModuleError(error, 'um_approve_failed');
                } finally {
                    this.userModuleGenerationModal.actionLoading = false;
                }
            },

            async refreshUserModuleGenerationAfterFailure() {
                const generationId = this.userModuleGenerationModal.generation?.generation_id;
                if (!generationId) return;
                try {
                    const response = await axios.get(`${API_ROOT}/generations/${encodeURIComponent(generationId)}`, { headers: this.userModuleHeaders() });
                    const payload = unwrap(response) || {};
                    this.userModuleGenerationModal.generation = payload;
                    this.userModuleGenerationModal.files = payload.files || this.userModuleGenerationModal.files;
                    this.userModuleGenerationModal.validation = payload.validation || null;
                    this.userModuleGenerationModal.review = payload.review || null;
                    await this.loadUserModules();
                } catch (_refreshError) {
                    // 保留原始批准错误；刷新失败不覆盖更有用的诊断信息。
                }
            },

            async openUserModuleDetail(module) {
                Object.assign(this.userModuleDetailModal, { show: true, loading: true, module, releases: [], error: '' });
                Object.assign(this.userModuleBindings, { bindings: [], targets: null, form: { taskByOperation: {} }, loading: true, error: '' });
                try {
                    const response = await axios.get(`${API_ROOT}/${encodeURIComponent(module.module_id)}/releases`, { headers: this.userModuleHeaders() });
                    this.userModuleDetailModal.releases = arrayFrom(unwrap(response), ['releases', 'items', 'list']);
                } catch (error) {
                    this.userModuleDetailModal.error = this.handleUserModuleError(error, 'um_releases_failed');
                } finally {
                    this.userModuleDetailModal.loading = false;
                }
                await this.loadUserModuleBindings(module.module_id);
            },
            async loadUserModuleBindings(moduleId) {
                this.userModuleBindings.loading = true;
                this.userModuleBindings.error = '';
                this.userModuleBindings.inactiveHint = false;
                try {
                    const requests = [
                        axios.get(`${API_ROOT}/${encodeURIComponent(moduleId)}/bindings`, { headers: this.userModuleHeaders() }),
                        axios.get(`${API_ROOT}/binding-targets`, { params: { module_id: moduleId }, headers: this.userModuleHeaders() }),
                    ];
                    // 分别容错：绑定列表失败才算加载失败；未激活模块的 targets 400 转为引导提示
                    const [bindingResult, targetResult] = await Promise.allSettled(requests);
                    if (bindingResult.status === 'fulfilled') {
                        this.userModuleBindings.bindings = arrayFrom(unwrap(bindingResult.value) || {}, ['bindings']);
                    } else {
                        this.userModuleBindings.bindings = [];
                        this.userModuleBindings.targets = { capabilities: [], tasks: {} };
                        this.userModuleBindings.error = this.handleUserModuleError(bindingResult.reason, 'um_bindings_failed');
                        return;
                    }
                    if (targetResult.status === 'fulfilled') {
                        const targets = unwrap(targetResult.value) || {};
                        this.userModuleBindings.targets = { capabilities: targets.capabilities || [], tasks: targets.tasks || {} };
                    } else {
                        const errorCode = targetResult.reason?.response?.data?.error_code;
                        if (errorCode === 'MODULE_NOT_ACTIVE') {
                            // 未激活模块无法绑定属预期：引导点击上方「启用此实现」，而不是报错
                            this.userModuleBindings.targets = { capabilities: [], tasks: {} };
                            this.userModuleBindings.inactiveHint = true;
                        } else {
                            console.warn('Failed to load binding targets:', targetResult.reason);
                            this.userModuleBindings.targets = { capabilities: [], tasks: {} };
                        }
                        return;
                    }
                    const taskByOperation = { ...this.userModuleBindings.form.taskByOperation };
                    for (const capability of this.userModuleBindings.targets.capabilities) {
                        if (!Object.prototype.hasOwnProperty.call(taskByOperation, capability.operation)) {
                            taskByOperation[capability.operation] = '';
                        }
                    }
                    this.userModuleBindings.form = { taskByOperation };
                } finally {
                    this.userModuleBindings.loading = false;
                }
            },
            userModuleCapabilityLabel(operation) {
                const key = `um_capability_${operation}`;
                const translated = this.t(key);
                return translated === key ? operation : translated;
            },
            userModuleBindingTaskOptions(operation) {
                if (!operation) return [];
                const categoryByOperation = {
                    text_to_video: 'text_to_video',
                    image_to_video: 'image_to_video',
                    text_to_image: 'text_to_image',
                    image_edit: 'image_edit',
                };
                const category = categoryByOperation[operation];
                const boundIds = new Set(
                    (this.userModuleBindings.bindings || [])
                        .filter((item) => item.operation === operation)
                        .map((item) => Number(item.task_id)),
                );
                return ((this.userModuleBindings.targets?.tasks || {})[category] || []).filter(
                    (task) => !boundIds.has(Number(task.id)),
                );
            },
            async createUserModuleBinding(operation) {
                const module = this.userModuleDetailModal.module;
                const taskId = this.userModuleBindings.form.taskByOperation[operation];
                if (!module || !operation || !taskId) return;
                this.userModuleBindings.actionLoading = true;
                this.userModuleBindings.error = '';
                try {
                    await axios.post(
                        `${API_ROOT}/${encodeURIComponent(module.module_id)}/bindings`,
                        { module_id: module.module_id, operation, task_id: Number(taskId) },
                        { headers: this.userModuleHeaders() },
                    );
                    this.showToast(this.t('um_binding_created'), 'success');
                    this.userModuleBindings.form.taskByOperation[operation] = '';
                    await this.loadUserModuleBindings(module.module_id);
                    // 新增绑定后刷新配置缓存，使新实现方尽快可见
                    await this.reloadConfigs();
                } catch (error) {
                    this.userModuleBindings.error = this.handleUserModuleError(error, 'um_binding_create_failed');
                } finally {
                    this.userModuleBindings.actionLoading = false;
                }
            },
            async deleteUserModuleBinding(binding) {
                const module = this.userModuleDetailModal.module;
                if (!binding || !confirm(this.t('um_binding_delete_confirm', { operation: this.userModuleCapabilityLabel(binding.operation) }))) return;
                this.userModuleBindings.actionLoading = true;
                this.userModuleBindings.error = '';
                try {
                    await axios.delete(`${API_ROOT}/bindings/${encodeURIComponent(binding.id)}`, { headers: this.userModuleHeaders() });
                    this.showToast(this.t('um_binding_deleted'), 'success');
                    await this.loadUserModuleBindings(module?.module_id);
                } catch (error) {
                    this.userModuleBindings.error = this.handleUserModuleError(error, 'um_binding_delete_failed');
                } finally {
                    this.userModuleBindings.actionLoading = false;
                }
            },
            closeUserModuleDetailModal() {
                if (!this.userModuleDetailModal.actionLoading) this.userModuleDetailModal.show = false;
            },
            isUserModuleEnabled(module) {
                return Boolean(module && (module.enabled || module.status === 'active'));
            },
            isCurrentUserModuleRelease(release) {
                const module = this.userModuleDetailModal.module || {};
                // 模块禁用后激活指针仍保留，此时不能再挂「当前启用」徽标，
                // 否则启用按钮（v-else）永远不渲染，模块没有任何入口恢复启用。
                if (!this.isUserModuleEnabled(module)) return false;
                return Number(module.active_release_id) === Number(release.id) || release.status === 'active';
            },
            async activateUserModuleRelease(release) {
                const module = this.userModuleDetailModal.module;
                if (!module) return;
                // 只有「模块启用中且已有激活指针」才是版本切换（rollback）；禁用后的恢复走启用语义
                const switching = this.isUserModuleEnabled(module) && module.active_release_id;
                if (!confirm(this.t(switching ? 'um_rollback_confirm' : 'um_enable_confirm', { version: release.version }))) return;
                this.userModuleDetailModal.actionLoading = true;
                try {
                    const action = switching ? `rollback/${release.id}` : `releases/${release.id}/activate`;
                    await axios.post(`${API_ROOT}/${encodeURIComponent(module.module_id)}/${action}`, null, { headers: this.userModuleHeaders() });
                    this.showToast(this.t(switching ? 'um_rollback_success' : 'um_enable_success'), 'success');
                    await this.loadUserModules();
                    const refreshed = this.userModules.modules.find((item) => item.module_id === module.module_id) || { ...module, active_release_id: release.id, enabled: true, status: 'active' };
                    await this.openUserModuleDetail(refreshed);
                } catch (error) {
                    if (error?.response?.data?.data) {
                        await this.loadUserModules();
                        const refreshed = this.userModules.modules.find((item) => item.module_id === module.module_id);
                        if (refreshed) await this.openUserModuleDetail(refreshed);
                    }
                    this.userModuleDetailModal.error = this.handleUserModuleError(error, 'um_activate_failed');
                } finally {
                    this.userModuleDetailModal.actionLoading = false;
                }
            },
            async enableUserModule(module) {
                // 模块列表行的「启用」入口：重新激活其当前激活指针指向的实现版本
                if (!module || !module.active_release_id) return;
                if (!confirm(this.t('um_enable_module_confirm', { module: module.module_id }))) return;
                this.userModules.busy = true;
                try {
                    await axios.post(
                        `${API_ROOT}/${encodeURIComponent(module.module_id)}/releases/${module.active_release_id}/activate`,
                        null,
                        { headers: this.userModuleHeaders() },
                    );
                    this.showToast(this.t('um_enable_success'), 'success');
                    await this.loadUserModules();
                } catch (error) {
                    if (error?.response?.data?.data) await this.loadUserModules();
                    this.showToast(this.handleUserModuleError(error, 'um_activate_failed'), 'error');
                } finally {
                    this.userModules.busy = false;
                }
            },
            async disableUserModule(module) {
                if (!confirm(this.t('um_disable_confirm', { module: module.module_id }))) return;
                this.userModules.busy = true;
                try {
                    await axios.post(`${API_ROOT}/${encodeURIComponent(module.module_id)}/disable`, null, { headers: this.userModuleHeaders() });
                    this.showToast(this.t('um_disable_success'), 'success');
                    await this.loadUserModules();
                } catch (error) {
                    if (error?.response?.data?.data) await this.loadUserModules();
                    this.showToast(this.handleUserModuleError(error, 'um_disable_failed'), 'error');
                } finally {
                    this.userModules.busy = false;
                }
            },

            async deleteUserModule(module) {
                if (!module || !module.module_id) return;
                const moduleId = module.module_id;
                if (module.enabled || module.status === 'active') {
                    this.showToast(this.t('um_delete_need_disabled'), 'warning');
                    return;
                }
                if (!confirm(this.t('um_delete_confirm', { module: moduleId }))) return;
                this.userModules.busy = true;
                try {
                    await axios.delete(`${API_ROOT}/${encodeURIComponent(moduleId)}`, { headers: this.userModuleHeaders() });
                    this.showToast(this.t('um_delete_success'), 'success');
                    if (this.userModuleDetailModal.show && this.userModuleDetailModal.module?.module_id === moduleId) {
                        this.userModuleDetailModal.show = false;
                    }
                    await this.loadUserModules();
                } catch (error) {
                    this.showToast(this.handleUserModuleError(error, 'um_delete_failed'), 'error');
                } finally {
                    this.userModules.busy = false;
                }
            },

            async openUserModuleReleaseCode(module, release) {
                if (!module || !release) return;
                Object.assign(this.userModuleCodeModal, {
                    show: true,
                    loading: true,
                    moduleId: module.module_id,
                    releaseId: release.id,
                    version: release.version || '',
                    files: [],
                    selectedPath: '',
                    content: '',
                    fileSize: 0,
                    fileLoading: false,
                    error: '',
                });
                try {
                    const response = await axios.get(
                        `${API_ROOT}/${encodeURIComponent(module.module_id)}/releases/${encodeURIComponent(release.id)}/files`,
                        { headers: this.userModuleHeaders() },
                    );
                    const payload = unwrap(response) || {};
                    this.userModuleCodeModal.files = payload.files || [];
                    const first = this.userModuleCodeModal.files.find((item) => item.path === 'src/driver.py')
                        || this.userModuleCodeModal.files.find((item) => item.path === 'manifest.json')
                        || this.userModuleCodeModal.files[0];
                    if (first) await this.selectUserModuleCodeFile(first);
                } catch (error) {
                    this.userModuleCodeModal.error = this.handleUserModuleError(error, 'um_code_files_failed');
                } finally {
                    this.userModuleCodeModal.loading = false;
                }
            },
            async selectUserModuleCodeFile(file) {
                if (!file || !this.userModuleCodeModal.moduleId || !this.userModuleCodeModal.releaseId) return;
                this.userModuleCodeModal.selectedPath = file.path;
                this.userModuleCodeModal.fileSize = file.size || 0;
                this.userModuleCodeModal.fileLoading = true;
                try {
                    const response = await axios.get(
                        `${API_ROOT}/${encodeURIComponent(this.userModuleCodeModal.moduleId)}/releases/${encodeURIComponent(this.userModuleCodeModal.releaseId)}/files/content`,
                        { params: { path: file.path }, headers: this.userModuleHeaders() },
                    );
                    const payload = unwrap(response) || {};
                    this.userModuleCodeModal.content = payload.content || '';
                    this.userModuleCodeModal.fileSize = payload.size || file.size || 0;
                } catch (error) {
                    this.userModuleCodeModal.error = this.handleUserModuleError(error, 'um_code_file_failed');
                } finally {
                    this.userModuleCodeModal.fileLoading = false;
                }
            },
            closeUserModuleCodeModal() {
                this.userModuleCodeModal.show = false;
            },
        },
    };
}());
