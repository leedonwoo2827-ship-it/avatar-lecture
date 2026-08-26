# -*- coding: utf-8 -*-
"""오래 걸리는 호출 동안 초를 세어 보여준다 — 화면이 안 바뀌면 사람은 멈춘 걸로
읽고 다시 누른다(260812 "누르면 시계가 돈다"와 같은 이유). ffmpeg 장면 검출처럼
몇십 초~몇 분 가는 자리에 두른다.

    with Ticker("장면 검출 중"):
        subprocess.run(...)

★ 화면이 아니면(파이프·리다이렉트) 초 세기를 건너뛴다. 커서를 줄 앞으로 되돌리는
  제어문자가 파이프에서는 안 먹혀서, 로그가 "1초 경과… 2초 경과… 3초 경과…" 하고
  한 줄로 길게 뭉친다(2026-08-26 실측).
"""
from __future__ import annotations

import sys
import threading
import time


class Ticker:
    def __init__(self, label: str) -> None:
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0
        self._live = False

    def __enter__(self) -> "Ticker":
        self._t0 = time.time()
        try:
            self._live = bool(sys.stdout.isatty())
        except Exception:  # noqa: BLE001 — 판단이 안 되면 조용한 쪽으로
            self._live = False
        if not self._live:
            print(f"  {self.label}…")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            elapsed = time.time() - self._t0
            sys.stdout.write("\r" + f"  {self.label} — {elapsed:0.0f}초 경과…   ")
            sys.stdout.flush()
            self._stop.wait(1.0)

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._live:
            sys.stdout.write("\r" + " " * (len(self.label) + 30) + "\r")
            sys.stdout.flush()
        else:
            print(f"  {self.label} — {time.time() - self._t0:0.0f}초 걸렸습니다")
