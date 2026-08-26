# -*- coding: utf-8 -*-
"""S5 — 슬라이드가 화면에서 언제 바뀌는지 찾아 씬 표를 만든다.

    output/NN/00/<원본>.mp4 + 00/slides/*.png
        → output/NN/05/scenes.json · 05/scenes.csv

260818의 s3_match_slides는 **영상이 없어서** 슬라이드 글자와 전사문을 Claude로
견줘 맞춰야 했다. 여기는 다르다 — 강의 영상이 통째로 있고, 강의 영상에서 슬라이드가
넘어가는 순간은 **화면이 확 바뀌는 순간**이다. ffmpeg의 장면 검출이 그걸 그대로
집어낸다. LLM을 부르지 않으니 공짜고, 120강을 돌려도 비용이 0이다.

    ffmpeg -vf "select='gt(scene,0.30)',metadata=print"

검출된 씬 개수와 받아온 슬라이드 장수가 맞으면 순서대로 짝지어 준다. 안 맞으면
**억지로 맞추지 않고 그대로 보고한다** — 애니메이션이 들어간 슬라이드는 한 장이
여러 씬으로 잡히고, 넘김 효과가 부드러우면 두 장이 한 씬으로 잡힌다. 그건 사람이
05/scenes.json 을 보고 판단할 일이다.

★ 슬라이드 이미지를 안 받았으면(s1에서 --slides 를 안 줬으면) 이 단계는 건너뛴다.
  s6은 scenes.json 이 없어도 돈다.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (IMAGE_EXTS, VIDEO_EXTS, current_workspace, die, ffmpeg,
                            load_json, mmss, paths, save_json)
from scripts.ticker import Ticker
import subprocess

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def detect_changes(video: Path, floor: float) -> list[tuple[float, float]]:
    """화면이 바뀐 순간들 → [(초, 점수)]. 점수가 floor를 넘는 것만 가져온다.

    ★ 임계값을 감으로 정하면 안 된다. ffmpeg 예제에 흔히 쓰이는 0.30은 **실사
      영상 기준**이다. 강의 슬라이드는 흰 배경에 글자만 바뀌어서 실제 전환
      점수가 0.06~0.08밖에 안 된다(2026-08-26 실측). 0.30으로 잡으면 32장짜리
      덱에서 전환이 **한 개도** 안 잡힌다.

      그래서 바닥값(floor)만 아주 낮게 두고 점수를 전부 걷어 온 뒤, 판단은
      호출부가 한다 — 슬라이드 장수를 아니까 상위 N-1개를 고르면 된다.
      (참고: h264 키프레임이 10초마다 0.002쯤 되는 잔점수를 낸다. floor는 그보다
      위에 있어야 한다.)
    """
    args = [ffmpeg(), "-hide_banner", "-nostats", "-i", str(video),
            "-filter_complex", f"select='gt(scene,{floor})',metadata=print",
            "-an", "-f", "null", "-"]
    with Ticker("장면 검출 중"):
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(f"장면 검출 실패: {(r.stderr or '')[-400:]}")

    err = r.stderr or ""
    times = _PTS_RE.findall(err)
    scores = _SCORE_RE.findall(err)
    if len(times) != len(scores):
        die(f"장면 검출 결과를 읽지 못했습니다 (시각 {len(times)}개, 점수 {len(scores)}개)")
    rows = [(float(t), float(sc)) for t, sc in zip(times, scores) if float(t) > 0.5]
    return sorted(rows)


def pick_boundaries(rows: list[tuple[float, float]], n_slides: int,
                    threshold: float | None) -> tuple[list[float], str]:
    """전환 목록 → 슬라이드 경계 시각. → (경계들, 어떻게 골랐는지)

    슬라이드 장수를 알면 **점수 상위 n-1개**를 고른다. 임계값을 맞추는 것보다
    훨씬 튼튼하다 — 슬라이드마다 바뀌는 글자 양이 달라 점수가 0.06~0.08로
    흔들리는데, 개수로 고르면 그 흔들림이 상관없어진다.
    """
    if threshold is not None:
        return [t for t, sc in rows if sc >= threshold], f"임계값 {threshold} 이상"
    if n_slides > 1 and len(rows) >= n_slides - 1:
        top = sorted(rows, key=lambda r: -r[1])[:n_slides - 1]
        return sorted(t for t, _ in top), f"점수 상위 {n_slides - 1}개"
    return [t for t, sc in rows], "검출된 전부"


def main() -> None:
    ap = argparse.ArgumentParser(description="슬라이드가 바뀌는 순간 찾기 → 씬 표")
    ap.add_argument("--floor", type=float, default=0.01,
                    help="이 점수 미만은 화면 변화로 안 본다 (기본 0.01 — "
                         "h264 키프레임 잔점수 0.002보다 위)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="개수로 고르지 말고 이 점수 이상만 경계로 잡는다 "
                         "(슬라이드 장수를 모를 때나 개수 선택이 틀렸을 때)")
    a = ap.parse_args()

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")

    vids = [p for p in P.src.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS] \
        if P.src.is_dir() else []
    if not vids:
        die(f"{P.src} 에 원본 영상이 없습니다 — s1_ingest.py를 먼저 돌리세요")
    video = vids[0]

    slides = sorted(p for p in P.src_slides.iterdir() if p.suffix.lower() in IMAGE_EXTS) \
        if P.src_slides.is_dir() else []

    # 슬라이드를 안 받은 강의는 씬 표를 만들 게 없다. 조용히 건너뛴다 — 여기서
    # 죽으면 run.bat 이 멈춘다. 장면 검출이 35분 영상에 30초쯤 걸리니 헛일을
    # 시키지 않는 것도 이유다.
    if not slides:
        print("슬라이드가 없어 씬 매핑을 건너뜁니다 (s6은 그래도 돕니다)")
        print("다음: python scripts/s6_package.py --sub-lang ru")
        return

    total = float(load_json(P.meta)["duration"]) if P.meta.is_file() else 0.0
    rows = detect_changes(video, a.floor)
    print(f"화면 변화 {len(rows)}곳 검출 (바닥값 {a.floor}) · 받아온 슬라이드 {len(slides)}장")
    if rows:
        top = sorted(rows, key=lambda r: -r[1])
        print(f"  점수 범위 — 가장 큰 {top[0][1]:.3f} · 가장 작은 {top[-1][1]:.3f}")

    cuts, how = pick_boundaries(rows, len(slides), a.threshold)
    starts = [0.0] + cuts
    print(f"씬 {len(starts)}개 ({how})")

    # 고른 경계와 버린 것의 점수 차이를 보여 준다 — 깔끔하게 갈렸는지 사람이 판단한다
    if a.threshold is None and cuts and len(rows) > len(cuts):
        chosen = {round(t, 3) for t in cuts}
        picked = [sc for t, sc in rows if round(t, 3) in chosen]
        dropped = [sc for t, sc in rows if round(t, 3) not in chosen]
        if picked and dropped:
            print(f"  고른 것 최저 {min(picked):.3f}  vs  버린 것 최고 {max(dropped):.3f}"
                  + ("   ← 깔끔하게 갈렸습니다" if min(picked) > max(dropped) * 3
                     else "   ← 차이가 작습니다. 05/scenes.json 을 확인하세요"))

    if slides and len(starts) != len(slides):
        print(f"경고: 씬({len(starts)})과 슬라이드({len(slides)}) 개수가 다릅니다.")
        print("      애니메이션이 있으면 한 장이 여러 씬으로, 넘김 효과가 부드러우면")
        print("      여러 장이 한 씬으로 잡힙니다. --floor 를 더 낮춰 보거나")
        print("      05/scenes.json 을 직접 고치세요 (억지로 맞추지 않습니다).")

    rows = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else (total or s + 1.0)
        rows.append({
            "no": i + 1,
            "start_sec": round(s, 2),
            "end_sec": round(e, 2),
            "slide": slides[i].name if i < len(slides) else "",
        })

    save_json(P.scenes, rows)
    P.scenes_csv.parent.mkdir(parents=True, exist_ok=True)
    # 외주업체가 엑셀로 열어 본다 — 윈도 엑셀이 UTF-8을 알아보게 BOM을 붙인다
    with P.scenes_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["씬", "시작", "끝", "길이(초)", "슬라이드"])
        for r in rows:
            w.writerow([r["no"], mmss(r["start_sec"]), mmss(r["end_sec"]),
                        f"{r['end_sec'] - r['start_sec']:.1f}", r["slide"]])

    print(f"완료 — {P.scenes}")
    print(f"       {P.scenes_csv}")
    short = [r for r in rows if r["end_sec"] - r["start_sec"] < 2.0]
    if short:
        print(f"경고: 2초도 안 되는 씬이 {len(short)}개 — 애니메이션일 수 있습니다 "
              f"(--threshold 를 올려 보세요)")
    print("다음: python scripts/s6_package.py --sub-lang ru")


if __name__ == "__main__":
    main()
