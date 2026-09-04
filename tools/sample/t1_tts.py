# -*- coding: utf-8 -*-
"""T1 — script.json 의 러시아어 내레이션을 Piper로 읽혀 씬별 wav를 만든다.

    <재료폴더>/script.json
        → <재료폴더>/_build/audio/001.wav … NNN.wav
        → <재료폴더>/_build/durations.json   [{no, sec}]

**왜 Piper인가.** 슈퍼토닉-3(260612 voicewright)는 한글 g2p와 한국어 발음사전으로
돌아가는 **한국어 전용**이라 러시아어를 못 읽는다. Piper는 성격이 똑같으면서
(ONNX · 로컬 CPU · API 키 없음) 러시아어 음성이 네 종 있고 MIT 라이선스다.

**문장 단위로 끊어 합성한다.** 260612 voicewright/engine.py가 긴 문장에서
alignment가 흔들려 단어를 통째로 빠뜨리는 걸 겪고 짧게 잘라 우회했는데, 같은
조심을 여기서도 한다. 문장 사이에는 짧은 뜸을 넣는다 — 붙여 놓으면 숨 안 쉬고
읽는 것처럼 들리고, 무엇보다 **뜸이 있어야 s4가 자를 자리를 찾는다.**

이건 샘플 제작용이다. 본편 음성은 수정본 mp4의 원본 오디오를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPER_DIR = HERE / "assets" / "piper"

# 문장 사이 뜸. 이게 있어야 s4_split이 자를 침묵을 찾는다.
PAUSE_SENT = 0.35
# 씬(슬라이드)이 넘어가는 자리의 뜸 — 더 길게 준다. s4는 여기서 자를 가능성이 높다.
PAUSE_SCENE = 0.90

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def die(msg: str) -> None:
    raise SystemExit(f"오류: {msg}")


def find_piper() -> Path:
    for p in (PIPER_DIR / "piper" / "piper.exe", PIPER_DIR / "piper.exe"):
        if p.is_file():
            return p
    found = shutil.which("piper")
    if found:
        return Path(found)
    die("piper 실행 파일이 없습니다 — tools/sample/setup_piper.ps1 을 먼저 돌리세요")
    raise AssertionError


def find_voice() -> Path:
    models = sorted(PIPER_DIR.glob("*.onnx"))
    if not models:
        die(f"{PIPER_DIR} 에 음성 모델(.onnx)이 없습니다 — setup_piper.ps1 을 돌리세요")
    return models[0]


def ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        die("ffmpeg를 찾지 못했습니다")
    return ff


def wav_info(p: Path) -> tuple[int, int, float]:
    with wave.open(str(p), "rb") as w:
        rate, ch = w.getframerate(), w.getnchannels()
        return rate, ch, w.getnframes() / float(rate)


def synth(piper: Path, voice: Path, text: str, out: Path,
          length_scale: float = 1.0) -> None:
    """length_scale 이 1보다 크면 더 느리게(길게) 읽는다.

    Piper 기본 속도는 est_sec 추정보다 빠르다 — 45분으로 잡은 대본이 35분으로
    나온다(2026-08-26 실측: 2700초 추정 → 2137초). 45분을 정확히 맞춰야 하면
    `--length-scale 1.26` 처럼 비율을 준다.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [str(piper), "-m", str(voice), "-f", str(out)]
    if abs(length_scale - 1.0) > 1e-6:
        args += ["--length_scale", f"{length_scale:.3f}"]
    r = subprocess.run(args, input=text, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.is_file():
        die(f"합성 실패 ({out.name}): {(r.stderr or '')[-300:]}")


def silence(ff: str, sec: float, rate: int, ch: int, out: Path) -> None:
    layout = "mono" if ch == 1 else "stereo"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl={layout}",
                    "-t", f"{sec:.3f}", "-c:a", "pcm_s16le", str(out)],
                   check=True, capture_output=True)


def concat(ff: str, parts: list[Path], out: Path) -> None:
    """ffmpeg concat demuxer. 목록 파일의 경로는 홑따옴표로 감싼다."""
    lst = out.with_suffix(".txt")
    q = chr(39)
    body = "\n".join("file " + q + p.resolve().as_posix() + q for p in parts)
    lst.write_text(body + "\n", encoding="utf-8")
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lst.unlink(missing_ok=True)
    if r.returncode != 0 or not out.is_file():
        die(f"이어 붙이기 실패 ({out.name}): {(r.stderr or '')[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="script.json → 씬별 러시아어 wav (Piper)")
    ap.add_argument("folder", help="script.json 이 있는 폴더 (Claude Code 데스크탑이 만든 것)")
    ap.add_argument("--field", default="narration_ru",
                    help="읽을 필드 (기본 narration_ru. 한국어 더미면 narration_ko)")
    ap.add_argument("--length-scale", type=float, default=1.0,
                    help="읽는 속도. 1보다 크면 느리게 = 길게 (45분을 맞추려면 1.26 근처)")
    a = ap.parse_args()

    root = Path(a.folder).expanduser().resolve()
    src = root / "script.json"
    if not src.is_file():
        die(f"{src} 가 없습니다")

    scenes = json.loads(src.read_text(encoding="utf-8-sig"))
    if not scenes:
        die("script.json 이 비었습니다")

    piper, voice, ff = find_piper(), find_voice(), ffmpeg()
    print(f"음성 — {voice.name}")
    print(f"씬 {len(scenes)}개 합성 중… (필드 {a.field})")

    build = root / "_build"
    audio_dir = build / "audio"
    tmp = build / "_tmp"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)

    rate = ch = None
    sil_sent = tmp / "_sil_sent.wav"
    sil_scene = tmp / "_sil_scene.wav"
    durations = []

    for sc in scenes:
        no = int(sc["no"])
        text = (sc.get(a.field) or "").strip()
        if not text:
            die(f"씬 {no}에 {a.field} 가 비었습니다")

        sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
        parts: list[Path] = []
        for i, s in enumerate(sents, 1):
            w = tmp / f"{no:03d}_{i:02d}.wav"
            synth(piper, voice, s, w, a.length_scale)
            if rate is None:
                rate, ch, _ = wav_info(w)
                silence(ff, PAUSE_SENT, rate, ch, sil_sent)
                silence(ff, PAUSE_SCENE, rate, ch, sil_scene)
            parts.append(w)
            if i < len(sents):
                parts.append(sil_sent)
        parts.append(sil_scene)   # 씬 끝의 뜸 — s4가 여기서 자른다

        dst = audio_dir / f"{no:03d}.wav"
        concat(ff, parts, dst)
        _, _, sec = wav_info(dst)
        durations.append({"no": no, "sec": round(sec, 3)})
        print(f"  {no:03d}.wav  {sec:6.1f}초  (문장 {len(sents)}개)")

    (build / "durations.json").write_text(
        json.dumps(durations, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(d["sec"] for d in durations)
    est = sum(float(s.get("est_sec") or 0) for s in scenes)
    print()
    print(f"완료 — 전체 {total / 60:.1f}분 ({total:.0f}초)")
    if est:
        print(f"       script.json 의 est_sec 합계는 {est / 60:.1f}분 "
              f"— 차이 {abs(total - est):.0f}초")
    if est and abs(total - est) > 60:
        want = est / total * a.length_scale
        print(f"       est_sec 만큼 맞추려면 --length-scale {want:.2f} 로 다시 돌리세요")
    if total < 30 * 60:
        print("경고: 30분이 안 됩니다 — 업체 분할 로직(s4)이 검증되지 않습니다.")
        print("      --length-scale 을 올리거나 대본을 늘리세요.")
    print(f"       {audio_dir}")


if __name__ == "__main__":
    main()
