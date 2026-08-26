# -*- coding: utf-8 -*-
"""공통 경로 · 자잘한 헬퍼.

강의 하나가 워크스페이스 폴더 하나다 — `output/2608261930-강의이름/`처럼
**만든 시각 + 짧은 이름**이다. 그 안은 단계 순서대로 `00`, `01`, `02` … 로만
부른다 — 설명은 이 파일(코드)이 갖고 있으면 되지 폴더 이름까지 길게 늘어놓을
필요는 없다.

    output/YYMMDDHHmm-슬러그/
      00/  원본 mp4 · 슬라이드 이미지(받아온 것)
      01/  audio.m4a(아바타 립싱크용 원본품질) · stt.wav(16k mono, 전사 전용)
      02/  words.json   {duration, segments, words}          ← s2 STT
      03/  cues.json · subs.<lang>.srt                       ← s3 한 줄 자막
      04/  chunks.json                                        ← s4 perso 분할점
      05/  scenes.json · scenes.csv                           ← s5 씬↔슬라이드
      06/  perso/chunk01/ …                                   ← s6 투입 패키지
           _preview/                                          ← s7 검수용 번인본

s1~s7은 전부 **이름이 가장 늦은(=시각이 가장 최근인) 워크스페이스**를 대상으로
돈다 — 굳이 어느 폴더인지 매번 지정할 필요가 없다. 시각이 앞자리라 폴더명을
문자열로 정렬해도 시간 순서와 같다. 새 강의를 시작할 때만(=s1이 새 mp4를 받을
때만) 워크스페이스가 하나 새로 생긴다.

★ 산출물은 지우지 않는다. 사람이 손으로 고친 03·04·05의 JSON이 다음 단계에서
  그대로 이긴다 — 손편집이 이긴다는 260812/260818 원칙 그대로다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# ★ 윈도 한글 로캘 콘솔의 기본 stdout 인코딩은 cp949라, 이 파일들이 곳곳에 쓰는
#   em dash(—)나 키릴 문자를 못 만나면 UnicodeEncodeError로 죽는다. 모든 스크립트가
#   이 파일을 제일 먼저 import하니 여기서 한 번만 고치면 된다. (260818에서 실측된 함정)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — 표시용 보정이다. 안 되면 그냥 넘어간다
        pass

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# ── perso 제약 ───────────────────────────────────────────────────────────────
# perso는 30분에서 끊긴다. 상한을 28분으로 잡아 2분을 마진으로 남긴다 — 인코딩
# 오차나 perso 쪽 반올림으로 1799.6초가 1800.4초로 읽히는 사고를 피하려는 것.
PERSO_LIMIT_SEC = 30 * 60
CHUNK_MAX_SEC = 28 * 60
# 컷 지점은 "목표 시각 ± 이만큼" 창 안에서 **가장 긴 침묵**을 찾아 정한다.
# 초를 재서 딱 자르면 말 중간이 잘려 아바타가 깨지므로, 반드시 말과 말 사이에서 끊는다.
CUT_SEARCH_HALF_SEC = 3 * 60

# ── 자막 규칙 ────────────────────────────────────────────────────────────────
# 큐 하나 = 한 줄. 글자폭이 언어마다 달라 최대 글자수를 따로 둔다.
CUE_MAX_CHARS = {
    "ru": 42,   # 키릴 — 글자가 넓다
    "uz": 46,   # 우즈벡 라틴
    "en": 46,
    "ko": 30,   # 한글 — 한 글자가 라틴 두 글자 폭
}
CUE_MIN_SEC = 1.2      # 이보다 짧게 스치면 못 읽는다
CUE_MAX_SEC = 6.0      # 이보다 길게 붙어 있으면 화면이 죽는다
CUE_GAP_SEC = 0.08     # 큐 사이 최소 간격 — 겹치면 플레이어가 둘을 겹쳐 그린다


def cue_max_chars(lang: str) -> int:
    return CUE_MAX_CHARS.get((lang or "").lower()[:2], 46)


def slugify(name: str, maxlen: int = 16) -> str:
    """파일명 → 폴더 이름에 쓸 짧은 조각. 한글·영문·숫자만 남긴다."""
    stem = Path(name).stem
    cleaned = re.sub(r"[^0-9A-Za-z가-힣]+", "", stem)
    return (cleaned or "lecture")[:maxlen]


def _workspace_dirs() -> list[Path]:
    if not OUTPUT_DIR.is_dir():
        return []
    return sorted((p for p in OUTPUT_DIR.iterdir() if p.is_dir()), key=lambda p: p.name)


def latest_workspace_or_none() -> Path | None:
    """이름이 가장 늦은 워크스페이스. 하나도 없으면 **만들지 않고** None."""
    dirs = _workspace_dirs()
    return dirs[-1] if dirs else None


def current_workspace() -> Path:
    """가장 최근 워크스페이스. 하나도 없으면 죽는다 — s1이 만드는 게 맞다.

    s2~s7이 실수로 빈 폴더를 만들어 놓고 "파일이 없다"고 헤매는 걸 막는다.
    """
    ws = latest_workspace_or_none()
    if ws is None:
        die("워크스페이스가 없습니다 — s1_ingest.py로 mp4를 먼저 넣으세요")
    return ws


def new_workspace(slug_source: str = "") -> Path:
    """`YYMMDDHHmm-슬러그` 폴더를 새로 만든다 — s1이 새 mp4를 받을 때만 부른다."""
    ts = datetime.now().strftime("%y%m%d%H%M")
    name = f"{ts}-{slugify(slug_source) if slug_source else 'lecture'}"
    p = OUTPUT_DIR / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def paths(ws: Path) -> SimpleNamespace:
    """그 워크스페이스 안의 모든 자리 이름 — 폴더 자체는 00~06 숫자로만 부른다."""
    dist = ws / "06"
    return SimpleNamespace(
        ws=ws,
        src=ws / "00",
        src_slides=ws / "00" / "slides",
        media=ws / "01",
        audio=ws / "01" / "audio.m4a",
        sttwav=ws / "01" / "stt.wav",
        meta=ws / "01" / "media.json",
        full=ws / "02",
        words=ws / "02" / "words.json",
        subs=ws / "03",
        cues=ws / "03" / "cues.json",
        split=ws / "04",
        chunks=ws / "04" / "chunks.json",
        scenes_dir=ws / "05",
        scenes=ws / "05" / "scenes.json",
        scenes_csv=ws / "05" / "scenes.csv",
        dist=dist,
        perso=dist / "perso",
        preview=dist / "_preview",
    )


def srt_path(P: SimpleNamespace, lang: str) -> Path:
    return P.subs / f"subs.{lang}.srt"


# ── 외부 도구 ────────────────────────────────────────────────────────────────

def ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        die("ffmpeg를 찾지 못했습니다 — https://www.gyan.dev/ffmpeg/builds/ 설치 후 PATH 등록")
    return ff


def ffprobe() -> str:
    fp = shutil.which("ffprobe")
    if not fp:
        die("ffprobe를 찾지 못했습니다 (ffmpeg와 같이 설치됩니다)")
    return fp


def run(args: list[str], *, what: str) -> subprocess.CompletedProcess:
    """조용히 돌리고, 실패하면 stderr 앞부분을 붙여 죽는다."""
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(f"{what} 실패: {(r.stderr or '').strip()[:400]}")
    return r


def probe_duration(src: Path) -> float:
    r = run([ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(src)],
            what=f"{src.name} 길이 재기")
    try:
        return float((r.stdout or "0").strip())
    except ValueError:
        die(f"{src.name} 길이를 읽지 못했습니다")
        return 0.0


# ── 자잘한 것 ────────────────────────────────────────────────────────────────

def load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save_json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def need(p: Path, hint: str) -> Path:
    if not p.is_file():
        die(f"{p} 가 없습니다 — {hint}")
    return p


def mmss(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 3600):d}:{int(t // 60) % 60:02d}:{t % 60:04.1f}" if t >= 3600 \
        else f"{int(t // 60)}:{t % 60:04.1f}"


def die(msg: str) -> None:
    raise SystemExit(f"오류: {msg}")
