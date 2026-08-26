# -*- coding: utf-8 -*-
"""T2 — HTML 슬라이드 → 1920×1080 PNG.

    <재료폴더>/slides/001.html … NNN.html
        → <재료폴더>/_build/slides/001.png … NNN.png

헤드리스 크로미움으로 한 장씩 찍는다. Claude Code 데스크탑이 만든 슬라이드는
인라인 CSS만 쓰는 자기완결 HTML이라 오프라인에서 그대로 열린다.

★ **키릴 글자가 두부(□)로 나오는지 첫 장에서 확인한다.** 러시아어 슬라이드인데
  시스템에 키릴 글꼴이 없으면 전부 네모로 찍히고, 그걸 45분치 다 굽고 나서야
  발견하면 처음부터 다시 해야 한다. 그래서 첫 장을 찍고 바로 검사한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

W, H = 1920, 1080


def die(msg: str) -> None:
    raise SystemExit(f"오류: {msg}")


def main() -> None:
    ap = argparse.ArgumentParser(description="HTML 슬라이드 → 1920×1080 PNG")
    ap.add_argument("folder", help="slides/ 가 있는 폴더")
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("playwright가 없습니다 — `pip install playwright` 뒤 "
            "`playwright install chromium` 을 돌리세요")
        return

    root = Path(a.folder).expanduser().resolve()
    src = root / "slides"
    if not src.is_dir():
        die(f"{src} 가 없습니다")
    htmls = sorted(src.glob("*.html"))
    if not htmls:
        die(f"{src} 안에 .html 이 없습니다")

    out_dir = root / "_build" / "slides"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"슬라이드 {len(htmls)}장 굽는 중… ({W}×{H})")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        for i, h in enumerate(htmls, 1):
            page.goto(h.resolve().as_uri())
            page.wait_for_timeout(120)
            dst = out_dir / f"{i:03d}.png"
            page.screenshot(path=str(dst))

            if i == 1:
                # 키릴 글꼴이 없으면 여기서 멈춘다 — 45장 다 굽고 알면 늦다
                missing = page.evaluate(
                    "() => { const s=document.createElement('span');"
                    "s.style.cssText='position:absolute;visibility:hidden;font-size:64px';"
                    "s.textContent='Привет'; document.body.appendChild(s);"
                    "const w=s.getBoundingClientRect().width; s.remove(); return w; }")
                if not missing or missing < 40:
                    browser.close()
                    die("키릴 글자가 그려지지 않습니다 — 시스템에 키릴 글꼴이 없습니다. "
                        "슬라이드 HTML의 font-family 에 Arial/Segoe UI 같은 폴백을 넣으세요")
            print(f"  {dst.name}")
        browser.close()

    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
