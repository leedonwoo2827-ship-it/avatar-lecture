# -*- coding: utf-8 -*-
"""S2 — 강의 오디오 전체를 한 번 전사해 **단어 타임스탬프**를 얻는다.

    output/NN/01/stt.wav  →  output/NN/02/words.json  {duration, language, segments, words}

이 파일이 뒷단 전부의 바탕이다 — s3(자막 큐)·s4(청크 분할점)·s5(씬 매핑)가 전부
여기서 나온 시각 위에 얹힌다.

언어는 `--lang`으로 준다. 기본값은 `config.local.json` 에 있다(저장소에 안 남긴다).

★ **언어마다 전사 정확도가 크게 다르다.** 자막도 컷도 전부 이 타임스탬프 위에
  얹히므로, 정확도가 낮은 언어를 음성으로 두면 뒷단이 통째로 흔들린다. 그런
  언어라면 02/words.json 을 사람이 더 손봐야 한다고 보는 게 맞다.

45분짜리를 medium/CPU로 돌리면 오래 걸린다. 처음엔 `--model small`로 파이프라인이
끝까지 도는지부터 확인하고, 품질이 필요할 때 medium으로 다시 돌리는 편이 낫다.
(모델은 첫 실행에서 한 번 내려받는다 — medium이 약 1.5GB.)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import current_workspace, local_config, mmss, need, paths, save_json

CFG = local_config()
from scripts.whisper_util import load_model, transcribe_file


def main() -> None:
    ap = argparse.ArgumentParser(description="강의 오디오 전사 — 단어 타임스탬프")
    ap.add_argument("--lang", default=CFG["audio_lang"],
                    help="음성 언어. 기본값은 config.local.json 의 audio_lang")
    ap.add_argument("--model", default="medium", help="whisper 모델 크기 (medium 기본, small이면 빠름)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute-type", default="int8")
    a = ap.parse_args()

    P = paths(current_workspace())
    print(f"워크스페이스 — {P.ws.name}")
    need(P.sttwav, "s1_ingest.py를 먼저 돌리세요")

    model = load_model(a.model, a.device, a.compute_type)
    print(f"전사 중… (언어 {a.lang} · 모델 {a.model})")
    t0 = time.time()
    data = transcribe_file(model, P.sttwav, language=a.lang)
    took = time.time() - t0

    save_json(P.words, data)
    ratio = took / max(data["duration"], 1.0)
    print(f"완료 — {mmss(data['duration'])} · 문장 {len(data['segments'])}개 · "
          f"단어 {len(data['words'])}개")
    print(f"       전사에 {took / 60:.1f}분 걸렸습니다 (영상 길이의 {ratio:.2f}배)")
    print(f"       → 45분짜리 100강이면 대략 {ratio * 45 * 100 / 60:.0f}시간")
    print(f"       {P.words}")
    print(f"다음: python scripts/s3_cue.py --lang {a.lang}")


if __name__ == "__main__":
    main()
