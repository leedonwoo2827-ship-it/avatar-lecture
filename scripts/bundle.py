# -*- coding: utf-8 -*-
r"""번들 폴더 인식 — 폴더 하나만 가리키면 안에 뭐가 있는지 알아서 찾는다.

강의 하나가 폴더 하나로 온다. 그 안에 영상이 있고, 슬라이드가 있을 수도 있고,
대본이나 자막 원문이 딸려 올 수도 있다. 그게 어디에 어떤 이름으로 들어 있는지는
보내는 쪽마다 다르다 — 외주업체가 `slides\`로 줄지 `슬라이드\`로 줄지, 영상을
폴더 바로 아래 둘지 알 수 없다. 그래서 **경로를 외우지 않고 찾는다.**

    번들폴더\
      아무이름.mp4              영상 — 하나만 있어야 한다
      slides\ 또는 슬라이드\    슬라이드 이미지 (없어도 된다)
      script.json              대본 (선택 — 있으면 씬 수를 견줘 본다)
      subs.*.srt               자막 원문 (선택 — 참고용으로만 둔다)

찾는 자리에 우선순위를 둔다. 슬라이드는 `slides` → `슬라이드` → `_build\slides`
→ 폴더 바로 아래 이미지 순으로 본다. `_build\slides`가 목록에 있는 이유는
`tools\sample`이 만든 시험용 강의가 거기에 PNG를 두기 때문이다.

★ 파이프라인이 만든 것은 재료로 오해하지 않는다 — `output\`, `_seg\`, `_tmp\`,
  `_preview\`는 건너뛴다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.common import IMAGE_EXTS, VIDEO_EXTS

SLIDE_DIRS = ("slides", "슬라이드", "_build/slides", "_build/슬라이드")
SKIP_DIRS = {"output", "_seg", "_tmp", "_preview", "__pycache__", ".venv", ".git"}


def _videos(root: Path) -> list[Path]:
    """폴더 바로 아래, 그리고 한 겹 안까지 본다. 파이프라인 산출물은 건너뛴다."""
    found: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if len(rel.parts) > 2:          # 너무 깊은 건 남의 것으로 본다
            continue
        found.append(p)
    return found


def _slides(root: Path) -> tuple[Path | None, int]:
    for name in SLIDE_DIRS:
        d = root / name
        if d.is_dir():
            n = len([p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS])
            if n:
                return d, n
    # 폴더 바로 아래 흩어져 있는 이미지도 인정한다 (3장 이상일 때만 — 표지 한 장이
    # 섞여 들어온 것을 슬라이드 덱으로 오해하지 않으려는 것)
    loose = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    if len(loose) >= 3:
        return root, len(loose)
    return None, 0


def scan(root: Path) -> SimpleNamespace:
    """번들 폴더 → {root, video, videos, slides, n_slides, script, subs, problems}

    `problems`가 비어 있지 않으면 그대로 진행하면 안 된다. 무엇을 어떻게 고쳐야
    하는지까지 문장으로 담아 둔다.
    """
    root = root.expanduser().resolve()
    problems: list[str] = []

    if not root.is_dir():
        return SimpleNamespace(root=root, video=None, videos=[], slides=None, n_slides=0,
                               script=None, subs=[],
                               problems=[f"폴더가 아닙니다: {root}"])

    vids = _videos(root)
    video = None
    if not vids:
        problems.append("mp4 없음")
    elif len(vids) > 1:
        names = ", ".join(v.name for v in vids)
        problems.append(f"영상 {len(vids)}개 ({names})")
        video = vids[0]
    else:
        video = vids[0]

    slides, n_slides = _slides(root)
    script = root / "script.json" if (root / "script.json").is_file() else None
    subs = sorted(p for p in root.glob("subs.*.srt"))

    return SimpleNamespace(root=root, video=video, videos=vids, slides=slides,
                           n_slides=n_slides, script=script, subs=subs,
                           problems=problems)


def report(b: SimpleNamespace) -> None:
    """찾은 것을 사람이 읽을 수 있게 찍는다. 못 찾은 것도 왜 괜찮은지 말해 준다."""
    print(f"번들 폴더 — {b.root}")
    print(f"  영상       {b.video.name if b.video else '없음'}"
          + (f"   (다른 후보 {len(b.videos) - 1}개)" if len(b.videos) > 1 else ""))
    if b.slides:
        rel = b.slides.relative_to(b.root)
        print(f"  슬라이드   {b.n_slides}장  ({rel if str(rel) != '.' else '폴더 바로 아래'})")
    else:
        print("  슬라이드   없음 — s5(씬 매핑)를 건너뜁니다")
    if b.script:
        print(f"  대본       {b.script.name}")
    if b.subs:
        print(f"  자막 원문  {', '.join(p.name for p in b.subs)}"
              f"   ← 참고용입니다. 파이프라인은 음성에서 자막을 새로 만듭니다")
    for m in b.problems:
        print(f"  문제       {m}")
