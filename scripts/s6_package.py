# -*- coding: utf-8 -*-
"""S6 — perso에 그대로 올릴 조각 패키지를 만든다. 이 파이프라인의 산출물이다.

    output/NN/01/audio.m4a + 03/subs.<lang>.srt + 04/chunks.json (+ 05/scenes.json)
        → output/NN/06/perso/chunk01/
             audio.m4a      아바타 립싱크 소스 — 자막 없는 클린본
             subs.<lang>.srt  그 조각만, **0초부터 다시 매긴** 타임코드
             scenes.csv     그 조각에 걸리는 씬만
             slides/        그 조각에 쓰이는 슬라이드 이미지만
             지시서.md       외주업체가 읽을 작업 지시 — 자동 생성

**자막을 영상에 굽지 않는다.** perso에는 클린 오디오와 SRT를 따로 올린다. 자막을
이미지로 만들어 얹던 수작업이 이 단계에서 통째로 사라진다 — 검수용 번인본이
필요하면 s7이 ffmpeg 한 번으로 굽는다.

지시서를 왜 자동으로 만드는가: 120강 × 2조각 = **240장**이다. 손으로 못 쓴다.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (PERSO_LIMIT_SEC, VIDEO_EXTS, current_workspace, die, ffmpeg, load_json,
                            mmss, need, paths, run, srt_path)
from scripts.cues import Cue, cues_from_json, parse_srt, to_srt

INSTRUCTION = """# {lecture} — 조각 {no:02d} / {total_chunks} 작업 지시

## 이 조각이 무엇인가
원본 강의 **{lecture}** 중 **{start} ~ {end}** 구간입니다 (길이 **{length}**).
perso가 한 번에 처리할 수 있는 길이(30분)를 넘지 않도록 잘라 둔 것입니다.
{sibling}

## 넘긴 파일
| 파일 | 무엇인가 | 어떻게 쓰나 |
|---|---|---|
| `video.mp4` | 이 구간의 화면. **소리가 없습니다(무음)** | 화면 소스. 소리를 뺀 이유는 아바타 음성이 `audio.m4a`에서 새로 만들어지기 때문입니다 — 영상에 원본 소리가 남아 있으면 두 소리가 겹칩니다 |
| `audio.m4a` | 이 구간의 강의 음성 (자막·효과음 없는 클린본) | **아바타 립싱크 소스**로 perso에 올립니다 |
| `subs.{lang}.srt` | 이 구간의 자막. 타임코드는 **이 조각의 0초 기준**입니다 | 자막 트랙으로 올리거나, 마지막에 얹습니다 |
| `scenes.csv` | 화면이 바뀌는 시각과 그때 떠 있는 슬라이드 | 슬라이드 전환 타이밍을 맞출 때 봅니다 |
| `slides/` | 이 구간에 쓰이는 슬라이드 이미지 | 슬라이드를 낱장으로 다시 쓸 때 |

## 지켜 주실 것
1. **오디오를 다시 인코딩하지 마세요.** `audio.m4a`를 그대로 올립니다. 다시 압축하면
   립싱크가 미세하게 밀립니다.
2. **자막을 영상에 굽지 마세요.** 자막은 별도 트랙으로 유지합니다. 검수 단계에서
   문구가 바뀌는 일이 잦은데, 구워 두면 그때마다 전부 다시 만들어야 합니다.
3. **조각의 앞뒤를 잘라내지 마세요.** 이미 말과 말 사이 조용한 자리에서 끊어 두었습니다.
   여기서 더 다듬으면 나중에 조각을 다시 이어 붙일 때 어긋납니다.
4. 자막 한 줄이 화면 폭을 넘으면 **문구를 줄여 주시고, 두 줄로 접지 마세요.**
   두 줄 자막은 아바타 화면 아래를 가립니다.

## 검수 기준
- [ ] 아바타 입모양이 소리와 맞는가 (특히 조각 시작 5초, 끝 5초)
- [ ] 소리가 **한 겹만** 들리는가 (video.mp4 의 무음을 살려 두었는지)
- [ ] 자막이 소리보다 먼저 뜨거나 늦게 사라지지 않는가
- [ ] `scenes.csv`의 시각에 맞춰 슬라이드가 넘어가는가
- [ ] 조각 전체 길이가 **{length}** 그대로인가 (길이가 변하면 이어 붙일 때 어긋납니다)

## 문의
이 지시서는 파이프라인이 자동 생성했습니다. 산출물이 이상하면 파일을 지우지 마시고
그대로 두신 채 연락 주세요 — 무엇이 어긋났는지 그 파일로 되짚습니다.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="perso 투입 패키지 만들기")
    ap.add_argument("--sub-lang", default="ru", help="담을 자막 언어 (기본 ru, 번역본이 있으면 uz)")
    ap.add_argument("--no-video", action="store_true",
                    help="조각별 영상(video.mp4)을 만들지 않는다. perso가 영상을 "
                         "안 받는 것으로 확인되면 이걸 주면 시간이 크게 줄어든다")
    a = ap.parse_args()
    lang = a.sub_lang

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")
    need(P.audio, "s1_ingest.py를 먼저 돌리세요")
    need(P.chunks, "s4_split.py를 먼저 돌리세요")

    srt = srt_path(P, lang)
    if not srt.is_file():
        die(f"{srt} 가 없습니다 — s3_cue.py --lang {lang} 를 돌리거나, "
            f"번역한 자막을 그 이름으로 저장하세요")
    cues = parse_srt(srt.read_text(encoding="utf-8-sig"))
    if not cues:
        die(f"{srt.name} 에서 큐를 읽지 못했습니다")

    chunks = load_json(P.chunks)
    scenes = load_json(P.scenes) if P.scenes.is_file() else []

    video = None
    if not a.no_video:
        vids = [q for q in P.src.iterdir()
                if q.is_file() and q.suffix.lower() in VIDEO_EXTS] if P.src.is_dir() else []
        if not vids:
            die(f"{P.src} 에 원본 영상이 없습니다 — s1_ingest.py를 먼저 돌리거나 "
                f"--no-video 를 주세요")
        video = vids[0]
        print("영상도 함께 자릅니다 (무음) — 다시 인코딩하므로 조각마다 몇 분 걸립니다")
    lecture = P.ws.name.split("-", 1)[-1]
    ff = ffmpeg()

    print(f"{len(chunks)}조각 만드는 중… (자막 {lang} · 큐 {len(cues)}개)")
    for r in chunks:
        no, s, e = int(r["no"]), float(r["start_sec"]), float(r["end_sec"])
        length = e - s
        if length > PERSO_LIMIT_SEC:
            die(f"chunk{no:02d}가 perso 한계({mmss(PERSO_LIMIT_SEC)})를 넘습니다 "
                f"— s4_split.py --targets 로 다시 자르세요")

        d = P.perso / f"chunk{no:02d}"
        (d / "slides").mkdir(parents=True, exist_ok=True)

        # 오디오 — `-ss`를 `-i` 뒤에 둔다. 앞에 두면 가장 가까운 키프레임으로
        # 반올림돼 조각 경계가 흔들린다(260818 s4a에서 실측된 함정).
        run([ff, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(P.audio), "-ss", f"{s:.3f}", "-to", f"{e:.3f}",
             "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
             str(d / "audio.m4a")], what=f"chunk{no:02d} 오디오 자르기")

        # 영상 — 화면(슬라이드)만 담은 **무음** 영상.
        # ★ 소리를 빼는 이유: 아바타 음성은 audio.m4a 에서 새로 만들어진다. 영상에
        #   원본 소리가 남아 있으면 두 소리가 겹쳐 이중으로 들린다. 그래서 `-an`.
        # ★ 스트림 복사(-c copy)로는 안 된다. 키프레임 간격이 10초라 컷이 최대
        #   10초까지 밀린다. 조각 경계가 밀리면 다시 이어 붙일 때 어긋나므로
        #   프레임 단위로 정확하게 다시 인코딩한다.
        if video is not None:
            run([ff, "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(video), "-ss", f"{s:.3f}", "-to", f"{e:.3f}",
                 "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 str(d / "video.mp4")], what=f"chunk{no:02d} 영상 자르기")

        # 자막 — 이 구간에 걸치는 큐만, 0초 기준으로 다시 매긴다
        mine = [c for c in cues if c.end > s and c.start < e]
        clipped = [Cue(text=c.text, start=max(c.start, s), end=min(c.end, e)) for c in mine]
        (d / f"subs.{lang}.srt").write_text(to_srt(clipped, offset=s), encoding="utf-8")

        # 씬 표 + 슬라이드
        my_scenes = [sc for sc in scenes if sc["end_sec"] > s and sc["start_sec"] < e]
        with (d / "scenes.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["씬", "이 조각 안에서 시작", "끝", "슬라이드"])
            for sc in my_scenes:
                w.writerow([sc["no"], mmss(max(sc["start_sec"], s) - s),
                            mmss(min(sc["end_sec"], e) - s), sc.get("slide", "")])
        n_slides = 0
        for sc in my_scenes:
            name = sc.get("slide") or ""
            srcp = P.src_slides / name
            if name and srcp.is_file():
                shutil.copy2(srcp, d / "slides" / name)
                n_slides += 1

        others = [f"chunk{int(x['no']):02d}" for x in chunks if int(x["no"]) != no]
        sibling = ("이 강의는 조각이 하나입니다." if not others else
                   f"같은 강의의 다른 조각({', '.join(others)})과 이어지는 내용이니 "
                   f"톤·아바타·자막 서식을 똑같이 맞춰 주세요.")
        (d / "지시서.md").write_text(INSTRUCTION.format(
            lecture=lecture, no=no, total_chunks=len(chunks),
            start=mmss(s), end=mmss(e), length=mmss(length),
            lang=lang, sibling=sibling), encoding="utf-8")

        print(f"  chunk{no:02d}  {mmss(length)} · 자막 {len(clipped)}개 · "
              f"씬 {len(my_scenes)}개 · 슬라이드 {n_slides}장"
              + ("  + video.mp4(무음)" if video is not None else ""))

    print(f"완료 — {P.perso}")
    print("이 폴더를 그대로 perso에 올리고, 외주업체에는 폴더째 넘기면 됩니다.")
    print("검수용 자막 번인본이 필요하면: python scripts/s7_preview.py")


if __name__ == "__main__":
    main()
