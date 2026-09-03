# -*- coding: utf-8 -*-
r"""용어집 — 전공 용어를 한 강의 안에서 **같게** 옮긴다.

    __last-uz-output/script.ru-ko.json  →  용어집.json  →  translate.py

## 왜 필요한가

의료·간호 용어는 같은 말이 같게 나와야 한다. «электронная медицинская карта» 가
어디선 «전자의무기록», 어디선 «전자차트», 어디선 «전자 의료 카드» 로 오면 교육
자료로 못 쓴다. 옮기는 쪽은 줄 하나만 보고 판단하므로 이런 흔들림이 반드시 생긴다.

## 어디서 가져오나 — **이미 승인된 번역에서**

`script.ru-ko.json` 에 씬 32개의 러시아어·한국어 나레이션이 짝으로 들어 있다.
누군가 이미 옮겨 검수를 받은 것이다. 그 짝에서 용어를 뽑으면 **새로 지어내지
않고 이미 쓰이는 말**을 그대로 쓴다. 지어낸 용어가 가장 나쁘다.

## 사람이 고친 것이 이긴다

`용어집.json` 은 손으로 고쳐도 된다. 다시 뽑아도 **손으로 넣은 항목은 덮지
않는다**(`"손질": true` 로 표시된다). 03·04·05 JSON 과 같은 원칙이다.

    python scripts/glossary.py extract --to ko      # script.ru-ko.json 에서 뽑는다
    python scripts/glossary.py show --to ko
    python scripts/glossary.py add --to ko "медицинская сестра" "간호사"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import ROOT, die, load_json, save_json

GLOS = ROOT / "용어집.json"
PAIRS = ROOT / "__last-uz-output" / "script.ru-ko.json"

# 한 번에 볼 씬 수. 짝이 길어(러시아어 1000자 + 한국어 500자) 적게 끊는다.
BATCH = 4

SYSTEM = """너는 실무 교육 자료의 용어집을 만드는 사람이다.

같은 내용을 두 언어로 옮긴 글이 짝으로 온다. 거기서 **전공 용어만** 뽑아
{src} → {dst} 표를 만든다.

뽑는 것:
- 의료·간호·전산 전공 용어 (예: 전자의무기록, 활력징후, 투약, 접근 권한)
- 그 기관에서 쓰는 고유한 말, 약어
- 잘못 옮기면 뜻이 달라지는 말

뽑지 않는 것:
- 일반 낱말 (오늘, 여러분, 중요하다, 시작하다)
- 문장이나 구절 — **낱말이나 짧은 명사구만** 뽑는다
- 짝에 실제로 나오지 않은 말 — **지어내지 마라.** 없으면 빈 목록을 낸다

돌려줄 때:
- src 는 준 글에 **그대로 나온 형태**로 (원형으로 바꾸지 마라)
- dst 는 짝의 글에서 **실제로 쓰인 말**로. 네가 더 좋다고 생각하는 말로 바꾸지 마라
- 한 짝에서 5~15개면 충분하다

JSON만 출력한다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
                "required": ["src", "dst"],
            },
        }
    },
    "required": ["terms"],
}

LANG_NAME = {"ru": "러시아어", "ko": "한국어", "en": "영어",
             "uz": "우즈벡어(라틴 문자)", "kk": "카자흐어", "ja": "일본어"}


# ══ 파일 ═══════════════════════════════════════════════════════════════════

def load() -> dict:
    if not GLOS.is_file():
        return {"설명": "전공 용어집. 손으로 고쳐도 됩니다 — 고친 것이 이깁니다.",
                "src": "ru", "langs": {}}
    try:
        got = load_json(GLOS)
    except Exception:  # noqa: BLE001 — 깨진 용어집이 번역을 막지 않게
        print(f"경고: {GLOS.name} 을 읽지 못했습니다 — 용어집 없이 갑니다")
        return {"src": "ru", "langs": {}}
    got.setdefault("langs", {})
    return got


def terms_for(tag: str) -> dict[str, str]:
    """`translate.py` 가 그대로 쓸 {원어: 옮길말}. 없으면 빈 표."""
    rows = load().get("langs", {}).get(tag, {})
    out: dict[str, str] = {}
    for k, v in rows.items():
        v = v.get("dst", "") if isinstance(v, dict) else str(v)
        if str(k).strip() and str(v).strip():
            out[str(k).strip()] = str(v).strip()
    return out


def put(tag: str, pairs: dict[str, str], *, by_hand: bool = False) -> tuple[int, int]:
    """표에 넣는다. **손질된 항목은 덮지 않는다.** (넣은 수, 지킨 수)"""
    g = load()
    cur = g["langs"].setdefault(tag, {})
    added = kept = 0
    for k, v in pairs.items():
        k, v = str(k).strip(), str(v).strip()
        if not k or not v:
            continue
        old = cur.get(k)
        if isinstance(old, dict) and old.get("손질") and not by_hand:
            kept += 1
            continue
        cur[k] = {"dst": v, "손질": True} if by_hand else {"dst": v}
        added += 1
    g["langs"][tag] = dict(sorted(cur.items(), key=lambda x: -len(x[0])))
    save_json(GLOS, g)
    return added, kept


# ══ 뽑기 ═══════════════════════════════════════════════════════════════════

def extract(tag: str, *, budget_usd: float = 3.0, limit: int = 0) -> dict[str, str]:
    """`script.ru-ko.json` 의 짝에서 용어를 뽑는다. **ko 짝이 있을 때만 된다.**"""
    if tag != "ko":
        die(f"짝으로 된 원문이 {tag} 에는 없습니다 — script.ru-ko.json 은 ru↔ko 뿐입니다. "
            f"{tag} 는 `add` 로 손으로 넣거나, ko 용어집을 먼저 만든 뒤 "
            f"p2c_relang.py 가 그걸 참고하게 하세요")
    rows = load_json(need_pairs())
    if limit:
        rows = rows[:limit]

    from scripts.translate import _provider
    p = _provider(budget_usd)
    got: dict[str, str] = {}
    for i in range(0, len(rows), BATCH):
        grp = rows[i:i + BATCH]
        body = "\n\n".join(
            f"[씬 {r['no']}]\n"
            f"제목  ru: {r['slide_title_ru']}\n"
            f"제목  ko: {r['slide_title_ko']}\n"
            f"본문  ru: {r['narration_ru']}\n"
            f"본문  ko: {r['narration_ko']}"
            for r in grp)
        out = p.structured(
            SYSTEM.format(src=LANG_NAME["ru"], dst=LANG_NAME[tag]),
            [{"role": "user", "content": body}], schema=SCHEMA)
        n0 = len(got)
        for t in (out.get("terms") or []):
            s, d = str(t.get("src") or "").strip(), str(t.get("dst") or "").strip()
            # 문장은 버린다 — 용어집은 낱말 표다
            if s and d and len(s) <= 60 and s.count(" ") <= 5:
                got.setdefault(s, d)
        print(f"  씬 {grp[0]['no']}~{grp[-1]['no']}  +{len(got)-n0}개 "
              f"(누적 {len(got)}) · ${p.last_cost_usd:.2f}")
    return got


def need_pairs() -> Path:
    if not PAIRS.is_file():
        die(f"{PAIRS} 가 없습니다 — 러시아어·한국어 나레이션이 짝으로 든 "
            f"script.json 을 그 자리에 두세요")
    return PAIRS


# ══ CLI ════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="전공 용어집")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="이미 옮겨진 짝에서 용어를 뽑는다")
    e.add_argument("--to", default="ko")
    e.add_argument("--budget", type=float, default=3.0, help="Claude 호출 상한(USD)")
    e.add_argument("--limit", type=int, default=0, help="앞 N씬만 — 시험용")

    s = sub.add_parser("show", help="용어집을 본다")
    s.add_argument("--to", default="ko")

    a = sub.add_parser("add", help="손으로 넣는다 (다시 뽑아도 안 덮인다)")
    a.add_argument("--to", default="ko")
    a.add_argument("src")
    a.add_argument("dst")

    o = ap.parse_args()

    if o.cmd == "extract":
        print(f"ru → {o.to} 용어 뽑기 — {need_pairs().name}")
        got = extract(o.to, budget_usd=o.budget, limit=o.limit)
        added, kept = put(o.to, got)
        print(f"\n{added}개 넣었습니다"
              + (f" · 손질한 {kept}개는 그대로 두었습니다" if kept else ""))
        print(f"손으로 고쳐도 됩니다 — {GLOS}")

    elif o.cmd == "show":
        t = terms_for(o.to)
        if not t:
            print(f"{o.to} 용어집이 비어 있습니다 — "
                  f"`python scripts/glossary.py extract --to {o.to}` 를 돌리세요")
            return
        print(f"ru → {o.to} · {len(t)}개")
        for k, v in t.items():
            print(f"  {k}  →  {v}")

    else:
        added, _ = put(o.to, {o.src: o.dst}, by_hand=True)
        print(f"{'넣었습니다' if added else '못 넣었습니다'}: {o.src} → {o.dst}")


if __name__ == "__main__":
    main()
