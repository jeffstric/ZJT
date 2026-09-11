"""台词 ↔ ASR 有序切分。

角色来自 dialogue.character_id，ASR 只提供时间轴。
不是「ASR 句分类成某个角色」，也不是字符串相等匹配。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple
import unicodedata

from config.constant import VoiceReplaceConstants as C

try:
    from pypinyin import Style, lazy_pinyin
    _HAS_PINYIN = True
except ImportError:
    _HAS_PINYIN = False
    Style = None
    lazy_pinyin = None


@dataclass(frozen=True)
class DialogueLine:
    text: str
    character_id: Optional[int] = None
    character_name: str = ""
    id: Optional[int] = None
    sort_order: float = 0.0


@dataclass(frozen=True)
class AsrSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class AlignedSegment:
    start: float
    end: float
    asr_text: str
    score: float
    method: str
    dialogue_id: Optional[int] = None
    character_id: Optional[int] = None
    character_name: str = ""
    dialogue_text: str = ""


@dataclass
class AlignmentResult:
    status: str
    mean_score: float
    unmatched_asr_ratio: float
    segments: List[AlignedSegment] = field(default_factory=list)
    leftover_asr: List[AsrSegment] = field(default_factory=list)
    skip_reason: Optional[str] = None


def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    out = []
    for ch in s:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            out.append(ch)
    return "".join(out)


def lcs_length(a: Sequence, b: Sequence) -> int:
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    prev = [0] * (len(a) + 1)
    for bj in b:
        cur = [0]
        for i, ai in enumerate(a, start=1):
            if ai == bj:
                cur.append(prev[i - 1] + 1)
            else:
                cur.append(prev[i] if prev[i] >= cur[-1] else cur[-1])
        prev = cur
    return prev[-1]


def _pinyin_tokens(normalized: str) -> Tuple[str, ...]:
    if not normalized:
        return ()
    if not _HAS_PINYIN:
        return tuple(normalized)
    tokens = []
    for ch in normalized:
        if "\u4e00" <= ch <= "\u9fff":
            tokens.extend(lazy_pinyin(ch, style=Style.NORMAL))
        else:
            tokens.append(ch)
    return tuple(tokens)


def score_pair(dialogue_text: str, asr_text: str) -> float:
    d = normalize_text(dialogue_text)
    a = normalize_text(asr_text)
    if not d or not a:
        return 0.0
    if d == a:
        return float(C.SUBSTRING_SCORE)
    shorter, longer = (d, a) if len(d) <= len(a) else (a, d)
    if shorter in longer and (len(shorter) / len(longer)) >= 0.75:
        return float(C.SUBSTRING_SCORE)
    lcs = lcs_length(d, a)
    recall = lcs / len(d)
    precision = lcs / len(a)
    pd = _pinyin_tokens(d)
    pa = _pinyin_tokens(a)
    if pd and pa:
        pinyin_recall = lcs_length(pd, pa) / max(1, len(pd))
    else:
        pinyin_recall = recall
    return (
        C.WEIGHT_RECALL * recall
        + C.WEIGHT_PRECISION * precision
        + C.WEIGHT_PINYIN_RECALL * pinyin_recall
    )


def _same_speaker_id(dialogues: Sequence[DialogueLine]) -> Tuple[bool, Optional[int]]:
    ids = [d.character_id for d in dialogues if normalize_text(d.text)]
    if not ids:
        return False, None
    first = ids[0]
    if all(x == first for x in ids):
        return True, first
    return False, None


def _build_char_timeline(asr_segments: Sequence[AsrSegment]) -> Tuple[str, List[Tuple[float, float]]]:
    """规范化后每个字对应的 [start, end) 时间。"""
    chars = []
    spans: List[Tuple[float, float]] = []
    for seg in asr_segments:
        text = normalize_text(seg.text)
        dur = max(0.0, float(seg.end) - float(seg.start))
        if not text:
            continue
        n = len(text)
        step = dur / n if n else dur
        for i, ch in enumerate(text):
            t0 = float(seg.start) + i * step
            t1 = float(seg.start) + (i + 1) * step if i + 1 < n else float(seg.end)
            chars.append(ch)
            spans.append((t0, t1))
    return "".join(chars), spans


def _best_window(dialogue_text: str, remaining: str) -> Tuple[int, int, float]:
    """在 remaining 中找打分最高的 [a, b)，同分取更靠左、更短的窗口。"""
    if not remaining:
        return 0, 0, 0.0
    n = len(remaining)
    best_score = -1.0
    best = (0, 0, 0.0)
    for a in range(n):
        for b in range(a + 1, n + 1):
            raw = score_pair(dialogue_text, remaining[a:b])
            if raw <= 0:
                continue
            penalized = raw - C.WINDOW_GAP_PENALTY * (a / n)
            better = penalized > best_score + 1e-9
            tie_left_shorter = (
                abs(penalized - best_score) <= 1e-9
                and (a < best[0] or (a == best[0] and (b - a) < (best[1] - best[0])))
            )
            if better or tie_left_shorter:
                best_score = penalized
                best = (a, b, raw)
    return best


def _order_split(
    dialogues: Sequence[DialogueLine],
    asr_segments: Sequence[AsrSegment],
) -> List[AlignedSegment]:
    t0 = float(asr_segments[0].start)
    t1 = float(asr_segments[-1].end)
    weights = [max(1, len(normalize_text(d.text))) for d in dialogues]
    total = float(sum(weights)) or float(len(dialogues)) or 1.0
    cursor = t0
    span = max(0.0, t1 - t0)
    out: List[AlignedSegment] = []
    full_text = " ".join(s.text for s in asr_segments)
    for i, d in enumerate(dialogues):
        frac = weights[i] / total
        end = t1 if i == len(dialogues) - 1 else cursor + span * frac
        out.append(
            AlignedSegment(
                start=cursor,
                end=end,
                asr_text=full_text if i == 0 else "",
                score=0.0,
                method=C.METHOD_ORDER,
                dialogue_id=d.id,
                character_id=d.character_id,
                character_name=d.character_name,
                dialogue_text=d.text or "",
            )
        )
        cursor = end
    return out


def _leftover_from_chars(
    concat: str,
    spans: Sequence[Tuple[float, float]],
    used: List[bool],
    asr_segments: Sequence[AsrSegment],
) -> List[AsrSegment]:
    leftover: List[AsrSegment] = []
    i = 0
    n = len(used)
    while i < n:
        if used[i]:
            i += 1
            continue
        j = i
        while j < n and not used[j]:
            j += 1
        leftover.append(
            AsrSegment(
                start=spans[i][0],
                end=spans[j - 1][1],
                text=concat[i:j],
            )
        )
        i = j
    if not leftover and not concat:
        leftover = list(asr_segments)
    return leftover


def _decide_status(mean_score: float, unmatched_ratio: float, method: str) -> str:
    if method == C.METHOD_ORDER:
        return C.STATUS_WAIT_CONFIRM
    if mean_score >= C.SCORE_AUTO and unmatched_ratio <= C.UNMATCHED_ASR_RATIO_CONFIRM:
        return C.STATUS_AUTO
    if mean_score >= C.SCORE_LLM:
        return C.STATUS_NEEDS_LLM
    return C.STATUS_WAIT_CONFIRM


def align_dialogues(
    dialogues: Sequence[DialogueLine],
    asr_segments: Sequence[AsrSegment],
) -> AlignmentResult:
    """把有序对白切到 ASR 时间轴上。"""
    spoken = [d for d in dialogues if normalize_text(d.text)]
    if not spoken:
        return AlignmentResult(
            status=C.STATUS_SKIP,
            mean_score=0.0,
            unmatched_asr_ratio=1.0,
            skip_reason=C.SKIP_NO_DIALOGUE,
        )

    has_audio = any(s.end > s.start for s in asr_segments)
    has_text = any(normalize_text(s.text) for s in asr_segments)
    if not asr_segments or not has_audio or not has_text:
        return AlignmentResult(
            status=C.STATUS_SKIP,
            mean_score=0.0,
            unmatched_asr_ratio=1.0,
            skip_reason=C.SKIP_NO_SPEECH,
        )

    total_dur = sum(max(0.0, s.end - s.start) for s in asr_segments) or 1.0
    same_speaker, unique_cid = _same_speaker_id(spoken)
    if same_speaker:
        name = next((d.character_name for d in spoken if d.character_id == unique_cid), spoken[0].character_name)
        asr_text = " ".join(s.text for s in asr_segments if s.text)
        # 单角色仍打文本分，仅供展示；不参与是否自动 VC 的门槛。
        mean = score_pair("".join(d.text or "" for d in spoken), asr_text)
        return AlignmentResult(
            status=C.STATUS_AUTO,
            mean_score=mean,
            unmatched_asr_ratio=0.0,
            segments=[
                AlignedSegment(
                    start=float(asr_segments[0].start),
                    end=float(asr_segments[-1].end),
                    asr_text=asr_text,
                    score=mean,
                    method=C.METHOD_SINGLE_SPEAKER,
                    dialogue_id=spoken[0].id if len(spoken) == 1 else None,
                    character_id=unique_cid,
                    character_name=name,
                    dialogue_text=" ".join(d.text or "" for d in spoken),
                )
            ],
        )

    concat, spans = _build_char_timeline(asr_segments)
    if not concat:
        return AlignmentResult(
            status=C.STATUS_SKIP,
            mean_score=0.0,
            unmatched_asr_ratio=1.0,
            skip_reason=C.SKIP_NO_SPEECH,
        )

    used = [False] * len(concat)
    cursor = 0
    assigned: List[AlignedSegment] = []
    scores: List[float] = []

    for d in spoken:
        remaining = concat[cursor:]
        a, b, raw = _best_window(d.text or "", remaining)
        if b <= a or raw <= 0:
            assigned.append(
                AlignedSegment(
                    start=spans[cursor][0] if cursor < len(spans) else float(asr_segments[-1].end),
                    end=spans[cursor][0] if cursor < len(spans) else float(asr_segments[-1].end),
                    asr_text="",
                    score=0.0,
                    method=C.METHOD_SKIPPED,
                    dialogue_id=d.id,
                    character_id=d.character_id,
                    character_name=d.character_name,
                    dialogue_text=d.text or "",
                )
            )
            scores.append(0.0)
            continue
        abs_a = cursor + a
        abs_b = cursor + b
        for k in range(abs_a, abs_b):
            used[k] = True
        method = C.METHOD_TEXT
        if raw < C.SCORE_AUTO and _HAS_PINYIN:
            method = C.METHOD_PINYIN
        assigned.append(
            AlignedSegment(
                start=spans[abs_a][0],
                end=spans[abs_b - 1][1],
                asr_text=concat[abs_a:abs_b],
                score=raw,
                method=method,
                dialogue_id=d.id,
                character_id=d.character_id,
                character_name=d.character_name,
                dialogue_text=d.text or "",
            )
        )
        scores.append(raw)
        cursor = abs_b

    leftover = _leftover_from_chars(concat, spans, used, asr_segments)
    leftover_dur = sum(max(0.0, s.end - s.start) for s in leftover)
    unmatched_ratio = leftover_dur / total_dur
    mean_score = sum(scores) / max(1, len(scores))

    if mean_score < C.SCORE_LLM:
        order_segments = _order_split(spoken, asr_segments)
        return AlignmentResult(
            status=C.STATUS_WAIT_CONFIRM,
            mean_score=mean_score,
            unmatched_asr_ratio=unmatched_ratio,
            segments=order_segments,
            leftover_asr=[],
        )

    status = _decide_status(mean_score, unmatched_ratio, C.METHOD_TEXT)
    return AlignmentResult(
        status=status,
        mean_score=mean_score,
        unmatched_asr_ratio=unmatched_ratio,
        segments=assigned,
        leftover_asr=leftover,
    )
