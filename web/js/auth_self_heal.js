/**
 * 401 认证自愈公共模块（无依赖，页面脚本按需引入）。
 *
 * 背景（2026-10-20 事故，会话 203d9493）：营销智能体图文转视频轮询期间，
 * localStorage 残留的失效 token 令 get-status 持续 401，页面在生成中途被
 * 踢到登录页，进度卡片中断，用户误以为生成失败——实际服务端 4 个视频全部
 * 生成成功。
 *
 * 机制：
 *   1. 401 时先清掉 localStorage 残留 token：失效 token 以非空 Bearer 头发出
 *      会压住服务端 cookie 翻译中间件（server.py 的
 *      auth_cookie_translation_middleware 仅在 Authorization 为空时注入
 *      HttpOnly cookie 凭证）；
 *   2. 裸 fetch（不带 Authorization 头，浏览器自动带 HttpOnly cookie）探测
 *      cookie 会话是否仍有效；/api/user/role 鉴权失败也返回 HTTP 200 + {code:-1}
 *      （实测确认），探测必须解析业务码 code===0，只看 resp.ok 会恒真；
 *   3. cookie 有效 → reload 无感自愈（重载后页面不再携带失效 Bearer，同源
 *      请求走 cookie 翻译）；60 秒内只自愈一次，防 reload 循环；
 *   4. cookie 也失效 → 回调 onLoginExpired（页面自行跳登录页）。
 *
 * 与 script_writer.js 的 handleTokenExpired 行为对齐（该页为首个落地实现）。
 */
(function () {
    'use strict';

    var HEAL_THROTTLE_KEY = 'auth_self_heal_last_at';
    var HEAL_THROTTLE_MS = 60 * 1000;
    var inFlight = false;

    function clearStaleTokens() {
        try {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('token');
        } catch (e) {
            // 隐私模式等存储异常不应阻断后续 cookie 探测
        }
    }

    // 不带 Authorization 头：残留失效 Bearer 会压住服务端 cookie 翻译
    // /api/user/role 鉴权失败仍返回 HTTP 200 + {"code":-1}（server.py get_user_role
    // 所有失败分支均为 200，实测确认），不能只看 resp.ok——否则探测恒真：cookie
    // 失效也走 reload 分支（多一轮整页闪烁），且后续轮询 401 误删仍有效的凭证
    function probeSession(probePath) {
        return fetch(probePath || '/api/user/role', { credentials: 'same-origin' })
            .then(function (resp) {
                if (!resp.ok) {
                    return false;
                }
                return resp.json().then(function (data) {
                    return !!(data && data.code === 0);
                });
            })
            .catch(function () {
                return false;
            });
    }

    function readLastHealAt() {
        try {
            return parseInt(sessionStorage.getItem(HEAL_THROTTLE_KEY) || '0', 10) || 0;
        } catch (e) {
            return 0;
        }
    }

    function markHealed() {
        try {
            sessionStorage.setItem(HEAL_THROTTLE_KEY, String(Date.now()));
        } catch (e) {
            // sessionStorage 不可用时最多失去防循环保护，不影响自愈本身
        }
    }

    /**
     * 401 统一入口（并发去重：多个请求同时 401 只触发一次流程）。
     *
     * @param {Object} opts
     * @param {string}  [opts.probePath]      cookie 会话探测路径，默认 /api/user/role
     * @param {Function} [opts.onLoginExpired] cookie 也失效时的回调（跳登录页）
     */
    function handle401(opts) {
        opts = opts || {};
        if (inFlight) {
            return;
        }
        inFlight = true;
        clearStaleTokens();

        // 60 秒内已自愈过仍 401：直接按登录失效处理，避免 reload 循环
        var shouldProbe = Date.now() - readLastHealAt() > HEAL_THROTTLE_MS;
        var probing = shouldProbe
            ? probeSession(opts.probePath)
            : Promise.resolve(false);

        probing.then(function (cookieAlive) {
            if (cookieAlive) {
                markHealed();
                window.location.reload();
                return;
            }
            inFlight = false;
            if (typeof opts.onLoginExpired === 'function') {
                opts.onLoginExpired();
            }
        });
    }

    window.authSelfHeal = {
        handle401: handle401,
        // 探测 HttpOnly cookie 会话是否有效（页面初始化门禁可复用：
        // localStorage token 缺失/失效时，cookie 有效则允许直接使用页面）
        probeSession: probeSession,
        // 仅供测试与调试
        _reset: function () {
            inFlight = false;
        },
    };
})();
