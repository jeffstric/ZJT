        let sessionId = null;
        let isProcessing = false;
        let pendingVerificationId = null;
        let pendingVerificationData = null;
        let needsNewMessageDiv = false;
        let fullText = ''; // 全局变量，用于累积消息内容
        const urlParams = new URLSearchParams(window.location.search);
        
        // 全局参数：从URL获取并存储，供所有接口使用
        const USER_ID = urlParams.get('user_id');
        const WORLD_ID = urlParams.get('world_id');
        const WORKFLOW_ID = urlParams.get('workflow_id')
        // auth_token 从 localStorage 读取，不再从 URL 获取，避免敏感信息暴露
        const AUTH_TOKEN = localStorage.getItem('auth_token') || '';

        // 角度常量类 - 统一管理多角度图片的角度定义
        const AngleKey = {
            RIGHT_90: 'right',
            BACK_180: 'back',
            LEFT_270: 'left'
        };

        // 角度配置列表 - 用于生成多角度图片
        const ANGLES_CONFIG = [
            { angle: 90, label: '90°', angleKey: AngleKey.RIGHT_90 },
            { angle: 180, label: '180°', angleKey: AngleKey.BACK_180 },
            { angle: 270, label: '270°', angleKey: AngleKey.LEFT_270 }
        ];

        // 角度label到角度值的映射
        const ANGLE_LABEL_MAP = {
            // 纯角度格式 (主要格式)
            '90°': { angle: 90, angleKey: AngleKey.RIGHT_90 },
            '180°': { angle: 180, angleKey: AngleKey.BACK_180 },
            '270°': { angle: 270, angleKey: AngleKey.LEFT_270 },
            // 英文格式
            'right': { angle: 90, angleKey: AngleKey.RIGHT_90 },
            'back': { angle: 180, angleKey: AngleKey.BACK_180 },
            'left': { angle: 270, angleKey: AngleKey.LEFT_270 },
            // 纯数字
            '90': { angle: 90, angleKey: AngleKey.RIGHT_90 },
            '180': { angle: 180, angleKey: AngleKey.BACK_180 },
            '270': { angle: 270, angleKey: AngleKey.LEFT_270 },
            // 旧格式兼容
            '右侧 (90°)': { angle: 90, angleKey: AngleKey.RIGHT_90 },
            '背面 (180°)': { angle: 180, angleKey: AngleKey.BACK_180 },
            '左侧 (270°)': { angle: 270, angleKey: AngleKey.LEFT_270 },
            '右侧': { angle: 90, angleKey: AngleKey.RIGHT_90 },
            '背面': { angle: 180, angleKey: AngleKey.BACK_180 },
            '左侧': { angle: 270, angleKey: AngleKey.LEFT_270 }
        };

        const LOGIN_URL = window.location.origin + '/?login=1&redirect_url=video-workflow-list';

        // LLM 供应商常量（从 /api/vendors 动态加载）
        const LLMVendor = {};
        // 供应商图标映射（从 /api/vendors 动态加载）
        const vendorIcons = {};

        // LLM 模型名称常量
        const LLMModel = {
            GEMINI_3_FLASH: 'gemini-3-flash-preview',
            GEMINI_3_1_PRO: 'gemini-3.1-pro-preview',
            QWEN_3_5_PLUS: 'qwen3.5-plus',
            QWEN_3_6_PLUS: 'qwen3.6-plus',
            QWEN_PLUS: 'qwen-plus',
            OLLAMA_QWEN_3_6_35B: 'qwen3.6:35b-a3b'
        };
        const STORY_TYPE_LABELS = {
            dialogue: '对话剧情',
            narration: '旁白解说',
            music_mv: '音乐MV'
        };

        function normalizeStoryType(storyType) {
            return Object.prototype.hasOwnProperty.call(STORY_TYPE_LABELS, storyType)
                ? storyType
                : 'dialogue';
        }

        function getStoryTypeLabel(storyType) {
            const normalized = normalizeStoryType(storyType);
            const key = `story_type_${normalized}`;
            return window.t ? window.t(key) : (STORY_TYPE_LABELS[normalized] || STORY_TYPE_LABELS.dialogue);
        }
        let isCommunityEdition = false;  // 默认为商业版，页面初始化时通过API更新
        let currentFileType = 'worlds';
        let currentEditFile = { fileType: '', fileName: '' };
        let currentEditWorld = { id: '', name: '', description: '', story_type: 'dialogue' };
        let driverStatus = {};  // 驱动可用状态

        function handleTokenExpired() {
            alert('⚠️ ' + (window.t ? window.t('alert_login_expired') : '登录已过期\n\n您的登录信息已过期，请重新登录。'));
            window.location.href = LOGIN_URL;
        }

        function checkTokenExpired(data, response) {
            if (data && (data.token_expired || data.error_code === 'TOKEN_EXPIRED')) {
                handleTokenExpired();
                return true;
            }
            if (response && response.status === 401) {
                handleTokenExpired();
                return true;
            }
            return false;
        }

        const carouselState = {
            currentIndex: 0,
            slides: [],
            indicators: [],
            track: null,
            autoplayInterval: 3000,
            autoplayTimer: null
        };

        // 轮播卡片数据与动态渲染
        const carouselData = [
            { tag_key: 'slide_tag_orchestrator', title_key: 'script_orchestrator', features_key: 'orchestrator_features' },
            { tag_key: 'slide_tag_architect', title_key: 'story_architect', features_key: 'architect_features' },
            { tag_key: 'slide_tag_writer', title_key: 'episode_writer', features_key: 'writer_features' },
            { tag_key: 'slide_tag_reviewer', title_key: 'content_reviewer', features_key: 'reviewer_features' },
            { tag_key: 'slide_tag_splitter', title_key: 'script_splitter', features_key: 'splitter_features' },
            { tag_key: 'slide_tag_designer', title_key: 'character_designer', features_key: 'designer_features' },
            { tag_key: 'slide_tag_visualizer', title_key: 'character_visualizer', features_key: 'visualizer_features' },
            { tag_key: 'slide_tag_scene', title_key: 'scene_designer', features_key: 'scene_designer_features' },
            { tag_key: 'slide_tag_renderer', title_key: 'visual_renderer', features_key: 'renderer_features' },
        ];

        function renderCarousel() {
            const track = document.getElementById('carousel-track');
            if (!track) return;
            const t = window.t || (k => k);
            let html = '';
            carouselData.forEach((item, idx) => {
                const tag = t(item.tag_key);
                const title = t(item.title_key);
                const featuresRaw = t(item.features_key);
                const features = featuresRaw.split(';').map(f => f.trim()).filter(Boolean);
                html += `<div class="carousel-slide${idx === 0 ? ' active' : ''}" data-slide="${idx}">`;
                html += `<p class="slide-tag">${tag}</p>`;
                html += `<h3>${title}</h3>`;
                html += '<ul>';
                features.forEach(f => { html += `<li>${f}</li>`; });
                html += '</ul></div>';
            });
            track.innerHTML = html;
        }

        function initCarousel() {
            const carousel = document.getElementById('agent-carousel');
            if (!carousel) return;

            stopCarouselAutoplay();
            carouselState.currentIndex = 0;

            carouselState.track = carousel.querySelector('.carousel-track');
            carouselState.slides = Array.from(carousel.querySelectorAll('.carousel-slide'));
            carouselState.indicators = Array.from(carousel.querySelectorAll('.indicator'));

            const prevBtn = document.getElementById('carousel-prev');
            const nextBtn = document.getElementById('carousel-next');

            // 移除旧监听器防止重复绑定
            if (carouselState._prevHandler) prevBtn?.removeEventListener('click', carouselState._prevHandler);
            if (carouselState._nextHandler) nextBtn?.removeEventListener('click', carouselState._nextHandler);

            carouselState._prevHandler = () => moveSlide(-1);
            carouselState._nextHandler = () => moveSlide(1);
            prevBtn?.addEventListener('click', carouselState._prevHandler);
            nextBtn?.addEventListener('click', carouselState._nextHandler);

            carouselState.indicators.forEach((indicator, idx) => {
                indicator.addEventListener('click', () => goToSlide(idx));
            });

            updateCarousel();
            startCarouselAutoplay();
        }

        function moveSlide(direction, isAuto = false) {
            const total = carouselState.slides.length;
            carouselState.currentIndex = (carouselState.currentIndex + direction + total) % total;
            updateCarousel();
            if (!isAuto) {
                resetCarouselAutoplay();
            }
        }

        function goToSlide(index) {
            carouselState.currentIndex = index;
            updateCarousel();
            resetCarouselAutoplay();
        }

        function updateCarousel() {
            const offset = -carouselState.currentIndex * 100;
            if (carouselState.track) {
                carouselState.track.style.transform = `translateX(${offset}%)`;
            }

            carouselState.slides.forEach((slide, idx) => {
                slide.classList.toggle('active', idx === carouselState.currentIndex);
            });

            carouselState.indicators.forEach((indicator, idx) => {
                indicator.classList.toggle('active', idx === carouselState.currentIndex);
            });
        }

        function startCarouselAutoplay() {
            if (carouselState.autoplayTimer || carouselState.slides.length <= 1) return;
            carouselState.autoplayTimer = setInterval(() => moveSlide(1, true), carouselState.autoplayInterval);
        }

        function stopCarouselAutoplay() {
            if (carouselState.autoplayTimer) {
                clearInterval(carouselState.autoplayTimer);
                carouselState.autoplayTimer = null;
            }
        }

        function resetCarouselAutoplay() {
            stopCarouselAutoplay();
            startCarouselAutoplay();
        }

        // 在 DOM 加载前恢复语言设置（避免中文闪现）
        const savedLocale = localStorage.getItem('zjt_locale') || 'zh-CN';
        document.documentElement.lang = savedLocale === 'en' ? 'en' : 'zh-CN';

        document.addEventListener('DOMContentLoaded', async () => {
            // i18n 初始化
            try {
                // 初始化所有所需的命名空间
                await ZJTi18n.init(['common', 'index']);

                // 确保当前语言设置正确（从 localStorage 读取）
                const currentLocale = ZJTi18n.getLocale();
                if (currentLocale !== savedLocale) {
                    await ZJTi18n.setLocale(savedLocale, ['common', 'index']);
                }

                // 扫描并翻译所有 data-i18n 属性的 DOM 元素
                if (window.ZJTi18nDOM && window.ZJTi18nDOM.scanDOM) {
                    window.ZJTi18nDOM.scanDOM(document);
                }
                // 初始化语言切换器
                initLanguageSwitcher();
            } catch (e) {
                console.warn('[i18n] 初始化失败，使用中文:', e);
            }

            // 意见反馈入口 / 二维码（不阻塞后续主流程）
            applyFeedbackVisibilityFromServer().catch(() => {});

            // 检查是否缺少 user_id 参数
            if (!USER_ID || USER_ID === 'null' || USER_ID === '') {
                alert('⚠️ ' + (window.t ? window.t('alert_missing_params') : '缺少关键参数\n\n请回到工作流列表后，再进入。'));
                const baseUrl = window.location.origin;
                const redirectUrl = baseUrl + '/video-workflow-list';
                window.location.href = redirectUrl;
                return;
            }

            configureMarked();
            // 获取版本信息，用于社区版功能标注
            try {
                const editionResp = await fetch('/api/edition');
                const editionResult = await editionResp.json();
                if (editionResult.code === 0 && editionResult.data) {
                    isCommunityEdition = editionResult.data.mode === 'community';
                }
            } catch (e) {
                isCommunityEdition = true;
            }
            await loadVendors();
            await loadAvailableModels();
            await loadDriverStatus();
            await loadTextToImageModels();
            await loadComputingPower();
            await loadUserWorlds();
            bindWorldSearchEvents();
            // 加载任务配置（用于多角度图生成）
            if (window.TaskConfig) {
                await window.TaskConfig.load();
                // 检测 runninghub 配置状态，禁用/启用生成多角度图按钮
                checkRunningHubForMultiAngle();
            }

            renderCarousel();
            initCarousel();
            restoreInterventionLevel();
            initCustomModelSelectMenus();
            initImportDropZone();

            // 设置发送按钮事件监听器
            const sendButton = document.getElementById('send-btn');
            if (sendButton) {
                sendButton.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('Send button clicked, disabled:', this.disabled);
                    if (!this.disabled) {
                        sendMessage();
                    }
                });
            }

            // 设置 Debug 测试按钮事件监听器
            const debugTestBtn = document.getElementById('debug-test-btn');
            if (debugTestBtn) {
                debugTestBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    testAskUserFeature();
                });
            }

            // 设置输入框事件监听器
            const messageInput = document.getElementById('message-input');
            if (messageInput) {
                messageInput.addEventListener('input', function() {
                    this.style.height = 'auto';
                    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
                    syncSendBtnLayout();
                });

                messageInput.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                    }
                });
                // 首屏：单行居中
                syncSendBtnLayout();
            }
            
            // 检查是否缺少world_id
            if (!WORLD_ID || WORLD_ID === 'null' || WORLD_ID === '') {
                // 缺少world_id，自动弹出世界选择侧边栏
                showWorldSelectionPrompt();
                return; // 不继续初始化其他功能
            }
            
            // 核心初始化流程：加载世界名称、初始化会话、加载文件
            // 使用 try-catch 防止快速刷新时 fetch 被取消导致异常中断后续流程
            try {
                await loadCurrentWorldName();
                await initOrReuseSession();
                await loadFiles('worlds');
            } catch (error) {
                // 快速刷新时 fetch 会被页面导航取消，抛出 TypeError: Failed to fetch
                // 这是正常行为，不需要创建新会话或做其他处理
                if (error.name === 'AbortError' || (error.message && error.message.includes('Failed to fetch'))) {
                    console.log('[初始化] 页面导航取消了正在进行的请求，忽略此次初始化');
                } else {
                    console.error('[初始化] 核心初始化流程出错:', error);
                }
                return; // 如果初始化被中断，不继续执行后续UI更新
            }

            // 有世界时显示需求选择界面
            const requirementSelector = document.getElementById('requirement-selector');
            if (requirementSelector) {
                requirementSelector.style.display = 'block';
            }
            // 更新欢迎提示文字
            const welcomeHint = document.querySelector('.welcome-hint');
            if (welcomeHint) {
                welcomeHint.textContent = window.t ? window.t('welcome_hint_select') : '选择下方需求或直接输入，开始您的创作之旅！';
            }
            if (messageInput) messageInput.focus();
        });

        async function loadAndDisplayHistory(sessionId) {
            try {
                const response = await fetch(`/api/session/${sessionId}/history`, {
                    headers: {
                        'Authorization': `Bearer ${AUTH_TOKEN}`
                    }
                });
                
                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                if (data.success && data.history && data.history.length > 0) {
                    console.log(`加载历史消息: ${data.history.length} 条`);
                    
                    // 显示历史消息
                    data.history.forEach(msg => {
                        // 不显示系统提示
                        if (msg.role === 'system') {
                            return;
                        }

                        // 不显示 context_summary 消息（已在后端排除，此处双重保障）
                        if (msg.message_type === 'context_summary') {
                            return;
                        }

                        // 特殊处理 tool 消息：只显示 ask_user 的用户回答
                        if (msg.role === 'tool') {
                            const content = msg.content;
                            if (typeof content === 'object') {
                                // 检查是否是 ask_user 工具的结果
                                if (content.name === 'ask_user' && content.content) {
                                    // 尝试解析 content
                                    let result;
                                    try {
                                        result = typeof content.content === 'string'
                                            ? JSON.parse(content.content)
                                            : content.content;
                                    } catch (e) {
                                        result = content.content;
                                    }

                                    // 提取用户的回答
                                    let userAnswer = null;
                                    if (typeof result === 'object') {
                                        userAnswer = result.user_input || result.success;
                                    } else if (typeof result === 'string') {
                                        userAnswer = result;
                                    }

                                    if (userAnswer) {
                                        // 显示用户的回答
                                        addMessage('user', `我的回答：${userAnswer}`);
                                    }
                                }
                            }
                            return;
                        }

                        // 显示历史中的 verification 问题（样式与对话中保持一致）
                        if (msg.role === 'verification') {
                            const vContent = msg.content;
                            const desc = vContent.description || '';
                            const options = vContent.options || [];

                            let vHtml = `<div class="verification-question history-mode">`;
                            vHtml += `<strong class="verification-title">${escapeHtml(vContent.title || (window.t ? window.t('ai_question') : 'AI 提问'))}</strong>`;
                            vHtml += `<p class="verification-description">${escapeHtml(desc)}</p>`;
                            if (options.length > 0) {
                                vHtml += `<div class="verification-options">`;
                                options.forEach(opt => {
                                    vHtml += `<span class="option-btn">${escapeHtml(opt)}</span>`;
                                });
                                vHtml += `</div>`;
                            }
                            vHtml += `</div>`;
                            addMessage('assistant', vHtml);
                            return;
                        }

                        // 处理其他角色的 content
                        let content = msg.content;
                        let hasToolCalls = false;

                        if (typeof content === 'object') {
                            // 检查是否包含函数调用
                            if (content.tool_calls && Array.isArray(content.tool_calls)) {
                                hasToolCalls = true;
                                // 检查是否有 ask_user 调用
                                const hasAskUser = content.tool_calls.some(tc => tc.function?.name === 'ask_user');

                                // 如果只有函数调用，没有文本内容，显示图标
                                if (!content.text && content.tool_calls.length > 0) {
                                    const icon = hasAskUser ? '❓' : '🔧';
                                    const desc = hasAskUser ? '提出了一个问题' : `执行了 ${content.tool_calls.length} 个操作`;
                                    content = `<span class="tool-call-icon" title="调用了 ${content.tool_calls.length} 个工具">${icon} ${desc}</span>`;
                                } else if (content.text) {
                                    // 如果既有文本又有函数调用，显示文本 + 图标
                                    const icon = hasAskUser ? '❓' : '🔧';
                                    const desc = hasAskUser ? '提出了一个问题' : `执行了 ${content.tool_calls.length} 个操作`;
                                    content = content.text + `\n\n<span class="tool-call-icon" title="调用了 ${content.tool_calls.length} 个工具">${icon} ${desc}</span>`;
                                }
                            } else if (Array.isArray(content)) {
                                // 如果是数组，提取所有 text 类型的内容，过滤掉 tool_use
                                const textItems = content.filter(item => item.type === 'text');
                                if (textItems.length === 0) {
                                    // 如果没有文本内容（只有函数调用），跳过这条消息
                                    return;
                                }
                                content = textItems.map(item => item.text).join('\n');
                            } else if (content.text) {
                                // 如果是对象且有 text 属性
                                content = content.text;
                            } else {
                                // 尝试转为字符串
                                content = String(content);
                            }
                        }

                        // 如果 content 为空或只有空白字符，跳过
                        if (!content || !content.trim()) {
                            return;
                        }

                        addMessage(msg.role, content);
                    });
                    
                    updateStatus(window.t ? window.t('status_loaded_history', {count: data.history.length}) : `已加载 ${data.history.length} 条历史消息`);
                } else {
                    console.log('没有历史消息');
                }

                // 历史加载完成后确保输入区可用（发送按钮始终可点；仅未选世界时保持禁用）
                restoreInputControlsAfterHistory();
            } catch (error) {
                console.error('加载历史消息失败:', error);
                restoreInputControlsAfterHistory();
            }
        }

        /**
         * 按输入框高度切换发送按钮垂直布局：
         * - 单行：CSS top:50% 居中
         * - 多行（is-expanded）：贴右下
         * 阈值略大于单行自然高度，避免亚像素抖动。
         */
        function syncSendBtnLayout() {
            const input = document.getElementById('message-input');
            const container = input && input.closest
                ? input.closest('.input-container')
                : document.querySelector('.input-container');
            if (!input || !container) return;
            const expanded = input.offsetHeight > 56;
            container.classList.toggle('is-expanded', expanded);
        }

        /**
         * 历史消息渲染后恢复底部输入/发送控件。
         * 宽内容曾会把 flex 布局撑出视口导致发送按钮被裁切；同时避免 isProcessing 残留导致按钮一直 disabled。
         * 窄屏兜底：确保输入条滚入视口，避免加载长历史后发送按钮“看不见”。
         */
        function restoreInputControlsAfterHistory() {
            if (!window.WORLD_ID) return;
            const input = document.getElementById('message-input');
            const sendBtn = document.getElementById('send-btn');
            if (input) {
                input.disabled = false;
            }
            // 仅当当前没有进行中的任务/验证时恢复发送按钮，避免打断流式回复
            if (sendBtn && !isProcessing && !pendingVerificationId) {
                sendBtn.disabled = false;
                sendBtn.classList.remove('sending');
            }
            syncSendBtnLayout();
            // 窄屏：输入区应始终在聊天列底部；极端布局下再 scrollIntoView 兜底
            const inputSection = document.querySelector('.input-section');
            if (inputSection && typeof inputSection.scrollIntoView === 'function') {
                try {
                    inputSection.scrollIntoView({ block: 'end', behavior: 'instant' });
                } catch (_) {
                    // Safari 旧版不支持 behavior:'instant'
                    inputSection.scrollIntoView(false);
                }
            }
        }

        async function initOrReuseSession() {
            try {
                // 先尝试获取当前用户的最新活跃会话
                const response = await fetch(`/api/sessions?user_id=${USER_ID}&world_id=${WORLD_ID}&session_type=1&limit=1`, {
                    headers: {
                        'Authorization': `Bearer ${AUTH_TOKEN}`
                    }
                });
                
                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                if (data.success && data.sessions && data.sessions.length > 0) {
                    // 找到活跃会话，复用它
                    const latestSession = data.sessions[0];
                    sessionId = latestSession.session_id;
                    
                    const sessionIdElement = document.getElementById('session-id');
                    if (sessionIdElement) {
                        sessionIdElement.textContent = sessionId.substring(0, 8) + '...';
                    }
                    
                    console.log(`复用已有会话: ${sessionId}`);
                    updateStatus(window.t ? window.t('status_orchestrator_ready_reuse') : '剧本编排系统已就绪（复用已有会话）');
                    
                    // 加载并显示历史消息
                    await loadAndDisplayHistory(sessionId);
                    
                    // 会话复用成功后，自动设置生图模型到后端
                    await autoSetTextToImageModel();
                } else {
                    // 没有活跃会话，创建新的
                    console.log('没有找到活跃会话，创建新会话');
                    await createSession();
                }
            } catch (error) {
                // 快速刷新时 fetch 会被页面导航取消，抛出 TypeError: Failed to fetch
                // 这种情况下不应该创建新会话，直接向上抛出让外层 try-catch 处理
                if (error.name === 'AbortError' || (error.message && error.message.includes('Failed to fetch'))) {
                    console.log('[初始化] 会话初始化请求被页面导航取消，跳过');
                    return; // 不创建新会话
                }
                console.error('初始化会话失败:', error);
                // 只有非网络中断的错误才尝试创建新会话
                await createSession();
            }
        }

        async function createSession(systemPrompt = null) {
            try {
                // 使用全局变量 AUTH_TOKEN
                const selector = document.getElementById('model-selector');
                const selectedModel = selector ? selector.value : null;
                
                const response = await fetch('/api/session/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        system_prompt: systemPrompt,
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        auth_token: AUTH_TOKEN,
                        session_type: 1
                    })
                });

                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                if (data.success) {
                    sessionId = data.session_id;
                    const sessionIdElement = document.getElementById('session-id');
                    if (sessionIdElement) {
                        sessionIdElement.textContent = sessionId.substring(0, 8) + '...';
                    }

                    // 显示差异文件警告
                    const hasSkippedFiles = data.skipped_files && data.skipped_files.length > 0;
                    const hasLocalOnlyFiles = data.local_only_files && data.local_only_files.length > 0;
                    
                    if (hasSkippedFiles || hasLocalOnlyFiles) {
                        let warningMsg = window.t ? window.t('alert_file_diff_warning') : '⚠️ 检测到本地文件与数据库存在差异：\n\n';

                        if (hasSkippedFiles) {
                            const fileList = data.skipped_files.join('\n  • ');
                            warningMsg += window.t ? window.t('alert_file_diff_skipped', { files: fileList }) : `📝 内容差异文件（本地修改已保留）：\n  • ${fileList}\n\n`;
                        }

                        if (hasLocalOnlyFiles) {
                            const localOnlyList = data.local_only_files.join('\n  • ');
                            warningMsg += window.t ? window.t('alert_file_diff_local_only', { files: localOnlyList }) : `📁 本地独有文件（数据库中不存在）：\n  • ${localOnlyList}\n\n`;
                        }

                        warningMsg += window.t ? window.t('alert_file_diff_hint') : '💡 提示：这些文件的本地内容已保留，不会被数据库覆盖。如需同步，请使用"提交"按钮。';

                        alert(warningMsg);
                        updateStatus(window.t ? window.t('status_orchestrator_ready_local') : '剧本编排系统已就绪（检测到未提交的本地修改）');
                    } else {
                        updateStatus(window.t ? window.t('status_orchestrator_ready') : '剧本编排系统已就绪');
                    }
                    // 会话创建成功后，自动设置生图模型到后端
                    await autoSetTextToImageModel();
                } else {
                    showError((window.t ? window.t('error_create_session_failed', {error: data.error}) : '创建会话失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_create_session_failed', {error: error.message}) : '创建会话失败: ' + error.message));
            }
        }

        async function newSession() {
            const confirmMessage = window.t ? window.t('confirm_reset_session') : '⚠️ 确定要删除暂存并重置会话吗？\n\n这将会：\n1. 删除本地所有未提交到数据库的文件\n2. 从数据库同步最新数据到本地\n3. 清空当前对话历史\n\n⚠️ 请确保已将重要内容提交到数据库！\n\n是否继续？';
            
            if (confirm(confirmMessage)) {
                try {
                    updateStatus(window.t ? window.t('status_syncing_from_db') : '正在从数据库同步文件...');
                    const response = await fetch('/api/sync-files', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id: USER_ID, world_id: WORLD_ID })
                    });
                    
                    const data = await response.json();
                    if (!data.success) {
                        showError((window.t ? window.t('error_sync_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '同步失败: ' + (data.error || '未知错误')));
                        updateStatus(window.t ? window.t('status_ready') : '就绪');
                        return;
                    }
                    
                    const _t = window.t || (k => k);
                    document.getElementById('chat-messages').innerHTML = `
                        <div class="welcome-card">
                            <div class="welcome-icon">🎬</div>
                            <h2 class="welcome-title">${_t('welcome_title')}</h2>
                            <p class="welcome-desc">${_t('welcome_desc')}</p>
                            <div class="agent-carousel" id="agent-carousel">
                                <div class="carousel-track" id="carousel-track"></div>
                                <div class="carousel-controls">
                                    <button class="carousel-btn prev" id="carousel-prev" aria-label="${_t('prev_page')}"><span>←</span></button>
                                    <button class="carousel-btn next" id="carousel-next" aria-label="${_t('next_page')}"><span>→</span></button>
                                </div>
                                <div class="carousel-indicators" id="carousel-indicators">
                                    ${Array.from({length: 9}, (_, idx) => `<button class="indicator${idx === 0 ? ' active' : ''}" data-target="${idx}" aria-label="${_t('page_indicator', {page: idx + 1})}"></button>`).join('')}
                                </div>
                            </div>
                            <p class="welcome-hint">${_t('welcome_hint')}</p>
                        </div>
                    `;
                    renderCarousel();
                    
                    
                    await createSession();
                    initCarousel();
                    await loadFiles(currentFileType);
                    updateStatus((window.t ? window.t('status_synced_reset') : '已从数据库同步文件，会话已重置'));
                } catch (error) {
                    showError((window.t ? window.t('error_operation_failed', {error: error.message}) : '操作失败: ' + error.message));
                    updateStatus(window.t ? window.t('status_ready') : '就绪');
                }
            }
        }

        async function refreshFiles() {
            try {
                updateStatus(window.t ? window.t('status_refreshing') : '正在刷新文件...');
                await loadFiles(currentFileType);
                updateStatus(window.t ? window.t('status_files_refreshed') : '文件已刷新');
            } catch (error) {
                showError((window.t ? window.t('error_refresh_files_failed', {error: error.message}) : '刷新文件失败: ' + error.message));
            }
        }

        async function refreshPage() {
            if (confirm(window.t ? window.t('confirm_new_session') : '⚠️ 确定要新建会话吗？\n\n这将会刷新页面并清空当前对话历史。\n\n本地文件不会被删除，但对话上下文会丢失。\n\n是否继续？')) {
                try {
                    // 如果有当前会话，先清空会话历史
                    if (sessionId) {
                        updateStatus(window.t ? window.t('status_clearing_history') : '正在清空对话历史...');
                        const response = await fetch(`/api/session/${sessionId}/clear`, {
                            method: 'POST',
                            headers: {
                                'Authorization': `Bearer ${AUTH_TOKEN}`
                            }
                        });
                        
                        const data = await response.json();
                        if (data.success) {
                            console.log('会话历史已清空');
                        } else {
                            console.warn('清空会话历史失败:', data.error);
                        }
                    }
                } catch (error) {
                    console.error('清空会话历史失败:', error);
                }
                
                // 刷新页面
                window.location.reload();
            }
        }

        async function compressHistory() {
            if (!sessionId) {
                showError(window.t ? window.t('error_no_active_session') : '没有活跃的会话，无法压缩历史');
                return;
            }

            if (!confirm(window.t ? window.t('confirm_compress_history') : '🗜️ 确定要压缩对话历史吗？\n\n这将会：\n• 保留关键决策和重要信息\n• 删除冗余对话内容\n• 减少上下文长度以节省 token\n\n压缩后无法恢复原始历史，是否继续？')) {
                return;
            }

            try {
                updateStatus(window.t ? window.t('status_compressing_history') : '正在压缩对话历史...');
                const response = await fetch(`/api/session/${sessionId}/compress`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${AUTH_TOKEN}`
                    }
                });

                const data = await response.json();
                if (data.success) {
                    showSuccess(window.t ? window.t('success_history_compressed_detail', {before: data.before_count, after: data.after_count}) : `✓ 对话历史已压缩：${data.before_count} → ${data.after_count} 条消息`);
                    updateStatus(window.t ? window.t('status_history_compressed', {count: data.reduced}) : `对话历史已压缩，减少 ${data.reduced} 条消息`);

                    // 添加系统消息到聊天窗口显示压缩结果
                    addSystemMessage(`对话历史已压缩`,
                        `原始消息：${data.before_count} 条\n` +
                        `压缩后：${data.after_count} 条\n` +
                        `摘要：${data.summary || '无'}`,
                        'info'
                    );
                } else {
                    showError((window.t ? window.t('error_compress_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '压缩失败: ' + (data.error || '未知错误')));
                    updateStatus(window.t ? window.t('status_compress_failed') : '压缩失败');
                }
            } catch (error) {
                console.error('压缩对话历史失败:', error);
                showError((window.t ? window.t('error_compress_failed', {error: error.message}) : '压缩失败: ' + error.message));
                updateStatus(window.t ? window.t('status_compress_failed') : '压缩失败');
            }
        }

        // 添加系统消息到聊天窗口
        function addSystemMessage(title, content, type = 'info') {
            const chatMessages = document.getElementById('chat-messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `system-message ${type}`;
            messageDiv.innerHTML = `
                <div class="system-message-header">
                    <span class="system-message-icon">${type === 'info' ? 'ℹ️' : '⚠️'}</span>
                    <span class="system-message-title">${escapeHtml(title)}</span>
                </div>
                <div class="system-message-content">${escapeHtml(content).replace(/\n/g, '<br>')}</div>
            `;
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        // 提交状态标志，防止重复提交
        let isSubmitting = false;

        async function submitToDatabase() {
            // 防止重复提交
            if (isSubmitting) {
                console.log('[提交] 已有提交任务进行中，跳过');
                return;
            }

            // 检查是否选择了世界
            if (!WORLD_ID) {
                showError(window.t ? window.t('error_select_world_first') : '请先选择世界');
                return;
            }

            // 设置提交状态并禁用按钮
            isSubmitting = true;
            const submitBtn = document.querySelector('.header-action-btn.primary');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.classList.add('disabled');
            }

            try {
                updateStatus(window.t ? window.t('status_submitting_data') : '正在提交数据...');
                const response = await fetch('/api/submit-to-database', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: USER_ID, world_id: WORLD_ID })
                });

                const data = await response.json();
                if (data.success) {
                    showSuccess(window.t ? window.t('success_submit_detail', {total: data.total}) : `✓ 提交成功！共保存 ${data.total} 个文件到数据库`);
                    updateStatus(window.t ? window.t('status_data_submitted') : '数据已提交到数据库');
                } else {
                    showError((window.t ? window.t('error_submit_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '提交失败: ' + (data.error || '未知错误')));
                    updateStatus(window.t ? window.t('status_submit_failed') : '提交失败');
                }
            } catch (error) {
                showError((window.t ? window.t('error_submit_failed', {error: error.message}) : '提交失败: ' + error.message));
                updateStatus(window.t ? window.t('status_submit_failed') : '提交失败');
            } finally {
                // 恢复提交状态并启用按钮
                isSubmitting = false;
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('disabled');
                }
            }
        }

        // ========== 自动提交功能 ==========
        let autoSubmitTimer = null;
        let countdownInterval = null;
        let nextSubmitTime = null;

        // ========== 自动刷新暂存文件功能 ==========
        let autoRefreshTimer = null;
        const AUTO_REFRESH_MIN_INTERVAL = 67000; // 67秒
        const AUTO_REFRESH_MAX_INTERVAL = 83000; // 83秒

        // ========== 算力定时刷新功能 ==========
        let computingPowerRefreshTimer = null;
        const COMPUTING_POWER_REFRESH_MIN_INTERVAL = 30000; // 30秒
        const COMPUTING_POWER_REFRESH_MAX_INTERVAL = 45000; // 45秒

        function toggleAutoSubmit() {
            const switchEl = document.getElementById('auto-submit-switch');
            if (switchEl.checked) {
                startAutoSubmit();
            } else {
                stopAutoSubmit();
            }
            saveAutoSubmitSettings();
        }

        function startAutoSubmit() {
            scheduleNextSubmit();
        }

        function stopAutoSubmit() {
            if (autoSubmitTimer) {
                clearTimeout(autoSubmitTimer);
                autoSubmitTimer = null;
            }
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
            nextSubmitTime = null;
            updateCountdownDisplay();
        }

        function scheduleNextSubmit() {
            // 先清除已有的定时器，避免重复
            if (autoSubmitTimer) {
                clearTimeout(autoSubmitTimer);
                autoSubmitTimer = null;
            }

            const baseInterval = 60 * 1000; // 固定1分钟
            const randomDelay = Math.floor(Math.random() * 30000); // 0-30秒随机延迟

            const totalDelay = baseInterval + randomDelay;
            nextSubmitTime = Date.now() + totalDelay;

            console.log(`[自动提交] 已调度，${Math.round(totalDelay/1000)}秒后执行`);

            autoSubmitTimer = setTimeout(async () => {
                const switchEl = document.getElementById('auto-submit-switch');
                try {
                    console.log('[自动提交] 开始执行提交...');
                    await submitToDatabase();
                    console.log('[自动提交] 提交完成');
                } catch (error) {
                    console.error('[自动提交] 提交出错:', error);
                } finally {
                    // 无论成功失败，只要开关仍然开启，继续调度下一次
                    if (switchEl && switchEl.checked) {
                        scheduleNextSubmit();
                    }
                }
            }, totalDelay);

            updateCountdownDisplay();
            startCountdownUpdater();
        }

        function startCountdownUpdater() {
            if (countdownInterval) {
                clearInterval(countdownInterval);
            }
            countdownInterval = setInterval(updateCountdownDisplay, 1000);
        }

        function updateCountdownDisplay() {
            const countdownEl = document.getElementById('auto-submit-countdown');
            if (countdownEl) {
                countdownEl.style.display = 'none';
            }
        }

        function saveAutoSubmitSettings() {
            const switchEl = document.getElementById('auto-submit-switch');
            const enabled = switchEl.checked;
            
            // 使用cookie保存，设置1年有效期
            const expires = new Date();
            expires.setFullYear(expires.getFullYear() + 1);
            document.cookie = `autoSubmitEnabled=${enabled}; expires=${expires.toUTCString()}; path=/`;
            
            console.log(`[自动提交] 设置已保存: ${enabled}`);
        }

        function loadAutoSubmitSettings() {
            // 从cookie读取设置
            const cookies = document.cookie.split(';');
            let enabled = null;
            
            for (const cookie of cookies) {
                const [name, value] = cookie.trim().split('=');
                if (name === 'autoSubmitEnabled') {
                    enabled = value === 'true';
                    break;
                }
            }
            
            // 如果有保存的设置，恢复状态
            if (enabled !== null) {
                const switchEl = document.getElementById('auto-submit-switch');
                switchEl.checked = enabled;
                if (enabled) {
                    startAutoSubmit();
                }
                console.log(`[自动提交] 已恢复设置: ${enabled}`);
            }
            
            // 启动自动刷新暂存文件功能
            startAutoRefresh();
            // 启动算力定时刷新功能
            startComputingPowerRefresh();
        }

        function startAutoRefresh() {
            // 清除现有定时器
            if (autoRefreshTimer) {
                clearTimeout(autoRefreshTimer);
            }
            
            // 生成随机间隔时间 (67-83秒)
            const randomInterval = AUTO_REFRESH_MIN_INTERVAL + 
                Math.random() * (AUTO_REFRESH_MAX_INTERVAL - AUTO_REFRESH_MIN_INTERVAL);
            
            console.log(`[自动刷新] 已调度，${Math.round(randomInterval/1000)}秒后刷新暂存文件`);
            
            autoRefreshTimer = setTimeout(async () => {
                try {
                    console.log('[自动刷新] 开始刷新暂存文件...');
                    await refreshFiles();
                    console.log('[自动刷新] 暂存文件刷新完成');
                } catch (error) {
                    console.error('[自动刷新] 刷新暂存文件出错:', error);
                } finally {
                    // 无论成功失败，继续调度下一次刷新
                    startAutoRefresh();
                }
            }, randomInterval);
        }

        function stopAutoRefresh() {
            if (autoRefreshTimer) {
                clearTimeout(autoRefreshTimer);
                autoRefreshTimer = null;
                console.log('[自动刷新] 已停止');
            }
        }

        function startComputingPowerRefresh() {
            // 清除现有定时器
            if (computingPowerRefreshTimer) {
                clearTimeout(computingPowerRefreshTimer);
            }

            // 生成随机间隔时间 (30-45秒)
            const randomInterval = COMPUTING_POWER_REFRESH_MIN_INTERVAL +
                Math.random() * (COMPUTING_POWER_REFRESH_MAX_INTERVAL - COMPUTING_POWER_REFRESH_MIN_INTERVAL);

            console.log(`[算力刷新] 已调度，${Math.round(randomInterval/1000)}秒后刷新算力`);

            computingPowerRefreshTimer = setTimeout(async () => {
                try {
                    console.log('[算力刷新] 开始刷新算力...');
                    await loadComputingPower();
                    console.log('[算力刷新] 算力刷新完成');
                } catch (error) {
                    console.error('[算力刷新] 刷新算力出错:', error);
                } finally {
                    // 无论成功失败，继续调度下一次刷新
                    startComputingPowerRefresh();
                }
            }, randomInterval);
        }

        function stopComputingPowerRefresh() {
            if (computingPowerRefreshTimer) {
                clearTimeout(computingPowerRefreshTimer);
                computingPowerRefreshTimer = null;
                console.log('[算力刷新] 已停止');
            }
        }

        // 页面加载完成后恢复设置
        document.addEventListener('DOMContentLoaded', () => {
            setTimeout(loadAutoSubmitSettings, 500);
            
            // 添加页面卸载事件监听器，清理定时器
            window.addEventListener('beforeunload', () => {
                stopAutoRefresh();
                stopAutoSubmit();
            });
        });

        async function sendMessage(customMessage = null, isSystemMessage = false) {
            console.log('sendMessage called, isProcessing:', isProcessing, 'pendingVerificationId:', pendingVerificationId);

            // Disable send button immediately to prevent multiple clicks
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.classList.add('sending');
                console.log('Button disabled and sending class added');
            }

            if (!sessionId) {
                console.log('No sessionId, re-enabling button');
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.classList.remove('sending');
                }
                return;
            }

            // 如果有待处理的验证，优先走验证提交路由（不受 isProcessing 限制）
            if (pendingVerificationId) {
                let message;
                let fromInput = false;
                if (customMessage) {
                    message = customMessage;
                } else {
                    const input = document.getElementById('message-input');
                    message = input.value.trim();
                    if (!message) {
                        if (sendBtn) {
                            sendBtn.disabled = false;
                            sendBtn.classList.remove('sending');
                        }
                        return;
                    }
                    // 成功后再清空，避免提交失败时丢失草稿
                    fromInput = true;
                }
                // 保持 isProcessing = true，Expert 仍在处理中
                await submitVerificationAnswer(message, { fromInput });
                // 提交失败时恢复发送按钮，便于用户重试
                if (sendBtn && pendingVerificationId) {
                    sendBtn.disabled = false;
                    sendBtn.classList.remove('sending');
                }
                return;
            }

            if (isProcessing) {
                console.log('Already processing, re-enabling button');
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.classList.remove('sending');
                }
                return;
            }

            // 立即设置 isProcessing 为 true，防止重复调用
            isProcessing = true;
            console.log('isProcessing set to true');

            let message;
            if (customMessage) {
                message = customMessage;
            } else {
                const input = document.getElementById('message-input');
                message = input.value.trim();
                if (!message) {
                    // Re-enable button if no message
                    isProcessing = false;
                    sendBtn.disabled = false;
                    sendBtn.classList.remove('sending');
                    return;
                }
                input.value = '';
                input.style.height = 'auto';
                syncSendBtnLayout();
            }

            if (isSystemMessage) {
                addMessage('user', `🔄 ${message}`);
            } else {
                addMessage('user', message);
            }

            showTypingIndicator();
            updateStatus(window.t ? window.t('status_ai_thinking') : 'AI 思考中...');

            let timeoutId;
            let hasStartedReceiving = false;
            
            try {
                const controller = new AbortController();
                timeoutId = setTimeout(() => {
                    if (!hasStartedReceiving) {
                        controller.abort();
                        hideTypingIndicator();
                        showError(window.t ? window.t('error_timeout_retry') : '请求超时，请稍后重试。');
                    }
                }, 300000);
                
                // 使用全局变量 AUTH_TOKEN
                const selector = document.getElementById('model-selector');
                const selectedOption = selector?.options[selector.selectedIndex];
                const modelId = selectedOption?.dataset?.modelId;
                const vendorId = selectedOption?.dataset?.vendorId;

                if (!modelId) {
                    hideTypingIndicator();
                    showError(window.t ? window.t('error_model_unavailable') : '当前模型不可用，请重新加载模型列表');
                    isProcessing = false;
                    const sendBtn = document.getElementById('send-btn');
                    sendBtn.disabled = false;
                    sendBtn.classList.remove('sending');
                    return;
                }

                const taskResponse = await fetch(`/api/session/${sessionId}/task`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message,
                        auth_token: AUTH_TOKEN,
                        model: selector?.value || '',
                        model_id: modelId,
                        vendor_id: vendorId ? parseInt(vendorId) : 1,
                        language: localStorage.getItem('zjt_locale') || 'zh-CN',
                        ...getThinkingParams(),
                        intervention_level: getInterventionLevel()
                    }),
                    signal: controller.signal
                });

                const taskData = await taskResponse.json();
                
                if (!taskResponse.ok || !taskData.success) {
                    // 检查 token 是否过期
                    if (checkTokenExpired(taskData, taskResponse)) {
                        hideTypingIndicator();
                        isProcessing = false;
                        const sendBtn = document.getElementById('send-btn');
                        sendBtn.disabled = false;
                        sendBtn.classList.remove('sending');
                        return;
                    }
                    // 检查是否是算力不足错误
                    if (taskData.error === '算力不足' || taskData.message?.includes('算力不足')) {
                        alert('⚠️ ' + (window.t ? window.t('alert_insufficient_power') : '算力不足\n\n您的算力不足，请充值后继续使用。'));
                        hideTypingIndicator();
                        isProcessing = false;
                        const sendBtn = document.getElementById('send-btn');
                        if (sendBtn) { sendBtn.disabled = false; sendBtn.classList.remove('sending'); }
                        return;
                    }
                    // 其他错误
                    throw new Error(taskData.message || taskData.error || `HTTP ${taskResponse.status}: ${taskResponse.statusText}`);
                }
                const taskId = taskData.task_id;
                
                const eventSource = new EventSource(`/api/task/${taskId}/stream`);
                // 保持打字指示器，直到收到第一个消息
                const messageDiv = addMessage('assistant', '');
                let contentDiv = messageDiv.querySelector('.message-content');

                // 重置全局 fullText 变量
                fullText = '';
                let startTime = Date.now();

                eventSource.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        
                        if (!hasStartedReceiving) {
                            hasStartedReceiving = true;
                            hideTypingIndicator(); // 收到第一个消息时才移除打字指示器
                            const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                            updateStatus(window.t ? window.t('status_ai_replying', {elapsed: elapsed}) : `AI 正在回复... (等待了 ${elapsed}s)`);
                            clearTimeout(timeoutId);
                        }
                        
                        if (data.type === 'message') {
                            hideToolCalls(); // 收到文本消息时隐藏工具调用指示器
                            if (data.content) {
                                // 如果 verification 出现过，创建新 div（此时 verification 已在 DOM 中）
                                if (needsNewMessageDiv) {
                                    const newDiv = addMessage('assistant', '');
                                    contentDiv = newDiv.querySelector('.message-content');
                                    fullText = '';
                                    needsNewMessageDiv = false;
                                }
                                fullText += data.content + '\n\n';
                                contentDiv.innerHTML = renderMarkdown(fullText);
                                scrollToBottom();
                            }
                        } else if (data.type === 'progress') {
                            updateStatus(window.t ? window.t('status_executing', {step: data.step || ''}) : `执行中: ${data.step || ''}`);
                        } else if (data.type === 'tool_call') {
                            // 实时显示工具调用
                            if (data.tool_names && data.tool_names.length > 0) {
                                showToolCalls(data.tool_names);
                            }
                        } else if (data.type === 'context_compression') {
                            updateStatus(window.t ? window.t('status_context_compressed') : '上下文已自动压缩，继续回复中...');
                            console.log('[SSE] 上下文压缩事件:', data.reason);
                        } else if (data.type === 'done') {
                            eventSource.close();
                            hideTypingIndicator(); // 确保移除打字指示器
                            hideToolCalls(); // 确保移除工具调用指示器
                            updateStatus(window.t ? window.t('status_done') : '完成');
                            isProcessing = false;
                            pendingVerificationId = null;
                            pendingVerificationData = null;
                            const sendBtn = document.getElementById('send-btn');
                            sendBtn.disabled = false;
                            sendBtn.classList.remove('sending');
                            // 刷新算力显示
                            loadComputingPower();
                            // 自动刷新暂存文件列表
                            try {
                                refreshFiles().catch(err => console.error('刷新文件列表失败:', err));
                            } catch (err) {
                                console.error('调用refreshFiles失败:', err);
                            }
                        } else if (data.type === 'error') {
                            eventSource.close();
                            hideToolCalls(); // 确保移除工具调用指示器
                            showError((window.t ? window.t('error_task_execution', {error: data.error}) : '任务执行错误: ' + data.error));
                            isProcessing = false;
                            pendingVerificationId = null;
                            pendingVerificationData = null;
                            const sendBtn = document.getElementById('send-btn');
                            sendBtn.disabled = false;
                            sendBtn.classList.remove('sending');
                        } else if (data.type === 'human_verification_required') {
                            hideToolCalls(); // ask_user 工具调用完成，隐藏指示器
                            const verification = data.verification || {};
                            console.log('[SSE] Received human_verification_required:', verification);
                            handleHumanVerification(verification);
                        } else if (data.type === 'verification_timeout') {
                            console.log('[SSE] Received verification_timeout:', data);
                            if (pendingVerificationId === data.verification_id) {
                                pendingVerificationId = null;
                                pendingVerificationData = null;
                                const input = document.getElementById('message-input');
                                if (input) {
                                    input.placeholder = window.t ? window.t('placeholder_message') : '输入消息...';
                                }
                                // 超时后需允许用户重新发送，恢复发送按钮与处理状态
                                isProcessing = false;
                                const sendBtn = document.getElementById('send-btn');
                                if (sendBtn) {
                                    sendBtn.disabled = false;
                                    sendBtn.classList.remove('sending');
                                }
                            }
                            showError(window.t ? window.t('error_verification_timeout') : '验证已超时，请重新发送消息');
                        } else if (data.type === 'status') {
                            if (data.status) updateStatus(data.status);
                        }
                    } catch (e) {
                        console.error('[SSE-CLIENT] 解析失败:', e);
                    }
                };
                
                eventSource.onerror = (error) => {
                    // 关闭当前连接
                    eventSource.close();

                    // 检查后端任务状态，确认是否真的完成
                    checkTaskStatus(taskId).then(taskStatus => {
                        if (taskStatus === 'completed' || taskStatus === 'failed' || taskStatus === 'cancelled') {
                            // 任务已结束，安全重置状态
                            resetProcessingState();
                            if (!hasStartedReceiving) {
                                showError(window.t ? window.t('error_connection_failed') : '连接失败，请重试');
                            }
                        } else {
                            // 任务仍在运行，保持旋转状态并尝试重连
                            updateStatus(window.t ? window.t('status_reconnecting') : '连接中断，正在重连...');
                            setTimeout(() => {
                                reconnectSSE(taskId, messageDiv, contentDiv, startTime);
                            }, 2000);
                        }
                    }).catch(() => {
                        // If status lookup also fails, the backend is likely unavailable.
                        // End the local sending state so the user is not trapped in loading.
                        hideTypingIndicator();
                        hideToolCalls();
                        resetProcessingState();
                        updateStatus(window.t ? window.t('status_connection_lost') : '连接中断，请刷新页面后重试');
                        showError(window.t ? window.t('error_connection_lost') : '连接中断，无法确认任务状态，请刷新页面后重试');
                    });
                };

                updateStatus(window.t ? window.t('status_ready') : '就绪');
            } catch (error) {
                hideTypingIndicator();
                clearTimeout(timeoutId);
                if (error.name === 'AbortError') {
                    showError(window.t ? window.t('error_orchestrator_timeout') : '请求超时。剧本编排系统需要较长时间处理，请稍后重试。');
                } else {
                    showError((window.t ? window.t('error_send_message_failed', {error: error.message}) : '发送消息失败: ' + error.message));
                }
                // 只在 catch 中重置状态，不用 finally（因为 EventSource 是异步的）
                isProcessing = false;
                const sendBtn = document.getElementById('send-btn');
                sendBtn.disabled = false;
                sendBtn.classList.remove('sending');
            }
        }

        // 检查任务状态
        async function checkTaskStatus(taskId) {
            const response = await fetch(`/api/task/${taskId}/status`);
            if (!response.ok) throw new Error('Failed to check task status');
            const data = await response.json();
            return data.task?.status;
        }

        // 重置处理状态
        function resetProcessingState() {
            isProcessing = false;
            pendingVerificationId = null;
            pendingVerificationData = null;
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn) {
                sendBtn.disabled = false;
                sendBtn.classList.remove('sending');
            }
            updateStatus(window.t ? window.t('status_ready') : '就绪');
        }

        // 重连SSE（最多重连5次）
        function reconnectSSE(taskId, messageDiv, contentDiv, startTime, retryCount = 0) {
            const MAX_RETRIES = 5;

            if (retryCount >= MAX_RETRIES) {
                updateStatus(window.t ? window.t('status_reconnect_failed') : '重连失败，请刷新页面重试');
                resetProcessingState();
                showError(window.t ? window.t('error_connection_lost') : '连接中断，已尝试重连5次失败，请刷新页面');
                return null;
            }

            const newEventSource = new EventSource(`/api/task/${taskId}/stream`);
            let hasStartedReceiving = false;

            newEventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    if (!hasStartedReceiving) {
                        hasStartedReceiving = true;
                        hideTypingIndicator();
                        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                        updateStatus(window.t ? window.t('status_ai_replying', {elapsed: elapsed}) : `AI 正在回复... (等待了 ${elapsed}s)`);
                    }

                    if (data.type === 'message') {
                        hideToolCalls();
                        if (data.content) {
                            if (needsNewMessageDiv) {
                                const newDiv = addMessage('assistant', '');
                                contentDiv = newDiv.querySelector('.message-content');
                                fullText = '';
                                needsNewMessageDiv = false;
                            }
                            fullText += data.content + '\n\n';
                            contentDiv.innerHTML = renderMarkdown(fullText);
                            scrollToBottom();
                        }
                    } else if (data.type === 'progress') {
                        updateStatus(window.t ? window.t('status_executing', {step: data.step || ''}) : `执行中: ${data.step || ''}`);
                    } else if (data.type === 'tool_call') {
                        if (data.tool_names && data.tool_names.length > 0) {
                            showToolCalls(data.tool_names);
                        }
                    } else if (data.type === 'context_compression') {
                        updateStatus(window.t ? window.t('status_context_compressed') : '上下文已自动压缩，继续回复中...');
                    } else if (data.type === 'done') {
                        newEventSource.close();
                        hideToolCalls();
                        updateStatus(window.t ? window.t('status_done') : '完成');
                        resetProcessingState();
                        loadComputingPower();
                        try {
                            refreshFiles().catch(err => console.error('刷新文件列表失败:', err));
                        } catch (err) {
                            console.error('调用refreshFiles失败:', err);
                        }
                    } else if (data.type === 'error') {
                        newEventSource.close();
                        hideToolCalls();
                        showError((window.t ? window.t('error_task_execution', {error: data.error}) : '任务执行错误: ' + data.error));
                        resetProcessingState();
                    } else if (data.type === 'human_verification_required') {
                        hideToolCalls();
                        const verification = data.verification || {};
                        handleHumanVerification(verification);
                    } else if (data.type === 'verification_timeout') {
                        if (pendingVerificationId === data.verification_id) {
                            pendingVerificationId = null;
                            pendingVerificationData = null;
                            const input = document.getElementById('message-input');
                            if (input) {
                                input.placeholder = window.t ? window.t('placeholder_message') : '输入消息...';
                            }
                            // 超时后需允许用户重新发送，恢复发送按钮与处理状态
                            isProcessing = false;
                            const sendBtn = document.getElementById('send-btn');
                            if (sendBtn) {
                                sendBtn.disabled = false;
                                sendBtn.classList.remove('sending');
                            }
                        }
                        showError(window.t ? window.t('error_verification_timeout') : '验证已超时，请重新发送消息');
                    } else if (data.type === 'status') {
                        if (data.status) updateStatus(data.status);
                    }
                } catch (e) {
                    console.error('[SSE-CLIENT] 解析失败:', e);
                }
            };

            newEventSource.onerror = (error) => {
                newEventSource.close();
                checkTaskStatus(taskId).then(taskStatus => {
                    if (taskStatus === 'completed' || taskStatus === 'failed' || taskStatus === 'cancelled') {
                        resetProcessingState();
                    } else {
                        updateStatus(window.t ? window.t('status_reconnect_retry', {count: retryCount + 1, max: MAX_RETRIES}) : `重连失败，2秒后再次尝试 (${retryCount + 1}/${MAX_RETRIES})...`);
                        setTimeout(() => {
                            reconnectSSE(taskId, messageDiv, contentDiv, startTime, retryCount + 1);
                        }, 2000);
                    }
                }).catch(() => {
                    hideTypingIndicator();
                    hideToolCalls();
                    resetProcessingState();
                    updateStatus(window.t ? window.t('status_reconnect_final') : '重连失败，请刷新页面');
                    showError(window.t ? window.t('error_connection_lost') : '重连失败，无法确认任务状态，请刷新页面后重试');
                });
            };

            return newEventSource;
        }

        function configureMarked() {
            if (typeof marked !== 'undefined') {
                const renderer = new marked.Renderer();
                renderer.link = function(href, title, text) {
                    const url = href.href || '';
                    const safeUrl = /^(https?:\/\/|mailto:|\/)/.test(url) ? escapeHtml(url) : '#';
                    const safeTitle = title ? ` title="${escapeHtml(title)}"` : '';
                    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer"${safeTitle}>${escapeHtml(href.text || '')}</a>`;
                };
                renderer.image = function(href, title, text) {
                    const url = href.href || href || '';
                    const safeUrl = /^(https?:\/\/|\/|data:)/.test(url) ? escapeHtml(url) : '#';
                    const safeAlt = escapeHtml(text || '');
                    const safeTitle = title ? ` title="${escapeHtml(title)}"` : '';
                    return `<img src="${safeUrl}" alt="${safeAlt}"${safeTitle}>`;
                };

                marked.setOptions({
                    renderer: renderer,
                    highlight: function(code, lang) {
                        if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                            try {
                                return hljs.highlight(code, { language: lang }).value;
                            } catch (err) {}
                        }
                        // 确保代码被正确转义，防止HTML标签破坏页面结构
                        return code.replace(/&/g, '&amp;')
                                   .replace(/</g, '&lt;')
                                   .replace(/>/g, '&gt;')
                                   .replace(/"/g, '&quot;')
                                   .replace(/'/g, '&#39;');
                    },
                    breaks: true,
                    gfm: true
                });
            }
        }

        function sanitizeHtml(html) {
            // 移除危险标签及其内容
            var result = html.replace(/<(script|iframe|object|embed|form|style)[^>]*>[\s\S]*?<\/\1>/gi, '');
            result = result.replace(/<(script|iframe|object|embed|form|style)[^>]*\/?\s*>/gi, '');
            // 移除 on* 事件处理器属性
            result = result.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
            // 移除 javascript: URL（在 href/src/action 中）
            result = result.replace(/(href|src|action)\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')/gi, '$1="#"');
            return result;
        }

        function renderMarkdown(content) {
            if (typeof marked !== 'undefined') {
                try {
                    return sanitizeHtml(marked.parse(content));
                } catch (error) {
                    return escapeHtml(content);
                }
            }
            return escapeHtml(content);
        }

        function addMessage(role, content) {
            const messagesDiv = document.getElementById('chat-messages');
            const welcome = messagesDiv.querySelector('.welcome-card');
            if (welcome) {
                stopCarouselAutoplay();
                welcome.remove();
            }

            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}-message`;
            
            let renderedContent;
            if (role === 'assistant') {
                renderedContent = renderMarkdown(content);
            } else {
                renderedContent = escapeHtml(content);
            }
            
            messageDiv.innerHTML = `<div class="message-content">${renderedContent}</div>`;
            messagesDiv.appendChild(messageDiv);
            scrollToBottom();
            return messageDiv;
        }

        function showTypingIndicator() {
            const messagesDiv = document.getElementById('chat-messages');
            const indicator = document.createElement('div');
            indicator.className = 'typing-indicator';
            indicator.id = 'typing-indicator';
            indicator.innerHTML = `
                <div class="typing-dots">
                    <span></span><span></span><span></span>
                </div>
                <span class="typing-text">剧本编排中...</span>
            `;
            messagesDiv.appendChild(indicator);
            scrollToBottom();
        }

        function hideTypingIndicator() {
            const indicator = document.getElementById('typing-indicator');
            if (indicator) indicator.remove();
        }

        // ===== 工具调用实时显示 =====
        const TOOL_NAME_MAP = {
            'call_agent': '🤖 调用专家',
            'ask_user': '❓ 向用户提问',
            'load_sop': '📋 加载流程',
            'write_file': '📝 写入文件',
            'read_file': '📖 读取文件',
            'list_files': '📂 列出文件',
            'generate_text_to_image': '🎨 生成图片',
            'generate_text_to_video': '🎬 生成视频',
            'image_to_video': '🎬 图生视频',
            'edit_image': '✏️ 编辑图片',
            'fetch_image_as_base64': '🖼️ 获取图片',
            'submit_video_project': '📤 提交视频任务',
            'search_web': '🔍 搜索网络',
        };

        function getToolDisplayName(toolName) {
            return TOOL_NAME_MAP[toolName] || `🔧 ${toolName}`;
        }

        function showToolCalls(toolNames) {
            const messagesDiv = document.getElementById('chat-messages');
            // 移除已有的工具调用指示器
            const existing = document.getElementById('tool-call-indicator');
            if (existing) existing.remove();

            const indicator = document.createElement('div');
            indicator.className = 'tool-call-indicator';
            indicator.id = 'tool-call-indicator';

            let html = '';
            for (const name of toolNames) {
                html += `<div class="tool-call-item">
                    <div class="tool-spinner"></div>
                    <span class="tool-name">${escapeHtml(getToolDisplayName(name))}</span>
                </div>`;
            }
            indicator.innerHTML = html;
            messagesDiv.appendChild(indicator);
            scrollToBottom();
        }

        function hideToolCalls() {
            const indicator = document.getElementById('tool-call-indicator');
            if (indicator) {
                indicator.classList.add('fade-out');
                setTimeout(() => indicator.remove(), 500);
            }
        }

        function scrollToBottom() {
            const messagesDiv = document.getElementById('chat-messages');
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function updateStatus(text) {
            const statusElement = document.getElementById('status-text');
            if (statusElement) {
                statusElement.textContent = text;
            }
        }

        function handleHumanVerification(verification) {
            // 隐藏 typing indicator
            hideTypingIndicator();

            // 标记：后续 message 事件需要创建新 div（延迟到 message 到达时创建，确保在 verification 之后）
            needsNewMessageDiv = true;

            // 设置待处理验证信息
            pendingVerificationId = verification.verification_id;
            pendingVerificationData = verification;

            // 显示验证问题
            const messageDiv = addMessage('assistant', '');
            const contentDiv = messageDiv.querySelector('.message-content');

            // 构造 HTML
            let html = `<div class="verification-question">`;
            html += `<strong class="verification-title">${escapeHtml(verification.title)}</strong>`;
            html += `<p class="verification-description">${escapeHtml(verification.description)}</p>`;

            // 如果有选项，显示选择按钮
            if (verification.options && verification.options.length > 0) {
                html += `<div class="verification-options">`;
                verification.options.forEach((option, index) => {
                    const escapedOption = escapeHtml(option);
                    html += `<button class="option-btn" data-option-index="${index}">`;
                    html += `${escapedOption}</button>`;
                });
                // 添加"其他"按钮
                html += `<button class="option-btn option-other-btn" data-option-other="true">`;
                html += `${window.t ? window.t('btn_other') : '其他'}</button>`;
                html += `</div>`;
            }

            html += `</div>`;

            contentDiv.innerHTML = html;

            // 为选项按钮添加事件监听器
            const optionBtns = contentDiv.querySelectorAll('.option-btn');
            const input = document.getElementById('message-input');
            const sendBtn = document.getElementById('send-btn');

            optionBtns.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const isOther = e.target.dataset.optionOther === 'true';

                    if (isOther) {
                        // 点击"其他"按钮，焦点转移到下方的消息输入框
                        input.placeholder = window.t ? window.t('placeholder_custom_answer') : '请输入您的自定义答案...';
                        input.focus();
                        // 等待自定义输入时保持发送按钮可用
                        if (sendBtn) {
                            sendBtn.disabled = false;
                            sendBtn.classList.remove('sending');
                        }
                        updateStatus('💬 ' + (window.t ? window.t('status_custom_answer') : '请在下方输入框中输入您的自定义答案'));
                        console.log('[VERIFICATION] 用户选择"其他"，等待自定义输入');
                    } else {
                        // 点击预设选项，直接提交（无需用户再输入）
                        // fromInput=false：不清理输入框草稿
                        const index = e.target.dataset.optionIndex;
                        const option = verification.options[index];
                        if (option) {
                            console.log('[VERIFICATION] 用户选择选项:', option);
                            // 提交中禁用按钮，避免重复点击
                            if (sendBtn) {
                                sendBtn.disabled = true;
                                sendBtn.classList.add('sending');
                            }
                            submitVerificationAnswer(option, { fromInput: false }).finally(() => {
                                // 失败仍 pending 时 submitVerificationAnswer 外层/调用方会恢复；
                                // 成功则保持 disabled，等待 SSE 继续；失败由下方 pending 恢复兜底
                                if (sendBtn && pendingVerificationId) {
                                    sendBtn.disabled = false;
                                    sendBtn.classList.remove('sending');
                                }
                            });
                        }
                    }
                });
            });

            // 启用输入框与发送按钮：原始 sendMessage 在发起任务时会把按钮置为 disabled+sending，
            // ask_user 出现后若不恢复，按钮会一直半透明，选中输入框后看起来像“消失”
            if (input) {
                input.disabled = false;
                input.placeholder = verification.options && verification.options.length > 0
                    ? (window.t ? window.t('placeholder_select_or_custom') : '点击上方选项或选择"其他"输入自定义答案')
                    : (window.t ? window.t('placeholder_enter_answer') : '请输入您的回答...');
            }
            if (sendBtn) {
                sendBtn.disabled = false;
                sendBtn.classList.remove('sending');
            }

            updateStatus(window.t ? window.t('status_waiting_answer') : '等待您的回答...');
        }

        /**
         * 提交 human_verification / ask_user 的用户答案。
         * @param {string} userInput 答案内容
         * @param {{fromInput?: boolean}} [options]
         *   - fromInput: true 表示答案来自底部输入框，成功后才清空输入框；
         *     false（默认）表示来自预设选项点击，保留输入框草稿不被覆盖。
         */
        async function submitVerificationAnswer(userInput, { fromInput = false } = {}) {
            if (!pendingVerificationId) {
                console.error('No pending verification');
                return;
            }

            try {
                const response = await axios.post(
                    `/api/verification/${pendingVerificationId}`,
                    {
                        approved: true,
                        user_input: userInput
                    },
                    {
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${AUTH_TOKEN}`
                        }
                    }
                );

                if (response.data.success) {
                    console.log('[VERIFICATION] Answer submitted successfully');

                    // 清除验证状态
                    pendingVerificationId = null;
                    pendingVerificationData = null;

                    // 显示用户回答
                    addMessage('user', `我的回答：${userInput}`);

                    // 仅当答案来自输入框时清空；选项点击保留用户草稿
                    const input = document.getElementById('message-input');
                    if (input) {
                        if (fromInput) {
                            input.value = '';
                            input.style.height = 'auto';
                            syncSendBtnLayout();
                        }
                        input.placeholder = window.t ? window.t('placeholder_message') : '输入消息...';
                    }

                    updateStatus(window.t ? window.t('status_waiting_ai') : '等待 AI 继续处理...');
                } else {
                    showError((window.t ? window.t('error_verification_submit_failed_detail', {error: response.data.error}) : '验证提交失败：' + response.data.error + '，请重新输入'));
                    // 保持 pendingVerificationId，允许用户重试；失败不清空输入框
                    const input = document.getElementById('message-input');
                    input?.focus();
                }
            } catch (error) {
                console.error('Failed to submit verification:', error);
                const input = document.getElementById('message-input');

                // 401: token 过期
                if (error.response && error.response.status === 401) {
                    pendingVerificationId = null;
                    pendingVerificationData = null;
                    handleTokenExpired();
                    return;
                }

                // 400 算力不足：清除验证状态，提醒用户充值（保留输入框内容便于后续使用）
                if (error.response && error.response.status === 400 && error.response.data?.error_code === 'INSUFFICIENT_POWER') {
                    pendingVerificationId = null;
                    pendingVerificationData = null;
                    if (input) {
                        input.placeholder = window.t ? window.t('placeholder_message') : '输入消息...';
                    }
                    showError(error.response.data.message || '您的算力不足，请充值后再试');
                    return;
                }

                // 如果是 404/410，说明验证已过期（超时/已完成/已取消），清除状态让用户继续对话
                if (error.response && (error.response.status === 404 || error.response.status === 410)) {
                    pendingVerificationId = null;
                    pendingVerificationData = null;
                    if (input) {
                        input.placeholder = window.t ? window.t('placeholder_message') : '输入消息...';
                    }
                    showError(window.t ? window.t('error_verification_expired') : '验证已过期，请重新发送消息');
                } else {
                    // 其他错误（网络问题等），保持状态与输入内容，允许用户重试
                    showError((window.t ? window.t('error_verification_error_detail', {error: error.message}) : '提交验证时出错：' + error.message + '，请重新输入'));
                    input?.focus();
                }
            }
        }

        function openFeedbackModal() {
            const modal = document.getElementById('feedback-modal');
            modal?.classList.add('show');
        }

        function closeFeedbackModal() {
            const modal = document.getElementById('feedback-modal');
            modal?.classList.remove('show');
        }

        function closeFeedbackFab() {
            const fabContainer = document.getElementById('feedback-fab-container');
            if (fabContainer) {
                fabContainer.style.display = 'none';
            }
        }

        /**
         * 意见反馈：按 server-config 隐藏入口或替换二维码 URL。
         * 与官方微信群引导无关；失败时默认保持开启。
         */
        async function applyFeedbackVisibilityFromServer() {
            const fabContainer = document.getElementById('feedback-fab-container');
            const modal = document.getElementById('feedback-modal');
            const img = modal ? modal.querySelector('img.qr-image') : null;
            let enabled = true;
            let qrUrl = '/files/二维码.jpg';
            try {
                const res = await fetch('/api/system/server-config');
                const data = await res.json();
                if (data && data.code === 0 && data.data) {
                    if (data.data.show_feedback_qr === false) enabled = false;
                    if (data.data.feedback_qr_url) qrUrl = data.data.feedback_qr_url;
                }
            } catch (e) { /* 默认开启 */ }
            if (!enabled) {
                if (fabContainer) {
                    fabContainer.style.display = 'none';
                    fabContainer.setAttribute('hidden', 'true');
                }
                if (modal) {
                    modal.classList.remove('show');
                    modal.style.display = 'none';
                    modal.setAttribute('hidden', 'true');
                }
                return;
            }
            if (img && qrUrl) img.setAttribute('src', qrUrl);
        }

        function showError(message) {
            const messagesDiv = document.getElementById('chat-messages');
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error-toast';
            errorDiv.textContent = message;
            messagesDiv.appendChild(errorDiv);
            scrollToBottom();
            setTimeout(() => errorDiv.remove(), 5000);
        }

        function showSuccess(message) {
            const messagesDiv = document.getElementById('chat-messages');
            const successDiv = document.createElement('div');
            successDiv.className = 'success-toast';
            successDiv.textContent = message;
            messagesDiv.appendChild(successDiv);
            scrollToBottom();
            setTimeout(() => successDiv.remove(), 3000);
        }

        function showInfo(message) {
            const messagesDiv = document.getElementById('chat-messages');
            const infoDiv = document.createElement('div');
            infoDiv.className = 'info-toast';
            infoDiv.textContent = message;
            messagesDiv.appendChild(infoDiv);
            scrollToBottom();
            setTimeout(() => infoDiv.remove(), 3000);
        }

        function showWarning(message) {
            const messagesDiv = document.getElementById('chat-messages');
            const warningDiv = document.createElement('div');
            warningDiv.className = 'warning-toast';
            warningDiv.textContent = message;
            messagesDiv.appendChild(warningDiv);
            scrollToBottom();
            setTimeout(() => warningDiv.remove(), 5000);
        }

        async function loadComputingPower() {
            try {
                const response = await fetch('/api/user/computing_power', {
                    headers: {
                        'Authorization': `Bearer ${AUTH_TOKEN}`
                    }
                });
                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                const powerValue = document.getElementById('power-value');
                if (data.success && powerValue) {
                    const power = data.data?.computing_power || 0;
                    powerValue.textContent = power.toLocaleString();
                    
                    // 根据算力值设置颜色
                    const powerDisplay = document.getElementById('computing-power-display');
                    if (!powerDisplay) return;
                    if (power < 100) {
                        powerDisplay.classList.add('low-power');
                        powerDisplay.classList.remove('medium-power', 'high-power');
                    } else if (power < 1000) {
                        powerDisplay.classList.add('medium-power');
                        powerDisplay.classList.remove('low-power', 'high-power');
                    } else {
                        powerDisplay.classList.add('high-power');
                        powerDisplay.classList.remove('low-power', 'medium-power');
                    }
                } else if (powerValue) {
                    powerValue.textContent = '--';
                }
            } catch (error) {
                console.error('加载算力失败:', error);
                const powerValue = document.getElementById('power-value');
                if (powerValue) {
                    powerValue.textContent = '--';
                }
            }
        }

        async function loadVendors() {
            try {
                const response = await fetch('/api/vendors');
                const data = await response.json();
                if (data.success && data.vendors) {
                    data.vendors.forEach(v => {
                        const key = v.vendor_name.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
                        LLMVendor[key] = v.vendor_name;
                        vendorIcons[v.vendor_name.toLowerCase()] = v.icon || '📦';
                    });
                    console.log('[供应商加载] LLMVendor:', LLMVendor, 'vendorIcons:', vendorIcons);
                }
            } catch (e) {
                console.warn('[供应商加载] 失败，使用空映射:', e);
            }
        }

        async function loadAvailableModels() {
            try {
                const response = await fetch('/api/models', {
                    headers: {
                        'Authorization': `Bearer ${AUTH_TOKEN}`
                    }
                });
                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                const selector = document.getElementById('model-selector');
                selector.innerHTML = '';

                if (!data.success) {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = window.t ? window.t('error_model_load_failed') : '模型加载失败';
                    selector.appendChild(option);
                    showError(data.error || '获取模型列表失败');
                    return;
                }

                if (!data.models || data.models.length === 0) {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = '暂无可用模型';
                    selector.appendChild(option);
                    return;
                }

                // 按 vendor_name 分组，vendor_id 排序
                const vendorGroups = {};
                const vendorOrder = [];  // 保持 vendor 顺序
                data.models.forEach(model => {
                    const vendorId = model.vendor_id || 1;
                    const vendorName = model.vendor_name || 'unknown';
                    if (!vendorGroups[vendorId]) {
                        vendorGroups[vendorId] = {
                            vendorName: vendorName,
                            models: []
                        };
                        vendorOrder.push(vendorId);
                    }
                    vendorGroups[vendorId].models.push(model);
                });

                // 计算 input_token_threshold 倍数（threshold 越小越贵，以最大的 threshold 为基准 x1）
                const validThresholds = data.models
                    .map(m => m.input_token_threshold)
                    .filter(v => v && v > 0);
                const maxThreshold = validThresholds.length > 0 ? Math.max(...validThresholds) : null;

                // 调试日志：输出所有模型的费用信息
                console.log('[模型加载] 模型费用倍率计算:');
                console.log('  有效的 threshold 值:', validThresholds);
                console.log('  最大 threshold (基准):', maxThreshold);
                data.models.forEach(m => {
                    const threshold = m.input_token_threshold;
                    const multiplier = maxThreshold && threshold && threshold > 0
                        ? (maxThreshold / threshold).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')
                        : '不可用';
                    console.log(`  ${m.model_name} (vendor: ${m.vendor_name}): threshold=${threshold}, multiplier=${multiplier}x`);
                });

                // 记录排序后的第一个作为默认选中
                let firstEnabledModel = null;

                // 创建选项的辅助函数
                const createModelOption = (model) => {
                    const option = document.createElement('option');
                    const modelName = model.model_name || model.name || '';
                    const modelDesc = model.note || model.description || '';
                    // 判断是否为 Ollama 模型：vendor_name=ollama 或 id 包含 "ollama:" 前缀
                    const isOllama = model.vendor_name === LLMVendor.OLLAMA || String(model.id || '').startsWith('ollama:');
                    // Ollama 模型使用带前缀的模型名，其他模型使用 model_name
                    option.value = isOllama ? `ollama:${modelName}` : modelName;
                    option.dataset.conciseName = modelName;

                    let displayName = modelName;
                    // 改进费用倍率显示：确保有效数据时必须显示倍率
                    if (maxThreshold && model.input_token_threshold && model.input_token_threshold > 0) {
                        const multiplier = (maxThreshold / model.input_token_threshold)
                            .toFixed(2)
                            .replace(/\.00$/, '')
                            .replace(/(\.\d)0$/, '$1');
                        displayName = `${modelName} x${multiplier}`;  // 加上 x 使倍率更清晰
                    } else if (model.input_token_threshold === undefined || model.input_token_threshold === null) {
                        // 调试：标记缺少费用信息的模型
                        console.warn(`[模型加载] 模型 "${modelName}" 缺少 input_token_threshold 信息`);
                    }

                    option.textContent = displayName;
                    // model_id 用于获取 context_window 等信息
                    const dbModelId = model.model_id ?? '';
                    if (dbModelId) {
                        option.dataset.modelId = dbModelId;
                    }
                    if (model.context_window) {
                        option.dataset.contextWindow = model.context_window;
                    }
                    option.dataset.recommended = model.recommended ? 'true' : 'false';
                    option.dataset.vendorId = model.vendor_id || 1;
                    option.dataset.vendorName = model.vendor_name || 'jiekou';
                    option.dataset.supportsThinking = model.supports_thinking ? 'true' : 'false';
                    return option;
                };

                // 按 vendor 分组添加模型
                vendorOrder.forEach(vendorId => {
                    const group = vendorGroups[vendorId];
                    if (group.models.length > 0) {
                        const optGroup = document.createElement('optgroup');
                        const icon = vendorIcons[group.vendorName.toLowerCase()] || '📦';
                        const isOllamaGroup = group.vendorName.toLowerCase() === 'ollama';
                        const suffix = (isOllamaGroup && isCommunityEdition) ? '（限时免费）' : '';
                        optGroup.label = `${icon} ${group.vendorName}${suffix}`;
                        group.models.forEach(model => {
                            const option = createModelOption(model);
                            if (!option.disabled && !firstEnabledModel) {
                                firstEnabledModel = option;
                            }
                            optGroup.appendChild(option);
                        });
                        selector.appendChild(optGroup);
                    }
                });

                // 设置默认选中模型：deepseek-v4-flash (deepseek) → qwen3.5-plus (zjt_api) → qwen3.5-plus (其他) → 第一个启用的模型
                let defaultModel = null;

                const allOptions = selector.querySelectorAll('option');
                // 第一轮：优先查找 deepseek 供应商下的 deepseek-v4-flash
                for (let i = 0; i < allOptions.length; i++) {
                    const option = allOptions[i];
                    if (!option.disabled && option.value && option.value.includes('deepseek-v4-flash')
                        && option.dataset.vendorName === LLMVendor.DEEPSEEK) {
                        defaultModel = option;
                        console.log('[模型选择] 选择默认模型: deepseek-v4-flash (deepseek)');
                        break;
                    }
                }
                // 第二轮：查找 zjt_api 供应商下的 qwen3.5-plus
                if (!defaultModel) {
                    for (let i = 0; i < allOptions.length; i++) {
                        const option = allOptions[i];
                        if (!option.disabled && option.value && option.value.includes('qwen3.5-plus')
                            && option.dataset.vendorName === LLMVendor.ZJT_API) {
                            defaultModel = option;
                            console.log('[模型选择] 选择默认模型: qwen3.5-plus (zjt_api)');
                            break;
                        }
                    }
                }
                // 第三轮：查找其他供应商的 qwen3.5-plus
                if (!defaultModel) {
                    for (let i = 0; i < allOptions.length; i++) {
                        const option = allOptions[i];
                        if (!option.disabled && option.value && option.value.includes('qwen3.5-plus')) {
                            defaultModel = option;
                            console.log(`[模型选择] 未找到 zjt_api 的 qwen3.5-plus，选择其他供应商: ${option.dataset.vendorName}`);
                            break;
                        }
                    }
                }

                // 最终回退：使用第一个启用的模型
                if (!defaultModel && firstEnabledModel) {
                    defaultModel = firstEnabledModel;
                    console.log(`[模型选择] 未找到推荐模型，选择第一个启用的模型: ${firstEnabledModel.value}`);
                }

                if (defaultModel) {
                    defaultModel.selected = true;
                }

                // 检查是否有上次选择的模型并自动选中
                const savedModelRaw = localStorage.getItem('lastSelectedLlmModel');
                if (savedModelRaw) {
                    try {
                        const saved = JSON.parse(savedModelRaw);
                        const savedModelName = saved.model || saved;
                        const savedVendorId = saved.vendorId || '';
                        const options = selector.querySelectorAll('option');
                        // 优先匹配模型名+供应商ID
                        let matched = false;
                        if (savedVendorId) {
                            for (let i = 0; i < options.length; i++) {
                                if (options[i].value === savedModelName && !options[i].disabled
                                    && options[i].dataset.vendorId === String(savedVendorId)) {
                                    selector.selectedIndex = i;
                                    console.log(`[模型记忆] 自动选中上次模型: ${savedModelName} (vendor_id: ${savedVendorId})`);
                                    matched = true;
                                    break;
                                }
                            }
                        }
                        // 回退：仅匹配模型名
                        if (!matched) {
                            for (let i = 0; i < options.length; i++) {
                                if (options[i].value === savedModelName && !options[i].disabled) {
                                    selector.selectedIndex = i;
                                    console.log(`[模型记忆] 自动选中上次模型(回退匹配): ${savedModelName}`);
                                    break;
                                }
                            }
                        }
                    } catch (e) {
                        // 兼容旧格式（纯字符串）
                        const options = selector.querySelectorAll('option');
                        for (let i = 0; i < options.length; i++) {
                            if (options[i].value === savedModelRaw && !options[i].disabled) {
                                selector.selectedIndex = i;
                                console.log(`[模型记忆] 自动选中上次模型(旧格式): ${savedModelRaw}`);
                                break;
                            }
                        }
                    }
                }

                updateModelSelectorDisplay();
                updateModelTooltip();
                updateThinkingModeUI();

                // 确保选中的模型可用，否则自动切换
                ensureValidModelSelected();
            } catch (error) {
                console.error('加载模型列表失败:', error);
                showError(window.t ? window.t('error_load_models_failed') : '加载模型列表失败，请稍后重试');
            }
        }

        /**
         * 确保当前选中的模型可用
         * 如果选中了 disabled 的模型，自动切换到第一个可用模型
         * 如果所有模型都不可用，将 select 设为红色提醒用户
         */
        function ensureValidModelSelected() {
            const selector = document.getElementById('model-selector');
            if (!selector) return;

            const selectedOption = selector.options[selector.selectedIndex];
            // 当前选中项可用，清除红色样式
            if (selectedOption && !selectedOption.disabled) {
                selector.style.borderColor = '';
                selector.title = '选择 AI 模型';
                updateModelTooltip();
                return;
            }

            // 当前选中项被禁用，尝试切换到第一个可用模型
            let firstEnabled = null;
            for (let i = 0; i < selector.options.length; i++) {
                if (!selector.options[i].disabled && selector.options[i].value) {
                    firstEnabled = i;
                    break;
                }
            }

            if (firstEnabled !== null) {
                selector.selectedIndex = firstEnabled;
                selector.style.borderColor = '';
                selector.title = '选择 AI 模型';
                console.log(`[模型自动切换] 切换到可用模型: ${selector.options[firstEnabled].value}`);
            } else {
                // 所有模型都不可用，设为红色提醒
                selector.style.borderColor = '#ff4444';
                selector.style.boxShadow = '0 0 0 1px #ff4444';
                selector.title = '所有模型均不可用，请检查配置';
                console.warn('[模型自动切换] 所有模型均不可用');
            }
            updateModelTooltip();
        }

        function updateModelSelectorDisplay() {
            const selector = document.getElementById('model-selector');
            const display = document.getElementById('model-selector-display');
            if (!selector || !display) return;

            const selectedOption = selector.options[selector.selectedIndex];
            if (!selectedOption) return;

            const conciseName = selectedOption.dataset.conciseName || selectedOption.value || selectedOption.textContent;
            display.textContent = conciseName;
            display.style.color = '';
        }

        let activeCustomModelSelect = null;
        let customModelSelectListenersReady = false;

        function closeCustomModelSelectMenu() {
            if (!activeCustomModelSelect) return;
            activeCustomModelSelect.menu.remove();
            activeCustomModelSelect.wrapper.classList.remove('custom-select-open');
            activeCustomModelSelect.wrapper.setAttribute('aria-expanded', 'false');
            activeCustomModelSelect = null;
        }

        function appendCustomModelSelectOption(menu, selector, option, optionIndex) {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'custom-model-select-option';
            item.textContent = option.textContent || option.value;
            item.title = option.textContent || option.value;
            item.disabled = option.disabled;
            if (option.selected) {
                item.classList.add('selected');
            }
            item.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (option.disabled) return;
                selector.selectedIndex = optionIndex;
                closeCustomModelSelectMenu();
                selector.dispatchEvent(new Event('change', { bubbles: true }));
            });
            menu.appendChild(item);
        }

        function appendCustomModelSelectOptions(menu, selector, children) {
            Array.from(children).forEach((child) => {
                if (child.tagName === 'OPTGROUP') {
                    const label = document.createElement('div');
                    label.className = 'custom-model-select-group';
                    label.textContent = child.label;
                    menu.appendChild(label);
                    appendCustomModelSelectOptions(menu, selector, child.children);
                    return;
                }
                if (child.tagName !== 'OPTION') return;
                const optionIndex = Array.prototype.indexOf.call(selector.options, child);
                appendCustomModelSelectOption(menu, selector, child, optionIndex);
            });
        }

        function openCustomModelSelectMenu(selector) {
            const wrapper = selector.closest('.model-select-wrapper');
            if (!wrapper) return;
            if (activeCustomModelSelect && activeCustomModelSelect.selector === selector) {
                closeCustomModelSelectMenu();
                return;
            }
            closeCustomModelSelectMenu();

            const rect = wrapper.getBoundingClientRect();
            const menu = document.createElement('div');
            menu.className = 'custom-model-select-menu';
            menu.style.top = `${rect.bottom + 6}px`;
            menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8))}px`;
            menu.style.width = `${Math.max(rect.width, 240)}px`;
            menu.style.maxHeight = `${Math.max(120, Math.min(400, window.innerHeight - rect.bottom - 18))}px`;
            appendCustomModelSelectOptions(menu, selector, selector.children);
            document.body.appendChild(menu);

            wrapper.classList.add('custom-select-open');
            wrapper.setAttribute('aria-expanded', 'true');
            activeCustomModelSelect = { selector, wrapper, menu };
        }

        function initCustomModelSelectMenus() {
            document.querySelectorAll('.model-select-wrapper .model-select').forEach((selector) => {
                const wrapper = selector.closest('.model-select-wrapper');
                const display = wrapper?.querySelector('.model-select-display');
                if (!wrapper || !display || wrapper.dataset.customSelectReady === 'true') return;
                wrapper.dataset.customSelectReady = 'true';
                wrapper.tabIndex = 0;
                wrapper.setAttribute('role', 'combobox');
                wrapper.setAttribute('aria-haspopup', 'listbox');
                wrapper.setAttribute('aria-expanded', 'false');
                selector.tabIndex = -1;
                selector.setAttribute('aria-hidden', 'true');

                const openMenu = (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    openCustomModelSelectMenu(selector);
                };
                display.addEventListener('click', openMenu);
                wrapper.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        openMenu(event);
                    } else if (event.key === 'Escape') {
                        closeCustomModelSelectMenu();
                    }
                });
            });

            if (customModelSelectListenersReady) return;
            customModelSelectListenersReady = true;
            document.addEventListener('click', (event) => {
                if (!activeCustomModelSelect) return;
                if (activeCustomModelSelect.menu.contains(event.target) || activeCustomModelSelect.wrapper.contains(event.target)) return;
                closeCustomModelSelectMenu();
            });
            window.addEventListener('resize', closeCustomModelSelectMenu);
            window.addEventListener('scroll', (event) => {
                if (!activeCustomModelSelect) return;
                // 菜单自身（或其内部）滚动时不应关闭；仅当滚动发生在菜单/触发元素外部时才关闭
                const target = event.target;
                if (target instanceof Node) {
                    if (activeCustomModelSelect.menu.contains(target) || activeCustomModelSelect.wrapper.contains(target)) {
                        return;
                    }
                }
                closeCustomModelSelectMenu();
            }, true);
        }

        function updateModelTooltip() {
            const selector = document.getElementById('model-selector');
            if (!selector) return;

            const selectedOption = selector.options[selector.selectedIndex];
            if (!selectedOption) return;

            // 清除红色样式
            selector.style.color = '';

            // 更新 LLM 模型图标的 hover 提示
            updateLlmModelIcon();
            updateModelSelectorDisplay();
        }

        function updateLlmModelIcon() {
            const selector = document.getElementById('model-selector');
            const icon = document.getElementById('llm-model-icon');
            if (!selector || !icon) return;

            const selectedOption = selector.options[selector.selectedIndex];
            if (!selectedOption) {
                icon.title = 'AI 模型';
                return;
            }

            const modelName = selectedOption.textContent;
            icon.title = `AI 模型: ${modelName}`;
        }

        // ==================== 思考模式 ====================
        function updateThinkingModeUI() {
            const selector = document.getElementById('model-selector');
            const wrapper = document.getElementById('thinking-mode-wrapper');
            if (!selector || !wrapper) return;

            const selectedOption = selector.options[selector.selectedIndex];
            if (!selectedOption) {
                wrapper.style.display = 'none';
                return;
            }

            const supportsThinking = selectedOption.dataset.supportsThinking === 'true';
            wrapper.style.display = supportsThinking ? 'flex' : 'none';

            // 如果支持思考模式，恢复缓存的状态
            if (supportsThinking) {
                restoreThinkingState();
            } else {
                // 如果不支持思考模式，重置开关
                const toggle = document.getElementById('thinking-toggle');
                if (toggle) toggle.checked = false;
                updateThinkingEffortVisibility();
            }
        }

        function saveThinkingState(isUserAction = false) {
            const toggle = document.getElementById('thinking-toggle');
            const effortSelect = document.getElementById('thinking-effort');
            if (!toggle) return;

            const state = {
                enabled: toggle.checked,
                effort: effortSelect ? effortSelect.value : 'medium',
                // 记录用户是否明确关闭了思考模式（只有用户手动切换时才更新此字段）
                explicitlyDisabled: isUserAction ? !toggle.checked : ((function() { try { return JSON.parse(localStorage.getItem('lastThinkingState') || '{}'); } catch(e) { return {}; } })().explicitlyDisabled || false)
            };
            localStorage.setItem('lastThinkingState', JSON.stringify(state));
        }

        function restoreThinkingState() {
            const savedStateRaw = localStorage.getItem('lastThinkingState');
            const toggle = document.getElementById('thinking-toggle');
            const effortSelect = document.getElementById('thinking-effort');
            if (!toggle) return;

            // 获取当前选中模型的信息
            const selector = document.getElementById('model-selector');
            const selectedOption = selector?.options?.[selector.selectedIndex];
            const vendorName = (selectedOption?.dataset?.vendorName || '').toLowerCase();
            const modelValue = (selectedOption?.value || '').toLowerCase();
            const conciseName = (selectedOption?.dataset?.conciseName || '').toLowerCase();

            // 判断是否为 DeepSeek 模型（使用多种方式判断，确保可靠性）
            const isDeepSeek = vendorName === 'deepseek' ||
                modelValue.includes('deepseek') ||
                conciseName.includes('deepseek') ||
                (LLMVendor.DEEPSEEK && vendorName === LLMVendor.DEEPSEEK.toLowerCase());

            console.log('[思考模式] restoreThinkingState:', {
                savedStateRaw,
                vendorName,
                modelValue,
                conciseName,
                isDeepSeek,
                LLMVendor_DEEPSEEK: LLMVendor.DEEPSEEK,
                selectedOptionValue: selectedOption?.value
            });

            if (savedStateRaw) {
                try {
                    const state = JSON.parse(savedStateRaw);
                    // 对于 DeepSeek 模型，如果用户没有明确设置过不开启思考模式，默认开启
                    // 只有当 state.explicitlyDisabled 为 true 时，才保持关闭
                    if (isDeepSeek && !state.explicitlyDisabled) {
                        toggle.checked = true;
                        console.log('[思考模式] DeepSeek 模型默认开启思考模式');
                    } else {
                        toggle.checked = state.enabled || false;
                    }
                    if (effortSelect && state.effort) {
                        effortSelect.value = state.effort;
                    }
                    updateThinkingEffortVisibility();
                } catch (e) {
                    console.warn('[思考模式] 恢复状态失败:', e);
                    // 恢复失败时，对于 DeepSeek 模型默认开启
                    if (isDeepSeek) {
                        toggle.checked = true;
                    }
                }
            } else {
                // 无缓存：DeepSeek 模型默认开启思考模式
                if (isDeepSeek) {
                    toggle.checked = true;
                    console.log('[思考模式] DeepSeek 模型无缓存，默认开启思考模式');
                }
                updateThinkingEffortVisibility();
                saveThinkingState();
            }
        }

        function onThinkingToggleChange() {
            saveThinkingState(true);  // 传入 true 表示是用户手动切换
            updateThinkingEffortVisibility();
        }

        function updateThinkingEffortVisibility() {
            const toggle = document.getElementById('thinking-toggle');
            const effortSelect = document.getElementById('thinking-effort');
            const selector = document.getElementById('model-selector');
            if (!toggle || !effortSelect || !selector) return;

            const selectedOption = selector.options[selector.selectedIndex];
            const vendorName = selectedOption?.dataset?.vendorName || '';
            const isDoubao = vendorName === 'volcengine' || (selectedOption?.value || '').startsWith('doubao');

            // 只在开关打开且是 Doubao 模型时显示 effort 选择
            effortSelect.style.display = (toggle.checked && isDoubao) ? 'inline-block' : 'none';
        }

        function onThinkingEffortChange() {
            saveThinkingState();
        }

        function getThinkingParams() {
            const toggle = document.getElementById('thinking-toggle');
            const effortSelect = document.getElementById('thinking-effort');
            if (!toggle || !toggle.checked) {
                return { enable_thinking: false, thinking_effort: 'medium' };
            }
            return {
                enable_thinking: true,
                thinking_effort: effortSelect ? effortSelect.value : 'medium'
            };
        }

        // ==================== AI 介入程度 ====================
        const INTERVENTION_LEVEL_I18N_KEYS = {
            balanced: 'intervention_balanced',
            concise: 'intervention_concise',
            detailed: 'intervention_detailed'
        };

        function onInterventionLevelChange() {
            const selector = document.getElementById('intervention-level-selector');
            if (!selector) return;
            localStorage.setItem('lastInterventionLevel', selector.value);
            updateInterventionLevelDisplay();
        }

        function updateInterventionLevelDisplay() {
            const selector = document.getElementById('intervention-level-selector');
            const display = document.getElementById('intervention-level-display');
            if (!selector || !display) return;
            const fallbackLabels = {
                balanced: '标准',
                concise: '简洁·少提问',
                detailed: '精细·多确认'
            };
            const value = selector.value || 'balanced';
            const translationKey = INTERVENTION_LEVEL_I18N_KEYS[value] || INTERVENTION_LEVEL_I18N_KEYS.balanced;
            display.textContent = window.t ? window.t(translationKey) : (fallbackLabels[value] || fallbackLabels.balanced);
        }

        function restoreInterventionLevel() {
            const saved = localStorage.getItem('lastInterventionLevel');
            const selector = document.getElementById('intervention-level-selector');
            if (!selector) return;
            if (saved && ['balanced', 'concise', 'detailed'].includes(saved)) {
                selector.value = saved;
            } else {
                selector.value = 'balanced';
            }
            updateInterventionLevelDisplay();
        }

        function getInterventionLevel() {
            const selector = document.getElementById('intervention-level-selector');
            return selector ? selector.value : 'balanced';
        }

        // ==================== 窄屏暂存区切换 ====================
        function toggleFileSidebar() {
            const sidebar = document.getElementById('file-sidebar');
            const overlay = document.getElementById('file-sidebar-overlay');
            if (!sidebar || !overlay) return;
            const isOpen = sidebar.classList.contains('open');
            if (isOpen) {
                sidebar.classList.remove('open');
                overlay.classList.remove('active');
                document.body.style.overflow = '';
            } else {
                sidebar.classList.add('open');
                overlay.classList.add('active');
                document.body.style.overflow = 'hidden';
            }
        }

        function openModelSettingsPanel() {
            const card = document.getElementById('model-selector-card');
            const overlay = document.getElementById('model-settings-overlay');
            const button = document.querySelector('.model-settings-toggle-btn');
            if (!card || !overlay) return;
            card.classList.add('compact-open');
            overlay.classList.add('active');
            if (button) button.setAttribute('aria-expanded', 'true');
        }

        function closeModelSettingsPanel() {
            const card = document.getElementById('model-selector-card');
            const overlay = document.getElementById('model-settings-overlay');
            const button = document.querySelector('.model-settings-toggle-btn');
            if (!card || !overlay) return;
            card.classList.remove('compact-open');
            overlay.classList.remove('active');
            if (button) button.setAttribute('aria-expanded', 'false');
        }

        function toggleModelSettingsPanel() {
            const card = document.getElementById('model-selector-card');
            if (card && card.classList.contains('compact-open')) {
                closeModelSettingsPanel();
            } else {
                openModelSettingsPanel();
            }
        }

        function updateImageModelIcon() {
            const selector = document.getElementById('text-to-image-model-selector');
            const icon = document.getElementById('image-model-icon');
            if (!selector || !icon) return;

            const selectedOption = selector.options[selector.selectedIndex];
            if (!selectedOption) {
                icon.title = '生图模型';
                return;
            }

            const modelName = selectedOption.textContent;
            icon.title = `生图模型: ${modelName}`;
            // 同步自定义下拉框的显示文本（与 LLM 模型的 updateModelSelectorDisplay 保持一致）
            updateImageModelDisplay();
        }

        function updateImageModelDisplay() {
            const selector = document.getElementById('text-to-image-model-selector');
            const display = document.getElementById('image-model-selector-display');
            if (!selector || !display) return;

            const selectedOption = selector.options[selector.selectedIndex];
            if (!selectedOption) return;

            display.textContent = selectedOption.dataset.conciseName || selectedOption.textContent || selectedOption.value;
            display.style.color = '';
        }


        async function changeModel() {
            if (!sessionId) {
                showError(window.t ? window.t('error_create_session_first') : '请先创建会话');
                return;
            }
            const selector = document.getElementById('model-selector');
            const selectedOption = selector.options[selector.selectedIndex];
            const model = selector.value;
            const modelId = selectedOption?.dataset?.modelId;

            // 保存选中的模型和供应商到 localStorage
            const vendorId = selectedOption?.dataset?.vendorId || '';
            localStorage.setItem('lastSelectedLlmModel', JSON.stringify({ model, vendorId }));

            updateModelTooltip();
            updateLlmModelIcon();
            updateThinkingModeUI();

            // Ollama 模型检测和警告
            const vendorName = selectedOption?.dataset?.vendorName || '';
            const isOllama = vendorName === LLMVendor.OLLAMA;

            if (isOllama) {
                showWarning('⚠️ ' + (window.t ? window.t('warn_ollama_local', {model: LLMModel.QWEN_3_5_PLUS}) : '本地模型提示：Ollama 模型为本地运行，存在不稳定情况。推荐使用 ' + LLMModel.QWEN_3_5_PLUS + ' 模型以获得更好的体验。'));
            }

            // 其他模型不推荐提示
            const modelValue = model || '';
            if (modelValue === LLMModel.GEMINI_3_1_PRO) {
                showWarning('⚠️ ' + (window.t ? window.t('warn_expensive_model', {model: LLMModel.GEMINI_3_FLASH}) : '该模型价格较贵，推荐使用 ' + LLMModel.GEMINI_3_FLASH + ' 以获得更好的性价比。'));
            } else if (modelValue.includes('flash-lite')) {
                showWarning('⚠️ ' + (window.t ? window.t('warn_weak_model', {model: LLMModel.GEMINI_3_FLASH}) : '该模型实际表现不够智能，可能无法胜任复杂任务，谨慎选择。推荐使用 ' + LLMModel.GEMINI_3_FLASH + ' 以获得更好的效果。'));
            }

            if (!AUTH_TOKEN) {
                showError(window.t ? window.t('error_auth_missing') : '缺少认证信息，请重新登录');
                return;
            }


            try {
                const response = await fetch(`/api/session/${sessionId}/model`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        model: model,
                        model_id: modelId,
                        auth_token: AUTH_TOKEN
                    })
                });
                const data = await response.json();
                if (data.success) {
                    showSuccess(window.t ? window.t('success_switched_to', {name: selector.options[selector.selectedIndex].text}) : `已切换到 ${selector.options[selector.selectedIndex].text}`);
                } else {
                    // 如果返回了有效模型列表，显示更详细的错误信息
                    if (data.valid_models && data.valid_models.length > 0) {
                        showError(window.t ? window.t('error_switch_model_detail', {error: data.error, models: data.valid_models.join(', ')}) : `切换模型失败: ${data.error}
可用模型: ${data.valid_models.join(', ')}`);
                    } else {
                        showError(window.t ? window.t('error_switch_model_failed', {error: data.error}) : '切换模型失败: ' + data.error);
                    }
                }
            } catch (error) {
                showError((window.t ? window.t('error_switch_model_failed', {error: error.message}) : '切换模型失败: ' + error.message));
            }
        }

        async function loadDriverStatus() {
            try {
                const response = await fetch('/api/computing-power-config', {
                    headers: { 'Authorization': `Bearer ${AUTH_TOKEN}` }
                });
                const data = await response.json();
                if (data.success && data.data) {
                    driverStatus = data.data.driver_status || {};
                }
            } catch (error) {
                console.error('获取驱动状态失败:', error);
            }
        }

        async function loadTextToImageModels() {
            try {
                const response = await fetch('/api/text-to-image-models', {
                    headers: {
                        'Authorization': `Bearer ${AUTH_TOKEN}`
                    }
                });
                const data = await response.json();

                if (checkTokenExpired(data, response)) {
                    return;
                }

                const selector = document.getElementById('text-to-image-model-selector');
                selector.innerHTML = '';

                if (!data.success) {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = window.t ? window.t('error_model_load_failed') : '模型加载失败';
                    selector.appendChild(option);
                    showError(data.error || '获取生图模型列表失败');
                    return;
                }

                const models = data.models;
                if (!models || models.length === 0) {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = '暂无可用模型';
                    selector.appendChild(option);
                    return;
                }

                // 按优先级分组模型：GPT IMAGE 2 优先，其次 Seedream 5.0，最后其他支持宫格生图的模型
                const gptImage2Model = models.find(m => m.task_id === 26);  // GPT IMAGE 2 的 task_id 为 26
                const seedreamModel = models.find(m => m.name === 'Seedream 5.0');
                const otherModels = models.filter(m => m.task_id !== 26 && m.name !== 'Seedream 5.0' && m.supports_grid_image);

                // 先添加 GPT IMAGE 2（如果可用）
                if (gptImage2Model) {
                    const option = document.createElement('option');
                    option.value = gptImage2Model.task_id;
                    // 检查模型可用性
                    const taskTypeKey = String(gptImage2Model.task_id);
                    const status = driverStatus[taskTypeKey];
                    const isAvailable = !status || status.available !== false;
                    if (!isAvailable) {
                        option.textContent = `${gptImage2Model.name} (未配置)`;
                        option.disabled = true;
                    } else {
                        option.textContent = gptImage2Model.name;
                        option.selected = true;  // GPT IMAGE 2 默认选中（仅当可用时）
                    }
                    selector.appendChild(option);
                }

                // 再添加 Seedream 5.0
                if (seedreamModel) {
                    const option = document.createElement('option');
                    option.value = seedreamModel.task_id;
                    // 检查模型可用性
                    const taskTypeKey = String(seedreamModel.task_id);
                    const status = driverStatus[taskTypeKey];
                    const isAvailable = !status || status.available !== false;
                    if (!isAvailable) {
                        option.textContent = `${seedreamModel.name} (未配置)`;
                        option.disabled = true;
                    } else {
                        option.textContent = seedreamModel.name;
                        // 如果 GPT IMAGE 2 不可用，Seedream 作为备选默认选中
                        if (!gptImage2Model) {
                            option.selected = true;
                        }
                    }
                    selector.appendChild(option);
                }

                // 最后添加其他模型
                otherModels.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model.task_id;
                    // 检查模型可用性
                    const taskTypeKey = String(model.task_id);
                    const status = driverStatus[taskTypeKey];
                    const isAvailable = !status || status.available !== false;
                    if (!isAvailable) {
                        option.textContent = `${model.name} (未配置)`;
                        option.disabled = true;
                    } else {
                        option.textContent = model.name;
                    }
                    selector.appendChild(option);
                });

                // 显示选择器
                selector.style.display = '';
                // 包装在 .model-select-wrapper 后，同步自定义显示层的文本
                updateImageModelDisplay();
                // 注意：自动设置模型逻辑已移至 createSession() 成功后执行
            } catch (error) {
                console.error('加载生图模型列表失败:', error);
                const selector = document.getElementById('text-to-image-model-selector');
                if (selector) {
                    selector.innerHTML = `<option value="">${window.t ? window.t('error_model_load_failed') : '模型加载失败'}</option>`;
                }
                showError(window.t ? window.t('error_load_image_models_failed') : '加载生图模型列表失败，请稍后重试');
            }
        }

        async function autoSetTextToImageModel() {
            /** 会话创建后自动设置生图模型到后端 */
            const selector = document.getElementById('text-to-image-model-selector');
            if (!selector || !sessionId) return;

            let selectedModel = selector.value;

            // 如果没有选中的模型，尝试智能选择：优先 GPT IMAGE 2，其次 Seedream 5.0
            if (!selectedModel) {
                // 查找可用的模型
                let gptImage2Option = null;
                let seedreamOption = null;
                let firstAvailableOption = null;

                for (const option of selector.options) {
                    if (option.value && !option.disabled) {
                        if (!firstAvailableOption) {
                            firstAvailableOption = option;
                        }
                        if (option.value === '26') {  // GPT IMAGE 2 的 task_id
                            gptImage2Option = option;
                        }
                        if (option.textContent.includes('Seedream 5.0')) {
                            seedreamOption = option;
                        }
                    }
                }

                // 按优先级选择
                if (gptImage2Option) {
                    selectedModel = gptImage2Option.value;
                    selector.value = selectedModel;
                } else if (seedreamOption) {
                    selectedModel = seedreamOption.value;
                    selector.value = selectedModel;
                } else if (firstAvailableOption) {
                    selectedModel = firstAvailableOption.value;
                    selector.value = selectedModel;
                } else {
                    // 没有可用模型
                    return;
                }
            }

            if (!selectedModel) return;

            console.log('[DEBUG] 自动设置生图模型:', selector.options[selector.selectedIndex].text, 'task_id:', selectedModel);
            try {
                const response = await fetch('/api/text-to-image-model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        model_id: selectedModel,
                        auth_token: AUTH_TOKEN,
                        session_id: sessionId
                    })
                });
                const data = await response.json();
                console.log('[DEBUG] 设置生图模型响应:', data);
                if (data.success) {
                    console.log('[DEBUG] 生图模型已保存:', data.model_name);
                }
            } catch (err) {
                console.error('[DEBUG] 设置生图模型异常:', err);
            }
            updateImageModelIcon();
        }

        async function changeTextToImageModel() {
            if (!sessionId) {
                showError(window.t ? window.t('error_create_session_first') : '请先创建会话');
                return;
            }

            const selector = document.getElementById('text-to-image-model-selector');
            const model = selector.value;

            if (!model) {
                showError(window.t ? window.t('error_select_image_model') : '请选择生图模型');
                return;
            }

            if (!USER_ID || !WORLD_ID) {
                showError(window.t ? window.t('error_missing_ids') : '缺少用户ID或世界ID，请刷新页面重试');
                return;
            }

            if (!AUTH_TOKEN) {
                showError(window.t ? window.t('error_auth_missing') : '缺少认证信息，请重新登录');
                return;
            }

            try {
                const response = await fetch('/api/text-to-image-model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        model_id: model,
                        auth_token: AUTH_TOKEN,
                        session_id: sessionId
                    })
                });
                const data = await response.json();
                if (data.success) {
                    showSuccess(window.t ? window.t('success_switched_to', {name: selector.options[selector.selectedIndex].text}) : `已切换到 ${selector.options[selector.selectedIndex].text}`);
                } else {
                    showError((window.t ? window.t('error_switch_image_model_failed', {error: data.error}) : '切换生图模型失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_switch_image_model_failed', {error: error.message}) : '切换生图模型失败: ' + error.message));
            }
            updateImageModelIcon();
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML.replace(/\n/g, '<br>');
        }

        function escapeHtmlAttr(str) {
            return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        function getScriptEpisodeNumber(file) {
            if (!file) return '';
            const direct = file.episode_number || file.json_data?.episode_number;
            if (direct) return direct;
            const source = `${file.display_name || ''} ${file.file_name || ''} ${file.name || ''}`;
            const match = source.match(/(?:第\s*)?(\d+)\s*(?:集|episode|ep)?/i);
            return match ? match[1] : '';
        }

        async function openStoryboardFromScript(scriptId, episodeNumber) {
            const currentWorldId = window.currentWorldId || WORLD_ID;
            if (!currentWorldId) {
                alert('请先选择世界');
                return;
            }

            const ep = parseInt(episodeNumber, 10);
            if (!ep) {
                alert('该剧本没有集数信息');
                return;
            }

            // 进入故事板前检查当前世界是否已有角色图和场景图
            const assetsStatus = await checkAssetsComplete();
            const charCount = assetsStatus.character_image_count || 0;
            const locCount = assetsStatus.location_image_count || 0;
            if (charCount === 0 || locCount === 0) {
                let message = '';
                if (charCount === 0 && locCount === 0) {
                    message = window.t ? window.t('storyboard_entry_no_character_and_location_image') : '⚠️ 当前世界还没有角色参考图和场景参考图';
                } else if (charCount === 0) {
                    message = window.t ? window.t('storyboard_entry_no_character_image') : '⚠️ 当前世界还没有角色参考图';
                } else {
                    message = window.t ? window.t('storyboard_entry_no_location_image') : '⚠️ 当前世界还没有场景参考图';
                }
                message += window.t ? window.t('storyboard_entry_submit_hint') : '\n💡 提示：请点击上方的「提交」按钮提交数据后再进入故事板';
                alert(message);
                return;
            }

            const params = new URLSearchParams({
                world_id: currentWorldId,
                episode_number: ep,
            });
            if (scriptId) params.set('script_id', scriptId);
            if (USER_ID) params.set('user_id', USER_ID);
            if (WORKFLOW_ID) params.set('workflow_id', WORKFLOW_ID);
            // 注意：不再把 auth_token 放到 URL 中（避免敏感信息暴露），storyboard 会从 localStorage 读取（参考本文件实现）
            window.location.href = `/storyboard?${params.toString()}`;
        }


        function switchFileTab(fileType, evt) {
            currentFileType = fileType;
            document.querySelectorAll('.tab-btn').forEach(tab => tab.classList.remove('active'));
            var target = (evt || event).target;
            if (target) target.closest('.tab-btn').classList.add('active');
            // 新建按钮：世界标签页不显示，其他都显示
            const addBtn = document.getElementById('add-file-btn');
            if (addBtn) {
                if (fileType === 'worlds') {
                    addBtn.style.display = 'none';
                } else {
                    addBtn.style.display = 'flex';
                    const addBtnConfig = {
                        'scripts': { onclick: 'showNewScriptModal()', title: '新建剧本' },
                        'characters': { onclick: 'showNewCharacterModal()', title: '新建角色' },
                        'locations': { onclick: 'showNewLocationModal()', title: '新建场景' },
                        'props': { onclick: 'showNewPropModal()', title: '新建道具' }
                    };
                    const cfg = addBtnConfig[fileType];
                    if (cfg) {
                        addBtn.setAttribute('onclick', cfg.onclick);
                        addBtn.title = cfg.title;
                    }
                }
            }
            loadFiles(fileType);
        }

        async function exportWorld() {
            try {
                updateStatus(window.t ? window.t('status_packing_world') : '正在打包并上传世界数据...');
                const response = await fetch(`/api/export-world?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}`);
                const result = await response.json().catch(() => ({}));
                if (!response.ok) {
                    showError((window.t ? window.t('error_export_failed', {error: result.error || response.statusText}) : '导出失败: ' + (result.error || response.statusText)));
                    updateStatus(window.t ? window.t('status_export_failed') : '导出失败');
                    return;
                }
                if (!result.success || !result.download_url) {
                    showError((window.t ? window.t('error_export_failed', {error: result.error || (window.t ? window.t('error_no_download_link') : '未获取到下载链接')}) : '导出失败: ' + (result.error || '未获取到下载链接')));
                    updateStatus(window.t ? window.t('status_export_failed') : '导出失败');
                    return;
                }
                const a = document.createElement('a');
                a.href = result.download_url;
                a.download = result.filename || `world_export_${WORLD_ID}_${new Date().toISOString().slice(0,19).replace(/[-T:]/g, '')}.zip`;
                a.target = '_blank';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                showSuccess(window.t ? window.t('success_world_exported') : '✓ 世界数据导出成功，已生成下载链接');
                updateStatus(window.t ? window.t('status_export_done') : '导出完成，可通过图床链接下载');
            } catch (error) {
                showError((window.t ? window.t('error_export_failed', {error: error.message}) : '导出失败: ' + error.message));
                updateStatus(window.t ? window.t('status_export_failed') : '导出失败');
            }
        }

        function triggerImportWorld() {
            document.getElementById('import-world-file').click();
        }

        async function importWorldFromFile(file) {
            if (!file) return;
            if (!file.name.endsWith('.zip')) {
                showError(window.t ? window.t('error_zip_only') : '请选择 .zip 格式的文件');
                return;
            }
            if (!confirm(window.t ? window.t('confirm_import_world', {name: file.name}) : `确定要导入 "${file.name}" 吗？\n\n导入会覆盖当前世界的同名数据，请确认。`)) {
                return;
            }
            try {
                // 大文件链路：前端直传七牛 → 后端限速下载 → 后台解包 → 轮询
                updateStatus(window.t ? window.t('status_importing_world') : '正在导入世界数据...');
                showWorldImportProgress(window.t ? window.t('world_import_stage_uploading') : '上传中…', 0);

                // 1) 颁发上传 token
                const tokenResp = await fetch(`/api/world-upload-token?auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: new URLSearchParams({
                        world_id: WORLD_ID,
                        filename: file.name,
                        size: String(file.size),
                    })
                });
                const tokenData = await tokenResp.json().catch(() => ({}));
                if (!tokenResp.ok || !tokenData.success) {
                    throw new Error(tokenData.error || tokenResp.statusText || '获取上传凭证失败');
                }

                // 2) 前端直传七牛（XHR 带 upload.onprogress）
                const key = await uploadWorldZipToQiniu(
                    tokenData.upload_url,
                    tokenData.token,
                    tokenData.key,
                    file
                );

                // 3) 触发后端导入（立即返回 job_id）
                const importResp = await fetch(`/api/import-world-from-cloud?auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: new URLSearchParams({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        key: key,
                    })
                });
                const importData = await importResp.json().catch(() => ({}));
                if (importResp.status === 429) {
                    throw new Error(importData.error || '当前导入任务过多，请稍后再试');
                }
                if (!importResp.ok || !importData.success) {
                    throw new Error(importData.error || importResp.statusText || '创建导入任务失败');
                }

                // 4) 轮询任务进度
                const result = await pollWorldImportStatus(importData.job_id);
                showSuccess('✓ ' + (result.message || (window.t ? window.t('status_import_done') : '导入完成')));
                updateStatus(window.t ? window.t('status_import_done') : '导入完成');
                await loadFiles(currentFileType);
            } catch (error) {
                showError((window.t ? window.t('error_import_failed', {error: error.message}) : '导入失败: ' + error.message));
                updateStatus(window.t ? window.t('status_import_failed') : '导入失败');
            } finally {
                hideWorldImportProgress();
            }
        }

        /**
         * 前端直传七牛云（带进度回调）。返回上传后的 key。
         * 用 XHR 而非 fetch，因为需要 xhr.upload.onprogress。
         */
        function uploadWorldZipToQiniu(uploadUrl, token, key, file) {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', uploadUrl, true);
                xhr.responseType = 'json';

                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        const pct = Math.round(e.loaded * 100 / e.total);
                        showWorldImportProgress(
                            window.t ? window.t('world_import_stage_uploading') : '上传中…',
                            pct
                        );
                    }
                };

                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        // 七牛 form 上传成功响应体：{"key":"...","hash":"..."}（取决于 token returnBody）
                        // key 以我们传入的为准
                        resolve(key);
                    } else {
                        let detail = '';
                        try { detail = JSON.stringify(xhr.response || xhr.responseText); } catch (_) { detail = xhr.responseText || ''; }
                        reject(new Error(`上传到云端失败 (HTTP ${xhr.status}): ${detail}`));
                    }
                };

                xhr.onerror = () => reject(new Error('上传到云端失败：网络错误'));
                xhr.ontimeout = () => reject(new Error('上传到云端超时'));

                const formData = new FormData();
                formData.append('token', token);
                formData.append('key', key);
                formData.append('file', file);
                xhr.send(formData);
            });
        }

        /** 轮询后端导入任务状态直到 done/failed */
        async function pollWorldImportStatus(jobId) {
            const stageI18n = {
                downloading: window.t ? window.t('world_import_stage_downloading') : '云端下载中…',
                unpacking: window.t ? window.t('world_import_stage_unpacking') : '解包导入中…',
                done: window.t ? window.t('world_import_stage_done') : '导入完成',
                pending: window.t ? window.t('world_import_stage_pending') : '排队中…',
                failed: window.t ? window.t('world_import_stage_failed') : '导入失败',
            };
            while (true) {
                await new Promise(r => setTimeout(r, 1500));
                let resp;
                try {
                    resp = await fetch(`/api/world-import-status?job_id=${encodeURIComponent(jobId)}&auth_token=${AUTH_TOKEN}`);
                } catch (e) {
                    // 网络抖动：继续重试
                    continue;
                }
                if (resp.status === 404) {
                    // 任务丢失（进程重启等），让用户重试
                    throw new Error('导入任务已丢失（服务可能重启过），请重试');
                }
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || '查询导入状态失败');
                }
                const stageLabel = stageI18n[data.stage] || data.stage || '';
                showWorldImportProgress(stageLabel, data.progress || 0, data.status);
                if (data.status === 'done') {
                    return data;
                }
                if (data.status === 'failed') {
                    throw new Error(data.error || '导入失败');
                }
            }
        }

        /** 显示/更新导入进度条。status 可选：done/failed 用于变色 */
        function showWorldImportProgress(stageText, pct, status) {
            const box = document.getElementById('worldImportProgress');
            const stageEl = document.getElementById('worldImportProgressStage');
            const pctEl = document.getElementById('worldImportProgressPct');
            const fillEl = document.getElementById('worldImportProgressFill');
            if (!box) return;
            box.hidden = false;
            if (stageText !== undefined) stageEl.textContent = stageText;
            const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
            pctEl.textContent = p + '%';
            fillEl.style.width = p + '%';
            box.classList.toggle('done', status === 'done');
            box.classList.toggle('error', status === 'failed');
        }

        function hideWorldImportProgress() {
            const box = document.getElementById('worldImportProgress');
            if (!box) return;
            // 延迟隐藏，让用户看到完成/失败状态
            setTimeout(() => {
                box.hidden = true;
                box.classList.remove('done', 'error');
            }, 1500);
        }

        function handleImportWorld(event) {
            const fileInput = event.target;
            const file = fileInput.files[0];
            importWorldFromFile(file).finally(() => {
                fileInput.value = '';
            });
        }

        function initImportDropZone() {
            const dropZone = document.getElementById('importDropZone');
            if (!dropZone) return;

            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                }, false);
            });

            ['dragenter', 'dragover'].forEach(eventName => {
                dropZone.addEventListener(eventName, () => {
                    dropZone.classList.add('drag-over');
                }, false);
            });

            ['dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => {
                    // dragleave 仅在真正离开 dropZone 时移除高亮，避免进入子元素时闪烁
                    if (eventName === 'dragleave' && dropZone.contains(e.relatedTarget)) {
                        return;
                    }
                    dropZone.classList.remove('drag-over');
                }, false);
            });

            dropZone.addEventListener('drop', (e) => {
                const file = e.dataTransfer.files[0];
                importWorldFromFile(file);
            }, false);
        }

        async function loadFiles(fileType) {
            const fileItemsContainer = document.getElementById('file-items-container');
            try {
                const apiMap = {
                    'worlds': '/api/world-files',
                    'characters': '/api/characters-files',
                    'scripts': '/api/scripts-files',
                    'locations': '/api/locations-files',
                    'props': '/api/props-files'
                };

                // 添加 raw_json=true 参数以获取完整的JSON数据（包括reference_image）
                const response = await fetch(`${apiMap[fileType]}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();

                if (checkTokenExpired(data, response)) {
                    return;
                }

                // 兼容两种返回格式: {success, xxx:[]} 和 {code:0, data:{data:[]}}
                const isSuccess = data.success || data.code === 0;
                if (isSuccess) {
                    // 优先从 data.data.data 获取（server.py格式），否则从对应字段获取（script_writer_api格式）
                    let files = data.data?.data || data.worlds || data.characters || data.scripts || data.locations || data.props || [];

                    // 对于世界文件，只显示当前世界的文件
                    if (fileType === 'worlds') {
                        files = files.filter(file => file.name === `world_${WORLD_ID}.json`);
                        // 如果没有世界文件，创建一个虚拟的世界文件条目
                        if (files.length === 0) {
                            files = [{ name: `world_${WORLD_ID}.json`, exists: false }];
                        }
                    }
                    if (fileType === 'scripts') {
                        files = files.sort((a, b) => {
                            const episodeA = parseInt(a.episode_number) || 0;
                            const episodeB = parseInt(b.episode_number) || 0;
                            return episodeA - episodeB;
                        });
                    }

                    if (files.length === 0) {
                        fileItemsContainer.innerHTML = '<div class="file-empty">暂无文件</div>';
                        return;
                    }

                    fileItemsContainer.innerHTML = '';
                    files.forEach(file => {
                        const fileItem = document.createElement('div');
                        fileItem.className = 'file-item';
                        
                        // 对于角色、场景、道具、剧本，添加图片预览图标和删除按钮
                        let imageIconHtml = '';
                        let voiceIconHtml = '';
                        let deleteButtonHtml = '';
                        let storyboardButtonHtml = '';
                        
                        // 角色、场景、道具显示图片预览图标
                        if (['characters', 'locations', 'props'].includes(fileType)) {
                            // reference_image 在 json_data 对象里
                            const referenceImage = file.json_data?.reference_image || file.reference_image;
                            const hasImage = referenceImage && referenceImage.trim() !== '';
                            const iconClass = hasImage ? 'has-image' : 'no-image';
                            const iconTitle = hasImage ? '预览图片' : '暂无参考图';
                            imageIconHtml = `
                                <button class="file-btn image-preview-btn ${iconClass}" data-action="preview-image" data-file-type="${escapeHtmlAttr(fileType)}" data-file-name="${escapeHtmlAttr(file.name || '')}" title="${iconTitle}">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                                        <circle cx="8.5" cy="8.5" r="1.5"/>
                                        <polyline points="21 15 16 10 5 21"/>
                                    </svg>
                                </button>
                            `;
                        }
                        
                        // 角色显示音色播放按钮
                        if (fileType === 'characters') {
                            const defaultVoice = file.json_data?.default_voice || '';
                            const hasVoice = defaultVoice && defaultVoice.trim() !== '';
                            const voiceClass = hasVoice ? 'has-voice' : 'no-voice';
                            const voiceTitle = hasVoice ? '播放音色' : '暂无音色';
                            const voiceDisabled = hasVoice ? '' : 'disabled';
                            const voiceDataAttr = hasVoice ? `data-action="play-voice" data-file-name="${escapeHtmlAttr(file.name || '')}"` : 'data-action="play-voice"';
                            voiceIconHtml = `
                                <button class="file-btn voice-play-btn ${voiceClass}" ${voiceDataAttr} title="${voiceTitle}" ${voiceDisabled}>
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                                        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                                        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
                                    </svg>
                                </button>
                            `;
                        }
                        
                        // 角色、场景、道具、剧本都显示删除按钮
                        if (['characters', 'locations', 'props', 'scripts'].includes(fileType)) {
                            // 从 file_path 提取相对路径（script_writer 之后的部分）
                            let relativePath = '';
                            if (file.file_path) {
                                // 兼容 Windows 反斜杠和 Unix 正斜杠
                                const normalizedPath = file.file_path.replace(/\\/g, '/');
                                const pathMatch = normalizedPath.match(/script_writer\/(.*)/)
                                if (pathMatch) {
                                    relativePath = pathMatch[1];
                                } else {
                                    // fallback: 从文件名构造完整路径（包含前缀和扩展名）
                                    const fileName = file.file_path.split(/[/\\]/).pop();
                                    relativePath = `${USER_ID}/${WORLD_ID}/${fileType}/${fileName}`;
                                }
                            } else {
                                // 如果没有 file_path，构造默认路径
                                relativePath = `${USER_ID}/${WORLD_ID}/${fileType}/${file.name}`;
                            }
                            // 转义路径中的特殊字符
                            deleteButtonHtml = `
                                <button class="file-btn delete-btn" data-action="delete" data-file-path="${escapeHtmlAttr(relativePath)}" title="删除" data-i18n-title="title_delete">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <polyline points="3 6 5 6 21 6"/>
                                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                        <line x1="10" y1="11" x2="10" y2="17"/>
                                        <line x1="14" y1="11" x2="14" y2="17"/>
                                    </svg>
                                </button>
                            `;
                        }
                        
                        if (fileType === 'scripts') {
                            storyboardButtonHtml = `
                                <button class="file-btn storyboard-btn" data-action="open-storyboard" data-script-id="${escapeHtmlAttr(file.id || file.script_id || '')}" data-episode-number="${escapeHtmlAttr(getScriptEpisodeNumber(file))}" title="打开故事板">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="3" y="4" width="18" height="16" rx="2"/>
                                        <path d="M8 4v16M3 9h18M3 15h18"/>
                                    </svg>
                                </button>
                            `;
                        }

                        // 剧本使用 display_name 展示，其他类型使用 name
                        const displayName = (fileType === 'scripts' && file.display_name) ? file.display_name : file.name;
                        // 剧本使用 file_name 作为 API 键，其他类型使用 name
                        const fileKey = (fileType === 'scripts' && file.file_name) ? file.file_name : file.name;

                        fileItem.innerHTML = `
                            <div class="file-name">${escapeHtml(displayName)}</div>
                            <div class="file-actions">
                                ${imageIconHtml}
                                ${voiceIconHtml}
                                ${storyboardButtonHtml}
                                ${deleteButtonHtml}
                                <button class="file-btn view-btn" data-action="view" data-file-type="${escapeHtmlAttr(fileType)}" data-file-key="${escapeHtmlAttr(fileKey)}" title="查看" data-i18n-title="title_view">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                        <circle cx="12" cy="12" r="3"/>
                                    </svg>
                                </button>
                                <button class="file-btn edit-btn" data-action="edit" data-file-type="${escapeHtmlAttr(fileType)}" data-file-key="${escapeHtmlAttr(fileKey)}" title="编辑" data-i18n-title="title_edit">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                                    </svg>
                                </button>
                            </div>
                        `;
                        fileItemsContainer.appendChild(fileItem);
                    });

                    // Event delegation for file action buttons (replaces inline onclick for XSS safety)
                    if (!fileItemsContainer._delegationBound) {
                        fileItemsContainer._delegationBound = true;
                        fileItemsContainer.addEventListener('click', function(e) {
                            var btn = e.target.closest('[data-action]');
                            if (!btn) return;
                            var action = btn.dataset.action;
                            if (action === 'preview-image') {
                                previewItemImage(btn.dataset.fileType, btn.dataset.fileName);
                            } else if (action === 'play-voice') {
                                if (!btn.disabled) playCharacterVoice(btn.dataset.fileName);
                            } else if (action === 'delete') {
                                deleteStagingFile(btn.dataset.filePath);
                            } else if (action === 'open-storyboard') {
                                openStoryboardFromScript(btn.dataset.scriptId, btn.dataset.episodeNumber);
                            } else if (action === 'view') {
                                viewFile(btn.dataset.fileType, btn.dataset.fileKey);
                            } else if (action === 'edit') {
                                editFile(btn.dataset.fileType, btn.dataset.fileKey);
                            }
                        });
                    }
                } else {
                    fileItemsContainer.innerHTML = '<div class="file-empty">加载失败</div>';
                }
            } catch (error) {
                fileItemsContainer.innerHTML = '<div class="file-empty">加载失败</div>';
            }
        }

        async function viewFile(fileType, fileName) {
            try {
                const apiMap = {
                    'worlds': '/api/world-files',
                    'characters': '/api/characters-files',
                    'scripts': '/api/scripts-files',
                    'locations': '/api/locations-files',
                    'props': '/api/props-files'
                };
                
                const response = await fetch(`${apiMap[fileType]}/${encodeURIComponent(fileName)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                if (data.success) {
                    document.querySelectorAll('.view-form').forEach(form => form.style.display = 'none');
                    
                    let jsonData = data.world?.json_data || data.character?.json_data || data.location?.json_data || data.prop?.json_data || data.script?.json_data || {};
                    
                    if (!jsonData || Object.keys(jsonData).length === 0) {
                        const content = data.world?.content || data.character?.content || data.script?.content || data.location?.content || data.prop?.content || data.content || '';
                        try {
                            if (content.trim()) {
                                jsonData = JSON.parse(content);
                            } else {
                                jsonData = {};
                            }
                        } catch (e) {
                            showTextViewer(fileName, content);
                            document.getElementById('view-modal').classList.add('show');
                            return;
                        }
                    }
                    
                    if (fileType === 'worlds') {
                        showWorldViewer(fileName, jsonData);
                    } else if (fileType === 'characters') {
                        showCharacterViewer(fileName, jsonData);
                    } else if (fileType === 'locations') {
                        showLocationViewer(fileName, jsonData);
                    } else if (fileType === 'props') {
                        showPropViewer(fileName, jsonData);
                    } else if (fileType === 'scripts') {
                        showScriptViewer(fileName, jsonData);
                    } else {
                        const content = data.character?.content || data.script?.content || data.content || '';
                        showTextViewer(fileName, content);
                    }
                    
                    document.getElementById('view-modal').classList.add('show');
                } else {
                    showError((window.t ? window.t('error_view_file_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '查看文件失败: ' + (data.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_view_file_failed', {error: error.message}) : '查看文件失败: ' + error.message));
            }
        }

        function showWorldViewer(fileName, data) {
            data.story_type = normalizeStoryType(data.story_type);
            document.getElementById('view-modal-title').textContent = `🌍 查看世界 - ${fileName}`;
            document.getElementById('world-view-form').style.display = 'block';
            document.getElementById('view-world-name').textContent = data.name || '未设置';
            document.getElementById('view-world-user-id').textContent = data.user_id || '未设置';
            document.getElementById('world-story-type-view').textContent = getStoryTypeLabel(data.story_type);
            document.getElementById('view-world-description').textContent = data.description || '未设置';
            document.getElementById('view-world-story-outline').textContent = data.story_outline || '未设置';
            document.getElementById('view-world-visual-style').textContent = data.visual_style || '未设置';
            document.getElementById('view-world-era-environment').textContent = data.era_environment || '未设置';
            document.getElementById('view-world-color-language').textContent = data.color_language || '未设置';
            document.getElementById('view-world-composition-preference').textContent = data.composition_preference || '未设置';
            document.getElementById('view-world-created').textContent = data.create_time || '未设置';
            document.getElementById('view-world-updated').textContent = data.update_time || '未设置';
        }

        function showCharacterViewer(fileName, data) {
            document.getElementById('view-modal-title').textContent = `👤 查看角色 - ${fileName}`;
            document.getElementById('character-view-form').style.display = 'block';
            document.getElementById('view-char-name').textContent = data.name || '未设置';
            document.getElementById('view-char-age').textContent = data.age || '未设置';
            document.getElementById('view-char-identity').textContent = data.identity || '未设置';
            document.getElementById('view-char-appearance').textContent = data.appearance || '未设置';
            document.getElementById('view-char-personality').textContent = data.personality || '未设置';
            document.getElementById('view-char-behavior').textContent = data.behavior || '未设置';
            document.getElementById('view-char-other').textContent = data.other_info || '未设置';
            
            const imageContainer = document.getElementById('view-char-image-container');
            displayImage(imageContainer, data.reference_image);
        }

        function showLocationViewer(fileName, data) {
            document.getElementById('view-modal-title').textContent = `🏛️ 查看场景 - ${fileName}`;
            document.getElementById('location-view-form').style.display = 'block';
            document.getElementById('view-loc-name').textContent = data.name || '未设置';
            const parentLabel = resolveParentName(data) || '无';
            document.getElementById('view-loc-parent').textContent = parentLabel;
            document.getElementById('view-loc-description').textContent = data.description || '未设置';
            
            const imageContainer = document.getElementById('view-loc-image-container');
            displayImage(imageContainer, data.reference_image);
        }

        // ==================== 场景父级（仅顶级可选） ====================
        /** 缓存本世界场景 JSON 列表：[{name, parent_name, parent_id, ...}] */
        let cachedLocationJsonList = [];

        /** 无父引用 = 顶级（未落库只看文件字段，不查 DB） */
        function isTopLevelLocation(locJson) {
            if (!locJson || typeof locJson !== 'object') return true;
            const parentName = String(locJson.parent_name ?? '').trim();
            if (parentName) return false;
            const pid = locJson.parent_id;
            if (pid === null || pid === undefined || pid === '') return true;
            return false;
        }

        /**
         * 解析父场景名称（兼容 parent_name / 数字 parent_id / 名称字符串 parent_id）
         * @param {object} locJson
         * @param {Array} [allLocs]
         */
        function resolveParentName(locJson, allLocs) {
            if (!locJson || typeof locJson !== 'object') return null;
            const pn = String(locJson.parent_name ?? '').trim();
            if (pn) return pn;
            const pid = locJson.parent_id;
            if (pid === null || pid === undefined || pid === '') return null;
            const pidStr = String(pid).trim();
            if (!pidStr) return null;
            // 纯数字：尝试在列表中用 id 反查 name（历史同步残留）
            if (/^\d+$/.test(pidStr) && Array.isArray(allLocs)) {
                const byId = allLocs.find((l) => String(l.id) === pidStr || String(l.db_id) === pidStr);
                if (byId && byId.name) return String(byId.name).trim();
            }
            // 非纯数字或反查失败：当作名称
            if (!/^\d+$/.test(pidStr)) return pidStr;
            return pidStr;
        }

        /** 拉取本世界场景 JSON 列表（含 json_data） */
        async function fetchLocationJsonList() {
            try {
                const response = await fetch(
                    `/api/locations-files?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`
                );
                const data = await response.json();
                const locs = data.locations || data.data?.data || [];
                cachedLocationJsonList = locs.map((l) => {
                    const jd = l.json_data && typeof l.json_data === 'object' ? l.json_data : l;
                    return {
                        name: jd.name || l.name || '',
                        parent_name: jd.parent_name ?? null,
                        parent_id: jd.parent_id ?? null,
                        id: jd.id ?? null,
                        ...jd,
                    };
                }).filter((l) => l.name);
                return cachedLocationJsonList;
            } catch (e) {
                console.warn('获取场景列表失败:', e);
                cachedLocationJsonList = [];
                return [];
            }
        }

        /**
         * 填充父级场景下拉：仅顶级场景
         * @param {HTMLSelectElement} selectEl
         * @param {{ excludeName?: string, selectedParentName?: string|null }} [opts]
         */
        async function loadTopLevelParentOptions(selectEl, opts = {}) {
            if (!selectEl) return;
            const excludeName = (opts.excludeName || '').trim();
            const selectedParentName = (opts.selectedParentName || '').trim();
            const list = await fetchLocationJsonList();
            const tops = list.filter((l) => isTopLevelLocation(l) && l.name !== excludeName);

            selectEl.innerHTML = '';
            const emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = '无（顶层场景）';
            selectEl.appendChild(emptyOpt);

            tops.forEach((loc) => {
                const opt = document.createElement('option');
                opt.value = loc.name;
                opt.textContent = loc.name;
                if (selectedParentName && loc.name === selectedParentName) {
                    opt.selected = true;
                }
                selectEl.appendChild(opt);
            });

            // 历史父级已非顶级或已删除：保留可见但禁用，避免静默丢失
            if (selectedParentName && !tops.some((t) => t.name === selectedParentName)) {
                const stale = document.createElement('option');
                stale.value = selectedParentName;
                stale.textContent = `${selectedParentName}（已非顶级或已删除，请重选）`;
                stale.disabled = true;
                stale.selected = true;
                selectEl.appendChild(stale);
            }
        }

        function showPropViewer(fileName, data) {
            document.getElementById('view-modal-title').textContent = `🎁 查看道具 - ${fileName}`;
            document.getElementById('prop-view-form').style.display = 'block';
            document.getElementById('view-prop-name').textContent = data.name || '未设置';
            document.getElementById('view-prop-type').textContent = data.type || '未设置';
            document.getElementById('view-prop-description').textContent = data.description || '未设置';
            
            const imageContainer = document.getElementById('view-prop-image-container');
            displayImage(imageContainer, data.reference_image);
        }

        function showScriptViewer(fileName, data) {
            const epLabel = data.episode_number ? `第${data.episode_number}集：` : '';
            document.getElementById('view-modal-title').textContent = `📜 查看剧本 - ${epLabel}${data.title || fileName}`;
            document.getElementById('script-view-form').style.display = 'block';
            document.getElementById('view-script-title').textContent = data.title || '未设置';
            document.getElementById('view-script-episode').textContent = data.episode_number || '未设置';
            document.getElementById('view-script-content').textContent = data.content || '未设置';
            document.getElementById('view-script-created').textContent = data.create_time || '未设置';
            document.getElementById('view-script-updated').textContent = data.update_time || '未设置';
        }

        function showTextViewer(fileName, content) {
            document.getElementById('view-modal-title').textContent = `📄 ${fileName}`;
            document.getElementById('text-view-form').style.display = 'block';
            document.getElementById('view-modal-content').textContent = content;
        }

        function displayImage(container, imageUrl) {
            container.innerHTML = '';
            
            if (!imageUrl || imageUrl.trim() === '') {
                container.innerHTML = '<div class="view-field">未设置</div>';
                return;
            }
            
            if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://') || imageUrl.startsWith('/')) {
                const img = document.createElement('img');
                img.src = imageUrl;
                img.className = 'preview-image';
                img.alt = '参考图片';
                img.onerror = function() {
                    container.innerHTML = `<div class="view-field">图片加载失败<br><small>${escapeHtml(imageUrl)}</small></div>`;
                };
                container.appendChild(img);
            } else {
                container.innerHTML = `<div class="view-field">${escapeHtml(imageUrl)}</div>`;
            }
        }

        function closeViewModal() {
            document.getElementById('view-modal').classList.remove('show');
        }

        // 剧本全屏查看
        let _fullscreenFontSize = 14;
        let _fullscreenEditMode = false;

        function openScriptFullscreen() {
            _fullscreenEditMode = false;
            const content = document.getElementById('view-script-content').textContent || '';
            const title = document.getElementById('view-modal-title').textContent || '📜 剧本内容';
            document.getElementById('fullscreen-title').textContent = title;
            document.getElementById('fullscreen-script-content').textContent = content;
            document.getElementById('fullscreen-script-content').style.display = '';
            document.getElementById('fullscreen-script-textarea').style.display = 'none';
            _fullscreenFontSize = 14;
            updateFullscreenFontSize();
            document.getElementById('script-fullscreen-overlay').classList.add('show');
            document.addEventListener('keydown', _fullscreenKeyHandler);
        }

        function openScriptFullscreenFromEdit() {
            _fullscreenEditMode = true;
            const content = document.getElementById('script-content').value || '';
            const title = document.getElementById('script-title').value || '剧本内容';
            document.getElementById('fullscreen-title').textContent = '📜 ' + title;
            document.getElementById('fullscreen-script-textarea').value = content;
            document.getElementById('fullscreen-script-content').style.display = 'none';
            document.getElementById('fullscreen-script-textarea').style.display = '';
            _fullscreenFontSize = 14;
            updateFullscreenFontSize();
            document.getElementById('script-fullscreen-overlay').classList.add('show');
            document.getElementById('fullscreen-script-textarea').focus();
            document.addEventListener('keydown', _fullscreenKeyHandler);
        }

        function closeScriptFullscreen() {
            if (_fullscreenEditMode) {
                const edited = document.getElementById('fullscreen-script-textarea').value || '';
                document.getElementById('script-content').value = edited;
            }
            document.getElementById('script-fullscreen-overlay').classList.remove('show');
            document.removeEventListener('keydown', _fullscreenKeyHandler);
        }

        function _fullscreenKeyHandler(e) {
            if (e.key === 'Escape') closeScriptFullscreen();
        }

        function changeFullscreenFontSize(delta) {
            _fullscreenFontSize = Math.max(12, Math.min(32, _fullscreenFontSize + delta));
            updateFullscreenFontSize();
        }

        function updateFullscreenFontSize() {
            document.getElementById('fullscreen-script-content').style.fontSize = _fullscreenFontSize + 'px';
            document.getElementById('fullscreen-script-textarea').style.fontSize = _fullscreenFontSize + 'px';
            document.getElementById('fullscreen-font-size').textContent = _fullscreenFontSize + 'px';
        }

        async function editFile(fileType, fileName) {
            try {
                const apiMap = {
                    'worlds': '/api/world-files',
                    'characters': '/api/characters-files',
                    'scripts': '/api/scripts-files',
                    'locations': '/api/locations-files',
                    'props': '/api/props-files'
                };
                
                const response = await fetch(`${apiMap[fileType]}/${encodeURIComponent(fileName)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();
                
                if (checkTokenExpired(data, response)) {
                    return;
                }
                
                if (data.success) {
                    currentEditFile.fileType = fileType;
                    currentEditFile.fileName = fileName;
                    
                    document.querySelectorAll('.edit-form').forEach(form => form.style.display = 'none');
                    
                    let jsonData = data.world?.json_data || data.character?.json_data || data.location?.json_data || data.prop?.json_data || data.script?.json_data || {};
                    
                    if (!jsonData || Object.keys(jsonData).length === 0) {
                        const content = data.world?.content || data.character?.content || data.script?.content || data.location?.content || data.prop?.content || data.content || '';
                        try {
                            if (content.trim()) {
                                jsonData = JSON.parse(content);
                            } else {
                                jsonData = {};
                            }
                        } catch (e) {
                            showTextEditor(fileName, content);
                            document.getElementById('edit-modal').classList.add('show');
                            return;
                        }
                    }
                    
                    if (fileType === 'worlds') {
                        showWorldEditor(fileName, jsonData);
                    } else if (fileType === 'characters') {
                        showCharacterEditor(fileName, jsonData);
                    } else if (fileType === 'locations') {
                        showLocationEditor(fileName, jsonData);
                    } else if (fileType === 'props') {
                        showPropEditor(fileName, jsonData);
                    } else if (fileType === 'scripts') {
                        showScriptEditor(fileName, jsonData);
                    } else {
                        showTextEditor(fileName, content);
                    }
                    
                    document.getElementById('edit-modal').classList.add('show');
                } else {
                    showError((window.t ? window.t('error_read_file_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '读取文件失败: ' + (data.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_edit_file_failed', {error: error.message}) : '编辑文件失败: ' + error.message));
            }
        }

        function showCharacterEditor(fileName, data) {
            document.getElementById('edit-modal-title').textContent = `✏️ 编辑角色 - ${fileName}`;
            document.getElementById('character-edit-form').style.display = 'block';
            document.getElementById('char-name').value = data.name || '';
            document.getElementById('char-age').value = data.age || '';
            document.getElementById('char-identity').value = data.identity || '';
            document.getElementById('char-appearance').value = data.appearance || '';
            document.getElementById('char-personality').value = data.personality || '';
            document.getElementById('char-behavior').value = data.behavior || '';
            document.getElementById('char-other').value = data.other_info || '';
            document.getElementById('char-default-voice').value = data.default_voice || '';
            document.getElementById('char-image').value = data.reference_image || '';

            showCharacterDefaultVoicePreview(data.default_voice || '');

            // 如果有图片，显示预览
            if (data.reference_image) {
                showImagePreview('char-image', data.reference_image);
            } else {
                removeImagePreview('char-image');
            }

            // 填充多服装参考图
            const multiImageList = document.getElementById('char-multi-image-list');
            multiImageList.innerHTML = '';
            if (data.reference_images && Array.isArray(data.reference_images)) {
                data.reference_images.forEach(img => {
                    addCharMultiImageItem(multiImageList, img.label || '服装', img.url, img.id);
                });
            }
        }

        function showCharacterDefaultVoicePreview(audioUrl) {
            const preview = document.getElementById('char-default-voice-preview');
            const audio = preview.querySelector('audio');
            if (!audioUrl) {
                preview.style.display = 'none';
                audio.removeAttribute('src');
                return;
            }
            audio.src = audioUrl;
            preview.style.display = 'block';
        }

        function clearCharacterDefaultVoice() {
            document.getElementById('char-default-voice').value = '';
            showCharacterDefaultVoicePreview('');
        }

        function triggerCharacterVoiceUpload() {
            const fileInput = document.getElementById('char-voice-file');
            fileInput.click();
        }

        async function handleCharacterVoiceUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            const allowedExtensions = ['.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.wma'];
            const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
            if (!allowedExtensions.includes(fileExtension)) {
                showError(window.t ? window.t('error_select_audio_file') : '请选择支持的音频格式文件');
                event.target.value = '';
                return;
            }

            const maxSize = 20 * 1024 * 1024;
            if (file.size > maxSize) {
                showError(window.t ? window.t('error_audio_too_large') : '音频大小不能超过20MB');
                event.target.value = '';
                return;
            }

            showInfo('正在上传音频...');

            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', USER_ID);
            formData.append('world_id', WORLD_ID);
            formData.append('auth_token', AUTH_TOKEN);

            try {
                const response = await fetch('/api/upload-character-audio', {
                    method: 'POST',
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: formData
                });

                const data = await response.json();
                if (data.success) {
                    document.getElementById('char-default-voice').value = data.url;
                    showCharacterDefaultVoicePreview(data.url);
                    showSuccess(window.t ? window.t('success_audio_uploaded') : '音频上传成功');
                } else {
                    showError((window.t ? window.t('error_upload_failed', {error: data.error}) : '上传失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_upload_failed', {error: error.message}) : '上传失败: ' + error.message));
            }

            event.target.value = '';
        }

        async function generateCharacterReferenceAudio() {
            if (!currentEditFile || currentEditFile.fileType !== 'characters') {
                showError(window.t ? window.t('error_open_character_first') : '请先打开一个角色进行编辑');
                return;
            }
            const characterName = document.getElementById('char-name').value.trim();
            if (!characterName) {
                showError(window.t ? window.t('error_character_name_required') : '角色名称不能为空');
                return;
            }
            const btn = document.getElementById('generate-character-voice-btn');
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '生成中...';
            try {
                updateStatus(window.t ? window.t('status_generating_audio') : '正在生成角色参考音频...');
                // 获取当前选择的 LLM 模型信息
                const modelSelector = document.getElementById('model-selector');
                const selectedModelOption = modelSelector?.options[modelSelector.selectedIndex];
                const response = await fetch('/api/script-writer/characters/reference-audio', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: parseInt(WORLD_ID),
                        character_name: characterName,
                        character_data: JSON.parse(collectCharacterData()),
                        model: modelSelector?.value || '',
                        model_id: selectedModelOption?.dataset?.modelId ? parseInt(selectedModelOption.dataset.modelId) : null,
                        vendor_id: selectedModelOption?.dataset?.vendorId ? parseInt(selectedModelOption.dataset.vendorId) : null
                    })
                });
                const data = await response.json();
                if (checkTokenExpired(data, response)) {
                    return;
                }
                if (!data.success) {
                    throw new Error(data.error || '生成失败');
                }
                document.getElementById('char-default-voice').value = data.default_voice || data.result_url || '';
                showCharacterDefaultVoicePreview(data.default_voice || data.result_url || '');
                await saveEditedFile();
                showSuccess(window.t ? window.t('success_audio_generated') : '角色参考音频生成成功');
                updateStatus(window.t ? window.t('status_audio_generated') : '角色参考音频已生成');
            } catch (error) {
                showError((window.t ? window.t('error_generate_audio_failed', {error: error.message}) : '生成参考音频失败: ' + error.message));
                updateStatus(window.t ? window.t('status_audio_failed') : '生成参考音频失败');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        async function showLocationEditor(fileName, data) {
            document.getElementById('edit-modal-title').textContent = `✏️ 编辑场景 - ${fileName}`;
            document.getElementById('location-edit-form').style.display = 'block';
            document.getElementById('loc-name').value = data.name || '';
            document.getElementById('loc-description').value = data.description || '';
            document.getElementById('loc-image').value = data.reference_image || '';

            const parentSelect = document.getElementById('loc-parent');
            const selectedParent = resolveParentName(data, cachedLocationJsonList);
            await loadTopLevelParentOptions(parentSelect, {
                excludeName: data.name || '',
                selectedParentName: selectedParent,
            });

            // 如果有图片，显示预览
            if (data.reference_image) {
                showImagePreview('loc-image', data.reference_image);
            } else {
                removeImagePreview('loc-image');
            }

            // 填充多角度参考图
            const multiImageList = document.getElementById('loc-multi-image-list');
            multiImageList.innerHTML = '';
            if (data.reference_images && Array.isArray(data.reference_images)) {
                data.reference_images.forEach(img => {
                    addLocMultiImageItem(multiImageList, img.label || img.angle || '正面', img.url, img.angle || 'front', img.id);
                });
            }

            // 如果切换到的场景不是正在生成的场景，清除生成状态
            const statusSpan = document.getElementById('generate-multi-angle-status');
            const btn = document.getElementById('generate-loc-multi-angle-btn');
            if (generatingLocationName && generatingLocationName !== data.name) {
                if (statusSpan) statusSpan.textContent = '';
                if (btn) {
                    btn.disabled = false;
                    btn.classList.remove('disabled');
                }
            }
        }

        // 触发场景多角度图片上传
        function triggerLocMultiImageUpload() {
            const fileInput = document.getElementById('loc-multi-image-file');
            fileInput.click();
        }

        // 处理场景多角度图片上传
        async function handleLocMultiImageUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            // 验证文件类型
            if (!file.type.startsWith('image/')) {
                showError(window.t ? window.t('error_select_image_file') : '请选择图片文件');
                event.target.value = '';
                return;
            }

            // 验证文件大小 (10MB)
            if (file.size > 10 * 1024 * 1024) {
                showError(window.t ? window.t('error_image_too_large') : '图片大小不能超过10MB');
                event.target.value = '';
                return;
            }

            const angleSelect = document.getElementById('loc-multi-image-angle');
            const labelInput = document.getElementById('loc-multi-image-label');
            const list = document.getElementById('loc-multi-image-list');
            const angle = angleSelect.value;
            const label = labelInput.value.trim() || angleSelect.options[angleSelect.selectedIndex].text;

            showInfo('正在上传图片...');

            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', USER_ID);
            formData.append('world_id', WORLD_ID);
            formData.append('item_type', 2); // 2=location
            formData.append('auth_token', AUTH_TOKEN);

            try {
                const response = await fetch('/api/upload-image', {
                    method: 'POST',
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: formData
                });

                const data = await response.json();
                if (data.success) {
                    addLocMultiImageItem(list, label, data.url, angle, undefined);
                    labelInput.value = '';
                    showSuccess(window.t ? window.t('success_image_uploaded') : '图片上传成功');
                } else {
                    showError((window.t ? window.t('error_upload_failed', {error: data.error}) : '上传失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_upload_failed', {error: error.message}) : '上传失败: ' + error.message));
            }

            event.target.value = '';
        }

        function addLocMultiImageItem(container, label, url, angle, imgId) {
            const wrapper = document.createElement('div');
            wrapper.dataset.multiLocImage = '';
            wrapper.dataset.id = imgId || '';
            wrapper.dataset.label = label;
            wrapper.dataset.angle = angle;
            wrapper.dataset.url = url;
            wrapper.style.cssText = 'position:relative;width:80px;height:80px;border-radius:8px;overflow:hidden;border:1px solid #d1d5db;';
            wrapper.innerHTML = `
                <img src="${escapeHtml(url)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display='none'" />
                <div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.7);color:white;font-size:10px;padding:2px 6px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(label)}</div>
                <button type="button" style="position:absolute;top:2px;right:2px;background:rgba(239,68,68,0.8);border:none;border-radius:50%;width:20px;height:20px;cursor:pointer;color:white;font-size:12px;line-height:20px;" title="删除" data-i18n-title="title_delete">&times;</button>
            `;
            wrapper.querySelector('button').addEventListener('click', () => wrapper.remove());
            container.appendChild(wrapper);
        }

        function showPropEditor(fileName, data) {
            document.getElementById('edit-modal-title').textContent = `✏️ 编辑道具 - ${fileName}`;
            document.getElementById('prop-edit-form').style.display = 'block';
            document.getElementById('prop-name').value = data.name || '';
            document.getElementById('prop-type').value = data.type || '';
            document.getElementById('prop-description').value = data.description || '';
            document.getElementById('prop-image').value = data.reference_image || '';
            
            // 如果有图片，显示预览
            if (data.reference_image) {
                showImagePreview('prop-image', data.reference_image);
            } else {
                removeImagePreview('prop-image');
            }
        }

        function showScriptEditor(fileName, data) {
            const epLabel = data.episode_number ? `第${data.episode_number}集：` : '';
            document.getElementById('edit-modal-title').textContent = `✏️ 编辑剧本 - ${epLabel}${data.title || fileName}`;
            document.getElementById('script-edit-form').style.display = 'block';
            document.getElementById('script-title').value = data.title || '';
            document.getElementById('script-episode').value = data.episode_number || '';
            document.getElementById('script-content').value = data.content || '';
            document.getElementById('script-created').value = data.create_time || '';
            document.getElementById('script-updated').value = data.update_time || '';
        }

        function showTextEditor(fileName, content) {
            document.getElementById('edit-modal-title').textContent = `✏️ 编辑 ${fileName}`;
            document.getElementById('text-edit-form').style.display = 'block';
            document.getElementById('edit-modal-content').value = content;
        }

        function closeEditModal() {
            document.getElementById('edit-modal').classList.remove('show');
            currentEditFile = { fileType: '', fileName: '' };
        }

        // 多图预览全局状态
        let previewImages = [];  // 当前预览的多图列表
        let previewImageIndex = 0;  // 当前显示的图片索引
        let previewImageFileType = '';  // 当前预览的文件类型
        let previewImageFileName = '';  // 当前预览的文件名
        let previewMainImage = '';  // 预览弹窗中场景的主图
        let previewDescription = '';  // 预览弹窗中场景的描述
        let previewLocationName = '';  // 预览弹窗中场景的名称

        function selectPreviewImage(index) {
            previewImageIndex = index;
            document.getElementById('preview-image').src = previewImages[index].url;
            renderImageThumbnails();
        }

        function renderImageThumbnails() {
            const container = document.getElementById('image-preview-thumbnails');
            container.innerHTML = '';
            previewImages.forEach((img, idx) => {
                const item = document.createElement('div');
                item.className = 'thumbnail-item' + (idx === previewImageIndex ? ' active' : '');
                item.dataset.index = idx;
                item.onclick = () => selectPreviewImage(idx);

                // 非主图且是场景类型，显示单独生成按钮
                const showGenerateBtn = idx > 0 && previewImageFileType === 'locations';

                item.innerHTML = `
                    <img src="${escapeHtml(img.url)}" alt="${escapeHtml(img.label || '')}">
                    <div class="thumbnail-label">${escapeHtml(img.label || '')}</div>
                    ${showGenerateBtn ? `<button class="thumbnail-generate-btn" data-index="${idx}" onclick="event.stopPropagation(); regeneratePreviewSingleAngle(${idx})">${window.t ? window.t('btn_generate') : '生成'}</button>` : ''}
                `;
                container.appendChild(item);
            });

            // 显示/隐藏生成多角度按钮区域
            const generateSection = document.getElementById('preview-generate-section');
            if (previewImageFileType === 'locations' && previewMainImage) {
                generateSection.style.display = 'block';
                // 根据 runninghub 配置状态更新预览按钮
                checkRunningHubForMultiAngle();
            } else {
                generateSection.style.display = 'none';
            }
        }

        async function previewItemImage(fileType, fileName) {
            try {
                const apiMap = {
                    'characters': '/api/characters-files',
                    'locations': '/api/locations-files',
                    'props': '/api/props-files'
                };

                const response = await fetch(`${apiMap[fileType]}/${encodeURIComponent(fileName)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();

                if (checkTokenExpired(data, response)) {
                    return;
                }

                if (data.success) {
                    let jsonData = data.character?.json_data || data.location?.json_data || data.prop?.json_data || {};

                    if (!jsonData || Object.keys(jsonData).length === 0) {
                        const content = data.character?.content || data.location?.content || data.prop?.content || '';
                        try {
                            if (content.trim()) {
                                jsonData = JSON.parse(content);
                            } else {
                                jsonData = {};
                            }
                        } catch (e) {
                            showError(window.t ? window.t('error_parse_file_data') : '无法解析文件数据');
                            return;
                        }
                    }

                    // 收集所有图片
                    previewImages = [];
                    previewImageFileType = fileType;
                    previewImageFileName = fileName;

                    // 存储场景信息（用于生成多角度图）
                    if (fileType === 'locations') {
                        previewMainImage = jsonData.reference_image || '';
                        previewDescription = jsonData.description || '';
                        previewLocationName = fileName;
                    } else {
                        previewMainImage = '';
                        previewDescription = '';
                        previewLocationName = '';
                    }

                    // 主图
                    if (jsonData.reference_image && jsonData.reference_image.trim() !== '') {
                        previewImages.push({ url: jsonData.reference_image, label: '主图' });
                    }

                    // 多角度/多服装参考图（场景和角色）
                    if (fileType === 'locations' && jsonData.reference_images && Array.isArray(jsonData.reference_images)) {
                        jsonData.reference_images.forEach(img => {
                            if (img.url && img.url.trim() !== '') {
                                previewImages.push({
                                    url: img.url,
                                    label: img.label || img.angle || '角度图'
                                });
                            }
                        });
                    } else if (fileType === 'characters' && jsonData.reference_images && Array.isArray(jsonData.reference_images)) {
                        jsonData.reference_images.forEach((img, idx) => {
                            if (img.url && img.url.trim() !== '') {
                                previewImages.push({
                                    url: img.url,
                                    label: img.label || `服装${idx + 1}`
                                });
                            }
                        });
                    }

                    if (previewImages.length === 0) {
                        showInfo('该项目暂无参考图');
                        return;
                    }

                    // 显示图片预览弹窗
                    const typeNames = {
                        'characters': '角色',
                        'locations': '场景',
                        'props': '道具'
                    };
                    previewImageIndex = 0;
                    document.getElementById('image-preview-title').textContent = `${typeNames[fileType]}参考图 - ${fileName}`;
                    document.getElementById('preview-image').src = previewImages[0].url;

                    // 渲染缩略图网格
                    renderImageThumbnails();

                    document.getElementById('image-preview-modal').classList.add('show');
                } else {
                    showError((window.t ? window.t('error_fetch_data_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '获取数据失败: ' + (data.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_preview_image_failed', {error: error.message}) : '预览图片失败: ' + error.message));
            }
        }

        function closeImagePreviewModal() {
            document.getElementById('image-preview-modal').classList.remove('show');
        }

        // 生成场景多角度图片（90°, 180°, 270°）
        // 多角度生图任务轮询状态
        let multiAnglePollInterval = null;
        let generatingLocationName = null;  // 当前正在生成的场景名称

        // 检测 runninghub 配置状态，禁用/启用生成多角度图按钮
        function checkRunningHubForMultiAngle() {
            if(window.TaskConfig && !window.TaskConfig.isLoaded()) {
                window.TaskConfig.onLoaded(() => checkRunningHubForMultiAngle());
                return;
            }

            const btn = document.getElementById('generate-loc-multi-angle-btn');
            const statusSpan = document.getElementById('generate-multi-angle-status');
            const previewBtn = document.getElementById('preview-generate-multi-angle-btn');
            const previewStatusSpan = document.getElementById('preview-generate-status');

            const isConfigured = window.TaskConfig && window.TaskConfig.isRunningHubConfigured();

            // 编辑表单按钮
            if (btn) {
                if (!isConfigured) {
                    btn.disabled = true;
                    btn.title = '该功能依赖runninghub接口，请配置密钥';
                    btn.classList.add('disabled');
                    if (statusSpan) {
                        statusSpan.textContent = '该功能依赖runninghub接口，请配置密钥';
                        statusSpan.style.color = '#ef4444';
                    }
                } else {
                    btn.disabled = false;
                    btn.title = '';
                    btn.classList.remove('disabled');
                    if (statusSpan) {
                        statusSpan.textContent = '';
                    }
                }
            }

            // 预览弹窗按钮
            if (previewBtn) {
                if (!isConfigured) {
                    previewBtn.disabled = true;
                    previewBtn.title = '该功能依赖runninghub接口，请配置密钥';
                    previewBtn.classList.add('disabled');
                    if (previewStatusSpan) {
                        previewStatusSpan.textContent = '该功能依赖runninghub接口，请配置密钥';
                        previewStatusSpan.style.color = '#ef4444';
                    }
                } else {
                    previewBtn.disabled = false;
                    previewBtn.title = '';
                    previewBtn.classList.remove('disabled');
                    if (previewStatusSpan) {
                        previewStatusSpan.textContent = '';
                    }
                }
            }
        }

        async function generateLocMultiAngleImages() {
            const btn = document.getElementById('generate-loc-multi-angle-btn');
            const statusSpan = document.getElementById('generate-multi-angle-status');

            // 获取当前场景的主图和描述
            const mainImage = document.getElementById('loc-image').value.trim();
            const locationDesc = document.getElementById('loc-description').value.trim();
            const locationName = document.getElementById('loc-name').value.trim();

            if (!mainImage) {
                showError(window.t ? window.t('error_upload_main_image_first') : '请先上传主图');
                return;
            }

            if (!locationDesc) {
                showError(window.t ? window.t('error_fill_scene_desc') : '请先填写场景描述');
                return;
            }

            if (!locationName) {
                showError(window.t ? window.t('error_fill_scene_name') : '请先填写场景名称');
                return;
            }

            // 检查是否已选择生图模型
            const textToImageModelSelect = document.getElementById('text-to-image-model-selector');
            if (!textToImageModelSelect || !textToImageModelSelect.value) {
                showError(window.t ? window.t('error_select_image_model') : '请先选择生图模型');
                return;
            }

            // 定义要生成的角度
            const angles = ANGLES_CONFIG;

            // 记录当前正在生成的场景
            generatingLocationName = locationName;

            // 禁用按钮，显示状态
            btn.disabled = true;
            btn.classList.add('disabled');
            statusSpan.textContent = `[${locationName}] 正在提交多角度生图任务...`;

            try {
                // 1. 提交任务到后端队列
                const response = await fetch('/api/location-multi-angle-tasks', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        location_name: locationName,
                        main_image: mainImage,
                        description: locationDesc,
                        angles: angles,
                        model: textToImageModelSelect.value,
                        auth_token: AUTH_TOKEN
                    })
                });

                const result = await response.json();

                if (!result.success) {
                    showError((window.t ? window.t('error_submit_task_failed', {error: result.error}) : '提交任务失败: ' + result.error));
                    statusSpan.textContent = `[${locationName}] 提交失败`;
                    btn.disabled = false;
                    btn.classList.remove('disabled');
                    generatingLocationName = null;
                    return;
                }

                const taskKey = result.task_key;
                statusSpan.textContent = `[${locationName}] 任务已提交，等待处理...`;
                showInfo(`[${locationName}] 多角度生图任务已提交，后台正在处理中`);

                // 2. 开始轮询任务状态
                startMultiAnglePoll(taskKey, statusSpan, btn, locationName);

            } catch (error) {
                console.error('提交多角度生图任务出错:', error);
                statusSpan.textContent = `[${locationName}] 提交失败`;
                showError((window.t ? window.t('error_submit_task_failed', {error: error.message}) : '提交任务失败: ' + error.message));
                btn.disabled = false;
                btn.classList.remove('disabled');
                generatingLocationName = null;
            }
        }

        // 轮询任务状态
        async function startMultiAnglePoll(taskKey, statusSpan, btn, locationName) {
            // 清除之前的轮询
            if (multiAnglePollInterval) {
                clearInterval(multiAnglePollInterval);
            }

            const existingGeneratedUrls = new Set();
            // 记录已有的图片URL，避免重复添加
            document.querySelectorAll('#loc-multi-image-list [data-multi-loc-image]').forEach(item => {
                existingGeneratedUrls.add(item.dataset.url);
            });

            multiAnglePollInterval = setInterval(async () => {
                try {
                    const response = await fetch(
                        `/api/location-multi-angle-tasks/${encodeURIComponent(taskKey)}?user_id=${USER_ID}&world_id=${WORLD_ID}`,
                        {
                            headers: {
                                'Authorization': AUTH_TOKEN,
                                'X-User-Id': USER_ID
                            }
                        }
                    );

                    const result = await response.json();

                    if (!result.success || !result.task) {
                        console.warn('查询任务状态失败');
                        return;
                    }

                    const task = result.task;
                    const angles = task.angles || [];
                    const generatedImages = task.generated_images || [];
                    const currentIndex = task.current_angle_index;

                    // 更新状态显示
                    if (task.status === 0) {  // QUEUED
                        statusSpan.textContent = `[${locationName}] 任务排队中...`;
                    } else if (task.status === 1) {  // PROCESSING
                        const currentAngle = angles[currentIndex];
                        if (currentAngle) {
                            statusSpan.textContent = `[${locationName}] 正在生成 ${currentAngle.label}... (${currentIndex + 1}/${angles.length})`;
                        } else {
                            statusSpan.textContent = `[${locationName}] 处理中... (${currentIndex + 1}/${angles.length})`;
                        }
                    } else if (task.status === 2) {  // COMPLETED
                        // 任务完成
                        clearInterval(multiAnglePollInterval);
                        multiAnglePollInterval = null;
                        generatingLocationName = null;

                        // 添加所有生成的图片到 DOM
                        const listEl = document.getElementById('loc-multi-image-list');
                        generatedImages.forEach(img => {
                            if (!existingGeneratedUrls.has(img.url)) {
                                addLocMultiImageItem(listEl, img.label || img.angle, img.url, img.angle || 'front', null);
                                existingGeneratedUrls.add(img.url);
                            }
                        });

                        if (generatedImages.length > 0) {
                            statusSpan.textContent = `[${locationName}] 完成！已生成 ${generatedImages.length} 张多角度图`;
                            showSuccess(window.t ? window.t('success_multi_angle_done', {name: locationName, count: generatedImages.length}) : `[${locationName}] 多角度生图完成！共 ${generatedImages.length} 张图片已保存到暂存区`);
                        } else {
                            statusSpan.textContent = `[${locationName}] 任务完成但无图片`;
                            showWarning(window.t ? window.t('warn_no_images_generated') : '任务完成，但未生成任何图片');
                        }

                        btn.disabled = false;
                        btn.classList.remove('disabled');
                    } else if (task.status === -1) {  // FAILED
                        clearInterval(multiAnglePollInterval);
                        multiAnglePollInterval = null;
                        generatingLocationName = null;

                        // 添加已生成的图片
                        const listEl = document.getElementById('loc-multi-image-list');
                        generatedImages.forEach(img => {
                            if (!existingGeneratedUrls.has(img.url)) {
                                addLocMultiImageItem(listEl, img.label || img.angle, img.url, img.angle || 'front', null);
                                existingGeneratedUrls.add(img.url);
                            }
                        });

                        statusSpan.textContent = `[${locationName}] 失败: ${task.error_message || '未知错误'}`;
                        showError(window.t ? window.t('error_multi_angle_failed_named', {name: locationName, error: task.error_message || (window.t ? window.t('error_unknown') : '未知错误')}) : `[${locationName}] 多角度生图失败: ${task.error_message || '未知错误'}`);
                        btn.disabled = false;
                        btn.classList.remove('disabled');
                    }

                } catch (error) {
                    console.error('轮询任务状态出错:', error);
                }
            }, 37000);  // 每 37 秒轮询一次
        }

        // 停止轮询
        function stopMultiAnglePoll() {
            if (multiAnglePollInterval) {
                clearInterval(multiAnglePollInterval);
                multiAnglePollInterval = null;
            }
        }

        // ========== 预览弹窗中的多角度生成功能 ==========

        // 预览弹窗中生成多角度图片
        async function generatePreviewMultiAngleImages() {
            const btn = document.getElementById('preview-generate-multi-angle-btn');
            const statusSpan = document.getElementById('preview-generate-status');

            if (!previewMainImage) {
                showError(window.t ? window.t('error_no_main_image') : '主图信息不存在，无法生成');
                return;
            }

            if (!previewDescription) {
                showError(window.t ? window.t('error_empty_scene_desc') : '场景描述为空，无法生成');
                return;
            }

            if (!previewLocationName) {
                showError(window.t ? window.t('error_empty_scene_name') : '场景名称为空，无法生成');
                return;
            }

            const textToImageModelSelect = document.getElementById('text-to-image-model-selector');
            if (!textToImageModelSelect || !textToImageModelSelect.value) {
                showError(window.t ? window.t('error_select_image_model') : '请先选择生图模型');
                return;
            }

            const angles = ANGLES_CONFIG;

            btn.disabled = true;
            btn.classList.add('disabled');
            statusSpan.textContent = '正在提交多角度生图任务...';

            try {
                const response = await fetch('/api/location-multi-angle-tasks', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        location_name: previewLocationName,
                        main_image: previewMainImage,
                        description: previewDescription,
                        angles: angles,
                        model: textToImageModelSelect.value,
                        auth_token: AUTH_TOKEN
                    })
                });

                const result = await response.json();

                if (!result.success) {
                    showError((window.t ? window.t('error_submit_task_failed', {error: result.error}) : '提交任务失败: ' + result.error));
                    statusSpan.textContent = '提交失败';
                    btn.disabled = false;
                    btn.classList.remove('disabled');
                    return;
                }

                const taskKey = result.task_key;
                statusSpan.textContent = '任务已提交，等待处理...';
                showInfo('多角度生图任务已提交，后台正在处理中');

                // 开始轮询预览弹窗中的任务
                startPreviewMultiAnglePoll(taskKey, statusSpan, btn);

            } catch (error) {
                console.error('提交多角度生图任务出错:', error);
                statusSpan.textContent = '提交失败';
                showError((window.t ? window.t('error_submit_task_failed', {error: error.message}) : '提交任务失败: ' + error.message));
                btn.disabled = false;
                btn.classList.remove('disabled');
            }
        }

        // 预览弹窗中轮询多角度任务状态
        async function startPreviewMultiAnglePoll(taskKey, statusSpan, btn) {
            if (multiAnglePollInterval) {
                clearInterval(multiAnglePollInterval);
            }

            multiAnglePollInterval = setInterval(async () => {
                try {
                    const response = await fetch(
                        `/api/location-multi-angle-tasks/${encodeURIComponent(taskKey)}?user_id=${USER_ID}&world_id=${WORLD_ID}`,
                        {
                            headers: {
                                'Authorization': AUTH_TOKEN,
                                'X-User-Id': USER_ID
                            }
                        }
                    );

                    const result = await response.json();

                    if (!result.success || !result.task) {
                        console.warn('查询任务状态失败');
                        return;
                    }

                    const task = result.task;
                    const generatedImages = task.generated_images || [];
                    const currentIndex = task.current_angle_index;

                    if (task.status === 1) {  // PROCESSING
                        if (currentIndex !== undefined && currentIndex < angles.length) {
                            const currentAngle = angles[currentIndex];
                            if (currentAngle) {
                                statusSpan.textContent = `正在生成 ${currentAngle.label}... (${currentIndex}/${angles.length})`;
                            }
                        } else {
                            statusSpan.textContent = `处理中... (${currentIndex}/${angles.length})`;
                        }
                    } else if (task.status === 2) {  // COMPLETED
                        clearInterval(multiAnglePollInterval);
                        multiAnglePollInterval = null;

                        // 使用 dict 风格按 label 更新图片
                        const existingByLabel = {};
                        previewImages.forEach((img, idx) => {
                            if (idx > 0) { // 跳过主图
                                existingByLabel[img.label] = idx;
                            }
                        });

                        generatedImages.forEach(img => {
                            const label = img.label || img.angle || '角度图';
                            if (existingByLabel.hasOwnProperty(label)) {
                                // 替换已有图片
                                const idx = existingByLabel[label];
                                previewImages[idx] = { url: img.url, label: label };
                            } else {
                                // 添加新图片
                                previewImages.push({ url: img.url, label: label });
                            }
                        });

                        // 更新主图显示
                        if (previewImages.length > 0) {
                            document.getElementById('preview-image').src = previewImages[previewImageIndex].url;
                        }

                        renderImageThumbnails();

                        if (generatedImages.length > 0) {
                            statusSpan.textContent = `完成！已生成 ${generatedImages.length} 张多角度图`;
                            showSuccess(window.t ? window.t('success_multi_angle_done_short', {count: generatedImages.length}) : `多角度生图完成！共 ${generatedImages.length} 张图片已保存到暂存区`);
                        } else {
                            statusSpan.textContent = '任务完成但无图片';
                            showWarning(window.t ? window.t('warn_no_images_generated') : '任务完成，但未生成任何图片');
                        }

                        btn.disabled = false;
                        btn.classList.remove('disabled');
                    } else if (task.status === -1) {  // FAILED
                        clearInterval(multiAnglePollInterval);
                        multiAnglePollInterval = null;

                        statusSpan.textContent = `失败: ${task.error_message || '未知错误'}`;
                        showError(window.t ? window.t('error_multi_angle_failed', {error: task.error_message || (window.t ? window.t('error_unknown') : '未知错误')}) : `多角度生图失败: ${task.error_message || '未知错误'}`);
                        btn.disabled = false;
                        btn.classList.remove('disabled');
                    }

                } catch (error) {
                    console.error('轮询任务状态出错:', error);
                }
            }, 37000);
        }

        // 预览弹窗中单独生成某个角度的图片
        async function regeneratePreviewSingleAngle(index) {
            const img = previewImages[index];
            if (!img || index === 0) return;

            // 更灵活的角度匹配
            // 使用统一的 ANGLE_LABEL_MAP 匹配
            let angleInfo = ANGLE_LABEL_MAP[img.label];

            if (!angleInfo) {
                // 尝试从 label 中提取角度数字
                const angleMatch = img.label.match(/(\d+)/);
                if (angleMatch) {
                    angleInfo = ANGLE_LABEL_MAP[angleMatch[1]];
                }
            }

            if (!angleInfo) {
                console.warn('未匹配的角度标签:', img.label);
                showError(window.t ? window.t('error_unsupported_angle', {label: img.label}) : '不支持的角度标签: ' + img.label);
                return;
            }

            if (!previewMainImage) {
                showError(window.t ? window.t('error_no_main_image') : '主图信息不存在，无法生成');
                return;
            }

            const textToImageModelSelect = document.getElementById('text-to-image-model-selector');
            if (!textToImageModelSelect || !textToImageModelSelect.value) {
                showError(window.t ? window.t('error_select_image_model') : '请先选择生图模型');
                return;
            }

            const btn = document.querySelector(`.thumbnail-generate-btn[data-index="${index}"]`);
            if (btn) {
                btn.textContent = '生成中...';
                btn.disabled = true;
            }

            try {
                const response = await fetch('/api/location-multi-angle-tasks', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        location_name: previewLocationName,
                        main_image: previewMainImage,
                        description: previewDescription,
                        angles: [{ ...angleInfo, label: img.label }],
                        model: textToImageModelSelect.value,
                        auth_token: AUTH_TOKEN
                    })
                });

                const result = await response.json();
                if (result.success) {
                    await pollPreviewSingleAngleTask(result.task_key, index, img.label, btn);
                } else {
                    showError((window.t ? window.t('error_generate_failed', {error: result.error}) : '生成失败: ' + result.error));
                    if (btn) { btn.textContent = '生成'; btn.disabled = false; }
                }
            } catch (error) {
                showError((window.t ? window.t('error_generate_failed', {error: error.message}) : '生成失败: ' + error.message));
                if (btn) { btn.textContent = '生成'; btn.disabled = false; }
            }
        }

        // 轮询预览弹窗中单个角度生成任务
        async function pollPreviewSingleAngleTask(taskKey, imageIndex, originalLabel, btn) {
            const maxWait = 300000;
            const startTime = Date.now();

            const poll = async () => {
                if (Date.now() - startTime > maxWait) {
                    showError(window.t ? window.t('error_generate_timeout') : '生成超时');
                    if (btn) { btn.textContent = '生成'; btn.disabled = false; }
                    return;
                }

                try {
                    const response = await fetch(
                        `/api/location-multi-angle-tasks/${encodeURIComponent(taskKey)}?user_id=${USER_ID}&world_id=${WORLD_ID}`,
                        { headers: { 'Authorization': AUTH_TOKEN, 'X-User-Id': USER_ID } }
                    );
                    const result = await response.json();

                    if (!result.success) {
                        console.warn('查询任务失败:', result);
                        setTimeout(poll, 5000);
                        return;
                    }

                    const task = result.task;
                    if (task.status === 2) {  // COMPLETED
                        const generatedImages = task.generated_images || [];
                        if (generatedImages.length > 0) {
                            previewImages[imageIndex] = {
                                url: generatedImages[0].url,
                                label: originalLabel
                            };
                            document.getElementById('preview-image').src = generatedImages[0].url;
                            renderImageThumbnails();
                            showSuccess(window.t ? window.t('success_generated') : '生成成功');
                        }
                        if (btn) { btn.textContent = '生成'; btn.disabled = false; }
                    } else if (task.status === -1) {  // FAILED
                        showError(window.t ? window.t('error_generate_failed', {error: task.error_message || (window.t ? window.t('error_unknown') : '未知错误')}) : '生成失败: ' + (task.error_message || '未知错误'));
                        if (btn) { btn.textContent = '生成'; btn.disabled = false; }
                    } else if (task.status === 1) {  // PROCESSING
                        const currentIdx = task.current_angle_index;
                        const total = task.angles?.length || 1;
                        if (btn) { btn.textContent = `生成中... (${currentIdx + 1}/${total})`; }
                        setTimeout(poll, 5000);
                    } else {
                        setTimeout(poll, 5000);
                    }
                } catch (error) {
                    console.error('轮询出错:', error);
                    setTimeout(poll, 5000);
                }
            };

            poll();
        }

        // 根据角度获取方向描述（参考 camera_control_node.js 的逻辑）
        function getDirectionPromptFromAngle(angle) {
            angle = parseInt(angle);
            if (angle >= 337.5 || angle < 22.5) {
                return 'front view';
            } else if (angle >= 22.5 && angle < 67.5) {
                return 'front-right quarter view';
            } else if (angle >= 67.5 && angle < 112.5) {
                return 'right side view';
            } else if (angle >= 112.5 && angle < 157.5) {
                return 'back-right quarter view';
            } else if (angle >= 157.5 && angle < 202.5) {
                return 'back view';
            } else if (angle >= 202.5 && angle < 247.5) {
                return 'back-left quarter view';
            } else if (angle >= 247.5 && angle < 292.5) {
                return 'left side view';
            } else if (angle >= 292.5 && angle < 337.5) {
                return 'front-left quarter view';
            }
            return 'front view';
        }

        function triggerImageUpload(inputId, itemType) {
            const fileInputId = inputId + '-file';
            const fileInput = document.getElementById(fileInputId);
            fileInput.setAttribute('data-item-type', itemType);
            fileInput.click();
        }

        async function handleImageUpload(event, inputId, itemType) {
            const file = event.target.files[0];
            if (!file) return;
            
            // 验证文件类型
            if (!file.type.startsWith('image/')) {
                showError(window.t ? window.t('error_select_image_file') : '请选择图片文件');
                event.target.value = '';
                return;
            }
            
            // 验证文件大小 (10MB)
            if (file.size > 10 * 1024 * 1024) {
                showError(window.t ? window.t('error_image_too_large') : '图片大小不能超过10MB');
                event.target.value = '';
                return;
            }
            
            // 显示上传进度
            showInfo('正在上传图片...');
            
            // 上传到服务器
            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', USER_ID);
            formData.append('world_id', WORLD_ID);
            formData.append('item_type', itemType);
            formData.append('auth_token', AUTH_TOKEN);
            
            try {
                const response = await fetch('/api/upload-image', {
                    method: 'POST',
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: formData
                });
                
                const data = await response.json();
                if (data.success) {
                    // 更新输入框和预览
                    document.getElementById(inputId).value = data.url;
                    showImagePreview(inputId, data.url);
                    showSuccess(window.t ? window.t('success_image_uploaded') : '图片上传成功');
                } else {
                    showError((window.t ? window.t('error_upload_failed', {error: data.error}) : '上传失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_upload_failed', {error: error.message}) : '上传失败: ' + error.message));
            }
            
            // 清空file input
            event.target.value = '';
        }

        function showImagePreview(inputId, imageUrl) {
            const previewBox = document.getElementById(inputId + '-preview');
            const img = previewBox.querySelector('.preview-thumbnail');
            
            img.src = imageUrl;
            previewBox.style.display = 'block';
        }

        function removeImagePreview(inputId) {
            document.getElementById(inputId).value = '';
            document.getElementById(inputId + '-preview').style.display = 'none';
        }

        function clearImageInput(inputId) {
            removeImagePreview(inputId);
        }

        async function playCharacterVoice(characterName) {
            try {
                const response = await fetch(`/api/characters-files/${encodeURIComponent(characterName)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();

                if (checkTokenExpired(data, response)) {
                    return;
                }

                if (!data.success) {
                    showError(window.t ? window.t('error_fetch_character_failed') : '获取角色信息失败');
                    return;
                }

                let jsonData = data.character?.json_data || {};
                if (!jsonData || Object.keys(jsonData).length === 0) {
                    const content = data.character?.content || '';
                    try {
                        if (content.trim()) {
                            jsonData = JSON.parse(content);
                        } else {
                            showError(window.t ? window.t('error_empty_character_data') : '角色数据为空');
                            return;
                        }
                    } catch (e) {
                        showError(window.t ? window.t('error_parse_character_data') : '无法解析角色数据');
                        return;
                    }
                }

                const defaultVoice = jsonData.default_voice || '';
                if (!defaultVoice || defaultVoice.trim() === '') {
                    showInfo('该角色暂无音色');
                    return;
                }

                const audio = new Audio(defaultVoice);
                audio.onerror = () => {
                    showError(window.t ? window.t('error_audio_load_failed') : '音频加载失败');
                };
                audio.play().catch(err => {
                    showError(window.t ? window.t('error_play_failed', {error: err.message}) : '播放失败：' + err.message);
                });

                showSuccess(window.t ? window.t('success_playing_voice', {name: characterName}) : `正在播放 ${characterName} 的音色`);
            } catch (error) {
                console.error('播放角色音色失败:', error);
                showError(window.t ? window.t('error_play_failed') : '播放失败');
            }
        }

        async function deleteStagingFile(relativePath) {
            // 从相对路径提取文件类型和文件名
            const pathParts = relativePath.split('/');
            if (pathParts.length < 4) {
                showError(window.t ? window.t('error_invalid_file_path') : '无效的文件路径');
                return;
            }
            
            const fileType = pathParts[2];  // user_id/world_id/file_type/filename
            const fileName = pathParts[pathParts.length - 1];
            
            // 确认提示
            const typeNames = {
                'characters': '角色',
                'locations': '场景',
                'props': '道具',
                'scripts': '剧本'
            };
            const typeName = typeNames[fileType] || '文件';
            
            const confirmed = confirm(
                `⚠️ 删除暂存区${typeName}\n\n` +
                `确定要删除 "${fileName}" 吗？\n\n` +
                `提示：此操作只会删除暂存区的文件，工作流中的${typeName}不会被删除。`
            );
            
            if (!confirmed) {
                return;
            }
            
            try {
                showInfo('正在删除...');
                
                const response = await fetch(`/api/staging-file?user_id=${USER_ID}&world_id=${WORLD_ID}&relative_path=${encodeURIComponent(relativePath)}&auth_token=${AUTH_TOKEN}`, {
                    method: 'DELETE',
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showSuccess(window.t ? window.t('success_deleted') : '删除成功');
                    // 重新加载文件列表
                    loadFiles(fileType);
                } else {
                    showError((window.t ? window.t('error_delete_failed', {error: data.error}) : '删除失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_delete_failed', {error: error.message}) : '删除失败: ' + error.message));
            }
        }

        async function saveEditedFile() {
            let newContent = '';
            
            if (document.getElementById('world-edit-form').style.display !== 'none') {
                newContent = collectWorldData();
            } else if (document.getElementById('character-edit-form').style.display !== 'none') {
                newContent = collectCharacterData();
            } else if (document.getElementById('location-edit-form').style.display !== 'none') {
                newContent = collectLocationData();
            } else if (document.getElementById('prop-edit-form').style.display !== 'none') {
                newContent = collectPropData();
            } else if (document.getElementById('script-edit-form').style.display !== 'none') {
                newContent = collectScriptData();
            } else if (document.getElementById('text-edit-form').style.display !== 'none') {
                newContent = document.getElementById('edit-modal-content').value;
            }
            
            if (!newContent.trim()) {
                showError(window.t ? window.t('error_file_content_empty') : '文件内容不能为空');
                return;
            }
            
            try {
                const apiMap = {
                    'worlds': '/api/world-files',
                    'characters': '/api/characters-files',
                    'scripts': '/api/scripts-files',
                    'locations': '/api/locations-files',
                    'props': '/api/props-files'
                };
                
                const response = await fetch(`${apiMap[currentEditFile.fileType]}/${encodeURIComponent(currentEditFile.fileName)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: newContent,
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        auth_token: AUTH_TOKEN
                    })
                });
                
                const data = await response.json();
                if (data.success) {
                    const fileType = currentEditFile.fileType;
                    const fileName = currentEditFile.fileName;
                    showSuccess(window.t ? window.t('success_file_updated', {name: fileName}) : `✓ 文件已更新: ${fileName}`);
                    closeEditModal();
                    await loadFiles(fileType);
                    
                    if (sessionId) {
                        try {
                            const fileTypeMap = {
                                'characters': '角色卡',
                                'locations': '场景',
                                'props': '道具',
                                'scripts': '剧本',
                                'worlds': '世界设定'
                            };
                            const notificationMessage = `系统通知：${fileTypeMap[fileType]} "${fileName}" 已被用户编辑更新，请重新读取最新内容。`;
                            await sendMessage(notificationMessage, true);
                        } catch (error) {
                            console.error('发送编辑通知失败:', error);
                        }
                    }
                } else {
                    showError((window.t ? window.t('error_save_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '保存失败: ' + (data.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_save_file_failed', {error: error.message}) : '保存文件失败: ' + error.message));
            }
        }

        function collectCharacterData() {
            const data = {
                name: document.getElementById('char-name').value.trim(),
                age: document.getElementById('char-age').value.trim(),
                identity: document.getElementById('char-identity').value.trim(),
                appearance: document.getElementById('char-appearance').value.trim(),
                personality: document.getElementById('char-personality').value.trim(),
                behavior: document.getElementById('char-behavior').value.trim(),
                other_info: document.getElementById('char-other').value.trim(),
                default_voice: document.getElementById('char-default-voice').value.trim(),
                reference_image: document.getElementById('char-image').value.trim()
            };
            // 收集多服装参考图
            const multiImageItems = document.querySelectorAll('#char-multi-image-list [data-multi-char-image]');
            if (multiImageItems.length > 0) {
                data.reference_images = [];
                multiImageItems.forEach(item => {
                    const imgData = {
                        label: item.dataset.label || '默认',
                        url: item.dataset.url
                    };
                    if (item.dataset.id) {
                        imgData.id = item.dataset.id;
                    }
                    data.reference_images.push(imgData);
                });
            }
            return JSON.stringify(data, null, 2);
        }

        // 触发角色多图片上传
        function triggerCharMultiImageUpload() {
            const fileInput = document.getElementById('char-multi-image-file');
            fileInput.click();
        }

        // 处理角色多图片上传
        async function handleCharMultiImageUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            // 验证文件类型
            if (!file.type.startsWith('image/')) {
                showError(window.t ? window.t('error_select_image_file') : '请选择图片文件');
                event.target.value = '';
                return;
            }

            // 验证文件大小 (10MB)
            if (file.size > 10 * 1024 * 1024) {
                showError(window.t ? window.t('error_image_too_large') : '图片大小不能超过10MB');
                event.target.value = '';
                return;
            }

            const labelInput = document.getElementById('char-multi-image-label');
            const list = document.getElementById('char-multi-image-list');
            const label = labelInput.value.trim() || '服装';

            showInfo('正在上传图片...');

            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', USER_ID);
            formData.append('world_id', WORLD_ID);
            formData.append('item_type', 1); // 1=character
            formData.append('auth_token', AUTH_TOKEN);

            try {
                const response = await fetch('/api/upload-image', {
                    method: 'POST',
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: formData
                });

                const data = await response.json();
                if (data.success) {
                    addCharMultiImageItem(list, label, data.url, undefined);
                    labelInput.value = '';
                    showSuccess(window.t ? window.t('success_image_uploaded') : '图片上传成功');
                } else {
                    showError((window.t ? window.t('error_upload_failed', {error: data.error}) : '上传失败: ' + data.error));
                }
            } catch (error) {
                showError((window.t ? window.t('error_upload_failed', {error: error.message}) : '上传失败: ' + error.message));
            }

            event.target.value = '';
        }

        function addCharMultiImageItem(container, label, url, imgId) {
            const wrapper = document.createElement('div');
            wrapper.dataset.multiCharImage = '';
            wrapper.dataset.id = imgId || '';
            wrapper.dataset.label = label;
            wrapper.dataset.url = url;
            wrapper.style.cssText = 'position:relative;width:80px;height:80px;border-radius:8px;overflow:hidden;border:1px solid #d1d5db;';
            wrapper.innerHTML = `
                <img src="${escapeHtml(url)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display='none'" />
                <div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.7);color:white;font-size:10px;padding:2px 6px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(label)}</div>
                <button type="button" style="position:absolute;top:2px;right:2px;background:rgba(239,68,68,0.8);border:none;border-radius:50%;width:20px;height:20px;cursor:pointer;color:white;font-size:12px;line-height:20px;" title="删除" data-i18n-title="title_delete">&times;</button>
            `;
            // 删除按钮 - 阻止冒泡
            wrapper.querySelector('button').addEventListener('click', (e) => {
                e.stopPropagation();
                wrapper.remove();
            });
            // 点击缩略图打开详情弹窗
            wrapper.addEventListener('click', () => {
                openOutfitDetailModal(wrapper);
            });
            container.appendChild(wrapper);
        }

        // ========== 多服装/造型详情弹窗 ==========
        let outfitDetailItems = [];  // 当前弹窗中的所有服装项
        let outfitDetailIndex = 0;   // 当前显示索引

        function openOutfitDetailModal(clickedWrapper) {
            const list = document.getElementById('char-multi-image-list');
            const allItems = list.querySelectorAll('[data-multi-char-image]');
            outfitDetailItems = [];
            let clickedIdx = 0;
            allItems.forEach((item, idx) => {
                outfitDetailItems.push({
                    label: item.dataset.label || '默认',
                    url: item.dataset.url
                });
                if (item === clickedWrapper) clickedIdx = idx;
            });
            if (outfitDetailItems.length === 0) return;
            outfitDetailIndex = clickedIdx;
            renderOutfitDetail();
            // 渲染缩略图
            renderOutfitThumbs();
            // 更新导航按钮状态
            updateOutfitNavButtons();
            document.getElementById('outfit-detail-modal').classList.add('show');
        }

        function closeOutfitDetailModal() {
            document.getElementById('outfit-detail-modal').classList.remove('show');
            outfitDetailItems = [];
            outfitDetailIndex = 0;
        }

        function renderOutfitDetail() {
            const item = outfitDetailItems[outfitDetailIndex];
            if (!item) return;
            document.getElementById('outfit-detail-image').src = item.url;
            document.getElementById('outfit-detail-label').textContent = item.label;
            document.getElementById('outfit-detail-title').textContent = item.label + ' - 服装/造型详情';
            // 更新缩略图高亮
            document.querySelectorAll('#outfit-detail-thumbs .outfit-thumb-item').forEach((thumb, idx) => {
                thumb.classList.toggle('active', idx === outfitDetailIndex);
            });
            updateOutfitNavButtons();
        }

        function renderOutfitThumbs() {
            const container = document.getElementById('outfit-detail-thumbs');
            container.innerHTML = '';
            if (outfitDetailItems.length <= 1) {
                container.style.display = 'none';
                return;
            }
            container.style.display = 'flex';
            outfitDetailItems.forEach((item, idx) => {
                const thumb = document.createElement('div');
                thumb.className = 'outfit-thumb-item' + (idx === outfitDetailIndex ? ' active' : '');
                thumb.innerHTML = `<img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.label || '')}" onerror="this.style.display='none'" />`;
                thumb.addEventListener('click', () => {
                    outfitDetailIndex = idx;
                    renderOutfitDetail();
                });
                container.appendChild(thumb);
            });
        }

        function navigateOutfitDetail(direction) {
            const newIdx = outfitDetailIndex + direction;
            if (newIdx < 0 || newIdx >= outfitDetailItems.length) return;
            outfitDetailIndex = newIdx;
            renderOutfitDetail();
        }

        function updateOutfitNavButtons() {
            const prevBtn = document.getElementById('outfit-nav-prev');
            const nextBtn = document.getElementById('outfit-nav-next');
            if (outfitDetailItems.length <= 1) {
                prevBtn.style.display = 'none';
                nextBtn.style.display = 'none';
                return;
            }
            prevBtn.style.display = '';
            nextBtn.style.display = '';
            prevBtn.disabled = outfitDetailIndex === 0;
            nextBtn.disabled = outfitDetailIndex === outfitDetailItems.length - 1;
        }

        // 键盘左右切换支持
        document.addEventListener('keydown', (e) => {
            const modal = document.getElementById('outfit-detail-modal');
            if (!modal.classList.contains('show')) return;
            if (e.key === 'ArrowLeft') { e.preventDefault(); navigateOutfitDetail(-1); }
            if (e.key === 'ArrowRight') { e.preventDefault(); navigateOutfitDetail(1); }
            if (e.key === 'Escape') { closeOutfitDetailModal(); }
        });

        function collectLocationData() {
            const parentName = (document.getElementById('loc-parent').value || '').trim() || null;
            const data = {
                name: document.getElementById('loc-name').value.trim(),
                // 文件层主字段：父场景名称；parent_id 过渡期双写同名，同步时按名称解析
                parent_name: parentName,
                parent_id: parentName,
                description: document.getElementById('loc-description').value.trim(),
                reference_image: document.getElementById('loc-image').value.trim()
            };
            // 收集多角度参考图
            const multiImageItems = document.querySelectorAll('#loc-multi-image-list [data-multi-loc-image]');
            if (multiImageItems.length > 0) {
                data.reference_images = [];
                multiImageItems.forEach(item => {
                    const imgData = {
                        label: item.dataset.label || '',
                        angle: item.dataset.angle || 'front',
                        url: item.dataset.url
                    };
                    if (item.dataset.id) {
                        imgData.id = item.dataset.id;
                    }
                    data.reference_images.push(imgData);
                });
            }
            return JSON.stringify(data, null, 2);
        }

        // 自动保存场景的 reference_images 到暂存区
        async function autoSaveLocationReferenceImages() {
            const locationName = document.getElementById('loc-name').value.trim();
            if (!locationName) {
                console.warn('无法保存：场景名称为空');
                return false;
            }

            // 收集当前 DOM 中的所有多角度参考图
            const multiImageItems = document.querySelectorAll('#loc-multi-image-list [data-multi-loc-image]');
            const referenceImages = [];
            multiImageItems.forEach(item => {
                const imgData = {
                    label: item.dataset.label || '',
                    angle: item.dataset.angle || 'front',
                    url: item.dataset.url
                };
                if (item.dataset.id) {
                    imgData.id = item.dataset.id;
                }
                referenceImages.push(imgData);
            });

            try {
                const response = await fetch(`/api/locations-files/${encodeURIComponent(locationName)}/reference-images`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        reference_images: referenceImages
                    })
                });

                const result = await response.json();
                if (result.success) {
                    console.log(`场景 ${locationName} 的参考图已自动保存`);
                    return true;
                } else {
                    console.error('自动保存失败:', result.error);
                    return false;
                }
            } catch (error) {
                console.error('自动保存参考图失败:', error);
                return false;
            }
        }

        function collectPropData() {
            const data = {
                name: document.getElementById('prop-name').value.trim(),
                type: document.getElementById('prop-type').value.trim(),
                description: document.getElementById('prop-description').value.trim(),
                reference_image: document.getElementById('prop-image').value.trim()
            };
            return JSON.stringify(data, null, 2);
        }

        function collectScriptData() {
            const now = new Date().toISOString();
            const data = {
                title: document.getElementById('script-title').value.trim(),
                episode_number: parseInt(document.getElementById('script-episode').value) || null,
                content: document.getElementById('script-content').value.trim(),
                create_time: document.getElementById('script-created').value || now,
                update_time: now
            };
            return JSON.stringify(data, null, 2);
        }

        function showWorldEditor(fileName, data) {
            console.log('showWorldEditor called with data:', data); // 调试日志
            data.story_type = normalizeStoryType(data.story_type);
            document.getElementById('edit-modal-title').textContent = `✏️ 编辑世界 - ${fileName}`;
            document.getElementById('world-edit-form').style.display = 'block';
            
            // 确保所有字段都有值，使用空字符串作为默认值
            document.getElementById('world-name').value = data.name || '';
            document.getElementById('world-user-id').value = data.user_id || USER_ID;
            document.getElementById('world-story-type').value = data.story_type;
            document.getElementById('world-description').value = data.description || '';
            document.getElementById('world-story-outline').value = data.story_outline || '';
            document.getElementById('world-visual-style').value = data.visual_style || '';
            document.getElementById('world-era-environment').value = data.era_environment || '';
            document.getElementById('world-color-language').value = data.color_language || '';
            document.getElementById('world-composition-preference').value = data.composition_preference || '';
            document.getElementById('world-created').value = data.create_time || '';
            document.getElementById('world-updated').value = data.update_time || '';
        }

        function collectWorldData() {
            const now = new Date().toISOString();
            const data = {
                id: parseInt(WORLD_ID),
                name: document.getElementById('world-name').value.trim(),
                user_id: parseInt(document.getElementById('world-user-id').value) || parseInt(USER_ID),
                story_type: normalizeStoryType(document.getElementById('world-story-type').value),
                description: document.getElementById('world-description').value.trim(),
                story_outline: document.getElementById('world-story-outline').value.trim(),
                visual_style: document.getElementById('world-visual-style').value.trim(),
                era_environment: document.getElementById('world-era-environment').value.trim(),
                color_language: document.getElementById('world-color-language').value.trim(),
                composition_preference: document.getElementById('world-composition-preference').value.trim(),
                create_time: document.getElementById('world-created').value || now,
                update_time: now
            };
            return JSON.stringify(data, null, 2);
        }

        // 缓存世界列表，用于侧边栏搜索
        let cachedWorlds = [];

        function renderWorldList(worlds) {
            const worldList = document.getElementById('world-list');
            if (!worldList) return;

            if (worlds.length === 0) {
                const searchInput = document.getElementById('world-search-input');
                const hasKeyword = searchInput && searchInput.value.trim();
                worldList.innerHTML = `<div class="world-empty">${hasKeyword
                    ? (window.t ? window.t('no_worlds_found') : '未找到匹配的世界')
                    : (window.t ? window.t('no_worlds') : '暂无世界')}</div>`;
                return;
            }

            worldList.innerHTML = '';
            worlds.forEach(world => {
                const worldItem = document.createElement('div');
                worldItem.className = 'world-item' + (world.id == WORLD_ID ? ' active' : '');

                const worldInfo = document.createElement('div');
                worldInfo.className = 'world-info';
                worldInfo.onclick = () => switchWorld(world.id);

                const worldName = document.createElement('div');
                worldName.className = 'world-name';
                worldName.textContent = world.name;
                worldInfo.appendChild(worldName);

                if (world.description) {
                    const worldDesc = document.createElement('div');
                    worldDesc.className = 'world-desc';
                    worldDesc.textContent = world.description;
                    worldInfo.appendChild(worldDesc);
                }

                const worldActions = document.createElement('div');
                worldActions.className = 'world-actions';

                const editBtn = document.createElement('button');
                editBtn.className = 'world-edit-btn';
                editBtn.title = '编辑世界';
                editBtn.onclick = (e) => {
                    e.stopPropagation();
                    showEditWorldModal(world.id, world.name, world.description || '', world.story_type);
                };
                editBtn.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                `;

                worldActions.appendChild(editBtn);
                worldItem.appendChild(worldInfo);
                worldItem.appendChild(worldActions);
                worldList.appendChild(worldItem);
            });
        }

        function filterWorlds(keyword) {
            const normalized = (keyword || '').toLowerCase().trim();
            if (!normalized) {
                renderWorldList(cachedWorlds);
                return;
            }
            const filtered = cachedWorlds.filter(world => {
                const name = (world.name || '').toLowerCase();
                const desc = (world.description || '').toLowerCase();
                return name.includes(normalized) || desc.includes(normalized);
            });
            renderWorldList(filtered);
        }

        function bindWorldSearchEvents() {
            const searchInput = document.getElementById('world-search-input');
            const clearBtn = document.getElementById('world-search-clear');
            if (!searchInput) return;

            searchInput.addEventListener('input', (e) => {
                filterWorlds(e.target.value);
                if (clearBtn) {
                    clearBtn.style.display = e.target.value ? 'flex' : 'none';
                }
            });

            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    searchInput.value = '';
                    filterWorlds('');
                    clearBtn.style.display = 'none';
                    searchInput.focus();
                });
            }
        }

        async function loadUserWorlds() {
            try {
                const response = await fetch('/api/worlds?page=1&page_size=100', {
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    }
                });
                const data = await response.json();

                // 兼容后端返回格式: {code: 0, data: {data: [...]}}
                const worlds = data.data?.data || data.worlds || [];
                if (data.code === 0 || data.success) {
                    cachedWorlds = worlds;
                    // 应用当前搜索关键字过滤（如果有）
                    const searchInput = document.getElementById('world-search-input');
                    filterWorlds(searchInput ? searchInput.value : '');
                } else {
                    cachedWorlds = [];
                    document.getElementById('world-list').innerHTML = '<div class="world-empty">加载失败</div>';
                }
            } catch (error) {
                console.error('加载世界列表失败:', error);
                cachedWorlds = [];
                document.getElementById('world-list').innerHTML = '<div class="world-empty">加载失败</div>';
            }
        }

        function toggleWorldSidebar() {
            const sidebar = document.getElementById('world-sidebar');
            const overlay = document.getElementById('world-sidebar-overlay');
            sidebar.classList.toggle('open');
            overlay.classList.toggle('active');
        }

        function switchWorld(worldId) {
            if (worldId == WORLD_ID) {
                toggleWorldSidebar();
                return;
            }
            
            // auth_token 已在 localStorage 中，无需通过 URL 传递
            // 保留workflow_id参数，确保切换世界后仍能跳转到制作工坊
            let newUrl = `${window.location.pathname}?user_id=${USER_ID}&world_id=${worldId}`;
            if (WORKFLOW_ID) {
                newUrl += `&workflow_id=${WORKFLOW_ID}`;
            }
            window.location.href = newUrl;
        }

        async function loadCurrentWorldName() {
            try {
                const response = await fetch('/api/worlds?page=1&page_size=100', {
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    }
                });
                const data = await response.json();
                
                // 兼容后端返回格式: {code: 0, data: {data: [...]}}
                const worlds = data.data?.data || data.worlds || [];
                if (data.code === 0 || data.success) {
                    const currentWorld = worlds.find(w => w.id == WORLD_ID);
                    const worldNameDisplay = document.getElementById('world-name-display');
                    
                    if (currentWorld && worldNameDisplay) {
                        worldNameDisplay.textContent = currentWorld.name;
                    } else if (worldNameDisplay) {
                        worldNameDisplay.textContent = '';
                    }
                }
            } catch (error) {
                console.error('加载世界名称失败:', error);
                const worldNameDisplay = document.getElementById('world-name-display');
                if (worldNameDisplay) {
                    worldNameDisplay.textContent = '';
                }
            }
        }

        // 新建世界相关函数
        // 「新建世界」弹窗行内错误：模态框会遮挡聊天区，showError 写入 #chat-messages 时用户看不到，
        // 因此重名/失败等提示改为直接在弹窗内输入框下方展示，并标红聚焦。
        function showNewWorldFormError(message) {
            const nameInput = document.getElementById('new-world-name');
            const errorEl = document.getElementById('new-world-error');
            if (errorEl) {
                errorEl.textContent = message || '创建失败';
                errorEl.style.display = 'block';
            }
            if (nameInput) {
                nameInput.style.borderColor = '#ef4444';
                nameInput.focus();
            }
        }

        function clearNewWorldFormError() {
            const nameInput = document.getElementById('new-world-name');
            const errorEl = document.getElementById('new-world-error');
            if (errorEl && errorEl.style.display !== 'none') {
                errorEl.style.display = 'none';
                errorEl.textContent = '';
            }
            if (nameInput) {
                nameInput.style.borderColor = '';
            }
        }

        function showNewWorldModal() {
            document.getElementById('new-world-name').value = '';
            document.getElementById('new-world-description').value = '';
            document.getElementById('new-world-story-type').value = 'dialogue';
            // 世界描述默认折叠，需用户点击后再编辑
            const descSection = document.getElementById('new-world-desc-section');
            const toggleBtn = document.getElementById('toggle-new-world-desc-btn');
            if (descSection) descSection.style.display = 'none';
            if (toggleBtn) {
                toggleBtn.textContent = window.t ? window.t('expand_world_desc') : '展开填写世界描述（可选）';
            }
            clearNewWorldFormError();
            document.getElementById('new-world-modal').classList.add('show');
            document.getElementById('new-world-name').focus();
        }

        function toggleNewWorldDescSection() {
            const section = document.getElementById('new-world-desc-section');
            const btn = document.getElementById('toggle-new-world-desc-btn');
            if (!section || !btn) return;
            const isHidden = section.style.display === 'none' || !section.style.display;
            if (isHidden) {
                section.style.display = 'block';
                btn.textContent = window.t ? window.t('collapse_world_desc') : '收起世界描述';
                const ta = document.getElementById('new-world-description');
                if (ta) ta.focus();
            } else {
                section.style.display = 'none';
                btn.textContent = window.t ? window.t('expand_world_desc') : '展开填写世界描述（可选）';
            }
        }

        function closeNewWorldModal() {
            clearNewWorldFormError();
            document.getElementById('new-world-modal').classList.remove('show');
        }

        async function createNewWorld() {
            const name = document.getElementById('new-world-name').value.trim();
            const description = document.getElementById('new-world-description').value.trim();
            const storyType = normalizeStoryType(document.getElementById('new-world-story-type').value);

            if (!name) {
                showNewWorldFormError(window.t ? window.t('error_enter_world_name') : '请输入世界名称');
                return;
            }

            clearNewWorldFormError();
            const createBtn = document.querySelector('#new-world-modal .btn-primary');
            const originText = createBtn ? createBtn.textContent : '';
            if (createBtn) { createBtn.disabled = true; createBtn.textContent = '创建中...'; }

            try {
                updateStatus(window.t ? window.t('status_creating_world') : '正在创建世界...');
                const response = await fetch('/api/worlds', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${AUTH_TOKEN}`,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({
                        name: name,
                        description: description,
                        story_type: storyType
                    })
                });

                const data = await response.json().catch(() => ({}));
                if (data.code === 0) {
                    showSuccess(window.t ? window.t('success_world_created_detail', {name: name}) : `✓ 世界 "${name}" 创建成功！`);
                    closeNewWorldModal();
                    await loadUserWorlds();
                    updateStatus(window.t ? window.t('status_world_created') : '世界创建完成');

                    // 自动选中新创建的世界
                    if (data.data && data.data.id) {
                        switchWorld(data.data.id);
                    }
                } else {
                    // 后端业务错误（含重名「该世界已经存在，请选择其他名称」）原样透传，行内展示
                    const fallback = window.t ? window.t('error_unknown') : '未知错误';
                    showNewWorldFormError(data.message || fallback);
                    updateStatus(window.t ? window.t('status_create_failed') : '创建失败');
                }
            } catch (error) {
                showNewWorldFormError(error && error.message ? error.message : '网络异常，创建世界失败');
                updateStatus(window.t ? window.t('status_create_failed') : '创建失败');
            } finally {
                if (createBtn) { createBtn.disabled = false; createBtn.textContent = originText || '创建世界'; }
            }
        }

        // 用户修正名称后，及时清除行内错误（避免红框/红字残留）
        (function bindNewWorldErrorClear() {
            const nameInput = document.getElementById('new-world-name');
            if (nameInput) nameInput.addEventListener('input', clearNewWorldFormError);
        })();

        // 新建剧本相关函数
        let existingEpisodes = []; // 缓存已有集数

        function showNewScriptModal() {
            document.getElementById('new-script-title').value = '';
            document.getElementById('new-script-episode').value = '';
            document.getElementById('new-script-content').value = '';
            const hint = document.getElementById('episode-hint');
            hint.style.display = 'none';
            hint.textContent = '';
            // 加载已有集数列表用于校验
            fetchExistingEpisodes();
            document.getElementById('new-script-modal').classList.add('show');
            document.getElementById('new-script-title').focus();
        }

        function closeNewScriptModal() {
            document.getElementById('new-script-modal').classList.remove('show');
        }

        async function fetchExistingEpisodes() {
            try {
                const response = await fetch(`/api/scripts-files?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();
                const scripts = data.scripts || data.data?.data || [];
                existingEpisodes = scripts
                    .map(s => parseInt(s.episode_number))
                    .filter(n => !isNaN(n));
            } catch (e) {
                console.warn('获取已有剧本集数失败:', e);
                existingEpisodes = [];
            }
        }

        function checkEpisodeDuplicate() {
            const episodeInput = document.getElementById('new-script-episode');
            const hint = document.getElementById('episode-hint');
            const value = parseInt(episodeInput.value);

            if (!episodeInput.value) {
                hint.style.display = 'none';
                hint.textContent = '';
                return;
            }

            if (isNaN(value) || value < 1) {
                hint.style.display = 'block';
                hint.style.color = 'var(--error-color, #e74c3c)';
                hint.textContent = '集数必须为正整数';
                return;
            }

            if (existingEpisodes.includes(value)) {
                hint.style.display = 'block';
                hint.style.color = 'var(--error-color, #e74c3c)';
                hint.textContent = `第 ${value} 集已存在，请选择其他集数`;
            } else {
                hint.style.display = 'block';
                hint.style.color = 'var(--success-color, #27ae60)';
                hint.textContent = `第 ${value} 集可用`;
            }
        }

        async function createNewScript() {
            const title = document.getElementById('new-script-title').value.trim();
            const episodeValue = document.getElementById('new-script-episode').value;
            const content = document.getElementById('new-script-content').value.trim();
            const episode = parseInt(episodeValue);

            if (!title) {
                showError(window.t ? window.t('error_enter_script_title') : '请输入剧本标题');
                return;
            }
            if (!episodeValue || isNaN(episode) || episode < 1) {
                showError(window.t ? window.t('error_invalid_episode_num') : '请输入有效的集数（正整数）');
                return;
            }
            if (existingEpisodes.includes(episode)) {
                showError(window.t ? window.t('error_episode_exists', {episode: episode}) : `第 ${episode} 集已存在，请选择其他集数`);
                return;
            }

            try {
                updateStatus(window.t ? window.t('status_creating_script') : '正在创建剧本...');
                const now = new Date().toISOString();
                const scriptData = JSON.stringify({
                    user_id: USER_ID,
                    world_id: WORLD_ID,
                    title: title,
                    episode_number: episode,
                    content: content || '',
                    create_time: now,
                    update_time: now
                }, null, 2);

                const response = await fetch(`/api/scripts-files/${encodeURIComponent(episode)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: scriptData,
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        auth_token: AUTH_TOKEN
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showSuccess(window.t ? window.t('success_script_created_detail', {title: title, episode: episode}) : `✓ 剧本 "${title}"（第${episode}集）创建成功！`);
                    closeNewScriptModal();
                    await loadFiles('scripts');
                    updateStatus(window.t ? window.t('status_script_created') : '剧本创建完成');
                } else {
                    showError((window.t ? window.t('error_create_script_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '创建剧本失败: ' + (data.error || '未知错误')));
                    updateStatus(window.t ? window.t('status_create_failed') : '创建失败');
                }
            } catch (error) {
                showError((window.t ? window.t('error_create_script_failed', {error: error.message}) : '创建剧本失败: ' + error.message));
                updateStatus(window.t ? window.t('status_create_failed') : '创建失败');
            }
        }

        // ==================== 新建角色 ====================
        let existingCharacters = [];

        async function fetchExistingCharacters() {
            try {
                const response = await fetch(`/api/characters-files?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();
                const chars = data.characters || data.data?.data || [];
                existingCharacters = chars.map(c => c.name).filter(Boolean);
            } catch (e) {
                console.warn('获取已有角色列表失败:', e);
                existingCharacters = [];
            }
        }

        function checkCharacterNameDuplicate() {
            const nameInput = document.getElementById('new-char-name');
            const hint = document.getElementById('char-name-hint');
            const value = nameInput.value.trim();
            if (!value) { hint.style.display = 'none'; return; }
            if (existingCharacters.includes(value)) {
                hint.style.display = 'block';
                hint.style.color = 'var(--error-color, #e74c3c)';
                hint.textContent = `角色"${value}"已存在，请使用其他名称`;
            } else {
                hint.style.display = 'block';
                hint.style.color = 'var(--success-color, #27ae60)';
                hint.textContent = `名称"${value}"可用`;
            }
        }

        function showNewCharacterModal() {
            ['new-char-name','new-char-age','new-char-identity'].forEach(id => document.getElementById(id).value = '');
            ['new-char-appearance','new-char-personality','new-char-behavior','new-char-other'].forEach(id => document.getElementById(id).value = '');
            const hint = document.getElementById('char-name-hint');
            hint.style.display = 'none'; hint.textContent = '';
            fetchExistingCharacters();
            document.getElementById('new-character-modal').classList.add('show');
            document.getElementById('new-char-name').focus();
            // 绑定实时校验
            document.getElementById('new-char-name').oninput = checkCharacterNameDuplicate;
        }

        function closeNewCharacterModal() {
            document.getElementById('new-character-modal').classList.remove('show');
        }

        async function createNewCharacter() {
            const name = document.getElementById('new-char-name').value.trim();
            if (!name) { showError(window.t ? window.t('error_enter_character_name') : '请输入角色名称'); return; }
            if (existingCharacters.includes(name)) { showError(window.t ? window.t('error_character_exists', {name: name}) : `角色"${name}"已存在`); return; }

            try {
                updateStatus(window.t ? window.t('status_creating_character') : '正在创建角色...');
                const now = new Date().toISOString();
                const data = {
                    user_id: USER_ID,
                    world_id: WORLD_ID,
                    name: name,
                    age: document.getElementById('new-char-age').value.trim(),
                    identity: document.getElementById('new-char-identity').value.trim(),
                    appearance: document.getElementById('new-char-appearance').value.trim(),
                    personality: document.getElementById('new-char-personality').value.trim(),
                    behavior: document.getElementById('new-char-behavior').value.trim(),
                    other_info: document.getElementById('new-char-other').value.trim(),
                    reference_image: '',
                    reference_images: [],
                    create_time: now,
                    update_time: now
                };
                const response = await fetch(`/api/characters-files/${encodeURIComponent(name)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: JSON.stringify(data, null, 2), user_id: USER_ID, world_id: WORLD_ID, auth_token: AUTH_TOKEN })
                });
                const result = await response.json();
                if (result.success) {
                    showSuccess(window.t ? window.t('success_character_created_detail', {name: name}) : `✓ 角色"${name}"创建成功！`);
                    closeNewCharacterModal();
                    await loadFiles('characters');
                } else {
                    showError((window.t ? window.t('error_create_character_failed', {error: result.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '创建角色失败: ' + (result.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_create_character_failed', {error: error.message}) : '创建角色失败: ' + error.message));
            }
        }

        // ==================== 新建场景 ====================
        let existingLocations = [];

        async function fetchExistingLocations() {
            try {
                const list = await fetchLocationJsonList();
                existingLocations = list.map((l) => l.name).filter(Boolean);
            } catch (e) {
                console.warn('获取已有场景列表失败:', e);
                existingLocations = [];
            }
        }

        function checkLocationNameDuplicate() {
            const nameInput = document.getElementById('new-loc-name');
            const hint = document.getElementById('loc-name-hint');
            const value = nameInput.value.trim();
            if (!value) { hint.style.display = 'none'; return; }
            if (existingLocations.includes(value)) {
                hint.style.display = 'block';
                hint.style.color = 'var(--error-color, #e74c3c)';
                hint.textContent = `场景"${value}"已存在，请使用其他名称`;
            } else {
                hint.style.display = 'block';
                hint.style.color = 'var(--success-color, #27ae60)';
                hint.textContent = `名称"${value}"可用`;
            }
        }

        async function showNewLocationModal() {
            document.getElementById('new-loc-name').value = '';
            document.getElementById('new-loc-description').value = '';
            const hint = document.getElementById('loc-name-hint');
            hint.style.display = 'none'; hint.textContent = '';
            await fetchExistingLocations();
            await loadTopLevelParentOptions(document.getElementById('new-loc-parent'), {
                selectedParentName: '',
            });
            document.getElementById('new-location-modal').classList.add('show');
            document.getElementById('new-loc-name').focus();
            document.getElementById('new-loc-name').oninput = checkLocationNameDuplicate;
        }

        function closeNewLocationModal() {
            document.getElementById('new-location-modal').classList.remove('show');
        }

        async function createNewLocation() {
            const name = document.getElementById('new-loc-name').value.trim();
            if (!name) { showError(window.t ? window.t('error_enter_scene_name') : '请输入场景名称'); return; }
            if (existingLocations.includes(name)) { showError(window.t ? window.t('error_scene_exists', {name: name}) : `场景"${name}"已存在`); return; }

            try {
                updateStatus(window.t ? window.t('status_creating_scene') : '正在创建场景...');
                const now = new Date().toISOString();
                const parentName = (document.getElementById('new-loc-parent').value || '').trim() || null;
                const data = {
                    user_id: USER_ID,
                    world_id: WORLD_ID,
                    name: name,
                    parent_name: parentName,
                    parent_id: parentName,
                    description: document.getElementById('new-loc-description').value.trim(),
                    reference_image: '',
                    reference_images: [],
                    create_time: now,
                    update_time: now
                };
                const response = await fetch(`/api/locations-files/${encodeURIComponent(name)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: JSON.stringify(data, null, 2), user_id: USER_ID, world_id: WORLD_ID, auth_token: AUTH_TOKEN })
                });
                const result = await response.json();
                if (result.success) {
                    showSuccess(window.t ? window.t('success_scene_created_detail', {name: name}) : `✓ 场景"${name}"创建成功！`);
                    closeNewLocationModal();
                    await loadFiles('locations');
                } else {
                    showError((window.t ? window.t('error_create_scene_failed', {error: result.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '创建场景失败: ' + (result.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_create_scene_failed', {error: error.message}) : '创建场景失败: ' + error.message));
            }
        }

        // ==================== 新建道具 ====================
        let existingProps = [];

        async function fetchExistingProps() {
            try {
                const response = await fetch(`/api/props-files?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}&raw_json=true`);
                const data = await response.json();
                const props = data.props || data.data?.data || [];
                existingProps = props.map(p => p.name).filter(Boolean);
            } catch (e) {
                console.warn('获取已有道具列表失败:', e);
                existingProps = [];
            }
        }

        function checkPropNameDuplicate() {
            const nameInput = document.getElementById('new-prop-name');
            const hint = document.getElementById('prop-name-hint');
            const value = nameInput.value.trim();
            if (!value) { hint.style.display = 'none'; return; }
            if (existingProps.includes(value)) {
                hint.style.display = 'block';
                hint.style.color = 'var(--error-color, #e74c3c)';
                hint.textContent = `道具"${value}"已存在，请使用其他名称`;
            } else {
                hint.style.display = 'block';
                hint.style.color = 'var(--success-color, #27ae60)';
                hint.textContent = `名称"${value}"可用`;
            }
        }

        function showNewPropModal() {
            ['new-prop-name','new-prop-type'].forEach(id => document.getElementById(id).value = '');
            document.getElementById('new-prop-description').value = '';
            const hint = document.getElementById('prop-name-hint');
            hint.style.display = 'none'; hint.textContent = '';
            fetchExistingProps();
            document.getElementById('new-prop-modal').classList.add('show');
            document.getElementById('new-prop-name').focus();
            document.getElementById('new-prop-name').oninput = checkPropNameDuplicate;
        }

        function closeNewPropModal() {
            document.getElementById('new-prop-modal').classList.remove('show');
        }

        async function createNewProp() {
            const name = document.getElementById('new-prop-name').value.trim();
            if (!name) { showError(window.t ? window.t('error_enter_prop_name') : '请输入道具名称'); return; }
            if (existingProps.includes(name)) { showError(window.t ? window.t('error_prop_exists', {name: name}) : `道具"${name}"已存在`); return; }

            try {
                updateStatus(window.t ? window.t('status_creating_prop') : '正在创建道具...');
                const now = new Date().toISOString();
                const data = {
                    user_id: USER_ID,
                    world_id: WORLD_ID,
                    name: name,
                    type: document.getElementById('new-prop-type').value.trim(),
                    description: document.getElementById('new-prop-description').value.trim(),
                    reference_image: '',
                    create_time: now,
                    update_time: now
                };
                const response = await fetch(`/api/props-files/${encodeURIComponent(name)}?user_id=${USER_ID}&world_id=${WORLD_ID}&auth_token=${AUTH_TOKEN}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: JSON.stringify(data, null, 2), user_id: USER_ID, world_id: WORLD_ID, auth_token: AUTH_TOKEN })
                });
                const result = await response.json();
                if (result.success) {
                    showSuccess(window.t ? window.t('success_prop_created_detail', {name: name}) : `✓ 道具"${name}"创建成功！`);
                    closeNewPropModal();
                    await loadFiles('props');
                } else {
                    showError((window.t ? window.t('error_create_prop_failed', {error: result.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '创建道具失败: ' + (result.error || '未知错误')));
                }
            } catch (error) {
                showError((window.t ? window.t('error_create_prop_failed', {error: error.message}) : '创建道具失败: ' + error.message));
            }
        }

        // 编辑世界相关函数
        function showEditWorldModal(worldId, worldName, worldDescription = '', storyType = 'dialogue') {
            currentEditWorld.id = worldId;
            currentEditWorld.name = worldName;
            currentEditWorld.description = worldDescription;
            currentEditWorld.story_type = normalizeStoryType(storyType);
            
            document.getElementById('edit-world-name').value = worldName;
            document.getElementById('edit-world-description').value = worldDescription;
            document.getElementById('edit-world-story-type').value = currentEditWorld.story_type;
            document.getElementById('edit-world-modal').classList.add('show');
            document.getElementById('edit-world-name').focus();
        }

        function closeEditWorldModal() {
            document.getElementById('edit-world-modal').classList.remove('show');
            currentEditWorld = { id: '', name: '', description: '', story_type: 'dialogue' };
        }

        function openComputingPowerLogsModal() {
            if (!AUTH_TOKEN) {
                updateStatus(window.t ? window.t('status_auth_missing') : '缺少认证信息', 'error');
                return;
            }
            
            const modal = document.getElementById('computing-power-logs-modal');
            const iframe = document.getElementById('computing-power-logs-iframe');
            
            // iframe 与父页面同源，共享 localStorage，无需通过 URL 传递 auth_token
            iframe.src = `/computing_power_logs.html`;
            
            modal.classList.add('show');
        }

        function closeComputingPowerLogsModal() {
            const modal = document.getElementById('computing-power-logs-modal');
            const iframe = document.getElementById('computing-power-logs-iframe');
            
            // 关闭时清空 iframe src
            iframe.src = '';
            
            modal.classList.remove('show');
        }

        // 打开算力充值弹窗
        async function handleRechargeClick() {
            // 检查是否本地模式
            try {
                const response = await fetch('/api/system/server-config');
                const data = await response.json();
                if (data.data && data.data.is_local) {
                    alert(window.t ? window.t('alert_cloud_only_payment') : '只有云端环境才能开启二维码支付。本地模式下，管理员用户请进入后台增加算力，非管理员用户请通知管理员。');
                    return;
                }
            } catch (e) {
                console.error('获取配置失败:', e);
            }

            // 显示充值弹窗
            const modal = document.getElementById('recharge-power-modal');
            modal.classList.add('show');

            // 加载充值套餐
            loadRechargePackages();
        }

        // 关闭充值弹窗
        function closeRechargeModal() {
            const modal = document.getElementById('recharge-power-modal');
            modal.classList.remove('show');
        }

        // 加载充值套餐
        async function loadRechargePackages() {
            const body = document.getElementById('rechargeModalBody');
            body.innerHTML = '<div style="text-align: center; padding: 40px;"><div class="loading-spinner"></div><p style="margin-top: 16px; color: #6b7280;">加载套餐中...</p></div>';

            try {
                const authToken = localStorage.getItem('auth_token') || '';
                const response = await fetch(`/api/recharge/packages?auth_token=${encodeURIComponent(authToken)}`);
                const data = await response.json();

                if (data.packages && data.packages.length > 0) {
                    let html = '<div style="display: flex; flex-direction: column; gap: 12px;">';
                    data.packages.forEach(pkg => {
                        html += `
                            <div class="package-item" data-pkg-id="${pkg.package_id}" data-pkg-desc="${escapeHtml(pkg.description || '')}" data-pkg-power="${pkg.computing_power}" data-pkg-price="${pkg.price}" onclick="selectRechargePackage(Number(this.dataset.pkgId), this.dataset.pkgDesc, Number(this.dataset.pkgPower), Number(this.dataset.pkgPrice))" style="padding: 16px; border: 1px solid #e5e7eb; border-radius: 8px; cursor: pointer; transition: all 0.2s;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <div>
                                        <div style="font-weight: 600; color: #0f172a;">${escapeHtml(pkg.description)}</div>
                                        <div style="font-size: 12px; color: #6b7280; margin-top: 4px;">${pkg.computing_power} 算力</div>
                                    </div>
                                    <div style="text-align: right;">
                                        <div style="font-size: 20px; font-weight: 600; color: #ef4444;">¥${pkg.price}</div>
                                        <div style="font-size: 11px; color: #9ca3af;">${(pkg.price / pkg.computing_power * 100).toFixed(2)}元/百算力</div>
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';
                    body.innerHTML = html;
                } else {
                    body.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">暂无可用套餐</div>';
                }
            } catch (e) {
                console.error('加载充值套餐失败:', e);
                body.innerHTML = '<div style="text-align: center; padding: 40px; color: #ef4444;">加载失败，请重试</div>';
            }
        }

        // 选择充值套餐
        async function selectRechargePackage(packageId, description, computingPower, price) {
            const body = document.getElementById('rechargeModalBody');
            body.innerHTML = `
                <div style="text-align: center; margin-bottom: 20px;">
                    <div style="font-size: 16px; font-weight: 600; color: #0f172a;">${description}</div>
                    <div style="font-size: 14px; color: #6b7280; margin-top: 8px;">${computingPower} 算力 - ¥${price}</div>
                </div>
                <div id="rechargeQrCode" style="text-align: center; padding: 20px;">
                    <div class="loading-spinner"></div>
                    <p style="margin-top: 16px; color: #6b7280;">正在生成支付二维码...</p>
                </div>
            `;

            try {
                // 获取用户 IP
                let paymentIp = '0.0.0.0';
                try {
                    const ipResponse = await fetch('https://api.ipify.org?format=json');
                    const ipData = await ipResponse.json();
                    paymentIp = ipData.ip || '0.0.0.0';
                } catch (e) {
                    console.error('获取用户IP失败:', e);
                }

                const response = await fetch('/api/recharge/wechat-pay', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: USER_ID,
                        package_id: packageId,
                        auth_token: AUTH_TOKEN,
                        is_wechat_browser: false,
                        payment_ip: paymentIp
                    })
                });

                const data = await response.json();
                if (data.code_url) {
                    // 使用 QR Server API 将 weixin:// 协议转换为二维码图片
                    const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(data.code_url)}`;
                    body.innerHTML = `
                        <div style="text-align: center;">
                            <div style="font-weight: 600; font-size: 14px; margin-bottom: 16px;">请使用微信扫码完成支付</div>
                            <div style="background: #fff; padding: 12px; border-radius: 12px; display: inline-block;">
                                <img src="${qrCodeUrl}" alt="微信支付二维码" style="width: 200px; height: 200px;" />
                            </div>
                            <div style="font-size: 12px; color: #6b7280; margin-top: 16px; line-height: 1.6;">
                                请打开微信"扫一扫"完成支付<br/>
                                如果已支付，请稍等片刻系统会自动到账
                            </div>
                            <div style="margin-top: 16px;">
                                <button class="btn btn-secondary" onclick="loadRechargePackages()" data-i18n="btn_return_select_package">返回选择套餐</button>
                            </div>
                        </div>
                    `;
                } else {
                    throw new Error(data.error || '创建支付订单失败');
                }
            } catch (e) {
                console.error('创建支付订单失败:', e);
                body.innerHTML = `
                    <div style="text-align: center; padding: 20px;">
                        <p style="color: #ef4444; margin-bottom: 16px;">${escapeHtml(e.message)}</p>
                        <button class="btn btn-secondary" onclick="loadRechargePackages()">返回选择套餐</button>
                    </div>
                `;
            }
        }

        async function saveEditedWorld() {
            const name = document.getElementById('edit-world-name').value.trim();
            const description = document.getElementById('edit-world-description').value.trim();
            const storyType = normalizeStoryType(document.getElementById('edit-world-story-type').value);
            
            if (!name) {
                showError(window.t ? window.t('error_enter_world_name') : '请输入世界名称');
                return;
            }
            
            if (!currentEditWorld.id) {
                showError(window.t ? window.t('error_invalid_world_id') : '无效的世界ID');
                return;
            }
            
            try {
                updateStatus(window.t ? window.t('status_saving_world') : '正在保存世界信息...');
                const response = await fetch(`/api/worlds/${currentEditWorld.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        description: description,
                        story_type: storyType,
                        user_id: USER_ID,
                        auth_token: AUTH_TOKEN
                    })
                });
                
                const data = await response.json();
                if (data.success) {
                    showSuccess(window.t ? window.t('success_world_updated_detail', {name: name}) : `✓ 世界 "${name}" 更新成功！`);
                    closeEditWorldModal();
                    await loadUserWorlds();
                    await loadCurrentWorldName();
                    updateStatus(window.t ? window.t('status_world_updated') : '世界信息已更新');
                } else {
                    showError((window.t ? window.t('error_update_world_failed', {error: data.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '更新世界失败: ' + (data.error || '未知错误')));
                    updateStatus(window.t ? window.t('status_update_failed') : '更新失败');
                }
            } catch (error) {
                showError((window.t ? window.t('error_update_world_failed', {error: error.message}) : '更新世界失败: ' + error.message));
                updateStatus(window.t ? window.t('status_update_failed') : '更新失败');
            }
        }

        // 键盘事件处理
        document.addEventListener('keydown', function(e) {
            // 新建世界弹窗中按 Enter 键创建世界
            if (e.key === 'Enter' && document.getElementById('new-world-modal').classList.contains('show')) {
                if (e.target.id === 'new-world-name' || e.target.id === 'new-world-description') {
                    e.preventDefault();
                    createNewWorld();
                }
            }
            
            // 编辑世界弹窗中按 Enter 键保存
            if (e.key === 'Enter' && document.getElementById('edit-world-modal').classList.contains('show')) {
                if (e.target.id === 'edit-world-name' || e.target.id === 'edit-world-description') {
                    e.preventDefault();
                    saveEditedWorld();
                }
            }
            
            // 按 Escape 键关闭弹窗
            if (e.key === 'Escape') {
                closeCustomModelSelectMenu();
                if (document.getElementById('new-world-modal').classList.contains('show')) {
                    closeNewWorldModal();
                }
                if (document.getElementById('edit-world-modal').classList.contains('show')) {
                    closeEditWorldModal();
                }
            }
        });

        // 处理需求选择
        function handleRequirementSelect(option) {
            const messageInput = document.getElementById('message-input');
            if (!messageInput) return;

            // 隐藏需求选择区域
            const requirementSelector = document.getElementById('requirement-selector');
            if (requirementSelector) {
                requirementSelector.style.display = 'none';
            }

            let promptText = '';
            switch(option) {
                case 1:
                    // 隐藏需求选择区域
                    if (requirementSelector) {
                        requirementSelector.style.display = 'none';
                    }
                    openImportScriptModal();
                    return;
                case 2:
                    promptText = window.t ? window.t('prompt_continuation') : '我想进行剧本续写，请继续之前的剧情发展';
                    break;
                case 3:
                    promptText = window.t ? window.t('prompt_new_script') : '我想新建一个剧本';
                    break;
                case 4:
                    promptText = '';
                    // 其他选项不自动填充，让用户自己输入
                    break;
                default:
                    return;
            }

            if (promptText) {
                messageInput.value = promptText;
            }

            // 将光标移到末尾
            messageInput.focus();
            messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
        }

        // 显示世界选择提示
        function showWorldSelectionPrompt() {
            // 自动打开世界选择侧边栏
            const sidebar = document.getElementById('world-sidebar');
            const overlay = document.getElementById('world-sidebar-overlay');
            sidebar.classList.add('open');
            overlay.classList.add('active');
            
            // 更新欢迎卡片内容，显示世界选择提示
            const chatMessages = document.getElementById('chat-messages');
            chatMessages.innerHTML = `
                <div class="welcome-card world-selection-prompt">
                    <div class="welcome-icon">🌍</div>
                    <h2 class="welcome-title" data-i18n="no_world_selected">请选择一个世界开始创作</h2>
                    <p class="welcome-desc" data-i18n="select_world_desc">您需要先选择一个世界才能开始使用剧本智能创作系统</p>
                    <div class="world-selection-actions">
                        <div class="selection-step">
                            <span class="step-icon">←</span>
                            <span class="step-text" data-i18n="select_world_step">左侧侧边栏中选择一个现有世界</span>
                        </div>
                        <div class="selection-divider" data-i18n="or_divider">或</div>
                        <div class="selection-step">
                            <button class="btn btn-primary" onclick="showNewWorldModal()">
                                <span class="btn-icon">➕</span>
                                <span class="btn-text" data-i18n="create_new_world_btn">创建新世界</span>
                            </button>
                        </div>
                    </div>
                    <div class="selection-note">
                        <span class="note-icon">ℹ️</span>
                        <span data-i18n="world_desc">世界是您的创作空间，包含角色、场景、道具和剧本等内容</span>
                    </div>
                </div>
            `;

            // 翻译新添加的 data-i18n 元素
            if (window.ZJTi18nDOM && window.ZJTi18nDOM.scanDOM) {
                window.ZJTi18nDOM.scanDOM(chatMessages);
            }

            // 禁用输入区域
            const messageInput = document.getElementById('message-input');
            const sendBtn = document.getElementById('send-btn');
            if (messageInput) {
                messageInput.disabled = true;
                messageInput.placeholder = window.t ? window.t('world_placeholder') : '请先选择一个世界...';
            }
            if (sendBtn) {
                sendBtn.disabled = true;
            }

            // 更新状态显示
            updateStatus(window.t ? window.t('no_world_selected') : '请选择一个世界开始创作');
            
            // 更新世界名称显示
            const worldNameDisplay = document.getElementById('world-name-display');
            if (worldNameDisplay) {
                worldNameDisplay.textContent = window.t ? window.t('world_not_selected') : '未选择世界';
                worldNameDisplay.style.color = 'var(--warning-color)';
            }
        }
        
        // ========== 左侧导览条相关函数 ==========
        // 导览条现在是悬浮模式，通过CSS hover自动展开/收起，无需JavaScript控制
        
        // 检查资产完成状态
        async function checkAssetsComplete() {
            if (!WORLD_ID) {
                return { hasScript: false, missingAssets: [] };
            }
            
            try {
                const response = await fetch('/api/check-assets-complete', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    },
                    body: JSON.stringify({ world_id: parseInt(WORLD_ID) })
                });
                
                const data = await response.json();
                
                if (data.code === 0) {
                    return {
                        hasScript: data.data.has_script,
                        missingAssets: data.data.missing_assets || [],
                        character_image_count: data.data.character_image_count || 0,
                        location_image_count: data.data.location_image_count || 0
                    };
                } else {
                    console.error('检查资产状态失败:', data.message);
                    return { hasScript: true, missingAssets: [], character_image_count: 0, location_image_count: 0 };
                }
            } catch (error) {
                console.error('检查资产状态请求失败:', error);
                return { hasScript: true, missingAssets: [], character_image_count: 0, location_image_count: 0 };
            }
        }
        
        // 显示资产检查确认弹窗
        function showAssetConfirmModal(hasScript, missingAssets) {
            return new Promise((resolve) => {
                let message = window.t ? window.t('asset_confirm_title') : '检测到以下问题：\n\n';

                // 检查剧本
                if (!hasScript) {
                    message += window.t ? window.t('asset_confirm_no_script') : '⚠️ 当前世界还没有剧本\n';
                }

                // 检查资产图片
                if (missingAssets && missingAssets.length > 0) {
                    message += window.t ? window.t('asset_confirm_missing_images') : '\n以下资产图片尚未生成：\n';
                    missingAssets.forEach(asset => {
                        const typeLabel = window.t ? window.t(`label_${asset.type}`) || asset.type : asset.type;
                        message += `【${typeLabel}】${asset.items.slice(0, 3).join(window.t ? window.t('separator_comma') || '、' : '、')}`;
                        if (asset.items.length > 3) {
                            message += window.t ? window.t('asset_confirm_item_count', { count: asset.items.length }) : ` 等${asset.items.length}项`;
                        }
                        message += '\n';
                    });
                    message += window.t ? window.t('asset_confirm_hint') : '\n💡 提示：请点击「提交」按钮生成资产图片后再进入制作工坊\n';
                }

                message += window.t ? window.t('asset_confirm_enter_workflow') : '\n是否仍要进入制作工坊？';

                if (confirm(message)) {
                    resolve(true);
                } else {
                    resolve(false);
                }
            });
        }
        
        function showModeSelection() {
            submitToDatabase().catch(e => console.warn('预提交失败:', e));

            let modal = document.getElementById('mode-selection-modal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'mode-selection-modal';
                modal.className = 'sw-modal-overlay';
                modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);display:none;align-items:center;justify-content:center;z-index:9999;';
                modal.innerHTML = `
                    <div style="background:#1e1e2e;border-radius:12px;padding:32px;max-width:480px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4);">
                        <h2 style="color:#e8e8e8;margin:0 0 8px;font-size:20px;">选择制作模式</h2>
                        <p style="color:#a0a0b0;margin:0 0 24px;font-size:14px;">选择你想使用的短剧制作方式</p>
                        <div style="display:flex;gap:16px;">
                            <div onclick="selectMode('canvas')" style="flex:1;background:#0f3460;border:2px solid transparent;border-radius:10px;padding:20px;cursor:pointer;text-align:center;transition:all 0.2s;" onmouseenter="this.style.borderColor='#4f46e5'" onmouseleave="this.style.borderColor='transparent'">
                                <div style="font-size:36px;margin-bottom:8px;">🎨</div>
                                <h3 style="color:#e8e8e8;margin:0 0 6px;font-size:16px;">画布模式</h3>
                                <p style="color:#a0a0b0;margin:0;font-size:12px;">节点式工作流，自由连接各类处理节点</p>
                            </div>
                            <div onclick="selectMode('storyboard')" style="flex:1;background:#0f3460;border:2px solid transparent;border-radius:10px;padding:20px;cursor:pointer;text-align:center;transition:all 0.2s;" onmouseenter="this.style.borderColor='#4f46e5'" onmouseleave="this.style.borderColor='transparent'">
                                <div style="font-size:36px;margin-bottom:8px;">📋</div>
                                <h3 style="color:#e8e8e8;margin:0 0 6px;font-size:16px;">故事板模式</h3>
                                <p style="color:#a0a0b0;margin:0;font-size:12px;">分镜式编辑，按场景逐帧生成图片和视频</p>
                            </div>
                        </div>
                        <div style="text-align:center;margin-top:16px;">
                            <button onclick="closeModeSelection()" style="background:none;border:1px solid #555;color:#a0a0b0;padding:6px 20px;border-radius:6px;cursor:pointer;font-size:13px;">取消</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            modal.style.display = 'flex';
        }

        function closeModeSelection() {
            const modal = document.getElementById('mode-selection-modal');
            if (modal) modal.style.display = 'none';
        }

        async function selectMode(mode) {
            closeModeSelection();
            if (mode === 'canvas') {
                await goToWorkflowCanvas();
            } else if (mode === 'storyboard') {
                await goToStoryboard();
            }
        }

        async function goToStoryboard() {
            try {
                await submitToDatabase();
            } catch (e) {
                console.error('提交数据失败:', e);
            }

            const assetsStatus = await checkAssetsComplete();
            const hasProblems = !assetsStatus.hasScript || assetsStatus.missingAssets.length > 0;
            if (hasProblems) {
                const confirmed = await showAssetConfirmModal(assetsStatus.hasScript, assetsStatus.missingAssets);
                if (!confirmed) return;
            }

            const currentWorldId = window.currentWorldId || WORLD_ID;
            if (!currentWorldId) {
                alert('请先选择世界');
                return;
            }

            let episodeNumber = 1;
            const episodeInput = document.getElementById('script-episode');
            if (episodeInput && episodeInput.value) {
                episodeNumber = parseInt(episodeInput.value, 10) || 1;
            }

            let scriptId = null;
            try {
                const resp = await fetch(`/api/scripts?world_id=${encodeURIComponent(currentWorldId)}&page_size=100&order_by=episode_number&order_direction=ASC`, {
                    headers: {
                        'Authorization': AUTH_TOKEN,
                        'X-User-Id': USER_ID
                    }
                });
                const result = await resp.json();
                const scripts = result?.data?.data || [];
                const matched = scripts.find(item => parseInt(item.episode_number, 10) === episodeNumber);
                scriptId = matched ? matched.id : null;
            } catch (e) {
                console.warn('获取当前剧本ID失败，故事板后端将按集数兜底:', e);
            }

            const params = new URLSearchParams({
                world_id: currentWorldId,
                episode_number: episodeNumber,
            });
            if (scriptId) params.set('script_id', scriptId);
            if (USER_ID) params.set('user_id', USER_ID);
            if (WORKFLOW_ID) params.set('workflow_id', WORKFLOW_ID);
            // 注意：不再把 auth_token 放到 URL 中（避免敏感信息暴露），storyboard 会从 localStorage 读取（参考本文件实现）
            window.location.href = `/storyboard?${params.toString()}`;
        }

        // 跳转到工作流画布
        async function goToWorkflowCanvas() {
            // 如果没有WORKFLOW_ID，尝试从当前世界获取关联的工作流
            if (!WORKFLOW_ID && window.currentWorldId) {
                // 可以在这里添加获取世界关联工作流的逻辑
                console.log('当前世界ID:', window.currentWorldId);
            }
            
            // 先提交当前数据
            try {
                await submitToDatabase();
            } catch (e) {
                console.error('提交数据失败:', e);
            }
            
            // 检查资产完成状态
            const assetsStatus = await checkAssetsComplete();
            
            // 如果有问题（没有剧本或资产缺失图片），弹出确认提示
            const hasProblems = !assetsStatus.hasScript || assetsStatus.missingAssets.length > 0;
            if (hasProblems) {
                const confirmed = await showAssetConfirmModal(assetsStatus.hasScript, assetsStatus.missingAssets);
                if (!confirmed) {
                    return;
                }
            }
            
            // 跳转到工作流画布
            if (WORKFLOW_ID) {
                // 传递当前世界ID，供工作流页面自动同步世界配置
                const currentWorldId = window.currentWorldId || WORLD_ID;
                let url = `/video-workflow?id=${WORKFLOW_ID}`;
                if (currentWorldId) {
                    url += `&from_world_id=${currentWorldId}`;
                }
                // 传递 auto_load_script 参数，让工作流自动打开剧本选择框
                url += `&auto_load_script=true`;
                window.location.href = url;
            } else {
                // 没有WORKFLOW_ID，跳转到工作流列表
                alert(window.t ? window.t('alert_no_workflow') : '未找到关联的工作流，请先创建工作流');
                window.location.href = '/video-workflow-list';
            }
        }

        // ========== 导入剧本弹窗 ==========
        let importScriptFileContent = '';

        function openImportScriptModal() {
            importScriptFileContent = '';
            document.getElementById('import-script-content').value = '';
            document.getElementById('import-script-file').value = '';
            document.getElementById('drop-zone-text').innerHTML = window.t ? window.t('drop_zone_text') : '拖拽 TXT 文件到此处，或<span class="drop-zone-link">点击选择文件</span>';
            document.getElementById('script-drop-zone').classList.remove('has-file');
            document.getElementById('import-script-modal').classList.add('show');
        }

        function closeImportScriptModal() {
            document.getElementById('import-script-modal').classList.remove('show');
            importScriptFileContent = '';
        }

        async function submitImportScript() {
            const textareaContent = document.getElementById('import-script-content').value.trim();
            const content = textareaContent || importScriptFileContent;

            if (!content) {
                showError(window.t ? window.t('error_no_script_content') : '请上传文件或输入剧本内容');
                return;
            }

            closeImportScriptModal();
            const message = `${window.t ? window.t('msg_import_script_prompt') : '请帮我导入以下已有剧本内容：'}\n\n---\n${content}\n---`;
            await sendMessage(message);
        }

        function readScriptFile(file) {
            if (!file) return;
            if (!file.name.toLowerCase().endsWith('.txt')) {
                showError(window.t ? window.t('error_txt_only') : '仅支持 TXT 文件');
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                showError(window.t ? window.t('error_file_too_large') : '文件大小不能超过5MB');
                return;
            }

            const reader = new FileReader();
            reader.onload = function(e) {
                importScriptFileContent = (e.target.result || '').trim();
                if (!importScriptFileContent) {
                    showError(window.t ? window.t('error_file_empty') : '文件内容为空');
                    return;
                }
                document.getElementById('drop-zone-text').innerHTML = `${window.t ? window.t('msg_file_selected') : '已选择'}: <strong>${escapeHtml(file.name)}</strong>`;
                document.getElementById('script-drop-zone').classList.add('has-file');
            };
            reader.onerror = function() {
                showError(window.t ? window.t('error_read_file_failed') : '读取文件失败');
            };
            reader.readAsText(file, 'UTF-8');
        }

        // Debug: 测试 ask_user 功能
        async function testAskUserFeature() {
            const debugBtn = document.getElementById('debug-test-btn');
            if (!debugBtn) return;

            debugBtn.disabled = true;
            debugBtn.textContent = '⏳ 测试中...';

            try {
                console.log('🧪 开始测试 ask_user 功能...');

                // 获取当前选择的模型
                const modelSelector = document.getElementById('model-selector');
                if (!modelSelector || !modelSelector.value) {
                    showError(window.t ? window.t('error_select_llm_model') : '请先选择一个 LLM 模型');
                    debugBtn.disabled = false;
                    debugBtn.textContent = '🧪 测试';
                    return;
                }

                const selectedOption = modelSelector.options[modelSelector.selectedIndex];
                const model = modelSelector.value;
                const vendor_id = selectedOption?.dataset?.vendorId || 1;
                const model_id = selectedOption?.dataset?.modelId || 1;
                const modelDisplay = selectedOption?.text || model;

                console.log('📋 使用模型:', {
                    model: model,
                    vendor_id: vendor_id,
                    model_id: model_id,
                    display: modelDisplay
                });

                // 1. 触发测试端点
                const taskResp = await fetch('/api/test/ask-user', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: 'test_' + Date.now(),
                        user_id: USER_ID,
                        world_id: WORLD_ID,
                        auth_token: '',
                        model: model,
                        vendor_id: parseInt(vendor_id),
                        model_id: parseInt(model_id)
                    })
                }).then(r => r.json());

                if (!taskResp.success) {
                    console.error('❌ 测试任务创建失败:', taskResp);
                    showError((window.t ? window.t('error_test_failed', {error: taskResp.error || (window.t ? window.t('error_unknown') : '未知错误')}) : '测试失败: ' + (taskResp.error || '未知错误')));
                    return;
                }

                console.log('✅ 任务已创建:', taskResp);
                alert('✅ ' + (window.t ? window.t('alert_test_created', {taskId: taskResp.task_id}) : `测试任务已创建！\n\n📋 任务ID: ${taskResp.task_id}\n\n现在 LLM 将向你提问，请在前端回答，然后观察 LLM 的回复。\n\n💡 提示：打开浏览器控制台（F12）可以看到更详细的 SSE 消息日志。`));

                // 2. 监听 SSE
                const es = new EventSource(`/api/task/${taskResp.task_id}/stream`);

                let hasQuestion = false;
                let hasReply = false;

                es.onmessage = (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        console.log('📨 SSE消息:', data.type, data);

                        if (data.type === 'human_verification_required') {
                            hasQuestion = true;
                            const verification = data.verification || {};
                            console.log('📢 LLM提问:', verification.description);
                            console.log('   验证ID:', verification.verification_id);
                            handleHumanVerification(verification);
                        }

                        if (data.type === 'message') {
                            hasReply = true;
                            console.log('💬 LLM回复:', data.content);
                            // 也显示 LLM 的回复消息
                            addMessage('assistant', data.content || '');
                        }

                        if (data.type === 'done') {
                            es.close();
                            console.log('✅ 测试完成！');

                            // 验证链路
                            if (hasQuestion && hasReply) {
                                console.log('🎉 完整链路验证成功：LLM 成功提问并基于回答生成了内容！');
                                showSuccess(window.t ? window.t('success_test_passed') : '🎉 测试成功！LLM 完整链路验证通过！');
                            } else {
                                console.warn('⚠️ 链路验证不完整:', { hasQuestion, hasReply });
                            }
                        }
                    } catch (err) {
                        console.error('❌ 解析 SSE 消息失败:', err);
                    }
                };

                es.onerror = (e) => {
                    console.error('❌ SSE 连接错误:', e);
                    es.close();
                };

            } catch (error) {
                console.error('❌ 测试过程发生错误:', error);
                showError((window.t ? window.t('error_test_error', {error: error.message}) : '测试过程发生错误: ' + error.message));
            } finally {
                debugBtn.disabled = false;
                debugBtn.textContent = '🧪 测试';
            }
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const sidebar = document.getElementById('file-sidebar');
                const overlay = document.getElementById('file-sidebar-overlay');
                if (sidebar && sidebar.classList.contains('open')) {
                    sidebar.classList.remove('open');
                    overlay.classList.remove('active');
                    document.body.style.overflow = '';
                }
                closeModelSettingsPanel();
            }
        });

        document.addEventListener('DOMContentLoaded', () => {
            const dropZone = document.getElementById('script-drop-zone');
            const fileInput = document.getElementById('import-script-file');

            if (dropZone && fileInput) {
                fileInput.addEventListener('change', (e) => {
                    readScriptFile(e.target.files[0]);
                    e.target.value = '';
                });

                dropZone.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropZone.classList.add('drag-over');
                });

                dropZone.addEventListener('dragleave', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropZone.classList.remove('drag-over');
                });

                dropZone.addEventListener('drop', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropZone.classList.remove('drag-over');
                    const file = e.dataTransfer.files[0];
                    readScriptFile(file);
                });
            }
        });

        // ========== 语言切换器初始化 ==========
        function initLanguageSwitcher() {
            const container = document.getElementById('i18n-switcher-container');
            if (!container) return;

            const currentLocale = localStorage.getItem('zjt_locale') || 'zh-CN';
            const isEnglish = currentLocale === 'en';

            // 创建切换按钮
            const btn = document.createElement('button');
            btn.className = 'i18n-switcher-btn';
            btn.innerHTML = isEnglish ? '中文' : 'English';
            btn.title = isEnglish ? '切换为中文' : 'Switch to English';
            btn.style.cssText = `
                padding: 6px 12px;
                border: 1px solid var(--border-color, #d1d5db);
                background: var(--bg-primary, #ffffff);
                color: var(--text-primary, #1f2937);
                border-radius: 6px;
                cursor: pointer;
                font-size: 13px;
                transition: all 0.3s ease;
                white-space: nowrap;
            `;

            btn.onmouseover = () => {
                btn.style.backgroundColor = 'var(--bg-hover, #f3f4f6)';
            };
            btn.onmouseout = () => {
                btn.style.backgroundColor = 'var(--bg-primary, #ffffff)';
            };

            btn.onclick = async () => {
                // 每次点击时重新获取当前语言，而不是使用闭包中的变量
                const currentLocale = localStorage.getItem('zjt_locale') || 'zh-CN';
                const newLocale = currentLocale === 'en' ? 'zh-CN' : 'en';
                localStorage.setItem('zjt_locale', newLocale);
                await ZJTi18n.setLocale(newLocale, ['common', 'index']);
                // 更新HTML lang属性
                document.documentElement.lang = newLocale === 'en' ? 'en' : 'zh-CN';
                // 更新按钮文本
                btn.innerHTML = newLocale === 'en' ? '中文' : 'English';
                btn.title = newLocale === 'en' ? '切换为中文' : 'Switch to English';
                // 重新扫描并翻译 DOM
                if (window.ZJTi18nDOM && window.ZJTi18nDOM.scanDOM) {
                    window.ZJTi18nDOM.scanDOM(document);
                }
                // 重新渲染轮播卡片
                renderCarousel();
                initCarousel();
            };

            container.appendChild(btn);
        }

        // 监听语言变化事件，更新动态设置的文本值
        if (window.ZJTi18n) {
            window.ZJTi18n.on('locale-changed', () => {
                updateInterventionLevelDisplay();
                // 如果没有选择世界，更新占位符和状态文本
                if (!window.WORLD_ID) {
                    const messageInput = document.getElementById('message-input');
                    if (messageInput && messageInput.disabled) {
                        messageInput.placeholder = window.t('world_placeholder');
                    }
                    // 更新状态显示
                    updateStatus(window.t('no_world_selected'));
                    // 更新世界名称显示
                    const worldNameDisplay = document.getElementById('world-name-display');
                    if (worldNameDisplay) {
                        worldNameDisplay.textContent = window.t('world_not_selected');
                    }
                }
            });
        }

