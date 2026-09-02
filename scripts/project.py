# -*- coding: utf-8 -*-
"""작업 폴더 규칙 — 어디에 무엇을 넣고 무엇이 나오는가.

hyper-close-frame(260831) 과 **같은 방식**으로 맞춘다. 두 도구를 오가며 쓰는데
폴더 규칙이 다르면 매번 헷갈린다.

    projects/<YYMMDD-이름>/
      00_원본/        ← 사람이 넣는 **유일한** 폴더
          대본.txt              씬 번호·시각·제목·나레이션
          자막.<lang>.srt       번역 자막 — 있으면 번역 단계를 건너뛴다
          슬라이드/             001.png 002.png … (앞 숫자 = 씬 번호)
          음성원본.mp4          (선택) 시연본 — 크레딧 0 으로 소리를 떼어 올 때
      01_씬/          p1  scenes.json · 씬별 자막 · 슬라이드 사본
      02_음성/        p2  sceneNN.wav
      03_자막/        p3  목소리 길이에 맞춘 sceneNN.<lang>.srt
      04_아바타/      p4  sceneNN.mov (배경 투명)
      05_완성/        p5  sceneNN.mp4 · all.mp4

★ **01~05 는 언제 지워도 된다.** 전부 00_원본 에서 다시 만들어진다. 사람이 만든
  것과 기계가 만든 것을 폴더 단위로 갈라 두면 "이거 지워도 되나"를 물을 일이 없다.

## 00_원본 에 넣는 규칙

파일 **이름이 곧 뜻**이다. 설정 파일을 따로 두지 않는다 — 폴더를 열면 규칙이 보여야 한다.

  대본        `*.txt` 하나. `01. [00:00:00 ~ 00:01:11] 제목` 다음 줄부터 나레이션.
  자막        `*.<lang>.srt`. **파일명의 언어 코드가 자막 언어다** — `자막.ru.srt` → 러시아어.
              없으면 번역 단계를 돌려야 한다(Claude, 추가 과금 없음).
  슬라이드    `슬라이드/` 안에 이미지. **앞 숫자만 맞으면 된다** — `003.png` 도
              `003_저축함수.png` 도 3번 씬이다(이미지프롬프트 json 의 file_naming 규칙 그대로).
  음성원본    `*.mp4` 하나. 있으면 p2 가 `--engine source` 로 **크레딧 0** 에 소리를 떼어 온다.
              없으면 무음이나 perso TTS 를 쓴다.

그 밖의 파일은 무시한다 — 메모나 원본 문서를 같이 두어도 된다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"

SRC, SCENE, VOICE, SUBS, AVATAR, FINAL = (
    "00_원본", "01_씬", "02_음성", "03_자막", "04_아바타", "05_완성")
STAGE_DIRS = [SRC, SCENE, VOICE, SUBS, AVATAR, FINAL]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

# `자막.ru.srt` · `subs.ru.srt` · `lecture01_uz.srt` 어느 쪽이든 언어 코드를 뽑는다.
_LANG_IN_NAME = re.compile(r"[._]([a-z]{2})$", re.I)


def paths(task: str) -> SimpleNamespace:
    root = PROJECTS / task
    return SimpleNamespace(
        task=task, root=root,
        src=root / SRC, src_slides=root / SRC / "슬라이드",
        scene=root / SCENE, meta=root / SCENE / "scenes.json",
        scene_subs=root / SCENE / "subs", scene_slides=root / SCENE / "slides",
        voice=root / VOICE,
        subs=root / SUBS,
        avatar=root / AVATAR,
        final=root / FINAL, joined=root / FINAL / "all.mp4",
        ass=root / FINAL / "_ass",
    )


def sub_lang_of(p: Path) -> str:
    """자막 파일 이름에서 언어 코드를 뽑는다. 못 뽑으면 빈 문자열."""
    m = _LANG_IN_NAME.search(p.stem)
    return m.group(1).lower() if m else ""


def discover(src: Path) -> dict:
    """`00_원본/` 을 규칙대로 훑는다. 없는 건 빈 문자열로 둔다 — 여기서 죽지 않는다.

    무엇을 못 찾았는지는 부르는 쪽이 판단한다. p1 은 대본이 없으면 못 돌지만,
    화면은 "대본이 없습니다" 라고 띄우기만 하면 되기 때문이다.
    """
    out = {"script": "", "subs": "", "sub_lang": "", "slides": "", "source": "",
           "problems": []}
    if not src.is_dir():
        out["problems"].append(f"{src} 가 없습니다")
        return out

    txts = sorted(p for p in src.glob("*.txt") if p.is_file())
    if txts:
        out["script"] = str(txts[0])
        if len(txts) > 1:
            out["problems"].append(
                f"대본 후보가 {len(txts)}개입니다 — {txts[0].name} 을 씁니다")
    else:
        out["problems"].append("대본(.txt)이 없습니다")

    srts = sorted(p for p in src.glob("*.srt") if p.is_file())
    if srts:
        out["subs"] = str(srts[0])
        out["sub_lang"] = sub_lang_of(srts[0])
        if not out["sub_lang"]:
            out["problems"].append(
                f"{srts[0].name} 에서 언어 코드를 못 읽었습니다 — `자막.ru.srt` 처럼 이름을 지으세요")

    slides = src / "슬라이드"
    if slides.is_dir() and any(p.suffix.lower() in IMAGE_EXTS for p in slides.iterdir()):
        out["slides"] = str(slides)
    else:
        # 슬라이드/ 가 없으면 00_원본 바로 아래에 번호 이미지가 있는지 본다
        loose = [p for p in src.iterdir()
                 if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                 and re.match(r"^\d+", p.stem)]
        if loose:
            out["slides"] = str(src)
        else:
            out["problems"].append("슬라이드 이미지가 없습니다")

    vids = sorted(p for p in src.glob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    if vids:
        out["source"] = str(vids[0])
    return out


def slide_for(slides_dir: Path, no: int) -> Path | None:
    """씬 번호 → 슬라이드 파일. **앞 숫자만** 맞으면 된다."""
    if not slides_dir.is_dir():
        return None
    for p in sorted(slides_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        m = re.match(r"^(\d+)", p.stem)
        if m and int(m.group(1)) == no:
            return p
    return None


README = """# 00_원본 — 여기에만 넣습니다

이 폴더가 **사람이 채우는 유일한 자리**입니다. 옆의 01~05 는 전부 여기서
다시 만들어지므로 언제 지워도 됩니다.

| 넣을 것 | 이름 규칙 | 없으면 |
|---|---|---|
| 대본 | `*.txt` 하나 | 못 돕니다 |
| 번역 자막 | `*.<언어코드>.srt` — 예 `자막.ru.srt` | 번역 단계를 돌려야 합니다 |
| 슬라이드 | `슬라이드/` 안에 `001.png` `002.png` … | 못 돕니다 |
| 음성 원본 | `*.mp4` 하나 (시연본) | 무음이나 perso TTS 를 씁니다 |

## 대본 형식

```
01. [00:00:00 ~ 00:01:11] (1분 11초)  씬 제목
여기부터 나레이션입니다. 여러 줄이어도 한 문단으로 붙습니다.

02. [00:01:11 ~ 00:02:24] (1분 13초)  다음 씬 제목
...
```

괄호 안의 길이는 사람이 읽으라고 적는 것이고, 실제로는 **시각 두 개**만 씁니다.

## 슬라이드 이름

**앞 숫자만 맞으면 됩니다.** `003.png` 도 `003_전자차트.png` 도 3번 씬입니다.
확장자는 png · jpg · jpeg · webp 를 받습니다.
"""


def new_project(name: str) -> Path:
    """`projects/YYMMDD-이름/` 뼈대를 만든다. 이미 있으면 그대로 쓴다."""
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "", name) or "untitled"
    task = f"{datetime.now().strftime('%y%m%d')}-{slug}"
    P = paths(task)
    for d in STAGE_DIRS:
        (P.root / d).mkdir(parents=True, exist_ok=True)
    P.src_slides.mkdir(parents=True, exist_ok=True)
    rp = P.src / "README.md"
    if not rp.is_file():
        rp.write_text(README, encoding="utf-8")
    return P.root


def list_projects() -> list[str]:
    if not PROJECTS.is_dir():
        return []
    return sorted((p.name for p in PROJECTS.iterdir() if p.is_dir()), reverse=True)
