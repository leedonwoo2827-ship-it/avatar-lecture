# -*- coding: utf-8 -*-
"""HeyGen 플랫폼 — **붙었다.**

옛 업체 클라이언트는 엔드포인트를 몰라 껍데기로 두었다가 지웠다.
HeyGen 은 문서가 다 있어서 이 파일은 **추측 없이** 채워져 있다. 아래 ENDPOINTS 는
전부 developers.heygen.com 에서 읽은 실제 경로다.

함수 모양을 셋으로 좁혀 뒀다 — `status()` · `tts()` · `avatar()` —
webapp 이 그 모양을 읽어 가고, 나중에 업체를 갈아탈 때 부르는 쪽을 안 고치려는 것이다.

★ 표준 라이브러리만 쓴다(urllib). 나머지 파이프라인이 그렇듯 pip 의존을 늘리지
  않는다. multipart 경계는 직접 만든다 — requests 를 끌어오지 않으려는 것이다.

★ **돈이 나가는 파일이다.** 그래서 세 가지를 지킨다:
    1. 씬마다 `Idempotency-Key` 를 붙인다 — 타임아웃 재시도가 두 번 과금되지 않게
    2. `estimate()` 로 부르기 전에 예상액을 낸다 (호출 0회)
    3. 429 는 `Retry-After` 를 지킨다 — 두들겨서 잡을 늘리지 않는다

설정은 `heygen.local.json`(.gitignore 에 이미 있다):

    {"api_key": "...", "avatar_id": "<look id>", "voice_uz": "<voice_id>",
     "engine": "avatar_v", "motion_prompt": "..."}
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "heygen.local.json"

BASE = "https://api.heygen.com"

# ── 실제 경로 (문서에서 읽은 값. 추측 아님) ─────────────────────────────────────
ENDPOINTS: dict[str, str] = {
    "assets":     "/v3/assets",            # POST multipart, 필드명 file, ≤32MB
    "avatars":    "/v3/avatars",           # GET  그룹 목록 · POST 아바타 생성
    "looks":      "/v3/avatars/looks",     # GET  look 목록 ← look.id 가 avatar_id
    "voices":     "/v3/voices",            # GET  보이스 목록
    "videos":     "/v3/videos",            # POST 영상 만들기
    "video":      "/v3/videos/{id}",       # GET  상태 · video_url
    "speech":     "/v3/speech",            # POST TTS (script → 오디오)
}

# ── 요금 (1080p, 초당 USD) ───────────────────────────────────────────────────
# ★ 공개 요금표에서 읽은 값이고, 헬프센터의 "$1 = 1분(standard)" 표기와 어긋난다.
#   어느 라인이 걸리는지는 **1씬 실측 후 Billing → Transactions 차감액으로만**
#   확정된다. 그래서 estimate() 는 «예상»이라고만 말하고 장부에 쓰지 않는다.
RATE_USD_PER_SEC = {
    "avatar_iii": 0.0167,   # Digital Twin 라인 — 가장 싸다 ($1.00/분)
    "avatar_iv":  0.0500,   # Photo Avatar     ($3.00/분)
    "avatar_v":   0.0667,   # 최고 화질·제스처 ($4.00/분)
}
MIN_TOPUP_USD = 5.0

# ── HeyGen 한도 (문서 «Usage Limits») ────────────────────────────────────────
AUDIO_MAX_SEC = 600          # 오디오 입력 상한 10분
ASSET_MAX_BYTES = 32 * 1024 * 1024
VIDEO_MAX_SEC = 30 * 60
MOTION_PROMPT_MAX_SEC = 10   # 커스텀 모션이 실제로 걸리는 구간


class NotConfigured(RuntimeError):
    """키나 아바타가 아직 안 정해졌다. 무엇을 해야 하는지 메시지에 담는다."""


class ApiError(RuntimeError):
    """HeyGen 이 거절했다. 본문을 그대로 담는다 — 우리가 요약하면 원인이 흐려진다."""

    def __init__(self, status: int, body: str, where: str) -> None:
        self.status, self.body, self.where = status, body, where
        super().__init__(f"{where} — HTTP {status}: {body[:500]}")


# ══ 설정 ═══════════════════════════════════════════════════════════════════

def load_conf() -> dict:
    """`heygen.local.json` → 설정. 없으면 환경변수만 본다."""
    conf: dict = {}
    if CONF.is_file():
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001 — 설정이 깨져도 도구는 돌아야 한다
            conf = {}
    if not conf.get("api_key"):
        conf["api_key"] = os.environ.get("HEYGEN_API_KEY", "")
    conf.setdefault("engine", "avatar_v")
    return conf


FIELDS = ("api_key", "avatar_id", "voice_uz", "engine", "motion_prompt")


def save_conf(**kw: str) -> dict:
    """화면·CLI 에서 받은 값을 넣는다.

    **빈 값으로 온 항목은 덮지 않는다** — 키만 고치려고 저장했다가 아바타 id 를
    지워 버리는 사고를 막는다. 지우려면 파일을 고친다.
    """
    conf = {}
    if CONF.is_file():
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            conf = {}
    for k in FIELDS:
        v = str(kw.get(k) or "").strip()
        if v:
            conf[k] = v
    CONF.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
    return status()


def status() -> dict:
    """화면이 읽어 갈 연결 상태. **여기서 거짓말하지 않는다.**

    ok 는 «호출해도 된다» 는 뜻이다 — 키와 아바타 둘 다 있어야 참이다.
    키만 있고 아바타가 없으면 그 사실을 그대로 말한다(그 상태로 p4 를 부르면
    무엇을 립싱크시킬지 모른다).
    """
    conf = load_conf()
    key, av = bool(conf.get("api_key")), bool(conf.get("avatar_id"))
    if key and av:
        why = "API 로 부를 수 있습니다"
    elif not key:
        # ★ 이것은 **오류가 아니다.** 웹 드래그드랍으로 가는 길에는 키가 필요 없다.
        #   화면이 붉게 경고하면 «뭘 잘못했나» 하고 멈춘다 — 그래서 그냥 사실만 적는다.
        why = ("키가 없습니다. 웹 드래그드랍으로 가는 길에는 필요 없습니다 — "
               "여러 편을 자동으로 돌릴 때만 넣으세요")
    else:
        why = ("키는 있고 아바타를 안 골랐습니다 — heygen.cli avatars 로 look id 를 "
               "찾아 넣으세요 (조회는 무료입니다)")
    eng = conf.get("engine", "avatar_v")
    return {
        "ok": key and av, "key": key, "conf": CONF.is_file(),
        "endpoints": {k: bool(v) for k, v in ENDPOINTS.items()},
        "why": why,
        "avatar_id": conf.get("avatar_id", ""),
        "voice_uz": conf.get("voice_uz", ""),
        "engine": eng,
        "motion_prompt": conf.get("motion_prompt", ""),
        # 화면에 그대로 보여 줄 요금. 우리가 계산한 값이 아니라 «읽은 값»이다.
        "rates": {k: {"n": v, "unit": "USD / 초 (1080p)"}
                  for k, v in RATE_USD_PER_SEC.items()},
        "rate_now": RATE_USD_PER_SEC.get(eng, 0.0),
        "min_topup_usd": MIN_TOPUP_USD,
    }


def _guard(what: str) -> dict:
    st = status()
    if not st["ok"]:
        raise NotConfigured(f"{what} — {st['why']}")
    return load_conf()


def estimate(seconds: float, engine: str = "") -> dict:
    """호출 0회. 초 수 × 단가. **«예상»이라고만 말한다.**"""
    eng = engine or load_conf().get("engine", "avatar_v")
    rate = RATE_USD_PER_SEC.get(eng, 0.0)
    return {"engine": eng, "seconds": round(seconds, 3),
            "rate": rate, "usd": round(seconds * rate, 2)}


# ══ 통신 ═══════════════════════════════════════════════════════════════════

def _headers(conf: dict, idem: str = "") -> dict[str, str]:
    h = {"X-Api-Key": conf["api_key"], "Accept": "application/json"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def _open(req: urllib.request.Request, *, where: str, tries: int = 4) -> bytes:
    """429·5xx 만 다시 던진다. 4xx 는 즉시 죽는다 — 두들겨서 나아지지 않는다."""
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = (e.read() or b"").decode("utf-8", "replace")
            if e.code == 429:
                wait = float(e.headers.get("Retry-After") or (2 ** n))
                print(f"    잡이 꽉 찼습니다(429) — {wait:.0f}초 뒤 다시 시도")
                time.sleep(min(wait, 60))
                last = ApiError(e.code, body, where)
                continue
            if 500 <= e.code < 600 and n < tries - 1:
                time.sleep(2 ** n)
                last = ApiError(e.code, body, where)
                continue
            raise ApiError(e.code, body, where) from None
        except urllib.error.URLError as e:
            if n < tries - 1:
                time.sleep(2 ** n)
                last = RuntimeError(f"{where} — 연결 실패: {e.reason}")
                continue
            raise RuntimeError(f"{where} — 연결 실패: {e.reason}") from None
    raise last or RuntimeError(f"{where} — 알 수 없는 실패")


def _json_body(raw: bytes, where: str) -> dict:
    try:
        got = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        raise ApiError(200, raw[:300].decode("utf-8", "replace"),
                       f"{where} — json 이 아닙니다") from None
    # HeyGen 은 성공도 실패도 200 으로 주면서 error 를 채우는 경우가 있다.
    if isinstance(got, dict) and got.get("error"):
        raise ApiError(200, json.dumps(got["error"], ensure_ascii=False), where)
    return got.get("data", got) if isinstance(got, dict) else got


def get(key: str, params: dict | None = None, *, conf: dict | None = None,
        path: str = "") -> dict:
    conf = conf or load_conf()
    if not conf.get("api_key"):
        raise NotConfigured("API 키가 없습니다 — heygen.local.json 에 api_key 를 넣으세요")
    url = BASE + (path or ENDPOINTS[key])
    q = {k: v for k, v in (params or {}).items() if v not in ("", None)}
    if q:
        url += "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers=_headers(conf), method="GET")
    return _json_body(_open(req, where=f"GET {url}"), f"GET {url}")


def post(key: str, payload: dict, *, idem: str = "", conf: dict | None = None) -> dict:
    conf = conf or load_conf()
    url = BASE + ENDPOINTS[key]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h = _headers(conf, idem)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    return _json_body(_open(req, where=f"POST {url}"), f"POST {url}")


# ══ 자산 올리기 ═════════════════════════════════════════════════════════════

def upload_asset(path: Path, *, conf: dict | None = None, idem: str = "") -> str:
    """파일 하나 → asset_id. multipart 를 손으로 만든다(requests 안 씀).

    ★ 32MB 상한이 실제로 걸린다. 44.1k 스테레오 wav 는 **분당 약 10.6MB** 라
      5분이면 넘는다. 그래서 부르는 쪽(p4)이 mp3 로 바꿔서 넘긴다.
    """
    conf = conf or load_conf()
    if not conf.get("api_key"):
        raise NotConfigured("API 키가 없습니다")
    raw = path.read_bytes()
    if len(raw) > ASSET_MAX_BYTES:
        raise ApiError(413, f"{path.name} 이 {len(raw)/1048576:.1f}MB 입니다 "
                            f"(상한 32MB) — mp3 로 줄여서 올리세요", "upload_asset")

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    b = "----heygen" + uuid.uuid4().hex
    body = b"".join([
        f"--{b}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        raw, b"\r\n", f"--{b}--\r\n".encode(),
    ])
    h = _headers(conf, idem)
    h["Content-Type"] = f"multipart/form-data; boundary={b}"
    url = BASE + ENDPOINTS["assets"]
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    got = _json_body(_open(req, where=f"POST {url} ({path.name})"), "upload_asset")
    aid = got.get("asset_id") or got.get("id")
    if not aid:
        raise ApiError(200, json.dumps(got, ensure_ascii=False)[:300],
                       "upload_asset — asset_id 가 없습니다")
    return str(aid)


# ══ 목록 (전부 무료) ════════════════════════════════════════════════════════

def _rows_in(got: dict) -> list[dict]:
    """응답에서 **목록을 찾아낸다.**

    HeyGen 이 어느 열쇠에 목록을 담는지 엔드포인트마다 다르고 문서에도 다 안
    적혀 있다. 이름을 추측해 박아 두면 «0개 나옵니다» 하고 몇 시간을 쓴다.
    그래서 아는 이름을 먼저 보고, 없으면 **딕셔너리들의 리스트를 찾아** 쓴다.
    """
    if not isinstance(got, dict):
        return [r for r in (got or []) if isinstance(r, dict)]
    for k in ("avatars", "looks", "avatar_looks", "voices", "list", "items",
              "data", "results"):
        v = got.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
        if isinstance(v, dict):
            inner = _rows_in(v)
            if inner:
                return inner
    for v in got.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _next_token(got: dict) -> str:
    if not isinstance(got, dict):
        return ""
    for k in ("token", "next_token", "next", "cursor", "page_token"):
        v = got.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _paged(key: str, params: dict, *, cap: int = 400,
           raw: list | None = None) -> list[dict]:
    """token 커서를 따라가며 다 모은다. **목록 조회는 과금되지 않는다.**

    raw 를 주면 첫 페이지 응답을 그대로 담아 준다 — 파싱이 어긋났을 때 무엇이
    왔는지 눈으로 보려는 것이다(cli 의 --raw).
    """
    out: list[dict] = []
    token = ""
    while len(out) < cap:
        got = get(key, {**params, "limit": 50, "token": token})
        if raw is not None and not raw:
            raw.append(got)
        rows = _rows_in(got)
        out += rows
        token = _next_token(got)
        if not token or not rows:
            break
    return out


def list_avatar_groups(ownership: str = "public", *, raw: list | None = None) -> list[dict]:
    return _paged("avatars", {"ownership": ownership}, raw=raw)


def list_looks(*, ownership: str = "public", avatar_type: str = "",
               group_id: str = "", raw: list | None = None) -> list[dict]:
    return _paged("looks", {"ownership": ownership, "avatar_type": avatar_type,
                            "group_id": group_id}, raw=raw)


def list_voices(*, language: str = "", gender: str = "",
                raw: list | None = None) -> list[dict]:
    return _paged("voices", {"type": "public", "language": language,
                             "gender": gender}, raw=raw)


def probe() -> dict:
    """키가 살아 있는지만 본다. 과금 0. 401 이면 그대로 던진다."""
    got = get("avatars", {"ownership": "public", "limit": 1})
    return {"ok": True, "sample": got}


def balance() -> None:
    """남은 잔액.

    ★ **문서에 잔액 조회 엔드포인트가 없다.** 옛 업체에서 «추측으로 URL 을 박아 두면
      나중에 왜 401 이 뜨는지 며칠을 쓴다»고 배웠으므로 여기서도 추측하지 않는다.
      잔액은 HeyGen 대시보드(Billing)에서 본다.
    """
    return None


# ══ 영상 만들기 (여기서만 돈이 나간다) ═══════════════════════════════════════

def create_video(*, avatar_id: str, audio_asset_id: str = "", audio_url: str = "",
                 script: str = "", voice_id: str = "",
                 engine: str = "avatar_v", alpha: bool = True,
                 aspect_ratio: str = "9:16", resolution: str = "1080p",
                 motion_prompt: str = "", title: str = "",
                 idem: str = "", conf: dict | None = None) -> str:
    """POST /v3/videos → video_id.

    ★ `output_format:"webm"` 이 **배경 투명(알파)** 이다. mp4 는 알파를 못 담는다.
      문서가 "가장 많이 놓치는 설정"이라고 적어 둔 자리다. 이 값을 주면 배경 제거가
      저절로 걸리고, 같은 요청에 `background` 를 같이 주면 **거절된다.**

    ★ audio 와 script 는 **배타**다. 우리는 우즈베크 녹음본이 있으므로 audio 쪽이다.
    """
    if not (audio_asset_id or audio_url or script):
        raise NotConfigured("음성이 없습니다 — audio_asset_id · audio_url · script 중 하나")
    if script and not voice_id:
        raise NotConfigured("script 를 쓰려면 voice_id 가 필요합니다")

    payload: dict = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "output_format": "webm" if alpha else "mp4",
    }
    if engine:
        # 문서의 Avatar V 예시가 {"type": "..."} 꼴이다. 문자열만 받는 계정도
        # 있을 수 있어 실패하면 부르는 쪽(p4)이 문자열로 한 번 더 시도한다.
        payload["engine"] = {"type": engine}
    if audio_asset_id:
        payload["audio_asset_id"] = audio_asset_id
    elif audio_url:
        payload["audio_url"] = audio_url
    else:
        payload["script"], payload["voice_id"] = script, voice_id
    if motion_prompt:
        payload["motion_prompt"] = motion_prompt
    if title:
        payload["title"] = title

    got = post("videos", payload, idem=idem or str(uuid.uuid4()), conf=conf)
    vid = got.get("video_id") or got.get("id")
    if not vid:
        raise ApiError(200, json.dumps(got, ensure_ascii=False)[:400],
                       "create_video — video_id 가 없습니다")
    return str(vid)


DONE = {"completed", "success", "succeeded", "done"}
FAILED = {"failed", "error", "canceled", "cancelled"}


def wait_video(video_id: str, *, timeout: float = 1800, every: float = 6.0,
               on_tick=None, conf: dict | None = None) -> dict:
    """다 될 때까지 기다린다. 폴링은 과금되지 않는다.

    ★ 타임아웃으로 죽어도 **이미 만들어진 영상은 서버에 있다.** 같은 video_id 로
      다시 이어서 폴링하면 된다 — 다시 만들지 않는다(그러면 두 번 과금된다).
    """
    t0 = time.time()
    while True:
        got = get("video", conf=conf,
                  path=ENDPOINTS["video"].format(id=urllib.parse.quote(video_id)))
        st = str(got.get("status") or "").lower()
        if st in DONE and (got.get("video_url") or got.get("url")):
            return got
        if st in FAILED:
            raise ApiError(200, json.dumps(got, ensure_ascii=False)[:400],
                           f"영상 만들기 실패 (video_id={video_id})")
        if time.time() - t0 > timeout:
            raise TimeoutError(
                f"{timeout:.0f}초를 기다렸지만 아직 {st or '상태미상'} 입니다. "
                f"영상은 서버에 남아 있습니다 — video_id={video_id} 로 이어서 받으세요 "
                f"(다시 만들면 두 번 과금됩니다)")
        if on_tick:
            on_tick(st, time.time() - t0)
        time.sleep(every)


def download(url: str, dest: Path) -> Path:
    """결과 파일 받기. 서명된 URL 이라 헤더를 붙이지 않는다."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "recmaker2heygen"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=600) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return dest


# ══ 밖으로 나가는 두 함수 ════════════════════════════════════════════

def avatar(audio_path: Path, out_path: Path, *, avatar_id: str = "",
           engine: str = "", alpha: bool = True, aspect_ratio: str = "9:16",
           motion_prompt: str = "", title: str = "", idem: str = "",
           on_tick=None) -> dict:
    """오디오 → 립싱크 아바타 영상. 파일을 out_path 에 놓고 실측값을 돌려준다.

    돌려주는 것: {"video_id", "seconds", "usd_est", "engine", "url"}
    ★ usd_est 는 **예상**이다. 실제 차감액은 HeyGen Billing 에서만 확인된다.
    """
    conf = _guard("아바타 생성")
    avatar_id = avatar_id or conf.get("avatar_id", "")
    engine = engine or conf.get("engine", "avatar_v")
    motion_prompt = motion_prompt or conf.get("motion_prompt", "")
    idem = idem or str(uuid.uuid4())

    aid = upload_asset(audio_path, conf=conf, idem=idem + "-asset")
    vid = create_video(avatar_id=avatar_id, audio_asset_id=aid, engine=engine,
                       alpha=alpha, aspect_ratio=aspect_ratio,
                       motion_prompt=motion_prompt, title=title,
                       idem=idem, conf=conf)
    got = wait_video(vid, on_tick=on_tick, conf=conf)
    url = got.get("video_url") or got.get("url") or ""
    if not url:
        raise ApiError(200, json.dumps(got, ensure_ascii=False)[:300],
                       "결과 URL 이 없습니다")
    download(url, out_path)
    sec = float(got.get("duration") or 0.0)
    return {"video_id": vid, "asset_id": aid, "seconds": sec,
            "usd_est": round(sec * RATE_USD_PER_SEC.get(engine, 0.0), 2),
            "engine": engine, "url": url}


def tts(text: str, out_path: Path, *, voice: str = "", lang: str = "uz") -> dict:
    """우즈베크어 음성 합성 — **녹음본 싱크가 안 맞을 때만 쓰는 예비 경로.**

    ★ 우즈베크 보이스가 HeyGen 에 있는지는 문서에 없다. 쓰기 전에
      `python -m heygen.cli voices --lang Uzbek` 로 **무료로** 확인할 것.
    """
    conf = load_conf()
    voice = voice or conf.get("voice_uz", "")
    if not voice:
        raise NotConfigured(
            "보이스를 안 골랐습니다 — `python -m heygen.cli voices --lang Uzbek` 로 "
            "찾아 `set --voice-uz` 로 넣으세요 (조회는 무료입니다)")
    got = post("speech", {"text": text, "voice_id": voice}, conf=conf)
    url = got.get("audio_url") or got.get("url") or ""
    if not url:
        raise ApiError(200, json.dumps(got, ensure_ascii=False)[:300],
                       "tts — audio_url 이 없습니다")
    download(url, out_path)
    return {"voice_id": voice, "url": url}
