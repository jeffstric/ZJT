/**
 * AIGC 显式标识（明水印）前端模块 —— 图片/视频弹窗"添加AI标识"入口
 *
 * 合规依据：《人工智能生成合成内容标识办法》第 4 条（图片适当位置/视频起始画面添加显式标识）、
 * 第 8 条（协议说明标识规范）、第 10 条（用户不得恶意删除标识，发布时应主动声明）。
 * 确认弹窗文案即"通过用户协议明确用户的标识义务和使用责任"（第 9 条前置条件）的可执行落地。
 *
 * 依赖：marketing_agent.js 的 window.setModalImageInfo / window.resetModalImageInfo
 * （本文件加载时包装二者以跟踪当前弹窗的 aiToolId）。
 */
(function () {
    'use strict';

    function getAuthToken() {
        try { return localStorage.getItem('auth_token') || ''; } catch (e) { return ''; }
    }

    // 跟踪当前弹窗任务 ID（包装 marketing_agent.js 的弹窗信息设置函数）
    let currentAiToolId = null;
    let currentMediaType = 'image';

    function wrapWindowFn(name, fn) {
        const orig = window[name];
        window[name] = function () {
            try { fn.apply(null, arguments); } catch (e) { /* 跟踪失败不影响原逻辑 */ }
            if (orig) return orig.apply(this, arguments);
        };
    }

    wrapWindowFn('setModalImageInfo', function (aiToolId) {
        currentAiToolId = aiToolId || null;
        // 弹窗媒体类型：视频元素可见时为 video
        const video = document.getElementById('imgModalVideo');
        const img = document.getElementById('imgModalImg');
        currentMediaType = (video && video.style.display !== 'none' && img && img.style.display === 'none')
            ? 'video' : 'image';
        refreshBtnText();
    });

    wrapWindowFn('resetModalImageInfo', function () {
        currentAiToolId = null;
        currentMediaType = 'image';
        refreshBtnText();
    });

    function getBtn() { return document.getElementById('imgModalAigcBtn'); }

    function refreshBtnText() {
        const btn = getBtn();
        if (btn && !btn.disabled) {
            btn.textContent = currentMediaType === 'video' ? '视频添加AI标识' : '图片添加AI标识';
        }
    }

    function setBtnLoading(loading) {
        const btn = getBtn();
        if (!btn) return;
        btn.disabled = loading;
        btn.style.opacity = loading ? '0.6' : '1';
        btn.textContent = loading
            ? '处理中…（视频可能需要数分钟）'
            : (currentMediaType === 'video' ? '视频添加AI标识' : '图片添加AI标识');
    }

    async function addToCurrentModal() {
        if (!currentAiToolId) {
            alert('该内容缺少任务信息，无法添加标识');
            return;
        }
        // 协议义务确认（标识办法第 8/9/10 条的可执行落地）
        const confirmed = window.confirm(
            '将在此内容中添加"AI生成"标识（画面明水印）。\n\n' +
            '根据《人工智能生成合成内容标识办法》：\n' +
            '· 您发布、传播 AI 生成内容时应主动声明并使用标识功能；\n' +
            '· 任何人不得恶意删除、篡改、伪造、隐匿内容标识；\n' +
            '· 文件元数据中的隐式标识将始终保留，用于内容溯源。\n\n' +
            (currentMediaType === 'video' ? '视频处理可能需要数分钟，请耐心等待。\n\n' : '') +
            '确认添加吗？'
        );
        if (!confirmed) return;

        setBtnLoading(true);
        try {
            const res = await fetch('/api/aigc/explicit-label', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + getAuthToken(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ ai_tool_id: Number(currentAiToolId) })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                alert((data && data.detail) || ('添加失败（HTTP ' + res.status + '）'));
                return;
            }
            alert('已在内容中添加"AI生成"标识。重新打开该内容即可看到。');
        } catch (e) {
            alert((e && e.message) || '添加失败，请稍后重试');
        } finally {
            setBtnLoading(false);
        }
    }

    // 数字人/TTS 等强制标识类内容的关闭申请（标识办法第 9 条，留痕 >= 6 个月）
    async function requestOptOut(aiToolId, scope) {
        const confirmed = window.confirm(
            '申请不再为该内容添加画面/语音"AI生成"提示？\n\n' +
            '说明：\n' +
            '· 您须自行承担发布、传播时的主动声明义务；\n' +
            '· 本次申请将依法记录留存不少于 6 个月；\n' +
            '· 文件元数据中的隐式标识不会被移除。\n\n' +
            '确认申请吗？'
        );
        if (!confirmed) return false;
        try {
            const res = await fetch('/api/aigc/explicit-optout', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + getAuthToken(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ ai_tool_id: aiToolId || null, scope: scope || null })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                alert((data && data.detail) || ('申请失败（HTTP ' + res.status + '）'));
                return false;
            }
            alert('申请已记录。');
            return true;
        } catch (e) {
            alert((e && e.message) || '申请失败，请稍后重试');
            return false;
        }
    }

    // 挂载到全局（HTML onclick 与其他页面复用）
    window.AigcLabel = {
        addToCurrentModal: addToCurrentModal,
        requestOptOut: requestOptOut
    };
})();
