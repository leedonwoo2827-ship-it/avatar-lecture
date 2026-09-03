# -*- coding: utf-8 -*-
r"""웹 화면 — 브라우저에서 순서대로 돌리고 결과를 본다.

    run.bat  →  http://127.0.0.1:6326

외부 패키지를 쓰지 않는다(파이썬 표준 라이브러리만 — Flask 아님). 화면은
webapp/index.html 하나에 들어 있어 디자인을 고치려면 그 파일만 건드리면 된다.

**대본과 슬라이드에서 영상을 세우는 길(p1~p5)만** 담는다. 반대 방향(완성 mp4 를
헐어 perso 재료를 만드는 s1~s7)은 이 저장소의 옛 용도라 화면에서 뺐다 —
scripts/s1_*.py ~ s7_*.py 는 그대로 있으니 CLI 로는 계속 쓸 수 있다.

perso 는 **목소리(p2)와 아바타(p4) 두 단계에서만** 부른다. 나머지는 전부 로컬
ffmpeg 이라 크레딧이 0 이다. 키를 넣기 전까지는 그 둘도 크레딧 안 쓰는 엔진으로
돈다(시연본에서 소리 떼기 · 임시 아바타).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import LECTURES, ROOT, load_json, local_config, scene_paths
from scripts.cues import parse_srt, to_srt, Cue

PORT = 6326
HERE = Path(__file__).resolve().parent
# .venv 가 있으면 그것을, 없으면 지금 돌고 있는 파이썬을 쓴다.
# 씬 만들기(p1~p5)는 표준 라이브러리와 ffmpeg 만 쓰므로 setup.bat 없이도 돈다 —
# 화면부터 보고 나서 무거운 설치를 하려는 사람을 막지 않으려는 것이다.
# s1~s7 은 faster-whisper 가 필요하니 그때는 .venv 가 있어야 한다.
_VENV = ROOT / ".venv" / "Scripts" / "python.exe"
PY = _VENV if _VENV.is_file() else Path(sys.executable)
BUILD = LECTURES   # 강의 하나가 폴더 하나 (scripts/common.scene_paths)

# ══ 순서 ═══════════════════════════════════════════════════════════════════
# 화면의 번호와 같은 순서다. 자막(p3)이 목소리(p2) 뒤에 오는 것은 자막 타임코드를
# **실제 합성된 음성 길이에 맞춰** 다시 재기 때문이다 — 목소리가 없으면 못 돈다.
SCENE_STEPS = [
    ("p1",  "씬 떼기"),
    ("p2",  "목소리"),
    ("p2b", "다국어 자막"),
    ("p3",  "자막 맞추기"),
    ("p3b", "음성 묶음"),
    ("p4",  "아바타"),
    ("p5",  "합치기"),
]

class Job:
    """지금 돌고 있는 작업 하나. 로그를 줄 단위로 쌓아 두고 화면이 받아 간다."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.step: str = ""
        self.running = False
        self.failed = False
        self.ws: str = ""
        self.lang: str = ""
        self.sub_lang: str = ""
        # 이번에 도는 단계 목록 — 전부 만들기면 다섯, 단계 하나면 하나다.
        self.kind: str = ""
        self.steps: list[dict] = []
        self._lock = threading.Lock()

    def log(self, line: str) -> None:
        with self._lock:
            self.lines.append(line.rstrip())

    def snapshot(self, since: int) -> dict:
        with self._lock:
            return {"lines": self.lines[since:], "total": len(self.lines),
                    "step": self.step, "running": self.running,
                    "failed": self.failed, "ws": self.ws,
                    "lang": self.lang, "sub_lang": self.sub_lang,
                    "kind": self.kind, "steps": self.steps}


JOB = Job()


def scene_args(o: dict) -> dict[str, list[str]]:
    """단계 이름 → 명령줄. **전부 만들기와 단계 하나가 같은 표를 쓴다** —
    둘이 따로 놀면 화면에서 돌린 것과 한 번에 돌린 것이 달라진다.
    """
    task = o["task"]
    return {
        "p1": ["scripts/p1_scenes.py", "--task", task, "--scenes", o["scenes"],
               "--script", o["script"], "--subs", o["subs"], "--slides", o["slides"],
               "--sub-lang", o["sub_lang"]],
        "p2": ["scripts/p2_voice.py", "--task", task, "--engine", o["voice_engine"]]
              + (["--from", o["source"]] if o["voice_engine"] == "source" else []),
        # 자막 파일이 이미 있으면 p2b 는 "할 일이 없습니다" 하고 그냥 끝난다.
        # 우즈베크어 대본만 온 강의에서만 실제로 옮긴다.
        "p2b": ["scripts/p2b_translate.py", "--task", task,
                "--from", o["script_lang"], "--to", o["sub_lang"]]
               + (["--force"] if o.get("retranslate") else []),
        "p3": ["scripts/p3_resync.py", "--task", task],
        # 아바타 업체(HeyGen)에 넣을 덩어리. 10분 상한 안에서 씬 경계로만 묶는다 —
        # 45분 강의가 4조각이 된다. 아바타를 씬별로 렌더하면 매 씬 시작마다
        # 자세가 리셋되어 이어붙인 자리가 튀므로 묶어 넣는다.
        "p3b": ["scripts/p3b_voicepack.py", "--task", task,
                "--max-sec", str(o["bundle_max_sec"]), "--pack", o["bundle_pack"]],
        "p4": ["scripts/p4_avatar.py", "--task", task, "--engine", o["avatar_engine"]]
              # ★ avatar_src 가 **비어 있으면 --from 을 아예 안 붙인다.** 빈 값으로
              #   넘기면 argparse 가 빈 경로를 받아 죽는다. 안 붙이면 p4 가 묶음
              #   폴더(05/bundleNN/)를 본다 — 그게 기본 길이다.
              + (["--from", o["avatar_src"]]
                 if (o["avatar_engine"] == "drop" and o["avatar_src"]) else []),
        "p5": ["scripts/p5_compose.py", "--task", task, "--style", o["style"],
               "--subs", o["subs_mode"], "--avatar-h", str(o["avatar_h"]),
               "--avatar-vary", str(o["avatar_vary"]),
               "--avatar-sink", str(o["avatar_sink"]),
               "--avatar-rotate", str(o["avatar_rotate"]),
               "--slide-fit", o["slide_fit"], "--join"],
    }


def run_scene_pipeline(opts: dict) -> None:
    """전부 만들기 — p1~p5 를 순서대로 돌린다.

    기본은 **돈을 안 쓰는 엔진**이다: 목소리는 원본에서 떼어 오고(source),
    아바타는 임시 아바타(stub)를 놓는다. 화면과 배치를 다 확인한 뒤 아바타만
    갈아 끼운다 — `drop`(HeyGen 웹에서 렌더해 내려받기) 또는 `heygen`(API).
    """
    JOB.lines.clear()
    JOB.running, JOB.failed, JOB.ws = True, False, ""
    JOB.lang, JOB.sub_lang = "uz", opts["sub_lang"]
    JOB.kind = "scene"
    JOB.steps = [{"key": k, "label": l} for k, l in SCENE_STEPS]

    args_for = scene_args(opts)
    try:
        for key, label in SCENE_STEPS:
            JOB.step = key
            JOB.log(f"[{key}] {label}")
            pr = subprocess.Popen([str(PY)] + args_for[key], cwd=str(ROOT),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  bufsize=1)
            for line in pr.stdout:
                JOB.log("    " + line.rstrip())
            if pr.wait() != 0:
                JOB.failed = True
                JOB.log(f"[{key}] 멈췄습니다 — 위 메시지를 확인하세요")
                return
        JOB.ws = opts["task"]
        JOB.step = "done"
    finally:
        JOB.running = False


def run_one_step(step: str, opts: dict) -> None:
    """**단계 하나만** 돌린다. 전부 만들기와 같은 표를 쓴다.

    화면이 단계마다 「다시」를 누를 수 있어야 해서 가른 것이다 — 자막 문구를
    하나 고쳤다고 목소리부터 다시 만들 이유가 없다.
    """
    JOB.lines.clear()
    JOB.running, JOB.failed, JOB.ws = True, False, ""
    JOB.kind = "scene"
    JOB.steps = [{"key": k, "label": l} for k, l in SCENE_STEPS if k == step]
    try:
        JOB.step = step
        label = dict(SCENE_STEPS).get(step, step)
        JOB.log(f"[{step}] {label}")
        args = scene_args(opts)[step]
        pr = subprocess.Popen([str(PY)] + args, cwd=str(ROOT),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in pr.stdout:
            JOB.log("    " + line.rstrip())
        if pr.wait() != 0:
            JOB.failed = True
            JOB.log(f"[{step}] 멈췄습니다 — 위 메시지를 확인하세요")
            return
        JOB.ws = opts["task"]
        JOB.step = "done"
    finally:
        JOB.running = False


# ══ 상태 읽기 ═══════════════════════════════════════════════════════════════

BUNDLE_RE = re.compile(r"^bundle[0-9]{2}$")
# 파일 이름에 쓰면 안 되는 글자 — 윈도우가 막는 것 + 제어 문자.
# ★ 정규식 문자 집합에 넣지 않는다. 역슬래시가 닫는 «]» 를 이스케이프해
#   «unterminated character set» 으로 죽는다. 집합 하나로 두면 그 함정이 없다.
_NAME_BAD = set('<>:"/|?*' + chr(92)) | {chr(c) for c in range(32)}


def safe_name(raw: str) -> str:
    r"""파일 이름에서 알맹이만 남긴다.

    보내는 쪽을 믿지 않는다 — 경로가 섞여 오면 묶음 폴더 밖에 쓸 수 있게
    된다. 그래서 폴더 부분을 떼고(`Path.name`) 못 쓰는 글자를 바꾼다.
    """
    got = "".join("_" if c in _NAME_BAD else c for c in Path(raw).name)
    return got.strip().lstrip(".")


AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac")
VIDEO_EXTS = (".webm", ".mp4", ".mov", ".mkv", ".m4v")
_dur_seen: dict[tuple[str, int, int], float] = {}


def media_dur(f: Path) -> float:
    """길이(초). ffprobe 를 부르지만 **파일이 그대로면 다시 안 부른다** —
    화면을 열 때마다 열다섯 번 부르면 그만큼 늦어진다."""
    try:
        st = f.stat()
    except OSError:
        return 0.0
    key = (str(f), int(st.st_mtime), st.st_size)
    if key in _dur_seen:
        return _dur_seen[key]
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(f)],
            capture_output=True, text=True, timeout=20)
        v = float((out.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001 — 길이를 못 재도 목록은 나와야 한다
        v = 0.0
    _dur_seen[key] = v
    return v


def media_in(d: Path, exts: tuple[str, ...]) -> list[dict]:
    r"""폴더 안의 그 종류 파일들. `장면\` 같은 하위 폴더까지 훑는다."""
    if not d.is_dir():
        return []
    got = sorted(x for x in d.rglob("*")
                 if x.is_file() and x.suffix.lower() in exts)
    return [{"name": x.name,
             "rel": str(x.relative_to(d)).replace("\\", "/"),
             "path": str(x),
             "sec": round(media_dur(x), 1),
             "mb": round(x.stat().st_size / 1_048_576, 1)} for x in got]


def scene_rows() -> list[dict]:
    """build/ 안의 씬 작업들 — 씬마다 어디까지 됐는지 그대로 보여 준다."""
    rows: list[dict] = []
    if not BUILD.is_dir():
        return rows
    for d in sorted((p for p in BUILD.iterdir() if p.is_dir()), reverse=True):
        mp = scene_paths(d.name).meta
        if not mp.is_file():
            continue
        try:
            meta = load_json(mp)
        except Exception:  # noqa: BLE001 — 깨진 json 이 목록을 막지 않게
            continue
        # 씬 → 묶음 번호. 씬 목록을 묶음 단위로 색칠하려면 씬마다 «몇 번째
        # 묶음인가» 를 알아야 한다. 묶음을 아직 안 만들었으면 전부 0 이다.
        of_bundle: dict[int, int] = {}
        for i, b in enumerate(meta.get("bundles", []), 1):
            for n in b.get("scenes", []):
                of_bundle[int(n)] = int(b.get("no") or i)
        scenes = []
        for r in meta.get("scenes", []):
            scenes.append({
                "no": r["no"], "title": r.get("title", ""),
                "bundle": of_bundle.get(int(r["no"]), 0),
                "dur": r.get("voice_dur") or r.get("script_dur") or 0,
                "cues": r.get("cues", 0), "over": r.get("cue_over", 0),
                "slide": bool(r.get("slide")),
                "voice": bool(r.get("voice")), "avatar": bool(r.get("avatar")),
                "preview": r.get("preview", ""),
                "voice_engine": r.get("voice_engine", ""),
                "avatar_engine": r.get("avatar_engine", ""),
            })
        # 이어 붙인 파일 이름은 스타일에 따라 all-panel.mp4 처럼 바뀐다.
        # p5 가 scenes.json 에 적어 두지만, 옛 산출을 위해 폴더도 한 번 뒤진다.
        # 이미 만들어 둔 자막 언어. «무엇을 더 만들까» 를 고르는 화면이
        # 무엇이 이미 있는지 모르면, 넣어 둔 원본을 골라 지우게 된다.
        P = scene_paths(d.name)
        have = sorted({x.name.split(".")[-2] for x in P.subs.glob("scene*.*.srt")
                       } if P.subs.is_dir() else set())
        done = sorted({x.name.split(".")[-2] for x in P.aligned.glob("scene*.*.srt")
                       } if P.aligned.is_dir() else set())

        pv = P.preview                            # 09/ — 옛 preview/ 가 아니다
        named = meta.get("all") or ""
        joined = pv / named if named else None
        if joined is None or not joined.is_file():
            found = sorted(pv.glob("all*.mp4")) if pv.is_dir() else []
            joined = found[-1] if found else (pv / "all.mp4")
        rows.append({
            "task": d.name, "path": str(d),
            "sub_lang": meta.get("sub_lang", ""),
            "langs_have": have,                   # 01/subs 에 있는 언어
            "langs_done": done,                   # 03 에 맞춰 둔 언어
            "layout": meta.get("layout", ""),
            "total": meta.get("voice_total_sec") or meta.get("total_sec") or 0,
            "scenes": scenes,
            "all": joined.name if joined.is_file() else "",
            # 묶음 개수 — 화면의 «묶음» 단계가 이 값으로 «아직 안 만들었습니다» 를
            # 판단한다. 없으면 5개가 있어도 안 만든 것으로 나온다.
            "bundles": len(meta.get("bundles", [])),
            "preview_dir": str(pv),
            "src": {"script": meta.get("script", ""), "subs": meta.get("subs", ""),
                    "slides": meta.get("slides", "")},
        })
    return rows


def scene_defaults() -> dict:
    """재료 자리를 찍어 준다 — `_context*` 폴더를 훑어 대본·자막·슬라이드·원본을 찾는다.

    화면에 빈 칸 네 개를 던져 놓고 "경로를 넣으세요" 하면 매번 탐색기를 열어야 한다.
    폴더 구조가 뻔하므로(대본 옆에 그 언어 자막과 원본이 같이 있고, 슬라이드는
    PNG 가 많은 폴더다) 여기서 찍어 주고 사람이 고치게 한다.
    """
    out = {"script": "", "subs": "", "slides": "", "source": ""}
    # `_context*` 는 옛 이름이다. 재료를 한 폴더에 모아 두는 쪽이 편해서
    # `__last-*` · `assets` 도 같이 본다 — 어느 이름으로 두든 찍어 준다.
    roots = sorted({p for pat in ("_context*", "__last-*", "assets")
                    for p in ROOT.glob(pat) if p.is_dir()})
    if not roots:
        return out

    best_slides, best_n = None, 0
    script_dir = None
    for root in roots:
        for d in [root] + [x for x in root.iterdir() if x.is_dir()]:
            pngs = [x for x in d.glob("*.png") if re.match(r"^\d+$", x.stem)]
            if len(pngs) > best_n:
                best_slides, best_n = d, len(pngs)
            if not out["script"]:
                txts = sorted(d.glob("*.txt"))
                if txts:
                    out["script"] = str(txts[0])
                    script_dir = d
    if best_slides:
        out["slides"] = str(best_slides)
    if script_dir:
        srts = sorted(script_dir.glob("*.srt"))
        mp4s = sorted(script_dir.glob("*.mp4"))
        if srts:
            out["subs"] = str(srts[0])
        if mp4s:
            out["source"] = str(mp4s[0])
    return out


LECTURE_DIR = LECTURES
SLIDE_SUBS = ("slides", "슬라이드", "_build/slides")
MATERIAL_SUBS = ("00", "재료", "materials", "src", "input")


def materials_in(d: Path) -> dict:
    r"""폴더 하나 -> 재료 네 자리. **경로를 외우지 않고 찾는다.**

    보내는 쪽마다 이름이 다르다 - 슬라이드를 `slides\` 로 줄지 `슬라이드\` 로 줄지,
    재료를 강의 폴더 바로 아래 둘지 `재료\` 안에 둘지 알 수 없다. 120강이 쌓이는데
    매번 네 칸을 손으로 채우게 하면 그게 곧 일이 된다. scripts/bundle.py 가
    s1~s7 에서 하는 것과 같은 사고다.

        강의\001-emr\                또는   강의\001-emr\재료\
          아무이름.mp4                        아무이름.mp4
          아무이름.srt                        아무이름.srt
          아무이름.txt                        아무이름.txt
          slides\                            slides\

    둘 다 된다. 재료 폴더가 있으면 그쪽을 먼저 본다.
    """
    out = {"script": "", "subs": "", "slides": "", "source": ""}
    if not d.is_dir():
        return out

    # 재료를 담아 둔 하위 폴더가 있으면 그 안을 본다. 없으면 폴더 바로 아래.
    roots = [x for name in MATERIAL_SUBS if (x := d / name).is_dir()] + [d]

    for r in roots:
        txts = sorted(x for x in r.glob("*.txt") if "넣으세요" not in x.name)
        srts = sorted(r.glob("*.srt"))
        mp4s = sorted(x for x in r.glob("*.mp4") if x.stat().st_size > 1_000_000)
        if txts and not out["script"]:
            out["script"] = str(txts[0])
        if srts and not out["subs"]:
            out["subs"] = str(srts[0])
        if mp4s and not out["source"]:
            out["source"] = str(mp4s[0])
        if out["slides"]:
            continue
        for name in SLIDE_SUBS:
            cand = r / name
            if cand.is_dir() and any(cand.glob("*.png")):
                out["slides"] = str(cand)
                break
        if not out["slides"]:
            best, best_n = None, 0
            for x in [r] + [y for y in r.iterdir() if y.is_dir()]:
                n = len([z for z in x.glob("*.png") if re.match(r"^\d+", z.stem)])
                if n > best_n:
                    best, best_n = x, n
            if best is not None:
                out["slides"] = str(best)
    return out


def lecture_rows() -> list[dict]:
    r"""«강의» 목록 — 재료 폴더 하나가 강의 하나다. 120개까지 쌓인다.

    `강의\` 안의 폴더를 보고, 예전 이름(`__last-*`)도 같이 본다. 각 강의가
    어디까지 됐는지는 `build/<작업>/scenes.json` 에서 읽는다 — 재료와 산출을
    갈라 두었으므로 재료 폴더는 건드리지 않는다.
    """
    dirs: list[Path] = []
    if LECTURE_DIR.is_dir():
        dirs += sorted(x for x in LECTURE_DIR.iterdir() if x.is_dir())
    dirs += sorted(x for x in ROOT.glob("__last-*") if x.is_dir())

    rows: list[dict] = []
    for d in dirs:
        m = materials_in(d)
        task = d.name
        mp = scene_paths(task).meta
        meta = None
        if mp.is_file():
            try:
                meta = load_json(mp)
            except Exception:  # noqa: BLE001 — 깨진 json 이 목록을 막지 않게
                meta = None
        sc = (meta or {}).get("scenes", [])
        n_slides = 0
        if m["slides"]:
            n_slides = len([x for x in Path(m["slides"]).glob("*.png")
                            if re.match(r"^\d+", x.stem)])
        rows.append({
            "task": task, "dir": str(d),
            "ready": bool(m["script"] and m["slides"]),
            # ★ **m 을 먼저 펼친다.** 뒤에 두면 m["slides"](경로)가 장수를 덮어
            #   화면에 «슬라이드=D:\…\slides장» 이 찍힌다(2026-09-03 실측).
            **m,
            "slide_count": n_slides,
            # 진행 현황 — 화면 왼쪽 레일의 점과 같은 것을 목록에서도 보여 준다
            "scenes": len(sc),
            "voice": sum(1 for r in sc if r.get("voice")),
            "subs_done": sum(1 for r in sc if r.get("aligned")),
            "bundles": len((meta or {}).get("bundles", [])),
            "avatar": sum(1 for r in sc if r.get("avatar")),
            "preview": sum(1 for r in sc if r.get("preview")),
            "sub_langs": (meta or {}).get("sub_langs", []),
            "total_sec": (meta or {}).get("voice_total_sec")
                         or (meta or {}).get("total_sec") or 0,
            "all": (meta or {}).get("all", ""),
        })
    return rows


def perso_status() -> dict:
    """perso 연결 상태. **안 붙었다** — HeyGen 으로 옮겼다. 자리만 남겨 둔다."""
    try:
        from perso.client import status
        return status()
    except Exception as e:  # noqa: BLE001 — 상태 조회가 화면을 막지 않게
        return {"ok": False, "key": False, "why": f"상태를 읽지 못했습니다: {e}",
                "endpoints": {}, "rates": {}, "credit_usd": 0}


def heygen_status() -> dict:
    """HeyGen 연결 상태. 안 붙었으면 왜 안 붙었는지 그대로 말한다."""
    try:
        from heygen.client import status
        return status()
    except Exception as e:  # noqa: BLE001 — 상태 조회가 화면을 막지 않게
        return {"ok": False, "key": False, "why": f"상태를 읽지 못했습니다: {e}",
                "endpoints": {}, "rates": {}, "rate_now": 0, "engine": "",
                "avatar_id": "", "voice_uz": "", "motion_prompt": "",
                "min_topup_usd": 0}


# 옛 이름 → 번호 폴더. 화면과 API 는 뜻이 있는 이름으로 부르고, 디스크는
# 단계 순서대로 번호를 쓴다 — 어느 쪽도 상대의 규칙을 외우지 않는다.
SUB_NO = {"slides": "01/slides", "subs": "01/subs", "voice": "02",
          "aligned": "03", "upload": "05", "avatar": "07", "preview": "09"}


def scene_dir(task: str, sub: str) -> Path | None:
    """`강의/<task>/<번호>/` — 이름이 수상하면 None. 강의/ 밖은 절대 안 준다."""
    if not task or not re.match(r"^[0-9A-Za-z가-힣_.-]{1,40}$", task):
        return None
    d = (BUILD / task / SUB_NO.get(sub, sub)).resolve()
    if BUILD.resolve() not in d.parents or not d.is_dir():
        return None
    return d


def read_srt_rows(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    return [{"i": i + 1, "text": c.text, "start": round(c.start, 2), "end": round(c.end, 2)}
            for i, c in enumerate(parse_srt(p.read_text(encoding="utf-8-sig")))]


def write_srt_rows(p: Path, rows: list[dict]) -> int:
    """화면에서 고친 자막을 되쓴다. **타임코드는 그대로** — 본문만 바뀐다.

    시각은 p3_resync 가 실제 음성 길이를 재서 정한 값이라, 여기서 건드리면
    소리와 어긋난다. 문구만 고치는 화면인 이유가 이것이다.
    """
    cues = [Cue(text=(r.get("text") or "").strip(),
                start=float(r["start"]), end=float(r["end"]))
            for r in rows if (r.get("text") or "").strip()]
    p.write_text(to_srt(cues), encoding="utf-8")
    return len(cues)


# ══ Claude 연결 ═════════════════════════════════════════════════════════════

def claude_status() -> dict:
    """자막 번역(s3b --translate)에 쓰는 Claude 연결 상태.

    **API 키를 쓰지 않는다.** `claude` CLI 로 로그인해 둔 세션(OAuth)을 그대로
    쓴다 — llm/claude_provider.py 가 환경변수의 ANTHROPIC_API_KEY 를 일부러
    빈 문자열로 덮기 때문이다(오래된 export 가 OAuth 를 가로채 남의 계정에
    과금되는 것을 막는 장치).

    계정 정보는 `claude auth status --json` 이 그대로 준다 — 파일을 뜯어보지
    않는다. CLI 가 답하는 것이 사실이다.
    """
    out = {"ok": False, "cli": False, "login": False, "sdk": False,
           "path": None, "api_key_env": False, "email": "", "org": "",
           "plan": "", "method": "", "why": ""}

    exe = None
    try:
        from llm.claude_provider import status
        st = status()
        out["cli"] = bool(st.get("installed"))
        out["path"] = st.get("path")
        out["api_key_env"] = bool(st.get("api_key_env"))
        exe = st.get("path")
    except Exception as e:  # noqa: BLE001 — 상태 조회가 화면을 막지 않게
        out["why"] = f"상태를 읽지 못했습니다: {e}"
        return out

    if exe:
        try:
            r = subprocess.run([exe, "auth", "status", "--json"],
                               capture_output=True, text=True, timeout=20,
                               encoding="utf-8", errors="replace")
            info = json.loads((r.stdout or "").strip() or "{}")
            out["login"] = bool(info.get("loggedIn"))
            out["email"] = info.get("email") or ""
            out["org"] = info.get("orgName") or ""
            out["plan"] = info.get("subscriptionType") or ""
            out["method"] = info.get("authMethod") or ""
        except Exception:  # noqa: BLE001 — 로그인 안 됐을 때도 여기로 온다
            pass

    try:
        import claude_agent_sdk  # noqa: F401
        out["sdk"] = True
    except ImportError:
        pass

    if not out["cli"]:
        out["why"] = "claude 실행 파일을 찾지 못했습니다"
    elif not out["login"]:
        out["why"] = "로그인이 안 되어 있습니다"
    elif not out["sdk"]:
        out["why"] = "claude-agent-sdk 가 설치되지 않았습니다"
    else:
        out["ok"] = True
        out["why"] = "쓸 수 있습니다"
    return out


# 콘솔 창에서 돌릴 명령. 웹 화면이 로그인을 대신할 수는 없다 — OAuth 는 브라우저와
# CLI 가 주고받는 것이고 중간에서 토큰을 만지면 안 된다. 그래서 **창만 열어 준다.**
CLAUDE_ACTS = {
    "login":  ("auth", "login"),
    "logout": ("auth", "logout"),
    "switch": ("auth", "login"),   # 로그아웃 뒤 로그인 — 아래에서 둘을 잇는다
}


def open_claude_console(act: str) -> bool:
    """로그인·로그아웃할 콘솔 창을 띄운다. 사람이 마치면 '다시 확인'을 누른다."""
    st = claude_status()
    exe = st.get("path")
    if not exe or act not in CLAUDE_ACTS:
        return False
    q = chr(34)
    if act == "switch":
        cmd = f"{q}{exe}{q} auth logout & {q}{exe}{q} auth login"
    else:
        sub = " ".join(CLAUDE_ACTS[act])
        cmd = f"{q}{exe}{q} {sub}"
    # /k 로 창을 남긴다 — 실패했을 때 메시지를 읽을 수 있어야 한다
    subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", cmd])
    return True


# ══ HTTP ════════════════════════════════════════════════════════════════════

class Server(ThreadingHTTPServer):
    """포트를 이미 누가 쓰고 있으면 **조용히 같이 붙지 않고 죽는다.**

    HTTPServer 는 allow_reuse_address 를 켜 두는데, 윈도에서는 그 값이
    "이미 듣고 있는 포트에도 붙어라"로 동작한다. 그래서 서버를 두 번 띄우면
    둘 다 LISTENING 이 되고 요청은 **먼저 뜬 쪽**이 받는다 — 코드를 고치고
    다시 띄웠는데 옛 코드가 답하는 일이 생긴다(2026-09-02 실측). 꺼 둔다.
    """
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    server_version = "ava"

    def log_message(self, fmt, *args) -> None:   # 조용히 — 폴링이 화면을 덮는다
        pass

    # ── 보내기 ──
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = {".html": "text/html; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".mp4": "video/mp4", ".m4a": "audio/mp4",
                 ".png": "image/png", ".jpg": "image/jpeg",
                 ".srt": "text/plain; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8"}.get(path.suffix.lower(),
                                                       "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    # ── GET ──
    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path

        if path == "/" or path == "/index.html":
            return self._file(HERE / "index.html")
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (HERE / "static" / rel).resolve()
            if (HERE / "static").resolve() not in target.parents:
                return self._send(403, b"no", "text/plain")
            return self._file(target)

        if path == "/api/state":
            return self._json({"sceneSteps": [{"key": k, "label": l} for k, l in SCENE_STEPS],
                               "scenes": scene_rows(),
                               "sceneDefaults": scene_defaults(),
                               # 어느 언어가 기본인지도 저장소에 안 남긴다 —
                               # config.local.json 이 정한다.
                               "cfg": local_config()})
        if path == "/api/claude":
            return self._json(claude_status())
        if path == "/api/langs":
            from scripts.langs import SCRIPTS, rows_for_ui
            return self._json({"langs": rows_for_ui(),
                               "scripts": [{"key": k, "label": l} for k, l in SCRIPTS]})
        if path == "/api/perso":
            return self._json(perso_status())
        if path == "/api/heygen":
            return self._json(heygen_status())
        if path == "/api/lectures":
            return self._json({"lectures": lecture_rows(),
                               "dir": str(LECTURE_DIR)})
        if path == "/api/bundles":
            # 묶음 표 — 화면 위쪽 탭이 이걸 읽는다
            name = (q.get("task") or ["lecture01"])[0]
            mp = scene_paths(name).meta
            if not mp.is_file():
                return self._json({"bundles": [], "upload": ""})
            try:
                meta = load_json(mp)
            except Exception:  # noqa: BLE001
                return self._json({"bundles": [], "upload": ""})
            by_no = {int(r["no"]): r for r in meta.get("scenes", [])}
            up = scene_paths(name).upload
            rows = []
            for b in meta.get("bundles", []):
                nos = [int(x) for x in b.get("scenes", [])]
                bdir = up / str(b.get("dir") or f"bundle{int(b['no']):02d}")
                rows.append({
                    **b,
                    "path": str(bdir),
                    # ★ 올릴 것과 받은 것을 **따로** 준다. 이 두 방향이 한 칸에
                    #   섞여 있으면 «지금 내가 보내는 차례인가 받는 차례인가» 를
                    #   화면이 안 알려 준다 — 이 단계에서 사람이 제일 헤맨다.
                    "mp3s": media_in(bdir, AUDIO_EXTS),
                    "vids": media_in(bdir, VIDEO_EXTS),
                    "titles": [str(by_no.get(n, {}).get("title", "")) for n in nos],
                    # 그 묶음 씬들이 아바타를 받았는지 — 진행 현황 표시용
                    "avatar": sum(1 for n in nos if by_no.get(n, {}).get("avatar")),
                    "avatar_scenes": [n for n in nos if by_no.get(n, {}).get("avatar")],
                    "preview": sum(1 for n in nos if by_no.get(n, {}).get("preview")),
                })
            return self._json({"bundles": rows,
                               "upload": str(scene_paths(name).upload),
                               "max_sec": meta.get("bundle_max_sec", 590)})
        if path == "/api/scene-media":
            # 씬 검수본을 브라우저에서 바로 재생하기 위한 자리
            name = (q.get("task") or [""])[0]
            rel = (q.get("rel") or [""])[0]
            if not name or not rel:
                return self._send(404, b"not found", "text/plain")
            base = (BUILD / name).resolve()
            if BUILD.resolve() not in base.parents or not base.is_dir():
                return self._send(404, b"not found", "text/plain")
            # 화면은 뜻이 있는 이름(`preview/…`)으로 부르고 디스크는 번호를 쓴다.
            # 첫 칸만 SUB_NO 로 바꿔 준다 — 옛 링크도 그대로 걸린다.
            head, _, tail = rel.replace("\\", "/").partition("/")
            if tail and head in SUB_NO:
                rel = f"{SUB_NO[head]}/{tail}"
            target = (base / rel).resolve()
            if base not in target.parents and target.parent != base:
                return self._send(403, b"no", "text/plain")
            return self._file(target)
        if path == "/api/log":
            since = int((q.get("since") or ["0"])[0])
            return self._json(JOB.snapshot(since))
        if path == "/api/scene-subs":
            # 4 자막 — build/<task>/aligned/sceneNN.<lang>.srt 를 읽는다
            task = (q.get("task") or [""])[0]
            base = scene_dir(task, "aligned")
            if base is None:
                return self._json({"error": "작업을 찾지 못했습니다"}, 404)
            files = sorted(x.name for x in base.glob("*.srt"))
            name = (q.get("file") or [files[0] if files else ""])[0]
            return self._json({"files": files, "file": name,
                               "cues": read_srt_rows(base / name) if name else []})

        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ── POST ──
    def _take_upload(self, q: dict) -> None:
        r"""받은 영상을 묶음 폴더에 앉힌다 — 본문이 **파일 바이트 그대로**다.

        multipart 를 안 쓴다. 표준 라이브러리로 경계를 파싱하는 코드는 길고
        틀리기 쉽다. 이름은 쿼리로 오고 본문에는 파일만 온다. 브라우저 쪽은
        `xhr.send(file)` 한 줄이고, 올리는 진행률도 그대로 나온다.

        ★ 1MB 씩 끊어 **디스크로 흘려보낸다.** 한 번에 read() 하면 100MB 짜리가
          메모리에 통째로 올라온다. 다 받기 전에는 `.part` 이름으로 두어,
          반쯤 받은 파일을 p4 가 온전한 영상으로 오해하지 않게 한다.
        """
        task = (q.get("task") or [""])[0]
        bdir = (q.get("bundle") or [""])[0]
        fname = (q.get("name") or [""])[0]
        up = scene_dir(task, "upload")
        if up is None:
            return self._json({"error": "그 강의의 05 폴더가 없습니다"}, 404)
        if not BUNDLE_RE.match(bdir):
            return self._json({"error": "묶음 이름이 수상합니다"}, 400)
        safe = safe_name(fname)
        if not safe or Path(safe).suffix.lower() not in VIDEO_EXTS:
            return self._json(
                {"error": "영상 파일만 받습니다 (" + ", ".join(VIDEO_EXTS) + ")"}, 400)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return self._json({"error": "빈 파일입니다"}, 400)
        if n > 4 * 1024 ** 3:
            return self._json({"error": "4GB 를 넘습니다"}, 413)

        dest = up / bdir
        dest.mkdir(parents=True, exist_ok=True)
        tmp = dest / (safe + ".part")
        try:
            left = n
            with tmp.open("wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left > 0:
                tmp.unlink(missing_ok=True)
                return self._json({"error": "받는 중에 끊겼습니다"}, 400)
            tmp.replace(dest / safe)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            return self._json({"error": "쓰지 못했습니다: " + str(e)}, 500)
        got = dest / safe
        return self._json({"ok": True, "name": safe, "path": str(got),
                           "sec": round(media_dur(got), 1),
                           "mb": round(n / 1_048_576, 1)})

    def do_POST(self) -> None:
        u = urlparse(self.path)
        path = u.path

        # ★ 파일 올리기가 맨 앞이다. 아래 _body() 는 본문을 JSON 으로 통째
        #   읽으므로, 영상이 오면 100MB 를 메모리에 담아 놓고 버린다.
        if path == "/api/bundle-drop":
            return self._take_upload(parse_qs(u.query))

        body = self._body()

        if path == "/api/heygen-key":
            # 키는 파일(heygen.local.json)에만 넣는다. 되돌려 주는 건 status() 뿐이라
            # 화면에 키 자체가 다시 실려 나가지 않는다.
            try:
                from heygen.client import save_conf
                st = save_conf(api_key=body.get("api_key") or "",
                               avatar_id=body.get("avatar_id") or "",
                               voice_uz=body.get("voice_uz") or "",
                               engine=body.get("engine") or "",
                               motion_prompt=body.get("motion_prompt") or "")
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"저장하지 못했습니다: {e}"}, 500)
            return self._json({"ok": True, "status": st})

        if path == "/api/perso-key":
            # 키는 파일에만 넣는다. 되돌려 주는 건 status() 뿐이라 화면에
            # 키 자체가 다시 실려 나가지 않는다.
            try:
                from perso.client import save_conf
                st = save_conf(api_key=body.get("api_key") or "",
                               base_url=body.get("base_url") or "",
                               voice_uz=body.get("voice_uz") or "",
                               avatar_id=body.get("avatar_id") or "")
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"저장하지 못했습니다: {e}"}, 500)
            return self._json({"ok": True, "status": st})

        if path in ("/api/scene-run", "/api/scene-step"):
            if JOB.running:
                return self._json({"error": "이미 돌고 있습니다"}, 409)
            step = body.get("step") or ""
            if path.endswith("scene-step") and step not in dict(SCENE_STEPS):
                return self._json({"error": f"그런 단계는 없습니다: {step}"}, 400)

            cfg = local_config()
            opts = {
                "task": (body.get("task") or "lecture01").strip(),
                "scenes": body.get("scenes") or "1-8",
                "style": body.get("style") or "full",
                "voice_engine": body.get("voice_engine") or "source",
                "avatar_engine": body.get("avatar_engine") or "stub",
                # drop = HeyGen 웹에서 렌더해 내려받은 영상이 있는 폴더
                "avatar_src": body.get("avatar_src") or "",
                "bundle_max_sec": body.get("bundle_max_sec") or "590",
                "bundle_pack": ("fill" if body.get("bundle_pack") == "fill" else "even"),
                "script": body.get("script") or "",
                "subs": body.get("subs") or "",
                "slides": body.get("slides") or "",
                "source": body.get("source") or "",
                "sub_lang": body.get("sub_lang") or cfg["sub_lang"],
                "script_lang": body.get("script_lang") or cfg["audio_lang"],
                "retranslate": bool(body.get("retranslate")),
                "subs_mode": body.get("subs_mode") or "burn",
                "avatar_h": body.get("avatar_h") or "0.85",
                "avatar_vary": body.get("avatar_vary") or "40",
                "avatar_rotate": body.get("avatar_rotate") or "0",
                "slide_fit": body.get("slide_fit") or "contain",
            }
            if not re.match(r"^[0-9A-Za-z가-힣_.-]{1,40}$", opts["task"]):
                return self._json({"error": "작업 이름에 쓸 수 없는 글자가 있습니다"}, 400)
            if opts["style"] not in ("full", "panel", "both"):
                return self._json({"error": "스타일은 전면샷·여백형·둘 다 중 하나입니다"}, 400)
            try:
                av = float(opts["avatar_h"])
                if not 0.2 <= av <= 1.0:
                    raise ValueError
            except ValueError:
                return self._json({"error": "아바타 크기는 0.2~1.0 사이 숫자여야 합니다"}, 400)

            # 재료는 p1 을 도는 경우에만 있어야 한다 — 자막만 다시 맞출 때까지
            # 대본 경로를 물으면 화면이 쓸데없이 막힌다.
            if step in ("", "p1"):
                # 자막 srt 는 **선택**이다 — 없으면 p2b 가 대본에서 만든다.
                for k in ("script", "slides"):
                    if not opts[k] or not Path(opts[k]).exists():
                        return self._json(
                            {"error": f"{k} 자리를 찾지 못했습니다: {opts[k] or '(비어 있음)'}"}, 400)
                if opts["subs"] and not Path(opts["subs"]).exists():
                    return self._json(
                        {"error": f"자막 파일이 없습니다: {opts['subs']}"}, 400)
            if step in ("", "p2") and opts["voice_engine"] == "source"                     and not Path(opts["source"]).is_file():
                return self._json(
                    {"error": f"목소리를 떼어 올 원본이 없습니다: {opts['source'] or '(비어 있음)'}"}, 400)
            # ★ avatar_src 는 **비워 두는 것이 기본**이다 — 그러면 p4 가 묶음 폴더
            #   (05/bundleNN/)를 본다. 거기서 mp3 를 꺼내 올렸으니 내려받은 영상도
            #   거기 되돌려 놓는 것이 자연스럽다. 다운로드 폴더에서 바로 읽고 싶을
            #   때만 채운다. 그래서 «비어 있음» 을 오류로 보지 않는다.
            if step in ("", "p4") and opts["avatar_engine"] == "drop"                     and opts["avatar_src"] and not Path(opts["avatar_src"]).exists():
                return self._json(
                    {"error": f"그 폴더를 찾지 못했습니다: {opts['avatar_src']}"}, 400)

            target = (lambda: run_one_step(step, opts)) if step else (lambda: run_scene_pipeline(opts))
            threading.Thread(target=target, daemon=True).start()
            time.sleep(0.2)
            return self._json({"ok": True})

        if path == "/api/scene-subs":
            # 문구만 고친다. 타임코드는 손대지 않는다 — 시각은 p3 가 정한다.
            base = scene_dir(body.get("task") or "", "aligned")
            name = body.get("file") or ""
            if base is None or not name.endswith(".srt") or "/" in name or "\\" in name:
                return self._json({"error": "자막 파일을 찾지 못했습니다"}, 404)
            n = write_srt_rows(base / name, body.get("cues") or [])
            return self._json({"ok": True, "saved": n})

        if path == "/api/claude-act":
            act = body.get("act") or ""
            if not open_claude_console(act):
                return self._json({"error": "그 동작을 할 수 없습니다 "
                                            "(claude 실행 파일을 찾지 못했을 수 있습니다)"}, 400)
            return self._json({"ok": True})

        if path == "/api/bundle-drop-del":
            # 잘못 넣은 것을 화면에서 뺀다. 묶음 폴더 안의 영상만 지운다 —
            # 올릴음성.mp3 나 자막은 이 길로 못 지운다.
            name = body.get("task") or ""
            bdir = body.get("bundle") or ""
            fname = Path(str(body.get("name") or "")).name
            up = scene_dir(name, "upload")
            if up is None or not BUNDLE_RE.match(bdir):
                return self._json({"error": "자리를 찾지 못했습니다"}, 404)
            f = (up / bdir / fname).resolve()
            if ((up / bdir).resolve() != f.parent
                    or f.suffix.lower() not in VIDEO_EXTS or not f.is_file()):
                return self._json({"error": "그 자리의 영상이 아닙니다"}, 400)
            f.unlink()
            return self._json({"ok": True})

        if path == "/api/open":
            target = Path(body.get("path") or "")
            if not target.exists():
                return self._json({"error": "그 자리에 아무것도 없습니다"}, 404)
            subprocess.Popen(["explorer", str(target)])
            return self._json({"ok": True})

        return self._json({"error": "그런 자리는 없습니다"}, 404)


def main() -> None:
    # .venv 가 없어도 연다 — 씬 만들기(p1~p5)는 표준 라이브러리와 ffmpeg 만 쓴다.
    # s1~s7(전사)은 faster-whisper 가 있어야 하므로 그때는 안내만 남긴다.
    if not _VENV.is_file():
        print("  .venv 가 없어 지금 이 파이썬으로 돕니다 — 씬 만들기는 그대로 됩니다.")
        print("  전사(s1~s7)까지 쓰려면 setup.bat 을 돌리세요.")
    try:
        srv = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        raise SystemExit(
            f"{PORT} 번을 이미 누가 쓰고 있습니다 — 먼저 뜬 창을 닫고 다시 여세요.")
    print("=" * 60)
    print("  Avatar Lecture  —  http://127.0.0.1:%d" % PORT)
    print("=" * 60)
    print("  창을 닫거나 Ctrl+C 를 누르면 꺼집니다.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n껐습니다.")


if __name__ == "__main__":
    main()
