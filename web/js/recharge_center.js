/**
 * 充值中心（算力直充 + 月度订阅）
 *
 * 首页 index.html 用 Vue 自带同一套界面。工作流 / 故事板 / 营销智能体
 * 原先只有直付套餐，这里用同一套交互补上月度订阅（含入门版首期动画、
 * 升级、解约、扫码轮询）。样式见 web/css/subscription.css。
 */
(function () {
    'use strict';

    var OVERLAY_ID = 'rechargeCenterOverlay';
    var LOCAL_TIP = '只有云端环境才能开启二维码支付。本地模式下，管理员用户请进入后台增加算力，非管理员用户请通知管理员。';

    var state = {
        open: false,
        tab: 'subscription',
        onPaid: null,
        onLocalBlocked: null,
        packages: [],
        packagesLoading: false,
        packagesError: '',
        plans: [],
        plansLoading: false,
        plansError: '',
        status: null,
        selectedPackage: null,
        paymentLoading: false,
        paymentError: '',
        paymentQr: '',
        selectedPlan: null,
        subAgreed: false,
        subAgreementError: false,
        subPaymentLoading: false,
        subPaymentError: '',
        subQr: '',
        subOrderId: '',
        lastOrderIsUpgrade: false,
        subCancelling: false,
        introPhase: '',
        introGen: 0,
        introTimers: [],
        pollTimer: null,
        userIp: ''
    };

    function esc(value) {
        if (typeof window.escapeHtml === 'function') return window.escapeHtml(value);
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function money(value) {
        var n = Number(value);
        if (!isFinite(n)) return esc(value);
        return String(Math.round(n * 100) / 100);
    }

    function authToken() {
        try { return localStorage.getItem('auth_token') || ''; } catch (e) { return ''; }
    }

    function userId() {
        try { return parseInt(localStorage.getItem('user_id') || '0', 10) || 0; } catch (e) { return 0; }
    }

    function authHeaders(extra) {
        var headers = extra ? Object.assign({}, extra) : {};
        var token = authToken();
        if (token) headers.Authorization = 'Bearer ' + token;
        return headers;
    }

    // 认证统一走 authHeaders() 的 Authorization 头（红线14：token 禁止进 URL query，
    // query 会经 Referer/浏览器历史/服务端日志泄漏；后端已支持头兜底）。
    // 本函数只负责拼装非敏感 query 参数（user_id / order_id 等）。
    function apiUrl(path, extra) {
        var url = new URL(path, window.location.origin);
        if (extra) {
            Object.keys(extra).forEach(function (key) {
                if (extra[key] !== undefined && extra[key] !== null) {
                    url.searchParams.set(key, String(extra[key]));
                }
            });
        }
        return url.pathname + url.search;
    }

    function errorText(data, fallback) {
        var raw = data && (data.detail || data.error || data.message);
        if (!raw) return fallback;
        if (typeof raw === 'string') return raw;
        try { return JSON.stringify(raw); } catch (e) { return fallback; }
    }

    async function readJson(resp) {
        var data = await resp.json().catch(function () { return {}; });
        if (!resp.ok) {
            var err = new Error(errorText(data, 'HTTP ' + resp.status));
            err.status = resp.status;
            err.data = data;
            throw err;
        }
        return data;
    }

    function firstBonusEligible(status) {
        // fail-closed（#7）：资格必须由后端显式下发 true 才展示首期价。
        // 此前 !status || !== false 的兜底会让"status 查询失败/字段缺失"的老用户
        // 看到 18.8+加赠，实收却按签约记录扣 29.9（展示价 != 实收价 -> 客诉）。
        return !!(status && status.first_bonus_eligible === true);
    }

    function showsIntroPrice(plan, status) {
        return !!(plan && plan.first_period_price != null && firstBonusEligible(status));
    }

    function introPriceCut(plan) {
        var diff = (Number(plan && plan.price) || 0) - (Number(plan && plan.first_period_price) || 0);
        return Math.round(diff * 10) / 10;
    }

    function planTagline(plans, plan) {
        var lines = ['日常使用', '效率升级', '专业创作', '全能尊享'];
        var sorted = (plans || []).slice().sort(function (a, b) {
            return (a.computing_power || 0) - (b.computing_power || 0);
        });
        var idx = -1;
        for (var i = 0; i < sorted.length; i++) {
            if (sorted[i].plan_id === plan.plan_id) { idx = i; break; }
        }
        return idx >= 0 ? (lines[idx] || '') : '';
    }

    function planMultipleText(plans, plan) {
        var powers = (plans || []).map(function (p) { return Number(p.computing_power) || 0; }).filter(function (x) { return x > 0; });
        if (!powers.length) return '';
        var base = Math.min.apply(null, powers);
        if (!base || !plan.computing_power || plan.computing_power <= base) return '';
        var m = Math.round((plan.computing_power / base) * 10) / 10;
        return '≈ 基础档 ' + m + ' 倍算力';
    }

    function rechargeReferenceRate(packages) {
        var pkgs = (packages || []).filter(function (p) {
            var price = Number(p.price) || 0;
            var power = Number(p.granted_computing_power || p.computing_power) || 0;
            return price >= 1 && power > 0;
        });
        if (!pkgs.length) return 0;
        var ref = pkgs.reduce(function (a, b) { return Number(a.price) <= Number(b.price) ? a : b; });
        return (Number(ref.granted_computing_power || ref.computing_power) || 0) / (Number(ref.price) || 1);
    }

    function headlinePower(plan, withBonus) {
        var base = Number(plan && plan.computing_power) || 0;
        var bonus = withBonus ? (Number(plan && plan.first_period_bonus) || 0) : 0;
        return base + bonus;
    }

    function planExtraVsRecharge(plan, packages, status, withBonus) {
        var rate = rechargeReferenceRate(packages);
        if (!rate || !plan) return null;
        var price = showsIntroPrice(plan, status)
            ? Number(plan.first_period_price)
            : (Number(plan.price) || 0);
        var direct = Math.round(price * rate);
        var extra = headlinePower(plan, withBonus) - direct;
        return extra > 0 ? extra : 0;
    }

    function isManaging(status) {
        return !!(status && status.subscribed && (status.status === 'active' || status.status === 'upgrading'));
    }

    function upgradePlans(plans, status) {
        if (!status || (status.status !== 'active' && status.status !== 'upgrading')) return [];
        var currentId = status.plan && status.plan.plan_id;
        if (!currentId) return [];
        return (plans || []).filter(function (p) { return Number(p.plan_id) > Number(currentId); });
    }

    function isUpgradeSelection(plan, status) {
        var currentId = status && status.plan && status.plan.plan_id;
        return !!(plan && currentId && Number(plan.plan_id) > Number(currentId));
    }

    function formatDateStr(iso) {
        if (!iso) return '--';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return String(iso);
        var pad = function (n) { return String(n).padStart(2, '0'); };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }

    function introDealActive() {
        return state.introPhase === 'price' || state.introPhase === 'slash' || state.introPhase === 'power';
    }

    function clearIntro() {
        state.introGen += 1;
        (state.introTimers || []).forEach(function (id) { clearTimeout(id); });
        state.introTimers = [];
        state.introPhase = '';
    }

    function stopPoll() {
        if (state.pollTimer) {
            clearInterval(state.pollTimer);
            state.pollTimer = null;
        }
    }

    function prefersReducedMotion() {
        try {
            return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        } catch (e) {
            return false;
        }
    }

    function maybePlayIntro() {
        clearIntro();
        var intro = (state.plans || []).find(function (p) {
            return p && p.first_period_price != null && p.first_period_bonus;
        });
        var play = state.open && state.tab === 'subscription' && !state.plansLoading
            && !isManaging(state.status) && firstBonusEligible(state.status) && !!intro;
        if (!play) {
            if (state.open) render();
            return;
        }
        if (prefersReducedMotion()) {
            state.introPhase = 'done';
            render();
            return;
        }
        var gen = state.introGen;
        state.introPhase = 'price';
        render();
        var step = function (phase, delay, next) {
            var id = setTimeout(function () {
                if (state.introGen !== gen || !state.open) return;
                state.introPhase = phase;
                render();
                if (next) next();
            }, delay);
            state.introTimers.push(id);
        };
        step('slash', 700, function () { step('power', 800, function () { step('done', 900, null); }); });
    }

    function resetSession() {
        stopPoll();
        clearIntro();
        state.tab = 'subscription';
        state.packages = [];
        state.packagesLoading = true;
        state.packagesError = '';
        state.plans = [];
        state.plansLoading = true;
        state.plansError = '';
        state.status = null;
        state.selectedPackage = null;
        state.paymentLoading = false;
        state.paymentError = '';
        state.paymentQr = '';
        state.selectedPlan = null;
        state.subAgreed = false;
        state.subAgreementError = false;
        state.subPaymentLoading = false;
        state.subPaymentError = '';
        state.subQr = '';
        state.subOrderId = '';
        state.lastOrderIsUpgrade = false;
        state.subCancelling = false;
    }

    function ensureDom() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.className = 'recharge-center-overlay';
        overlay.hidden = true;
        overlay.innerHTML = ''
            + '<div class="recharge-center-root" role="dialog" aria-modal="true" aria-label="充值中心">'
            + '  <button type="button" class="rc-close" data-rc-action="close" aria-label="关闭">×</button>'
            + '  <div class="rc-title">充值中心</div>'
            + '  <div data-rc-body></div>'
            + '</div>';
        overlay.addEventListener('click', function (event) {
            if (event.target === overlay) close();
        });
        var root = overlay.querySelector('.recharge-center-root');
        root.addEventListener('click', onRootClick);
        root.addEventListener('change', onRootChange);
        document.body.appendChild(overlay);
        return overlay;
    }

    function onRootChange(event) {
        var input = event.target;
        if (!input || input.getAttribute('data-rc-action') !== 'toggle-agree') return;
        state.subAgreed = !!input.checked;
        if (state.subAgreed) state.subAgreementError = false;
        render();
    }

    function onRootClick(event) {
        var el = event.target && event.target.closest ? event.target.closest('[data-rc-action]') : null;
        if (!el) return;
        var action = el.getAttribute('data-rc-action');
        if (action === 'close') {
            close();
            return;
        }
        if (action === 'switch-tab') {
            switchTab(el.getAttribute('data-tab'));
            return;
        }
        if (action === 'select-plan') {
            selectPlan(el.getAttribute('data-plan-id'));
            return;
        }
        if (action === 'create-sub-order') {
            createSubscriptionOrder();
            return;
        }
        if (action === 'back-sub') {
            backToSubPlan();
            return;
        }
        if (action === 'refresh-status') {
            refreshStatus({ busy: true });
            return;
        }
        if (action === 'cancel-sub') {
            cancelSubscription();
            return;
        }
        if (action === 'select-package') {
            selectPackage(el.getAttribute('data-package-id'));
            return;
        }
        if (action === 'reload-plans') {
            loadPlans();
            return;
        }
        if (action === 'back-packages' || action === 'retry-packages') {
            state.selectedPackage = null;
            state.paymentError = '';
            state.paymentQr = '';
            state.paymentLoading = false;
            if (action === 'retry-packages' || !state.packages.length) loadPackages();
            else render();
            return;
        }
        if (action === 'retry-pay') {
            createPaymentOrder();
        }
    }

    function switchTab(tab) {
        if (tab !== 'power' && tab !== 'subscription') return;
        state.tab = tab;
        if (tab === 'subscription') maybePlayIntro();
        else {
            clearIntro();
            render();
        }
    }

    function findPlan(planId) {
        var id = String(planId);
        return (state.plans || []).find(function (p) { return String(p.plan_id) === id; }) || null;
    }

    function selectPlan(planId) {
        var plan = findPlan(planId);
        if (!plan) return;
        stopPoll();
        state.selectedPlan = plan;
        state.subAgreed = false;
        state.subAgreementError = false;
        state.subPaymentError = '';
        state.subQr = '';
        state.subOrderId = '';
        render();
    }

    function backToSubPlan() {
        stopPoll();
        state.selectedPlan = null;
        state.subQr = '';
        state.subPaymentError = '';
        state.subOrderId = '';
        render();
    }

    function notifyPaid() {
        var cb = state.onPaid;
        if (typeof cb !== 'function') return;
        setTimeout(function () {
            try { cb(); } catch (e) { console.error(e); }
        }, 2000);
    }

    function isWechatBrowser() {
        return /micromessenger/i.test(navigator.userAgent || '');
    }

    function wechatOpenid() {
        try { return localStorage.getItem('wechat_openid') || ''; } catch (e) { return ''; }
    }

    async function ensureIp() {
        if (state.userIp) return state.userIp;
        var timer = null;
        try {
            var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
            timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 5000);
            var resp = await fetch('https://api.ipify.org?format=json', ctrl ? { signal: ctrl.signal } : undefined);
            var data = await resp.json();
            state.userIp = (data && data.ip) || '0.0.0.0';
        } catch (e) {
            state.userIp = '0.0.0.0';
        } finally {
            if (timer) clearTimeout(timer);
        }
        return state.userIp;
    }

    function maskedPhone() {
        var phone = '';
        try { phone = localStorage.getItem('phone') || ''; } catch (e) { phone = ''; }
        return phone.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2');
    }

    function invokeJsapi(params, handlers) {
        if (typeof WeixinJSBridge === 'undefined') {
            handlers.onError('请在微信中打开');
            return;
        }
        WeixinJSBridge.invoke('getBrandWCPayRequest', {
            appId: params.appId,
            timeStamp: params.timeStamp,
            nonceStr: params.nonceStr,
            package: params.package,
            signType: params.signType,
            paySign: params.paySign
        }, function (res) {
            var msg = res && res.err_msg;
            if (msg === 'get_brand_wcpay_request:ok') handlers.onOk();
            else if (msg === 'get_brand_wcpay_request:cancel') handlers.onError('支付已取消');
            else handlers.onError('支付失败: ' + (msg || ''));
        });
    }

    async function loadPackages() {
        state.packagesLoading = true;
        state.packagesError = '';
        render();
        try {
            var resp = await fetch('/api/recharge/packages', { headers: authHeaders() });
            var data = await readJson(resp);
            state.packages = data.packages || [];
        } catch (e) {
            console.error('加载充值套餐失败:', e);
            state.packagesError = e.message || '加载套餐失败';
            state.packages = [];
        } finally {
            state.packagesLoading = false;
            if (state.open) render();
        }
    }

    async function loadPlans() {
        state.plansLoading = true;
        state.plansError = '';
        if (state.open) render();
        try {
            var resp = await fetch(apiUrl('/api/subscription/plans'), { headers: authHeaders() });
            var data = await readJson(resp);
            if (data.success) {
                state.plans = data.plans || [];
                state.status = data.subscription || null;
            } else {
                state.plansError = data.message || '加载订阅套餐失败';
            }
        } catch (e) {
            console.error('加载订阅套餐失败:', e);
            state.plansError = e.message || '加载订阅套餐失败';
        } finally {
            state.plansLoading = false;
            if (state.open) maybePlayIntro();
        }
    }

    async function refreshStatus(opts) {
        var busy = !opts || opts.busy !== false;
        if (!authToken() || !userId()) return;
        if (busy) state.subCancelling = true;
        if (state.open) render();
        try {
            var resp = await fetch(apiUrl('/api/subscription/status', { user_id: userId() }), { headers: authHeaders() });
            var data = await readJson(resp);
            if (data.success) state.status = data.subscription || null;
        } catch (e) {
            console.error('刷新订阅状态失败:', e);
        } finally {
            if (busy) state.subCancelling = false;
            if (state.open) render();
        }
    }

    function startSubPayPolling() {
        stopPoll();
        state.pollTimer = setInterval(async function () {
            if (!state.open || !state.subOrderId) {
                stopPoll();
                return;
            }
            try {
                var resp = await fetch(apiUrl('/api/subscription/order-status', {
                    order_id: state.subOrderId,
                    user_id: userId()
                }), { headers: authHeaders() });
                var data = await readJson(resp);
                if (data && data.success && data.paid) {
                    stopPoll();
                    state.subOrderId = '';
                    var upgraded = state.lastOrderIsUpgrade;
                    window.alert(upgraded
                        ? '支付成功！套餐升级已生效，新套餐算力稍后到账'
                        : '支付成功！订阅已生效，算力稍后到账');
                    state.selectedPlan = null;
                    state.subQr = '';
                    await refreshStatus({ busy: false });
                    notifyPaid();
                }
            } catch (e) { /* 单次失败下一轮继续 */ }
        }, 3000);
    }

    async function createSubscriptionOrder() {
        if (!state.selectedPlan) return;
        if (!authToken() || !userId()) {
            window.alert('请先登录');
            close();
            return;
        }
        if (!state.subAgreed) {
            state.subAgreementError = true;
            render();
            return;
        }
        state.subPaymentLoading = true;
        state.subPaymentError = '';
        state.subQr = '';
        stopPoll();
        render();
        var isWechat = isWechatBrowser() && !!wechatOpenid();
        await ensureIp();
        try {
            var body = {
                subscription_plan_id: state.selectedPlan.plan_id,
                user_id: userId(),
                auth_token: authToken(),
                is_wechat_browser: isWechat,
                payment_ip: state.userIp || '0.0.0.0',
                display_name: maskedPhone()
            };
            if (isWechat) body.openid = wechatOpenid();
            var resp = await fetch('/api/subscription/wechat-sign-pay', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            });
            var data = await readJson(resp);
            if (!state.open) return;
            if (data.success) {
                state.subOrderId = data.order_id || '';
                state.lastOrderIsUpgrade = !!data.upgrade;
                if (data.payment_type === 'JSAPI') {
                    invokeJsapi(data.jsapi_params || {}, {
                        onOk: function () {
                            window.alert(state.lastOrderIsUpgrade
                                ? '支付成功！套餐升级将在确认后生效，新套餐算力稍后到账'
                                : '支付成功！订阅将在确认后生效，算力稍后到账');
                            state.selectedPlan = null;
                            refreshStatus({ busy: false });
                            notifyPaid();
                        },
                        onError: function (msg) {
                            state.subPaymentError = msg;
                            if (state.open) render();
                        }
                    });
                } else if (!data.code_url) {
                    state.subPaymentError = '未获取到支付二维码，请重试';
                } else {
                    state.subQr = 'https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=' + encodeURIComponent(data.code_url);
                    startSubPayPolling();
                }
            } else {
                state.subPaymentError = data.message || '创建订阅订单失败';
            }
        } catch (e) {
            console.error('创建订阅订单失败:', e);
            if (e.status !== 401) state.subPaymentError = e.message || '创建订阅订单失败，请重试';
            else window.alert('登录已过期，请重新登录');
        } finally {
            state.subPaymentLoading = false;
            if (state.open) render();
        }
    }

    async function cancelSubscription() {
        if (!window.confirm('确定取消月度订阅吗？\n取消后当期权益保留至周期结束，之后不再自动扣费。')) return;
        state.subCancelling = true;
        render();
        try {
            var resp = await fetch('/api/subscription/cancel', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ user_id: userId(), auth_token: authToken() })
            });
            var data = await readJson(resp);
            if (data.success) {
                window.alert('订阅已取消');
                await refreshStatus({ busy: false });
            } else {
                window.alert(data.message || '取消订阅失败');
            }
        } catch (e) {
            console.error('取消订阅失败:', e);
            window.alert(e.message || '取消订阅失败，请稍后重试');
        } finally {
            state.subCancelling = false;
            if (state.open) render();
        }
    }

    function selectPackage(packageId) {
        var id = String(packageId);
        var pkg = (state.packages || []).find(function (p) { return String(p.package_id) === id; });
        if (!pkg) return;
        if (!authToken() || !userId()) {
            window.alert('请先登录');
            close();
            return;
        }
        state.selectedPackage = pkg;
        state.paymentError = '';
        state.paymentQr = '';
        createPaymentOrder();
    }

    async function createPaymentOrder() {
        if (!state.selectedPackage) return;
        state.paymentLoading = true;
        state.paymentError = '';
        state.paymentQr = '';
        render();
        var isWechat = isWechatBrowser() && !!wechatOpenid();
        await ensureIp();
        try {
            var body = {
                package_id: state.selectedPackage.package_id,
                user_id: userId(),
                auth_token: authToken(),
                is_wechat_browser: isWechat,
                payment_ip: state.userIp || '0.0.0.0'
            };
            if (isWechat) body.openid = wechatOpenid();
            var resp = await fetch('/api/recharge/wechat-pay', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            });
            var data = await readJson(resp);
            if (!state.open) return;
            if (data.payment_type === 'JSAPI' || (data.jsapi_params && !data.code_url)) {
                invokeJsapi(data.jsapi_params || {}, {
                    onOk: function () {
                        window.alert('支付成功！算力将在几秒内到账');
                        notifyPaid();
                        close();
                    },
                    onError: function (msg) {
                        state.paymentError = msg;
                        if (state.open) render();
                    }
                });
            } else if (data.code_url) {
                state.paymentQr = 'https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=' + encodeURIComponent(data.code_url);
            } else {
                state.paymentError = data.message || data.error || '创建支付订单失败';
            }
        } catch (e) {
            console.error('创建支付订单失败:', e);
            state.paymentError = e.message || '创建支付订单失败，请重试';
        } finally {
            state.paymentLoading = false;
            if (state.open) render();
        }
    }

    function renderTabs() {
        return ''
            + '<div class="recharge-tabs">'
            + '<button type="button" class="recharge-tab' + (state.tab === 'power' ? ' active' : '') + '" data-rc-action="switch-tab" data-tab="power">算力充值</button>'
            + '<button type="button" class="recharge-tab' + (state.tab === 'subscription' ? ' active' : '') + '" data-rc-action="switch-tab" data-tab="subscription">月度订阅</button>'
            + '</div>';
    }

    function renderIntroBanners() {
        var status = state.status;
        var html = '';
        if (!status || (!status.subscribed && status.status !== 'terminated')) {
            html += '<div class="package-intro"><p class="package-intro-text">会员订阅</p><p class="package-intro-subtext">选择适合您的月度创作套餐，自动续费可随时取消</p></div>';
        }
        if (status && status.status === 'terminated' && status.sign_not_effective) {
            html += '<div class="package-intro package-intro-warning"><p class="package-intro-text">本月会员已付费，算力权益保留至 ' + esc(formatDateStr(status.current_period_end)) + '</p><p class="package-intro-subtext">您尚未开通「每月自动续费」，到期后订阅优惠将中断；重新开通订阅即可持续享受会员优惠</p></div>';
        } else if (status && status.status === 'terminated') {
            html += '<div class="package-intro"><p class="package-intro-text">您已取消订阅，当期权益保留至 ' + esc(formatDateStr(status.current_period_end)) + '</p><p class="package-intro-subtext">重新订阅立即生效并重新计算周期；入门版首次开通首月 ¥18.8 并多 40 算力，已订阅过的用户按 ¥29.9、不再加赠。其他档首订加赠同样仅限首次订阅</p></div>';
        }
        return html;
    }

    function renderSigningBanner() {
        var status = state.status;
        if (!status || status.status !== 'signing') return '';
        return ''
            + '<div class="sub-status-card" style="margin-bottom:16px;">'
            + '<div class="sub-status-title"><div class="sub-status-plan-name">签约进行中</div><span class="sub-status-badge inactive">处理中</span></div>'
            + '<p class="sub-status-note">您有一笔订阅签约正在处理（完成支付并确认开通自动续费后生效）。您也可以直接选择下方套餐重新发起，之前的未完成签约将自动作废。</p>'
            + '<div style="margin-top:12px;"><button type="button" class="btn secondary" data-rc-action="refresh-status">' + (state.subCancelling ? '刷新中...' : '刷新状态') + '</button></div>'
            + '</div>';
    }

    function introClassNames(plan) {
        if (!showsIntroPrice(plan, state.status)) {
            return introDealActive() ? ['sub-intro-dim'] : [];
        }
        var names = ['sub-intro-card'];
        if (introDealActive()) names.push('sub-intro-play');
        if (state.introPhase === 'price') names.push('sub-intro-price');
        else if (state.introPhase === 'slash') names.push('sub-intro-slash');
        else if (state.introPhase === 'power') names.push('sub-intro-power');
        else if (state.introPhase === 'done') names.push('sub-intro-done');
        return names;
    }

    function renderNewPrice(plan) {
        var show = showsIntroPrice(plan, state.status);
        if (show && state.introPhase === 'price') {
            return '<div class="sub-plan-price"><span class="symbol">¥</span><span class="amount sub-intro-old">' + money(plan.price) + '</span><span class="unit">/月</span></div>';
        }
        if (show && (state.introPhase === 'slash' || state.introPhase === 'power')) {
            return '<div class="sub-plan-price"><span class="symbol">¥</span><span class="amount sub-intro-new">' + money(plan.first_period_price) + '</span><span class="unit">/月</span><span class="sub-intro-stamp">降了 ¥' + money(introPriceCut(plan)) + '</span></div>';
        }
        var amount = show ? plan.first_period_price : plan.price;
        var renew = show ? '<span class="sub-plan-renew">之后 ¥' + money(plan.price) + '/月</span>' : '';
        return '<div class="sub-plan-price"><span class="symbol">¥</span><span class="amount">' + money(amount) + '</span><span class="unit">/月</span>' + renew + '</div>';
    }

    function renderNewPower(plan) {
        var show = showsIntroPrice(plan, state.status);
        var eligible = firstBonusEligible(state.status);
        if (show && (state.introPhase === 'price' || state.introPhase === 'slash')) {
            return '<div class="sub-plan-power">⚡ ' + esc(plan.computing_power) + ' 算力</div>';
        }
        if (show && state.introPhase === 'power') {
            return '<div class="sub-plan-power">⚡ <span class="sub-intro-power-num">' + esc(headlinePower(plan, true)) + '</span> 算力<span class="sub-plan-power-first">· 首期</span><span class="sub-intro-plus">+' + esc(plan.first_period_bonus) + '</span><span class="sub-plan-power-sub">之后每期 ' + esc(plan.computing_power) + ' 算力</span></div>';
        }
        var bonus = !!(plan.first_period_bonus && eligible);
        var head = headlinePower(plan, bonus);
        return '<div class="sub-plan-power">⚡ ' + esc(head) + ' 算力'
            + (bonus ? '<span class="sub-plan-power-first">· 首期</span><span class="sub-plan-power-sub">之后每期 ' + esc(plan.computing_power) + ' 算力</span>' : '')
            + '</div>';
    }

    function renderSaveBadge(plan, withBonus) {
        var extra = planExtraVsRecharge(plan, state.packages, state.status, withBonus);
        if (!(extra > 0)) return '';
        return '<div class="sub-plan-save">🔥 比直接购买多约 ' + esc(extra) + ' 算力</div>';
    }

    function renderPlanCard(plan, mode) {
        var selected = state.selectedPlan && String(state.selectedPlan.plan_id) === String(plan.plan_id);
        var classes = ['sub-plan-card'];
        if (selected) classes.push('selected');
        if (mode !== 'upgrade') classes = classes.concat(introClassNames(plan));
        var mult = planMultipleText(state.plans, plan);
        var withBonus = mode === 'upgrade' ? false : firstBonusEligible(state.status);
        var priceHtml = mode === 'upgrade'
            ? '<div class="sub-plan-price"><span class="symbol">¥</span><span class="amount">' + money(plan.price) + '</span><span class="unit">/月</span></div>'
            : renderNewPrice(plan);
        var powerHtml = mode === 'upgrade'
            ? '<div class="sub-plan-power">⚡ ' + esc(plan.computing_power) + ' 算力/期</div>'
            : renderNewPower(plan);
        return ''
            + '<button type="button" class="' + classes.join(' ') + '" data-rc-action="select-plan" data-plan-id="' + esc(plan.plan_id) + '">'
            + (selected ? '<span class="sub-plan-selected-tag">✓ 已选择</span>' : '')
            + '<div class="sub-plan-name">' + esc(plan.name || '') + '</div>'
            + '<div class="sub-plan-tagline">' + esc(planTagline(state.plans, plan)) + '</div>'
            + priceHtml
            + powerHtml
            + (mult ? '<div class="sub-plan-mult">' + esc(mult) + '</div>' : '')
            + renderSaveBadge(plan, withBonus)
            + '</button>';
    }

    function renderQrBox(opts) {
        var inner;
        if (opts.loading) {
            inner = '<div class="rc-qr-wait"><div class="rc-spinner"></div><span>生成二维码中...</span></div>';
        } else if (opts.qr) {
            inner = '<img src="' + esc(opts.qr) + '" alt="微信支付二维码" />';
        } else if (opts.error) {
            inner = '<div class="sub-error-text" style="padding:0 12px;text-align:center;">' + esc(opts.error) + '</div>';
        } else {
            inner = '<div class="rc-qr-empty">' + opts.emptyHtml + '</div>';
        }
        return (opts.qr && opts.head ? '<div class="sub-qr-tip sub-qr-head">' + opts.head + '</div>' : '')
            + '<div class="sub-qr-box' + (opts.qr ? ' has-qr' : '') + '">' + inner + '</div>'
            + (opts.qr && opts.tip ? '<div class="sub-qr-tip">' + opts.tip + '</div>' : '');
    }

    // 二维码上方提示：首订加赠用户改为「微信支付页开关」引导动画（纯 CSS 循环），
    // 提醒扫码后在微信支付页打开「每月自动续费」开关，否则加赠不发放、首期只到账基础算力。
    // 置于二维码上方（而非下方）：小屏用户点支付后无需下滚即可看到
    function renderRenewGuideTip(plan) {
        return '<div class="sub-rg">'
            + '<div class="sub-rg-title">扫码后，在微信支付页打开此开关</div>'
            + '<div class="sub-rg-row">'
            + '<span class="sub-rg-label">' + esc('开通智剧通' + (plan.name || '') + '每月自动续费') + '</span>'
            + '<span class="sub-rg-switch"><i class="sub-rg-thumb"></i></span>'
            + '<span class="sub-rg-finger">👆</span>'
            + '</div>'
            + '<div class="sub-rg-badge">⚡ 首期多送 ' + esc(plan.first_period_bonus) + ' 算力</div>'
            + '</div>'
            + '<div class="sub-rg-note">不开通自动续费，首期仅到账 ' + esc(plan.computing_power) + ' 算力</div>';
    }

    function renderPayPanel(upgrade) {
        var plan = state.selectedPlan;
        if (!plan) return '';
        if (upgrade && !isUpgradeSelection(plan, state.status)) return '';
        var show = !upgrade && showsIntroPrice(plan, state.status);
        var eligible = firstBonusEligible(state.status);
        var amount = show ? plan.first_period_price : plan.price;
        var suffix;
        if (upgrade) suffix = '/月 · 每期 ' + esc(plan.computing_power) + ' 算力';
        else if (show) suffix = '/月 · 首月优惠，之后 ¥' + money(plan.price) + '/月 · 首期到账 ' + esc(headlinePower(plan, true)) + ' 算力，之后每期 ' + esc(plan.computing_power) + ' 算力';
        else if (plan.first_period_bonus && eligible) suffix = '/月 · 首期到账 ' + esc(headlinePower(plan, true)) + ' 算力，之后每期 ' + esc(plan.computing_power) + ' 算力';
        else suffix = '/月 · 每期 ' + esc(plan.computing_power) + ' 算力';
        var agreeClass = 'sub-agreement' + (state.subAgreementError ? ' sub-agreement-error' : '');
        var agreeText = upgrade
            ? '同意 <a href="/auto_renewal_agreement.html" target="_blank" rel="noopener">《自动续费服务协议》</a>，升级立即生效，原套餐的自动续费将自动解除'
            : '同意 <a href="/auto_renewal_agreement.html" target="_blank" rel="noopener">《自动续费服务协议》</a>，到期自动扣费，可随时取消';
        var actionLabel = state.subPaymentLoading ? '生成中...' : (upgrade ? '升级并支付' : '微信支付');
        var renewGuide = (!upgrade && plan.first_period_bonus && eligible) ? renderRenewGuideTip(plan) : '';
        return ''
            + '<div class="sub-payment-panel">'
            + '<div class="sub-qr-section">'
            + renderQrBox({
                loading: state.subPaymentLoading,
                qr: state.subQr,
                error: state.subPaymentError,
                emptyHtml: upgrade ? '勾选协议并点击右侧<br/>「升级并支付」生成二维码' : '勾选协议并点击右侧<br/>「微信支付」生成二维码',
                head: renewGuide,
                tip: renewGuide ? '' : (upgrade ? '请使用微信扫码<br/>支付完成套餐升级' : '请使用微信扫码<br/>支付并确认开通自动续费')
            })
            + '</div>'
            + '<div class="sub-info-section">'
            + '<div class="sub-method-row"><span>使用</span><span class="sub-method-tag">💬 微信</span><span>扫码支付并签约</span></div>'
            + '<div class="sub-amount-row"><span class="symbol">¥</span><span class="value">' + money(amount) + '</span><span class="per-month">' + suffix + '</span></div>'
            + '<label class="' + agreeClass + '"><input type="checkbox" data-rc-action="toggle-agree"' + (state.subAgreed ? ' checked' : '') + ' /><span>' + agreeText + '</span></label>'
            + (upgrade ? '<p class="sub-upgrade-note">升级支付成功后立即切换为新套餐并发放整期算力，新周期自支付成功起算 30 天；本期剩余天数不折算、不退差价，升级档位不重复享首期加赠。</p>' : '')
            + '<div class="sub-action-row">'
            + (state.subPaymentError ? '<button type="button" class="btn secondary" data-rc-action="back-sub">返回</button>' : '')
            + '<button type="button" class="btn" data-rc-action="create-sub-order"' + ((!state.subAgreed || state.subPaymentLoading) ? ' disabled' : '') + '>' + actionLabel + '</button>'
            + '</div>'
            + (state.subQr && state.subOrderId ? '<div class="sub-order-info">订单号：' + esc(state.subOrderId) + '</div>' : '')
            + '</div></div>';
    }

    function renderManage() {
        var status = state.status;
        var plan = status.plan || {};
        var badge = status.status === 'upgrading' ? '升级开通中' : '生效中';
        var higher = upgradePlans(state.plans, status);
        var note;
        if (status.status === 'upgrading' && status.pending_plan) {
            note = '正在升级至「' + esc(status.pending_plan.name || '') + '」：完成微信支付后立即切换为新套餐，当前套餐在升级完成前继续可用。';
        } else {
            note = '取消订阅后当期权益保留至周期结束，之后不再自动扣款；也可直接升级到更高套餐，无需退订。';
        }
        var html = ''
            + '<div class="sub-status-card">'
            + '<div class="sub-status-title"><div class="sub-status-plan-name">' + esc(plan.name || '月度会员') + '</div>'
            + '<span class="sub-status-badge' + (status.status === 'active' ? '' : ' inactive') + '">' + badge + '</span></div>'
            + '<div class="sub-status-rows">'
            + '<div><span class="label">每期到账</span><span class="value">⚡ ' + esc(plan.computing_power) + ' 算力/期</span></div>'
            + '<div><span class="label">月费</span><span class="value">¥' + money(plan.price) + '/月</span></div>'
            + (status.current_period_end ? '<div><span class="label">当前周期至</span><span class="value">' + esc(formatDateStr(status.current_period_end)) + '</span></div>' : '')
            + (status.next_deduct_date ? '<div><span class="label">下次扣款日</span><span class="value">' + esc(status.next_deduct_date) + '</span></div>' : '')
            + '</div>'
            + '<p class="sub-status-note">' + note + '</p>'
            + '<div class="rc-row">'
            + '<button type="button" class="btn secondary" data-rc-action="refresh-status"' + (state.subCancelling ? ' disabled' : '') + '>' + (state.subCancelling ? '刷新中...' : '刷新状态') + '</button>'
            + (status.status === 'active' ? '<button type="button" class="btn secondary rc-btn-danger" data-rc-action="cancel-sub"' + (state.subCancelling ? ' disabled' : '') + '>' + (state.subCancelling ? '处理中...' : '取消订阅') + '</button>' : '')
            + '</div></div>';
        if (higher.length) {
            html += '<div class="sub-upgrade-section"><p class="sub-upgrade-title">升级到更高套餐（无需退订，支付成功立即切换）</p><div class="sub-plans-grid">';
            higher.forEach(function (p) { html += renderPlanCard(p, 'upgrade'); });
            html += '</div>' + renderPayPanel(true) + '</div>';
        }
        return html;
    }

    function renderPlanGrid() {
        var active = introDealActive();
        var html = '<div class="sub-plans-grid' + (active ? ' sub-intro-show' : '') + '" data-intro-phase="' + esc(state.introPhase) + '">';
        (state.plans || []).forEach(function (p) { html += renderPlanCard(p, 'new'); });
        html += '</div>';
        html += renderPayPanel(false);
        return html;
    }

    function renderSubscription() {
        var html = '<div class="rc-pane">' + renderIntroBanners() + renderSigningBanner();
        if (state.plansLoading) {
            html += '<div class="rc-center"><div class="rc-spinner"></div><p class="rc-muted">加载订阅套餐中...</p></div>';
        } else if (state.plansError) {
            html += '<div class="rc-center"><p class="sub-error-text">' + esc(state.plansError) + '</p><button type="button" class="btn secondary" data-rc-action="reload-plans">重试</button></div>';
        } else if (isManaging(state.status)) {
            html += renderManage();
        } else if (!state.plans.length) {
            html += '<div class="rc-center"><p class="rc-muted">暂无订阅套餐</p></div>';
        } else {
            html += renderPlanGrid();
        }
        return html + '</div>';
    }

    function renderPackageList() {
        if (state.packagesLoading) {
            return '<div class="rc-center"><div class="rc-spinner"></div><p class="rc-muted">加载套餐中...</p></div>';
        }
        if (state.packagesError) {
            return '<div class="rc-center"><p class="sub-error-text">' + esc(state.packagesError) + '</p><button type="button" class="btn secondary" data-rc-action="retry-packages">重试</button></div>';
        }
        if (!state.packages.length) {
            return '<div class="rc-center"><p class="rc-muted">暂无可用套餐</p></div>';
        }
        var html = '<div class="package-list">';
        state.packages.forEach(function (pkg) {
            var power = Number(pkg.granted_computing_power || pkg.computing_power) || 0;
            var price = Number(pkg.price) || 0;
            var unit = power > 0 ? (price / power * 100).toFixed(2) : '--';
            html += ''
                + '<button type="button" class="package-item" data-rc-action="select-package" data-package-id="' + esc(pkg.package_id) + '">'
                + '<div class="package-header"><div class="package-title-section">'
                + '<span class="package-name">' + esc(pkg.description || '') + '</span>'
                + '<span class="package-computing-power">' + esc(power) + ' 算力</span>'
                + '</div><div class="package-price-section">'
                + '<span class="package-price">¥' + money(price) + '</span>'
                + '<span class="package-unit-price">' + esc(unit) + '元/百算力</span>'
                + '</div></div>'
                + '<div class="package-footer"><span class="package-select-hint">点击选择</span><span class="package-arrow">→</span></div>'
                + '</button>';
        });
        return html + '</div>';
    }

    function renderPowerPay() {
        var pkg = state.selectedPackage || {};
        var power = Number(pkg.granted_computing_power || pkg.computing_power) || 0;
        var html = '<div class="rc-center" style="margin-bottom:16px;"><div class="rc-pkg-title">' + esc(pkg.description || '') + '</div><div class="rc-muted">' + esc(power) + ' 算力 - ¥' + money(pkg.price) + '</div></div>';
        if (state.paymentLoading) {
            html += '<div class="rc-center"><div class="rc-spinner"></div><p>正在创建支付订单...</p></div>';
        } else if (state.paymentError) {
            html += '<div class="rc-center"><p class="sub-error-text">' + esc(state.paymentError) + '</p><button type="button" class="btn secondary" data-rc-action="retry-pay">重试</button></div>';
        } else if (state.paymentQr) {
            html += '<div class="rc-center"><div style="font-weight:600;margin-bottom:12px;">请使用微信扫码完成支付</div>'
                + '<div class="rc-pay-qr"><img src="' + esc(state.paymentQr) + '" alt="微信支付二维码" width="240" height="240" /></div>'
                + '<p class="rc-muted">请打开微信“扫一扫”完成支付<br/>如果已支付，请稍等片刻系统会自动到账</p>'
                + '<button type="button" class="btn secondary" data-rc-action="retry-pay">二维码失效？重新生成</button></div>';
        }
        html += '<div class="rc-center" style="margin-top:16px;"><button type="button" class="btn secondary" data-rc-action="back-packages">返回选择套餐</button></div>';
        return html;
    }

    function renderPower() {
        var html = '<div class="rc-pane">';
        if (!state.selectedPackage) {
            html += '<div class="package-intro"><p class="package-intro-text">选择适合您的算力套餐</p><p class="package-intro-subtext">支持微信支付，充值后立即到账</p></div>';
            html += renderPackageList();
        } else {
            html += renderPowerPay();
        }
        return html + '</div>';
    }

    function render() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (!overlay) return;
        var body = overlay.querySelector('[data-rc-body]');
        if (!body) return;
        body.innerHTML = renderTabs() + (state.tab === 'subscription' ? renderSubscription() : renderPower());
    }

    async function open(options) {
        options = options || {};
        state.onPaid = typeof options.onPaid === 'function' ? options.onPaid : null;
        state.onLocalBlocked = typeof options.onLocalBlocked === 'function' ? options.onLocalBlocked : null;
        try {
            var resp = await fetch('/api/system/server-config');
            var data = await resp.json();
            if (data && data.data && data.data.is_local) {
                var blocked = state.onLocalBlocked;
                close();
                if (blocked) blocked(LOCAL_TIP);
                else window.alert(LOCAL_TIP);
                return;
            }
        } catch (e) {
            console.error('获取配置失败:', e);
        }
        resetSession();
        var overlay = ensureDom();
        state.open = true;
        overlay.hidden = false;
        render();
        await Promise.all([loadPackages(), loadPlans()]);
    }

    function close() {
        state.open = false;
        stopPoll();
        clearIntro();
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.hidden = true;
        state.onPaid = null;
    }

    window.RechargeCenter = {
        open: open,
        close: close,
        pricing: {
            firstBonusEligible: firstBonusEligible,
            showsIntroPrice: showsIntroPrice,
            introPriceCut: introPriceCut,
            planTagline: planTagline,
            planMultipleText: planMultipleText,
            rechargeReferenceRate: rechargeReferenceRate,
            headlinePower: headlinePower,
            planExtraVsRecharge: planExtraVsRecharge,
            upgradePlans: upgradePlans,
            isUpgradeSelection: isUpgradeSelection
        }
    };
})();
