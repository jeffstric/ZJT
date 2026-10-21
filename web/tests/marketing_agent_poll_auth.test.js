import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// 回归背景（2026-10-20 事故，会话 203d9493）：营销智能体图文转视频轮询期间，
// localStorage 残留的失效 token 令 /api/get-status 持续 401（token 拼 URL 传参），
// 页面在生成中途被踢到登录页，进度卡片中断，用户误以为生成失败——实际服务端
// 4 个视频全部生成成功。
// 修复契约：
//   1. 轮询不再把 auth_token 放进 axios params（token 进 URL 会经 Referer/
//      浏览器历史/服务端访问日志泄漏，X3 红线）；同源请求由服务端 cookie 翻译鉴权
//   2. 401 先自愈（web/js/auth_self_heal.js）：清残留 token → 探测 HttpOnly
//      cookie 会话 → 有效则 reload 无感恢复，无效才跳登录页
describe('marketing_agent 轮询凭证与 401 自愈', () => {
    const agentSource = readSource('web/js/marketing_agent.js');
    const healSource = readSource('web/js/auth_self_heal.js');
    const htmlSource = readSource('web/marketing_agent.html');

    it('轮询请求不再把 auth_token 放进 params 对象（token 不进 URL）', () => {
        const paramsObjectForm = /\bparams\s*:\s*\{[^}]*\bauth_token\b|\bparams\s*=\s*[\w.]+\s*\?\s*\{[^}]*\bauth_token\b/;
        const offenders = agentSource
            .split('\n')
            .filter((line) => paramsObjectForm.test(line));
        expect(offenders, `仍存在 token 进 params 的行: ${offenders.join(' | ')}`).toEqual([]);
    });

    it('get-status 轮询调用不再携带 params 配置', () => {
        const pollLines = agentSource.split('\n').filter((l) => l.includes('axios.get(`/api/get-status/'));
        expect(pollLines.length).toBeGreaterThan(0);
        for (const line of pollLines) {
            expect(line).not.toMatch(/\{\s*params\s*\}/);
        }
    });

    it('401 经由 authSelfHeal.handle401 自愈，而非直接跳登录页', () => {
        expect(agentSource).toContain('window.authSelfHeal.handle401({ onLoginExpired: redirectToLogin })');
        const checker = agentSource.slice(
            agentSource.indexOf('function checkAuthResponse'),
            agentSource.indexOf('function handleAuth401'),
        );
        expect(checker).toContain('handleAuth401()');
        expect(checker).not.toContain('redirectToLogin()');
    });

    it('注册 axios 全局 401 拦截，覆盖所有轮询请求', () => {
        expect(agentSource).toContain('axios.interceptors.response.use');
        const interceptorBody = agentSource.slice(
            agentSource.indexOf('axios.interceptors.response.use'),
            agentSource.indexOf('axios.interceptors.response.use') + 400,
        );
        expect(interceptorBody).toContain('err.response.status === 401');
        expect(interceptorBody).toContain('handleAuth401()');
    });

    it('初始化门禁接受 HttpOnly cookie 会话兜底（自愈 reload 后不再弹回登录页）', () => {
        expect(agentSource).toContain('window.authSelfHeal?.probeSession');
    });

    it('页面在加载 marketing_agent.js 之前引入 auth_self_heal.js', () => {
        const healIdx = htmlSource.indexOf('/js/auth_self_heal.js');
        const agentIdx = htmlSource.indexOf('/js/marketing_agent.js');
        expect(healIdx).toBeGreaterThan(-1);
        expect(agentIdx).toBeGreaterThan(healIdx);
    });
});

describe('auth_self_heal 自愈契约（与 script_writer.handleTokenExpired 行为对齐）', () => {
    const healSource = readSource('web/js/auth_self_heal.js');

    it('先清 localStorage 残留 token（失效 Bearer 会压住服务端 cookie 翻译）', () => {
        expect(healSource).toContain("localStorage.removeItem('auth_token')");
        expect(healSource).toContain("localStorage.removeItem('token')");
    });

    it('cookie 探测为裸 fetch，不带 Authorization 头', () => {
        expect(healSource).toContain("fetch(probePath || '/api/user/role'");
        expect(healSource).not.toMatch(/fetch\([^)]*Authorization/);
    });

    it('cookie 有效则 reload 自愈，且 60 秒内只自愈一次防 reload 循环', () => {
        expect(healSource).toContain('window.location.reload()');
        expect(healSource).toContain('HEAL_THROTTLE_MS = 60 * 1000');
        expect(healSource).toContain('auth_self_heal_last_at');
    });

    it('并发 401 去重，多个请求同时失败只触发一次自愈流程', () => {
        expect(healSource).toContain('if (inFlight)');
        expect(healSource).toContain('inFlight = true');
    });

    it('cookie 也失效时回调 onLoginExpired 由页面跳登录页', () => {
        expect(healSource).toContain('opts.onLoginExpired');
    });

    it('探测解析业务码 code===0（/api/user/role 失效也返回 HTTP 200，resp.ok 恒真）', () => {
        const probeBody = healSource.slice(
            healSource.indexOf('function probeSession'),
            healSource.indexOf('function readLastHealAt'),
        );
        expect(probeBody).toContain('resp.ok');
        expect(probeBody).toContain('data.code === 0');
        // 契约护栏：不得退回「只看 HTTP 状态」的恒真探测
        expect(probeBody).not.toMatch(/return\s+resp\.ok\s*;?\s*\}\)/);
    });

    it('探测 JSON 解析失败/网络异常按会话失效处理（fail closed 到 onLoginExpired）', () => {
        const probeBody = healSource.slice(
            healSource.indexOf('function probeSession'),
            healSource.indexOf('function readLastHealAt'),
        );
        expect(probeBody).toContain('.catch(function ()');
        expect(probeBody).toContain('return false');
    });
});
