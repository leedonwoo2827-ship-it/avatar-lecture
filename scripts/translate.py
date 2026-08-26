# -*- coding: utf-8 -*-
r"""자막 번역 — Claude Code CLI 로그인(OAuth)을 그대로 쓴다. API 키가 없다.

`llm/claude_provider.py`는 260818에서 가져온 것이고, **환경변수의
ANTHROPIC_API_KEY 를 일부러 빈 문자열로 덮는다**(scrubbed_env). 오래된 export 가
OAuth 를 가로채 남의 계정에 과금되는 것을 막으려는 것이다. 그래서 인증은
`~/.claude/.credentials.json` — 즉 `claude` CLI 로 로그인한 그 세션이다.

## 왜 줄 수를 목숨처럼 지키는가

자막 한 줄이 큐 하나다. 번역이 두 줄로 늘거나 한 줄로 합쳐지면 그 뒤 전부가
밀린다. 그래서 **번호를 붙여 보내고 번호로 돌려받는다** — 개수가 안 맞으면
그 묶음만 다시 시킨다. 지어낸 번호가 오면 버린다.

한 번에 다 보내지 않는 이유도 같다. 802줄을 한 번에 시키면 중간에서 줄이 어긋나도
어디서 어긋났는지 모른다. 40줄씩 끊어 보내면 어긋난 묶음만 다시 하면 된다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import cue_max_chars, die

BATCH = 40          # 한 번에 보낼 줄 수
RETRY = 2           # 개수가 안 맞을 때 같은 묶음을 다시 시킬 횟수

LANG_NAME = {
    "uz": "우즈벡어(라틴 문자)", "ru": "러시아어", "ko": "한국어",
    "en": "영어", "kk": "카자흐어",
}

SYSTEM = """너는 실무 교육 영상의 자막을 옮기는 사람이다.

지켜야 할 것:
- **줄 하나가 화면에 뜨는 자막 하나다.** 준 줄 수와 낸 줄 수가 같아야 한다.
  줄을 합치거나 나누지 마라. 번호를 그대로 달아 돌려준다.
- 한 줄은 {maxc}자 안으로. 넘으면 뜻을 줄이지 말고 **표현을 짧게** 한다.
- 줄바꿈을 넣지 마라. 한 줄은 한 줄이다.
- 앞뒤 줄이 한 문장의 조각일 수 있다. 그 줄만 보고 문장을 완성하려 하지 마라 —
  조각은 조각으로 옮긴다.
- 전문 용어는 현지 실무에서 쓰는 말로 옮긴다. 확신이 없으면 원어를 괄호 없이
  그대로 두는 편이 낫다 — 지어낸 용어가 더 나쁘다.
- 말투는 강의체. 존대하되 딱딱하지 않게.

JSON만 출력한다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["no", "text"],
            },
        }
    },
    "required": ["lines"],
}


def _provider(budget_usd: float):
    try:
        from llm.claude_provider import ClaudeProvider
    except ImportError as e:  # noqa: BLE001
        die(f"llm/claude_provider.py 를 불러오지 못했습니다: {e}")
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        die("claude-agent-sdk 가 없습니다 — setup.bat 을 다시 돌리거나 "
            "`pip install claude-agent-sdk` 하세요. API 키는 필요 없습니다 — "
            "`claude` CLI 로 로그인만 되어 있으면 됩니다.")
    from llm.claude_provider import ClaudeProvider
    return ClaudeProvider(model="", effort="low", allowed_tools=[], max_turns=1,
                          budget_usd=budget_usd)


def _one_batch(p, rows: list[tuple[int, str]], src: str, dst: str, maxc: int) -> dict[int, str]:
    body = "\n".join(f"{n}. {t}" for n, t in rows)
    prompt = (f"{LANG_NAME.get(src, src)} 자막 {len(rows)}줄이다. "
              f"{LANG_NAME.get(dst, dst)}로 옮겨라.\n"
              f"번호를 그대로 달아 {len(rows)}줄을 돌려준다.\n\n{body}")
    out = p.structured(SYSTEM.format(maxc=maxc),
                       [{"role": "user", "content": prompt}], schema=SCHEMA)
    got: dict[int, str] = {}
    want = {n for n, _ in rows}
    for r in (out.get("lines") or []):
        try:
            n = int(r["no"])
        except (KeyError, TypeError, ValueError):
            continue
        if n in want:                      # 지어낸 번호는 버린다
            got[n] = " ".join(str(r.get("text") or "").split())
    return got


def translate_lines(texts: list[str], src: str, dst: str, *,
                    budget_usd: float = 8.0, log=print) -> list[str]:
    """줄 목록 → 옮긴 줄 목록. **길이가 반드시 같다.**

    끝까지 못 받은 줄은 원문을 그대로 둔다 — 조용히 지우면 그 줄만 자막이 사라져
    나중에 찾기 어렵다. 몇 줄이 남았는지는 로그로 말한다.
    """
    p = _provider(budget_usd)
    maxc = cue_max_chars(dst)
    result: list[str | None] = [None] * len(texts)

    for start in range(0, len(texts), BATCH):
        rows = [(i + 1, texts[i]) for i in range(start, min(start + BATCH, len(texts)))]
        got: dict[int, str] = {}
        for attempt in range(1 + RETRY):
            got = _one_batch(p, rows, src, dst, maxc)
            if len(got) == len(rows):
                break
            log(f"  {rows[0][0]}~{rows[-1][0]}번 — {len(got)}/{len(rows)}줄만 왔습니다"
                f" (다시 {attempt + 1}/{RETRY})" if attempt < RETRY else
                f"  {rows[0][0]}~{rows[-1][0]}번 — {len(got)}/{len(rows)}줄에서 멈췄습니다")
        for n, t in got.items():
            result[n - 1] = t
        done = sum(1 for x in result if x is not None)
        log(f"  {done}/{len(texts)}줄 · ${p.last_cost_usd:.2f}")

    left = [i + 1 for i, x in enumerate(result) if x is None]
    if left:
        log(f"못 받은 줄 {len(left)}개 — 원문을 그대로 두었습니다: "
            f"{', '.join(map(str, left[:12]))}{' …' if len(left) > 12 else ''}")
    over = [i + 1 for i, x in enumerate(result) if x and len(x) > maxc]
    if over:
        log(f"{maxc}자를 넘긴 줄 {len(over)}개 — 웹 화면의 '자막 다듬기'에서 노랗게 뜹니다")
    return [x if x is not None else texts[i] for i, x in enumerate(result)]
