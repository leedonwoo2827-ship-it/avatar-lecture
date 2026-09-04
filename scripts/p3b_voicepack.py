# -*- coding: utf-8 -*-
r"""P3b — 아바타 업체에 넣을 **음성 한 덩어리**를 만든다.

    강의/<작업>/02/sceneNN.wav  →  강의/<작업>/05/bundleNN/올릴음성.mp3
                                                        경계.txt
                                강의/<작업>/05/경계표.txt

★ **묶음마다 폴더 하나.** 그 폴더에서 mp3 를 꺼내 업체에 올리고, 렌더된 영상을
  **같은 폴더에 되돌려 놓는다.** p4_avatar.py --engine drop 이 거기서 찾는다 —
  어느 영상이 어느 묶음인지 파일 이름으로 기억할 필요가 없어진다.

★ **왜 씬별로 안 넣고 이어붙이나.**
  씬마다 따로 렌더하면 아바타가 매 씬 시작마다 **같은 기본 포즈로 리셋된다.**
  이어붙인 자리에서 자세가 툭 튀고, 손이 방금 올라가던 중이었어도 다음 씬에서
  다시 내려가 있다. 한 덩어리로 렌더하면 자세와 제스처가 이어진다 — 제스처가
  자연스러워야 한다는 요구가 곧 이 결정이다.

★ **왜 그래도 나누나.**
  HeyGen 오디오 입력 상한이 **10분(600초)** 이다. 45분 강의는 못 한 번에 넣는다.
  그래서 590초를 넘지 않게 묶는다 — 10초만 마진으로 둔다. 마진을 크게 잡으면
  9:47 짜리가 «7씬 + 1씬» 으로 갈려 마지막 씬만 따로 렌더되는데, 그러면 그 자리에서
  자세가 튀고 드래그드랍도 두 번 해야 한다. **상한을 넘기면 렌더 전에 거절되므로
  과금 위험이 없다** — 그래서 마진은 작게 잡고, 거절되면 그때 낮춘다.
  옛 업체 GUI 는 1분에서 끊겨 45분을 45조각으로 잘라야 했다. 여기서는 **5조각**이다.

      40:01  →  5조각 (8:00 씩)
      45:00  →  5조각 (9:00 씩)
      49:10  →  5조각 (9:50 씩)   ← 5 x 590초. **5조각의 한계**
      50:00  →  6조각

★ 기본은 `--pack even` — 묶음 **수는 최소로 두고 길이를 고르게** 나눈다. 꽉 채우면
  마지막이 3:41 짜리 자투리로 남는데, 렌더 대기를 가늠하기 어렵고 재렌더 비용도
  들쭉날쭉해진다. 120강을 반복할 때 그 차이가 쌓인다.

★ **자르는 자리는 늘 씬 경계다.** 초를 재서 자르면 말 한가운데가 끊겨 입모양이
  깨진다. 씬 경계는 대본이 정한 문장 경계라 그럴 일이 없다.

만든 뒤 할 일은 둘 중 하나다.

    (가) 05/bundleNN/올릴음성.mp3 를 HeyGen 웹에 드래그드랍 → 렌더 →
         webm(배경 투명)을 **그 폴더에 되돌려 놓기** → `p4_avatar.py --engine drop`
    (나) `p4_avatar.py --engine heygen` — API 가 같은 일을 자동으로 한다(단가 3~4배)

    python scripts/p3b_voicepack.py --task lecture01
    python scripts/p3b_voicepack.py --task lecture01 --max-sec 560 --scenes 1-8
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (ROOT, die, ffmpeg, load_json, mmss, need,
                            probe_duration, save_json, scene_paths)
from scripts.cues import Cue, parse_srt, to_srt
from scripts.ticker import Ticker


# HeyGen 오디오 입력 상한 600초. 10초를 마진으로 남긴다(위 ★ 참고).
HEYGEN_AUDIO_MAX = 600
DEFAULT_MAX = 590
MP3_KBPS = 128          # 590초 × 128kbps ≈ 9.4MB — 자산 상한 32MB 안에 넉넉히 든다


def _fill(rows: list[dict], cap: float) -> list[list[dict]] | None:
    """앞에서부터 cap 까지 채운다. 하나라도 cap 을 넘는 씬이 있으면 None."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    acc = 0.0
    for r in rows:
        d = float(r["voice_dur"])
        if d > cap:
            return None
        if cur and acc + d > cap:
            out.append(cur)
            cur, acc = [], 0.0
        cur.append(r)
        acc += d
    if cur:
        out.append(cur)
    return out


def group(rows: list[dict], max_sec: float, *, balance: bool = False) -> list[list[dict]]:
    """씬을 상한 안에서 순서대로 묶는다. **씬을 쪼개지도, 순서를 바꾸지도 않는다.**

    기본은 앞에서부터 꽉 채운다. 그러면 앞 묶음이 상한에 붙고 **마지막 하나만
    짧게 남는다** (32씬 40분이면 9:47·8:36·8:54·9:02·3:41). 첫 묶음이 정확히
    승인본과 같은 경계가 되므로 검수를 이미 받은 건에는 이쪽이 낫다.

    balance=True 면 **묶음 수는 그대로 두고 고르게** 나눈다. 상한을 조금씩 낮춰
    보다가 묶음 수가 늘어나는 직전 값을 쓴다 — 렌더 길이가 비슷해져 대기 시간을
    가늠하기 쉽고, 3분짜리 자투리 렌더가 사라진다. 120강처럼 반복할 때 쓴다.
    """
    for r in rows:
        d = float(r["voice_dur"])
        if d > max_sec:
            die(f"{int(r['no']):02d}번 씬 하나가 {mmss(d)} 로 상한 {mmss(max_sec)} 를 "
                f"넘습니다 — 그 씬을 대본에서 둘로 나누고 p1 부터 다시 돌리세요")

    base = _fill(rows, max_sec) or []
    if not balance or len(base) < 2:
        return base

    # 묶음 수를 유지하면서 상한을 낮춘다. 총합÷묶음수가 이론적 하한이다.
    n = len(base)
    total = sum(float(r["voice_dur"]) for r in rows)
    best = base
    cap = max_sec
    while cap > total / n:
        cap -= 1.0
        got = _fill(rows, cap)
        if got is None or len(got) != n:
            break
        best = got
    return best


def concat(ff: str, parts: list[Path], out: Path) -> None:
    """wav 여러 개 → mp3 하나. concat 디먹서를 쓴다(재인코딩 한 번).

    ★ 목록 파일의 경로는 **작은따옴표로 싸고 슬래시로 쓴다** — 윈도 역슬래시를
      그대로 넣으면 concat 디먹서가 이스케이프로 읽는다. p5_compose.py 가
      `--join` 에서 쓰는 방식과 같다.
    """
    q = chr(39)
    lst = out.with_suffix(".txt")
    lst.write_text("\n".join(f"file {q}{p.resolve().as_posix()}{q}" for p in parts) + "\n",
                   encoding="utf-8")
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(lst),
         "-vn", "-c:a", "libmp3lame", "-b:a", f"{MP3_KBPS}k", "-ar", "44100",
         str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    lst.unlink(missing_ok=True)
    if r.returncode != 0 or not out.is_file():
        die(f"{out.name} 이어붙이기 실패: {(r.stderr or '')[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="아바타 업체에 넣을 음성 묶음 만들기")
    ap.add_argument("--task", default="lecture01")
    ap.add_argument("--max-sec", type=float, default=DEFAULT_MAX,
                    help=f"묶음 하나의 상한 초 (기본 {DEFAULT_MAX} — "
                         f"HeyGen 상한 {HEYGEN_AUDIO_MAX}초에 10초 마진)")
    ap.add_argument("--scenes", default="", help="이 씬만 (기본: 목소리가 있는 전부)")
    ap.add_argument("--ends", action="store_true", default=True,
                    help="**첫 강의의 도입 씬과 마지막 강의의 결론 씬을 따로 낸다.** "
                         "업체 편집기에서 장면을 둘로 두고 그 두 장면에만 다른 "
                         "표현·제스처를 주려는 것이다 — 인사와 마무리는 본문과 "
                         "말투가 다르다. 중간 묶음은 통째로 하나다")
    ap.add_argument("--no-ends", dest="ends", action="store_false",
                    help="도입·결론을 따로 내지 않는다 (묶음마다 한 덩어리)")
    ap.add_argument("--pack", default="even", choices=["even", "fill"],
                    help="even=묶음 수를 최소로 두고 **고르게** 나눈다(기본) · "
                         "fill=앞에서부터 상한까지 꽉 채운다(마지막이 자투리로 남는다)")
    a = ap.parse_args()

    if a.max_sec > HEYGEN_AUDIO_MAX:
        die(f"--max-sec {a.max_sec:.0f} 은 HeyGen 상한 {HEYGEN_AUDIO_MAX}초를 넘습니다")

    P = scene_paths(a.task)
    meta = load_json(need(P.meta, "p1_scenes.py 를 먼저 돌리세요"))
    rows = [r for r in meta["scenes"] if r.get("voice")]
    if a.scenes:
        from scripts.p1_scenes import parse_range
        want = set(parse_range(a.scenes, len(meta["scenes"])))
        rows = [r for r in rows if r["no"] in want]
    if not rows:
        die("목소리가 아직 없습니다 — p2_voice.py 를 먼저 돌리세요")

    out_dir = P.upload
    out_dir.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()

    bundles = group(rows, a.max_sec, balance=(a.pack == "even"))
    total = sum(float(r["voice_dur"]) for r in rows)
    print(f"{len(rows)}씬 · 합계 {mmss(total)} → 묶음 {len(bundles)}개 "
          f"(상한 {mmss(a.max_sec)} · {'고르게' if a.pack == 'even' else '꽉 채움'})")

    table: list[str] = [
        f"# {a.task} — 아바타 업체에 넣을 음성 묶음",
        f"# 씬 {len(rows)}개 · 합계 {mmss(total)} · 묶음 {len(bundles)}개",
        "#",
        "# 묶음 폴더의 «올릴음성.mp3» 을 HeyGen 에 드래그드랍해 렌더하고,",
        "# 내려받은 영상을 **그 폴더에 되돌려 놓으면** p4_avatar.py --engine drop 이",
        "# 아래 경계를 그대로 씁니다. 영상은 자르지 않습니다.",
        "",
    ]
    made: list[Path] = []
    for bi, grp in enumerate(bundles, start=1):
        bdir = out_dir / f"bundle{bi:02d}"
        bdir.mkdir(parents=True, exist_ok=True)
        out = bdir / "올릴음성.mp3"
        parts = [P.voice / r["voice"] for r in grp]
        for p in parts:
            if not p.is_file():
                die(f"{p} 가 없습니다 — p2_voice.py 를 다시 돌리세요")
        with Ticker(f"묶음 {bi:02d} 이어붙이는 중"):
            concat(ff, parts, out)
        got = probe_duration(out)
        want = sum(float(r["voice_dur"]) for r in grp)

        # 경계 — 묶음 **안에서의** 시작 초. p5 가 -ss 로 이 값을 쓴다.
        off = 0.0
        head = (f"[{bdir.name}]  씬 {grp[0]['no']:02d}~{grp[-1]['no']:02d}  "
                f"{mmss(got)}  ({out.stat().st_size/1048576:.1f}MB)")
        table.append(head)
        mine = [head]
        for r in grp:
            d = float(r["voice_dur"])
            r["bundle"] = bi
            r["bundle_dir"] = bdir.name
            r["bundle_file"] = f"{bdir.name}/{out.name}"
            r["bundle_offset"] = round(off, 3)
            line = (f"  {int(r['no']):02d}  {mmss(off):>8} ~ {mmss(off + d):>8}"
                    f"  ({d:6.2f}초)  {str(r.get('title',''))[:34]}")
            table.append(line)
            mine.append(line)
            off += d
        table.append("")

        # ── 검수용 자막 ─────────────────────────────────────────────────────
        # ★ **업체에 자막을 보내지 않는다.** 자막은 p5 가 로컬 ffmpeg 으로 굽는다 —
        #   그래서 자막을 몇 번 고쳐도 아바타를 다시 렌더할 일이 없다(0원).
        #
        #   그래도 묶음 폴더에 넣어 두는 이유는 **검수**다. 8분짜리 묶음을 통째로
        #   들으면서 자막이 맞는지 보려면 소리와 자막이 짝이어야 한다. 파일 이름을
        #   «올릴음성»으로 맞춰 두면 곰플레이어가 알아서 물어 온다 — 재료의
        #   `lecture01_uz.mp4` + `lecture01_uz.srt` 가 짝지어져 있던 것과 같은 방식.
        #
        #   시각은 **묶음 안에서 0초부터** 다시 매긴다. 씬 하나가 곧 조각 하나이던
        #   s6_package.py 와 같은 이유다 — 묶음을 열었을 때 0초가 시작이어야 한다.
        made_srt: list[str] = []
        for tag in sorted({x.name.split(".")[1] for x in P.aligned.glob("scene*.*.srt")
                           if x.name.count(".") >= 2}):
            pool: list = []
            at = 0.0
            for r in grp:
                one = P.aligned / f"scene{int(r['no']):02d}.{tag}.srt"
                if one.is_file():
                    for c in parse_srt(one.read_text(encoding="utf-8-sig")):
                        pool.append(Cue(text=c.text, start=c.start + at, end=c.end + at))
                at += float(r["voice_dur"])
            if not pool:
                continue
            # ★ 언어를 **이름에 늘 박는다.** 소리는 우즈베크어인데 자막은 러시아어라
            #   «올릴음성.srt» 로 두면 소리를 받아쓴 것으로 오해된다. 플레이어는
            #   `올릴음성.ru.srt` 도 소리와 짝으로 알아본다.
            name = f"올릴음성.{tag}.srt"
            (bdir / name).write_text(to_srt(pool), encoding="utf-8")
            made_srt.append(f"{name} ({len(pool)}큐)")

        # ── 씬별 mp3 ────────────────────────────────────────────────────────
        # ★ **묶음 전체와 씬별을 나란히 둔다.** 올리는 방식이 둘이고, 어느 쪽이
        #   나은지는 실제로 보고서야 정해진다. 하나만 만들어 두면 마음이 바뀔
        #   때마다 이 단계를 다시 돌려야 한다.
        #
        #     올릴음성.mp3      묶음 전체 — 드래그드랍 한 번. 자세가 이어진다
        #     씬\sceneNN.mp3    씬 하나씩 — 씬마다 제스처·표현을 지정할 수 있다
        #
        #   ★ 옛 업체와 다른 점: 옛 업체는 상한이 1분이라 **씬 안을** 잘라야 했다
        #     (슬라이드 하나가 1분을 조금 넘었다). HeyGen 은 600초라 씬 하나
        #     (66~82초)가 통째로 들어간다 — 씬별로 나누는 것이 말을 끊는 일이
        #     아니고, 드래그드랍 횟수만 늘어난다.
        #
        #   p4_avatar.py --engine drop 은 **둘 다 받는다.** 묶음 폴더에 영상 하나가
        #   있으면 묶음으로, 씬별 영상이 다 있으면 씬별로 읽는다.
        sdir = bdir / "씬"
        sdir.mkdir(parents=True, exist_ok=True)
        for r in grp:
            no = int(r["no"])
            out_s = sdir / f"scene{no:02d}.mp3"
            rr = subprocess.run(
                [ff, "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(P.voice / r["voice"]), "-vn",
                 "-c:a", "libmp3lame", "-b:a", f"{MP3_KBPS}k", "-ar", "44100",
                 str(out_s)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if rr.returncode != 0 or not out_s.is_file():
                die(f"{out_s.name} 만들기 실패: {(rr.stderr or '')[-300:]}")
            # 씬별 검수 자막 — 씬 안에서 0초부터. 이름을 소리와 짝지어 둔다
            for one in P.aligned.glob(f"scene{no:02d}.*.srt"):
                if one.name.count(".") >= 2:
                    (sdir / one.name).write_text(
                        one.read_text(encoding="utf-8-sig"), encoding="utf-8")

        # ── 업체 편집기에 넣을 «장면» 조각 ──────────────────────────────────
        # ★ **도입과 결론만 떼어낸다.** 업체 편집기는 한 프로젝트에 장면을 여러
        #   개 둘 수 있고, 장면마다 표현·제스처를 따로 준다. 그런데 장면을 씬마다
        #   두면 설정을 32번 해야 하고, 그렇게 통일해 버리면 나눈 뜻이 없어진다.
        #
        #   실제로 말투가 다른 자리는 **인사와 마무리** 둘이다. 그 둘만 떼면
        #   장면 둘로 뜻을 다 담는다 — 설정은 두 번, 렌더는 한 번이다.
        #
        #   ★ 나온 영상은 **여전히 묶음 하나**다(업체가 장면을 이어 준다).
        #     그래서 p4 는 안 고친다 — 경계표 시각이 그대로 맞는다.
        scene_parts: list[tuple[str, list[dict]]] = []
        if a.ends and len(grp) > 1:
            if bi == 1:
                scene_parts = [("도입", grp[:1]), ("본문", grp[1:])]
            elif bi == len(bundles):
                scene_parts = [("본문", grp[:-1]), ("마무리", grp[-1:])]
        if scene_parts:
            pdir = bdir / "장면"
            pdir.mkdir(parents=True, exist_ok=True)
            made_parts = []
            for pi, (label, part) in enumerate(scene_parts, start=1):
                nos_txt = (f"씬{int(part[0]['no']):02d}" if len(part) == 1
                           else f"씬{int(part[0]['no']):02d}-{int(part[-1]['no']):02d}")
                out_p = pdir / f"{pi}_{label}_{nos_txt}.mp3"
                concat(ff, [P.voice / r["voice"] for r in part], out_p)
                psec = probe_duration(out_p)
                made_parts.append(f"{out_p.name} ({mmss(psec)})")
            print(f"      장면 조각  {' · '.join(made_parts)}")

        # 묶음 폴더 안에도 그 묶음 것만 적어 둔다 — 폴더를 열었을 때 바로 보이게
        srt_names = [x.split(" ")[0] for x in made_srt]
        guide = [
            "═══ HeyGen 에 올리는 것 — 길이 둘입니다 ═══",
            "",
            "   (가) 올릴음성.mp3        묶음 전체. **드래그드랍 한 번.**",
            "        자세와 제스처가 씬을 넘어 이어집니다.",
            "        씬마다 제스처·표현을 따로 지정할 수는 없습니다",
            "        (커스텀 모션이 앞 10초만 걸리기 때문입니다).",
            "",
            "   (나) 씬\\sceneNN.mp3      씬 하나씩. 드래그드랍 여러 번.",
            "        씬마다 제스처·표현을 지정할 수 있고, 틀린 씬만 다시 렌더합니다.",
            "        씬 시작마다 자세가 리셋되지만 슬라이드가 바뀌는 순간과 겹쳐",
            "        잘 안 보입니다.",
            "",
            "   (다) 장면\1_도입_… · 2_본문_…   업체 편집기에 **장면 둘**로 넣습니다.",
            "        인사와 마무리는 본문과 말투가 다르니 그 둘만 떼어 표현·제스처를",
            "        따로 줍니다. 설정은 두 번, 렌더는 한 번. 나온 영상은 여전히",
            "        묶음 하나라 경계표가 그대로 맞습니다. **이쪽을 권합니다.**",
            "",
            "   아무 쪽이나 받아서 **이 폴더에 되돌려 놓으면** 됩니다 —",
            "   묶음 영상 하나든, 씬별 영상 여러 개든 알아서 읽습니다.",
            "   총 과금은 초당이라 **어느 쪽이든 같습니다.**",
            "",
            "═══ 올리지 않는 것 (우리 쪽에서만 씁니다) ═══",
            "",
            *[f"   {n:<22} 검수용 자막" for n in srt_names],
            "   씬\\sceneNN.<언어>.srt   씬별 검수용 자막",
            "   경계.txt               지금 읽고 있는 이 파일",
            "",
            "   자막은 마지막에 로컬 ffmpeg 이 굽습니다. 그래서 자막을 몇 번 고쳐도",
            "   아바타를 다시 렌더할 일이 없습니다(0원). 업체는 자막을 볼 필요가 없습니다.",
            "",
            "   ★ 소리는 **우즈베크어**, 자막은 **러시아어**입니다. 파일 이름의 두 글자가",
            "     자막 언어입니다(ru=러시아어). 이름이 소리와 짝이라 곰플레이어가 알아서",
            "     물어 옵니다 — 통째로 들으면서 자막이 맞는지 보세요.",
            "",
            "═══ HeyGen 에서 챙길 설정 셋 ═══",
            "",
            "   · 음성 — 스크립트 입력이 아니라 **오디오 파일 업로드**",
            "   · 엔진 — Avatar V (제스처가 가장 자연스럽습니다)",
            "   · 배경 — 투명 / Remove background → **webm** 으로 내려받기",
            "",
            "   렌더가 끝나면 내려받은 영상을 **이 폴더에 그대로 놓으세요.**",
            "   파일 이름은 아무래도 됩니다 — 이 폴더에 있으면 알아서 찾습니다.",
            "",
            "   그다음:  python scripts/p4_avatar.py --task <작업> --engine drop",
            "",
            "═══ 이 묶음이 담고 있는 씬 ═══",
            "",
            *mine,
            "",
        ]
        (bdir / "경계.txt").write_text("\n".join(guide), encoding="utf-8")

        drift = got - want
        mark = "" if abs(drift) < 0.30 else f"   ← 씬 합계와 {drift:+.2f}초 차이"
        print(f"  {bdir.name}/{out.name}  씬 {grp[0]['no']:02d}~{grp[-1]['no']:02d}  "
              f"{mmss(got):>8}  {out.stat().st_size/1048576:5.1f}MB{mark}")
        if made_srt:
            print(f"      검수용 자막  {' · '.join(made_srt)}")
        made.append(out)

    (out_dir / "경계표.txt").write_text("\n".join(table) + "\n", encoding="utf-8")
    meta["bundles"] = [{"no": i + 1, "dir": p.parent.name,
                        "file": f"{p.parent.name}/{p.name}",
                        "scenes": [r["no"] for r in g],
                        "sec": round(sum(float(r["voice_dur"]) for r in g), 3)}
                       for i, (p, g) in enumerate(zip(made, bundles))]
    meta["bundle_max_sec"] = a.max_sec
    save_json(P.meta, meta)

    # 예상 비용 — 호출 0회. «예상»이라고만 말한다.
    try:
        from heygen.client import RATE_USD_PER_SEC
        rates = "  ".join(f"{k.replace('avatar_','A')} ${total*v:,.1f}"
                          for k, v in RATE_USD_PER_SEC.items())
        print(f"\nAPI 로 돌릴 때 예상액(초당 과금): {rates}")
        print("웹 월정액이 3~4배 쌉니다 — 이 묶음을 드래그드랍하는 쪽을 먼저 보세요.")
    except Exception:  # noqa: BLE001 — 비용 안내가 산출을 막지 않게
        pass

    print(f"\n다음: HeyGen 에 {made[0].name} 를 넣고 렌더 → webm(배경 투명)으로 내려받기")
    print(f"      그다음  python scripts/p4_avatar.py --task {a.task} "
          f"--engine drop --from <내려받은 폴더>")
    print(f"완료 — {out_dir}")


if __name__ == "__main__":
    main()
