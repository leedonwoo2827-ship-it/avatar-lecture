# -*- coding: utf-8 -*-
"""faster-whisper 로딩·전사. 260818 scripts/whisper_util.py를 가져와 **언어를
파라미터로 뺀** 것이 유일한 차이다.

원본은 `language="ko"`가 하드코딩돼 있었다. 음성 언어는 프로젝트마다 다르고, 같은
프로젝트 안에서도 뒤집힐 수 있다. 언어가 코드에 박히면 안 된다.

모델 객체는 호출부가 한 번만 만들어 넘긴다(load_model) — 파일마다 새로 불러오면
같은 1.5GB를 반복해서 읽는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def load_model(model_size: str = "medium", device: str = "cpu", compute_type: str = "int8"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:  # noqa: BLE001
        raise SystemExit(
            "오류: faster-whisper가 없습니다 — setup.bat을 돌리거나 "
            "`pip install faster-whisper` 하세요"
        )

    print(f"모델 불러오는 중 — {model_size} ({device}/{compute_type})")
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe_file(model, audio: Path, *, language: str = "ru",
                    verbose: bool = True) -> Dict[str, Any]:
    """음성 파일 하나 → {duration, language, segments, words}.

    `word_timestamps=True`가 이 파이프라인의 전제다 — 자막 큐(s3)도 청크 분할점
    (s4)도 전부 단어 단위 시각 위에 얹힌다. 끄면 뒷단이 통째로 못 돈다.

    `vad_filter`로 긴 무음을 걸러 낸다. 45분 강의에는 슬라이드 넘기는 뜸이 여럿
    있고, 그걸 그대로 두면 whisper가 없는 말을 지어내 채우는 일이 있다.
    """
    segments, info = model.transcribe(
        str(audio),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    seg_rows: List[Dict[str, Any]] = []
    word_rows: List[Dict[str, Any]] = []
    for seg in segments:
        seg_rows.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                         "text": seg.text.strip()})
        for w in (seg.words or []):
            word_rows.append({"word": w.word.strip(), "start": round(w.start, 2),
                              "end": round(w.end, 2)})
        if verbose:
            print(f"  {seg.start:7.1f}s  {seg.text.strip()[:60]}")

    return {"duration": round(float(info.duration), 2),
            "language": language,
            "segments": seg_rows, "words": word_rows}
