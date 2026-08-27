/**
 * 剧本分段拆分任务客户端（视频工作流）。
 *
 * 见 docs/script/script_parser_incremental_split_design.md §14。
 * 负责提交任务、轮询状态、恢复、继续、获取结果和幂等物化节点。
 * 抽离自 script_node.js，避免 video_workflow.html 内联逻辑膨胀。
 */
(function () {
    'use strict';

    // 任务终态：进入后停止轮询
    const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled'];
    // 需要用户干预的非终态
    const INTERACTIVE_STATUSES = ['paused', 'waiting_auth'];

    /** 规范化分镜拆分模式（与故事板 sequence_mode 对齐）。 */
    function normalizeSequenceMode(mode) {
        const value = String(mode || '').trim().toLowerCase();
        if (value === 'speed' || value === 'balanced' || value === 'quality') return value;
        // 与故事板前端默认一致
        return 'balanced';
    }

    /** 构造提交请求体（两个拆分按钮共用）。 */
    function buildSplitRequestBody(scriptNodeData, defaultWorldId) {
        const qcRounds = Number(scriptNodeData.scriptSplitQcMaxRounds);
        return {
            script_content: scriptNodeData.scriptContent,
            max_group_duration: scriptNodeData.maxGroupDuration || 15,
            world_id: defaultWorldId,
            force_medium_shot: scriptNodeData.forceMediumShot || false,
            no_bg_music: scriptNodeData.noBgMusic || false,
            split_multi_dialogue: scriptNodeData.splitMultiDialogue || false,
            dialogue_language: scriptNodeData.dialogueLanguage || '',
            prompt_language: scriptNodeData.promptLanguage || '',
            model: scriptNodeData.splitModel || 'deepseek-v4-flash',
            model_id: scriptNodeData.splitModelId || '',
            vendor_id: scriptNodeData.splitModelVendorId || '',
            enable_thinking: scriptNodeData.enableThinking === true,
            thinking_effort: scriptNodeData.thinkingEffort || 'medium',
            // 与故事板 generate-from-script 对齐
            sequence_mode: normalizeSequenceMode(scriptNodeData.sequenceMode),
            enable_script_split_qc: scriptNodeData.enableScriptSplitQc === true,
            script_split_qc_max_rounds: [1, 2, 3, 4, 5].includes(qcRounds) ? qcRounds : 2,
        };
    }

    /** 提交拆分任务，返回 { task_id, status_url }。后端返回 202。 */
    async function submitSplitTask(scriptNodeData, defaultWorldId) {
        const response = await fetch('/api/parse-script', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...(window.getAuthHeaders ? window.getAuthHeaders() : {}) },
            body: JSON.stringify(buildSplitRequestBody(scriptNodeData, defaultWorldId)),
        });
        const result = await response.json();
        if (!result || result.code !== 0 || !result.data || !result.data.task_id) {
            throw new Error((result && result.message) || '提交拆分任务失败');
        }
        return result.data; // { task_id, status, status_url }
    }

    /** 查询任务轻量状态。 */
    async function getTaskStatus(taskId) {
        const resp = await fetch(`/api/script-split/tasks/${taskId}`, {
            headers: { ...(window.getAuthHeaders ? window.getAuthHeaders() : {}) },
        });
        const result = await resp.json();
        if (!result || result.code !== 0) {
            throw new Error((result && result.message) || '查询任务状态失败');
        }
        return result.data; // to_public_status 结构
    }

    /** 获取最终合并结果（仅 completed 可取）。 */
    async function getTaskResult(taskId) {
        const resp = await fetch(`/api/script-split/tasks/${taskId}/result`, {
            headers: { ...(window.getAuthHeaders ? window.getAuthHeaders() : {}) },
        });
        const result = await resp.json();
        if (!result || result.code !== 0) {
            throw new Error((result && result.message) || '获取任务结果失败');
        }
        return result.data; // parsed_data
    }

    /** 恢复 paused / waiting_auth 任务。 */
    async function resumeTask(taskId) {
        const resp = await fetch(`/api/script-split/tasks/${taskId}/resume`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...(window.getAuthHeaders ? window.getAuthHeaders() : {}) },
        });
        const result = await resp.json();
        if (!result || result.code !== 0) {
            throw new Error((result && result.message) || '恢复任务失败');
        }
        return result.data;
    }

    /** 协作式取消。 */
    async function cancelTask(taskId) {
        const resp = await fetch(`/api/script-split/tasks/${taskId}/cancel`, {
            method: 'POST',
            headers: { ...(window.getAuthHeaders ? window.getAuthHeaders() : {}) },
        });
        const result = await resp.json();
        if (!result || result.code !== 0) {
            throw new Error((result && result.message) || '取消任务失败');
        }
        return result.data;
    }

    /**
     * 轮询任务直到终态。
     *
     * @param {number} taskId
     * @param {object} callbacks
     *   - onUpdate(statusData): 每次轮询收到状态时调用
     *   - onComplete(parsedData): 任务 completed 时，自动拉取结果并调用
     *   - onPaused(statusData): 任务进入 paused/waiting_auth 时调用
     *   - onError(error): 终态为 failed/cancelled 或网络错误时调用
     * @returns {function} cancel 函数，调用可停止轮询
     */
    function pollScriptSplitTask(taskId, callbacks) {
        let stopped = false;
        let timer = null;
        let errorBackoff = 1;

        const stop = () => {
            stopped = true;
            if (timer) { clearTimeout(timer); timer = null; }
        };

        const poll = async () => {
            if (stopped) return;
            try {
                const status = await getTaskStatus(taskId);
                errorBackoff = 1; // 重置退避
                if (callbacks.onUpdate) callbacks.onUpdate(status);

                if (TERMINAL_STATUSES.indexOf(status.status) >= 0) {
                    if (status.status === 'completed') {
                        try {
                            const data = await getTaskResult(taskId);
                            if (callbacks.onComplete) callbacks.onComplete(data, status);
                        } catch (e) {
                            if (callbacks.onError) callbacks.onError(e);
                        }
                    } else {
                        if (callbacks.onError) callbacks.onError(
                            new Error(status.message || `任务${status.status}`));
                    }
                    return;
                }
                if (INTERACTIVE_STATUSES.indexOf(status.status) >= 0) {
                    if (callbacks.onPaused) callbacks.onPaused(status);
                    return; // 停止轮询，等用户点击继续
                }
                // 继续轮询：遵循服务端 poll_after_ms
                const interval = status.poll_after_ms || 3000;
                timer = setTimeout(poll, interval);
            } catch (e) {
                if (stopped) return;
                // 网络错误指数退避，上限 30s
                errorBackoff = Math.min(errorBackoff * 2, 10);
                const interval = 3000 * errorBackoff;
                if (callbacks.onUpdate) {
                    callbacks.onUpdate({ status: 'network_error', message: `网络异常，${Math.round(interval / 1000)}s 后重试…` });
                }
                timer = setTimeout(poll, interval);
            }
        };

        poll();
        return stop;
    }

    // 暴露到全局
    window.ScriptSplitTask = {
        buildSplitRequestBody,
        normalizeSequenceMode,
        submitSplitTask,
        getTaskStatus,
        getTaskResult,
        resumeTask,
        cancelTask,
        pollScriptSplitTask,
        TERMINAL_STATUSES,
        INTERACTIVE_STATUSES,
    };
})();
