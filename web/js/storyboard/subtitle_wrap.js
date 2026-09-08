/**
 * 预览字幕折行/分页：逐行移植 services/storyboard_subtitle.py，
 * 保证界面预览与导出 ASS 硬烧字幕的折行位置、行数上限、页时长分配完全一致。
 * 常量对应 config/constant.py StoryboardSubtitleConstants；后端改动时需同步。
 */

const MAX_WIDTH_RATIO = 0.86;
const CHAR_WIDTH_RATIO = 1.0;
const MIN_CHARS_PER_LINE = 10;
const MAX_LINES = 3;
const MIN_PAGE_DURATION_SECONDS = 0.8;
const DEFAULT_CUE_DURATION_SECONDS = 2.0;
/** 与后端 SMART_CUE_MAX_LINES 一致：smart 逐句模式单条 cue 最大行数 */
const SMART_CUE_MAX_LINES = 2;

const PUNCT_BREAK = new Set([...'，。！？；、,.!?;:：…—-\n\r\t ']);
/** 与后端 _SNAP_PUNCT 一致：smart 切句/二级细分的可吸附标点 */
const SNAP_PUNCT = new Set([...'，。！？；、,.!?;:：…—']);
/** 与后端 _STRIP_FOR_COUNT 一致：字数占比统计时忽略的字符 */
const STRIP_FOR_COUNT = new Set([...SNAP_PUNCT, ' ', '\n', '\r', '\t']);

function contentCharCount(s) {
    let n = 0;
    for (const ch of s) {
        if (!STRIP_FOR_COUNT.has(ch)) n += 1;
    }
    return n;
}

export function normalizeSubtitleText(text) {
    if (!text) return '';
    let s = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    s = s.replace(/[ \t]+/g, ' ');
    s = s.replace(/\n{3,}/g, '\n\n');
    return s.trim();
}

/** 与后端 resolve_font_size 一致 */
export function resolveExportFontSize(height) {
    const raw = Math.round(height / 28);
    return Math.max(28, Math.min(56, raw));
}

/** 与后端 estimate_max_chars_per_line 一致（中文按一字一宽） */
export function estimateMaxCharsPerLine(width, fontSize) {
    const usable = Math.max(1, Math.floor(width * MAX_WIDTH_RATIO));
    const charW = Math.max(1.0, fontSize * CHAR_WIDTH_RATIO);
    const n = Math.floor(usable / charW);
    return Math.max(MIN_CHARS_PER_LINE, n);
}

/** 与后端 wrap_subtitle_lines 一致：按标点优先、再按字数硬切 */
export function wrapSubtitleLines(text, maxChars) {
    const normalized = normalizeSubtitleText(text);
    if (!normalized) return [];
    const limit = Math.max(MIN_CHARS_PER_LINE, Math.floor(maxChars));
    const paragraphs = normalized.split('\n').map((p) => p.trim()).filter(Boolean);
    const lines = [];
    for (const para of paragraphs) {
        lines.push(...wrapParagraph(para, limit));
    }
    return lines;
}

function wrapParagraph(para, maxChars) {
    if (para.length <= maxChars) return [para];
    const lines = [];
    let buf = '';
    let i = 0;
    const n = para.length;
    while (i < n) {
        buf += para[i];
        i += 1;
        if (buf.length < maxChars) continue;
        // 在 buf 内找最近可断点
        let breakAt = -1;
        for (let j = buf.length - 1; j >= Math.max(0, buf.length - Math.floor(maxChars / 3)); j -= 1) {
            if (PUNCT_BREAK.has(buf[j])) {
                breakAt = j + 1;
                break;
            }
        }
        if (breakAt <= 0) breakAt = buf.length;
        const line = buf.slice(0, breakAt).trim();
        buf = buf.slice(breakAt);
        if (line) lines.push(line);
    }
    if (buf.trim()) lines.push(buf.trim());
    return lines;
}

/** 与后端 paginate_lines 一致 */
export function paginateLines(lines, maxLines = MAX_LINES) {
    if (!lines.length) return [];
    const size = Math.max(1, Math.floor(maxLines));
    const pages = [];
    for (let i = 0; i < lines.length; i += size) {
        pages.push(lines.slice(i, i + size));
    }
    return pages;
}

/** 与后端 ellipsize_line 一致 */
export function ellipsizeLine(line, maxChars) {
    const s = (line || '').trim();
    if (s.length <= maxChars) return s;
    if (maxChars <= 1) return '…';
    return `${s.slice(0, maxChars - 1).trimEnd()}…`;
}

/** 与后端 fit_pages_to_duration 一致：装不下则截断末页并加省略号 */
export function fitPagesToDuration(pages, avail, { minPage = MIN_PAGE_DURATION_SECONDS, maxChars } = {}) {
    if (!pages.length) return [];
    const availS = Math.max(0, Number(avail) || 0);
    const minPageS = Math.max(0.1, Number(minPage));
    const chars = Math.max(MIN_CHARS_PER_LINE, Math.floor(maxChars));
    if (availS < 1e-6) {
        const first = [...pages[0]];
        if (pages.length > 1 || (first.length && first.join('').length > chars * 2)) {
            if (first.length) first[first.length - 1] = ellipsizeLine(first[first.length - 1], chars);
        }
        return [first];
    }
    const maxPages = Math.max(1, Math.floor(availS / minPageS));
    if (pages.length <= maxPages) return pages;
    const kept = pages.slice(0, maxPages);
    if (kept.length && kept[kept.length - 1].length) {
        kept[kept.length - 1] = [...kept[kept.length - 1]];
        const lastIdx = kept[kept.length - 1].length - 1;
        kept[kept.length - 1][lastIdx] = ellipsizeLine(kept[kept.length - 1][lastIdx], chars);
    }
    return kept;
}

/** 与后端 allocate_page_durations 一致：字数加权分配各页时长，尽量满足 minPage */
export function allocatePageDurations(pages, avail, { minPage = MIN_PAGE_DURATION_SECONDS } = {}) {
    const n = pages.length;
    if (n === 0) return [];
    const availS = Math.max(0, Number(avail) || 0);
    if (n === 1) return [availS];
    const weights = pages.map((p) => Math.max(1, p.reduce((acc, line) => acc + line.length, 0)));
    const totalW = weights.reduce((a, b) => a + b, 0) || n;
    const raw = weights.map((w) => (availS * w) / totalW);

    const minPageS = availS > 0 ? Math.min(minPage, availS / n) : 0;
    for (let iter = 0; iter < n * 2; iter += 1) {
        const shortIdx = raw.map((d, i) => (d + 1e-9 < minPageS ? i : -1)).filter((i) => i >= 0);
        if (!shortIdx.length) break;
        const need = shortIdx.reduce((acc, i) => acc + (minPageS - raw[i]), 0);
        const longIdx = raw.map((d, i) => (d > minPageS + 1e-9 ? i : -1)).filter((i) => i >= 0);
        if (!longIdx.length) break;
        const pool = longIdx.reduce((acc, i) => acc + (raw[i] - minPageS), 0);
        if (pool <= 1e-9) break;
        for (const i of shortIdx) raw[i] = minPageS;
        for (const i of longIdx) {
            const excess = raw[i] - minPageS;
            raw[i] = minPageS + (excess * Math.max(0, pool - need)) / pool;
        }
    }

    const s = raw.reduce((a, b) => a + b, 0) || 1;
    return raw.map((d) => (d * availS) / s);
}

/** 与后端 split_long_seg_by_inner_punct 的原子切分一致：按可吸附标点切段（标点保留在段尾） */
function splitSnapAtoms(text) {
    const atoms = [];
    let buf = '';
    for (const ch of text) {
        buf += ch;
        if (SNAP_PUNCT.has(ch)) {
            atoms.push(buf.trim());
            buf = '';
        }
    }
    if (buf.trim()) atoms.push(buf.trim());
    return atoms.filter(Boolean);
}

/**
 * smart（逐句）模式的字幕页：预览侧无 ASR 句级时间轴（导出时才调 SenseVoice），
 * 用标点切句近似 ASR 句界，再按后端 split_long_seg_by_inner_punct 的贪心合并
 * 保证每条 ≤ SMART_CUE_MAX_LINES 行（烧录不会出现 3 行同屏）。
 * 单片段自身超行（标点太稀）时交回 MAX_LINES 分页，与后端回退路径一致。
 */
export function buildSmartCuePages(text, maxChars) {
    const normalized = normalizeSubtitleText(text);
    if (!normalized) return [];
    const chars = Math.max(MIN_CHARS_PER_LINE, Math.floor(maxChars));
    const atoms = splitSnapAtoms(normalized);
    if (atoms.length < 2) {
        return paginateLines(wrapSubtitleLines(normalized, chars), MAX_LINES);
    }
    const groups = [];
    let cur = [atoms[0]];
    for (const atom of atoms.slice(1)) {
        if (wrapSubtitleLines(cur.join('') + atom, chars).length <= SMART_CUE_MAX_LINES) {
            cur.push(atom);
        } else {
            groups.push(cur);
            cur = [atom];
        }
    }
    groups.push(cur);
    const pages = [];
    for (const group of groups) {
        const lines = wrapSubtitleLines(group.join(''), chars);
        if (lines.length <= SMART_CUE_MAX_LINES) {
            pages.push(lines);
        } else {
            pages.push(...paginateLines(lines, MAX_LINES));
        }
    }
    return pages;
}

/** smart 模式页时长：按去标点字符占比分配（与后端 ASR 切句/二级细分的内插口径一致） */
function allocateSmartDurations(pages, avail) {
    const weights = pages.map((p) => Math.max(1, contentCharCount(p.join(''))));
    const total = weights.reduce((a, b) => a + b, 0) || 1;
    return weights.map((w) => (avail * w) / total);
}

/**
 * 单条对白的字幕分页器（对应导出字幕 cue）：
 * 创建时折行分页；音频时长已知后 setDuration 截断页数（仅 block）并分配页时长；
 * textAt(t) 返回 t 秒时刻应显示的文本（\n 分行），无变化时返回上次结果。
 * mode = 'smart'（默认逐句，≤2 行/页）或 'block'（整段，≤3 行/页）。
 */
export function createSubtitlePager(text, maxChars, { mode = 'smart' } = {}) {
    const chars = Math.max(MIN_CHARS_PER_LINE, Math.floor(maxChars) || MIN_CHARS_PER_LINE);
    const smart = mode === 'smart';
    const rawPages = smart
        ? buildSmartCuePages(text, chars)
        : paginateLines(wrapSubtitleLines(text, chars), MAX_LINES);
    let pages = rawPages;
    let durations = null;
    let lastText = null;

    function pageText(page) {
        return (page || []).join('\n');
    }

    return {
        isEmpty: rawPages.length === 0,
        /** 音频时长（秒）已知后调用；可重复调用（幂等） */
        setDuration(avail) {
            const dur = Number.isFinite(avail) && avail > 0 ? avail : DEFAULT_CUE_DURATION_SECONDS;
            if (smart) {
                // smart：页与时长无关（不截断），时长仅用于页间切换时机
                durations = allocateSmartDurations(rawPages, dur);
            } else {
                pages = fitPagesToDuration(rawPages, dur, { maxChars: chars });
                durations = allocatePageDurations(pages, dur);
            }
        },
        /** t 秒时刻应显示的字幕文本 */
        textAt(t) {
            if (!pages.length) return '';
            let idx = 0;
            if (durations && durations.length) {
                let acc = 0;
                const time = Math.max(0, Number(t) || 0);
                for (let i = 0; i < pages.length; i += 1) {
                    acc += durations[i] || 0;
                    if (time < acc || i === pages.length - 1) {
                        idx = i;
                        break;
                    }
                }
            }
            const next = pageText(pages[idx]);
            if (next === lastText) return lastText;
            lastText = next;
            return next;
        },
    };
}
