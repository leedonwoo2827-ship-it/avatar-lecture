# -*- coding: utf-8 -*-
"""T3 — 씬별 PNG + WAV → 45분 dummy.mp4.

    <재료폴더>/_build/slides/NNN.png + _build/audio/NNN.wav
        → <재료폴더>/_build/_seg/NNN.mp4   (한 씬씩)
        → <재료폴더>/dummy.mp4             (전부 이어 붙인 것)

260818 s6_assemble이 하던 것과 같다 — 이미지 한 장을 오디오 길이만큼 늘려 조각
mp4를 만들고 이어 붙인다. 조각(`_seg/`)은 안 지운다. 중간에 한 씬만 다시 만들고
싶을 때 나머지를 다시 굽지 않아도 된다.

★ **자막은 굽지 않는다.** 굽어 버리면 본 파이프라인의 s2(전사)·s3(자막 만들기)가
  제대로 도는지 검증할 수 없다 — 정답을 화면에 띄워 놓고 시험을 보는 셈이 된다.
  Claude Code 데스크탑이 준 subs.uz.srt 는 나중에 s3 결과와 견줄 **정답지**로
  따로 둔다.

산출된 dummy.mp4 를 본 파이프라인에 넣으면 된다:
    python scripts/s1_ingest.py <재료폴더>/dummy.mp4 --slides <재료폴더>/_build/slides
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1920, 1080


def die(msg: str) -> None:
    raise SystemExit(f"오류: {msg}")


def ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        die("ffmpeg를 찾지 못했습니다")
    return ff


def clip(ff: str, png: Path, wav: Path, dst: Path) -> None:
    """이미지 한 장 + 오디오 → mp4 조각. 오디오 길이에 맞춰 끝난다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=white,format=yuv420p")
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y",
         "-loop", "1", "-framerate", "25", "-i", str(png),
         "-i", str(wav),
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
         "-shortest", str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not dst.is_file():
        die(f"{dst.name} 만들기 실패: {(r.stderr or '')[-300:]}")


def concat(ff: str, parts: list[Path], out: Path) -> None:
    lst = out.with_name("_concat.txt")
    q = chr(39)
    lst.write_text("\n".join("file " + q + p.resolve().as_posix() + q for p in parts) + "\n",
                   encoding="utf-8")
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lst.unlink(missing_ok=True)
    if r.returncode != 0 or not out.is_file():
        die(f"이어 붙이기 실패: {(r.stderr or '')[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="씬별 PNG+WAV → dummy.mp4")
    ap.add_argument("folder", help="_build/ 가 있는 폴더")
    a = ap.parse_args()

    root = Path(a.folder).expanduser().resolve()
    build = root / "_build"
    pngs = sorted((build / "slides").glob("*.png"))
    wavs = sorted((build / "audio").glob("*.wav"))
    if not pngs:
        die(f"{build / 'slides'} 에 PNG가 없습니다 — t2를 먼저 돌리세요")
    if not wavs:
        die(f"{build / 'audio'} 에 WAV가 없습니다 — t1을 먼저 돌리세요")
    if len(pngs) != len(wavs):
        die(f"슬라이드 {len(pngs)}장인데 오디오는 {len(wavs)}개입니다 — "
            f"script.json 항목 수와 slides/*.html 개수를 맞추세요")

    ff = ffmpeg()
    seg_dir = build / "_seg"
    segs = []
    print(f"{len(pngs)}개 조각 만드는 중…")
    for i, (p, w) in enumerate(zip(pngs, wavs), 1):
        dst = seg_dir / f"{i:03d}.mp4"
        clip(ff, p, w, dst)
        segs.append(dst)
        print(f"  {dst.name}")

    out = root / "dummy.mp4"
    print("이어 붙이는 중…")
    concat(ff, segs, out)

    print(f"완료 — {out}")
    print()
    print("본 파이프라인에 넣으려면:")
    slides_dir = build / "slides"
    print(f'  python scripts/s1_ingest.py "{out}" --slides "{slides_dir}"')


if __name__ == "__main__":
    main()
