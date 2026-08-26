# -*- coding: utf-8 -*-
"""자막 큐 — 이 파이프라인의 핵심.

Whisper가 준 **단어 타임스탬프**를 "한 줄짜리 자막"으로 묶는다. 260612의
voicewright/srt.py가 하던 일과 같지만 규칙을 훨씬 조인다:

  1. **큐 하나는 반드시 한 줄** — 큐 본문에 줄바꿈을 넣지 않는다. 두 줄 자막은
     아바타 영상 아래쪽을 다 덮어 버리고, perso 쪽 자막 트랙이 어떻게 접을지도
     모르기 때문에 애초에 접힐 일이 없게 만든다.
  2. 최대 글자수는 언어별(common.CUE_MAX_CHARS) — 키릴 42 / 라틴 46 / 한글 30.
  3. 끊는 자리 우선순위: 문장 끝 → 쉼표·접속사 → 단어 경계. **단어 중간에서는
     절대 안 자른다** (voicewright의 _hard_wrap은 글자 단위 강제 분할까지 갔는데,
     여기서는 그 마지막 수단을 쓰지 않는다 — 러시아어 한 단어가 42자를 넘는 일은
     없고, 넘는다면 그건 STT가 뭔가 잘못 붙인 것이라 조용히 자르면 안 된다).
  4. 시각은 **묶인 첫 단어의 start / 마지막 단어의 end**를 그대로 쓴다. 글자수
     비례 배분(voicewright의 auto_time_cues)이 아니다 — 우리는 진짜 타임스탬프가
     있으니 추정할 이유가 없다.
  5. 너무 짧으면(< 1.2초) 못 읽으니 뒤로 늘리고, 너무 길면(> 6.0초) 잘라 낸다.
     늘리다 다음 큐와 부딪히면 최소 간격(0.08초)을 남기고 멈춘다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Any

from scripts.common import CUE_GAP_SEC, CUE_MAX_SEC, CUE_MIN_SEC, cue_max_chars

# 문장이 끝나는 자리. 러시아어·우즈벡어·영어·한국어를 한 벌로 본다.
_SENT_END = re.compile(r"[.!?…。！？]$")
# 절이 끊기는 자리 — 쉼표류와 콜론·세미콜론·대시.
_CLAUSE_END = re.compile(r"[,;:，、—–]$")
# 쉼표 경계가 목표 지점에서 이만큼 안에 있으면 그쪽에서 끊는다.
CLAUSE_BONUS = 8


@dataclass
class Cue:
    text: str
    start: float
    end: float

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "start": round(self.start, 3), "end": round(self.end, 3)}


def _word_text(w: dict[str, Any]) -> str:
    return (w.get("word") or "").strip()


def _plen(part: list[dict[str, Any]]) -> int:
    """이 단어들을 한 줄로 붙였을 때 글자 수 (단어 사이 공백 포함)."""
    if not part:
        return 0
    return sum(len(_word_text(w)) for w in part) + len(part) - 1


def _split_sentences(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """단어 목록 → 문장별 단어 목록. 문장 끝 부호에서 끊는다."""
    sents: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        t = _word_text(w)
        if not t:
            continue
        cur.append(w)
        if _SENT_END.search(t):
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    return sents


def _break_into(sent: list[dict[str, Any]], k: int) -> list[list[dict[str, Any]]] | None:
    """한 문장을 k조각으로 **고르게** 나눈다.

    앞에서부터 최대 글자수까지 꽉 채우는 방식(voicewright가 하던 것)은 문장 끝에
    한두 단어짜리 꼬리를 남긴다. 그 꼬리가 화면에 0.5초 스쳤다 사라지면 읽을 수
    없다 — 실측으로 1129개 중 200개가 그랬다. 그래서 조각 수를 먼저 정하고
    **길이가 비슷하게** 나눈다. 50자 문장은 42+8이 아니라 25+25가 된다.

    나눌 자리는 목표 지점에 가장 가까운 단어 경계로 잡되, 쉼표 경계가 가까이
    있으면 그쪽을 고른다(CLAUSE_BONUS 글자만큼 양보한다).
    """
    if k <= 1:
        return [sent]
    if k > len(sent):
        return None

    cum: list[int] = []
    acc = 0
    for i, w in enumerate(sent):
        acc += len(_word_text(w)) + (1 if i else 0)
        cum.append(acc)
    total = cum[-1]

    cuts: list[int] = []
    for j in range(1, k):
        want = total * j / k
        lo = (cuts[-1] + 1) if cuts else 0
        hi = len(sent) - (k - j)          # 뒤 조각들에 최소 한 단어씩은 남긴다
        if lo > hi:
            return None
        def cost(i: int) -> float:
            d = abs(cum[i] - want)
            return d - (CLAUSE_BONUS if _CLAUSE_END.search(_word_text(sent[i])) else 0)
        cuts.append(min(range(lo, hi + 1), key=cost))

    parts: list[list[dict[str, Any]]] = []
    prev = 0
    for c in cuts:
        parts.append(sent[prev:c + 1])
        prev = c + 1
    parts.append(sent[prev:])
    return [p for p in parts if p]


def _pack_sentence(sent: list[dict[str, Any]], maxc: int) -> list[list[dict[str, Any]]]:
    """한 문장 → 최대 글자수를 지키는, 길이가 고른 조각들."""
    need = max(1, math.ceil(_plen(sent) / maxc))
    for k in range(need, len(sent) + 1):
        parts = _break_into(sent, k)
        if parts and all(_plen(p) <= maxc for p in parts):
            return parts
    # 단어 하나가 최대 글자수를 넘는 극단 — 단어 중간을 자르지 않는 것이 원칙이라
    # 그대로 내보내고, check.py 가 "글자수 초과"로 잡아 사람에게 알린다.
    return [[w] for w in sent]


def _to_cue(part: list[dict[str, Any]]) -> Cue:
    text = re.sub(r"\s+", " ", " ".join(_word_text(w) for w in part).strip())
    return Cue(text=text, start=float(part[0]["start"]), end=float(part[-1]["end"]))


def group_words(words: list[dict[str, Any]], lang: str) -> list[Cue]:
    """단어 목록 → 한 줄 큐 목록.

    문장 단위로 끊고(문장이 섞이면 읽기 어렵다), 최대 글자수를 넘는 문장만 고르게
    쪼갠다. 그래도 1.2초를 못 채우는 짧은 큐는 다음 큐와 합친다 — 합쳐도 최대
    글자수를 안 넘을 때만.
    """
    maxc = cue_max_chars(lang)
    parts: list[list[dict[str, Any]]] = []
    for sent in _split_sentences(words):
        parts.extend(_pack_sentence(sent, maxc))

    # 너무 짧은 큐를 뒤 큐에 붙인다 — 화면을 스쳐 지나가는 자막을 남기지 않으려는 손질.
    merged: list[list[dict[str, Any]]] = []
    i = 0
    while i < len(parts):
        cur = parts[i]
        while (i + 1 < len(parts)
               and float(cur[-1]["end"]) - float(cur[0]["start"]) < CUE_MIN_SEC
               and _plen(cur) + 1 + _plen(parts[i + 1]) <= maxc):
            i += 1
            cur = cur + parts[i]
        merged.append(cur)
        i += 1

    return [_to_cue(p) for p in merged if p]


def enforce_timing(cues: list[Cue], *, total: float) -> list[Cue]:
    """최소 노출·최대 노출·겹침 금지를 강제한다. 순서는 그대로 둔다."""
    out: list[Cue] = []
    for i, c in enumerate(cues):
        start = max(0.0, float(c.start))
        end = max(float(c.end), start + 0.05)

        # 너무 길게 남아 있지 않게
        if end - start > CUE_MAX_SEC:
            end = start + CUE_MAX_SEC

        # 너무 짧으면 다음 큐 직전까지 늘려 본다 (없으면 영상 끝까지)
        if end - start < CUE_MIN_SEC:
            room = (float(cues[i + 1].start) - CUE_GAP_SEC) if i + 1 < len(cues) else total
            end = min(max(end, start + CUE_MIN_SEC), max(room, start + 0.05))

        # 앞 큐와 겹치면 뒤로 민다 (밀 자리가 없으면 앞 큐를 줄인다)
        if out and start < out[-1].end + CUE_GAP_SEC:
            shifted = out[-1].end + CUE_GAP_SEC
            if shifted < end:
                start = shifted
            else:
                out[-1].end = max(out[-1].start + 0.05, start - CUE_GAP_SEC)

        out.append(Cue(text=c.text, start=start, end=min(end, max(total, start + 0.05))))
    return out


# ── SRT ─────────────────────────────────────────────────────────────────────

def format_timestamp(seconds: float) -> str:
    """`HH:MM:SS,mmm` — 260612 voicewright/srt.py와 같은 구현."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_timestamp(s: str) -> float:
    s = s.strip().replace(".", ",")
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})(?:,(\d{1,3}))?$", s)
    if not m:
        return 0.0
    h, mi, se, ms = m.groups()
    ms = (ms or "0").ljust(3, "0")[:3]
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms) / 1000.0


def to_srt(cues: list[Cue], *, offset: float = 0.0) -> str:
    """Cue 목록 → SRT 문자열. offset을 빼서 청크 로컬 타임코드로 만들 수 있다."""
    parts: list[str] = []
    for i, c in enumerate(cues, 1):
        start = max(0.0, c.start - offset)
        end = max(start + 0.05, c.end - offset)
        # 한 줄 규칙 — 혹시 손편집으로 줄바꿈이 들어왔어도 여기서 한 줄로 편다
        body = re.sub(r"\s+", " ", (c.text or "").strip())
        if not body:
            continue
        parts += [str(i), f"{format_timestamp(start)} --> {format_timestamp(end)}", body, ""]
    return ("\n".join(parts).rstrip() + "\n") if parts else ""


_SRT_TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")


def parse_srt(text: str) -> list[Cue]:
    """SRT 문자열 → Cue 목록. 사람이 손으로 고친 자막을 다시 읽어들일 때 쓴다."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        tm = None
        body: list[str] = []
        for ln in block.splitlines():
            m = _SRT_TIME_RE.search(ln)
            if m and tm is None:
                tm = (parse_timestamp(m.group(1)), parse_timestamp(m.group(2)))
                continue
            if tm is not None:
                body.append(ln)
        if tm is None:
            continue
        joined = re.sub(r"\s+", " ", " ".join(body).strip())
        if joined:
            cues.append(Cue(text=joined, start=tm[0], end=tm[1]))
    return cues


def cues_from_json(rows: list[dict[str, Any]]) -> list[Cue]:
    return [Cue(text=r["text"], start=float(r["start"]), end=float(r["end"])) for r in rows]


def cues_to_json(cues: list[Cue]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in cues]
