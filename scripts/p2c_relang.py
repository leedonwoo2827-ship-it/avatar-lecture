# -*- coding: utf-8 -*-
r"""P2c — **있는 자막을 다른 언어로.** 타임코드는 그대로 둔다.

    강의/<작업>/subs/sceneNN.<src>.srt  →  강의/<작업>/subs/sceneNN.<dst>.srt

## p2b_translate.py 와 무엇이 다른가

`p2b` 는 **자막이 없을 때** 대본에서 만든다. 씬 길이를 글자 수에 비례해 나눠
«가짜 단어 시각»을 만들고 거기서 큐를 끊는다 — 추정이다.

여기는 **자막이 이미 있을 때** 쓴다. 러시아어 자막은 실제 음성에 맞춰 작성된
것이라 p3_resync 가 재 보면 대본과 0.06초밖에 안 어긋난다(2026-09-02 실측).
그 정확도를 버리고 다시 추정할 이유가 없다. **큐도 시각도 그대로 두고 본문만
갈아끼운다.** 큐 개수가 1:1 로 보존되므로 그 뒤 단계가 전부 그대로 돈다.

## 시간 예산 — 이것이 «LLM 으로 싱크를 맞춘다» 이다

큐마다 화면에 뜨는 시간을 알고 있다. 그 시간에 그 언어로 읽힐 글자 수
(`langs.budget_chars` = 초 x cps)를 함께 보내, 옮기는 쪽이 **그 안에서 표현을
고르게** 한다. 한국어는 7자/초, 러시아어는 14자/초라 3초짜리 줄에 들어갈 양이
두 배 넘게 차이 난다 — 예산을 안 주면 뜻은 맞는데 다 못 읽는 자막이 나온다.

시각 자체는 **옮기지 않는다.** 실제 음성에서 나온 값이라 손대면 소리와 어긋난다.

## 용어집

`용어집.json` 이 있으면 규칙으로 박아 보낸다(scripts/glossary.py). 전공 용어가
강의 안에서 흔들리지 않게 하는 유일한 방법이다.

## 나온 뒤

    p3_resync.py   subs/ 의 **모든 언어**를 음성 길이에 맞춘다 → aligned/
    p5_compose.py  기본 언어만 픽셀에 굽고 **나머지는 트랙으로 얹는다**
                   → 언어를 열 개 더해도 굽는 일은 한 번이다. 아바타는 안 건드린다.

    python scripts/p2c_relang.py --task lecture01 --to ko
    python scripts/p2c_relang.py --task lecture01 --to en --from ru --force
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import ROOT, cue_max_chars, die, load_json, mmss, need, save_json, scene_paths
from scripts.cues import parse_srt, to_srt
from scripts.langs import LANGS, budget_chars, find as find_lang



def main() -> None:
    ap = argparse.ArgumentParser(description="있는 자막을 다른 언어로 (시각 유지)")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--to", dest="dst", required=True, help="옮길 언어 (ko · en · kk …)")
    ap.add_argument("--from", dest="src", default="",
                    help="원본 자막 언어 (기본: scenes.json 의 sub_lang)")
    ap.add_argument("--scenes", default="", help="이 씬만 (기본: 전부)")
    ap.add_argument("--force", action="store_true", help="이미 있어도 다시 옮긴다")
    ap.add_argument("--budget", type=float, default=8.0, help="Claude 호출 상한(USD)")
    ap.add_argument("--no-glossary", action="store_true", help="용어집을 쓰지 않는다")
    a = ap.parse_args()

    P = scene_paths(a.task)
    meta = load_json(need(P.meta, "p1_scenes.py 를 먼저 돌리세요"))
    src_tag = a.src or meta.get("sub_lang") or "ru"
    dst_tag = LANGS[find_lang(a.dst)]["tag"]
    if dst_tag == src_tag:
        die(f"원본과 옮길 언어가 같습니다 ({src_tag}) — --to 를 다른 언어로 주세요")

    rows = [r for r in meta["scenes"] if r.get("subs")]
    if a.scenes:
        from scripts.p1_scenes import parse_range
        want = set(parse_range(a.scenes, len(meta["scenes"])))
        rows = [r for r in rows if r["no"] in want]
    if not rows:
        die("자막이 없습니다 — p1_scenes.py 를 먼저 돌리세요")

    sub_dir = P.subs
    todo: list[tuple[dict, Path, Path]] = []
    for r in rows:
        no = int(r["no"])
        s = sub_dir / f"scene{no:02d}.{src_tag}.srt"
        d = sub_dir / f"scene{no:02d}.{dst_tag}.srt"
        if not s.is_file():
            die(f"{s.name} 가 없습니다 — 원본 자막 언어를 --from 으로 맞춰 주세요")
        if d.is_file() and not a.force:
            continue
        todo.append((r, s, d))

    if not todo:
        print(f"{dst_tag} 자막이 이미 다 있습니다 — 다시 만들려면 --force")
        return

    # ── 용어집 ──────────────────────────────────────────────────────────────
    glos: dict[str, str] = {}
    if not a.no_glossary:
        from scripts.glossary import terms_for
        glos = terms_for(dst_tag)
        if glos:
            print(f"용어집 {len(glos)}개 적용 ({src_tag} → {dst_tag})")
        else:
            print(f"용어집이 비어 있습니다 — 전공 용어가 흔들릴 수 있습니다. "
                  f"`python scripts/glossary.py extract --to {dst_tag}` 를 먼저 "
                  f"돌리는 편이 낫습니다")

    # ── 큐를 한 줄씩 모아 **한 번에** 옮긴다 ─────────────────────────────────
    # ★ 씬마다 따로 부르면 씬 경계에서 용어가 흔들린다(같은 말을 다른 호출이
    #   각자 판단한다). 전부 모아 보내면 한 흐름 안에서 판단한다. translate.py
    #   가 40줄씩 끊어 보내므로 한 번에 다 보내도 어긋난 묶음만 다시 한다.
    texts: list[str] = []
    secs: list[float] = []
    spans: list[tuple[dict, Path, Path, int, int]] = []
    for r, s, d in todo:
        cues = parse_srt(s.read_text(encoding="utf-8-sig"))
        i0 = len(texts)
        texts += [c.text for c in cues]
        secs += [max(0.0, c.end - c.start) for c in cues]
        spans.append((r, s, d, i0, len(texts)))

    iso = find_lang(dst_tag)
    maxc = cue_max_chars(dst_tag)
    tight = sum(1 for t, sec in zip(texts, secs)
                if sec > 0 and budget_chars(iso, sec) < 12)
    print(f"{len(todo)}씬 · 큐 {len(texts)}개 · {src_tag} → {dst_tag} "
          f"({LANGS[iso]['cps']:.0f}자/초 · 한 줄 {maxc}자)")
    if tight:
        print(f"  시간이 아주 짧은 큐 {tight}개 — 그 줄은 많이 줄여야 합니다")

    from scripts.translate import translate_lines
    out = translate_lines(texts, src_tag, dst_tag, secs=secs, glossary=glos,
                          budget_usd=a.budget)

    # ── 되쓴다. **시각은 원본 그대로.** ─────────────────────────────────────
    over_total = 0
    for r, s, d, i0, i1 in spans:
        cues = parse_srt(s.read_text(encoding="utf-8-sig"))
        new = [type(c)(text=out[i0 + k], start=c.start, end=c.end)
               for k, c in enumerate(cues)]
        d.write_text(to_srt(new), encoding="utf-8")
        over = sum(1 for c in new
                   if (c.end - c.start) > 0
                   and len(c.text) > budget_chars(iso, c.end - c.start))
        over_total += over
        mark = f"   ← 읽을 시간이 모자란 줄 {over}개" if over else ""
        print(f"  {int(r['no']):02d}  큐 {i1-i0:3d}개  {d.name}{mark}")

    # 어느 씬에 무슨 언어가 생겼는지 남긴다 — 화면이 이걸 읽어 탭을 만든다
    langs = sorted({p.name.split(".")[1] for p in sub_dir.glob("scene*.*.srt")
                    if p.name.count(".") >= 2})
    meta["sub_langs"] = langs
    save_json(P.meta, meta)

    print(f"\n자막 언어: {', '.join(langs)}")
    if over_total:
        print(f"읽을 시간이 모자란 줄이 모두 {over_total}개입니다 — "
              f"웹 화면의 «자막 다듬기»에서 손으로 줄이면 됩니다 (시각은 안 건드립니다)")
    print(f"다음: python scripts/p3_resync.py --task {a.task}   "
          f"(subs/ 의 모든 언어를 음성 길이에 맞춥니다)")
    print(f"      그다음 p5_compose.py — 기본 언어만 굽고 나머지는 트랙으로 얹습니다 "
          f"(아바타 재렌더 없음)")


if __name__ == "__main__":
    main()
