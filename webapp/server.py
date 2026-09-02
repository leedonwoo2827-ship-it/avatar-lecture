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
from scripts.common import ROOT, load_json, local_config
from scripts.cues import parse_srt, to_srt, Cue

PORT = 6326
HERE = Path(__file__).resolve().parent
# .venv 가 있으면 그것을, 없으면 지금 돌고 있는 파이썬을 쓴다.
# 씬 만들기(p1~p5)는 표준 라이브러리와 ffmpeg 만 쓰므로 setup.bat 없이도 돈다 —
# 화면부터 보고 나서 무거운 설치를 하려는 사람을 막지 않으려는 것이다.
# s1~s7 은 faster-whisper 가 필요하니 그때는 .venv 가 있어야 한다.
_VENV = ROOT / ".venv" / "Scripts" / "python.exe"
PY = _VENV if _VENV.is_file() else Path(sys.executable)
BUILD = ROOT / "build"

# ══ 순서 ═══════════════════════════════════════════════════════════════════
# 화면의 번호와 같은 순서다. 자막(p3)이 목소리(p2) 뒤에 오는 것은 자막 타임코드를
# **실제 합성된 음성 길이에 맞춰** 다시 재기 때문이다 — 목소리가 없으면 못 돈다.
SCENE_STEPS = [
    ("p1",  "씬 떼기"),
    ("p2",  "목소리"),
    ("p2b", "다국어 자막"),
    ("p3",  "자막 맞추기"),
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
        "p4": ["scripts/p4_avatar.py", "--task", task, "--engine", o["avatar_engine"]],
        "p5": ["scripts/p5_compose.py", "--task", task, "--style", o["style"],
               "--subs", o["subs_mode"], "--avatar-h", str(o["avatar_h"]),
               "--slide-fit", o["slide_fit"], "--join"],
    }


def run_scene_pipeline(opts: dict) -> None:
    """전부 만들기 — p1~p5 를 순서대로 돌린다.

    perso 가 아직 안 붙어 있으므로 기본은 **크레딧을 안 쓰는 엔진**이다:
    목소리는 시연본에서 떼어 오고(source), 아바타는 임시 아바타(stub)를 놓는다.
    화면과 배치를 다 확인한 뒤 키를 발급하고 engine 만 perso 로 바꾸면 된다.
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

def scene_rows() -> list[dict]:
    """build/ 안의 씬 작업들 — 씬마다 어디까지 됐는지 그대로 보여 준다."""
    rows: list[dict] = []
    if not BUILD.is_dir():
        return rows
    for d in sorted((p for p in BUILD.iterdir() if p.is_dir()), reverse=True):
        mp = d / "scenes.json"
        if not mp.is_file():
            continue
        try:
            meta = load_json(mp)
        except Exception:  # noqa: BLE001 — 깨진 json 이 목록을 막지 않게
            continue
        scenes = []
        for r in meta.get("scenes", []):
            scenes.append({
                "no": r["no"], "title": r.get("title", ""),
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
        named = meta.get("all") or ""
        joined = d / "preview" / named if named else None
        if joined is None or not joined.is_file():
            found = sorted((d / "preview").glob("all*.mp4")) if (d / "preview").is_dir() else []
            joined = found[-1] if found else (d / "preview" / "all.mp4")
        rows.append({
            "task": d.name, "path": str(d),
            "sub_lang": meta.get("sub_lang", ""),
            "layout": meta.get("layout", ""),
            "total": meta.get("voice_total_sec") or meta.get("total_sec") or 0,
            "scenes": scenes,
            "all": joined.name if joined.is_file() else "",
            "preview_dir": str(d / "preview"),
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
    roots = sorted(p for p in ROOT.glob("_context*") if p.is_dir())
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


def perso_status() -> dict:
    """perso 연결 상태. 아직 안 붙었으면 왜 안 붙었는지 그대로 말한다."""
    try:
        from perso.client import status
        return status()
    except Exception as e:  # noqa: BLE001 — 상태 조회가 화면을 막지 않게
        return {"ok": False, "key": False, "why": f"상태를 읽지 못했습니다: {e}",
                "endpoints": {}, "rates": {}, "credit_usd": 0}


def scene_dir(task: str, sub: str) -> Path | None:
    """`build/<task>/<sub>/` — 이름이 수상하면 None. build/ 밖은 절대 안 준다."""
    if not task or not re.match(r"^[0-9A-Za-z가-힣_.-]{1,40}$", task):
        return None
    d = (BUILD / task / sub).resolve()
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
        if path == "/api/scene-media":
            # 씬 검수본을 브라우저에서 바로 재생하기 위한 자리
            name = (q.get("task") or [""])[0]
            rel = (q.get("rel") or [""])[0]
            if not name or not rel:
                return self._send(404, b"not found", "text/plain")
            base = (BUILD / name).resolve()
            if BUILD.resolve() not in base.parents or not base.is_dir():
                return self._send(404, b"not found", "text/plain")
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
    def do_POST(self) -> None:
        u = urlparse(self.path)
        path, body = u.path, self._body()

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
                "style": body.get("style") or "panel",
                "voice_engine": body.get("voice_engine") or "source",
                "avatar_engine": body.get("avatar_engine") or "stub",
                "script": body.get("script") or "",
                "subs": body.get("subs") or "",
                "slides": body.get("slides") or "",
                "source": body.get("source") or "",
                "sub_lang": body.get("sub_lang") or cfg["sub_lang"],
                "script_lang": body.get("script_lang") or cfg["audio_lang"],
                "retranslate": bool(body.get("retranslate")),
                "subs_mode": body.get("subs_mode") or "burn",
                "avatar_h": body.get("avatar_h") or "0.80",
                "slide_fit": body.get("slide_fit") or "contain",
            }
            if not re.match(r"^[0-9A-Za-z가-힣_.-]{1,40}$", opts["task"]):
                return self._json({"error": "작업 이름에 쓸 수 없는 글자가 있습니다"}, 400)
            if opts["style"] not in ("full", "panel"):
                return self._json({"error": "스타일은 전면샷·여백형 둘뿐입니다"}, 400)
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
