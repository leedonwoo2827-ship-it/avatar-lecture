# -*- coding: utf-8 -*-
"""P2b — 번역 자막이 없을 때 **대본에서 자막을 만든다.**

    강의/<작업>/scenes.json (우즈베크어 나레이션)
        → 강의/<작업>/subs/sceneNN.<lang>.srt

지금까지는 러시아어 자막이 이미 번역돼 들어왔다(`lecture01_uz.srt`). 새 강의는
우즈베크어 대본만 오는 경우가 있고, 그때 이 단계가 자막을 만든다.

옮기는 일은 `scripts/translate.py` 가 한다 — **Claude Code CLI 로그인(OAuth)** 을
쓰므로 API 키가 필요 없고 구독으로 덮인다. perso 크레딧과는 무관하다.

## 시각은 어떻게 정하나

s1~s7 은 Whisper 가 준 **단어 타임스탬프**로 자막을 끊는다. 여기는 그게 없다 —
아직 음성을 안 만들었거나, 만들었어도 전사를 안 했기 때문이다. 그래서 씬 길이를
**글자 수에 비례해 나눠** 가짜 단어 시각을 만들고, 그 뒤는 진짜 파이프라인과
똑같이 `cues.group_words` 로 문장을 끊고 `enforce_timing` 으로 최소·최대 노출과
겹침을 강제한다. 규칙이 한 벌이라 결과가 s1~s7 과 어긋나지 않는다.

비례 배분은 어디까지나 **추정**이다. 다만 p3_resync 가 뒤에서 실제 음성 길이에
맞춰 다시 재므로 씬 경계는 정확히 맞고, 씬 안에서만 조금 밀린다. 밀림이 눈에
띄면 그때 생성된 음성을 전사해 단어 시각으로 올리면 된다.

★ 끊기는 **옮길 언어의 글자 수 상한**으로 한다. 우즈벡어(46자)로 끊어 놓고
  러시아어(42자)로 옮기면 옮긴 줄이 상한을 넘는다.

    python scripts/p2b_translate.py --task lecture01
    python scripts/p2b_translate.py --task lecture01 --force   # 있어도 다시 만든다
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import ROOT, cue_max_chars, die, load_json, mmss, need, save_json, scene_paths
from scripts.cues import Cue, enforce_timing, group_words, to_srt
from scripts.langs import LANGS, budget_chars, find as find_lang



def pseudo_words(text: str, dur: float) -> list[dict]:
    """나레이션 한 덩이 → **글자 수에 비례해 시각을 나눈** 가짜 단어 목록.

    Whisper 가 없을 때의 대역이다. 진짜 타임스탬프가 아니라는 것을 이름으로
    말해 둔다 — 나중에 이 값을 사실로 믿고 계산을 쌓으면 안 된다.
    """
    words = [w for w in text.split() if w]
    if not words:
        return []
    total = sum(len(w) + 1 for w in words)
    out: list[dict] = []
    t = 0.0
    for w in words:
        share = (len(w) + 1) / total * dur
        out.append({"word": w, "start": t, "end": t + share})
        t += share
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="대본 → 번역 자막")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--from", dest="src", default="uz", help="대본 언어")
    ap.add_argument("--to", dest="dst", default="",
                    help="자막 언어. 쉼표로 여러 개 — `ru,en,ja`. "
                         "«러시아» · «Русский» · «ru» 다 알아듣는다 (기본: scenes.json)")
    ap.add_argument("--force", action="store_true", help="자막이 있어도 다시 만든다")
    ap.add_argument("--budget", type=float, default=8.0, help="Claude 호출 상한(USD)")
    a = ap.parse_args()

    P = scene_paths(a.task)
    meta = load_json(need(P.meta, "p1_scenes.py 를 먼저 돌리세요"))
    out_dir = P.subs
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = meta.get("scenes", [])
    if not rows:
        die("씬이 없습니다 — p1_scenes.py 를 먼저 돌리세요")

    # 언어를 이름으로 받아 코드로 푼다 — 사람이 코드를 외울 이유가 없다.
    want = [w for w in (a.dst or meta.get("sub_lang") or "ru").split(",") if w.strip()]
    langs: list[str] = []
    for w in want:
        iso = find_lang(w)
        if not iso:
            die(f"모르는 언어입니다: {w} — «러시아» · «Русский» · «ru» 처럼 적으세요")
        tag = LANGS[iso]["tag"]
        if tag not in langs:
            langs.append(tag)
    src_iso = find_lang(a.src) or "uzb"

    made_any = False
    for tag in langs:
        iso = next(k for k, v in LANGS.items() if v["tag"] == tag)
        nm = LANGS[iso]["name"]
        todo = []
        for r in rows:
            f = out_dir / f"scene{int(r['no']):02d}.{tag}.srt"
            if not a.force and f.is_file() and f.stat().st_size > 0:
                continue
            if not (r.get("narration") or "").strip():
                continue
            todo.append(r)
        if not todo:
            print(f"[{tag}] {nm} — {len(rows)}씬 모두 있습니다. 건너뜁니다.")
            continue

        # 씬마다 먼저 **끊어 놓고**, 그 언어 전체를 한 번에 옮긴다. 씬별로 부르면
        # 호출이 씬 수만큼 늘고 앞뒤 문맥도 끊긴다.
        maxc = cue_max_chars(tag)
        per_scene: list[tuple[dict, list[Cue]]] = []
        for r in todo:
            dur = float(r.get("voice_dur") or r.get("script_dur") or 0)
            if dur <= 0:
                die(f"{int(r['no']):02d}번 씬 길이를 모릅니다")
            per_scene.append((r, group_words(pseudo_words(r["narration"], dur), tag)))

        flat = [c.text for _, cues in per_scene for c in cues]
        cap = sum(budget_chars(iso, float(r.get("voice_dur") or r.get("script_dur") or 0))
                  for r in todo)
        print(f"[{tag}] {nm} — {len(todo)}씬 · 자막 {len(flat)}줄 옮깁니다 "
              f"(이 길이에 읽힐 수 있는 글자 수 약 {cap:,}자)")

        from scripts.translate import translate_lines
        moved = translate_lines(flat, src_iso[:2], tag, budget_usd=a.budget)
        if len(moved) != len(flat):
            die(f"줄 수가 어긋났습니다: 보낸 {len(flat)} · 받은 {len(moved)}")

        i = 0
        for r, cues in per_scene:
            no = int(r["no"])
            dur = float(r.get("voice_dur") or r.get("script_dur") or 0)
            put = [Cue(text=moved[i + k], start=c.start, end=c.end)
                   for k, c in enumerate(cues)]
            i += len(cues)
            put = enforce_timing(put, total=dur)
            (out_dir / f"scene{no:02d}.{tag}.srt").write_text(to_srt(put), encoding="utf-8")
            over = sum(1 for c in put if len(c.text) > maxc)
            chars = sum(len(c.text) for c in put)
            room = budget_chars(iso, dur)
            r.setdefault("subs_langs", [])
            if tag not in r["subs_langs"]:
                r["subs_langs"].append(tag)
            if tag == langs[0]:                 # 첫 언어를 기본 자막으로 삼는다
                r["subs"] = f"scene{no:02d}.{tag}.srt"
                r["cues"] = len(put)
                r["cue_chars"] = chars
                r["cue_over"] = over
                r["subs_from"] = "translate"
            flags = []
            if over:
                flags.append(f"{over}줄이 {maxc}자 초과")
            if chars > room:
                flags.append(f"길이 초과 {chars}/{room}자 — 화면에 다 못 뜹니다")
            mark = ("   ← " + " · ".join(flags)) if flags else ""
            print(f"  {no:02d}  {mmss(dur):>7}  자막 {len(put):3d}개{mark}")
        made_any = True

    if not made_any:
        print("\n할 일이 없었습니다. 다시 만들려면 --force 를 주세요.")
        return

    meta["sub_langs"] = langs
    meta["sub_lang"] = dst
    save_json(P.meta, meta)
    print(f"\n완료 — {out_dir}")
    print("이제 4 자막에서 문구를 다듬고, 5 아바타·6 빌드로 이어 가세요.")


if __name__ == "__main__":
    main()
