# -*- coding: utf-8 -*-
"""P2 — 씬마다 목소리를 만든다.

    build/<task>/scenes.json  →  build/<task>/voice/sceneNN.wav

엔진이 셋이다. **perso 를 붙이기 전에 나머지 둘로 화면을 다 볼 수 있게** 갈라 뒀다 —
크레딧을 쓰지 않고 배치·자막·싱크를 먼저 확정하려는 것이다.

    source   시연본 mp4 에서 그 씬 구간의 소리를 그대로 떼어 온다. **기본값.**
             이미 우즈베크어로 녹음된 것이라 검수본이 진짜와 거의 같아진다.
             크레딧 0.
    silent   대본 길이만큼 무음. 시연본이 없을 때 배치만 볼 용도. 크레딧 0.
    perso    perso TTS. API 키를 넣은 뒤에 쓴다.

★ 만든 뒤 **실제 길이를 재서** scenes.json 에 남긴다. 대본에 적힌 길이(71초)와
  실제로 만들어진 길이는 다를 수 있고, 그 차이가 자막을 밀어 버린다. 다음 단계
  (p3b_resync.py)가 이 실측값을 보고 자막을 다시 맞춘다.

    python scripts/p2_voice.py --task lecture01 \
        --engine source --from _context11/last-uz-output/lecture01_uz.mp4
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (ROOT, die, ffmpeg, load_json, mmss, need,
                            probe_duration, save_json)
from scripts.ticker import Ticker

BUILD = ROOT / "build"
RATE, CH = 44100, 2


def cut_from_source(ff: str, src: Path, start: float, end: float, out: Path) -> None:
    """시연본에서 그 구간의 소리만 떼어 낸다."""
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
         "-vn", "-ac", str(CH), "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.is_file():
        die(f"{out.name} 떼어 내기 실패: {(r.stderr or '')[-300:]}")


def silence(ff: str, sec: float, out: Path) -> None:
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo",
         "-t", f"{sec:.3f}", "-c:a", "pcm_s16le", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.is_file():
        die(f"{out.name} 무음 만들기 실패: {(r.stderr or '')[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="씬별 목소리 만들기")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--engine", default="source", choices=["source", "silent", "perso"])
    ap.add_argument("--from", dest="src", default="", help="source 엔진이 쓸 원본 mp4")
    ap.add_argument("--scenes", default="", help="이 씬만 다시 만든다 (기본: 전부)")
    a = ap.parse_args()

    task = BUILD / a.task
    meta = load_json(need(task / "scenes.json", "p1_scenes.py 를 먼저 돌리세요"))
    rows = meta["scenes"]
    if a.scenes:
        from scripts.p1_scenes import parse_range
        want = set(parse_range(a.scenes, len(rows)))
        rows = [r for r in rows if r["no"] in want]

    if a.engine == "perso":
        die("perso 엔진은 아직 붙지 않았습니다 — API 키를 발급한 뒤 "
            "perso/client.py 의 엔드포인트를 채우고 다시 부르세요. "
            "그때까지는 --engine source 로 시연본 소리를 씁니다.")

    src = None
    if a.engine == "source":
        if not a.src:
            die("--engine source 에는 --from <원본mp4> 가 필요합니다")
        src = Path(a.src).expanduser().resolve()
        if not src.is_file():
            die(f"원본을 찾지 못했습니다: {src}")

    out_dir = task / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()

    print(f"{len(rows)}씬 — 엔진 {a.engine}"
          + (f" · 원본 {src.name}" if src else ""))
    made: dict[int, dict] = {}
    for r in rows:
        no = int(r["no"])
        out = out_dir / f"scene{no:02d}.wav"
        with Ticker(f"{no:02d} 목소리"):
            if a.engine == "source":
                cut_from_source(ff, src, float(r["script_start"]), float(r["script_end"]), out)
            else:
                silence(ff, float(r["script_dur"]), out)
        got = probe_duration(out)
        drift = got - float(r["script_dur"])
        made[no] = {"voice": out.name, "voice_dur": round(got, 3),
                    "voice_engine": a.engine}
        mark = "" if abs(drift) < 0.25 else f"   ← 대본과 {drift:+.2f}초 차이"
        print(f"  {no:02d}  {mmss(got):>7}  {out.name}{mark}")

    for r in meta["scenes"]:
        if r["no"] in made:
            r.update(made[r["no"]])
    meta["voice_total_sec"] = round(
        sum(float(r.get("voice_dur") or 0) for r in meta["scenes"]), 3)
    save_json(task / "scenes.json", meta)

    done = [r for r in meta["scenes"] if r.get("voice")]
    print(f"\n{len(done)}씬 · 합계 {mmss(meta['voice_total_sec'])}")
    if a.engine == "silent":
        print("무음입니다 — 배치만 보는 용도입니다. 소리까지 보려면 --engine source 를 쓰세요.")
    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
