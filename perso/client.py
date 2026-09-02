# -*- coding: utf-8 -*-
"""perso 플랫폼 붙이는 자리 — **아직 안 붙었다.**

지금은 껍데기다. 엔드포인트를 **추측해서 채우지 않았다** — platform.perso.ai 의
가격 페이지는 SPA 라 크롤이 막히고 docs.perso.ai 는 이름이 안 풀린다(2026-09-02
실측). 추측으로 URL 을 박아 두면 나중에 "왜 401 이 뜨지" 하고 며칠을 쓴다.

**API 키를 발급한 뒤 할 일은 이 파일 하나다:**

  1. 사이드바 Documentation 에서 실제 레퍼런스를 읽는다
  2. 아래 ENDPOINTS 를 채운다 (TTS · 아바타 · 잔액)
  3. tts() 와 avatar() 의 TODO 자리에 호출을 넣는다
  4. `perso.local.json` 에 키를 넣는다 (.gitignore 라 저장소에 안 간다)

        {"api_key": "...", "base_url": "https://...",
         "voice_uz": "...", "avatar_id": "..."}   ← 정장 차림 발표자를 고른다

  5. `python scripts/p2_voice.py --engine perso --scenes 1` 로 **1씬만** 돌린다
  6. Billing → Transactions 의 차감량을 `_doc/credit-ledger.csv` 와 맞춰 본다

그 전까지는 p2 가 `--engine source`(시연본 소리), p4 가 `--engine stub`(임시 아바타)로
돈다 — 크레딧 0 으로 화면과 배치를 다 볼 수 있다.

★ 이 파일은 표준 라이브러리만 쓴다(urllib). 나머지 파이프라인이 그렇듯 pip 의존을
  늘리지 않는다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "perso.local.json"

# ── 여기를 채운다 ────────────────────────────────────────────────────────────
# 문서를 읽기 전이라 **비워 둔다.** 빈 값이면 아래 status() 가 "안 붙었다"고 답하고
# 파이프라인은 크레딧을 안 쓰는 엔진으로 돈다.
ENDPOINTS: dict[str, str] = {
    "tts": "",        # 예: "/v1/speech/synthesize"
    "avatar": "",     # 예: "/v1/interactive/sessions"
    "balance": "",    # 크레딧 잔액 조회 (있으면)
}

# 가격표에서 읽은 값. execution 이 잡 하나인지 1초인지 **확인 안 됐다** —
# 1씬 실측 전까지 계산에 쓰지 않는다. 화면에 그대로 보여 주기만 한다.
RATES_SEEN = {
    "interactive": (1.0, "credits / 분"),
    "video_translation": (0.025, "credits / execution"),
    "tts": (0.01, "credits / execution"),
}
CREDIT_USD = 0.20   # 50 credits = $10.00, 100 credits = $20.00 에서 나온 값


class NotConfigured(RuntimeError):
    """perso 가 아직 안 붙었다. 무엇을 해야 하는지 메시지에 담는다."""


def load_conf() -> dict:
    """`perso.local.json` → 설정. 없으면 환경변수만 본다."""
    conf: dict = {}
    if CONF.is_file():
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001 — 설정이 깨져도 도구는 돌아야 한다
            conf = {}
    if not conf.get("api_key"):
        conf["api_key"] = os.environ.get("PERSO_API_KEY", "")
    return conf


def save_conf(api_key: str = "", base_url: str = "", voice_uz: str = "",
              avatar_id: str = "") -> dict:
    """화면에서 받은 값을 `perso.local.json` 에 넣는다 (.gitignore 라 저장소 밖).

    빈 값으로 온 항목은 **덮지 않는다** — 키만 고치려고 저장했다가 보이스 이름을
    지워 버리는 사고를 막는다. 키를 지우려면 파일을 직접 지운다.
    """
    conf = {}
    if CONF.is_file():
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            conf = {}
    for k, v in (("api_key", api_key), ("base_url", base_url),
                 ("voice_uz", voice_uz), ("avatar_id", avatar_id)):
        if str(v).strip():
            conf[k] = str(v).strip()
    CONF.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
    return status()


def status() -> dict:
    """화면이 읽어 갈 연결 상태. 여기서 거짓말하지 않는다."""
    conf = load_conf()
    key = bool(conf.get("api_key"))
    eps = {k: bool(v) for k, v in ENDPOINTS.items()}
    ready = key and eps["tts"] and eps["avatar"]
    if ready:
        why = "쓸 수 있습니다"
    elif not key:
        why = "API 키가 없습니다 — perso.local.json 에 api_key 를 넣으세요"
    else:
        missing = [k for k, v in eps.items() if not v and k != "balance"]
        why = f"엔드포인트가 비어 있습니다 ({', '.join(missing)}) — perso/client.py 를 채우세요"
    return {
        "ok": ready, "key": key, "conf": CONF.is_file(),
        "endpoints": eps, "why": why,
        "rates": {k: {"n": v[0], "unit": v[1]} for k, v in RATES_SEEN.items()},
        "credit_usd": CREDIT_USD,
        "voice_uz": conf.get("voice_uz", ""),
        "avatar_id": conf.get("avatar_id", ""),
    }


def _guard(what: str) -> None:
    st = status()
    if not st["ok"]:
        raise NotConfigured(
            f"{what} — perso 가 아직 안 붙었습니다: {st['why']}. "
            "그때까지는 크레딧을 안 쓰는 엔진으로 돌아갑니다 "
            "(p2 --engine source · p4 --engine stub).")


def tts(text: str, out_path: Path, *, voice: str = "", lang: str = "uz") -> float:
    """우즈베크어 음성 합성. 실제로 빠진 크레딧을 돌려준다.

    TODO(키 발급 후): ENDPOINTS["tts"] 로 POST 하고 오디오를 out_path 에 쓴다.
    응답에 크레딧 사용량이 오면 그 값을, 안 오면 balance 를 전후로 재서 차이를
    돌려준다. **추정치를 돌려주지 않는다** — 장부가 추정으로 채워지면 쓸모가 없다.
    """
    _guard("음성 합성")
    raise NotConfigured("tts() 가 아직 안 채워졌습니다")


def avatar(audio_path: Path, out_path: Path, *, avatar_id: str = "") -> float:
    """오디오 → 립싱크 아바타 영상. 실제로 빠진 크레딧을 돌려준다.

    TODO(키 발급 후): ENDPOINTS["avatar"] 로 세션을 열고 오디오를 넣은 뒤
    결과 영상을 out_path 에 받는다. 배경 투명(알파) 출력이 되는지 먼저 확인할 것 —
    되면 p5 의 side/overlay 두 배치 모두 자연스러워지고, 안 되면 아바타가 사각형
    박스로 남아 side 배치만 쓸 만하다.
    """
    _guard("아바타 생성")
    raise NotConfigured("avatar() 가 아직 안 채워졌습니다")


def balance() -> float | None:
    """남은 크레딧. 조회 엔드포인트가 없으면 None."""
    if not ENDPOINTS.get("balance") or not load_conf().get("api_key"):
        return None
    raise NotConfigured("balance() 가 아직 안 채워졌습니다")
