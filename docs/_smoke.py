# -*- coding: utf-8 -*-
"""스모크 테스트 — whisper·piper 없이 파이프라인 로직만 검증한다.

45분짜리 가짜 워크스페이스를 만든다: 무음 오디오 + 손으로 지어낸 단어
타임스탬프. 그다음 s3(자막) → s4(분할) → s6(패키지) → check 를 돌려
사람 손 없이 규칙을 다 지키는지 본다.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.common import save_json  # noqa: E402

TOTAL = 2700.0          # 45분
WORDS = ("медицинская сестра должна записать данные пациента в электронную "
         "карту сразу после осмотра потому что позже можно забыть важные "
         "детали и это влияет на качество лечения").split()

ws = ROOT / "output" / "2608262100-smoke"
for sub in ("00", "01", "02"):
    (ws / sub).mkdir(parents=True, exist_ok=True)

# 1) 무음 45분 오디오 — s6이 자를 실제 파일이 필요하다
audio = ws / "01" / "audio.m4a"
if not audio.is_file():
    print("무음 45분 오디오 만드는 중…")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", str(TOTAL), "-c:a", "aac", "-b:a", "64k", str(audio)],
                   check=True)
(ws / "01" / "stt.wav").write_bytes(b"")   # 존재만 확인하니 빈 파일로 둔다
save_json(ws / "01" / "media.json", {"source": "smoke.mp4", "duration": TOTAL, "slides": 0})

# 2) 지어낸 단어 타임스탬프
rnd = random.Random(20260826)
words, t, n_sent = [], 0.6, 0
while t < TOTAL - 6.0:
    n = rnd.randint(8, 15)          # 한 문장 단어 수
    for i in range(n):
        w = rnd.choice(WORDS)
        dur = rnd.uniform(0.28, 0.52)
        if i == n - 1:
            w += "."                # 문장 끝 — s3이 여기서 끊는다
        words.append({"word": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += dur + rnd.uniform(0.02, 0.08)
    n_sent += 1
    # 문장 사이 뜸
    t += rnd.uniform(0.30, 0.45)
    # 슬라이드 넘기는 뜸 — 대략 90초마다
    if n_sent % 7 == 0:
        t += rnd.uniform(0.8, 1.1)
    # 절반쯤에 뚜렷하게 긴 침묵 하나 — s4가 여기서 자르는 게 정답이다
    if 1340.0 < t < 1360.0:
        t += 2.6

save_json(ws / "02" / "words.json",
          {"duration": TOTAL, "language": "ru",
           "segments": [{"start": 0.0, "end": TOTAL, "text": "(가짜)"}],
           "words": words})
print(f"가짜 워크스페이스 — {ws.name} · 단어 {len(words)}개 · 문장 {n_sent}개")
