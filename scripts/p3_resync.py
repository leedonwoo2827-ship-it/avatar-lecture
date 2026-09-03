# -*- coding: utf-8 -*-
"""P3 — 만들어진 목소리 길이에 자막을 다시 맞춘다.

    강의/<작업>/subs/sceneNN.<lang>.srt   (대본 시각 기준)
        → 강의/<작업>/aligned/sceneNN.<lang>.srt   (실제 목소리 기준)

대본에 적힌 씬 길이(71초)는 **시연본 음성 기준**이다. perso TTS 로 다시 만들면
같은 문장이라도 68초나 76초가 나온다. 그대로 두면 자막이 통째로 밀린다.

여기서는 **선형 스케일**로 맞춘다 — 씬 하나의 자막 시각을 `실제/대본` 비율로
늘리거나 줄인다. 씬 경계는 정확히 맞고, 씬 안에서 1~2초 밀릴 수 있다. 밀림이
눈에 띄면 그때 재전사 정렬(scripts/s2_transcribe.py 로 다시 받아쓰고 단어
타임스탬프에 맞추는 방식)로 올린다 — 지금 그것까지 하면 크레딧도 안 쓴 채로
확인만 오래 걸린다.

스케일한 뒤에는 반드시 enforce_timing 을 통과시킨다. 줄어드는 쪽으로 스케일하면
1.2초를 못 채우는 큐가 생기고, 늘어나는 쪽이면 6초를 넘는 큐가 생긴다 — 둘 다
s3_cue.py 가 지키는 규칙이라 여기서도 같게 지킨다.

    python scripts/p3_resync.py --task lecture01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import ROOT, die, load_json, mmss, need, save_json, scene_paths
from scripts.cues import Cue, enforce_timing, parse_srt, to_srt



def main() -> None:
    ap = argparse.ArgumentParser(description="목소리 길이에 자막 맞추기")
    ap.add_argument("--task", default="lecture01")
    a = ap.parse_args()

    P = scene_paths(a.task)
    meta = load_json(need(P.meta, "p1_scenes.py 를 먼저 돌리세요"))
    lang = meta["sub_lang"]
    out_dir = P.aligned
    out_dir.mkdir(parents=True, exist_ok=True)

    todo = [r for r in meta["scenes"] if r.get("voice")]
    if not todo:
        die("목소리가 아직 없습니다 — p2_voice.py 를 먼저 돌리세요")

    print(f"{len(todo)}씬 — 자막을 목소리 길이에 맞춥니다")
    worst = 0.0
    for r in todo:
        no = int(r["no"])
        # subs/ 에 있는 **모든 언어**를 맞춘다. 기본 자막만 맞추면 트랙으로
        # 얹힐 다른 언어가 옛 시각을 그대로 갖고 있어 소리와 어긋난다.
        found = sorted(P.subs.glob(f"scene{no:02d}.*.srt"))
        if not found:
            die(f"scene{no:02d} 자막이 없습니다 — «다국어 자막» 을 먼저 돌리세요")

        want = float(r["voice_dur"])           # 실제 목소리 길이
        had = float(r["script_dur"])           # 대본에 적힌 길이
        k = (want / had) if had > 0 else 1.0

        n_cue = 0
        for src in found:
            cues = parse_srt(src.read_text(encoding="utf-8-sig"))
            scaled = [Cue(text=c.text, start=c.start * k, end=c.end * k) for c in cues]
            fixed = enforce_timing(scaled, total=want)
            (out_dir / src.name).write_text(to_srt(fixed), encoding="utf-8")
            if src.name == r.get("subs") or n_cue == 0:
                n_cue = len(fixed)
        r["aligned"] = r.get("subs") or found[0].name
        r["aligned_langs"] = [f.name for f in found]
        r["scale"] = round(k, 5)
        shift = abs(want - had)
        worst = max(worst, shift)
        mark = "" if abs(k - 1.0) < 0.005 else f"   ← {k:.3f}배로 늘렸습니다"
        if k < 0.995:
            mark = f"   ← {k:.3f}배로 줄였습니다"
        langs = ", ".join(f.name.split(".")[1] for f in found)
        print(f"  {no:02d}  대본 {mmss(had):>7} → 목소리 {mmss(want):>7}  "
              f"자막 {n_cue:3d}개 [{langs}]{mark}")

    save_json(P.meta, meta)
    print(f"\n가장 큰 차이 {worst:.2f}초")
    if worst < 0.25:
        print("대본과 목소리가 거의 같습니다 — 밀림 걱정은 없습니다.")
    elif worst < 2.0:
        print("선형 스케일로 충분합니다. 검수본에서 씬 가운데를 한 번 보세요.")
    else:
        print("차이가 큽니다 — 검수본에서 밀림이 보이면 재전사 정렬로 올리세요.")
    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
