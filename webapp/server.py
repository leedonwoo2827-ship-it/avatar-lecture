# -*- coding: utf-8 -*-
r"""웹 화면 — 브라우저에서 파이프라인을 돌리고 결과를 본다.

    web.bat  →  http://127.0.0.1:6326

외부 패키지를 쓰지 않는다(파이썬 표준 라이브러리만). 화면은 webapp/index.html
하나에 들어 있어 디자인을 고치려면 그 파일만 건드리면 된다.

perso 쪽 스펙이 아직 미확인이라, **perso에 안 걸리는 부분만** 담았다 —
번들 고르기 · 진행 보기 · 자막 다듬기 · 컷 옮기기 · 결과 열기. 업로드나 아바타
선택은 perso 화면을 본 뒤에 붙인다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.bundle import scan
from scripts.common import ROOT, load_json, local_config, mmss, save_json
from scripts.cues import parse_srt, to_srt, Cue

PORT = 6326
HERE = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
MATERIAL = ROOT / "재료"
OUTPUT = ROOT / "output"

# 파이프라인 단계 — 화면의 진행 표시와 순서가 같다.
# ★ s3b(자막 번역)는 **자막 언어가 음성 언어와 다를 때만** 돈다. 같으면 건너뛴다.
STEPS = [
    ("s1", "영상 받기"),
    ("s2", "전사"),
    ("s3", "자막 만들기"),
    ("s3b", "자막 번역"),
    ("s4", "perso 분할"),
    ("s5", "씬 매핑"),
    ("s6", "패키지"),
    ("s7", "검수본"),
]
# 오른쪽 서랍의 막대 — 워크스페이스 폴더만 보고 판단할 수 있는 단계들.
# s3b 는 자막 언어를 알아야 판단이 되므로 여기 넣지 않는다.
DOT_STEPS = [(k, l) for k, l in STEPS if k != "s3b"]

# 단계가 끝났는지 판단할 자리 — 워크스페이스 안의 이 파일이 있으면 끝난 것으로 본다
DONE_MARK = {
    "s1": "01/audio.m4a", "s2": "02/words.json", "s3": "03",
    "s4": "04/chunks.json", "s5": "05/scenes.json", "s6": "06/perso", "s7": "06/_preview",
}


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
        self._lock = threading.Lock()

    def log(self, line: str) -> None:
        with self._lock:
            self.lines.append(line.rstrip())

    def snapshot(self, since: int) -> dict:
        with self._lock:
            return {"lines": self.lines[since:], "total": len(self.lines),
                    "step": self.step, "running": self.running,
                    "failed": self.failed, "ws": self.ws,
                    "lang": self.lang, "sub_lang": self.sub_lang}


JOB = Job()


def latest_ws() -> Path | None:
    if not OUTPUT.is_dir():
        return None
    dirs = sorted((p for p in OUTPUT.iterdir() if p.is_dir()), key=lambda p: p.name)
    return dirs[-1] if dirs else None


def run_pipeline(bundle: str, lang: str, sub_lang: str, model: str) -> None:
    """백그라운드 스레드에서 순서대로 돌리고 로그를 JOB 에 쌓는다.

    `lang` 은 **음성** 언어(전사할 언어), `sub_lang` 은 **자막** 언어다. 둘이
    다르면 s3b 가 s3 의 자막을 번역해 같은 타임코드에 얹는다 — 대본 단계에서
    만든 자막을 쓰면 실제 음성과 어긋나기 때문이다.
    """
    JOB.lines.clear()
    JOB.running, JOB.failed, JOB.ws = True, False, ""
    JOB.lang, JOB.sub_lang = lang, sub_lang
    translate = sub_lang != lang
    args_for = {
        "s1": ["scripts/s1_ingest.py", bundle],
        "s2": ["scripts/s2_transcribe.py", "--lang", lang, "--model", model],
        "s3": ["scripts/s3_cue.py", "--lang", lang],
        "s3b": ["scripts/s3b_relabel.py", "--translate", "--from", lang, "--to", sub_lang],
        "s4": ["scripts/s4_split.py", "--lang", lang],
        "s5": ["scripts/s5_scene_map.py"],
        "s6": ["scripts/s6_package.py", "--sub-lang", sub_lang],
        "s7": ["scripts/s7_preview.py", "--sub-lang", sub_lang, "--limit", "60"],
    }
    try:
        for key, label in STEPS:
            JOB.step = key
            if key == "s3b" and not translate:
                JOB.log(f"[{key}] {label} — 음성과 자막이 같은 언어라 건너뜁니다")
                continue
            JOB.log(f"[{key}] {label}")
            p = subprocess.Popen([str(PY)] + args_for[key], cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace",
                                 bufsize=1)
            for line in p.stdout:
                JOB.log("    " + line.rstrip())
            if p.wait() != 0:
                JOB.failed = True
                JOB.log(f"[{key}] 멈췄습니다 — 위 메시지를 확인하세요")
                return
            ws = latest_ws()
            if ws:
                JOB.ws = ws.name
        JOB.step = "check"
        JOB.log("[검사] 규칙을 지켰는지 확인")
        p = subprocess.run([str(PY), "scripts/check.py", "--sub-lang", sub_lang],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        for line in (p.stdout or "").splitlines():
            JOB.log("    " + line)
        JOB.step = "done"
    finally:
        JOB.running = False


# ══ 상태 읽기 ═══════════════════════════════════════════════════════════════

def bundle_rows() -> list[dict]:
    """재료/ 안의 강의 후보들."""
    rows = []
    if not MATERIAL.is_dir():
        return rows
    for d in sorted(p for p in MATERIAL.iterdir() if p.is_dir()):
        b = scan(d)
        rows.append({
            "name": d.name, "path": str(d),
            "video": b.video.name if b.video else "",
            "slides": b.n_slides,
            "script": bool(b.script),
            "subs": [p.name for p in b.subs],
            "problems": b.problems,
        })
    return rows


def job_rows() -> list[dict]:
    """지난 작업들 — 단계마다 끝났는지 표시한다."""
    rows = []
    if not OUTPUT.is_dir():
        return rows
    for d in sorted((p for p in OUTPUT.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        meta = {}
        mp = d / "01" / "media.json"
        if mp.is_file():
            try:
                meta = load_json(mp)
            except Exception:  # noqa: BLE001 — 깨진 json 이 목록을 막지 않게
                meta = {}
        steps = {k: (d / v).exists() for k, v in DONE_MARK.items()}
        chunks = []
        cp = d / "04" / "chunks.json"
        if cp.is_file():
            try:
                chunks = [{"no": r["no"],
                           "len": round(float(r["end_sec"]) - float(r["start_sec"]), 1),
                           "start": float(r["start_sec"]), "end": float(r["end_sec"])}
                          for r in load_json(cp)]
            except Exception:  # noqa: BLE001
                chunks = []
        rows.append({
            "name": d.name, "path": str(d),
            "source": meta.get("source", ""),
            "duration": meta.get("duration", 0),
            "slides": meta.get("slides", 0),
            "steps": steps, "chunks": chunks,
            "perso": str(d / "06" / "perso"),
            "preview": str(d / "06" / "_preview"),
        })
    return rows


def sub_files(ws: Path) -> list[str]:
    d = ws / "03"
    return sorted(p.name for p in d.glob("subs.*.srt")) if d.is_dir() else []


def read_cues(ws: Path, name: str) -> list[dict]:
    p = ws / "03" / name
    if not p.is_file():
        return []
    return [{"i": i + 1, "text": c.text, "start": round(c.start, 2), "end": round(c.end, 2)}
            for i, c in enumerate(parse_srt(p.read_text(encoding="utf-8-sig")))]


def write_cues(ws: Path, name: str, rows: list[dict]) -> int:
    """화면에서 고친 자막을 SRT로 되쓴다. 타임코드는 손대지 않는다 —
    본문만 고치는 화면이라 시간이 밀릴 이유가 없다."""
    cues = [Cue(text=(r.get("text") or "").strip(),
                start=float(r["start"]), end=float(r["end"]))
            for r in rows if (r.get("text") or "").strip()]
    (ws / "03" / name).write_text(to_srt(cues), encoding="utf-8")
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

class Handler(BaseHTTPRequestHandler):
    server_version = "mp42perso"

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

    def _ws(self, q: dict) -> Path | None:
        """?ws=폴더이름 → 워크스페이스 경로. output/ 밖은 절대 안 준다."""
        name = (q.get("ws") or [""])[0]
        if not name:
            return None
        p = (OUTPUT / name).resolve()
        if OUTPUT.resolve() not in p.parents or not p.is_dir():
            return None
        return p

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
            return self._json({"bundles": bundle_rows(), "jobs": job_rows(),
                               "steps": [{"key": k, "label": l} for k, l in STEPS],
                               "dotSteps": [{"key": k, "label": l} for k, l in DOT_STEPS],
                               # 어느 언어가 기본인지도 저장소에 안 남긴다 —
                               # config.local.json 이 정한다.
                               "cfg": local_config()})
        if path == "/api/claude":
            return self._json(claude_status())
        if path == "/api/log":
            since = int((q.get("since") or ["0"])[0])
            return self._json(JOB.snapshot(since))
        if path == "/api/subs":
            ws = self._ws(q)
            if ws is None:
                return self._json({"error": "워크스페이스를 찾지 못했습니다"}, 404)
            files = sub_files(ws)
            name = (q.get("file") or [files[0] if files else ""])[0]
            return self._json({"files": files, "file": name,
                               "cues": read_cues(ws, name) if name else []})
        if path == "/api/media":
            # 검수본·오디오를 브라우저에서 바로 재생하기 위한 자리
            ws = self._ws(q)
            rel = (q.get("rel") or [""])[0]
            if ws is None or not rel:
                return self._send(404, b"not found", "text/plain")
            target = (ws / rel).resolve()
            if ws.resolve() not in target.parents and target.parent != ws.resolve():
                return self._send(403, b"no", "text/plain")
            return self._file(target)

        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ── POST ──
    def do_POST(self) -> None:
        u = urlparse(self.path)
        path, body = u.path, self._body()

        if path == "/api/run":
            if JOB.running:
                return self._json({"error": "이미 돌고 있습니다"}, 409)
            bundle = body.get("bundle") or ""
            if not bundle or not Path(bundle).is_dir():
                return self._json({"error": "번들 폴더를 고르세요"}, 400)
            cfg = local_config()
            lang = body.get("lang") or cfg["audio_lang"]
            sub_lang = body.get("sub_lang") or lang
            model = body.get("model") or "small"
            threading.Thread(target=run_pipeline,
                             args=(bundle, lang, sub_lang, model),
                             daemon=True).start()
            time.sleep(0.2)
            return self._json({"ok": True})

        if path == "/api/subs":
            ws = (OUTPUT / (body.get("ws") or "")).resolve()
            if OUTPUT.resolve() not in ws.parents or not ws.is_dir():
                return self._json({"error": "워크스페이스를 찾지 못했습니다"}, 404)
            name = body.get("file") or ""
            if not name.startswith("subs.") or not name.endswith(".srt"):
                return self._json({"error": "자막 파일 이름이 아닙니다"}, 400)
            n = write_cues(ws, name, body.get("cues") or [])
            return self._json({"ok": True, "saved": n})

        if path == "/api/chunks":
            ws = (OUTPUT / (body.get("ws") or "")).resolve()
            if OUTPUT.resolve() not in ws.parents or not ws.is_dir():
                return self._json({"error": "워크스페이스를 찾지 못했습니다"}, 404)
            rows = []
            for r in body.get("chunks") or []:
                rows.append({"no": int(r["no"]),
                             "start_sec": round(float(r["start"]), 2),
                             "end_sec": round(float(r["end"]), 2),
                             "cue_from": int(r.get("cue_from", 0)),
                             "cue_to": int(r.get("cue_to", 0))})
            save_json(ws / "04" / "chunks.json", rows)
            return self._json({"ok": True, "saved": len(rows)})

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
    if not PY.is_file():
        raise SystemExit("setup.bat 을 먼저 돌리세요 (.venv 가 없습니다).")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 60)
    print("  mp42perso  —  http://127.0.0.1:%d" % PORT)
    print("=" * 60)
    print("  창을 닫거나 Ctrl+C 를 누르면 꺼집니다.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n껐습니다.")


if __name__ == "__main__":
    main()
