# -*- coding: utf-8 -*-
"""S1 — 강의 mp4를 받아 워크스페이스를 열고 오디오 두 벌을 뽑는다.

    <어딘가>/강의.mp4  (+ 슬라이드 이미지 폴더)
        → output/YYMMDDHHmm-강의/00/강의.mp4 · 00/slides/*.png
        → output/YYMMDDHHmm-강의/01/audio.m4a   아바타 립싱크 소스(원본 품질)
        → output/YYMMDDHHmm-강의/01/stt.wav     전사 전용(16kHz mono)
        → output/YYMMDDHHmm-강의/01/media.json  길이·트랙 정보

오디오를 왜 두 벌 뽑는가:
  - `audio.m4a` 는 업체에 그대로 올라갈 물건이다. 원본 품질을 지킨다.
  - `stt.wav`  는 whisper 전용이다. whisper는 내부적으로 16kHz mono로 리샘플하니
    미리 그 모양으로 주면 전사가 빨라지고, 무엇보다 **재인코딩 손실이 전사
    타임스탬프에 섞이지 않는다**. 이 타임스탬프 위에 자막과 분할점이 다 얹히므로
    조금이라도 흔들리면 안 된다.

★ 이 스크립트만 워크스페이스를 새로 만든다. s2~s7은 가장 최근 것을 알아서 쓴다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.bundle import report, scan
from scripts.common import (IMAGE_EXTS, VIDEO_EXTS, die, ffmpeg, new_workspace,
                            paths, probe_duration, run, save_json, mmss)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="강의 영상(또는 번들 폴더) → 워크스페이스 + 오디오 2종")
    ap.add_argument("target",
                    help="강의 영상 파일, 또는 **번들 폴더**(영상·슬라이드가 든 폴더)")
    ap.add_argument("--slides", default=None,
                    help="슬라이드 이미지 폴더. 번들 폴더를 주면 알아서 찾으니 필요 없다")
    ap.add_argument("--dry-run", action="store_true",
                    help="무엇을 찾았는지만 보여 주고 아무것도 만들지 않는다")
    a = ap.parse_args()

    target = Path(a.target).expanduser().resolve()
    slides_arg = a.slides

    if target.is_dir():
        # 번들 폴더 — 안에 뭐가 있는지 찾아 준다
        b = scan(target)
        report(b)
        if b.problems:
            die("번들 폴더를 그대로 쓸 수 없습니다 — 위 '문제'를 먼저 고치세요")
        src = b.video
        if slides_arg is None and b.slides is not None:
            slides_arg = str(b.slides)
        print()
    elif target.is_file():
        src = target
        if src.suffix.lower() not in VIDEO_EXTS:
            print(f"경고: 확장자 {src.suffix}는 낯설지만 일단 시도합니다 (ffmpeg가 알면 됩니다)")
    else:
        die(f"영상 파일도 폴더도 아닙니다: {target}")

    if a.dry_run:
        print("찾기만 했습니다 (--dry-run) — 아무것도 만들지 않았습니다.")
        return

    ws = new_workspace(src.name)
    P = paths(ws)
    # P.media 는 01/ **폴더**다(파일이 아니다). 여기서 안 만들면 아래 ffmpeg가
    # "No such file or directory"로 죽는다 — 2026-08-26 실측.
    P.src.mkdir(parents=True, exist_ok=True)
    P.media.mkdir(parents=True, exist_ok=True)
    print(f"워크스페이스 — {ws.name}")

    # 원본을 00/ 안에 보관한다 — 나중에 다시 볼 수 있어야 한다
    kept = P.src / src.name
    if src != kept:
        print(f"원본 복사 중… ({src.name})")
        shutil.copy2(src, kept)

    dur = probe_duration(kept)
    print(f"길이 — {mmss(dur)} ({dur:.1f}초)")
    if dur < 60:
        print("경고: 1분도 안 되는 영상입니다 — 분할 검증이 안 됩니다")

    ff = ffmpeg()

    print("아바타용 오디오 뽑는 중… (01/audio.m4a)")
    run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(kept),
         "-vn", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
         str(P.audio)], what="audio.m4a 추출")

    print("전사용 오디오 뽑는 중… (01/stt.wav · 16kHz mono)")
    run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(kept),
         "-vn", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
         str(P.sttwav)], what="stt.wav 추출")

    n_slides = 0
    if slides_arg:
        sd = Path(slides_arg).expanduser().resolve()
        if not sd.is_dir():
            die(f"슬라이드 폴더가 없습니다: {sd}")
        P.src_slides.mkdir(parents=True, exist_ok=True)
        imgs = sorted(p for p in sd.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not imgs:
            die(f"{sd} 안에 이미지가 없습니다")
        # 파일명 순서 = 슬라이드 순서. 번호를 다시 매겨 뒷단이 순서를 의심하지 않게 한다.
        for i, p in enumerate(imgs, 1):
            shutil.copy2(p, P.src_slides / f"{i:03d}{p.suffix.lower()}")
        n_slides = len(imgs)
        print(f"슬라이드 {n_slides}장 복사 — 00/slides/")
    else:
        print("슬라이드가 없습니다 — s5(씬 매핑)는 건너뛰게 됩니다")

    save_json(P.meta, {"source": src.name, "duration": round(dur, 2), "slides": n_slides})
    print(f"완료 — {P.media}")
    print(f"다음: python scripts/s2_transcribe.py --lang ru")


if __name__ == "__main__":
    main()
