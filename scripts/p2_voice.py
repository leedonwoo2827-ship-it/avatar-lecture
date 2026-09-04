# -*- coding: utf-8 -*-
"""P2 — 씬마다 목소리를 만든다.

    강의/<작업>/scenes.json  →  강의/<작업>/voice/sceneNN.wav

엔진이 넷이다. **업체를 붙이기 전에 로컬 셋으로 화면을 다 볼 수 있게** 갈라 뒀다 —
크레딧을 쓰지 않고 배치·자막·싱크를 먼저 확정하려는 것이다.

    pkg      **씬별 음성 파일이 이미 있을 때.** 폴더에서 `NNN.mp3` 를 씬 번호로
             짝지어 가져온다(p1 이 슬라이드를 짝짓는 방식과 같다). 재인코딩이
             한 번뿐이라 시연본에서 자르는 것보다 소리가 깨끗하다. 크레딧 0.
    source   시연본 mp4 에서 그 씬 구간의 소리를 그대로 떼어 온다.
             이미 우즈베크어로 녹음된 것이라 검수본이 진짜와 거의 같아진다.
             크레딧 0.
    silent   대본 길이만큼 무음. 시연본이 없을 때 배치만 볼 용도. 크레딧 0.
    heygen   HeyGen TTS. 녹음본 싱크가 안 맞을 때만. 보이스 존재 여부를
             `python -m heygen.cli voices --lang Uzbek` 로 **먼저 무료 확인**할 것.

★ 만든 뒤 **실제 길이를 재서** scenes.json 에 남긴다. 대본에 적힌 길이(71초)와
  실제로 만들어진 길이는 다를 수 있고, 그 차이가 자막을 밀어 버린다. 다음 단계
  (p3b_resync.py)가 이 실측값을 보고 자막을 다시 맞춘다.

    python scripts/p2_voice.py --task lecture01 \
        --engine source --from _context11/last-uz-output/lecture01_uz.mp4
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (ROOT, die, ffmpeg, load_json, mmss, need,
                            probe_duration, save_json, scene_paths)
from scripts.ticker import Ticker

RATE, CH = 44100, 2
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


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


def find_in_pkg(folder: Path, no: int) -> Path | None:
    """`001.mp3` 처럼 **앞 숫자 = 씬 번호**인 파일을 찾는다.

    p1_scenes.py 가 슬라이드를 짝짓는 규칙 그대로다 — 확장자와 뒷말은 자유다.
    한 씬에 여러 개가 걸리면 이름이 가장 앞선 것을 쓴다(정렬해서 첫 번째).
    """
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        m = re.match(r"^(\d+)", f.stem)
        if m and int(m.group(1)) == no:
            return f
    return None


def from_pkg(ff: str, src: Path, out: Path) -> None:
    """씬별 음성 파일 → 파이프라인 규격 wav. **길이는 손대지 않는다.**

    자르지도 늘리지도 않는다 — 이 파일이 곧 그 씬의 진짜 길이이고, p3_resync.py
    가 그 실측값에 자막을 맞춘다. 여기서 대본 길이에 억지로 맞추면 소리가
    빨라지거나 뒤가 잘린다.
    """
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-vn", "-ac", str(CH), "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.is_file():
        die(f"{out.name} 옮기기 실패: {(r.stderr or '')[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="씬별 목소리 만들기")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--engine", default="pkg",
                    choices=["pkg", "source", "silent", "heygen"])
    ap.add_argument("--from", dest="src", default="",
                    help="pkg 엔진은 폴더(NNN.mp3 가 든), source 엔진은 원본 mp4")
    ap.add_argument("--scenes", default="", help="이 씬만 다시 만든다 (기본: 전부)")
    a = ap.parse_args()

    P = scene_paths(a.task)
    meta = load_json(need(P.meta, "p1_scenes.py 를 먼저 돌리세요"))
    rows = meta["scenes"]
    if a.scenes:
        from scripts.p1_scenes import parse_range
        want = set(parse_range(a.scenes, len(rows)))
        rows = [r for r in rows if r["no"] in want]

    src = None
    if a.engine in ("pkg", "source"):
        if not a.src:
            die(f"--engine {a.engine} 에는 --from "
                + ("<NNN.mp3 가 든 폴더>" if a.engine == "pkg" else "<원본mp4>")
                + " 가 필요합니다")
        src = Path(a.src).expanduser().resolve()
        if a.engine == "pkg" and not src.is_dir():
            die(f"음성 폴더를 찾지 못했습니다: {src}")
        if a.engine == "source" and not src.is_file():
            die(f"원본을 찾지 못했습니다: {src}")

    out_dir = P.voice
    out_dir.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()

    print(f"{len(rows)}씬 — 엔진 {a.engine}"
          + (f" · {src.name}" if src else ""))
    made: dict[int, dict] = {}
    for r in rows:
        no = int(r["no"])
        out = out_dir / f"scene{no:02d}.wav"
        with Ticker(f"{no:02d} 목소리"):
            if a.engine == "pkg":
                got_f = find_in_pkg(src, no)
                if got_f is None:
                    die(f"{no:02d}번 씬의 음성 파일이 {src} 에 없습니다 — "
                        f"{no:03d}.mp3 처럼 **앞 숫자가 씬 번호**여야 합니다")
                from_pkg(ff, got_f, out)
            elif a.engine == "source":
                cut_from_source(ff, src, float(r["script_start"]), float(r["script_end"]), out)
            elif a.engine == "heygen":
                from heygen.client import tts
                tts(r["narration"], out, lang="uz")
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
    save_json(P.meta, meta)

    done = [r for r in meta["scenes"] if r.get("voice")]
    print(f"\n{len(done)}씬 · 합계 {mmss(meta['voice_total_sec'])}")
    if a.engine == "silent":
        print("무음입니다 — 배치만 보는 용도입니다. 소리까지 보려면 --engine source 를 쓰세요.")
    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
