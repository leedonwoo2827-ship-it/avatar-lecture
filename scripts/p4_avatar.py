# -*- coding: utf-8 -*-
r"""P4 — 씬별 아바타. 엔진이 셋이다.

    강의/<작업>/voice/sceneNN.wav  →  강의/<작업>/avatar/…  + scenes.json

    stub     사람 모양 임시 아바타. 목소리 길이만큼. 크레딧 0. **배치 확인용.**
    drop     **HeyGen 웹에서 렌더해 내려받은 영상**을 붙인다. 오늘 쓰는 길.
    heygen   HeyGen API 가 같은 일을 자동으로 한다. 초당 과금(웹의 3~4배).

★ **아바타를 씬별로 자르지 않는다.**
  묶음 하나(=씬 8개쯤)가 영상 하나로 온다. 그걸 씬별로 잘라 두면 VP9 알파를
  여덟 번 재인코딩해야 하는데 — 1080x1920 짜리는 씬당 10분씩 걸리고 화질도
  깎인다. 그래서 **자르지 않고 «어디서부터 몇 초»만 적어 둔다.** p5_compose.py
  가 합성할 때 `-ss` 로 그 구간만 읽는다. 재인코딩 0회, 화질 손실 0.

★ **왜 묶음으로 렌더하나.** 씬마다 따로 렌더하면 아바타가 매 씬 시작마다 같은
  기본 포즈로 리셋되어 이어붙인 자리가 튄다. 한 덩어리로 렌더하면 자세와
  제스처가 이어진다 (p3b_voicepack.py 의 주석과 같은 이유).

★ 다음 단계(p5_compose.py)는 이 영상이 임시 아바타인지 진짜인지 **모른다.**
  scenes.json 의 `avatar` · `avatar_offset` · `avatar_crop` 만 보고 돈다.

    python scripts/p4_avatar.py --task lecture01 --engine stub
    python scripts/p4_avatar.py --task lecture01 --engine drop --from ~/Downloads
    python scripts/p4_avatar.py --task lecture01 --engine heygen --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (ROOT, die, ffmpeg, ffprobe, load_json, mmss, need,
                            probe_duration, save_json, scene_paths)
from scripts.ticker import Ticker

VIDEO_EXTS = {".webm", ".mp4", ".mov", ".mkv", ".m4v"}

# 임시 아바타 규격 — **선 사람 하나**의 비율이다(9:16 이 아니다). 레퍼런스 영상의
# 발표자를 재 보면 폭:높이가 대략 0.35 로, 9:16(0.5625)보다 한참 홀쭉하다.
# 임시 아바타가 실제보다 뚱뚱하면 배치를 잘못 잡게 되므로 여기서 맞춰 둔다.
AV_W, AV_H, FPS = 380, 1080, 25
FG = "0x23262B"      # 실루엣 색 — **검은 정장**. 진짜 아바타가 정장 차림이라
                     # 임시 아바타도 같은 톤이어야 미리보기가 실물과 안 어긋난다.

# ★ 임시 아바타는 **배경을 투명(알파)으로** 낸다. mp4 는 알파를 못 담으므로
#   ProRes 4444(.mov)로 낸다. 진짜 아바타는 HeyGen 이 webm(vp9 알파)으로 주므로
#   확장자가 다르다 — p5 는 scenes.json 에 적힌 **파일 이름**을 읽으니 상관없다.
EXT = ".mov"


# ══ stub — 임시 아바타 (기존 그대로) ═════════════════════════════════════════

def stub(ff: str, sec: float, out: Path) -> None:
    """사람 모양 임시 아바타 — 배경은 투명하고 실루엣만 남는다.

    머리·목·어깨·몸통을 상자 몇 개로 겹쳐 사람으로 읽히게 한다. 얼굴을 그리려는
    게 아니라 **어디까지 덮는지**를 보려는 것이라 이 정도면 충분하다.
    """
    head_w, head_h = 118, 142
    neck_w, neck_h = 46, 30
    sh_w, sh_h = 268, 74      # 어깨 — 정장 재킷이라 각지게
    torso_w = 232
    top = 74

    # ★ drawbox 는 **알파 채널을 안 쓴다.** 투명한 rgba 화면에 drawbox 로 그리면
    #   색만 얹히고 알파는 0 그대로라 결과가 통째로 투명해진다(2026-09-02 실측).
    #   그래서 모양을 흑백 **마스크**로 따로 그리고 alphamerge 로 붙인다.
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


def dec(src: Path) -> list[str]:
    r"""그 파일을 읽을 때 앞에 붙일 디코더 인자.

    ★ **webm 의 vp9 알파는 기본 디코더가 안 꺼낸다.** ffmpeg 내장 vp9 디코더는
      알파를 지원하지 않아 `alphaextract` 가 «Requested planes not available» 로
      죽는다. `-c:v libvpx-vp9` 를 **입력 앞에** 붙여야 알파가 나온다
      (2026-09-02 실측: HeyGen webm 은 ALPHA_MODE=1 인데 pix_fmt 는 yuv420p 로
      보고된다 — 알파가 별도 스트림이라 그렇다).
    """
    return ["-c:v", "libvpx-vp9"] if src.suffix.lower() == ".webm" else []


# ══ 영상 살펴보기 ═══════════════════════════════════════════════════════════

def has_alpha_tag(tags: dict) -> bool:
    """컨테이너 태그가 «알파가 있다» 고 말하는가. 이름의 대소문자를 안 가린다."""
    for k, v in tags.items():
        if str(k).lower() == "alpha_mode" and str(v).strip() == "1":
            return True
    return False


def probe_video(fp: str, src: Path) -> dict:
    """폭·높이·픽셀형식·길이. 알파가 있는지는 픽셀형식이 말해 준다."""
    r = subprocess.run(
        [fp, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,pix_fmt,r_frame_rate",
         # 태그 이름을 콕 집으면 대소문자가 다른 파일을 놓친다 — 통째로 받는다
         "-show_entries", "stream_tags",
         "-show_entries", "format=duration", "-of", "json", str(src)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(f"{src.name} 을 읽지 못했습니다: {(r.stderr or '')[-300:]}")
    got = json.loads(r.stdout or "{}")
    st = (got.get("streams") or [{}])[0]
    pix = str(st.get("pix_fmt") or "")
    return {
        "w": int(st.get("width") or 0), "h": int(st.get("height") or 0),
        "pix_fmt": pix,
        # yuva420p · rgba · yuva444p10le … 알파가 있으면 이름에 a 가 붙는다.
        # ★ webm 은 알파를 **별도 스트림**으로 담아 pix_fmt 가 yuv420p 로 나온다.
        #   그때는 컨테이너 태그 ALPHA_MODE 를 봐야 안다(2026-09-02 실측).
        # ★ **대소문자를 가리지 않는다.** HeyGen 은 `ALPHA_MODE`, ffmpeg 으로
        #   다시 묶으면 `alpha_mode` 로 적힌다(2026-09-03 실측). 콕 집어 비교하면
        #   한쪽을 놓치고, 놓치면 p5 가 검정 배경을 colorkey 로 빼려 들어
        #   **검정 정장이 같이 지워진다.** 조용히 틀리는 쪽이라 더 위험하다.
        "alpha": bool(re.search(r"(^|[^a-z])(yuva|rgba|bgra|argb|abgr|ya)", pix))
                 or has_alpha_tag(st.get("tags") or {}),
        "dur": float((got.get("format") or {}).get("duration") or 0.0),
    }


def alpha_bbox(ff: str, src: Path, w: int, h: int, dur: float,
               *, thr: int = 24, step: int = 2) -> tuple[int, int, int, int] | None:
    """알파가 실제로 차 있는 **바깥 테두리**를 찾는다.

    9:16 프레임에 사람이 오려 담겨 오면 좌우가 통째로 비어 있다. 그대로 쓰면
    p5 가 «폭이 이만큼인 사람»으로 알고 배치를 잡아 사람이 실제보다 작아진다.

    ★ 알파를 흑백으로 뽑아 **화소를 직접 읽는다.** 처음에는 cropdetect 에 물렸는데
      ProRes 4444 알파에서 limit 을 128 까지 올려도 «프레임 전체»만 답했다
      (2026-09-02 실측). 화소를 직접 세면 그런 일이 없다 — 느리지만 1080x1920
      한 장이 0.5초쯤이고 프레임 셋만 보므로 문제가 안 된다.

    ★ 프레임 셋(앞·중간·뒤)의 **합집합**을 쓴다 — 손을 든 프레임과 내린 프레임이
      다르므로 가장 넓은 쪽으로 잡아야 손이 잘리지 않는다.

    thr 은 «여기부터 사람» 으로 볼 알파값이다. 머리카락 끝처럼 반투명한 자리를
    배경으로 버리지 않으려고 낮게 둔다.
    """
    x1, y1, x2, y2 = w, h, 0, 0
    for at in (max(0.5, dur * 0.1), dur * 0.5, max(0.5, dur * 0.9)):
        r = subprocess.run(
            [ff, "-v", "error", *dec(src), "-ss", f"{at:.2f}", "-i", str(src),
             "-frames:v", "1",
             "-vf", "alphaextract", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True)
        d = r.stdout
        if len(d) < w * h:
            continue
        for y in range(0, h, step):
            row = y * w
            for x in range(0, w, step):
                if d[row + x] >= thr:
                    if x < x1:
                        x1 = x
                    if x > x2:
                        x2 = x
                    if y < y1:
                        y1 = y
                    if y > y2:
                        y2 = y
    if x2 <= x1 or y2 <= y1:
        return None
    pad = 6
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
    cw, ch = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    if cw < 32 or ch < 32:
        return None          # 잘라 봐야 남는 게 없다
    return cw, ch, x1, y1


def bg_bbox(ff: str, src: Path, w: int, h: int, dur: float, *,
            tol: int = 14, step: int = 2) -> tuple[tuple[int, int, int, int], str] | None:
    """**알파가 없을 때** — 배경색을 재서 사람만 남는 테두리를 찾는다.

    웹에서 배경을 «제거» 하려면 유료 플랜이 필요하다. 그래서 무료·저가 플랜에서는
    배경을 **단색**으로 지정해 받는다(우리는 슬라이드와 같은 아이보리로 받았다).
    단색이면 알파가 없어도 사람을 오려낼 수 있다 — 귀퉁이에서 색을 찍어 그 색과
    다른 화소의 바깥 테두리를 구하면 된다.

    ★ **배경색을 그대로 돌려준다.** h264 는 색을 정확히 보존하지 않아
      `#F6F1E8` 로 지정해도 `#F4F0E6` 로 온다(2026-09-02 실측). p5 의 발표자 칸을
      우리가 지정한 색으로 칠하면 그 2 차이가 **세로줄로 보인다.** 그래서 칸을
      «아바타에서 실제로 온 색»으로 칠한다.

    ★ 프레임 셋(앞·중간·뒤)의 **합집합**을 쓴다 — 손을 든 프레임과 내린 프레임이
      다르므로 가장 넓은 쪽으로 잡아야 손이 잘리지 않는다.
    """
    x1, y1, x2, y2 = w, h, 0, 0
    bg: tuple[int, int, int] | None = None
    for at in (max(0.5, dur * 0.1), dur * 0.5, max(0.5, dur * 0.9)):
        r = subprocess.run(
            [ff, "-v", "error", *dec(src), "-ss", f"{at:.2f}", "-i", str(src),
             "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        d = r.stdout
        if len(d) < w * h * 3:
            continue

        def px(x: int, y: int) -> tuple[int, int, int]:
            i = (y * w + x) * 3
            return d[i], d[i + 1], d[i + 2]

        # 네 귀퉁이의 **중앙값** — 하나가 사람에 물려도 색이 안 끌려간다
        corners = [px(6, 6), px(w - 7, 6), px(6, h - 7), px(w - 7, h - 7)]
        here = tuple(sorted(c[i] for c in corners)[len(corners) // 2] for i in range(3))
        if bg is None:
            bg = here
        for y in range(0, h, step):
            row = y * w
            for x in range(0, w, step):
                i = (row + x) * 3
                if (abs(d[i] - bg[0]) > tol or abs(d[i + 1] - bg[1]) > tol
                        or abs(d[i + 2] - bg[2]) > tol):
                    if x < x1:
                        x1 = x
                    if x > x2:
                        x2 = x
                    if y < y1:
                        y1 = y
                    if y > y2:
                        y2 = y
    if bg is None or x2 <= x1 or y2 <= y1:
        return None
    pad = 4
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
    cw, ch = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    if cw < 32 or ch < 32:
        return None
    return (cw, ch, x1, y1), "0x%02X%02X%02X" % bg


# ══ drop — 웹에서 내려받은 영상 붙이기 ═══════════════════════════════════════

# 이름 안의 «씬» 토막 — `scene02` · `scene02-07` · `씬3`. 묶음 번호를 찾을
# 때는 이것부터 지운다. 안 지우면 씬 번호가 묶음 번호로 읽힌다.
SCENE_TOK_RE = re.compile(r"(?:scene|씬)\s*0*\d+(?:\s*[-~–—]\s*0*\d+)?", re.I)
# 이름이 스스로 «몇 번 묶음» 이라고 말하는가
BUNDLE_TOK_RE = re.compile(r"(?:bundle|묶음)\s*0*(\d+)", re.I)


def _other_bundle(stem: str, bno: int) -> bool:
    """이름이 **다른 묶음**을 말하는가. 말하면 그 영상은 이 묶음 것이 아니다."""
    m = BUNDLE_TOK_RE.search(stem)
    return m is not None and int(m.group(1)) != bno


def find_bundle_clip(src: Path, bno: int, bdir_name: str) -> Path | None:
    r"""묶음 번호에 맞는 영상을 찾는다.

    가장 확실한 자리는 **묶음 폴더 안**이다 — `05\bundle01\` 에서 mp3 를 꺼내
    올렸으니 렌더된 영상도 거기 되돌려 놓는 것이 자연스럽고, 그러면 어느 영상이
    어느 묶음인지 이름으로 기억할 일이 없다.

    그 폴더가 비어 있으면 `--from` 으로 준 자리(보통 다운로드 폴더)를 뒤진다.
    이름 규칙은 강요하지 않는다 — 업체가 붙여 주는 이름을 모르고, 사람이 손으로
    고쳐 둘 수도 있다. 그래서 순서대로 넷을 본다:

      1. 이름이 `bundle01` 인 **폴더 안**의 영상
      2. 파일 이름에 `bundle01` 이 든 것
      3. 이름 어딘가에 `01` 이나 `1` 이 든 것
      4. 묶음이 하나뿐이면 그 안의 영상 하나
    """
    if src.is_file():
        return src if src.suffix.lower() in VIDEO_EXTS else None
    if not src.is_dir():
        return None
    vids = sorted(p for p in src.rglob("*")
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    if not vids:
        return None
    want = bdir_name.lower()
    inside = [p for p in vids if p.parent.name.lower() == want]
    if inside:
        return inside[0]
    for p in vids:
        if want in p.stem.lower():
            return p

    # ★ 이름이 **다른 묶음**을 말하면 아래 두 길에서 아예 뺀다. 그리고 숫자를
    #   보기 전에 «씬» 토큰을 지운다.
    #   `001-bundle01-scene02-07…` 을 묶음 2 로 잡은 적이 있다 — 이름 안의
    #   «scene02» 를 묶음 번호로 읽었다. 그 영상이 묶음 2(8분 36초)에 통째로
    #   붙어 씬 8~14 가 0.86배로 뭉개졌고, 화면은 «전부 붙었습니다» 라고 했다
    #   (2026-09-04 실측). 오류 없이 조용히 틀리는 자리라 더 나쁘다.
    rest = [p for p in vids if not _other_bundle(p.stem, bno)]
    for p in rest:
        stem = SCENE_TOK_RE.sub(" ", p.stem)
        if re.search(rf"(^|\D){bno:02d}(\D|$)", stem) or \
           re.search(rf"(^|\D){bno}(\D|$)", stem):
            return p
    return rest[0] if len(rest) == 1 else None


SPAN_RE = re.compile(r"(?:scene|씬|s)\s*0*(\d+)\s*[-~–—]\s*0*(\d+)", re.I)


def spans_range(stem: str) -> bool:
    r"""이름이 «씬 여러 개» 를 담고 있다고 말하는가.

    업체 프로젝트 이름은 `001-bundle01-scene02-07우즈벡간호-IV2` 처럼 온다.
    여기에 `scene02` 가 들어 있어 씬 2 짜리 영상으로 잡히면, 443초가 씬 2 에
    통째로 붙고 씬 3~7 은 «영상이 없다» 로 남는다 — 오류 없이 조용히 틀린다.

    ★ 범위로 읽히면 **씬 하나로 안 잡는다.** 그러면 길이로 나누는 길
      (조각 몇 개의 합이 남은 씬 길이와 맞나)로 떨어져 제대로 갈린다.
      길이는 이름과 달리 사람이 틀리게 적을 수 없다.

    ★ 씬 번호는 **두 자리**다. 그래서 뒤 숫자가 99 를 넘으면 범위가 아니다 —
      `scene02-1080p` 의 «02-1080» 을 씬 2~1080 으로 읽으면 안 된다.
      해상도·비트레이트·날짜가 이름에 붙는 것이 흔하다.
    """
    for m in SPAN_RE.finditer(stem):
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a < b <= 99 and b - a <= 40:
            return True
    return False


def find_scene_clip(src: Path, no: int) -> Path | None:
    r"""**씬 하나**에 맞는 영상을 찾는다.

    묶음 폴더에 `씬\sceneNN.mp3` 를 같이 넣어 두므로, 씬별로 렌더해 받아 오는
    길도 열려 있다. 씬별로 받으면 씬마다 제스처·표현을 지정할 수 있고 틀린
    씬만 다시 렌더한다 — 대신 드래그드랍을 여러 번 한다.

    ★ **이름을 엄하게 본다.** `bundle01` 도 «01» 을 갖고 있어서 느슨하게 찾으면
      묶음 영상을 씬 1번으로 오해한다. 그래서 둘만 인정한다:
        · 이름에 `scene01` 이 든 것
        · `씬\` 폴더 안에 있고 이름이 숫자로 시작하는 것
    """
    if not src.is_dir():
        return None
    want = f"scene{no:02d}"
    for p in sorted(src.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in VIDEO_EXTS):
            continue
        if want in p.stem.lower() and not spans_range(p.stem):
            return p
    for p in sorted(src.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in VIDEO_EXTS):
            continue
        if p.parent.name in ("씬", "scenes", "scene"):
            m = re.match(r"^0*(\d+)", p.stem)
            if m and int(m.group(1)) == no:
                return p
    return None


def place(clip: Path, dest_dir: Path) -> Path:
    """영상을 `avatar/` 안으로 들인다. **복사만 한다 — 다시 인코딩하지 않는다.**"""
    dest = dest_dir / clip.name
    if dest.resolve() != clip.resolve():
        shutil.copy2(clip, dest)
    return dest


def measure_clip(ff: str, fp: str, got: Path, a) -> dict:
    """영상 하나를 재서 p5 가 쓸 값을 낸다 — 테두리·배경색·뺄 색·알파.

    묶음 하나가 영상 하나로 오기도 하고 조각 여럿으로 오기도 한다. 재는 일은
    양쪽이 같으므로 여기 한 곳에 둔다 — 두 군데에 두면 한쪽만 고치는 사고가 난다.
    """
    v = probe_video(fp, got)
    crop, av_bg, key = "", "", ""
    if not a.no_tight:
        with Ticker(f"{got.name} 테두리 재는 중"):
            if v["alpha"]:
                bb = alpha_bbox(ff, got, v["w"], v["h"], v["dur"])
                got_bg = ""
            else:
                r2 = bg_bbox(ff, got, v["w"], v["h"], v["dur"])
                bb, got_bg = (r2[0], r2[1]) if r2 else (None, "")
        if bb:
            cw, ch, cx, cy = bb
            crop, av_bg = f"{cw}:{ch}:{cx}:{cy}", got_bg
    if av_bg and a.key != "off":
        if a.key not in ("auto", ""):
            key = a.key if a.key.startswith("0x") else "0x" + a.key.lstrip("#")
        else:
            rgb = [int(av_bg[2 + i * 2:4 + i * 2], 16) for i in range(3)]
            if max(rgb) - min(rgb) >= 60:
                key = av_bg
    aw = int(crop.split(":")[0]) if crop else v["w"]
    ah = int(crop.split(":")[1]) if crop else v["h"]
    return {"v": v, "crop": crop, "bg": av_bg, "key": key, "w": aw, "h": ah}


def say_clip(got: Path, m: dict, want_sec: float) -> None:
    """잰 값을 사람이 읽을 수 있게 한 번에 말한다."""
    v = m["v"]
    drift = v["dur"] - want_sec
    print(f"  {got.name}  {v['w']}x{v['h']}  {v['pix_fmt']}"
          f"{'  알파 있음' if v['alpha'] else '  **알파 없음**'}  {mmss(v['dur'])}"
          + ("" if abs(drift) < 0.5 else f"   ← 음성과 {drift:+.2f}초 차이"))
    if m["crop"]:
        cw, ch = m["w"], m["h"]
        print(f"     사람만 남기면 {cw}x{ch} (비율 {cw/ch:.3f})"
              + (f" · 배경 {m['bg']}" if m["bg"] else ""))
    if m["key"]:
        print(f"     배경 {m['key']} 을 **로컬에서 빼냅니다** — 알파와 같은 결과입니다")
    elif m["bg"]:
        print(f"     배경 {m['bg']} 은 채도가 낮아 안 뺍니다 — 발표자 칸을 이 색으로 칠합니다")


# ══ heygen — API ════════════════════════════════════════════════════════════

def render_via_api(bundle_mp3: Path, out: Path, *, engine: str, alpha: bool,
                   motion_prompt: str, title: str, idem: str) -> dict:
    from heygen.client import avatar as heygen_avatar

    def tick(st: str, waited: float) -> None:
        print(f"    {st or '대기'} … {waited:.0f}초")

    return heygen_avatar(bundle_mp3, out, engine=engine, alpha=alpha,
                         motion_prompt=motion_prompt, title=title,
                         idem=idem, on_tick=tick)


# ══ 본체 ════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="씬별 아바타")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--engine", default="stub", choices=["stub", "drop", "heygen"])
    ap.add_argument("--from", dest="src", default="",
                    help="drop 엔진이 쓸 폴더 또는 파일 (내려받은 아바타 영상)")
    ap.add_argument("--scenes", default="", help="이 씬만 (기본: 전부)")
    ap.add_argument("--key", default="auto",
                    help="배경을 로컬에서 빼낼 색 — auto=채도 높은 배경(초록 등)만 "
                         "자동으로(기본) · off=안 뺀다 · #00B140 처럼 직접 지정. "
                         "웹의 WebM(알파) 내보내기가 안 열릴 때 쓰는 길이다")
    ap.add_argument("--no-tight", action="store_true",
                    help="알파 테두리 자동 잘라내기를 끈다")
    ap.add_argument("--engine-ver", default="",
                    help="heygen: avatar_iii · avatar_iv · avatar_v (기본은 설정값)")
    ap.add_argument("--no-alpha", action="store_true",
                    help="heygen: 배경 투명(webm) 대신 불투명 mp4 로 받는다")
    ap.add_argument("--motion", default="", help="heygen: 제스처 지시문(motion_prompt)")
    ap.add_argument("--dry-run", action="store_true",
                    help="heygen: 예상액만 내고 **호출하지 않는다**")
    ap.add_argument("--force", action="store_true",
                    help="heygen: 이미 만든 묶음도 다시 만든다 (다시 과금된다)")
    a = ap.parse_args()

    P = scene_paths(a.task)
    meta = load_json(need(P.meta, "p1_scenes.py 를 먼저 돌리세요"))

    todo = [r for r in meta["scenes"] if r.get("voice")]
    if a.scenes:
        from scripts.p1_scenes import parse_range
        want = set(parse_range(a.scenes, len(meta["scenes"])))
        todo = [r for r in todo if r["no"] in want]
    if not todo:
        die("목소리가 아직 없습니다 — p2_voice.py 를 먼저 돌리세요")

    out_dir = P.avatar
    out_dir.mkdir(parents=True, exist_ok=True)
    ff, fp = ffmpeg(), ffprobe()

    # ── stub ────────────────────────────────────────────────────────────────
    if a.engine == "stub":
        print(f"{len(todo)}씬 — 임시 아바타 ({AV_W}x{AV_H}, 배경 투명)")
        for r in todo:
            no = int(r["no"])
            out = out_dir / f"scene{no:02d}{EXT}"
            with Ticker(f"{no:02d} 아바타"):
                stub(ff, float(r["voice_dur"]), out)
            r.update({"avatar": out.name, "avatar_dur": round(probe_duration(out), 3),
                      "avatar_engine": "stub", "avatar_offset": 0.0,
                      "avatar_crop": "", "avatar_w": AV_W, "avatar_h": AV_H})
            print(f"  {no:02d}  {mmss(r['avatar_dur']):>8}  {out.name}")
        save_json(P.meta, meta)
        print("\n배경이 투명한 임시 아바타입니다 — 사람이 어디까지 덮는지만 봅니다.")
        print(f"완료 — {out_dir}")
        return

    # ── drop · heygen — 둘 다 «묶음»이 단위다 ────────────────────────────────
    bundles = meta.get("bundles") or []
    if not bundles:
        die("묶음 정보가 없습니다 — `python scripts/p3b_voicepack.py --task "
            f"{a.task}` 를 먼저 돌리세요 (아바타는 묶음 단위로 렌더합니다)")

    by_no = {int(r["no"]): r for r in meta["scenes"]}
    want_nos = {int(r["no"]) for r in todo}
    use = [b for b in bundles if want_nos & set(b["scenes"])]
    if not use:
        die("고른 씬이 든 묶음이 없습니다")

    if a.engine == "heygen":
        from heygen.client import RATE_USD_PER_SEC, estimate, load_conf, status
        st = status()
        conf = load_conf()
        eng = a.engine_ver or conf.get("engine", "avatar_v")
        sec = sum(float(b["sec"]) for b in use)
        e = estimate(sec, eng)
        print(f"묶음 {len(use)}개 · 합계 {mmss(sec)} · 엔진 {eng}")
        print(f"예상액 ${e['usd']:,.2f}  (초당 ${e['rate']} × {sec:.1f}초)  "
              f"— **예상입니다.** 실제 차감액은 HeyGen Billing 에서 확인하세요")
        if a.dry_run:
            others = "  ".join(f"{k}=${sec*v:,.2f}" for k, v in RATE_USD_PER_SEC.items())
            print(f"엔진별: {others}")
            print("\n--dry-run 입니다 — 호출하지 않았습니다. 과금 0.")
            return
        if not st["ok"]:
            die(st["why"])

    print(f"묶음 {len(use)}개 — 엔진 {a.engine}")
    for b in use:
        bno, bsec = int(b["no"]), float(b["sec"])
        nos = [n for n in b["scenes"] if n in want_nos]

        # 1) 묶음 영상을 구한다 — 웹에서 내려받았거나, API 가 만들어 준다
        if a.engine == "drop":
            # --from 을 안 주면 **묶음 폴더**를 본다. 거기서 mp3 를 꺼내 올렸으니
            # 내려받은 영상도 거기 되돌려 놓는 것이 사람에게 자연스럽다.
            src = Path(a.src).expanduser().resolve() if a.src else P.upload
            if not src.exists():
                die(f"찾지 못했습니다: {src}")
            bdir_name = str(b.get("dir") or f"bundle{bno:02d}")

            # ★ **영상이 여러 개면 이름순으로 이어 읽는다.**
            #   업체 편집기에서 장면을 나눠 각각 따로 내려받을 수 있다(도입 71초 +
            #   본문 443초처럼). 그때 폴더에 영상이 둘 놓인다. 길이 합이 묶음
            #   길이와 맞으면 조각으로 본다 — 1개든 2개든 7개든 같은 규칙이다.
            #
            #   ★ 조각마다 **따로 잰다.** 프레이밍이 달라도(도입은 가까이, 본문은
            #     전신) 각자 제 테두리로 잘려 나온다 — 한 영상 안에서 크기가
            #     다르면 못 하던 일이 여기서는 된다.
            bdir_path = P.upload / bdir_name
            look_in = src if a.src else (bdir_path if bdir_path.is_dir() else src)

            # ★ **씬별 영상이 먼저다.** 이름에 `scene07` 이 든 영상이 고른 씬마다
            #   다 있으면 씬 단위로 읽는다. 묶음 길이와 안 맞아도 상관없다 —
            #   각자 제 씬 길이만 담고 있으니 시작이 늘 0초다.
            #
            #   이 길이 있어야 «씬 하나만 시험 삼아 렌더» 가 된다. 그게 없으면
            #   71초짜리를 514초 묶음으로 오해해 경계를 0.138배로 줄여 버린다.
            per = {}
            for n in nos:
                c = find_scene_clip(look_in, n)
                if c is not None:
                    per[n] = c

            vids = sorted(x for x in look_in.rglob("*")
                          if x.is_file() and x.suffix.lower() in VIDEO_EXTS)

            # ★ 씬별로 온 것을 먼저 박고, **남은 씬은 남은 영상으로** 채운다.
            #   섞여 오는 것이 정상이다 — 도입 한 씬만 좋은 모델로 따로 뽑고
            #   본문 여섯 씬은 싼 모델로 한 덩어리로 받는 식이다. 예전에는
            #   씬별이 하나라도 잡히면 나머지를 통째로 건너뛰어서, 그 흔한
            #   조합이 «씬 2~7 은 아직 없습니다» 로만 끝났다.
            if per:
                for n in sorted(per):
                    got_i = place(per[n], out_dir)
                    m = measure_clip(ff, fp, got_i, a)
                    r = by_no[n]
                    say_clip(got_i, m, float(r["voice_dur"]))
                    r.update({
                        "avatar": got_i.name, "avatar_offset": 0.0,
                        "avatar_dur": round(m["v"]["dur"], 3),
                        "avatar_engine": a.engine,
                        "avatar_crop": m["crop"], "avatar_w": m["w"],
                        "avatar_h": m["h"], "avatar_alpha": m["v"]["alpha"],
                        "avatar_bg": m["bg"], "avatar_key": m["key"],
                    })
                    print(f"    {n:02d}  0:00.0 부터 {r['avatar_dur']:6.2f}초  "
                          f"{str(r.get('title',''))[:28]}  ← 씬별 영상")

            used = {x.resolve() for x in per.values()}
            rest = [n for n in nos if n not in per]
            cand = [x for x in vids if x.resolve() not in used]
            if not rest:
                continue
            rsec = sum(float(by_no[n]["voice_dur"]) for n in rest)

            # 남은 영상 길이 합이 남은 씬 길이 합과 맞으면 조각으로 본다.
            # 1개든 2개든 같은 규칙이다 — 묶음 통째 영상도 여기 걸린다.
            if cand:
                durs = [probe_video(fp, x)["dur"] for x in cand]
                if abs(sum(durs) - rsec) <= max(3.0, 0.02 * rsec):
                    print(f"  조각 {len(cand)}개로 왔습니다 "
                          f"({' + '.join(mmss(d) for d in durs)} = {mmss(sum(durs))}"
                          f" ≈ 남은 씬 {mmss(rsec)})")
                    left = [by_no[n] for n in rest]
                    for clip_i, (one, dur_i) in enumerate(zip(cand, durs), start=1):
                        got_i = place(one, out_dir)
                        # 이 조각이 담은 씬들 — 씬 길이를 쌓아 조각 길이에 맞춘다
                        part, acc = [], 0.0
                        while left and acc + float(left[0]["voice_dur"]) <= dur_i + 1.0:
                            part.append(left.pop(0))
                            acc += float(part[-1]["voice_dur"])
                        if not part and left:
                            part.append(left.pop(0))
                            acc = float(part[0]["voice_dur"])
                        m = measure_clip(ff, fp, got_i, a)
                        say_clip(got_i, m, acc)
                        sc = (dur_i / acc) if acc > 0 else 1.0
                        off = 0.0
                        for r in part:
                            r.update({
                                "avatar": got_i.name,
                                "avatar_offset": round(off, 3),
                                "avatar_dur": round(float(r["voice_dur"]) * sc, 3),
                                "avatar_engine": a.engine,
                                "avatar_crop": m["crop"], "avatar_w": m["w"],
                                "avatar_h": m["h"], "avatar_alpha": m["v"]["alpha"],
                                "avatar_bg": m["bg"], "avatar_key": m["key"],
                                "avatar_part": clip_i,
                            })
                            print(f"    {int(r['no']):02d}  {mmss(off):>8} 부터 "
                                  f"{r['avatar_dur']:6.2f}초  "
                                  f"{str(r.get('title',''))[:28]}")
                            off += float(r["voice_dur"]) * sc
                    if left:
                        print(f"     ← 남은 씬 {[int(r['no']) for r in left]} 이 "
                              f"어느 조각에도 안 들어갔습니다. 조각 길이를 확인하세요")
                    continue
                # 길이가 안 맞는다 — 씬별로 온 것이 이미 있으면 여기서 멈춘다.
                # 통째 영상으로 다시 읽으면 이미 박은 씬을 덮어써 어긋난다.
                if per:
                    print(f"  · 씬 {rest} — 영상 {len(cand)}개의 길이 합 "
                          f"{mmss(sum(durs))} 이 남은 씬 {mmss(rsec)} 과 안 맞아 "
                          f"건드리지 않습니다")
                    continue

            # 씬별로 온 것이 있는데 남은 씬에 맞는 영상이 없으면 여기서 끝난다.
            # 통째 영상 길로 새면 방금 박은 씬01 영상을 «묶음 전체» 로 오해해
            # 경계를 0.14배로 줄여 버린다 — 그 사고를 한 번 겪었다.
            if per:
                print(f"  · 씬 {rest} — 아직 영상이 없어 건드리지 않습니다 "
                      f"({P.upload / bdir_name})")
                continue

            clip = find_bundle_clip(src, bno, bdir_name)
            if clip is None:
                # ★ **건너뛴다, 죽지 않는다.** 묶음이 다섯인데 하나만 받아 온
                #   상태가 정상이다. 거기서 죽으면 이미 받은 것도 안 붙는다.
                print(f"  · 묶음 {bno:02d} — 아직 영상이 없어 건너뜁니다 "
                      f"({P.upload / bdir_name})")
                continue
            got = place(clip, out_dir)
            info = {}
        else:
            mp3 = P.upload / b["file"]   # "bundle01/올릴음성.mp3"
            need(mp3, "p3b_voicepack.py 를 먼저 돌리세요")
            got = out_dir / f"bundle{bno:02d}{'.mp4' if a.no_alpha else '.webm'}"
            if got.is_file() and b.get("heygen_video_id") and not a.force:
                print(f"  {got.name}  이미 있습니다 — 건너뜁니다 "
                      f"(다시 만들려면 --force, 다시 과금됩니다)")
                info = {}
            else:
                with Ticker(f"묶음 {bno:02d} 렌더 요청"):
                    pass
                info = render_via_api(
                    mp3, got,
                    engine=a.engine_ver or "", alpha=not a.no_alpha,
                    motion_prompt=a.motion, title=f"{a.task}-bundle{bno:02d}",
                    idem=str(uuid.uuid5(uuid.NAMESPACE_URL,
                                        f"{a.task}/{b['file']}/{a.engine_ver}")))
                b["heygen_video_id"] = info["video_id"]
                b["heygen_seconds"] = info["seconds"]
                b["heygen_usd_est"] = info["usd_est"]
                print(f"    video_id {info['video_id']} · {info['seconds']:.1f}초 "
                      f"· 예상 ${info['usd_est']:,.2f}")

        # 2) 살펴본다 — 알파가 실제로 왔는지, 길이가 맞는지
        v = probe_video(fp, got)
        drift = v["dur"] - bsec
        print(f"  {got.name}  {v['w']}x{v['h']}  {v['pix_fmt']}"
              f"{'  알파 있음' if v['alpha'] else '  **알파 없음**'}"
              f"  {mmss(v['dur'])}"
              + ("" if abs(drift) < 0.5 else f"   ← 음성 합계와 {drift:+.2f}초 차이"))
        if not v["alpha"]:
            print("     배경이 불투명합니다 — `--style panel`(여백형)은 그대로 돕니다. "
                  "오른쪽 칸이 사각형으로 보일 뿐 깨지지 않습니다.")

        # ★ 길이가 벌어지면 **비율로 늘려** 경계를 다시 잡는다. 그대로 두면 뒤쪽
        #   씬이 통째로 밀려 입모양이 안 맞는다. 0.5초 안이면 손대지 않는다.
        # ★ 길이가 **크게** 어긋나면 늘리지 말고 멈춘다.
        #   묶음 8분 34초 자리에 씬 하나(1분 11초)를 놓으면 0.138배로 뭉개져
        #   씬마다 10초짜리 쓰레기가 나온다(2026-09-02 실측). 조용히 틀리는
        #   것이 제일 나쁘다 — 사람이 «왜 이러지» 하고 한참을 헤맨다.
        #
        #   씬 하나만 시험했다면 파일 이름에 `sceneNN` 을 넣어 주면 된다.
        #   그러면 위에서 씬별로 알아본다.
        scale = 1.0
        if bsec > 0 and abs(drift) > max(3.0, 0.2 * bsec):
            nl = chr(10)
            die(f"{got.name} 은 {mmss(v['dur'])} 인데 묶음 {bno:02d} 는 "
                f"{mmss(bsec)} 입니다 ({drift:+.1f}초).{nl}"
                f"  · 묶음 전체를 렌더한 영상이 맞나요?{nl}"
                f"  · 씬 하나만 시험한 것이면 파일 이름에 scene01 처럼 씬 번호를 "
                f"넣어 주세요 — 그러면 그 씬에만 붙입니다.{nl}"
                f"  · 조각으로 나눠 받았으면 조각을 **전부** 그 폴더에 넣어 주세요.")
        if bsec > 0 and abs(drift) >= 0.5:
            scale = v["dur"] / bsec
            print(f"     경계를 {scale:.4f} 배로 다시 잡습니다 "
                  f"(렌더 결과가 음성보다 {drift:+.2f}초)")

        # ★ 테두리를 재는 길이 둘이다. 알파가 오면 알파로, 안 오면 **배경색으로.**
        #   배경 제거는 유료 기능이라 저가 플랜에서는 단색 배경으로 받는데,
        #   단색이면 색으로도 사람을 오려낼 수 있다.
        crop, av_bg = "", ""
        if not a.no_tight:
            with Ticker(f"묶음 {bno:02d} 테두리 재는 중"):
                if v["alpha"]:
                    bb = alpha_bbox(ff, got, v["w"], v["h"], v["dur"])
                    got_bg = ""
                else:
                    r2 = bg_bbox(ff, got, v["w"], v["h"], v["dur"])
                    bb, got_bg = (r2[0], r2[1]) if r2 else (None, "")
            if bb:
                cw, ch, cx, cy = bb
                crop = f"{cw}:{ch}:{cx}:{cy}"
                av_bg = got_bg
                print(f"     사람만 남기면 {cw}x{ch} (비율 {cw/ch:.3f}) "
                      f"— 프레임 {v['w']}x{v['h']} 에서 잘라 씁니다"
                      + (f" · 배경색 {av_bg}" if av_bg else ""))
                if av_bg:
                    print(f"     발표자 칸을 **{av_bg}** 로 칠합니다 — 우리가 지정한 색이 "
                          f"아니라 **실제로 온 색**입니다(h264 가 색을 조금 바꿉니다). "
                          f"다르면 그 경계가 세로줄로 보입니다.")

        # ★ 배경이 **크로마(초록·파랑처럼 채도 높은 색)** 면 로컬에서 빼낸다.
        #   웹의 WebM(알파) 내보내기가 다중 장면 프로젝트에서 안 열린다
        #   (2026-09-02 실측: 형식 드롭다운에 MP4 하나뿐). 그래서 초록 배경으로
        #   받아 ffmpeg colorkey 로 뺀다 — 결과는 알파와 같고 0원이다.
        #
        #   아이보리(#F4F0E6)처럼 **채도가 낮은 색은 키잉하지 않는다.** 흰 셔츠와
        #   8~12 밖에 차이가 안 나 셔츠가 같이 사라진다(2026-09-02 실측).
        #   채널 최대-최소 차이로 판단한다: 초록 #00B140 은 177, 아이보리는 14.
        key = ""
        if av_bg and a.key != "off":
            if a.key not in ("auto", ""):
                key = a.key if a.key.startswith("0x") else "0x" + a.key.lstrip("#")
            else:
                rgb = [int(av_bg[2 + i * 2:4 + i * 2], 16) for i in range(3)]
                spread = max(rgb) - min(rgb)
                if spread >= 60:
                    key = av_bg
                    print(f"     배경 {av_bg} 은 채도가 높습니다(차이 {spread}) — "
                          f"**로컬에서 빼냅니다.** 알파와 같은 결과가 됩니다")
                else:
                    print(f"     배경 {av_bg} 은 채도가 낮습니다(차이 {spread}) — "
                          f"키잉하면 밝은 옷이 같이 사라집니다. 발표자 칸을 "
                          f"이 색으로 칠하는 쪽으로 갑니다")

        aw = int(crop.split(":")[0]) if crop else v["w"]
        ah = int(crop.split(":")[1]) if crop else v["h"]

        # 3) 씬마다 «어디서부터 몇 초»를 적는다. **자르지 않는다.**
        for n in nos:
            r = by_no[n]
            off = float(r.get("bundle_offset") or 0.0) * scale
            r.update({
                "avatar": got.name,
                "avatar_offset": round(off, 3),
                "avatar_dur": round(float(r["voice_dur"]) * scale, 3),
                "avatar_engine": a.engine,
                "avatar_crop": crop,
                "avatar_w": aw, "avatar_h": ah,
                "avatar_alpha": v["alpha"],
                # 알파가 없을 때 p5 가 발표자 칸을 이 색으로 칠한다
                "avatar_bg": av_bg,
                # 채도 높은 배경이면 p5 가 colorkey 로 빼낸다 (알파와 같은 결과)
                "avatar_key": key,
            })
            if info:
                r["heygen_video_id"] = info["video_id"]
            print(f"    {n:02d}  {mmss(off):>8} 부터 {r['avatar_dur']:6.2f}초  "
                  f"{str(r.get('title',''))[:30]}")

    save_json(P.meta, meta)
    if a.engine == "drop" and not any(r.get("avatar") for r in meta["scenes"]):
        die(f"붙일 영상이 하나도 없습니다 — {P.upload} 의 묶음 폴더에 "
            f"업체에서 받은 영상을 넣으세요")
    if a.engine == "heygen":
        tot = sum(float(b.get("heygen_usd_est") or 0) for b in use)
        if tot:
            print(f"\n예상 합계 ${tot:,.2f} — 실제 차감액을 HeyGen Billing → "
                  f"Transactions 에서 대조하세요")
    print(f"\n자르지 않았습니다 — p5 가 -ss 로 그 구간만 읽습니다 (재인코딩 0회)")
    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
