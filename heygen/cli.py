# -*- coding: utf-8 -*-
r"""HeyGen 손도구 — 아바타·보이스를 고르고, **싸게 시험한다.**

    python -m heygen.cli probe                       키가 살아 있나        0원
    python -m heygen.cli avatars --gender female      look id 찾기          0원
    python -m heygen.cli voices --lang Uzbek           우즈베크 보이스 유무  0원
    python -m heygen.cli set --api-key ... --avatar-id ...
    python -m heygen.cli try --audio <파일> --engine avatar_iii

## 왜 `try` 가 따로 있나

`p4_avatar.py` 는 **묶음 단위**로 부른다 — 그게 제스처가 이어지는 이유다. 그런데
엔진을 견주려고 그걸 쓰면 8분 34초가 통째로 과금된다(avatar_v 로 $34). 견주는 데
그만큼 쓸 이유가 없다.

`try` 는 **준 오디오 하나만** 부른다. 71초짜리 씬 하나면 avatar_iii $1.19,
avatar_v $4.73 — 합쳐 $6 으로 «제스처 차이가 값어치 있나» 를 눈으로 정한다.
120강 기준 두 엔진의 차이가 $16,000 이니, 그 결정을 $6 에 사는 것이다.

★ 목록 조회(probe·avatars·voices)는 **과금되지 않는다.** 키만 있으면 마음껏 본다.
★ `try` 는 부르기 전에 예상액을 찍고 **한 번 묻는다.** `--yes` 로 건너뛴다.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heygen import client as hc


def _die(msg: str) -> None:
    raise SystemExit(f"오류: {msg}")


# ══ 보기 ═══════════════════════════════════════════════════════════════════

def cmd_probe(a) -> None:
    st = hc.status()
    print(f"설정 파일  {hc.CONF}  {'있음' if st['conf'] else '없음'}")
    print(f"키         {'있음' if st['key'] else '없음'}")
    print(f"아바타     {st['avatar_id'] or '(안 고름)'}")
    print(f"엔진       {st['engine']}  (초당 ${st['rate_now']})")
    if st["motion_prompt"]:
        print(f"제스처     {st['motion_prompt']}")
    if not st["key"]:
        print(f"\n{st['why']}")
        return
    try:
        hc.probe()
    except hc.ApiError as e:
        if e.status == 401:
            _die("키가 거절됐습니다(401) — 다시 발급해 넣으세요")
        _die(f"HTTP {e.status}: {e.body[:200]}")
    print("\n키가 살아 있습니다. 조회는 과금되지 않습니다.")


def _engines(lk: dict) -> list[str]:
    """지원 엔진 목록. 열쇠 이름을 하나로 못 믿어 몇 개를 본다."""
    for k in ("supported_api_engines", "supported_engines", "engines",
              "api_engines", "motion_engines"):
        v = lk.get(k)
        if isinstance(v, list) and v:
            return [str(x) for x in v]
        if isinstance(v, str) and v:
            return [x.strip() for x in v.split(",") if x.strip()]
    return []


def cmd_avatars(a) -> None:
    """look 목록. **look.id 가 avatar_id 다** (그룹 id 가 아니다)."""
    raw: list = []
    looks = hc.list_looks(ownership=a.ownership, avatar_type=a.type,
                          raw=(raw if a.raw else None))
    if a.raw:
        import json
        print(json.dumps(raw[0] if raw else {}, ensure_ascii=False, indent=2)[:6000])
        return
    if not looks:
        print("아무것도 못 받았습니다 — --type 을 studio_avatar · digital_twin · "
              "photo_avatar 로 바꿔 보거나, --raw 로 응답을 그대로 보세요")
        return
    q = (a.q or "").lower()
    rows = []
    for lk in looks:
        name = str(lk.get("name") or lk.get("id") or "")
        gender = str(lk.get("gender") or "")
        engines = _engines(lk)
        if q and q not in name.lower():
            continue
        if a.gender and gender and gender.lower() != a.gender.lower():
            continue
        if a.engine and not any(a.engine in e for e in engines):
            continue
        rows.append((name, str(lk.get("id") or ""), gender,
                     ",".join(str(x).replace("avatar_", "") for x in engines),
                     str(lk.get("avatar_type") or ""),
                     str(lk.get("preview_image_url") or "")))
    print(f"look {len(rows)}개 / 받은 {len(looks)}개"
          + (f" · 이름에 «{a.q}»" if a.q else "")
          + (f" · {a.gender}" if a.gender else "")
          + (f" · {a.engine} 지원" if a.engine else ""))
    print(f"{'이름':<34} {'look id (=avatar_id)':<40} {'성별':<7} {'엔진':<12} 종류")
    for name, lid, gender, eng, typ, prev in rows[:a.limit]:
        print(f"{name[:33]:<34} {lid[:39]:<40} {gender[:6]:<7} {eng[:11]:<12} {typ}")
        if a.preview and prev:
            print(f"    {prev}")
    if len(rows) > a.limit:
        print(f"… {len(rows) - a.limit}개 더 (--limit 로 늘리세요)")
    print("\n고른 뒤:  python -m heygen.cli set --avatar-id <look id>")
    print("★ 정장 차림 · 상반신이 화면을 크게 차지하지 않는 것을 고르세요 — "
          "슬라이드 오른쪽 칸에 세로로 들어갑니다.")


def cmd_voices(a) -> None:
    raw: list = []
    vs = hc.list_voices(language=a.lang, gender=a.gender,
                        raw=(raw if a.raw else None))
    if a.raw:
        import json
        print(json.dumps(raw[0] if raw else {}, ensure_ascii=False, indent=2)[:6000])
        return
    print(f"보이스 {len(vs)}개"
          + (f" · {a.lang}" if a.lang else "")
          + (f" · {a.gender}" if a.gender else ""))
    if not vs:
        print("\n없습니다. 그 언어 보이스가 HeyGen 에 없거나 이름이 다릅니다 — "
              "«Uzbek» · «Russian» 처럼 영어 이름으로 넣어 보세요.")
        print("우즈베크 보이스가 없으면 **녹음본 립싱크**로 갑니다 "
              "(p2 --engine source · 이미 그렇게 돌고 있습니다).")
        return
    for v in vs[:a.limit]:
        print(f"  {str(v.get('name') or '')[:28]:<30} "
              f"{str(v.get('voice_id') or ''):<40} "
              f"{str(v.get('language') or '')[:14]:<15} {v.get('gender') or ''}")
        if a.preview and v.get("preview_audio_url"):
            print(f"    {v['preview_audio_url']}")
    if len(vs) > a.limit:
        print(f"… {len(vs) - a.limit}개 더")


def cmd_set(a) -> None:
    st = hc.save_conf(api_key=a.api_key, avatar_id=a.avatar_id,
                      voice_uz=a.voice_uz, engine=a.engine,
                      motion_prompt=a.motion)
    print(f"{hc.CONF} 에 넣었습니다 (빈 값은 안 덮습니다)")
    print(f"  아바타 {st['avatar_id'] or '(안 고름)'} · 엔진 {st['engine']} "
          f"(초당 ${st['rate_now']})")
    print(f"  {st['why']}")


# ══ 싸게 시험 ══════════════════════════════════════════════════════════════

def cmd_try(a) -> None:
    """오디오 하나 → 아바타 영상 하나. **엔진을 견주는 자리다.**"""
    src = Path(a.audio).expanduser().resolve()
    if not src.is_file():
        _die(f"오디오를 찾지 못했습니다: {src}")

    from scripts.common import ffprobe, run
    sec = float(run([ffprobe(), "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(src)],
                    what="길이 재기").stdout.strip() or 0)
    if sec > hc.AUDIO_MAX_SEC:
        _die(f"{sec:.0f}초는 HeyGen 오디오 상한 {hc.AUDIO_MAX_SEC}초를 넘습니다")

    conf = hc.load_conf()
    engine = a.engine or conf.get("engine", "avatar_v")
    avatar_id = a.avatar_id or conf.get("avatar_id", "")
    if not conf.get("api_key"):
        _die("API 키가 없습니다 — set --api-key 로 넣으세요")
    if not avatar_id:
        _die("아바타를 안 골랐습니다 — avatars 로 look id 를 찾아 "
             "set --avatar-id 로 넣으세요 (조회는 무료입니다)")

    e = hc.estimate(sec, engine)
    print(f"{src.name}  {sec:.1f}초  · 아바타 {avatar_id} · 엔진 {engine}")
    print(f"예상액 ${e['usd']:,.2f}  (초당 ${e['rate']})  "
          f"— **예상입니다.** 실제 차감액은 HeyGen Billing 에서 봅니다")
    if a.dry_run:
        others = "  ".join(f"{k}=${sec*v:,.2f}" for k, v in hc.RATE_USD_PER_SEC.items())
        print(f"엔진별: {others}")
        print("\n--dry-run 입니다 — 호출하지 않았습니다. 0원.")
        return
    if not a.yes:
        try:
            ans = input("부를까요? 돈이 나갑니다 [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("안 불렀습니다. 0원.")
            return

    out = Path(a.out) if a.out else src.with_name(
        f"{src.stem}_{engine}{'.mp4' if a.no_alpha else '.webm'}")

    def tick(st: str, waited: float) -> None:
        print(f"  {st or '대기'} … {waited:.0f}초")

    # ★ Idempotency-Key 를 오디오·엔진으로 고정한다 — 타임아웃 뒤 다시 불러도
    #   같은 요청으로 붙어 **두 번 과금되지 않는다.**
    idem = str(uuid.uuid5(uuid.NAMESPACE_URL, f"try/{src.name}/{engine}/{avatar_id}"))
    got = hc.avatar(src, out, avatar_id=avatar_id, engine=engine,
                    alpha=not a.no_alpha, aspect_ratio=a.aspect,
                    motion_prompt=a.motion or conf.get("motion_prompt", ""),
                    title=f"try-{src.stem}-{engine}", idem=idem, on_tick=tick)
    print(f"\n{out}")
    print(f"  video_id {got['video_id']} · {got['seconds']:.1f}초 · "
          f"예상 ${got['usd_est']:,.2f}")
    print("  HeyGen Billing → Transactions 에서 **실제 차감액**을 대조하세요 — "
          "그 값이 나오면 40분·120강 예산이 실측으로 확정됩니다.")


# ══ CLI ════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(prog="heygen.cli", description="HeyGen 손도구")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="키가 살아 있나 (0원)").set_defaults(fn=cmd_probe)

    p = sub.add_parser("avatars", help="look 목록 — look.id 가 avatar_id (0원)")
    p.add_argument("--q", default="", help="이름에 이 말이 든 것만")
    p.add_argument("--gender", default="", choices=["", "female", "male"])
    p.add_argument("--type", default="studio_avatar",
                   choices=["studio_avatar", "digital_twin", "photo_avatar", ""])
    p.add_argument("--ownership", default="public", choices=["public", "private"])
    p.add_argument("--engine", default="", help="이 엔진을 지원하는 것만 "
                                                "(avatar_iii · avatar_iv · avatar_v)")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--preview", action="store_true", help="미리보기 그림 주소도 찍는다")
    p.add_argument("--raw", action="store_true",
                   help="응답을 그대로 찍는다 — 목록이 0개로 나올 때 원인을 본다")
    p.set_defaults(fn=cmd_avatars)

    p = sub.add_parser("voices", help="보이스 목록 (0원)")
    p.add_argument("--lang", default="", help="영어 이름 — Uzbek · Russian · Korean")
    p.add_argument("--gender", default="", choices=["", "female", "male"])
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--preview", action="store_true")
    p.add_argument("--raw", action="store_true", help="응답을 그대로 찍는다")
    p.set_defaults(fn=cmd_voices)

    p = sub.add_parser("set", help="heygen.local.json 에 넣는다")
    p.add_argument("--api-key", default="")
    p.add_argument("--avatar-id", default="", help="look id")
    p.add_argument("--voice-uz", default="")
    p.add_argument("--engine", default="",
                   choices=["", "avatar_iii", "avatar_iv", "avatar_v"])
    p.add_argument("--motion", default="", help="제스처 지시문")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("try", help="오디오 하나만 부른다 — 엔진 견주기")
    p.add_argument("--audio", required=True)
    p.add_argument("--engine", default="",
                   choices=["", "avatar_iii", "avatar_iv", "avatar_v"])
    p.add_argument("--avatar-id", default="")
    p.add_argument("--aspect", default="9:16",
                   choices=["9:16", "16:9", "1:1", "4:5", "5:4"])
    p.add_argument("--motion", default="")
    p.add_argument("--out", default="")
    p.add_argument("--no-alpha", action="store_true",
                   help="배경 투명(webm) 대신 불투명 mp4")
    p.add_argument("--dry-run", action="store_true", help="예상액만 (0원)")
    p.add_argument("--yes", action="store_true", help="묻지 않고 부른다")
    p.set_defaults(fn=cmd_try)

    a = ap.parse_args()
    try:
        a.fn(a)
    except hc.NotConfigured as e:
        _die(str(e))
    except hc.ApiError as e:
        _die(str(e))


if __name__ == "__main__":
    main()
