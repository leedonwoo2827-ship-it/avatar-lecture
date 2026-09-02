# -*- coding: utf-8 -*-
"""P1 — 대본 한 편에서 씬을 떼어 낸다 (앞으로 만드는 쪽 파이프라인의 첫 단계).

s1~s7 이 **완성된 mp4를 헐어** perso에 올릴 재료로 만드는 길이라면, p1~p4 는
반대로 **대본과 슬라이드에서 영상을 세우는** 길이다. 시연본을 한 번 만들어 본
뒤라 재료가 이미 다 있다 — 대본, 번역 자막, 슬라이드. 없는 건 아바타와 음성뿐이고
그 둘만 perso가 채운다.

    대본(uzbek_script.txt) + 번역 자막(*.srt) + 슬라이드(NNN.png)
        → build/<task>/scenes.json
                       subs/scene01.<lang>.srt   0초부터 다시 매긴 타임코드
                       slides/001.png …          그 씬이 쓸 슬라이드

★ 자막은 **씬마다 0초부터 다시 매긴다** — s6_package.py 가 조각마다 하는 것과
  같은 이유다. 씬 하나가 곧 영상 하나이므로 그 안에서는 0초가 시작이어야 한다.

★ 큐를 씬에 나눠 담을 때 **가운데 시각**으로 판단한다. 경계에 걸친 큐를 양쪽에
  다 넣으면 자막이 두 번 뜨고, 양쪽에서 다 빼면 한 줄이 사라진다. 가운데를 보면
  어느 쪽이든 정확히 한 번 들어간다.

    python scripts/p1_scenes.py --task lecture01 --scenes 1-8 \
        --script  _context11/last-uz-output/uzbek_script.txt \
        --subs    _context11/last-uz-output/lecture01_uz.srt \
        --slides  _context11/last-ne-output \
        --sub-lang ru
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import ROOT, cue_max_chars, die, local_config, mmss, save_json
from scripts.cues import parse_srt, to_srt

BUILD = ROOT / "build"

# `01. [00:00:00 ~ 00:01:11] (1분 11초)  Добро пожаловать: цели занятия`
# 괄호 안의 길이는 사람 읽으라고 적힌 것이라 안 쓴다 — 시각 두 개가 사실이다.
SCENE_RE = re.compile(
    r"^(\d{1,3})\.\s*\[\s*(\d\d:\d\d:\d\d)\s*~\s*(\d\d:\d\d:\d\d)\s*\]"
    r"\s*(?:\([^)]*\))?\s*(.*)$"
)


def hhmmss(s: str) -> int:
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + int(sec)


def parse_script(text: str) -> list[dict]:
    """대본 → 씬 목록. 머리말·꼬리말은 씬 앞뒤라 저절로 걸러진다."""
    scenes: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        m = SCENE_RE.match(line)
        if m:
            cur = {"no": int(m.group(1)), "start": hhmmss(m.group(2)),
                   "end": hhmmss(m.group(3)), "title": m.group(4).strip(),
                   "narration": ""}
            scenes.append(cur)
            continue
        if cur is None or not line or line.startswith("총 길이"):
            continue
        cur["narration"] = (cur["narration"] + " " + line).strip()
    return scenes


def parse_range(spec: str, n: int) -> list[int]:
    """`1-8` · `3` · `1,4,7` · `all` → 씬 번호 목록."""
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(range(1, n + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                out += list(range(int(a), int(b) + 1))
            except ValueError:
                die(f"씬 범위를 못 읽었습니다: {part}")
        else:
            try:
                out.append(int(part))
            except ValueError:
                die(f"씬 번호를 못 읽었습니다: {part}")
    return sorted(set(out))


def main() -> None:
    cfg = local_config()
    ap = argparse.ArgumentParser(description="대본 → 씬별 재료")
    ap.add_argument("--task", default="lecture01", help="build/ 안에 만들 폴더 이름")
    ap.add_argument("--script", required=True, help="대본 txt")
    ap.add_argument("--subs", default="", help="번역 자막 srt (영상 전체 타임코드). "
                    "없으면 자막을 비워 두고 p2b_translate.py 가 대본에서 만든다")
    ap.add_argument("--slides", required=True, help="NNN.png 이 있는 폴더")
    ap.add_argument("--scenes", default="1-8", help="만들 씬 (기본 1-8)")
    ap.add_argument("--sub-lang", default=cfg["sub_lang"])
    a = ap.parse_args()

    script_p = Path(a.script).expanduser().resolve()
    subs_p = Path(a.subs).expanduser().resolve() if a.subs else None
    slides_p = Path(a.slides).expanduser().resolve()
    if not script_p.is_file():
        die(f"대본 파일이 없습니다: {script_p}")
    if a.subs and not subs_p.is_file():
        die(f"자막 파일이 없습니다: {subs_p}")
    if not slides_p.is_dir():
        die(f"슬라이드 폴더가 없습니다: {slides_p}")

    scenes = parse_script(script_p.read_text(encoding="utf-8-sig"))
    if not scenes:
        die(f"{script_p.name} 에서 씬을 하나도 못 찾았습니다 — "
            "`01. [00:00:00 ~ 00:01:11] 제목` 꼴이어야 합니다")
    want = parse_range(a.scenes, len(scenes))
    picked = [s for s in scenes if s["no"] in want]
    if not picked:
        die(f"{a.scenes} 에 해당하는 씬이 없습니다 (대본에는 {len(scenes)}개 있습니다)")

    # 번역 자막이 없으면 빈 채로 둔다 — p2b_translate.py 가 대본에서 만든다.
    # 여기서 죽이지 않는 이유: 우즈베크어 대본만 오는 강의가 있고, 그때도
    # 씬 분해와 슬라이드 짝짓기는 그대로 되어야 한다.
    cues = []
    if subs_p:
        cues = parse_srt(subs_p.read_text(encoding="utf-8-sig"))
        if not cues:
            die(f"{subs_p.name} 에서 자막 큐를 못 읽었습니다")

    task = BUILD / a.task
    (task / "subs").mkdir(parents=True, exist_ok=True)
    (task / "slides").mkdir(parents=True, exist_ok=True)

    maxc = cue_max_chars(a.sub_lang)
    rows: list[dict] = []
    total = 0.0
    print(f"대본 {len(scenes)}씬 중 {len(picked)}씬 — {task}")
    for s in picked:
        no, st, en = s["no"], float(s["start"]), float(s["end"])
        dur = en - st

        # 큐를 가운데 시각으로 이 씬에 넣을지 정한다 — 경계에 걸친 큐가
        # 두 번 뜨거나 사라지지 않게.
        mine = [c for c in cues if st <= (c.start + c.end) / 2 < en]
        srt_name = f"scene{no:02d}.{a.sub_lang}.srt"
        if cues:
            (task / "subs" / srt_name).write_text(to_srt(mine, offset=st), encoding="utf-8")

        # 슬라이드는 씬 번호 = 파일 앞 숫자. 확장자·뒷말은 자유다
        # (이미지프롬프트 json 의 file_naming 규칙 그대로).
        hit = None
        for p in sorted(slides_p.iterdir()):
            if not p.is_file():
                continue
            m = re.match(r"^(\d+)", p.stem)
            if m and int(m.group(1)) == no and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                hit = p
                break
        slide_name = ""
        if hit:
            slide_name = f"{no:03d}{hit.suffix.lower()}"
            shutil.copy2(hit, task / "slides" / slide_name)

        over = [c.text for c in mine if len(c.text) > maxc]
        chars = sum(len(c.text) for c in mine)
        rows.append({
            "no": no, "title": s["title"],
            "script_start": round(st, 3), "script_end": round(en, 3),
            "script_dur": round(dur, 3),
            "narration": s["narration"], "narration_chars": len(s["narration"]),
            "slide": slide_name, "subs": srt_name,
            "cues": len(mine), "cue_chars": chars, "cue_over": len(over),
        })
        total += dur
        flag = "" if hit else "   ← 슬라이드 없음"
        warn = f"   ← {len(over)}줄이 {maxc}자를 넘습니다" if over else ""
        print(f"  {no:02d}  {mmss(dur):>7}  자막 {len(mine):3d}개  "
              f"슬라이드 {slide_name or '—':<9}  {s['title'][:34]}{flag}{warn}")

    save_json(task / "scenes.json", {
        "task": a.task, "sub_lang": a.sub_lang,
        "script": str(script_p), "subs": str(subs_p or ""), "slides": str(slides_p),
        "total_sec": round(total, 3), "scenes": rows,
    })
    miss = [r["no"] for r in rows if not r["slide"]]
    print(f"\n{len(rows)}씬 · 합계 {mmss(total)} · 자막 {sum(r['cues'] for r in rows)}개")
    if not cues:
        print("번역 자막이 없습니다 — 다음 단계 «다국어 자막» 이 대본에서 만듭니다 "
              "(scripts/p2b_translate.py).")
    if miss:
        print(f"슬라이드를 못 찾은 씬: {miss} — {slides_p} 를 확인하세요")
    print(f"완료 — {task / 'scenes.json'}")


if __name__ == "__main__":
    main()
