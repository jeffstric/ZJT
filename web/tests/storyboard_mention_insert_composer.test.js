// 分镜助手输入框 @ 提及：插入不改重建助手面板（textarea 高度抖动回归）。
import { describe, expect, it } from 'vitest';
import state from '../js/storyboard/state.js';
import { bindEvents } from '../js/storyboard/events.js';

function setupDom() {
    document.body.innerHTML = `
        <div id="app">
            <div class="app-shell">
                <section class="ai-chat-section">
                    <div class="chat-composer">
                        <div class="chat-textarea-row">
                            <textarea id="chat-textarea"></textarea>
                        </div>
                    </div>
                </section>
            </div>
        </div>`;
}

function baseState() {
    state.error = '';
    state.ratioGateActive = false;
    state.showMentionPopup = false;
    state.mentionTab = 'character';
    state.characters = [{ id: 'c1', name: '张三', avatar: '' }];
    state.locations = [];
    state.props = [];
    state.scenes = [];
    state.currentSceneId = null;
    state.inputMessage = '你好世界';
    state.chatMode = 'video';
    state.videoImageMode = 'multi_reference';
    state.agentMessages = [];
    state.agentChatHistoryOpen = true;
    state.agentChatLogPinned = false;
    state.agentChatFontStep = 0;
    state.editionInfo = { mode: 'community' };
    state.videoMediaItems = [];
    state.mediaStackExpanded = false;
    state.showVideoModePanel = false;
    state.videoModels = [];
    state.videoModelKey = '';
    state.imageModels = [];
    state.dialogueModels = [];
    state.showEpisodePicker = false;
    state.sceneCandidates = {};
    state.candidateUploadsBySceneId = {};
    state.candidateDeletesBySceneId = {};
    state.storyboardId = null;
    state.lastPowerSpend = null;
    state.subtitleEnabled = false;
}

describe('storyboard chat mention insert keeps the composer textarea', () => {
    it('inserts at the pressed-@ caret without rebuilding the textarea', async () => {
        setupDom();
        baseState();
        bindEvents();

        const ta = document.getElementById('chat-textarea');
        ta.focus();
        ta.value = '你好世界';
        ta.setSelectionRange(2, 2);

        ta.dispatchEvent(new KeyboardEvent('keydown', { key: '@', bubbles: true, cancelable: true }));
        expect(state.showMentionPopup).toBe(true);
        const item = document.querySelector('[data-region="modals"] [data-mention-item="张三"]');
        expect(item).toBeTruthy();

        // 按下弹窗按钮不转移焦点（:focus-within 高度不塌）
        const down = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
        item.dispatchEvent(down);
        expect(down.defaultPrevented).toBe(true);
        expect(document.activeElement).toBe(ta);

        item.click();
        await Promise.resolve();

        // 关键断言：textarea 是同一个元素（面板未重建，高度不瞬塌回弹）
        expect(document.getElementById('chat-textarea')).toBe(ta);
        expect(state.showMentionPopup).toBe(false);
        expect(state.inputMessage).toBe('你好@张三 世界');
        expect(ta.value).toBe('你好@张三 世界');
        expect(ta.selectionStart).toBe(6);
        expect(document.activeElement).toBe(ta);
    });
});
