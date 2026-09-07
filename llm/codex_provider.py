# -*- coding: utf-8 -*-
r"""Codex 프로바이더 — ChatGPT 로그인(OAuth)을 그대로 쓴다. **API 키를 쓰지 않는다.**

`llm/claude_provider.py` 와 **같은 계약**이다. 새 인터페이스를 발명하지 않는다 —
그래야 부르는 쪽(scripts/translate.py)이 한 줄로 갈아끼운다.

    model                                     # 대입 가능한 필드
    generate(system, messages) -> str
    stream(system, messages)   -> Iterator[str]
    structured(system, messages, schema) -> dict
    ping() -> (bool, str)
    last_cost_usd                             # 구독이라 늘 0.0

인증은 `~/.codex/auth.json` — 즉 `codex` CLI 로 ChatGPT 로그인한 그 세션이다.
클로드 쪽과 **한 대에서 같이** 둘 수 있다. 서로 안 건드린다.

## 왜 `codex exec` 인가

    codex exec [옵션] -            프롬프트를 stdin 으로 받는다
      --output-schema <파일>       마지막 답을 그 JSON 스키마로 낸다
      -o <파일>                    **마지막 답만** 그 파일에 쓴다

`-o` 가 핵심이다. codex 는 에이전트라 stdout 에 진행 상황을 섞어 내는데, 그걸
긁어 파싱하면 형식이 바뀔 때마다 깨진다. 마지막 답만 파일로 받으면 그 위험이
없다. `--output-schema` 는 클로드 쪽 `structured()` 와 같은 자리다.

## 안전 · 재현

    -s read-only        모델이 낸 명령을 못 쓰게 한다. 우리는 글자만 받는다.
    --ephemeral         세션 파일을 남기지 않는다. 번역 한 묶음이 곧 한 번이다.
    --skip-git-repo-check   저장소 밖에서도 돈다.

★ **도구를 쓰지 말라고 프롬프트에 박는다.** codex 는 기본이 «일하는 에이전트» 라
  파일을 뒤지려 든다. 자막 40줄을 옮기는 데 그럴 일이 없고, 그러면 답이 느려지고
  엉뚱한 맥락이 섞인다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .errors import NotAuthenticated, ProviderError

NO_TOOLS = ("아래 일만 하고 바로 답만 낸다. 파일을 읽거나 명령을 실행하지 않는다. "
            "설명·머리말·코드펜스를 붙이지 않는다.")


def find_cli() -> Optional[Path]:
    r"""codex 실행 파일.

    ★ npm 으로 깔면 윈도에서 `codex.cmd` **셸 래퍼**가 PATH 에 잡힌다. 파이썬
      subprocess 는 그 .cmd 를 그대로 실행할 수 있다(2026-09-07 실측: --version
      이 0 으로 떨어진다). claude 쪽과 달리 여기서는 .cmd 를 피할 이유가 없다 —
      SDK 가 아니라 우리가 직접 부르고, 인자를 리스트로 넘기니 셸 해석이 없다.
    """
    if env := (os.environ.get("CODEX_CLI") or "").strip().strip('"'):
        p = Path(env).expanduser()
        if p.exists():
            return p
    for name in ("codex.cmd", "codex.exe", "codex"):
        if (w := shutil.which(name)):
            return Path(w)
    return None


def _auth_file() -> Path:
    home = os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
    return Path(home) / "auth.json"


def _flatten(system: str, messages: List[Dict]) -> str:
    """system + messages → 한 덩어리 프롬프트.

    codex exec 는 한 번에 한 프롬프트다(대화 턴이 없다). 역할을 글자로 적어
    붙인다 — 우리 쓰임은 «한 번 묻고 한 번 받는» 것뿐이라 이걸로 충분하다.
    """
    out = [NO_TOOLS]
    if system:
        out.append(system.strip())
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, list):          # 클로드 쪽 블록 형식도 받아 준다
            c = "".join(b.get("text", "") for b in c if isinstance(b, dict))
        who = "사용자" if m.get("role", "user") == "user" else "너"
        out.append(f"[{who}]\n{str(c or '').strip()}")
    return "\n\n".join(x for x in out if x)


def _strictify(node: Any) -> Any:
    r"""JSON 스키마를 OpenAI 의 **엄격 모드**가 받는 꼴로 고친다.

    ★ 부르는 쪽 스키마는 클로드(draft-07) 기준으로 적혀 있다. OpenAI 는 그걸
      그대로 거부한다 — «'additionalProperties' is required to be supplied and
      to be false» (2026-09-07 실측 400). 두 가지를 손본다:

        · 모든 객체에 `additionalProperties: false`
        · `required` 는 **properties 전부**여야 한다 (일부만 적으면 거부한다)

      스키마를 두 벌로 적어 두지 않는다. 한 벌을 두고 여기서 맞춰 넘긴다 —
      업체가 규칙을 바꾸면 고칠 자리가 이 함수 하나다.
    """
    if isinstance(node, list):
        return [_strictify(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _strictify(v) for k, v in node.items()}
    if out.get("type") == "object" or "properties" in out:
        out.setdefault("additionalProperties", False)
        props = out.get("properties")
        if isinstance(props, dict):
            out["required"] = list(props.keys())
    return out


def _unfence(s: str) -> str:
    """```json … ``` 로 감싸 오면 벗긴다. 스키마를 줘도 가끔 감싼다."""
    s = s.strip()
    m = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", s, re.S)
    return m.group(1).strip() if m else s


class CodexProvider:
    """ChatGPT 로그인으로 도는 프로바이더. 클로드 쪽과 같은 얼굴을 한다."""

    def __init__(self, model: str = "", *, budget_usd: float = 0.0,
                 timeout: int = 900, cwd: str | Path | None = None) -> None:
        self.model = model or ""
        self.budget_usd = budget_usd     # 구독이라 안 쓴다 (시그니처 호환)
        self.timeout = timeout
        self.cwd = str(cwd) if cwd else None
        # ★ 구독 호출이라 **호출당 값을 모른다.** 0 으로 둔다 — 모르는 값을
        #   그럴싸한 숫자로 채우면 로그가 거짓말을 한다.
        self.last_cost_usd = 0.0
        self.total_cost_usd = 0.0

    # ── 상태 ──────────────────────────────────────────────────────────────
    def ping(self) -> Tuple[bool, str]:
        cli = find_cli()
        if cli is None:
            return False, ("codex 를 찾지 못했습니다 — `npm i -g @openai/codex` 로 "
                           "깔고 `codex` 를 한 번 띄워 ChatGPT 로 로그인하세요.")
        if not _auth_file().is_file():
            return False, (f"ChatGPT 로그인이 없습니다 — `codex` 를 띄워 로그인하세요 "
                           f"({_auth_file()} 가 만들어집니다).")
        return True, f"codex · {cli.name}"

    # ── 부르기 ────────────────────────────────────────────────────────────
    def _run(self, prompt: str, schema: Optional[dict]) -> str:
        cli = find_cli()
        if cli is None:
            raise ProviderError(self.ping()[1])
        if not _auth_file().is_file():
            raise NotAuthenticated(self.ping()[1])

        with tempfile.TemporaryDirectory(prefix="codex-") as td:
            out_f = Path(td) / "last.txt"
            cmd: List[str] = [str(cli), "exec", "--ephemeral", "--color", "never",
                              "--skip-git-repo-check", "-s", "read-only",
                              "-o", str(out_f)]
            if self.model:
                cmd += ["-m", self.model]
            if schema is not None:
                sch_f = Path(td) / "schema.json"
                sch_f.write_text(json.dumps(_strictify(schema), ensure_ascii=False),
                                 encoding="utf-8")
                cmd += ["--output-schema", str(sch_f)]
            cmd.append("-")              # 프롬프트는 stdin 으로

            try:
                r = subprocess.run(cmd, input=prompt, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=self.timeout, cwd=self.cwd)
            except subprocess.TimeoutExpired:
                raise ProviderError(f"codex 가 {self.timeout}초 안에 답하지 않았습니다")

            got = out_f.read_text(encoding="utf-8").strip() if out_f.is_file() else ""

        if not got:
            tail = ((r.stderr or "") + (r.stdout or "")).strip()[-400:]
            raise ProviderError(f"codex 가 답을 내지 않았습니다 (종료 {r.returncode})"
                                + (f"\n{tail}" if tail else ""))
        return got

    def generate(self, system: str, messages: List[Dict], **_) -> str:
        return self._run(_flatten(system, messages), None)

    def stream(self, system: str, messages: List[Dict], **_) -> Iterator[str]:
        """한 번에 받아 한 번 흘린다. codex exec 는 조각으로 안 준다(우리 쓰임에선)."""
        yield self.generate(system, messages)

    def structured(self, system: str, messages: List[Dict],
                   schema: Dict[str, Any], **_) -> Dict[str, Any]:
        raw = self._run(_flatten(system, messages), schema)
        try:
            got = json.loads(_unfence(raw))
        except json.JSONDecodeError as e:
            raise ProviderError(f"codex 답을 JSON 으로 못 읽었습니다: {e}\n"
                                f"{raw[:300]}")
        if not isinstance(got, dict):
            raise ProviderError(f"codex 가 객체가 아닌 것을 냈습니다: {type(got).__name__}")
        return got
