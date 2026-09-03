# -*- coding: utf-8 -*-
r"""아바타 붙이고 합치기 — **한 번에.**

    강의/<작업>/05/bundleNN/  에 내려받은 영상을 놓고 이것을 부른다.
        → p4_avatar.py --engine drop     영상을 읽어 «어디서부터 몇 초»를 적는다
        → p5_compose.py --style both     전면샷·여백형 둘 다 굽는다
        → 09/ 폴더를 연다

업체에서 받아 온 뒤 할 일이 «두 줄을 정확히 치는 것» 이면 하루에 몇 번씩 하는
일이 부담이 된다. 120강이면 그 부담이 그대로 쌓인다. 그래서 한 번으로 묶는다.

★ **어느 묶음이 왔는지 알아서 찾는다.** 05 를 훑어 영상이 새로 들어온 묶음만
  붙인다 — 이미 붙인 것은 건드리지 않는다.

    python scripts/p45_attach.py                     가장 최근 강의
    python scripts/p45_attach.py --task 001
    python scripts/p45_attach.py --task 001 --style panel
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import LECTURES, die, load_json, mmss, scene_paths

VIDEO_EXTS = {".webm", ".mp4", ".mov", ".mkv", ".m4v"}
PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent


def latest_task() -> str:
    """가장 최근에 손댄 강의. `scenes.json` 이 있는 폴더 중 제일 나중 것."""
    got = [d for d in LECTURES.iterdir()
           if d.is_dir() and (d / "scenes.json").is_file()] if LECTURES.is_dir() else []
    if not got:
        die(f"강의를 찾지 못했습니다 — {LECTURES} 안에 폴더를 만들고 p1 부터 돌리세요")
    got.sort(key=lambda d: (d / "scenes.json").stat().st_mtime)
    return got[-1].name


def run(args: list[str], what: str) -> None:
    print()
    print(f"── {what} " + "─" * max(0, 56 - len(what)))
    r = subprocess.run([PY] + args, cwd=str(ROOT))
    if r.returncode != 0:
        die(f"{what} 에서 멈췄습니다 — 위 메시지를 확인하세요")


def main() -> None:
    ap = argparse.ArgumentParser(description="아바타 붙이고 합치기")
    ap.add_argument("--task", default="", help="강의 폴더 이름 (기본: 가장 최근)")
    ap.add_argument("--style", default="both", choices=["both", "full", "panel"])
    ap.add_argument("--avatar-h", default="0.60")
    ap.add_argument("--from", dest="src", default="",
                    help="내려받은 영상이 있는 폴더 (기본: 묶음 폴더를 본다)")
    ap.add_argument("--no-open", action="store_true", help="끝나고 폴더를 열지 않는다")
    a = ap.parse_args()

    task = a.task or latest_task()
    P = scene_paths(task)
    if not P.meta.is_file():
        die(f"{P.meta} 가 없습니다 — p1 부터 돌리세요")
    meta = load_json(P.meta)

    # ── 어느 묶음에 영상이 왔나 ────────────────────────────────────────────
    bundles = meta.get("bundles") or []
    if not bundles:
        die(f"묶음이 없습니다 — `python scripts/p3b_voicepack.py --task {task}` 를 "
            f"먼저 돌리세요")
    look_root = Path(a.src).expanduser().resolve() if a.src else P.upload
    ready, empty = [], []
    for b in bundles:
        bdir = look_root if a.src else (P.upload / str(b.get("dir") or ""))
        vids = [x for x in bdir.rglob("*")
                if x.is_file() and x.suffix.lower() in VIDEO_EXTS] if bdir.is_dir() else []
        (ready if vids else empty).append((b, vids))

    print(f"강의 {task} — 묶음 {len(bundles)}개")
    for b, vids in ready:
        names = ", ".join(x.name for x in vids[:3]) + (" …" if len(vids) > 3 else "")
        print(f"  ✔ {b.get('dir', '')}  씬 {b['scenes'][0]}~{b['scenes'][-1]}  "
              f"{mmss(float(b['sec']))}  ← {len(vids)}개 ({names})")
    for b, _ in empty:
        print(f"  · {b.get('dir', '')}  씬 {b['scenes'][0]}~{b['scenes'][-1]}  "
              f"{mmss(float(b['sec']))}  아직 영상 없음")

    if not ready:
        print()
        print("붙일 영상이 없습니다.")
        print(f"업체에서 받은 영상을 묶음 폴더에 넣으세요 — {P.upload}")
        print("폴더마다 «올릴음성.mp3» 을 올리고, 받은 영상을 그 폴더에 되돌려 놓으면 됩니다.")
        if not a.no_open and P.upload.is_dir():
            os.startfile(str(P.upload))  # noqa: S606 — 폴더를 열어 주는 것뿐이다
        return

    # ── 붙이고 합친다 ──────────────────────────────────────────────────────
    nos = sorted({int(n) for b, _ in ready for n in b["scenes"]})
    scenes_arg = ",".join(str(n) for n in nos)

    p4 = ["scripts/p4_avatar.py", "--task", task, "--engine", "drop",
          "--scenes", scenes_arg]
    if a.src:
        p4 += ["--from", a.src]
    run(p4, "아바타 붙이기")

    run(["scripts/p5_compose.py", "--task", task, "--style", a.style,
         "--avatar-h", a.avatar_h, "--scenes", scenes_arg, "--join"], "합치기")

    print()
    print(f"완료 — {P.dist}")
    if not a.no_open and P.dist.is_dir():
        os.startfile(str(P.dist))  # noqa: S606


if __name__ == "__main__":
    main()
