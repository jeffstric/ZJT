/**
 * 故事板全能参考：@首帧图 / @尾帧图 的提交前检查。
 * 图片顺序由服务端 services/storyboard_frame_mention.py 决定，这里只拦截缺图。
 * 标记与画布分镜节点一致，「@首帧图片」不能命中「@首帧图」。
 */

const FIRST_MENTION_RE = /@首帧图(?![\u4e00-\u9fff])/g;
const LAST_MENTION_RE = /@尾帧图(?![\u4e00-\u9fff])/g;

const H3_REFERENCE_KEYS = new Set([
    'minimax_h3_r2v',
    'minimax_h3_reference_to_video',
]);

export const H3_KEYFRAME_REF_MAX_IMAGES = 3;

function mentionFlags(prompt) {
    const text = prompt == null ? '' : String(prompt);
    FIRST_MENTION_RE.lastIndex = 0;
    const wantsFirst = FIRST_MENTION_RE.test(text);
    FIRST_MENTION_RE.lastIndex = 0;
    LAST_MENTION_RE.lastIndex = 0;
    const wantsLast = LAST_MENTION_RE.test(text);
    LAST_MENTION_RE.lastIndex = 0;
    return { wantsFirst, wantsLast };
}

export function promptHasFrameMention(prompt) {
    const flags = mentionFlags(prompt);
    return flags.wantsFirst || flags.wantsLast;
}

export function isH3ReferenceVideoModel(model) {
    if (!model) return false;
    const keys = [model.short_key, model.shortKey, model.key, model.model_key, model.modelKey];
    return keys.some((key) => H3_REFERENCE_KEYS.has(String(key || '')));
}

export function shouldUseH3KeyframeRef(imageMode, model, prompt) {
    return imageMode === 'multi_reference'
        && isH3ReferenceVideoModel(model)
        && promptHasFrameMention(prompt);
}

/**
 * @returns {'missing_first'|'missing_last'|'over_capacity'|null}
 */
export function findFrameMentionError({ imageMode, prompt, firstUrl, lastUrl, model }) {
    if (imageMode !== 'multi_reference') return null;
    const { wantsFirst, wantsLast } = mentionFlags(prompt);
    if (!wantsFirst && !wantsLast) return null;
    if (wantsFirst && !String(firstUrl || '').trim()) return 'missing_first';
    if (wantsLast && !String(lastUrl || '').trim()) return 'missing_last';
    const reserved = (wantsFirst ? 1 : 0) + (wantsLast ? 1 : 0);
    let max = 0;
    if (shouldUseH3KeyframeRef(imageMode, model, prompt)) {
        max = H3_KEYFRAME_REF_MAX_IMAGES;
    } else if (model) {
        const parsed = Number(model.max_multi_ref_images ?? model.maxMultiRefImages ?? 0);
        if (Number.isFinite(parsed) && parsed > 0) max = parsed;
    }
    if (max > 0 && reserved > max) return 'over_capacity';
    return null;
}

/** 光标前一个字符是 @ / ＠ 时去掉它，返回新文本和光标。否则返回 null。 */
export function stripMentionTrigger(value, cursor) {
    const text = value == null ? '' : String(value);
    const pos = cursor == null ? text.length : Number(cursor);
    if (!Number.isFinite(pos) || pos <= 0 || pos > text.length) return null;
    const trigger = text.slice(pos - 1, pos);
    if (trigger !== '@' && trigger !== '＠') return null;
    return {
        value: text.slice(0, pos - 1) + text.slice(pos),
        caret: pos - 1,
    };
}

function trimmedUrl(url) {
    return String(url || '').trim();
}

/**
 * 提交时的首尾帧地址。
 * 非参考模式原样返回槽位。
 * 参考模式：槽位有图用槽位；槽位空且提示词点名了该帧时用分镜图；
 * 没点名则保留空槽，避免把分镜图悄悄当成关键帧。
 */
export function resolveSubmitFrameUrls({
    imageMode,
    prompt,
    slotFirst,
    slotLast,
    sceneFirst,
    sceneLast,
} = {}) {
    const slotF = trimmedUrl(slotFirst);
    const slotL = trimmedUrl(slotLast);
    if (imageMode !== 'multi_reference') {
        return { frame_first_url: slotF, frame_last_url: slotL };
    }
    const { wantsFirst, wantsLast } = mentionFlags(prompt);
    return {
        frame_first_url: slotF || (wantsFirst ? trimmedUrl(sceneFirst) : ''),
        frame_last_url: slotL || (wantsLast ? trimmedUrl(sceneLast) : ''),
    };
}

/** 在光标处插入 @名称 。光标无效时接到末尾。 */
export function insertChatMention(value, caret, name) {
    const label = name == null ? '' : String(name);
    const token = `@${label} `;
    const text = value == null ? '' : String(value);
    let pos = text.length;
    if (caret != null && caret !== '') {
        const parsed = Number(caret);
        if (Number.isFinite(parsed) && parsed >= 0 && parsed <= text.length) pos = parsed;
    }
    return {
        value: text.slice(0, pos) + token + text.slice(pos),
        caret: pos + token.length,
    };
}

export function frameMentionErrorMessage(code, translate) {
    const t = typeof translate === 'function' ? translate : (_key, fallback) => fallback;
    if (code === 'missing_first') {
        return t('msg_frame_mention_missing_first', '视频提示词使用了 @首帧图，请先设置视频首帧');
    }
    if (code === 'missing_last') {
        return t('msg_frame_mention_missing_last', '视频提示词使用了 @尾帧图，请先设置视频尾帧');
    }
    if (code === 'over_capacity') {
        return t('msg_frame_mention_over_capacity', '当前模型的参考图数量不够同时放入首帧和尾帧');
    }
    return '';
}
