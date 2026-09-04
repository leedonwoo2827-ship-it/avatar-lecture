# -*- coding: utf-8 -*-
"""S4 — 업체 30분 한계에 맞춰 자를 지점을 정한다.

    output/NN/03/subs.<lang>.srt (또는 03/cues.json)
        → output/NN/04/chunks.json   [{no, start_sec, end_sec, cue_from, cue_to}]

**초를 재서 자르지 않는다.** 말 한가운데를 자르면 아바타 입모양이 그 자리에서
끊겨 버린다. 대신:

  1. 몇 조각이 필요한지 먼저 센다 — `ceil(전체길이 / 28분)`. 45분이면 2조각.
     (업체 한계는 30분이지만 상한을 28분으로 잡아 2분을 마진으로 남긴다.)
  2. 조각이 고르게 나뉘는 목표 시각을 잡는다 — 45분 2조각이면 22분 30초.
     `--targets`로 직접 줄 수도 있다: `--targets 25:00` 이면 25분+20분.
  3. 목표 ± 3분 창 안에서 **큐와 큐 사이 침묵이 가장 긴 자리**를 찾아, 그 침묵의
     한가운데를 컷으로 삼는다. 말이 끊긴 자리라 잘라도 티가 안 난다.
  4. 창 안에 쓸 만한 침묵이 없으면(쉬지 않고 말하는 강의) 가장 가까운 큐 경계에서
     끊고 경고를 띄운다.

★ 04/chunks.json 은 **사람이 손으로 고쳐도 된다.** 컷이 어색하면 초 단위로 고친
  뒤 s6부터 다시 돌리면 그 값이 그대로 쓰인다.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (CHUNK_MAX_SEC, CUT_SEARCH_HALF_SEC, VENDOR_LIMIT_SEC,
                            current_workspace, die, load_json, mmss, paths,
                            save_json, srt_path)
from scripts.cues import Cue, cues_from_json, parse_srt


def load_cues(P, lang: str) -> list[Cue]:
    """손편집 가능성이 있는 SRT를 우선 읽는다. 없으면 s3이 낸 cues.json."""
    srt = srt_path(P, lang)
    if srt.is_file():
        cues = parse_srt(srt.read_text(encoding="utf-8-sig"))
        if cues:
            print(f"자막 읽음 — {srt.name} (큐 {len(cues)}개)")
            return cues
    if P.cues.is_file():
        cues = cues_from_json(load_json(P.cues))
        print(f"자막 읽음 — cues.json (큐 {len(cues)}개)")
        return cues
    die("03/ 에 자막이 없습니다 — s3_cue.py를 먼저 돌리세요")
    return []


def parse_target(s: str) -> float:
    """`25:00` 또는 `1500` → 초."""
    s = s.strip()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)


def find_cut(cues: list[Cue], target: float, lo: float, hi: float) -> tuple[float, int, bool]:
    """[lo, hi] 안에서 가장 긴 침묵의 한가운데. → (컷 시각, 그 앞 큐 인덱스, 침묵을 찾았는가)

    침묵 = 큐 i가 끝나고 큐 i+1이 시작하기까지의 빈 시간.
    """
    best_gap, best_i = -1.0, None
    for i in range(len(cues) - 1):
        end, nxt = cues[i].end, cues[i + 1].start
        if not (lo <= end <= hi):
            continue
        gap = nxt - end
        if gap > best_gap:
            best_gap, best_i = gap, i

    if best_i is not None and best_gap >= 0.30:
        mid = cues[best_i].end + best_gap / 2.0
        return mid, best_i, True

    # 창 안에 쓸 만한 침묵이 없다 — 목표에 가장 가까운 큐 경계에서 끊는다
    if best_i is None:
        best_i = min(range(len(cues) - 1), key=lambda i: abs(cues[i].end - target))
    return cues[best_i].end + 0.01, best_i, False


def main() -> None:
    ap = argparse.ArgumentParser(description="업체 30분 한계에 맞춰 자를 지점 찾기")
    ap.add_argument("--lang", default="ru", help="어느 자막을 기준으로 자를지 (기본 ru)")
    ap.add_argument("--targets", nargs="*", default=None,
                    help="컷 목표 시각을 직접 지정 (예: --targets 25:00). 안 주면 고르게 나눈다")
    a = ap.parse_args()

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")
    cues = load_cues(P, a.lang)
    if not cues:
        die("자막 큐가 비었습니다")

    total = float(load_json(P.meta)["duration"]) if P.meta.is_file() else cues[-1].end
    print(f"전체 {mmss(total)} · 업체 한계 {mmss(VENDOR_LIMIT_SEC)} · 조각 상한 {mmss(CHUNK_MAX_SEC)}")

    if total <= CHUNK_MAX_SEC:
        rows = [{"no": 1, "start_sec": 0.0, "end_sec": round(total, 2),
                 "cue_from": 0, "cue_to": len(cues) - 1}]
        save_json(P.chunks, rows)
        print(f"자를 필요 없음 — 한 조각 ({mmss(total)})")
        print(f"다음: python scripts/s5_scene_map.py")
        return

    # 컷 목표 시각 정하기
    if a.targets:
        targets = sorted(parse_target(t) for t in a.targets)
    else:
        n = math.ceil(total / CHUNK_MAX_SEC)
        targets = [total * i / n for i in range(1, n)]
        print(f"{n}조각으로 고르게 나눕니다 — 조각당 약 {mmss(total / n)}")

    cuts: list[tuple[float, int]] = []
    prev = 0.0
    for t in targets:
        lo = max(prev + 60.0, t - CUT_SEARCH_HALF_SEC)
        hi = min(total - 60.0, t + CUT_SEARCH_HALF_SEC)
        if hi <= lo:
            die(f"컷 목표 {mmss(t)} 주변에 자를 자리가 없습니다 — --targets 로 직접 지정하세요")
        at, idx, found = find_cut(cues, t, lo, hi)
        if not found:
            print(f"경고: {mmss(t)} 주변에 쉬는 자리가 없어 큐 경계에서 끊습니다 "
                  f"({mmss(at)}) — 04/chunks.json 을 직접 확인하세요")
        cuts.append((at, idx))
        prev = at

    rows = []
    starts = [0.0] + [c[0] for c in cuts]
    ends = [c[0] for c in cuts] + [total]
    cue_starts = [0] + [c[1] + 1 for c in cuts]
    cue_ends = [c[1] for c in cuts] + [len(cues) - 1]
    for i, (s, e, cf, ct) in enumerate(zip(starts, ends, cue_starts, cue_ends), 1):
        rows.append({"no": i, "start_sec": round(s, 2), "end_sec": round(e, 2),
                     "cue_from": cf, "cue_to": ct})

    save_json(P.chunks, rows)

    print(f"완료 — {len(rows)}조각 · {P.chunks}")
    bad = False
    for r in rows:
        length = r["end_sec"] - r["start_sec"]
        mark = ""
        if length > VENDOR_LIMIT_SEC:
            mark, bad = "  ← 업체 한계 초과!", True
        elif length > CHUNK_MAX_SEC:
            mark = "  ← 마진 없음, 확인 권장"
        print(f"  chunk{r['no']:02d}  {mmss(r['start_sec'])} ~ {mmss(r['end_sec'])}"
              f"  ({mmss(length)}){mark}")
    if bad:
        die("업체 한계를 넘는 조각이 있습니다 — --targets 로 컷을 직접 지정하세요")
    print("컷이 어색하면 04/chunks.json 을 직접 고친 뒤 s6부터 다시 돌리세요.")
    print("다음: python scripts/s5_scene_map.py   (슬라이드가 없으면 건너뛰고 s6)")


if __name__ == "__main__":
    main()
