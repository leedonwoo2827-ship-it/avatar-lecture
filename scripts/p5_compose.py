# -*- coding: utf-8 -*-
"""P5 — 슬라이드 + 아바타 + 자막을 한 장면으로 합친다.

    slides/NNN.png + avatar/sceneNN.mp4 + voice/sceneNN.wav + aligned/sceneNN.<lang>.srt
        → build/<task>/preview/sceneNN.mp4

배치가 두 가지다. **이 슬라이드들은 오른쪽 세로로 라벨을 세 개씩 달고 있어서**
아바타를 그 위에 얹으면 글자가 통째로 사라진다(001.png 의 "Разделы карты и
навигация" 따위). 그래서 덮지 않는 쪽을 기본으로 둔다.

    side      슬라이드를 왼쪽으로 줄이고 오른쪽에 아바타 칸을 따로 낸다.
              **아무것도 가리지 않는다.** 기본값.
    overlay   슬라이드를 꽉 채우고 아바타를 그 위에 얹는다. 시연 영상과 같은
              모양이지만 오른쪽 라벨을 덮는다. 라벨이 없는 슬라이드면 이쪽이 낫다.

자막은 두 배치 모두 **아래 띠**에 깔린다. 글자 뒤에만 옅은 검은 판을 깔아 그림
위에서도 읽히게 한다 — 슬라이드 아래쪽이 실제로는 비어 있지 않다(바닥·인물 다리).

★ SRT 를 그대로 subtitles 필터에 주면 libass 가 **PlayResY=288** 로 재서 글자가
  네 배로 커진다. 그래서 여기서 ASS 로 직접 옮기며 PlayRes 를 1920x1080 으로
  박는다 — 그러면 아래 숫자들이 전부 **진짜 픽셀**이 된다.

★ ffmpeg 의 subtitles 필터는 윈도 경로의 콜론(C:)을 인자 구분자로 오해한다.
  그래서 ASS 가 있는 폴더로 들어가 **파일 이름만** 넘긴다 (s7_preview.py 와 같다).

    python scripts/p5_compose.py --task lecture01
    python scripts/p5_compose.py --task lecture01 --layout overlay
    python scripts/p5_compose.py --task lecture01 --scenes 1 --limit 8   # 빨리 확인
    python scripts/p5_compose.py --task lecture01 --join                 # 8씬 한 편으로
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import ROOT, die, ffmpeg, load_json, mmss, need, save_json
from scripts.cues import parse_srt
from scripts.ticker import Ticker

BUILD = ROOT / "build"

W, H = 1920, 1080
BAND = 200                # 자막 띠 높이(px) — 두 배치 공통
BG = "0xF6F1E8"           # 슬라이드 바탕과 같은 아이보리 (이미지프롬프트 지정색)
AV_ASPECT = 380 / 1080    # p4_avatar.py 가 만드는 임시 아바타 비율 (선 사람)

# 자막 — PlayRes 를 1920x1080 으로 박으므로 아래는 전부 진짜 픽셀이다.
FONT = "Arial"
FONT_SIZE = 46
OUTLINE = 3


def ass_time(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int(t // 60) % 60
    s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def srt_to_ass(srt: Path, dst: Path, *, margin_v: int,
               center: int | None = None, dark: bool = False) -> int:
    """SRT → ASS. PlayRes 를 박아 글자 크기를 픽셀로 고정한다.

    BorderStyle=3 은 **글자 뒤에만** 판을 깐다 — 띠 전체를 덮지 않아 슬라이드
    그림이 최대한 남는다. 바탕이 밝아 흰 글자만으로는 안 읽히므로 판이 필요하다.
    색은 &HAABBGGRR — 앞 두 자리가 투명도다(00 불투명, FF 완전투명).
    """
    cues = parse_srt(srt.read_text(encoding="utf-8-sig"))
    # Alignment=2 는 MarginL 과 (PlayResX - MarginR) 사이의 **가운데**에 글자를 놓는다.
    # 그래서 원하는 중심 x 가 있으면 MarginR 을 거꾸로 풀어 준다.
    ml = 100
    mr = 140 if center is None else max(60, W - 2 * int(center) + ml)
    if dark:
        # 밝은 띠 위 — 어두운 글자, 판도 테두리도 없다. 띠는 배치가 이미 그렸다.
        colors, border = "&H001F2328,&H000000FF,&H00FFFFFF,&H00FFFFFF", "1,0,0"
    else:
        # 그림 위 — 흰 글자에 글자 뒤에만 옅은 검은 판(BorderStyle=3)
        colors, border = ("&H00FFFFFF,&H000000FF,&H00000000,&H70000000",
                          "3," + str(OUTLINE) + ",0")
    style = (
        "Style: Sub," + FONT + "," + str(FONT_SIZE) + "," + colors + ","
        "-1,0,0,0,100,100,0,0," + border + ",2,"
        + str(ml) + "," + str(mr) + "," + str(margin_v) + ",1"
    )
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: " + str(W),
        "PlayResY: " + str(H),
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body = []
    for c in cues:
        # ASS 는 중괄호를 명령으로 읽는다. 우리 큐는 한 줄이라 줄바꿈은 없다.
        text = re.sub(r"\s+", " ", c.text).replace("{", "(").replace("}", ")")
        body.append("Dialogue: 0," + ass_time(c.start) + "," + ass_time(c.end)
                    + ",Sub,,0,0,0,," + text)
    dst.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    return len(cues)


def slide_bg(ff: str, slide: Path) -> str:
    """슬라이드 **네 귀퉁이**를 찍어 바탕색을 알아낸다.

    발표자 칸을 고정색으로 칠하면 덱이 바뀔 때마다 경계가 튄다. 슬라이드가 스스로
    바탕색을 말해 주므로 그걸 그대로 쓴다 — 아이보리 덱이면 아이보리, 남색 덱이면
    남색 칸이 되어 한 장처럼 이어진다.

    귀퉁이 하나가 그림에 물릴 수 있으니 **중앙값**을 쓴다. 평균을 쓰면 물린
    귀퉁이 하나가 색을 통째로 끌고 간다.
    """
    vals: list[tuple[int, int, int]] = []
    for x, y in (("18", "18"), ("iw-38", "18"), ("18", "ih-38"), ("iw-38", "ih-38")):
        r = subprocess.run(
            [ff, "-v", "error", "-i", str(slide),
             "-vf", f"crop=20:20:{x}:{y},scale=1:1", "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True)
        if len(r.stdout) >= 3:
            vals.append((r.stdout[0], r.stdout[1], r.stdout[2]))
    if not vals:
        return BG
    med = tuple(sorted(v[i] for v in vals)[len(vals) // 2] for i in range(3))
    return "0x%02X%02X%02X" % med


def _chain(slide_w: int, slide_h: int, sx: int, sy: int,
           av_w: int, av_h: int, ax: int, ay: int) -> str:
    """슬라이드를 깔고 그 위에 아바타를 얹는 필터 사슬.

    아바타가 알파(투명 배경)면 overlay 가 알아서 사람만 오려 얹는다. 알파가 없는
    영상이 와도 같은 자리에 그대로 들어간다 — 사각형으로 보일 뿐 깨지지 않는다.
    """
    return (
        "[0:v]scale=" + str(slide_w) + ":" + str(slide_h)
        + ":force_original_aspect_ratio=decrease,"
        + "pad=" + str(W) + ":" + str(H) + ":" + str(sx) + ":" + str(sy)
        + ":color=" + BG + ",setsar=1[bg];"
        + "[1:v]scale=" + str(av_w) + ":" + str(av_h) + "[av];"
        + "[bg][av]overlay=x=" + str(ax) + ":y=" + str(ay)
        + ":format=auto:shortest=0[ov]"
    )


def layout_stage(av_h_ratio: float) -> tuple[str, dict]:
    """참고 영상과 같은 구성 — 슬라이드를 크게 두고 컷아웃이 오른쪽 아래를 겹친다.

    슬라이드가 1588x894 로 거의 화면을 채우고, 발표자가 그 **오른쪽 아래**를 밟고
    화면 바닥에 선다. 겹치는 폭(약 200px)은 이 덱의 오른쪽 라벨이 끝나는 자리
    (슬라이드 폭의 85% 언저리)보다 바깥이라 글자를 먹지 않는다.
    """
    band = 170
    sx, sy = 16, 16
    slide_h = (H - band - sy * 2) // 2 * 2
    slide_w = int(round(slide_h * 16 / 9)) // 2 * 2

    av_h = int(round(H * av_h_ratio)) // 2 * 2
    av_w = int(round(av_h * AV_ASPECT)) // 2 * 2
    ax = W - av_w - 34
    ay = H - av_h                      # 발끝이 화면 바닥에 닿는다

    return _chain(slide_w, slide_h, sx, sy, av_w, av_h, ax, ay), {
        "slide": f"{slide_w}x{slide_h}@{sx},{sy}",
        "avatar": f"{av_w}x{av_h}@{ax},{ay}", "band": band,
        # 자막은 아바타가 안 덮는 왼쪽 구역의 가운데에 온다
        "sub_center": (sx + ax) // 2,
    }


def layout_split(av_h_ratio: float) -> tuple[str, dict]:
    """슬라이드 왼쪽 크게 · 아바타 오른쪽 아래 · 자막은 슬라이드 아래.

    **기본값.** 이 덱은 오른쪽 세로로 라벨을 세 개씩 달고 있어 아바타를 그 위에
    얹으면 글자를 먹는다. 그래서 아바타에게 오른쪽 칸을 따로 주고 슬라이드는
    그 왼쪽을 다 쓴다 — 아무것도 가리지 않는다.

    발끝은 화면 바닥에 닿는다. 조금이라도 띄우면 사람이 공중에 뜬 것처럼 보인다.
    """
    right_gap = 50
    av_h = int(round(H * av_h_ratio)) // 2 * 2
    av_w = int(round(av_h * AV_ASPECT)) // 2 * 2
    ax = W - av_w - right_gap
    ay = H - av_h                       # 발끝이 화면 바닥에 닿는다

    # 슬라이드는 아바타 칸 **왼쪽**을 다 쓴다. 아래에는 자막 띠를 남긴다.
    left_w = ax - 20
    top = 80
    slide_w = (left_w - 40) // 2 * 2
    slide_h = int(round(slide_w * 9 / 16)) // 2 * 2
    max_h = (H - top - 190) // 2 * 2
    if slide_h > max_h:
        slide_h = max_h
        slide_w = int(round(slide_h * 16 / 9)) // 2 * 2
    sx = (left_w - slide_w) // 2
    sy = top
    band = H - (sy + slide_h)

    return _chain(slide_w, slide_h, sx, sy, av_w, av_h, ax, ay), {
        "slide": f"{slide_w}x{slide_h}@{sx},{sy}",
        "avatar": f"{av_w}x{av_h}@{ax},{ay}", "band": band,
        "sub_center": sx + slide_w // 2,
    }


def layout_full(av_h_ratio: float) -> tuple[str, dict]:
    """**A안 — 꽉 채움.** 슬라이드가 화면 전체를 덮고 발표자가 그 위에 선다.

        ┌──────────────────────────────────────┐
        │   슬라이드 1920x1080 (여백 없음)         │
        │                            발표자      │
        ├──────────────────────────────────────┤
        │   자막 — 화면 폭 전체, 밝은 띠            │
        └──────────────────────────────────────┘

    여백이 하나도 없다. 대신 발표자가 슬라이드 오른쪽을 **가린다** — 지금 덱은
    거기에 라벨이 있어 글자가 먹히지만, 슬라이드를 오른쪽 20% 비워 다시 그리면
    문제가 없어진다. 자막 처리는 B안과 똑같다(밝은 띠 · 어두운 글자 · 폭 전체).
    """
    band_h = 124
    av_h = int(round(H * av_h_ratio)) // 2 * 2
    av_w = int(round(av_h * AV_ASPECT)) // 2 * 2
    ax = W - av_w - 60
    ay = H - av_h                        # 발끝이 화면 아래 끝에서 잘린다

    def box(x, y, w, h, color):
        return f"drawbox=x={int(x)}:y={int(y)}:w={int(w)}:h={int(h)}:color={color}:t=fill"

    band = (box(0, H - band_h, W, band_h, "0xEDEEF0@0.88") + ","
            + box(0, H - band_h, W, 1, "0xFFFFFF@0.5"))

    chain = (
        "[0:v]scale=" + str(W) + ":" + str(H)
        + ":force_original_aspect_ratio=increase,crop=" + str(W) + ":" + str(H)
        + ",setsar=1[bg];"
        + "[1:v]scale=" + str(av_w) + ":" + str(av_h) + "[av];"
        + "[bg][av]overlay=x=" + str(ax) + ":y=" + str(ay)
        + ":format=auto:shortest=0," + band + "[ov]"
    )
    return chain, {"slide": f"{W}x{H} 꽉 채움", "avatar": f"{av_w}x{av_h}@{ax},{ay}",
                   "band": band_h, "sub_center": W // 2,
                   "sub_dark": True, "sub_margin_v": 34}


def layout_signage(av_h_ratio: float) -> tuple[str, dict]:
    """**슬라이드를 디스플레이 안에 넣고**, 발표자는 그 옆 바닥에 세운다.

    LG 시그니지 사진과 같은 구성이다 — 벽에 걸린 화면이 내용을 띄우고 사람이 그
    옆에 선다. 베젤은 **슬라이드** 쪽에 씌운다(아바타에 씌우면 사람이 상자에
    갇힌다). 아바타는 프레임 없이 컷아웃으로 두고 발끝을 화면 아래 끝에 붙인다.

    테두리는 상자 몇 겹으로 만든다. ffmpeg 의 drawbox 는 둥근 모서리도 흐림도
    못 하므로 **알파가 낮은 상자를 여러 겹 겹쳐** 부드러운 그림자를 흉내낸다:

        그림자 6겹 → 베젤 몸체 → 바깥 모서리 빛 → 화면 둘레 선 → (슬라이드) → 윗변 반사 → 아래턱 LED

    아래턱(chin)을 옆·위 베젤보다 두껍게 둔다 — 실제 디스플레이가 그렇고, 그 차이가
    "기기"로 읽히게 만드는 가장 큰 단서다.
    """
    bez, chin = 14, 34
    band = 170
    right_gap = 60

    # 1) 발표자 — 오른쪽, 프레임 없이 바닥에 선다
    av_h = int(round(H * av_h_ratio)) // 2 * 2
    av_w = int(round(av_h * AV_ASPECT)) // 2 * 2
    ax = W - av_w - right_gap
    ay = H - av_h

    # 2) 디스플레이 — 발표자 왼쪽을 다 쓴다
    px = 30
    panel_w = (ax - 40 - px) // 2 * 2
    slide_w = (panel_w - bez * 2) // 2 * 2
    slide_h = int(round(slide_w * 9 / 16)) // 2 * 2
    panel_h = slide_h + bez + chin
    max_bottom = H - band
    if py_over := max(0, (panel_h + 60) - max_bottom):
        slide_h = (slide_h - py_over) // 2 * 2
        slide_w = int(round(slide_h * 16 / 9)) // 2 * 2
        panel_w = slide_w + bez * 2
        panel_h = slide_h + bez + chin
    py = max(24, max_bottom - panel_h)
    sx, sy = px + bez, py + bez

    def box(x, y, w, h, color, t="fill"):
        return (f"drawbox=x={int(x)}:y={int(y)}:w={int(w)}:h={int(h)}"
                f":color={color}:t={t}")

    pre, post = [], []
    # 그림자 — 아래로 10px 흘리고 바깥으로 번지게 여섯 겹
    for i in range(6, 0, -1):
        g = i * 5
        pre.append(box(px - g, py - g + 10, panel_w + 2 * g, panel_h + 2 * g,
                       "0x0A1018@0.035"))
    pre.append(box(px, py, panel_w, panel_h, "0x141B23@1"))          # 베젤 몸체
    pre.append(box(px, py, panel_w, panel_h, "0x4A5A6B@0.55", t="2"))  # 바깥 모서리 빛
    pre.append(box(sx - 1, sy - 1, slide_w + 2, slide_h + 2, "0x000000@0.85", t="1"))

    # 슬라이드를 얹은 **뒤에** 그리는 것들 — 유리 반사와 아래턱 LED
    post.append(box(sx, sy, slide_w, 3, "0xFFFFFF@0.12"))
    post.append(box(px + panel_w // 2 - 4, py + panel_h - chin // 2 - 3, 8, 6,
                    "0x6FD3A0@0.85"))
    # 발끝 접지 그림자 — 사람이 바닥에 닿아 보이게 아주 옅게 세 겹
    for i, a in enumerate((0.05, 0.07, 0.10)):
        h = 10 - i * 3
        post.append(box(ax - 18 + i * 6, H - h, av_w + 36 - i * 12, h,
                        f"0x0A1018@{a}"))

    chain = (
        # 바탕 + 베젤 → 그 안에 슬라이드를 얹는다
        "color=c=" + BG + ":s=" + str(W) + "x" + str(H) + ":r=25,"
        + ",".join(pre) + "[panel];"
        + "[0:v]scale=" + str(slide_w) + ":" + str(slide_h)
        + ":force_original_aspect_ratio=decrease,setsar=1[slide];"
        + "[panel][slide]overlay=x=" + str(sx) + ":y=" + str(sy) + ":shortest=1[withslide];"
        + "[withslide]" + ",".join(post) + "[bg];"
        + "[1:v]scale=" + str(av_w) + ":" + str(av_h) + "[av];"
        + "[bg][av]overlay=x=" + str(ax) + ":y=" + str(ay)
        + ":format=auto:shortest=0[ov]"
    )
    return chain, {"slide": f"{slide_w}x{slide_h}@{sx},{sy} (화면 안)",
                   "avatar": f"{av_w}x{av_h}@{ax},{ay}",
                   "panel": f"{panel_w}x{panel_h}@{px},{py}", "band": band,
                   "sub_center": px + panel_w // 2}


def layout_studio(av_h_ratio: float, fit: str = "contain",
                  col_bg: str = "pad", align: str = "center") -> tuple[str, dict]:
    """레퍼런스 영상과 같은 구성. **기본값.**

        ┌───────────────────────────────┬──────┐
        │        (위 여백)               │      │
        │   슬라이드 (왼쪽 칸)            │ 발표자 │
        │        (아래 여백)             │  칸  │
        ├───────────────────────────────┴──────┤
        │   자막 — 화면 폭 전체, 밝은 띠에 어두운 글자  │
        └──────────────────────────────────────┘

    ★ **위·아래 여백과 발표자 칸은 반드시 같은 색이어야 한다.** 색이 조금이라도
      다르면 그 경계가 세로줄로 보인다(2026-09-02 실측: 여백은 고정 아이보리
      #F6F1E8, 칸은 슬라이드에서 찍은 #FCF8F1 이라 미묘하게 갈렸다).
      그래서 여기서는 색을 **하나만 정해** 세 군데에 같이 쓴다.

        pad     고정 아이보리(#F6F1E8). **기본값.**
        auto    슬라이드 귀퉁이에서 찍은 색 — 덱 바탕이 아이보리가 아닐 때.
        dark    검정에 가까운 칸 — 밝은 옷 발표자일 때.

    슬라이드를 왼쪽 칸에 넣는 방법도 둘이다.

        contain  안 자르고 맞춘다 — 위아래에 여백이 생긴다. **기본값.**
        cover    잘라서 꽉 채운다 — 좌우가 잘린다.

    contain 일 때 남는 세로 여백을 어디에 둘지도 고른다.

        center   위아래로 반씩 나눈다. 슬라이드가 자막 띠를 조금 파고든다.
        band     **슬라이드 아래를 자막 띠 윗선에 붙인다.** 남는 여백은 전부 위로.
                 `panel` 스타일이 쓰는 값이다.

    16:9 슬라이드를 13:9 칸에 꽉 채우려면 좌우를 19% 잘라야 하는데, 이 덱은
    가장자리에 라벨을 둔다. 그래서 기본은 안 자르는 쪽이다.
    """
    col_w = 360                          # 오른쪽 발표자 칸
    band_h = 124                         # 자막 띠 — 맨 아래, 폭은 화면 전체
    slide_w = W - col_w

    # ★ 여백과 칸은 **반드시 같은 색**이다. 다르면 그 경계가 세로줄로 보인다
    #   (2026-09-02 실측: 여백 #F6F1E8 · 칸 #FCF8F1 이라 미묘하게 갈렸다).
    if col_bg == "dark":
        fill, sheen = "0x14161A", "0x1E2229@0.55"
    elif col_bg.startswith("0x"):
        fill, sheen = col_bg, ""          # auto 로 슬라이드에서 찍어 온 색
    else:
        fill, sheen = BG, ""              # pad · ivory — 고정 아이보리

    av_h = int(round(H * av_h_ratio)) // 2 * 2
    av_w = int(round(av_h * AV_ASPECT)) // 2 * 2
    ax = slide_w + (col_w - av_w) // 2
    ay = H - av_h                        # 발끝이 화면 아래 끝에서 잘린다

    def box(x, y, w, h, color, t="fill"):
        return (f"drawbox=x={int(x)}:y={int(y)}:w={int(w)}:h={int(h)}"
                f":color={color}:t={t}")

    col = box(slide_w, 0, col_w, H, fill + "@1")
    if sheen:
        col += "," + box(slide_w, 0, col_w, H // 2, sheen)

    # 자막 띠는 **아바타 위에** 온다 — 사람 앞을 지나가야 글자가 안 잘린다
    band = ",".join([
        box(0, H - band_h, W, band_h, "0xEDEEF0@0.88"),
        box(0, H - band_h, W, 1, "0xFFFFFF@0.5"),
    ])

    if fit == "cover":
        slide_fit = ("scale=" + str(slide_w) + ":" + str(H)
                     + ":force_original_aspect_ratio=increase,"
                     + "crop=" + str(slide_w) + ":" + str(H))
    else:
        # ★ 여백 색이 곧 칸 색이다 — 같은 fill 을 쓴다
        # ★ band — 슬라이드 **아래를 자막 띠 윗선에 붙인다.** 남는 여백은 전부
        #   위로 간다. center 로 두면 슬라이드가 띠를 23px 파고들고, 위로 바짝
        #   붙이면 반대로 78px 이 뜬다(2026-09-02 실측). 그 사이가 여기다.
        #
        #   슬라이드 높이는 ffmpeg 이 종횡비를 보고 정하므로 파이썬에는 없다.
        #   그래서 **띠를 뺀 높이 안에서 아래로 붙이고**(oh-ih = 남는 자리를 전부
        #   위로) 그 아래를 다시 채운다 — 16:9 가 아닌 슬라이드가 와도 맞는다.
        if align == "band":
            fit_box = ("scale=" + str(slide_w) + ":" + str(H - band_h)
                       + ":force_original_aspect_ratio=decrease,"
                       + "pad=" + str(slide_w) + ":" + str(H - band_h)
                       + ":(ow-iw)/2:(oh-ih):color=" + fill)
            slide_fit = (fit_box + ",pad=" + str(slide_w) + ":" + str(H)
                         + ":0:0:color=" + fill)
        else:
            slide_fit = ("scale=" + str(slide_w) + ":" + str(H)
                         + ":force_original_aspect_ratio=decrease,"
                         + "pad=" + str(slide_w) + ":" + str(H)
                         + ":(ow-iw)/2:(oh-ih)/2:color=" + fill)

    chain = (
        "[0:v]" + slide_fit
        + ",pad=" + str(W) + ":" + str(H) + ":0:0:color=" + fill + ",setsar=1,"
        + col + "[bg];"
        + "[1:v]scale=" + str(av_w) + ":" + str(av_h) + "[av];"
        + "[bg][av]overlay=x=" + str(ax) + ":y=" + str(ay)
        + ":format=auto:shortest=0," + band + "[ov]"
    )
    return chain, {"slide": f"{slide_w}x{H}@0,0 ({fit}·{align})", "col_bg": fill,
                   "avatar": f"{av_w}x{av_h}@{ax},{ay}",
                   "band": band_h, "sub_center": W // 2,
                   "sub_dark": True, "sub_margin_v": 34}


# ══ 화면이 고르는 스타일 — 이 둘만 쓴다 ═══════════════════════════════════
# 배치 함수는 다섯 개지만 실제로 내보내는 것은 둘이다. 이름을 여기 한 곳에 두어
# CLI 와 화면이 같은 말을 쓰게 한다. 나머지 배치는 코드에 남겨 둔다 — 지우면
# 되돌릴 때 다시 짜야 하고, 화면에 안 띄우면 헷갈릴 일도 없다.
STYLES = {
    "full":  ("full",   "center"),   # 전면샷 — 슬라이드가 화면을 꽉 채우고 발표자가 그 위에
    "panel": ("studio", "band"),     # 여백형 — 슬라이드는 왼쪽 칸, 아래가 자막 선에 붙음
}
STYLE_NAME = {"full": "전면샷", "panel": "여백형"}

LAYOUTS = {"studio": layout_studio, "signage": layout_signage,
           "split": layout_split, "stage": layout_stage, "full": layout_full}


def main() -> None:
    ap = argparse.ArgumentParser(description="슬라이드+아바타+자막 합치기")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--style", default="", choices=[""] + list(STYLES),
                    help="화면이 쓰는 이름 — full=전면샷 · panel=여백형. "
                         "주면 --layout/--slide-align/--suffix 를 알아서 채운다")
    ap.add_argument("--layout", default="studio", choices=list(LAYOUTS),
                    help="studio=레퍼런스 구성(기본) · signage=슬라이드를 화면 안에 "
                         "· split=옆칸 · stage=겹침 · full=꽉 채우고 얹기")
    ap.add_argument("--scenes", default="", help="이 씬만 (기본: 전부)")
    ap.add_argument("--limit", type=float, default=None, help="앞 N초만 — 빨리 확인용")
    ap.add_argument("--avatar-h", type=float, default=0.80,
                    help="아바타 높이 ÷ 화면 높이 (0.80 이면 거의 전신)")
    ap.add_argument("--subs", default="burn", choices=["burn", "soft", "none"],
                    help="burn=픽셀에 굽기 · soft=끌 수 있는 트랙 · none=영상엔 없음")
    ap.add_argument("--column-bg", default="pad", choices=["pad", "auto", "dark"],
                    help="여백·발표자 칸 색 (셋은 늘 같은 색이다) — "
                         "pad=고정 아이보리(기본) · auto=슬라이드에서 찍음 · dark=검정에 가까움")
    ap.add_argument("--slide-align", default="center", choices=["center", "band"],
                    help="contain 일 때 세로 여백 위치 — center=위아래 반씩 "
                         "· band=아래를 자막 선에 붙이고 여백을 위로")
    ap.add_argument("--slide-fit", default="contain", choices=["contain", "cover"],
                    help="contain=안 자르고 맞춤(기본) · cover=잘라서 꽉 채움")
    ap.add_argument("--suffix", default="", help="산출 파일 이름 뒤에 붙일 말")
    ap.add_argument("--join", action="store_true", help="다 만든 뒤 한 편으로 잇는다")
    a = ap.parse_args()

    # --style 은 배치·정렬·산출이름을 한꺼번에 정한다. 화면은 이것만 넘긴다.
    if a.style:
        a.layout, a.slide_align = STYLES[a.style]
        if not a.suffix:
            a.suffix = "-" + a.style

    task = BUILD / a.task
    meta = load_json(need(task / "scenes.json", "p1_scenes.py 를 먼저 돌리세요"))
    lang = meta["sub_lang"]

    rows = [r for r in meta["scenes"] if r.get("voice") and r.get("avatar")]
    if a.scenes:
        from scripts.p1_scenes import parse_range
        want = set(parse_range(a.scenes, len(meta["scenes"])))
        rows = [r for r in rows if r["no"] in want]
    if not rows:
        die("합칠 씬이 없습니다 — p2_voice.py 와 p4_avatar.py 를 먼저 돌리세요")

    ff = ffmpeg()

    def build(slide: Path) -> tuple[str, dict]:
        """씬 하나의 필터 사슬. 칸 색이 auto 면 **그 씬 슬라이드**에서 찍는다."""
        if a.layout != "studio":
            return LAYOUTS[a.layout](a.avatar_h)
        col = a.column_bg
        if col == "auto":
            col = slide_bg(ff, slide)   # 덱 바탕이 아이보리가 아닐 때만 쓴다
        return layout_studio(a.avatar_h, a.slide_fit, col, a.slide_align)

    first_slide = task / "slides" / (rows[0]["slide"] or "")
    chain, box = build(first_slide)
    # 자막은 띠 안에서 세로 가운데쯤 온다. 띠 높이는 배치마다 다르다.
    margin_v = box.get("sub_margin_v") or max(12, int(box["band"] * 0.30))

    out_dir = task / "preview"
    ass_dir = task / "ass"
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_dir.mkdir(parents=True, exist_ok=True)

    n_lang = len({p.name.split(".")[1] for p in (task / "aligned").glob("*.srt")
                  if "." in p.name})
    subs_say = {"burn": "픽셀에 구움 — 못 끕니다",
                "soft": "끌 수 있는 트랙 — 업체가 다시 디자인할 수 있습니다",
                "none": "영상에 없음 — aligned/*.srt 를 따로 넘깁니다"}[a.subs]
    print(f"{len(rows)}씬 — {a.layout} · {W}x{H} · 자막 띠 {box['band']}px "
          f"· 자막 {a.subs}({subs_say})"
          + (f" · 트랙으로 얹을 언어 {n_lang - 1}개" if n_lang > 1 else ""))
    print(f"  슬라이드 {box['slide']} · 아바타 {box['avatar']}"
          + (f" · 칸 {box['col_bg']}" if box.get("col_bg") else "")
          + f" (발끝 y={H}) · 자막 중심 x={box.get('sub_center')}")
    made: list[Path] = []
    for r in rows:
        no = int(r["no"])
        slide = task / "slides" / (r["slide"] or "")
        if not r["slide"] or not slide.is_file():
            die(f"{no:02d}번 슬라이드가 없습니다 — p1_scenes.py 를 다시 돌리세요")
        srt = task / "aligned" / f"scene{no:02d}.{lang}.srt"
        if not srt.is_file():
            die(f"{srt} 가 없습니다 — p3_resync.py 를 먼저 돌리세요")

        # 씬마다 사슬을 다시 만든다 — 칸 색이 auto 면 **그 씬 슬라이드**에서 찍는다
        chain, box = build(slide)
        margin_v = box.get("sub_margin_v") or max(12, int(box["band"] * 0.30))
        ass = ass_dir / f"scene{no:02d}.{lang}.ass"

        n_cues = 0
        q = chr(39)
        # chain 은 [ov] 로 끝난다. 자막을 안 구울 때는 그 [ov] 를 그대로
        # 출력 이름 [v] 로 바꾼다 — 뒤에 덧붙이면 출력 라벨이 둘이 되어 죽는다.
        vf = chain[: -len("[ov]")] + "[v]"
        if a.subs == "burn":
            n_cues = srt_to_ass(srt, ass, margin_v=margin_v,
                                center=box.get("sub_center"),
                                dark=bool(box.get("sub_dark")))
            vf = (chain + ";[ov]subtitles=" + ass.name
                  + ":force_style=" + q + "Fontname=" + FONT + q + "[v]")
        else:
            n_cues = len(parse_srt(srt.read_text(encoding="utf-8-sig")))

        tag = a.suffix or ("-앞부분" if a.limit else "")
        out = out_dir / f"scene{no:02d}{tag}.mp4"
        # ★ 다국어 — 기본 언어는 픽셀에 굽고(burn), **나머지 언어는 트랙으로**
        #   얹는다. 렌더를 다시 하지 않으므로 언어를 열 개 더해도 굽는 일은 한 번이다.
        extra = sorted(x for x in (task / "aligned").glob(f"scene{no:02d}.*.srt")
                       if x.name != srt.name)
        track = ([srt] if a.subs == "soft" else []) + extra

        args = [ff, "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "25", "-i", str(slide.resolve()),
                "-i", str((task / "avatar" / r["avatar"]).resolve()),
                "-i", str((task / "voice" / r["voice"]).resolve())]
        for x in track:
            args += ["-i", str(x.resolve())]
        args += ["-filter_complex", vf, "-map", "[v]", "-map", "2:a"]
        for k, x in enumerate(track):
            # mov_text 는 mp4 가 담을 수 있는 유일한 자막 형식이다. 플레이어가
            # 껐다 켤 수 있고, 업체가 나중에 제 디자인으로 다시 구울 수 있다.
            tag = x.name.split(".")[1] if "." in x.name else lang
            args += ["-map", f"{3 + k}:s",
                     f"-metadata:s:s:{k}", f"language={tag}"]
        if track:
            args += ["-c:s", "mov_text"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                 "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-shortest"]
        # ★ -shortest 만 믿으면 안 된다. filter_complex 를 끼고 돌리면 씬마다
        #   1.8초쯤 길어져 8씬 합계가 9:47 이 아니라 10:02 로 나왔다(2026-09-02 실측).
        #   목소리 길이를 알고 있으니 **그 값을 그대로 박는다.**
        args += ["-t", f"{min(float(r['voice_dur']), a.limit) if a.limit else float(r['voice_dur']):.3f}"]
        args.append(str(out.resolve()))

        with Ticker(f"{no:02d} 합치는 중"):
            p = subprocess.run(args, cwd=str(ass_dir), capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0 or not out.is_file():
            die(f"{no:02d}번 합치기 실패: {(p.stderr or '')[-500:]}")
        if not a.limit:
            r["preview"] = out.name
            r["layout"] = a.layout
            r["subs_mode"] = a.subs
            if a.style:
                r.setdefault("previews", {})[a.style] = out.name
        made.append(out)
        print(f"  {no:02d}  {out.name}  ({mmss(r['voice_dur'])})  "
              f"자막 {n_cues}개  {r['title'][:32]}")

    if not a.limit:
        meta["layout"] = a.layout
        meta["subs_mode"] = a.subs
        meta["style"] = a.style or ""
        save_json(task / "scenes.json", meta)

    if a.join and len(made) > 1:
        lst = out_dir / "_join.txt"
        q = chr(39)
        lst.write_text("\n".join("file " + q + p.resolve().as_posix() + q for p in made) + "\n",
                       encoding="utf-8")
        joined = out_dir / f"all{a.suffix}.mp4"
        with Ticker("한 편으로 잇는 중"):
            # ★ -map 0 이 없으면 ffmpeg 이 스트림을 종류별로 하나씩만 골라
            #   **자막 트랙을 버린다**(2026-09-02 실측: soft 로 구운 8개를 이었더니
            #   all.mp4 에 mov_text 가 없었다). 전부 그대로 넘긴다.
            p = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                                "-f", "concat", "-safe", "0", "-i", str(lst),
                                "-map", "0", "-c", "copy", str(joined)],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        lst.unlink(missing_ok=True)
        if p.returncode != 0 or not joined.is_file():
            die(f"잇기 실패: {(p.stderr or '')[-300:]}")
        if not a.limit:
            meta["all"] = joined.name
            meta.setdefault("alls", {})[a.style or "default"] = joined.name
            save_json(task / "scenes.json", meta)
        print(f"  {joined.name}  ({mmss(sum(float(r['voice_dur']) for r in rows))})")

    print(f"\n완료 — {out_dir}")


if __name__ == "__main__":
    main()
