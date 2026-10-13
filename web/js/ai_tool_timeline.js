/**
 * ai_tool_timeline.js — AI 生成任务事件时间轴弹窗（公共，video_workflow / storyboard 复用）。
 *
 * 数据源：GET /api/ai-tools/{id}/timeline（ai_tools_log 事件日志，与 index.html
 * 历史记录的 timeline-modal 同源），弹窗打开期间任务未到终态时自动轮询刷新。
 *
 * 对外 API（window.AiToolTimeline）：
 * - open(taskIds)            打开时间轴弹窗，taskIds 支持 number / number[]（多个时顶部可切换）
 * - close()                  关闭弹窗
 * - markNodeGenerating(id)   video_workflow 专用：结果节点（image/video）绑定 project_id 后
 *                            显示「生成中」状态行/占位 + 查看状态按钮（含工作流重载恢复）
 * - settleNodeResult(node)   video_workflow 专用：url 到位后隐藏占位 / 状态行标记成功
 * - failNode(id, message)    video_workflow 专用：状态行/占位标记失败（按钮保留可查时间轴）
 *
 * 节点内按钮（.ai-task-timeline-btn）由全局 click 委托处理：
 * 优先读 data-task-ids（storyboard 候选卡），否则回溯最近 .node[data-node-id]
 * 从 video_workflow 的全局 state.nodes 取 projectIds / project_id / aiToolsId。
 *
 * 安全：所有动态文本一律 DOM API + textContent 渲染，不拼接 HTML。
 */
(function () {
    'use strict';

    var REFRESH_INTERVAL_MS = 5000;
    // 与后端 AIToolStatus 对齐：0 PENDING / 1 PROCESSING / 2 COMPLETED / 3 SYNC_QUEUED /
    // 4 WAITING_PARAM_PREPARE / 5 WAITING_BEFORE_FINISH / 6 DOWNLOADING / -1 FAILED
    var RUNNING_STATUSES = [0, 1, 3, 4, 5, 6];
    var STATUS_LABELS = {
        0: '排队中', 1: '处理中', 2: '已完成', 3: '排队中',
        4: '准备参数', 5: '收尾中', 6: '下载中', '-1': '失败'
    };
    var STATUS_CLASSES = {
        0: 'is-pending', 1: 'is-running', 2: 'is-done', 3: 'is-pending',
        4: 'is-running', 5: 'is-running', 6: 'is-running', '-1': 'is-failed'
    };
    var EVENT_LABELS = {
        record_created: '记录创建', task_started: '开始处理', slot_delayed: '槽位延迟',
        implementation_selected: '选定实现方', submitted: '已提交', status_check: '状态轮询',
        upstream_succeeded: '上游成功', upstream_failed: '上游失败', download_started: '开始下载',
        download_completed: '下载完成', cdn_uploaded: 'CDN上传', retry_scheduled: '安排重试',
        max_retry_exceeded: '重试上限', task_completed: '任务完成', exception: '异常',
        pipeline_step: '流水线步骤'
    };

    function tr(key, fallback) {
        try {
            var v = window.t ? window.t(key) : null;
            return (v && v !== key) ? v : fallback;
        } catch (e) {
            return fallback;
        }
    }

    function authToken() {
        try { return localStorage.getItem('auth_token') || ''; } catch (e) { return ''; }
    }

    function normalizeIds(taskIds) {
        var arr = Array.isArray(taskIds) ? taskIds : [taskIds];
        var out = [];
        arr.forEach(function (v) {
            var n = parseInt(v, 10);
            if (Number.isFinite(n) && n > 0 && out.indexOf(n) === -1) out.push(n);
        });
        return out;
    }

    // ==================== 弹窗 ====================

    var overlayEl = null;      // 单例 DOM
    var currentIds = [];       // 本弹窗展示的任务集合
    var activeId = null;       // 当前展示的任务
    var refreshTimer = null;
    var refreshSeq = 0;        // 防止迟到响应覆盖新任务

    function closeModal() {
        if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null; }
        if (overlayEl && overlayEl.parentNode) overlayEl.parentNode.removeChild(overlayEl);
        overlayEl = null;
        activeId = null;
        currentIds = [];
    }

    function open(taskIds) {
        var ids = normalizeIds(taskIds);
        if (!ids.length) return;
        closeModal();
        currentIds = ids;
        activeId = ids[0];
        buildModal();
        fetchTimeline();
    }

    function buildModal() {
        overlayEl = document.createElement('div');
        overlayEl.className = 'ai-timeline-overlay';
        overlayEl.addEventListener('click', function (e) {
            if (e.target === overlayEl) closeModal();
        });

        var modal = document.createElement('div');
        modal.className = 'ai-timeline-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-label', tr('task_timeline', '任务时间轴'));

        var header = document.createElement('div');
        header.className = 'ai-timeline-header';

        var title = document.createElement('div');
        title.className = 'ai-timeline-title';
        title.textContent = tr('task_timeline', '任务时间轴');

        var tabs = document.createElement('div');
        tabs.className = 'ai-timeline-tabs';
        if (currentIds.length > 1) {
            currentIds.forEach(function (id) {
                var tab = document.createElement('button');
                tab.type = 'button';
                tab.className = 'ai-timeline-tab' + (id === activeId ? ' is-active' : '');
                tab.textContent = '#' + id;
                tab.addEventListener('click', function () {
                    if (activeId === id) return;
                    activeId = id;
                    Array.prototype.forEach.call(tabs.children, function (el) {
                        el.classList.toggle('is-active', el.textContent === '#' + id);
                    });
                    fetchTimeline();
                });
                tabs.appendChild(tab);
            });
        }

        var actions = document.createElement('div');
        actions.className = 'ai-timeline-actions';
        var refreshBtn = document.createElement('button');
        refreshBtn.type = 'button';
        refreshBtn.className = 'ai-timeline-refresh';
        refreshBtn.textContent = tr('refresh', '刷新');
        refreshBtn.addEventListener('click', fetchTimeline);
        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'ai-timeline-close';
        closeBtn.setAttribute('aria-label', tr('close', '关闭'));
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', closeModal);
        actions.appendChild(refreshBtn);
        actions.appendChild(closeBtn);

        header.appendChild(title);
        header.appendChild(tabs);
        header.appendChild(actions);

        var statusRow = document.createElement('div');
        statusRow.className = 'ai-timeline-status';

        var body = document.createElement('div');
        body.className = 'ai-timeline-body';

        modal.appendChild(header);
        modal.appendChild(statusRow);
        modal.appendChild(body);
        overlayEl.appendChild(modal);
        document.body.appendChild(overlayEl);
    }

    function setStatusBadge(status) {
        if (!overlayEl) return;
        var row = overlayEl.querySelector('.ai-timeline-status');
        if (!row) return;
        row.textContent = '';
        var s = (status === undefined || status === null) ? null : String(status);
        row.appendChild(document.createTextNode(tr('timeline_task_status', '当前状态') + '：'));
        if (s === null) {
            var unknown = document.createElement('span');
            unknown.className = 'ai-timeline-badge';
            unknown.textContent = '--';
            row.appendChild(unknown);
            return;
        }
        var badge = document.createElement('span');
        badge.className = 'ai-timeline-badge ' + (STATUS_CLASSES[s] || '');
        badge.textContent = STATUS_LABELS[s] || s;
        row.appendChild(badge);
        if (RUNNING_STATUSES.indexOf(parseInt(s, 10)) !== -1) {
            var hint = document.createElement('span');
            hint.className = 'ai-timeline-auto-hint';
            hint.textContent = tr('timeline_auto_refresh', '生成中，自动刷新中…');
            row.appendChild(hint);
        }
    }

    function fetchTimeline() {
        if (!overlayEl || !activeId) return;
        var seq = ++refreshSeq;
        if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null; }
        var body = overlayEl.querySelector('.ai-timeline-body');
        if (body) {
            body.textContent = '';
            var loading = document.createElement('div');
            loading.className = 'ai-timeline-empty';
            loading.textContent = tr('timeline_loading', '加载中...');
            body.appendChild(loading);
        }

        fetch('/api/ai-tools/' + activeId + '/timeline', {
            headers: { Authorization: 'Bearer ' + authToken() }
        }).then(function (resp) {
            return resp.json().catch(function () { return {}; });
        }).then(function (res) {
            if (seq !== refreshSeq || !overlayEl) return; // 弹窗已切换/关闭
            if (res && res.success && res.data) {
                setStatusBadge(res.data.status);
                renderEvents((res.data && res.data.timeline) || []);
                scheduleAutoRefresh(res.data.status);
            } else {
                showError((res && (res.message || res.detail)) || tr('timeline_fetch_failed', '获取时间线失败'));
            }
        }).catch(function () {
            if (seq !== refreshSeq || !overlayEl) return;
            showError(tr('timeline_fetch_failed', '获取时间线失败'));
        });
    }

    function scheduleAutoRefresh(status) {
        if (status === undefined || status === null) return;
        if (RUNNING_STATUSES.indexOf(parseInt(status, 10)) === -1) return;
        refreshTimer = setTimeout(function () {
            refreshTimer = null;
            fetchTimeline();
        }, REFRESH_INTERVAL_MS);
    }

    function showError(message) {
        if (!overlayEl) return;
        var body = overlayEl.querySelector('.ai-timeline-body');
        if (!body) return;
        body.textContent = '';
        var err = document.createElement('div');
        err.className = 'ai-timeline-empty ai-timeline-error';
        err.textContent = message;
        body.appendChild(err);
    }

    function formatTime(s) {
        if (!s) return '-';
        try {
            var d = new Date(s);
            if (isNaN(d.getTime())) return String(s);
            var pad = function (n) { return String(n).padStart(2, '0'); };
            var ms = String(d.getMilliseconds()).padStart(3, '0');
            return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) + '.' + ms;
        } catch (e) {
            return String(s);
        }
    }

    function renderEvents(timeline) {
        if (!overlayEl) return;
        var body = overlayEl.querySelector('.ai-timeline-body');
        if (!body) return;
        body.textContent = '';

        if (!timeline.length) {
            var empty = document.createElement('div');
            empty.className = 'ai-timeline-empty';
            empty.textContent = tr('no_timeline_records', '暂无时间线记录');
            body.appendChild(empty);
            return;
        }

        timeline.forEach(function (ev) {
            var item = document.createElement('div');
            item.className = 'ai-timeline-item';

            var time = document.createElement('div');
            time.className = 'ai-timeline-item-time';
            time.textContent = formatTime(ev.create_at);

            var main = document.createElement('div');
            main.className = 'ai-timeline-item-main';

            var head = document.createElement('div');
            head.className = 'ai-timeline-item-head';
            var label = document.createElement('span');
            label.className = 'ai-timeline-item-label';
            label.textContent = EVENT_LABELS[ev.event_type] || ev.event_type || '';
            var msg = document.createElement('span');
            msg.className = 'ai-timeline-item-msg';
            msg.textContent = ev.message || '';
            head.appendChild(label);
            head.appendChild(msg);
            if (ev.duration_ms !== undefined && ev.duration_ms !== null) {
                var dur = document.createElement('span');
                dur.className = 'ai-timeline-item-duration';
                dur.textContent = ev.duration_ms + 'ms';
                head.appendChild(dur);
            }

            main.appendChild(head);

            // detail 为后端 JSON 上下文（上游响应/URL 等），textContent 渲染防 XSS
            var detail = ev.detail;
            if (detail && typeof detail === 'object' && Object.keys(detail).length) {
                var detailBox = document.createElement('div');
                detailBox.className = 'ai-timeline-item-detail';
                var toggle = document.createElement('a');
                toggle.href = 'javascript:void(0)';
                toggle.textContent = tr('timeline_detail', '详情');
                var pre = document.createElement('pre');
                pre.className = 'ai-timeline-item-pre';
                pre.style.display = 'none';
                pre.textContent = JSON.stringify(detail, null, 2);
                toggle.addEventListener('click', function () {
                    var expanded = pre.style.display !== 'none';
                    pre.style.display = expanded ? 'none' : 'block';
                    toggle.textContent = expanded
                        ? tr('timeline_detail', '详情')
                        : tr('timeline_detail_collapse', '收起');
                });
                detailBox.appendChild(toggle);
                detailBox.appendChild(pre);
                main.appendChild(detailBox);
            }

            item.appendChild(time);
            item.appendChild(main);
            body.appendChild(item);
        });
    }

    // ==================== video_workflow 节点辅助 ====================

    function workflowState() {
        // video_workflow 的 state.js 在普通 <script> 顶层声明 const state（全局词法绑定，
        // 非 window 属性），同页面普通脚本可直接引用；storyboard 等无此绑定返回 null。
        try {
            return (typeof state !== 'undefined' && state && Array.isArray(state.nodes)) ? state : null;
        } catch (e) {
            return null;
        }
    }

    function findNode(nodeId) {
        var st = workflowState();
        if (!st) return null;
        return st.nodes.find(function (n) { return n && n.id === nodeId; }) || null;
    }

    function nodeTaskIds(node) {
        if (!node || !node.data) return [];
        if (Array.isArray(node.data.projectIds) && node.data.projectIds.length) {
            return normalizeIds(node.data.projectIds);
        }
        return normalizeIds([node.data.project_id, node.data.aiToolsId]);
    }

    function nodeEl(nodeId) {
        var canvas = document.getElementById('canvas');
        return canvas ? canvas.querySelector('.node[data-node-id="' + nodeId + '"]') : null;
    }

    function makeTimelineButton(taskIds) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ai-task-timeline-btn';
        btn.title = tr('view_timeline', '查看生成状态时间轴');
        btn.textContent = tr('timeline_btn_status', '状态');
        var ids = normalizeIds(taskIds);
        if (ids.length) btn.setAttribute('data-task-ids', ids.join(','));
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            open(normalizeIds(taskIds));
        });
        return btn;
    }

    /** 结果节点绑定任务后显示「生成中」提示 + 状态按钮（image 占位 / video 状态行） */
    function markNodeGenerating(nodeId) {
        var node = findNode(nodeId);
        if (!node) return;
        var el = nodeEl(nodeId);
        if (!el) return;
        var ids = nodeTaskIds(node);
        if (!ids.length) return;

        if (node.type === 'image' && !node.data.url) {
            var placeholder = el.querySelector('.image-generating-placeholder');
            if (placeholder) {
                placeholder.style.display = 'flex';
            }
        } else if (node.type === 'video') {
            var statusField = el.querySelector('.video-status-field');
            var statusEl = el.querySelector('.video-status');
            if (statusField && statusEl) {
                statusField.style.display = 'block';
                if (!node.data.url) statusEl.textContent = tr('timeline_generating', '生成中...');
            }
        }
    }

    /** url 到位（updateNodePreview 路径）：隐藏图片占位 / 视频状态行标记成功 */
    function settleNodeResult(node) {
        if (!node) return;
        var el = nodeEl(node.id);
        if (!el) return;
        if (node.type === 'image') {
            var placeholder = el.querySelector('.image-generating-placeholder');
            if (placeholder) placeholder.style.display = 'none';
        } else if (node.type === 'video') {
            var statusField = el.querySelector('.video-status-field');
            var statusEl = el.querySelector('.video-status');
            if (statusField && statusEl) {
                statusField.style.display = 'block';
                statusEl.textContent = '✓ ' + tr('timeline_generate_success', '生成成功');
                statusEl.style.color = '#16a34a';
            }
        }
    }

    /** 失败（updateNodeErrorDisplay 路径）：占位/状态行标记失败，按钮保留 */
    function failNode(nodeId, message) {
        var node = findNode(nodeId);
        if (!node) return;
        var el = nodeEl(nodeId);
        if (!el) return;
        var text = '✗ ' + (message || tr('timeline_generate_failed', '生成失败'));
        if (node.type === 'image') {
            var placeholder = el.querySelector('.image-generating-placeholder');
            if (placeholder) {
                placeholder.style.display = 'flex';
                placeholder.classList.add('is-failed');
                var label = placeholder.querySelector('.image-generating-label');
                if (label) label.textContent = text;
            }
        } else if (node.type === 'video') {
            var statusField = el.querySelector('.video-status-field');
            var statusEl = el.querySelector('.video-status');
            if (statusField && statusEl) {
                statusField.style.display = 'block';
                statusEl.textContent = text;
                statusEl.style.color = '#dc2626';
            }
        }
    }

    // ==================== 全局委托 ====================
    // 捕获阶段处理并在命中时 stopPropagation：候选卡/画布节点的点击委托
    // （如 storyboard 的选中候选、video_workflow 的节点选中）不会误触发。
    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.ai-task-timeline-btn') : null;
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        var ids = normalizeIds((btn.getAttribute('data-task-ids') || '').split(','));
        if (!ids.length) {
            // 节点内按钮：回溯最近 .node 取任务 id（video_workflow）
            var nodeHost = btn.closest('.node[data-node-id]');
            if (nodeHost) {
                ids = nodeTaskIds(findNode(parseInt(nodeHost.dataset.nodeId, 10)));
            }
        }
        if (ids.length) open(ids);
    }, true);

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlayEl) closeModal();
    });

    window.AiToolTimeline = {
        open: open,
        close: closeModal,
        markNodeGenerating: markNodeGenerating,
        settleNodeResult: settleNodeResult,
        failNode: failNode,
        makeTimelineButton: makeTimelineButton
    };
})();
