import { beforeEach, describe, expect, it } from 'vitest';

import state, {
    activateSceneAgentMessages,
    appendSceneAgentMessage,
    finishSceneAgentRun,
    isSceneAgentRunning,
    setSceneAgentTaskId,
    startSceneAgentRun,
} from '../js/storyboard/state.js';

describe('storyboard agent scene session state', () => {
    beforeEach(() => {
        state.currentSceneId = 2;
        state.agentRunsBySceneId = {};
        state.agentMessagesBySceneId = {};
        state.agentMessages = [];
    });

    it('does not lock or overwrite the current scene when another scene is running', () => {
        startSceneAgentRun(1);
        appendSceneAgentMessage(1, { role: 'status', content: 'scene 1 running' });

        expect(isSceneAgentRunning(1)).toBe(true);
        expect(isSceneAgentRunning(2)).toBe(false);
        expect(state.agentMessages).toEqual([]);

        activateSceneAgentMessages(1);
        expect(state.agentMessages).toEqual([
            { role: 'status', content: 'scene 1 running' },
        ]);
    });

    it('does not let a stale task callback finish a newer task for the same scene', () => {
        startSceneAgentRun(1, 'task-old');
        setSceneAgentTaskId(1, 'task-new');

        expect(finishSceneAgentRun(1, 'task-old')).toBe(false);
        expect(isSceneAgentRunning(1)).toBe(true);

        expect(finishSceneAgentRun(1, 'task-new')).toBe(true);
        expect(isSceneAgentRunning(1)).toBe(false);
    });
});
