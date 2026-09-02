# -*- coding: utf-8 -*-
"""크레딧 장부 — 얼마 썼는지 남기고, 정한 만큼 넘으면 멈춘다.

perso 는 **쓴 만큼 크레딧이 빠진다.** 실수로 돌린 반복문 하나가 잔액을 비울 수
있으므로, 호출하는 쪽이 아니라 **여기서** 상한을 지킨다. 상한을 넘기면 예외를
던져 파이프라인을 세운다 — 조용히 계속 쓰는 것보다 멈추는 쪽이 늘 싸다.

장부는 `_doc/credit-ledger.csv` 에 쌓인다(`_doc/` 는 .gitignore 라 저장소에 안 간다):

    시각, 작업, 씬, 서비스, 단위수, 크레딧, 누적, 비고

★ **단가를 코드에 박지 않는다.** 가격표에 "0.025 credits / execution" 이라고만
  적혀 있고 execution 이 잡 하나인지 1초인지는 공개 문서로 확인되지 않았다.
  그래서 여기서는 **실제로 빠진 크레딧을 받아 적기만** 한다. 1씬을 돌려 보고
  Billing → Transactions 의 차감량과 이 장부를 맞춰 본 뒤에 단가를 정하면 된다.
  추정치를 코드에 박아 두면 그게 사실인 줄 알고 계산을 쌓게 된다.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "_doc" / "credit-ledger.csv"
HEADER = ["시각", "작업", "씬", "서비스", "단위수", "크레딧", "누적", "비고"]


class BudgetExceeded(RuntimeError):
    """상한을 넘었다 — 부르는 쪽이 잡아서 멈춘다."""


class Ledger:
    """한 번 돌 때 쓴 크레딧을 적고 상한을 지킨다.

        led = Ledger(task="lecture01", budget=20.0)
        led.spend(scene=1, service="tts", units=1, credits=0.01)
    """

    def __init__(self, task: str, budget: float = 20.0,
                 path: Path | None = None) -> None:
        self.task = task
        self.budget = float(budget)
        self.path = path or LEDGER
        self.used = 0.0
        self.rows = 0

    # ── 읽기 ────────────────────────────────────────────────────────────────
    def total_so_far(self) -> float:
        """장부에 남은 이 작업의 누적 — 지난 실행까지 합쳐서."""
        if not self.path.is_file():
            return 0.0
        got = 0.0
        with self.path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("작업") == self.task:
                    try:
                        got += float(row.get("크레딧") or 0)
                    except ValueError:
                        pass
        return round(got, 5)

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def check(self, want: float) -> None:
        """이만큼 더 쓰면 상한을 넘는지 미리 본다 — 호출 **전에** 부른다."""
        if self.used + want > self.budget:
            raise BudgetExceeded(
                f"크레딧 상한을 넘습니다 — 지금까지 {self.used:.3f}, "
                f"이번에 {want:.3f}, 상한 {self.budget:.3f}. "
                f"상한을 올리려면 --budget 을 크게 주세요.")

    def spend(self, *, scene: int | str, service: str, units: float,
              credits: float, note: str = "") -> float:
        """실제로 빠진 크레딧을 적는다. 누적을 돌려준다."""
        credits = float(credits)
        self.check(credits)
        self.used = round(self.used + credits, 5)
        self.rows += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.is_file()
        with self.path.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HEADER)
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        self.task, scene, service, f"{units:g}",
                        f"{credits:.5f}", f"{self.used:.5f}", note])
        return self.used

    def summary(self) -> str:
        return (f"이번 실행 {self.used:.3f} 크레딧 · {self.rows}건 "
                f"(상한 {self.budget:.3f}) · 장부 {self.path}")
