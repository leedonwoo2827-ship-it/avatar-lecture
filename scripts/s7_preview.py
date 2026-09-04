# -*- coding: utf-8 -*-
"""S7 — 검수용 자막 번인본. **자막을 이미지로 만들지 않는다.**

    output/NN/00/<원본>.mp4 + 06/pkg/chunkNN/subs.<lang>.srt
        → output/NN/06/_preview/chunkNN.mp4

지금까지 자막을 씬마다 이미지로 만들어 얹느라 10분짜리에도 한참이 걸렸다. 그
작업이 여기서 통째로 없어진다 — ffmpeg의 subtitles 필터가 SRT를 읽어 한 번에
그린다. 글꼴·크기·위치도 필터 인자로 준다.

이건 **검수용**이다. 업체에 올라가는 건 어디까지나 06/pkg/chunkNN/ 안의
클린 오디오와 SRT다. 여기서 구운 mp4는 검수자에게 "이렇게 보입니다" 하고
보여 주는 용도로만 쓴다.

    python scripts/s7_preview.py --limit 60     # 앞 60초만, 빨리 확인할 때

★ ffmpeg의 subtitles 필터는 윈도 경로의 콜론(C:)을 필터 인자 구분자로 오해한다.
  그래서 SRT가 있는 폴더로 들어가 **파일 이름만** 넘긴다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (VIDEO_EXTS, current_workspace, die, ffmpeg, load_json,
                            mmss, need, paths)
from scripts.ticker import Ticker

# 자막 모양 — 아바타 화면 아래를 덜 가리게 아래에서 살짝 띄우고, 검은 테두리를 준다.
# 키릴·라틴 모두 있는 글꼴을 쓴다. 바꾸고 싶으면 이 줄만 고치면 된다.
STYLE = ("FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
         "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
         "Alignment=2,MarginV=40")


def main() -> None:
    ap = argparse.ArgumentParser(description="검수용 자막 번인본 굽기")
    ap.add_argument("--sub-lang", default=None)
    ap.add_argument("--limit", type=float, default=None, help="앞 N초만 굽는다 (빨리 확인용)")
    ap.add_argument("--chunk", type=int, default=None, help="이 조각만 굽는다 (기본: 전부)")
    a = ap.parse_args()

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")
    need(P.chunks, "s4_split.py를 먼저 돌리세요")

    vids = [p for p in P.src.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS] \
        if P.src.is_dir() else []
    if not vids:
        die(f"{P.src} 에 원본 영상이 없습니다")
    video = vids[0]

    chunks = [r for r in load_json(P.chunks)
              if a.chunk is None or int(r["no"]) == a.chunk]
    if not chunks:
        die(f"chunk{a.chunk}를 찾지 못했습니다")

    P.preview.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()

    for r in chunks:
        no, s, e = int(r["no"]), float(r["start_sec"]), float(r["end_sec"])
        d = P.pkg / f"chunk{no:02d}"
        srt = d / f"subs.{a.sub_lang}.srt"
        if not srt.is_file():
            die(f"{srt} 가 없습니다 — s6_package.py --sub-lang {a.sub_lang} 를 먼저 돌리세요")

        end = min(e, s + a.limit) if a.limit else e
        tag = "-앞부분" if a.limit else ""
        out = P.preview / f"chunk{no:02d}{tag}.mp4"
        vf = "subtitles=" + srt.name + ":force_style=" + chr(39) + STYLE + chr(39)

        # SRT가 있는 폴더에서 돌린다 — 필터 인자에 윈도 경로를 넣지 않으려는 것
        args = [ff, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video.resolve()), "-ss", f"{s:.3f}", "-to", f"{end:.3f}",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "160k",
                str(out.resolve())]
        with Ticker(f"chunk{no:02d} 굽는 중 ({mmss(end - s)})"):
            p = subprocess.run(args, cwd=str(d), capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        if p.returncode != 0 or not out.is_file():
            die(f"chunk{no:02d} 굽기 실패: {(p.stderr or '')[-400:]}")
        print(f"  {out.name}  ({mmss(end - s)})")

    print(f"완료 — {P.preview}")
    print("이건 검수용입니다. 업체에 올릴 건 06/pkg/chunkNN/ 안의 클린본입니다.")


if __name__ == "__main__":
    main()
