# -*- coding: utf-8 -*-
"""S3b — 자막의 **타임코드는 그대로 두고 본문만 다른 언어로 갈아끼운다**.

    내보내기:  03/subs.ru.srt  →  03/번역할것.ru.txt   (한 줄에 큐 하나)
    들여오기:  03/번역한것.uz.txt + 03/subs.ru.srt  →  03/subs.uz.srt

왜 이 도구가 필요한가. 우즈벡어 자막을 얻는 방법은 두 가지인데 하나는 틀렸다.

  (틀림) 대본 단계에서 만든 우즈벡어 SRT를 그대로 쓴다
         → 그 타임코드는 대본의 추정 길이(est_sec) 기준이다. 실제 음성 길이와
           다르므로 자막이 통째로 어긋난다. 2026-08-26 실측으로 45분 추정 대본이
           35.6분으로 읽혔다 — 10분이 밀린다.
  (맞음) 음성을 전사해 얻은 러시아어 자막의 타임코드를 그대로 쓰고, 본문만 번역해
         갈아끼운다 → 소리와 자막이 어긋날 수가 없다.

## 쓰는 법

### 가장 빠른 길 — Claude 가 바로 옮긴다 (API 키 없음)

    python scripts/s3b_relabel.py --translate --from ru --to uz

`claude` CLI 로 로그인해 둔 세션(OAuth)을 그대로 쓴다. 40줄씩 끊어 보내고
번호로 돌려받아 **줄 수가 어긋나지 않게** 지킨다. 최종 문구는 SME 가 봐야 하니,
이건 SME 에게 넘길 **초벌**을 만드는 자리로 보는 게 맞다.

### 사람이 번역할 때

    python scripts/s3b_relabel.py --export --from ru
      → 03/번역할것.ru.txt 이 나온다. 한 줄이 자막 하나다.

    이 txt를 번역기·SME·외주에 넘긴다. **줄 수를 바꾸지 말라**고 못박아야 한다.
    줄 하나가 자막 하나이므로 줄이 늘거나 줄면 전부 밀린다.

    python scripts/s3b_relabel.py --import 03/번역한것.uz.txt --to uz
      → 03/subs.uz.srt 이 나온다 (타임코드는 ru와 완전히 동일)

    python scripts/s6_package.py --sub-lang uz
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (cue_max_chars, current_workspace, die, mmss, paths, srt_path)
from scripts.cues import Cue, parse_srt, to_srt

HEADER = """# 한 줄이 자막 하나입니다. 줄 수를 바꾸지 마세요 — 줄이 늘거나 줄면 전부 밀립니다.
# `#`으로 시작하는 줄과 빈 줄은 무시됩니다.
# 번역문 한 줄은 {maxc}자 안으로 맞춰 주세요. 줄바꿈을 넣지 마세요.
# 원문: {src}  ({n}줄)
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="자막 타임코드를 유지한 채 본문만 다른 언어로 갈아끼운다")
    ap.add_argument("--translate", action="store_true",
                    help="Claude 로 바로 옮긴다 (API 키 없이 `claude` CLI 로그인 사용). "
                         "타임코드는 그대로 두고 본문만 갈아끼운다")
    ap.add_argument("--budget", type=float, default=8.0,
                    help="--translate 에 쓸 돈 상한(달러). 기본 8")
    ap.add_argument("--export", action="store_true", help="번역용 txt를 내보낸다")
    ap.add_argument("--import", dest="imp", default=None,
                    help="번역한 txt를 들여와 SRT를 만든다")
    ap.add_argument("--from", dest="src_lang", default="ru", help="원문 자막 언어 (기본 ru)")
    ap.add_argument("--to", dest="dst_lang", default="uz", help="만들 자막 언어 (기본 uz)")
    a = ap.parse_args()

    if not (a.export or a.imp or a.translate):
        die("--translate · --export · --import 중 하나를 주세요")

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")

    src = srt_path(P, a.src_lang)
    if not src.is_file():
        die(f"{src} 가 없습니다 — s3_cue.py --lang {a.src_lang} 를 먼저 돌리세요")
    cues = parse_srt(src.read_text(encoding="utf-8-sig"))
    if not cues:
        die(f"{src.name} 에서 큐를 읽지 못했습니다")

    if a.translate:
        from scripts.translate import translate_lines
        print(f"{len(cues)}줄을 {a.src_lang} → {a.dst_lang} 로 옮깁니다 "
              f"(claude CLI 로그인 사용 · API 키 없음)")
        texts = translate_lines([c.text for c in cues], a.src_lang, a.dst_lang,
                                budget_usd=a.budget)
        new = [Cue(text=t, start=c.start, end=c.end) for c, t in zip(cues, texts)]
        out = srt_path(P, a.dst_lang)
        out.write_text(to_srt(new), encoding="utf-8")
        maxc = cue_max_chars(a.dst_lang)
        over = sum(1 for c in new if len(c.text) > maxc)
        print(f"완료 — {out}  ({len(new)}개, 타임코드는 {src.name}과 동일)")
        print(f"  {maxc}자 초과 : {over}개")
        print(f"다음: python scripts/s6_package.py --sub-lang {a.dst_lang}")
        return

    if a.export:
        out = P.subs / f"번역할것.{a.src_lang}.txt"
        maxc = cue_max_chars(a.dst_lang)
        body = HEADER.format(maxc=maxc, src=src.name, n=len(cues))
        body += "\n".join(c.text for c in cues) + "\n"
        out.write_text(body, encoding="utf-8")
        print(f"내보냄 — {out}  ({len(cues)}줄)")
        print(f"이 파일을 번역해 같은 줄 수로 저장한 뒤:")
        print(f"  python scripts/s3b_relabel.py --import \"{out.parent}/번역한것.{a.dst_lang}.txt\" "
              f"--to {a.dst_lang}")
        return

    # 들여오기
    tp = Path(a.imp).expanduser().resolve()
    if not tp.is_file():
        die(f"{tp} 가 없습니다")
    lines = [ln.strip() for ln in tp.read_text(encoding="utf-8-sig").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]

    if len(lines) != len(cues):
        die(f"줄 수가 안 맞습니다 — 원문 {len(cues)}줄인데 번역문은 {len(lines)}줄입니다.\n"
            f"       한 줄이 자막 하나입니다. 줄을 합치거나 나누지 마세요.")

    maxc = cue_max_chars(a.dst_lang)
    new = [Cue(text=t, start=c.start, end=c.end) for c, t in zip(cues, lines)]
    out = srt_path(P, a.dst_lang)
    out.write_text(to_srt(new), encoding="utf-8")

    over = [(i + 1, len(c.text)) for i, c in enumerate(new) if len(c.text) > maxc]
    print(f"완료 — {out}  ({len(new)}개, 타임코드는 {src.name}과 동일)")
    print(f"  {maxc}자 초과 : {len(over)}개" +
          (f"  (가장 긴 것 {max(n for _, n in over)}자, {over[0][0]}번째 줄부터)" if over else ""))
    if over:
        print("  초과한 줄은 문구를 줄여 주세요 — 두 줄로 접지 않습니다.")
    print(f"다음: python scripts/s6_package.py --sub-lang {a.dst_lang}")


if __name__ == "__main__":
    main()
