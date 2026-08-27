# -*- coding: utf-8 -*-
"""S3 — 단어 타임스탬프 → **한 줄짜리** 자막 큐.

    output/NN/02/words.json
        → output/NN/03/cues.json
        → output/NN/03/subs.<lang>.srt

규칙은 전부 scripts/cues.py에 있다 — 한 큐 = 한 줄, 언어별 최대 글자수,
단어 중간 금지, 최소 1.2초·최대 6.0초, 겹침 금지.

이 단계가 내는 것은 **음성을 그대로 받아 적은 자막**이다. 자막을 다른 언어로
내려면 이 SRT의 **타임코드를 그대로 두고 본문만 갈아끼운다** — s3b가 그 일을 한다.

    python scripts/s3_cue.py --lang ko          # 음성 그대로 받아적은 자막
    python scripts/s3b_relabel.py --translate --from ko --to en
    python scripts/s6_package.py --sub-lang en

★ 03/subs.*.srt 는 **사람이 손으로 고쳐도 된다.** s4·s6은 cues.json이 아니라
  손편집 가능성이 있는 SRT를 다시 읽어 쓴다 — 손편집이 이긴다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (CUE_MAX_SEC, cue_max_chars, current_workspace, load_json,
                            mmss, need, paths, save_json, srt_path)
from scripts.cues import cues_to_json, enforce_timing, group_words, to_srt


def main() -> None:
    ap = argparse.ArgumentParser(description="단어 타임스탬프 → 한 줄 자막")
    ap.add_argument("--lang", default=None,
                    help="자막 언어 (안 주면 02/words.json에 기록된 음성 언어를 쓴다)")
    a = ap.parse_args()

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")
    need(P.words, "s2_transcribe.py를 먼저 돌리세요")

    data = load_json(P.words)
    lang = a.lang or data.get("language") or "ru"
    words = data.get("words") or []
    if not words:
        raise SystemExit("오류: 02/words.json 에 단어가 없습니다 — s2를 word_timestamps로 다시 돌리세요")

    maxc = cue_max_chars(lang)
    print(f"단어 {len(words)}개 → 자막 묶는 중… (언어 {lang} · 한 줄 최대 {maxc}자)")

    cues = group_words(words, lang)
    cues = enforce_timing(cues, total=float(data["duration"]))

    save_json(P.cues, cues_to_json(cues))
    out = srt_path(P, lang)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_srt(cues), encoding="utf-8")

    # 자기 검사 — 규칙을 스스로 어겼는지 여기서 바로 말한다
    over = [c for c in cues if len(c.text) > maxc]
    multiline = [c for c in cues if "\n" in c.text]
    overlap = [i for i in range(1, len(cues)) if cues[i].start < cues[i - 1].end]
    longest = max((c.end - c.start for c in cues), default=0.0)

    print(f"완료 — 큐 {len(cues)}개 · {out}")
    print(f"  최대 글자수 초과 : {len(over)}개" + ("" if not over else f"  ← 확인 필요"))
    print(f"  줄바꿈 든 큐     : {len(multiline)}개")
    print(f"  겹치는 큐        : {len(overlap)}개")
    print(f"  가장 긴 큐       : {longest:.1f}초 (상한 {CUE_MAX_SEC:.1f}초)")
    if cues:
        print(f"  첫 큐            : {mmss(cues[0].start)}  {cues[0].text[:50]}")
        print(f"  끝 큐            : {mmss(cues[-1].start)}  {cues[-1].text[:50]}")
    print(f"자막을 다듬으려면 {out.name} 을 직접 고친 뒤 s4부터 다시 돌리세요.")
    print(f"다음: python scripts/s4_split.py --lang {lang}")


if __name__ == "__main__":
    main()
