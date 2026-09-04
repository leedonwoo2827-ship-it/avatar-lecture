# -*- coding: utf-8 -*-
"""검사 — 파이프라인이 규칙을 스스로 어겼는지 한 번에 본다.

    python scripts/check.py --sub-lang ru

눈으로 240장을 확인할 수 없으니, 기계가 확인할 수 있는 것은 전부 기계가 본다.
사람은 "컷 앞뒤를 직접 들어 보기"와 "슬라이드 매핑 표본 확인"만 하면 된다.

하나라도 걸리면 종료 코드가 1이다 — 나중에 여러 강의 배치를 돌릴 때 이 코드로 거른다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (CHUNK_MAX_SEC, CUE_GAP_SEC, CUE_MAX_SEC, CUE_MIN_SEC,
                            VENDOR_LIMIT_SEC, cue_max_chars, current_workspace,
                            load_json, mmss, paths, srt_path)
from scripts.cues import parse_srt

fails: list[str] = []
warns: list[str] = []


def check(ok: bool, label: str, detail: str = "", *, warn: bool = False) -> None:
    mark = "OK  " if ok else ("주의" if warn else "실패")
    tail = f" — {detail}" if (detail and not ok) else ""
    print(f"  [{mark}] {label}{tail}")
    if not ok:
        (warns if warn else fails).append(f"{label}: {detail}")


def join(xs) -> str:
    return ", ".join(str(x) for x in xs)


def main() -> None:
    ap = argparse.ArgumentParser(description="파이프라인 산출물 자동 검사")
    ap.add_argument("--sub-lang", default="ru")
    a = ap.parse_args()
    lang = a.sub_lang

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")
    print()

    print("01·02 — 원본과 전사")
    total = 0.0
    if P.meta.is_file():
        total = float(load_json(P.meta)["duration"])
        check(P.audio.is_file(), "01/audio.m4a 있음")
        check(P.sttwav.is_file(), "01/stt.wav 있음")
    else:
        check(False, "01/media.json 있음", "s1을 돌리세요")
    if P.words.is_file():
        w = load_json(P.words)
        # VAD가 끝부분 무음을 잘라내므로 전사 길이는 영상보다 조금 짧게 나온다
        # (2026-08-26 실측: 2137초 영상 → 2108초, 1.4% 차이). 그건 정상이다.
        # 크게 벌어질 때만 문제다 — 그건 whisper가 오디오를 통째로 놓친 것이다.
        d = float(w["duration"])
        ratio = d / total if total else 0.0
        check(ratio >= 0.90, "전사가 영상을 거의 다 덮음 (90% 이상)",
              f"전사 {d:.1f}초 = 영상의 {ratio * 100:.0f}%")
        check(ratio >= 0.98, "전사 길이가 영상 길이에 가까움 (98% 이상)",
              f"전사 {d:.1f}초 vs 영상 {total:.1f}초 — 끝부분 무음이면 정상입니다",
              warn=True)
        check(bool(w.get("words")), "단어 타임스탬프 있음", "word_timestamps 없이 돌렸습니다")
    else:
        check(False, "02/words.json 있음", "s2를 돌리세요")

    print()
    print("03 — 자막")
    srt = srt_path(P, lang)
    cues = []
    if srt.is_file():
        cues = parse_srt(srt.read_text(encoding="utf-8-sig"))
        maxc = cue_max_chars(lang)
        check(bool(cues), f"{srt.name} 에 큐가 있음")
        over = [c for c in cues if len(c.text) > maxc]
        longest_over = max((len(c.text) for c in over), default=0)
        check(not over, f"모든 큐가 {maxc}자 이하",
              f"{len(over)}개 초과 (가장 긴 것 {longest_over}자)")
        multi = [c for c in cues if "\n" in c.text]
        check(not multi, "모든 큐가 한 줄", f"{len(multi)}개에 줄바꿈")
        ov = [i for i in range(1, len(cues)) if cues[i].start < cues[i - 1].end + CUE_GAP_SEC - 1e-6]
        check(not ov, "겹치는 큐 없음", f"{len(ov)}곳")
        short = [c for c in cues if c.end - c.start < CUE_MIN_SEC - 1e-6]
        check(not short, f"모든 큐가 {CUE_MIN_SEC}초 이상 떠 있음",
              f"{len(short)}개가 더 짧음", warn=True)
        longc = [c for c in cues if c.end - c.start > CUE_MAX_SEC + 1e-6]
        check(not longc, f"모든 큐가 {CUE_MAX_SEC}초 이하", f"{len(longc)}개가 더 김")
    else:
        check(False, f"03/{srt.name} 있음", f"s3_cue.py --lang {lang} 를 돌리세요")

    print()
    print("04 — 업체 분할")
    chunks = []
    if P.chunks.is_file():
        chunks = load_json(P.chunks)
        lens = [float(r["end_sec"]) - float(r["start_sec"]) for r in chunks]
        longest = max(lens, default=0.0)
        check(all(x <= VENDOR_LIMIT_SEC for x in lens),
              f"모든 조각이 업체 한계({mmss(VENDOR_LIMIT_SEC)}) 이하",
              f"가장 긴 조각 {mmss(longest)}")
        check(all(x <= CHUNK_MAX_SEC for x in lens),
              f"모든 조각이 상한({mmss(CHUNK_MAX_SEC)}) 이하 — 마진 확보",
              f"가장 긴 조각 {mmss(longest)}", warn=True)
        covered = sum(lens)
        check(abs(covered - total) <= 1.0, "조각을 다 합치면 원본 길이",
              f"합 {mmss(covered)} vs 원본 {mmss(total)}")
        gaps = [i for i in range(1, len(chunks))
                if abs(float(chunks[i]["start_sec"]) - float(chunks[i - 1]["end_sec"])) > 0.01]
        check(not gaps, "조각 사이에 빈틈·겹침 없음", f"{len(gaps)}곳")
        if cues:
            bad = []
            for r in chunks[1:]:
                t = float(r["start_sec"])
                if any(c.start < t < c.end for c in cues):
                    bad.append(mmss(t))
            check(not bad, "컷이 말 중간에 떨어지지 않음", f"{join(bad)} 에서 말이 잘립니다")
    else:
        check(False, "04/chunks.json 있음", "s4를 돌리세요")

    print()
    print("05 — 씬 매핑")
    if P.scenes.is_file():
        sc = load_json(P.scenes)
        mono = all(float(sc[i]["start_sec"]) >= float(sc[i - 1]["start_sec"])
                   for i in range(1, len(sc)))
        check(mono, "씬 순서가 단조증가")
        unmapped = [r for r in sc if not r.get("slide")]
        check(not unmapped, "모든 씬에 슬라이드가 붙음", f"{len(unmapped)}개 비어 있음", warn=True)
    else:
        print("  [건너뜀] 05/scenes.json 없음 — 슬라이드를 안 받은 강의입니다")

    print()
    print("06 — 업체 패키지")
    if chunks and P.pkg.is_dir():
        wanted = ["audio.m4a", f"subs.{lang}.srt", "scenes.csv", "지시서.md"]
        if (P.pkg / "chunk01" / "video.mp4").is_file():
            wanted.append("video.mp4")
        for r in chunks:
            no = int(r["no"])
            d = P.pkg / f"chunk{no:02d}"
            missing = [n for n in wanted if not (d / n).is_file()]
            check(not missing, f"chunk{no:02d} 파일 다 있음", f"없음: {join(missing)}")
            f = d / f"subs.{lang}.srt"
            if f.is_file():
                cc = parse_srt(f.read_text(encoding="utf-8-sig"))
                first = mmss(cc[0].start) if cc else "없음"
                check(bool(cc) and cc[0].start < 60.0,
                      f"chunk{no:02d} 자막이 0초 근처에서 시작", f"첫 큐가 {first}")
    else:
        check(False, "06/pkg/ 있음", "s6을 돌리세요")

    print()
    if fails:
        print(f"실패 {len(fails)}건:")
        for m in fails:
            print(f"  - {m}")
    if warns:
        print(f"주의 {len(warns)}건:")
        for m in warns:
            print(f"  - {m}")
    if not fails and not warns:
        print("전부 통과.")
    print()
    print("사람이 직접 볼 것: 컷 앞뒤 2초를 들어 보기 · scenes.csv 5장 표본 확인")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
