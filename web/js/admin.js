/**
 * 管理后台 JavaScript
 */

const AdminApp = {
    data() {
        return {
            // 认证
            authToken: '',
            adminUser: null,
            
            // 当前页面
            currentPage: 'dashboard',
            
            // 仪表盘数据
            dashboard: {
                totalUsers: 0,
                activeWorkflows3d: 0,
                loading: true
            },
            
            // 用户列表
            users: {
                list: [],
                total: 0,
                page: 1,
                pageSize: 20,
                loading: false,
                keyword: '',
                statusFilter: '',
                roleFilter: ''
            },
            
            // 算力调整弹窗
            powerModal: {
                show: false,
                userId: null,
                userName: '',
                currentPower: 0,
                amount: 0,
                reason: '',
                loading: false
            },
            
            // 用户详情弹窗
            userDetailModal: {
                show: false,
                user: null,
                loading: false
            },
            
            // 系统配置列表
            config: {
                list: [],
                total: 0,
                page: 1,
                pageSize: 50,
                loading: false,
                keyword: '',
                initLoading: false,
                reloadLoading: false
            },
            
            // 配置编辑弹窗
            configEditModal: {
                show: false,
                configId: null,
                configKey: '',
                value: '',
                boolValue: false,
                valueType: 'string',
                description: '',
                isSensitive: false,
                loading: false
            },
            
            // 配置历史弹窗
            configHistoryModal: {
                show: false,
                configKey: '',
                list: [],
                loading: false
            },
            
            // 敏感配置值查看弹窗
            sensitiveValueModal: {
                show: false,
                configKey: '',
                value: ''
            },
            
            // 快速配置弹窗
            quickConfigModal: {
                show: false,
                loading: false,
                testLoading: false,
                testResult: null,
                duomi: {
                    token: ''
                },
                google: {
                    apiKey: '',
                    baseUrl: ''
                },
                runninghub: {
                    apiKey: ''
                },
                vidu: {
                    token: ''
                }
            },
            
            // 使用手册引导弹窗
            guideModal: {
                show: false
            },
            
            // 使用手册链接
            userManualUrl: 'https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe',
            
            // Toast消息
            toast: {
                show: false,
                message: '',
                type: 'success'
            }
        };
    },
    
    computed: {
        totalPages() {
            return Math.ceil(this.users.total / this.users.pageSize);
        },
        
        configTotalPages() {
            return Math.ceil(this.config.total / this.config.pageSize);
        },
        
        maskedPhone() {
            if (!this.adminUser || !this.adminUser.phone) return '';
            const phone = this.adminUser.phone;
            if (phone.length !== 11) return phone;
            return phone.substring(0, 3) + '****' + phone.substring(7);
        }
    },
    
    mounted() {
        this.initAuth();
    },
    
    methods: {
        // 初始化认证
        initAuth() {
            this.authToken = localStorage.getItem('auth_token') || '';
            
            if (!this.authToken) {
                this.showToast('请先登录', 'error');
                setTimeout(() => {
                    window.location.href = '/?login=1&redirect_url=/admin';
                }, 1500);
                return;
            }
            
            // 验证管理员权限
            this.verifyAdmin();
        },
        
        // 验证管理员权限
        async verifyAdmin() {
            try {
                const response = await axios.get('/api/admin/dashboard', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    // 获取当前用户信息
                    const phone = localStorage.getItem('phone') || '';
                    this.adminUser = { phone };
                    
                    // 加载仪表盘数据
                    this.dashboard.totalUsers = response.data.data.total_users;
                    this.dashboard.activeWorkflows3d = response.data.data.active_workflows_3d;
                    this.dashboard.loading = false;
                    
                    // 默认加载用户列表
                    this.loadUsers();
                    
                    // 检查 URL 参数，是否需要自动打开快速配置
                    this.checkQuickConfigParam();
                }
            } catch (error) {
                console.error('Admin verification failed:', error);
                const detail = error?.response?.data?.detail || '';
                if (detail.includes('管理员权限') || error?.response?.status === 403) {
                    this.showToast('您没有管理员权限', 'error');
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1500);
                } else if (error?.response?.status === 401) {
                    this.showToast('登录已过期，请重新登录', 'error');
                    setTimeout(() => {
                        window.location.href = '/?login=1&redirect_url=/admin';
                    }, 1500);
                } else {
                    this.showToast('加载失败: ' + detail, 'error');
                }
            }
        },
        
        // 检查 URL 参数是否需要打开快速配置
        checkQuickConfigParam() {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('quick_config') === '1') {
                // 切换到系统配置页面
                this.switchPage('config');
                // 延迟打开快速配置弹窗（等待配置列表加载）
                setTimeout(() => {
                    this.openQuickConfigModal();
                    // 显示欢迎提示
                    this.showToast('🎉 欢迎！您是系统首位管理员，请先完成快速配置', 'success');
                }, 500);
                // 清除 URL 参数
                window.history.replaceState({}, document.title, '/admin');
            }
        },
        
        // 切换页面
        switchPage(page) {
            this.currentPage = page;
            if (page === 'dashboard') {
                this.loadDashboard();
            } else if (page === 'users') {
                this.loadUsers();
            } else if (page === 'config') {
                this.loadConfigs();
            }
        },
        
        // 加载仪表盘
        async loadDashboard() {
            this.dashboard.loading = true;
            try {
                const response = await axios.get('/api/admin/dashboard', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.dashboard.totalUsers = response.data.data.total_users;
                    this.dashboard.activeWorkflows3d = response.data.data.active_workflows_3d;
                }
            } catch (error) {
                console.error('Load dashboard failed:', error);
                this.showToast('加载仪表盘失败', 'error');
            } finally {
                this.dashboard.loading = false;
            }
        },
        
        // 加载用户列表
        async loadUsers() {
            this.users.loading = true;
            try {
                const params = {
                    page: this.users.page,
                    page_size: this.users.pageSize
                };
                
                if (this.users.keyword) {
                    params.keyword = this.users.keyword;
                }
                if (this.users.statusFilter !== '') {
                    params.status = parseInt(this.users.statusFilter);
                }
                if (this.users.roleFilter) {
                    params.role = this.users.roleFilter;
                }
                
                const response = await axios.get('/api/admin/users', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params
                });
                
                if (response.data.code === 0) {
                    this.users.list = response.data.data.data;
                    this.users.total = response.data.data.total;
                }
            } catch (error) {
                console.error('Load users failed:', error);
                this.showToast('加载用户列表失败', 'error');
            } finally {
                this.users.loading = false;
            }
        },
        
        // 搜索用户
        searchUsers() {
            this.users.page = 1;
            this.loadUsers();
        },
        
        // 翻页
        goToPage(page) {
            if (page < 1 || page > this.totalPages) return;
            this.users.page = page;
            this.loadUsers();
        },
        
        // 查看用户详情
        async viewUserDetail(userId) {
            this.userDetailModal.loading = true;
            this.userDetailModal.show = true;
            
            try {
                const response = await axios.get(`/api/admin/users/${userId}`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.userDetailModal.user = response.data.data;
                }
            } catch (error) {
                console.error('Load user detail failed:', error);
                this.showToast('加载用户详情失败', 'error');
                this.userDetailModal.show = false;
            } finally {
                this.userDetailModal.loading = false;
            }
        },
        
        // 关闭用户详情弹窗
        closeUserDetailModal() {
            this.userDetailModal.show = false;
            this.userDetailModal.user = null;
        },
        
        // 更新用户状态
        async updateUserStatus(userId, currentStatus) {
            const newStatus = currentStatus === 1 ? 0 : 1;
            const action = newStatus === 0 ? '禁用' : '启用';
            
            if (!confirm(`确定要${action}该用户吗？`)) {
                return;
            }
            
            try {
                const response = await axios.put(`/api/admin/users/${userId}/status`, 
                    { status: newStatus },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    this.showToast(`${action}成功`, 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Update user status failed:', error);
                const detail = error?.response?.data?.detail || '操作失败';
                this.showToast(detail, 'error');
            }
        },
        
        // 更新用户角色
        async updateUserRole(userId, currentRole) {
            const newRole = currentRole === 'admin' ? 'user' : 'admin';
            const action = newRole === 'admin' ? '设为管理员' : '取消管理员';
            
            if (!confirm(`确定要${action}吗？`)) {
                return;
            }
            
            try {
                const response = await axios.put(`/api/admin/users/${userId}/role`, 
                    { role: newRole },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    this.showToast(`${action}成功`, 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Update user role failed:', error);
                const detail = error?.response?.data?.detail || '操作失败';
                this.showToast(detail, 'error');
            }
        },
        
        // 打开算力调整弹窗
        openPowerModal(user) {
            this.powerModal.userId = user.user_id;
            this.powerModal.userName = user.phone;
            this.powerModal.currentPower = user.computing_power || 0;
            this.powerModal.amount = 0;
            this.powerModal.reason = '';
            this.powerModal.show = true;
        },
        
        // 关闭算力调整弹窗
        closePowerModal() {
            this.powerModal.show = false;
            this.powerModal.userId = null;
            this.powerModal.userName = '';
            this.powerModal.currentPower = 0;
            this.powerModal.amount = 0;
            this.powerModal.reason = '';
        },
        
        // 提交算力调整
        async submitPowerAdjust() {
            if (!this.powerModal.reason.trim()) {
                this.showToast('请填写调整原因', 'error');
                return;
            }
            
            if (this.powerModal.amount === 0) {
                this.showToast('调整数量不能为0', 'error');
                return;
            }
            
            this.powerModal.loading = true;
            
            try {
                const response = await axios.post(
                    `/api/admin/users/${this.powerModal.userId}/power`,
                    {
                        amount: parseInt(this.powerModal.amount),
                        reason: this.powerModal.reason.trim()
                    },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    const data = response.data.data;
                    this.showToast(`算力调整成功: ${data.old_power} → ${data.new_power}`, 'success');
                    this.closePowerModal();
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Adjust power failed:', error);
                const detail = error?.response?.data?.detail || '调整失败';
                this.showToast(detail, 'error');
            } finally {
                this.powerModal.loading = false;
            }
        },
        
        // 退出登录
        logout() {
            if (!confirm('确定要退出登录吗？')) {
                return;
            }
            
            localStorage.removeItem('auth_token');
            localStorage.removeItem('phone');
            localStorage.removeItem('user_id');
            localStorage.removeItem('admin_mode');
            window.location.href = '/';
        },
        
        // 显示Toast消息
        showToast(message, type = 'success') {
            this.toast.message = message;
            this.toast.type = type;
            this.toast.show = true;
            
            setTimeout(() => {
                this.toast.show = false;
            }, 3000);
        },
        
        // 格式化日期
        formatDate(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        },
        
        // 格式化手机号
        formatPhone(phone) {
            if (!phone || phone.length !== 11) return phone || '-';
            return phone.substring(0, 3) + '****' + phone.substring(7);
        },
        
        // ==================== 配置管理方法 ====================
        
        // 加载配置列表
        async loadConfigs() {
            this.config.loading = true;
            try {
                const params = {
                    page: this.config.page,
                    page_size: this.config.pageSize
                };
                
                if (this.config.keyword) {
                    params.keyword = this.config.keyword;
                }
                
                const response = await axios.get('/api/admin/config', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params
                });
                
                if (response.data.code === 0) {
                    this.config.list = response.data.data.data;
                    this.config.total = response.data.data.total;
                }
            } catch (error) {
                console.error('Load configs failed:', error);
                this.showToast('加载配置列表失败', 'error');
            } finally {
                this.config.loading = false;
            }
        },
        
        // 搜索配置
        searchConfigs() {
            this.config.page = 1;
            this.loadConfigs();
        },
        
        // 配置翻页
        goToConfigPage(page) {
            if (page < 1 || page > this.configTotalPages) return;
            this.config.page = page;
            this.loadConfigs();
        },
        
        // 初始化配置
        async initConfigs() {
            if (!confirm('确定要初始化配置吗？这将从配置文件导入默认配置到数据库（仅新增，不覆盖已存在的配置）')) {
                return;
            }
            
            this.config.initLoading = true;
            try {
                const response = await axios.post('/api/admin/config/init', {}, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.showToast(response.data.message, 'success');
                    this.loadConfigs();
                }
            } catch (error) {
                console.error('Init configs failed:', error);
                const detail = error?.response?.data?.detail || '初始化失败';
                this.showToast(detail, 'error');
            } finally {
                this.config.initLoading = false;
            }
        },
        
        // 刷新配置缓存
        async reloadConfigs() {
            this.config.reloadLoading = true;
            try {
                const response = await axios.post('/api/admin/config/reload', {}, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.showToast('配置缓存已刷新', 'success');
                }
            } catch (error) {
                console.error('Reload configs failed:', error);
                const detail = error?.response?.data?.detail || '刷新失败';
                this.showToast(detail, 'error');
            } finally {
                this.config.reloadLoading = false;
            }
        },
        
        // 格式化配置值显示
        formatConfigValue(value) {
            if (value === null || value === undefined) return '-';
            const str = String(value);
            if (str.length > 50) {
                return str.substring(0, 50) + '...';
            }
            return str;
        },
        
        // 打开配置编辑弹窗
        openConfigEditModal(item) {
            this.configEditModal.configId = item.id;
            this.configEditModal.configKey = item.config_key;
            this.configEditModal.valueType = item.value_type;
            this.configEditModal.description = item.description || '';
            this.configEditModal.isSensitive = item.is_sensitive;
            
            // 根据类型设置值
            if (item.value_type === 'bool') {
                const val = String(item.config_value).toLowerCase();
                this.configEditModal.boolValue = val === 'true' || val === '1';
                this.configEditModal.value = '';
            } else {
                this.configEditModal.value = item.config_value !== null ? String(item.config_value) : '';
                this.configEditModal.boolValue = false;
            }
            
            this.configEditModal.show = true;
        },
        
        // 关闭配置编辑弹窗
        closeConfigEditModal() {
            this.configEditModal.show = false;
            this.configEditModal.configId = null;
            this.configEditModal.configKey = '';
            this.configEditModal.value = '';
            this.configEditModal.boolValue = false;
            this.configEditModal.valueType = 'string';
            this.configEditModal.description = '';
            this.configEditModal.isSensitive = false;
        },
        
        // 提交配置编辑
        async submitConfigEdit() {
            let value = this.configEditModal.value;
            
            // 布尔类型特殊处理
            if (this.configEditModal.valueType === 'bool') {
                value = this.configEditModal.boolValue ? 'true' : 'false';
            }
            
            // JSON类型校验
            if (this.configEditModal.valueType === 'json') {
                try {
                    JSON.parse(value);
                } catch (e) {
                    this.showToast('JSON格式不正确', 'error');
                    return;
                }
            }
            
            this.configEditModal.loading = true;
            try {
                const response = await axios.put(
                    `/api/admin/config/${this.configEditModal.configKey}`,
                    { value: value },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    this.showToast('配置更新成功', 'success');
                    this.closeConfigEditModal();
                    this.loadConfigs();
                }
            } catch (error) {
                console.error('Update config failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
            } finally {
                this.configEditModal.loading = false;
            }
        },
        
        // 查看配置历史
        async viewConfigHistory(item) {
            this.configHistoryModal.configKey = item.config_key;
            this.configHistoryModal.loading = true;
            this.configHistoryModal.show = true;
            
            try {
                const response = await axios.get(`/api/admin/config/${item.config_key}`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.configHistoryModal.list = response.data.data.history || [];
                }
            } catch (error) {
                console.error('Load config history failed:', error);
                this.showToast('加载配置历史失败', 'error');
                this.configHistoryModal.show = false;
            } finally {
                this.configHistoryModal.loading = false;
            }
        },
        
        // 关闭配置历史弹窗
        closeConfigHistoryModal() {
            this.configHistoryModal.show = false;
            this.configHistoryModal.configKey = '';
            this.configHistoryModal.list = [];
        },
        
        // 脱敏敏感配置值
        maskSensitiveValue(value) {
            if (!value || value.length <= 8) {
                return '********';
            }
            return value.substring(0, 4) + '****' + value.substring(value.length - 4);
        },
        
        // 弹框显示敏感配置值（从后端获取完整值）
        async showSensitiveValue(item) {
            try {
                const response = await axios.get('/api/admin/config/raw', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params: { key: item.config_key }
                });
                
                if (response.data.code === 0) {
                    this.sensitiveValueModal.configKey = item.config_key;
                    this.sensitiveValueModal.value = response.data.data.config_value || '';
                    this.sensitiveValueModal.show = true;
                }
            } catch (error) {
                console.error('Failed to get raw config value:', error);
                this.showToast('获取配置值失败', 'error');
            }
        },
        
        // 关闭敏感配置值弹窗
        closeSensitiveValueModal() {
            this.sensitiveValueModal.show = false;
            this.sensitiveValueModal.configKey = '';
            this.sensitiveValueModal.value = '';
        },
        
        // 复制敏感配置值
        copySensitiveValue() {
            const input = document.getElementById('sensitiveValueInput');
            if (input) {
                input.select();
                document.execCommand('copy');
                this.showToast('已复制到剪贴板', 'success');
            }
        },
        
        // ==================== 快速配置方法 ====================
        
        // 打开快速配置弹窗
        async openQuickConfigModal() {
            this.quickConfigModal.show = true;
            this.quickConfigModal.testResult = null;
            
            // 从后端获取快速配置项列表并加载现有配置值
            try {
                // 获取快速配置项列表
                const quickConfigsResp = await axios.get('/api/admin/config/quick-configs', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (quickConfigsResp.data.code === 0) {
                    const configs = quickConfigsResp.data.data.configs || [];
                    
                    // 根据配置项列表加载现有值
                    for (const config of configs) {
                        try {
                            const response = await axios.get('/api/admin/config/raw', {
                                headers: { 'Authorization': `Bearer ${this.authToken}` },
                                params: { key: config.key }
                            });
                            
                            if (response.data.code === 0) {
                                const value = response.data.data.config_value || '';
                                // 根据 key 映射到对应的表单字段
                                if (config.key === 'duomi.token') {
                                    this.quickConfigModal.duomi.token = value;
                                } else if (config.key === 'llm.google.api_key') {
                                    this.quickConfigModal.google.apiKey = value;
                                } else if (config.key === 'llm.google.gemini_base_url') {
                                    this.quickConfigModal.google.baseUrl = value;
                                } else if (config.key === 'runninghub.api_key') {
                                    this.quickConfigModal.runninghub.apiKey = value;
                                } else if (config.key === 'vidu.token') {
                                    this.quickConfigModal.vidu.token = value;
                                }
                            }
                        } catch (e) {
                            // 配置可能不存在，忽略错误
                            console.log(`Config ${config.key} not found, will create on save`);
                        }
                    }
                }
            } catch (error) {
                console.error('Failed to load quick config values:', error);
            }
        },
        
        // 关闭快速配置弹窗
        closeQuickConfigModal() {
            this.quickConfigModal.show = false;
            this.quickConfigModal.loading = false;
            this.quickConfigModal.testLoading = false;
            this.quickConfigModal.testResult = null;
            this.quickConfigModal.duomi.token = '';
            this.quickConfigModal.google.apiKey = '';
            this.quickConfigModal.google.baseUrl = '';
            this.quickConfigModal.runninghub.apiKey = '';
            this.quickConfigModal.vidu.token = '';
        },
        
        // 测试 Google 连接
        async testGoogleConnection() {
            this.quickConfigModal.testLoading = true;
            this.quickConfigModal.testResult = null;
            
            try {
                const response = await axios.post('/api/admin/config/test-google', {
                    api_key: this.quickConfigModal.google.apiKey,
                    base_url: this.quickConfigModal.google.baseUrl || null
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.quickConfigModal.testResult = {
                        success: true,
                        message: `✅ ${response.data.message}`
                    };
                } else {
                    this.quickConfigModal.testResult = {
                        success: false,
                        message: `❌ ${response.data.message}`
                    };
                }
            } catch (error) {
                console.error('Test Google connection failed:', error);
                const detail = error?.response?.data?.detail || '测试失败';
                this.quickConfigModal.testResult = {
                    success: false,
                    message: `❌ ${detail}`
                };
            } finally {
                this.quickConfigModal.testLoading = false;
            }
        },
        
        // 提交快速配置
        async submitQuickConfig() {
            // 构建配置列表
            const configs = [];
            
            if (this.quickConfigModal.duomi.token) {
                configs.push({ key: 'duomi.token', value: this.quickConfigModal.duomi.token });
            }
            if (this.quickConfigModal.google.apiKey) {
                configs.push({ key: 'llm.google.api_key', value: this.quickConfigModal.google.apiKey });
            }
            if (this.quickConfigModal.google.baseUrl) {
                configs.push({ key: 'llm.google.gemini_base_url', value: this.quickConfigModal.google.baseUrl });
            }
            if (this.quickConfigModal.runninghub.apiKey) {
                configs.push({ key: 'runninghub.api_key', value: this.quickConfigModal.runninghub.apiKey });
            }
            if (this.quickConfigModal.vidu.token) {
                configs.push({ key: 'vidu.token', value: this.quickConfigModal.vidu.token });
            }
            
            if (configs.length === 0) {
                this.showToast('请至少填写一项配置', 'error');
                return;
            }
            
            this.quickConfigModal.loading = true;
            
            try {
                const response = await axios.put('/api/admin/config/batch', 
                    { configs },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    const data = response.data.data;
                    const updatedCount = data.results.filter(r => r.status === 'updated').length;
                    const errors = data.errors || [];
                    
                    if (errors.length > 0) {
                        this.showToast(`部分配置更新失败: ${errors.join(', ')}`, 'error');
                    } else if (updatedCount > 0) {
                        this.showToast(`成功更新 ${updatedCount} 条配置`, 'success');
                    } else {
                        this.showToast('配置未发生变化', 'success');
                    }
                    
                    this.closeQuickConfigModal();
                    this.loadConfigs();
                    
                    // 显示使用手册引导弹窗
                    this.guideModal.show = true;
                }
            } catch (error) {
                console.error('Submit quick config failed:', error);
                const detail = error?.response?.data?.detail || '保存失败';
                this.showToast(detail, 'error');
            } finally {
                this.quickConfigModal.loading = false;
            }
        }
    }
};

// 初始化Vue应用
Vue.createApp(AdminApp).mount('#app');
