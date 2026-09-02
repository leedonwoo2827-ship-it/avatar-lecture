# -*- coding: utf-8 -*-
"""P4 — 아바타 영상. 지금은 **자리만** 만든다.

    build/<task>/voice/sceneNN.wav  →  build/<task>/avatar/sceneNN.mp4

perso 가 붙기 전까지 아바타 대신 **사람 모양 임시 아바타**를 넣는다. 얼굴을 그리려는
게 아니라 "사람이 여기까지 덮는다"를 보려는 것이다 — 자막을 가리는지, 슬라이드의
글자를 밟는지는 실루엣만 있어도 판단이 된다. 크레딧 0.

    stub    임시 아바타. 목소리 길이만큼. **기본값.**
    perso   진짜 아바타. API 키를 넣은 뒤에 쓴다.

★ 다음 단계(p5_compose.py)는 이 mp4 가 임시 아바타인지 진짜인지 **모른다.** 같은
  자리에 같은 이름으로 놓이기만 하면 된다. perso 를 붙일 때 이 파일 하나만
  갈아 끼우면 나머지는 그대로 돈다 — 그러라고 단계를 갈라 뒀다.

    python scripts/p4_avatar.py --task lecture01
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

# 임시 아바타 규격 — **선 사람 하나**의 비율이다(9:16 이 아니다). 레퍼런스 영상의
# 발표자를 재 보면 폭:높이가 대략 0.35 로, 9:16(0.5625)보다 한참 홀쭉하다.
# 임시 아바타가 실제보다 뚱뚱하면 배치를 잘못 잡게 되므로 여기서 맞춰 둔다.
AV_W, AV_H, FPS = 380, 1080, 25
FG = "0x23262B"      # 실루엣 색 — **검은 정장**. 진짜 아바타가 정장 차림이라
                     # 임시 아바타도 같은 톤이어야 미리보기가 실물과 안 어긋난다.

# ★ **배경을 투명(알파)으로 낸다.** 참고 영상의 발표자처럼 사람만 오려 얹혀야
#   하는데 배경을 칠하면 슬라이드 위에 네이비 사각형이 앉는다. mp4 는 알파를
#   못 담으므로 ProRes 4444(.mov)로 낸다 — 컷아웃을 넘길 때 흔히 쓰는 형식이라,
#   perso 결과가 알파로 오면 그대로 이 자리에 들어간다.
EXT = ".mov"


def stub(ff: str, sec: float, out: Path) -> None:
    """사람 모양 임시 아바타 — 배경은 투명하고 실루엣만 남는다.

    머리·목·어깨·몸통을 상자 몇 개로 겹쳐 사람으로 읽히게 한다. 얼굴을 그리려는
    게 아니라 **어디까지 덮는지**를 보려는 것이라 이 정도면 충분하다. 몸통은
    아래를 자르지 않는다 — 발표자 컷아웃은 화면 아래 끝에서 잘린다.
    """
    head_w, head_h = 118, 142
    neck_w, neck_h = 46, 30
    sh_w, sh_h = 268, 74      # 어깨 — 정장 재킷이라 각지게
    torso_w = 232
    top = 74

    # ★ drawbox 는 **알파 채널을 안 쓴다.** 투명한 rgba 화면에 drawbox 로 그리면
    #   색만 얹히고 알파는 0 그대로라 결과가 통째로 투명해진다(2026-09-02 실측).
    #   그래서 모양을 흑백 **마스크**로 따로 그리고 alphamerge 로 붙인다 —
    #   색 판(0번)과 마스크(1번)를 겹치면 실루엣만 불투명해진다.
    boxes = ",".join([
        f"drawbox=x=(iw-{head_w})/2:y={top}:w={head_w}:h={head_h}:color=white:t=fill",
        f"drawbox=x=(iw-{neck_w})/2:y={top + head_h}:w={neck_w}:h={neck_h}:color=white:t=fill",
        f"drawbox=x=(iw-{sh_w})/2:y={top + head_h + 28}:w={sh_w}:h={sh_h}:color=white:t=fill",
        f"drawbox=x=(iw-{torso_w})/2:y={top + head_h + 28}:w={torso_w}:h=ih:color=white:t=fill",
    ])
    fc = (f"[0:v]format=rgba[base];"
          f"[1:v]{boxes},format=gray[mask];"
          f"[base][mask]alphamerge[v]")

    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c={FG}:s={AV_W}x{AV_H}:r={FPS}",
         "-f", "lavfi", "-i", f"color=c=black:s={AV_W}x{AV_H}:r={FPS}",
         "-t", f"{sec:.3f}", "-filter_complex", fc, "-map", "[v]",
         "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
         str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.is_file():
        die(f"{out.name} 임시 아바타 만들기 실패: {(r.stderr or '')[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="씬별 아바타 (지금은 임시 아바타)")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--engine", default="stub", choices=["stub", "perso"])
    a = ap.parse_args()

    task = BUILD / a.task
    meta = load_json(need(task / "scenes.json", "p1_scenes.py 를 먼저 돌리세요"))

    if a.engine == "perso":
        die("perso 엔진은 아직 붙지 않았습니다 — API 키를 발급한 뒤 "
            "perso/client.py 의 아바타 호출을 채우세요. "
            "그때까지는 --engine stub 으로 자리만 잡습니다.")

    todo = [r for r in meta["scenes"] if r.get("voice")]
    if not todo:
        die("목소리가 아직 없습니다 — p2_voice.py 를 먼저 돌리세요")

    out_dir = task / "avatar"
    out_dir.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()

    print(f"{len(todo)}씬 — 엔진 {a.engine} ({AV_W}x{AV_H}, 9:16, 배경 투명)")
    for r in todo:
        no = int(r["no"])
        out = out_dir / f"scene{no:02d}{EXT}"
        sec = float(r["voice_dur"])
        with Ticker(f"{no:02d} 아바타"):
            stub(ff, sec, out)
        r["avatar"] = out.name
        r["avatar_dur"] = round(probe_duration(out), 3)
        r["avatar_engine"] = a.engine
        print(f"  {no:02d}  {mmss(r['avatar_dur']):>7}  {out.name}")

    save_json(task / "scenes.json", meta)
    print(f"\n배경이 투명한 임시 아바타입니다 — 사람이 어디까지 덮는지만 봅니다. "
          f"진짜 아바타는 perso 를 붙인 뒤 같은 자리에 놓입니다.")
    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
