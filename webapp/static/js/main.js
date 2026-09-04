/* AVA(Avatar Lecture) 화면 — 대본과 슬라이드로 영상을 세우는 순서 하나.
 *
 * 좌측이 **번호 순서**다. 이 앱은 한 길로만 가는 도구라 평평한 메뉴를 두면
 * 무엇을 먼저 하는지가 안 보인다. 단계는 STEPS 하나에만 적고 화면·상태점·
 * 라우팅이 전부 그걸 읽는다 — 두 군데 적으면 반드시 어긋난다.
 *
 * 해시가 바뀌면 section 하나를 보이고 나머지를 숨긴다. 언마운트하지 않으므로
 * 돌고 있는 로그가 화면을 옮겨도 살아 있다.
 */
"use strict";
import { hydrateIcons } from "/static/js/icons.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* 자막 한 줄 최대 글자수 — scripts/common.py 의 CUE_MAX_CHARS 와 같은 값이어야
   한다. 여기서 다르면 화면은 통과라고 하는데 check.py 는 실패라고 한다. */
const CUE_MAX = { ru: 42, uz: 46, en: 46, ko: 30 };

/* ── 단계 ────────────────────────────────────────────────────────────────
 * page   : index.html 의 data-page
 * dir    : 이 단계가 **쓰는 폴더**. 화면의 번호가 곧 디스크의 번호다 —
 *          «3단계 결과가 어디 있나» 를 물을 일이 없게. 1..9 순번을 따로
 *          매기면 순번과 폴더가 어긋나 둘 다 외워야 한다.
 *          다국어 자막이 01 인 것은 실수가 아니다. 씬이 잘라 놓은
 *          01/subs 에 언어를 **더 얹는** 일이라 같은 폴더가 맞다.
 * run    : 이 단계가 돌리는 파이프라인 조각 (없으면 실행 없는 화면)
 * costs  : 아바타 업체를 실제로 부르는 단계 — $ 가 붙는다
 * rule   : 이 앞에 가로선을 긋는다. 글자를 주면 선 가운데에 얹는다.
 *          빈 글자는 «여기서 결이 바뀐다» 만 말하는 민 선이다.
 */
const STEPS = [
  { page: "p0",   dir: "00", name: "재료" },
  { page: "p1",   dir: "01", name: "씬",     run: "p1" },
  { page: "p2",   dir: "02", name: "목소리", run: "p2" },
  { page: "p2b",  dir: "01", name: "다국어 자막", run: "p2b", rule: "" },
  { page: "p3",   dir: "03", name: "자막",   run: "p3", rule: "" },
  { page: "p3b",  dir: "05", name: "묶음",   run: "p3b" },
  { page: "p4",   dir: "07", name: "아바타", run: "p4", costs: true },
  { page: "p5",   dir: "09", name: "완성본", run: "p5" },
];
// 폴더마다 무엇이 담기는지 — 번호에 마우스를 올리면 뜬다
const DIR_SAY = {
  "00": "재료 — 원본 mp4 · 자막 · 슬라이드",
  "01": "씬별로 자른 슬라이드와 자막 (언어마다 한 벌)",
  "02": "씬별 목소리 wav",
  "03": "목소리 길이에 맞춘 자막",
  "05": "업체에 올릴 묶음 — 올릴음성.mp3",
  "07": "받아 온 아바타 영상",
  "09": "완성본",
};
// ★ 고른 강의. lectures.js 가 갈아 끼우고 localStorage 에 남긴다 —
//   창을 다시 열어도 아까 고른 강의로 돌아온다. 120강이 쌓이면
//   «어느 강의였지» 를 매번 다시 고르게 하면 안 된다.
let TASK = localStorage.getItem("sc.task") || "";

let STATE = { scenes: [], sceneDefaults: null, cfg: null };
let HEYGEN = null, CONN = null;
let cues = [];                 // 5 자막 화면의 현재 큐
let LANGS = { langs: [], scripts: [] };
let picked = [];               // 고른 자막 언어 (꼬리표) — 맨 앞이 기본 자막
let logSeen = 0, poll = null;

/* ── 자잘한 것 ─────────────────────────────────────────────── */
const mmss = (t) => {
  t = Math.max(0, Number(t) || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
};
function toast(msg, isErr = false) {
  const n = document.createElement("div");
  n.className = "toast" + (isErr ? " err" : "");
  n.textContent = msg;
  $("#toast-host").appendChild(n);
  setTimeout(() => n.remove(), 3200);
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(j.error || `${r.status}`);
  return j;
}
const post = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const task = () => TASK || (STATE.scenes[0] && STATE.scenes[0].task) || "001";

/* ★ **고른 강의의 줄.** 여태 `STATE.scenes[0]` — 목록의 첫 줄 — 을 썼다.
 *   목록은 이름 역순이라 첫 줄이 고른 강의가 아니다. 그래서 「샘플」을 골라
 *   두고도 씬 개수·묶음 개수·자막 언어·진행 점이 전부 「001」 것을 읽었다.
 *   한 화면에서 «묶음이 없습니다» 와 «묶음 5개» 가 같이 뜬 원인이다.
 *
 *   고른 강의가 아직 p1 을 안 돌아 scenes.json 이 없으면 undefined 다.
 *   그것이 맞다 — 그 강의는 실제로 아무것도 없다. 다른 강의 숫자로 채워
 *   보여 주는 것이 거짓말이다.
 */
const cur = () => (STATE.scenes || []).find((r) => r.task === task());

/* ── 좌측 순서 ──────────────────────────────────────────────
 * 상태 점은 scenes.json 이 채워진 정도로 정한다 — 파일이 사실이고 화면은
 * 그걸 비출 뿐이다. done(다 됨) · part(일부) · 없음(회색).
 */
function stepState(page) {
  const j = cur();
  if (!j || !j.scenes.length) return page === "p0" ? "done" : "";
  const n = j.scenes.length;
  const got = {
    p0: n,
    p1: j.scenes.filter((s) => s.slide).length,
    p2: j.scenes.filter((s) => s.voice).length,
    p2b: j.scenes.filter((s) => s.cues > 0).length,
    p3: j.scenes.filter((s) => s.voice && s.cues > 0).length,
    // 묶음은 씬마다 세는 게 아니라 «있냐 없냐» 다 — 5개가 있으면 전부 된 것
    p3b: j.bundles > 0 ? n : 0,
    p4: j.scenes.filter((s) => s.avatar).length,
    p5: j.scenes.filter((s) => s.preview).length,
  }[page] || 0;
  // ★ **09 만 분모가 다르다.** 서른둘 중 일곱만 아바타가 왔으면 나머지 스물다섯은
  //   «아직 안 구운» 것이 아니라 **구울 수 없는** 것이다. 32 로 나누면 단추가
  //   영원히 「이어서」에 머물러, 다 구워 놓고도 «전부 다시 굽기» 를 못 한다.
  //   아바타가 온 만큼을 «전부» 로 본다 — 오는 대로 분모가 늘어난다.
  const need = page === "p5" ? j.scenes.filter((s) => s.avatar).length : n;
  if (!need) return "";
  return got >= need ? "done" : got > 0 ? "part" : "";
}

/* 지금 보고 있는 강의를 사이드바에 적는다. 씬 개수까지 같이 적어, 그 강의가
   아직 p1 을 안 돈 상태인지(0씬) 한눈에 보이게 한다 — 빈 화면을 보며
   «안 만들었나» 를 되묻던 자리가 여기다. */
function drawRailLec() {
  const el = $("#rail-lec-v");
  if (!el) return;
  const now = task();
  const L = (LECS || []).find((x) => x.task === now);
  el.textContent = now || "안 골랐습니다";
  el.title = L ? `씬 ${L.scenes}개 · 묶음 ${L.bundles}개` : "";
  const btn = $("#rail-lec");
  if (btn) btn.classList.toggle("warn", !!L && !L.scenes);
}
if ($("#rail-lec")) $("#rail-lec").onclick = () => { location.hash = "#/p0"; };

function renderSteps() {
  const cur = (location.hash || "#/p0").replace("#/", "");
  drawRailLec();
  $("#steps").innerHTML = STEPS.map((st) => `
    ${st.rule != null
        ? `<div class="step-rule${st.rule ? "" : " bare"}"><span>${st.rule}</span></div>`
        : ""}
    <button class="step ${cur === st.page ? "on" : ""}" data-page="${st.page}">
      <span class="step-no" title="강의/${TASK || "<강의>"}/${st.dir}/ — ${DIR_SAY[st.dir] || ""}">${st.dir}</span>
      <span class="step-name">${st.name}</span>
      ${st.costs ? '<span class="cost" title="돈이 드는 단계입니다">$</span>' : ""}
      <span class="step-dot ${stepState(st.page)}"></span>
    </button>`).join("");
}
$("#steps").addEventListener("click", (e) => {
  const b = e.target.closest("[data-page]");
  if (b) location.hash = "#/" + b.dataset.page;
});

/* ── 화면 갈아타기 ─────────────────────────────────────────── */
function route() {
  const to = (location.hash || "#/p0").replace("#/", "");
  const known = STEPS.some((s) => s.page === to);
  if (!known) { location.hash = "#/p0"; return; }   // 없어진 옛 링크는 처음으로
  $$(".page").forEach((p) => { p.hidden = p.dataset.page !== to; });
  renderSteps();
  if (to === "p1") drawScenes("#p1-out", "p1");
  if (to === "p2") drawScenes("#p2-out", "p2");
  if (to === "p2b") drawScenes("#p2b-out", "p2b");
  if (to === "p3") loadSubs();
  if (to === "p3b") loadBundles();      // ★ 강의를 갈아탄 뒤에도 그 강의의 묶음을 본다
  if (to === "p4") { drawScenes("#p4-out", "p4"); loadBundles(); }
  // ★ 09 도 묶음을 읽는다 — 맨 위 «어느 묶음을 굽나» 가 이걸 본다
  if (to === "p5") { drawDone(); drawScenes("#p5-out", "p5"); loadBundles(); }
  drawNotes();
}

/* ── 상태 읽어 오기 ────────────────────────────────────────── */
async function refresh() {
  STATE = await api("/api/state");
  // 읽기 모드 — 사내에 열어 둔 창(lan-run.bat). 서버가 POST 를 전부 막으므로
  // 화면도 그에 맞춰 잠근다. 잠그는 일은 CSS 한 줄이 맡는다 — 목록이 나중에
  // 그려져도(묶음·완성본) 새 단추까지 같이 잠긴다.
  document.body.classList.toggle("readonly", !!STATE.readonly);
  const roBar = $("#ro-bar");
  if (roBar) roBar.hidden = !STATE.readonly;
  fillPaths();
  renderSteps();
  drawJobs();
  drawNotes();
  const cur = (location.hash || "#/p0").replace("#/", "");
  if (cur === "p3") { /* 자막은 따로 읽는다 */ } else route();
}

/* ── 재료 자리 · 스타일 ─────────────────────────────────────
 * 경로는 서버가 _context* 를 훑어 찍어 준다. 사람이 고치면 그 값이 이긴다 —
 * 고친 값은 localStorage 에 남아 창을 다시 열어도 그대로다.
 */
const PATH_KEYS = ["script", "subs", "slides", "source"];
let pathsFilled = false;
function fillPaths() {
  if (pathsFilled || !STATE.sceneDefaults) return;
  pathsFilled = true;
  for (const k of PATH_KEYS) {
    const el = $("#sc-" + k);
    const saved = localStorage.getItem("sc." + k);
    el.value = saved || STATE.sceneDefaults[k] || "";
    el.onchange = () => localStorage.setItem("sc." + k, el.value.trim());
  }
  const st = localStorage.getItem("sc.style");
  if (st) { const r = $(`input[name="style"][value="${st}"]`); if (r) r.checked = true; }
  const rg = localStorage.getItem("sc.range");
  // 옛 기본값이 저장돼 있으면 버린다. 그 값은 이 강의 하나에만 맞았다.
  if (rg && rg !== "1-32" && rg !== "1-8") $("#sc-range").value = rg;
  else localStorage.removeItem("sc.range");
  $("#sc-range").onchange = () => localStorage.setItem("sc.range", $("#sc-range").value.trim());
}
const styleOf = () => ($('input[name="style"]:checked') || {}).value || "full";
const STYLE_NAME = { full: "전면샷", panel: "여백형", both: "둘 다" };
$$('input[name="style"]').forEach((r) => {
  r.onchange = () => { localStorage.setItem("sc.style", styleOf()); drawNotes(); };
});

/* 지금 화면이 서버로 보낼 값 한 벌 — 모든 단계가 같은 것을 보낸다.
   단계마다 다른 몸통을 만들면 「전부 만들기」와 「이 단계만」이 갈린다. */
function payload(step) {
  const b = { task: task(), step: step || "",
              // 비면 «전부». 예전 기본은 "1-8" 이라 32씬 강의가 8씬만 돌았다
              scenes: $("#sc-range").value.trim() || "all",
              style: styleOf(),
              voice_engine: $("#sc-voice").value,
              avatar_engine: $("#sc-avatar").value,
              avatar_h: $("#sc-avh").value.trim(),
              avatar_src: (($("#sc-avatar-src") || {}).value || "").trim(),
              bundle_max_sec: (($("#sc-bmax") || {}).value || "590").trim(),
              bundle_pack: (($("#sc-bpack") || {}).value || "even"),
              subs_mode: $("#sc-submode").value,
              retranslate: $("#sc-retrans").checked,
              script_lang: $("#sc-scriptlang").value || "uz",
              sub_lang: (picked.join(",") || "ru"),
              slide_fit: $("#sc-fit").value };
  for (const k of PATH_KEYS) b[k] = $("#sc-" + k).value.trim();
  return b;
}

/* ── 단계마다 한 줄 설명 ────────────────────────────────────
 * 고른 값을 문장으로 다시 읽어 준다. select 를 눈으로 견주는 것보다 빠르고,
 * 크레딧이 드는지 아닌지가 누르기 **전에** 보여야 한다.
 */
function drawNotes() {
  const j = cur();
  const n = j ? j.scenes.length : 0;
  const set = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };

  set("#p1-note", j && n
    ? `씬 <b>${n}개</b> · 합계 <b>${mmss(j.total)}</b> · 자막 ${j.scenes.reduce((a, s) => a + s.cues, 0)}개`
    : "아직 안 떼었습니다. 1 재료를 채우고 누르세요.");

  const v = $("#sc-voice").value;
  set("#p2-say", v === "source"
    ? "원본 mp4 에서 씬 구간의 소리를 그대로 떼어 옵니다 — <b>진짜 우즈베크어이고 0원</b>입니다. "
      + "자막이 이 소리에 맞춰 작성된 것이라 <b>밀림이 0.06초</b>까지 떨어집니다."
    : v === "pkg" ? "씬별 음성 파일을 <b>그대로</b> 씁니다 — 재인코딩이 한 번뿐이라 소리가 가장 깨끗합니다. <b>0원</b>."
    : v === "silent" ? "무음을 만듭니다. 배치만 볼 때 씁니다. <b>0원</b>."
    : `<b style="color:var(--err)">HeyGen TTS 를 부릅니다 — 돈을 씁니다.</b> `
      + "우즈베크 보이스가 있는지 먼저 확인하세요."
      + (HEYGEN && HEYGEN.ok ? "" : ` ${HEYGEN ? HEYGEN.why : ""}`));
  set("#p2-note", j ? `목소리 있는 씬 <b>${j.scenes.filter((s) => s.voice).length}/${n}</b>` : "");

  const withSubs = j ? j.scenes.filter((s) => s.cues > 0).length : 0;
  const names = picked.map((x) => (langByTag(x) || {}).name || x).join(" · ");
  set("#p2b-say", picked.length
    ? `<b>${names}</b> 로 옮깁니다. 맨 앞 «${(langByTag(picked[0]) || {}).name || picked[0]}» 가 `
      + "영상에 구워지고 나머지는 트랙으로 얹힙니다. "
      + "<b>Claude 로그인을 쓰므로 HeyGen 과금도 API 키도 안 듭니다.</b>"
    : "언어를 하나 이상 고르세요.");
  set("#p2b-note", j
    ? (withSubs >= n && n
        ? `자막이 <b>${n}씬 모두</b> 있습니다 — 다시 만들려면 아래를 켜세요.`
        : `자막 있는 씬 <b>${withSubs}/${n}</b> — 대본에서 옮겨 채웁니다.`)
    : "");
  const bp = (($("#sc-bpack") || {}).value || "even");
  set("#p3b-say", bp === "even"
    ? "묶음 <b>수는 최소로</b> 두고 길이를 고르게 나눕니다 — 3분짜리 자투리가 안 남습니다. "
      + "묶음마다 폴더가 생기고 그 안의 <b>올릴음성.mp3</b> 을 업체에 드래그드랍합니다."
    : "앞에서부터 상한까지 꽉 채웁니다 — 첫 묶음 경계가 승인본과 같아지지만 "
      + "<b>마지막이 자투리로 남습니다</b>.");
  set("#p3b-note", j && j.bundles
    ? `묶음 <b>${j.bundles}개</b>` : "아직 안 만들었습니다.");
  set("#p3-note", j
    ? `자막은 <b>목소리 길이에 맞춰</b> 시각이 다시 매겨집니다. 문구를 고치면 저장만 하면 됩니다.`
    : "");

  drawRun();

  const av = $("#sc-avatar").value;
  const dropRow = $("#p4-drop-row");
  if (dropRow) dropRow.hidden = av !== "drop";
  set("#p4-say", av === "stub"
    ? "사람 모양 <b>임시 아바타</b>를 넣습니다 — 배경이 투명해서 진짜 아바타가 오면 같은 자리에 그대로 들어갑니다. <b>0원</b>."
    : av === "drop"
    ? "<b>1</b> 아래 <b>묶음 폴더 열기</b>를 눌러 <b>올릴음성.mp3</b> 를 꺼냅니다"
      + " (씬을 나눠 받으려면 <b>장면\</b> 안의 mp3 를 씁니다). "
      + "<b>2</b> HeyGen 웹에 드래그드랍해 렌더하고 내려받습니다. "
      + "<b>3</b> 받은 영상을 <b>그 묶음 폴더에 되돌려</b> 놓습니다. "
      + "<b>4</b> 여기서 <b>실행</b>을 누릅니다 — 영상은 <b>자르지 않습니다</b>. "
      + "씬마다 «어디서부터 몇 초»만 적어 두고 다음 단계가 그 구간만 읽습니다."
    : `<b style="color:var(--err)">HeyGen API 를 부릅니다 — 초당 과금입니다.</b> `
      + (HEYGEN && HEYGEN.rate_now
          ? `${HEYGEN.engine} · 초당 $${HEYGEN.rate_now}`
          : "")
      + (HEYGEN && HEYGEN.ok ? "" : ` ${HEYGEN ? HEYGEN.why : ""}`));
  const noAv = j ? j.scenes.filter((s) => !s.avatar).map((s) => s.no) : [];
  set("#p4-note", j
    ? `아바타 있는 씬 <b>${n - noAv.length}/${n}</b>`
      + (noAv.length && noAv.length < n
          ? ` · 남은 씬 <b>${noAv.slice(0, 8).join(",")}${noAv.length > 8 ? "…" : ""}</b>`
          : "")
    : "");

  const sm = $("#sc-submode").value;
  $("#p5-style").value = STYLE_NAME[styleOf()];
  set("#p5-say", (styleOf() === "panel"
      ? "슬라이드는 왼쪽 칸, 발표자는 오른쪽 칸. <b>슬라이드 아래가 자막 선에 붙습니다.</b>"
      : "슬라이드가 화면을 꽉 채우고 발표자가 그 위에 섭니다.")
    + " " + (sm === "burn" ? "자막은 <b>픽셀에 구워</b> 어디서나 보입니다."
      : sm === "soft" ? "자막은 <b>끌 수 있는 트랙</b>입니다 — 플레이어가 안 켜면 안 보입니다."
      : "자막은 영상에 안 넣고 <b>srt 로만</b> 넘깁니다."));
  // 분모는 «아바타가 온 씬» 이다 (stepState 와 같은 셈). 전체와 다르면 그것도 적어
  // 준다 — «7/7 인데 왜 32씬 강의가 다 안 나오지» 를 화면이 먼저 답해야 한다.
  const nAv = j ? j.scenes.filter((s) => s.avatar).length : 0;
  set("#p5-note", j
    ? `구운 씬 <b>${j.scenes.filter((s) => s.preview).length}/${nAv}</b>`
      + (nAv < n ? ` <span class="run-dim">아바타 온 씬만 굽습니다 · 전체 ${n}</span>` : "")
    : "");
}
for (const id of ["#sc-voice", "#sc-avatar", "#sc-submode", "#sc-fit"])
  $(id).onchange = () => { drawNotes(); drawAvatar(); };


/* ── 다국어 자막 — 언어 고르기 ──────────────────────────────
 * 두 글자 코드를 외우게 하지 않는다. 목록에서 눌러 담고, «러시아»·«Русский»·«ru»
 * 무엇으로 찾아도 걸린다. 문자 체계로 묶는 이유는 **읽는 속도가 문자마다 달라서**다 —
 * 한중일 6~7자/초, 라틴·키릴 14~15자/초. 그 값이 번역 길이의 상한이 된다.
 */
async function loadLangs() {
  try { LANGS = await api("/api/langs"); } catch { return; }
  const sel = $("#sc-scriptlang");
  if (sel && !sel.options.length) {
    sel.innerHTML = LANGS.langs
      .map((l) => `<option value="${l.tag}">${l.name} · ${l.native}</option>`).join("");
    sel.value = localStorage.getItem("sc.scriptlang") || "uz";
    sel.onchange = () => localStorage.setItem("sc.scriptlang", sel.value);
  }
  // ★ 맨 앞은 **처음에 넣은 자막의 언어**다. 고르는 것이 아니라 이미 있는 것이라
  //   목록에서 빠질 수 없다 — 이것이 영상에 구워지는 언어이기도 하다.
  //   localStorage 에 옛 선택이 남아 있어도 기본은 늘 앞에 되박는다.
  const saved = (localStorage.getItem("sc.sublangs") || "").split(",").filter(Boolean);
  picked = [...new Set([baseLang(), ...saved])].filter(Boolean);
  drawLangs();
}

const langByTag = (tag) => LANGS.langs.find((l) => l.tag === tag);

/* 처음에 넣은 자막의 언어. 00/ 의 srt 가 무슨 말이었나 — p1 이 scenes.json 에
   `sub_lang` 으로 적어 둔다. 강의를 안 골랐으면 «ru» 로 떨어뜨린다. */
const baseLang = () => (cur() || {}).sub_lang || "ru";

function drawLangs() {
  localStorage.setItem("sc.sublangs", picked.join(","));
  const j = cur();

  // 고른 것 — 맨 앞이 기본 자막이다. 줄 수를 같이 보여 준다.
  const host = $("#lang-picked");
  if (host) {
    const base = baseLang();
    const have = (j && j.langs_have) || [];
    host.innerHTML = picked.map((tag) => {
      const l = langByTag(tag);
      const fixed = tag === base;
      const n = j && have.includes(tag)
        ? j.scenes.reduce((a, s) => a + s.cues, 0) : 0;
      // 기본은 못 뺀다 — data-drop 을 안 달아 클릭이 아무 일도 안 하게 한다
      return `<span class="lang-chip on${fixed ? " lang-fixed" : ""}"` +
        (fixed ? "" : ` data-drop="${tag}"`) + `>` +
        `<b>${l ? l.native : tag}</b> ${l ? l.name : ""}` +
        (fixed ? '<i class="lang-first">넣은 것 · 기본</i>'
               : (n ? '<i class="lang-n">있음</i>' : "")) +
        (n && fixed ? `<i class="lang-n">${n}줄</i>` : "") +
        (fixed ? "" : '<i class="lang-x">×</i>') + `</span>`;
    }).join("");
  }

  // 전체 목록 — 문자 체계로 묶고 자/초를 같이 적는다
  const all = $("#lang-all");
  if (all) {
    $("#lang-count").textContent = `${LANGS.langs.length}개`;
    all.innerHTML = LANGS.scripts.map(({ key, label }) => {
      const ls = LANGS.langs.filter((l) => l.script === key);
      if (!ls.length) return "";
      const cps = [...new Set(ls.map((l) => l.cps))].sort((a, b) => a - b);
      return `<div class="lang-group"><div class="lang-gh">${label}` +
        `<span class="lang-cps">${cps.join("~")}자/초</span></div>` +
        `<div class="lang-row">` + ls.map((l) => {
          const fixed = l.tag === baseLang();
          const made = ((cur() || {}).langs_have || []).includes(l.tag);
          return `<button type="button" class="lang-chip` +
            (picked.includes(l.tag) ? " on" : "") + (fixed ? " lang-fixed" : "") + `" ` +
            (fixed ? "" : `data-add="${l.tag}" `) +
            `title="${l.name} · 꼬리표 ${l.tag} · ${l.cps}자/초` +
            (fixed ? " · 처음에 넣은 자막이라 뺄 수 없습니다" : "") + `">` +
            `<b>${l.native}</b> ${l.name} <i class="lang-tag">${l.tag}</i>` +
            (fixed ? '<i class="lang-n">기본</i>'
                   : (made ? '<i class="lang-n">있음</i>' : "")) + `</button>`;
        }).join("") +
        `</div></div>`;
    }).join("");
  }
}

/* ── 눌러야 하나 ──────────────────────────────────────────────────────────
 * 「실행」이 늘 같은 말이면 «지금 눌러야 하는 것인지» 를 화면이 안 알려 준다.
 * 이미 산출물이 있는 단계는 누르면 **다시 만드는** 것이라 말을 바꾼다 —
 *   없음 → 「실행」  + 눌러야 합니다
 *   일부 → 「이어서」 + 남은 것만 채웁니다
 *   전부 → 「재실행」 + 고칠 때만 누르세요
 * 되돌릴 수 없는 일이 아니어도, 8분짜리를 다시 굽는 데 드는 시간은 실제다.
 */
function drawRun() {
  const SAY = {
    "":     ["실행",   "must", "눌러야 합니다"],
    part:   ["이어서", "part", "남은 것만 채웁니다"],
    done:   ["재실행", "done", "다 됐습니다 — 고칠 때만 누르세요"],
  };
  for (const st of STEPS) {
    if (!st.run) continue;
    const b = $(`#btn-${st.run}`);
    const note = $(`#${st.run}-note`);
    const [word, cls, why] = SAY[stepState(st.page)] || SAY[""];
    if (b) {
      const lab = b.querySelector("span:last-child");
      if (lab) lab.textContent = word;
      b.classList.toggle("btn-again", word === "재실행");
    }
    if (note && !note.querySelector(".run-must")) {
      note.insertAdjacentHTML("beforeend",
        ` <b class="run-must ${cls}">${why}</b>`);
    } else if (note) {
      const m = note.querySelector(".run-must");
      m.className = `run-must ${cls}`; m.textContent = why;
    }
  }
}

document.addEventListener("click", (e) => {
  const add = e.target.closest("[data-add]");
  if (add) {
    const tag = add.dataset.add;
    if (tag === baseLang()) return;                       // 기본은 못 뺀다
    picked = picked.includes(tag) ? picked.filter((x) => x !== tag) : [...picked, tag];
    drawLangs(); drawNotes(); return;
  }
  const drop = e.target.closest("[data-drop]");
  if (drop) {
    if (drop.dataset.drop !== baseLang()) {
      picked = picked.filter((x) => x !== drop.dataset.drop);
    }
    drawLangs(); drawNotes();
  }
});

$("#lang-find").oninput = () => {
  const q = $("#lang-find").value.trim().toLowerCase();
  $$("#lang-all .lang-chip").forEach((b) => {
    const l = langByTag(b.dataset.add);
    const hit = !q || !l ||
      l.name.toLowerCase().includes(q) || l.native.toLowerCase().includes(q) ||
      l.tag.includes(q) || l.iso.includes(q);
    b.style.display = hit ? "" : "none";
  });
  $$("#lang-all .lang-group").forEach((g) => {
    g.style.display = $$(".lang-chip", g).some((b) => b.style.display !== "none") ? "" : "none";
  });
};

/* ── 돌리기 ────────────────────────────────────────────────── */
function drawProgress(cur, failed, running, steps, sec) {
  const host = $("#dock-now");
  if (!host) return;
  const now = (steps || []).find((s) => s.key === cur);
  const what = !running && cur === "done" ? "끝났습니다"
    : failed ? "멈췄습니다" : now ? now.label : "";
  // 기록창을 접어 두어도 머리에 시간이 보인다 — 여기가 «도는 중» 을 보는 자리다
  host.textContent = what + (sec ? `  ${hms(sec)}` : "");
}

/* ── 얼마나 걸리나 ────────────────────────────────────────────────────────
 * ★ 씬 하나 굽는 데 20초, 일곱 씬을 두 배치로 구우면 5분이다. 그동안 화면이
 *   «돌고 있습니다» 만 말하면 멈춘 건지 도는 건지 몰라 기록창의 흐르는 글자를
 *   들여다보게 된다 — 실제로 다 끝나기 전에 «완료예요?» 를 물었다.
 * ★ **실행 단추 옆**에 붙인다. 누른 사람이 보고 있는 자리가 거기다. 도는
 *   단계가 바뀌면 같은 칸이 그 단계의 줄로 옮겨 간다 — 칸을 여럿 만들지 않는다.
 * ★ 끝난 뒤에도 지우지 않는다. «저건 4분 걸리는 일» 이 다음 번 예상이 된다.
 */
let SEC_EL = null, SEC_STEP = "";
const hms = (t) => {
  t = Math.max(0, Math.round(Number(t) || 0));
  const m = Math.floor(t / 60), s = t % 60;
  return m ? `${m}분 ${String(s).padStart(2, "0")}초` : `${s}초`;
};
function drawElapsed(step, sec, running, failed) {
  // 끝나면 step 이 "done" 이 된다 — 그때는 마지막으로 돌던 단계의 줄에 남긴다
  if (step && step !== "done") SEC_STEP = step;
  const btn = $("#btn-" + SEC_STEP);
  const row = btn && btn.closest(".run-in");
  if (!row || !sec) return;
  if (!SEC_EL) SEC_EL = document.createElement("span");
  if (SEC_EL.parentElement !== row) row.insertBefore(SEC_EL, btn);
  SEC_EL.className = "run-sec" + (running ? " on" : "");
  SEC_EL.textContent = running ? `${hms(sec)} 도는 중`
    : failed ? `${hms(sec)} 만에 멈췄습니다` : `${hms(sec)} 걸렸습니다`;
}

async function tick() {
  let s;
  try { s = await api(`/api/log?since=${logSeen}`); } catch { return; }
  if (s.lines.length) {
    const pre = $("#log");
    pre.textContent += s.lines.join("\n") + "\n";
    pre.scrollTop = pre.scrollHeight;
    logSeen = s.total;
  }
  drawProgress(s.step, s.failed, s.running, s.steps, s.sec);
  drawElapsed(s.step, s.sec, s.running, s.failed);
  if (!s.running) {
    clearInterval(poll); poll = null;
    $$(".btn-ink").forEach((b) => { b.disabled = false; });
    await refresh();
    if ((location.hash || "") === "#/p3") loadSubs();
    toast(s.failed ? "멈췄습니다 — 아래 기록을 보세요"
                   : `끝났습니다 — ${hms(s.sec)} 걸렸습니다`, s.failed);
  }
}

/* 한 단계를, **정해진 씬 범위만** 돌린다.
   묶음 하나가 왔을 때 서른두 씬을 전부 다시 재게 하면 안 된다. */
async function runScenes(step, range, btn) {
  if (btn) btn.disabled = true;
  showDock(true);
  $("#log").textContent = "";
  logSeen = 0;
  try {
    await post("/api/scene-step", { ...payload(step), scenes: range });
  } catch (e) {
    if (btn) btn.disabled = false;
    return toast(e.message, true);
  }
  if (poll) clearInterval(poll);
  poll = setInterval(tick, 1000);
  tick();
}

async function run(step, btnSel) {
  const btn = $(btnSel);
  if (btn) btn.disabled = true;
  showDock(true);
  $("#log").textContent = "";
  logSeen = 0;
  try {
    await post(step ? "/api/scene-step" : "/api/scene-run", payload(step));
  } catch (e) {
    if (btn) btn.disabled = false;
    return toast(e.message, true);
  }
  if (poll) clearInterval(poll);
  poll = setInterval(tick, 1000);
  tick();
}

$("#btn-all").onclick = () => run("", "#btn-all");
$("#btn-p1").onclick = () => run("p1", "#btn-p1");
$("#btn-p1b").onclick = () => run("p1", "#btn-p1b");
$("#btn-p2").onclick = () => run("p2", "#btn-p2");
$("#btn-p2b").onclick = () => run("p2b", "#btn-p2b");
$("#btn-p3").onclick = () => run("p3", "#btn-p3");
$("#btn-p4").onclick = () => run("p4", "#btn-p4");
/* 09 실행 — 맨 위에서 **고른 묶음의 씬만** 굽는다.
   ★ 이어붙인 `all*.mp4` 는 **이번에 구운 것**으로만 만들어진다. 한 편을
     통째로 다시 얻으려면 «전체» 를 켜고 눌러야 한다. */
$("#btn-p5").onclick = () => {
  const rows = BUNDLES.bundles || [];
  if (!rows.length) return run("p5", "#btn-p5");   // 묶음이 없으면 예전 길
  const sel = new Set(pickedNos());
  if (!sel.size) return toast("고른 묶음이 없습니다 — 아바타를 먼저 붙이세요", true);
  const range = rows.filter((b) => sel.has(Number(b.no)))
    .map((b) => { const n = b.scenes || []; return `${n[0]}-${n[n.length - 1]}`; })
    .join(",");
  runScenes("p5", range, $("#btn-p5"));
};

/* ── 씬 목록 ───────────────────────────────────────────────
 * 단계마다 같은 목록을 쓰되 **그 단계가 만든 것만** 굵게 보여 준다.
 * 목록을 단계마다 새로 짜면 씬 번호와 제목이 화면마다 달라 보인다.
 */
function drawScenes(hostSel, forStep) {
  const host = $(hostSel);
  if (!host) return;
  const j = cur();
  host.innerHTML = "";
  if (!j || !j.scenes.length) {
    host.innerHTML = '<p class="job-empty">아직 씬이 없습니다. 2 씬에서 떼어 내세요.</p>';
    return;
  }
  const grid = document.createElement("div");
  grid.className = "sc-grid";
  for (const s of j.scenes) {
    const c = document.createElement("div");
    const ready = { p1: s.slide, p2: s.voice, p2b: s.cues > 0,
                    p3: s.voice && s.cues > 0, p4: s.avatar, p5: !!s.preview }[forStep];
    c.className = "sc-card" + (ready ? "" : " pending");
    // 묶음이 갈리는 자리는 색으로 보인다 — 홀수 묶음과 짝수 묶음이 서로 다른
    // 바닥색을 쓴다. 어느 씬이 어느 묶음에 실려 업체로 가는지 세지 않아도 되게.
    if (s.bundle) c.dataset.bundle = (s.bundle % 2) ? "odd" : "even";
    // 4칸 = 슬라이드 · 목소리 · 아바타 · 검수본. 씬마다 어디까지 됐는지
    // 한눈에 보이게 — 목록을 훑으며 «이 씬은 아바타가 왔나» 를 세지 않아도 되게.
    const dots = [["슬라이드", s.slide], ["목소리", s.voice],
                  ["아바타", s.avatar], ["검수본", !!s.preview]]
      .map(([lab, on]) => `<i class="${on ? "on" : ""}" title="${lab}"></i>`).join("");
    c.innerHTML =
      `<div class="sc-h"><span class="sc-no">${String(s.no).padStart(2, "0")}</span>` +
      (s.bundle ? `<span class="sc-b">묶음 ${s.bundle}</span>` : "") +
      `<span class="dots">${dots}</span></div>` +
      `<div class="sc-t" title="${s.title}">${s.title}</div>` +
      `<div class="sc-m">${mmss(s.dur)} · 자막 ${s.cues}개` +
      (s.over ? ` · <b class="bad">${s.over}줄 초과</b>` : "") + `</div>`;
    if (forStep === "p5" && s.preview) {
      const v = document.createElement("video");
      v.controls = true; v.preload = "none";
      v.src = `/api/scene-media?task=${encodeURIComponent(j.task)}` +
              `&rel=preview/${encodeURIComponent(s.preview)}`;
      c.appendChild(v);
    }
    grid.appendChild(c);
  }
  host.appendChild(grid);
}

/* ── 7 결과 ────────────────────────────────────────────────── */
function drawDone() {
  const host = $("#sc-out");
  const j = cur();
  host.innerHTML = "";
  if (!j || !j.scenes.length) {
    host.innerHTML = '<p class="job-empty">아직 만든 것이 없습니다.</p>';
    return;
  }
  const box = document.createElement("div");
  box.className = "out-job";
  const done = j.scenes.filter((s) => s.preview).length;
  box.innerHTML = `<div class="out-head"><h2>${j.task}</h2>` +
    `<span>자막 ${j.sub_lang} · ${mmss(j.total)} · ${done}/${j.scenes.length}씬</span></div>`;

  /* ── 완성본 목록 ─────────────────────────────────────────────────────
   * ★ **덮어쓰지 않고 쌓인다.** p5 가 이름 앞에 «연월일-시분» 을 붙이므로
   *   새로 구운 것이 맨 위다. 한 강의를 여러 번 굽는 것이 정상이라 —
   *   묶음이 하나씩 오고, 스타일을 바꿔 보고, 자막을 고쳐 다시 굽는다 —
   *   앞 것이 사라지면 «아까 그게 나았는데» 를 되돌릴 길이 없다.
   * ★ 목록은 09 폴더를 읽어 만든다. 뒤쪽 이름은 사람이 고쳐도 그대로 뜬다.
   * ★ 화면에는 재생기를 **하나만** 둔다. 스무 개가 쌓였을 때 재생기를 스무 개
   *   놓으면 창이 무거워진다 — 줄을 누르면 그 줄이 위 재생기에 올라온다.
   */
  const builds = j.builds || (j.all ? [{ name: j.all, at: "", mb: 0 }] : []);
  if (builds.length) {
    const whole = document.createElement("div");
    whole.className = "sc-whole";
    const srcOf = (name) => `/api/scene-media?task=${encodeURIComponent(j.task)}`
      + `&rel=preview/${encodeURIComponent(name)}`;
    whole.innerHTML = `<div class="sc-cap">완성본 <b>${builds.length}개</b>`
      + ` — 새로 구운 것이 맨 위입니다</div>`
      + `<video controls preload="metadata" src="${srcOf(builds[0].name)}"></video>`
      + `<div class="build-list">` + builds.map((b, i) =>
          `<button type="button" class="build${i ? "" : " on"}" data-build="${b.name}">`
          + `<span class="build-n">${b.name}</span>`
          + `<span class="build-s">${b.at}${b.mb ? " · " + b.mb + "MB" : ""}</span>`
          + `</button>`).join("") + `</div>`;
    whole.addEventListener("click", (e) => {
      const row = e.target.closest("[data-build]");
      if (!row) return;
      whole.querySelector("video").src = srcOf(row.dataset.build);
      whole.querySelectorAll(".build").forEach((x) => x.classList.remove("on"));
      row.classList.add("on");
    });
    box.appendChild(whole);
  }

  const acts = document.createElement("div");
  acts.className = "out-acts";
  const mk = (label, path, iconName) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn-plain";
    b.innerHTML = `<span data-icon="${iconName}" data-icon-size="14"></span><span>${label}</span>`;
    b.onclick = () => post("/api/open", { path })
      .then(() => toast("폴더를 열었습니다"))
      .catch((e) => toast(e.message, true));
    return b;
  };
  acts.append(mk("검수본 폴더", j.preview_dir, "film"),
              mk("작업 폴더 전체", j.path, "folder"));
  box.appendChild(acts);
  host.appendChild(box);
  hydrateIcons(box);
}

/* ── 4 자막 ────────────────────────────────────────────────── */
const subLang = () => {
  const m = /scene\d+\.([a-z]{2})\.srt/.exec($("#sub-scene").value || "");
  return m ? m[1] : (cur() || {}).sub_lang || "ru";
};

async function loadSubs(file) {
  let d;
  try {
    d = await api(`/api/scene-subs?task=${encodeURIComponent(task())}` +
                  (file ? `&file=${encodeURIComponent(file)}` : ""));
  } catch (e) {
    // 어디를 봤는데 없었는지 말한다. «먼저 만드세요» 만 띄우면 이미 만들어 둔
    // 사람은 무엇이 틀렸는지 알 길이 없다.
    $("#cue-list").innerHTML =
      `<li class="job-empty">«${task()}» 의 <code>03</code> 에서 자막을 못 읽었습니다 — ` +
      `${e.message}. 강의를 다시 고르거나 <b>03 자막</b>을 실행하세요.</li>`;
    $("#sub-scene").innerHTML = "";
    return;
  }
  const sel = $("#sub-scene");
  sel.innerHTML = "";
  for (const f of d.files) {
    const o = document.createElement("option");
    o.value = f;
    o.textContent = (/scene(\d+)/.exec(f) || [, f])[1] + "번 씬";
    sel.appendChild(o);
  }
  if (d.file) sel.value = d.file;
  cues = d.cues;
  drawCues();
}

function drawSubStat() {
  const max = CUE_MAX[subLang()] || 46;
  const over = cues.filter((c) => c.text.length > max).length;
  $("#sub-stat").textContent =
    `큐 ${cues.length}개 · 한 줄 최대 ${max}자 · 넘긴 줄 ${over}개`;
}

function drawCues() {
  const max = CUE_MAX[subLang()] || 46;
  const ul = $("#cue-list");
  ul.innerHTML = "";
  for (const c of cues) {
    const li = document.createElement("li");
    if (c.text.length > max) li.classList.add("over");
    li.innerHTML = `<span class="cue-i">${c.i}</span>` +
      `<span class="cue-t">${mmss(c.start)}</span>`;
    const inp = document.createElement("input");
    const cnt = document.createElement("span");
    inp.type = "text"; inp.value = c.text;
    cnt.className = "cue-n"; cnt.textContent = String(c.text.length);
    inp.oninput = () => {
      c.text = inp.value;
      cnt.textContent = String(inp.value.length);
      li.classList.toggle("over", inp.value.length > max);
      drawSubStat();
    };
    li.append(inp, cnt);
    ul.appendChild(li);
  }
  drawSubStat();
}

$("#sub-scene").onchange = () => loadSubs($("#sub-scene").value);
$("#btn-sub-save").onclick = async () => {
  try {
    const r = await post("/api/scene-subs",
      { task: task(), file: $("#sub-scene").value, cues });
    toast(`저장했습니다 — ${r.saved}개. 6 빌드를 다시 돌리면 반영됩니다.`);
  } catch (e) { toast(e.message, true); }
};

/* ── 오른쪽 서랍 — 작업 목록 ───────────────────────────────── */
function drawJobs() {
  const ul = $("#job-list");
  const q = ($("#job-filter").value || "").trim().toLowerCase();
  const rows = (STATE.scenes || []).filter((j) => !q || j.task.toLowerCase().includes(q));
  $("#drawer-count").textContent = String((STATE.scenes || []).length);
  ul.innerHTML = "";
  if (!rows.length) {
    ul.innerHTML = `<li class="job-empty">${q ? "찾는 것이 없습니다" : "아직 없습니다"}</li>`;
    return;
  }
  for (const j of rows) {
    const li = document.createElement("li");
    const dots = STEPS.filter((s) => s.run)
      .map((s) => `<i class="${stepState(s.page) === "done" ? "on" : ""}" title="${s.name}"></i>`)
      .join("");
    li.innerHTML = `<button type="button"><span class="job-name">${j.task}</span>` +
      `<span class="job-meta">${mmss(j.total)} · 씬 ${j.scenes.length}개</span>` +
      `<span class="dots">${dots}</span></button>`;
    ul.appendChild(li);
  }
}
$("#job-filter").oninput = drawJobs;

/* ── HeyGen 연결 ────────────────────────────────────────────
 * 키는 서버 파일(heygen.local.json)에만 들어간다. 저장한 뒤 입력란을 비우는 것은
 * 화면을 녹화해 공유하는 일이 잦기 때문이다 — 상태는 문장으로만 말한다.
 */
async function loadHeygen() {
  try { HEYGEN = await api("/api/heygen"); } catch { HEYGEN = null; }
  if (HEYGEN && HEYGEN.voice_uz) $("#sc-voice-id").value = HEYGEN.voice_uz;
  if (HEYGEN && HEYGEN.avatar_id) $("#sc-avatar-id").value = HEYGEN.avatar_id;
  if (HEYGEN && HEYGEN.engine && $("#sc-hg-engine")) $("#sc-hg-engine").value = HEYGEN.engine;
  if (HEYGEN && HEYGEN.motion_prompt && $("#sc-hg-motion"))
    $("#sc-hg-motion").value = HEYGEN.motion_prompt;
  drawHeygenWhy();
  drawNotes();
}

function drawHeygenWhy() {
  const el = $("#sc-heygen-why");
  const dot = $("#heygen-dot");
  // ★ 좌하단 단추를 뺐으므로 없을 수 있다. 없으면 카드 문구만 고친다.
  if (!dot) { if (el && HEYGEN) el.innerHTML = HEYGEN.why; return; }
  // ★ 키가 없는 것은 **오류가 아니다** — 웹 드래그드랍으로 가면 필요 없다.
  //   그래서 붉은 점(bad)을 쓰지 않는다. 키는 있는데 아바타를 안 고른 어중간한
  //   상태만 노랗게 둔다 — 그건 실제로 p4 가 멈추는 상태다.
  dot.className = "conn-dot" + (!HEYGEN ? "" : HEYGEN.ok ? " ok" : HEYGEN.key ? " warn" : "");
  $("#heygen-t1").textContent = !HEYGEN ? "확인 중…"
    : HEYGEN.ok ? "HeyGen API 연결됨" : HEYGEN.key ? "아바타를 안 골랐습니다" : "HeyGen API 안 씀";
  $("#heygen-t2").textContent = !HEYGEN ? ""
    : HEYGEN.ok ? (HEYGEN.avatar_id || "") : HEYGEN.key ? "look id 를 넣으세요" : "웹 드래그드랍으로 갑니다";
  if (!el) return;
  if (!HEYGEN) { el.textContent = "HeyGen 상태를 읽지 못했습니다."; return; }
  const bits = [HEYGEN.key ? "키 <b>있음</b>" : "키 <b>없음</b>"];
  bits.push(HEYGEN.avatar_id ? "아바타 <b>" + HEYGEN.avatar_id + "</b>" : "아바타 <b>안 고름</b>");
  if (HEYGEN.engine) bits.push("엔진 <b>" + HEYGEN.engine + "</b>"
                               + (HEYGEN.rate_now ? ` ($${HEYGEN.rate_now}/초)` : ""));
  if (HEYGEN.voice_uz) bits.push("보이스 <b>" + HEYGEN.voice_uz + "</b>");
  el.innerHTML = bits.join(" · ") + " — " + HEYGEN.why;
  el.className = "sc-hint" + (HEYGEN.ok ? " ok" : "");
}
if ($("#heygen-btn")) $("#heygen-btn").onclick = () => { location.hash = "#/p0"; };

$("#btn-key").onclick = async () => {
  const key = $("#sc-key").value.trim();
  const voice = $("#sc-voice-id").value.trim();
  const av = $("#sc-avatar-id").value.trim();
  const eng = (($("#sc-hg-engine") || {}).value || "").trim();
  const motion = (($("#sc-hg-motion") || {}).value || "").trim();
  if (!key && !voice && !av && !eng && !motion) return toast("넣을 값이 없습니다", true);
  try {
    const r = await post("/api/heygen-key",
                         { api_key: key, voice_uz: voice, avatar_id: av,
                           engine: eng, motion_prompt: motion });
    HEYGEN = r.status;
    $("#sc-key").value = "";
    drawHeygenWhy();
    drawNotes();
    toast("저장했습니다 — " + HEYGEN.why);
  } catch (e) { toast(e.message, true); }
};

/* ── Claude 연결 ───────────────────────────────────────────
 * 자막 번역이 필요할 때만 쓴다. 로그인 자체는 화면이 못 한다 — OAuth 는
 * 브라우저와 CLI 가 주고받는 것이라 중간에서 토큰을 만지면 안 된다.
 */
function maskEmail(e) {
  const m = /^(.{1,2})[^@]*(@.+)$/.exec(e || "");
  return m ? `${m[1]}****${m[2]}` : (e || "");
}

function drawConn() {
  const c = CONN;
  $("#conn-dot").className = "conn-dot" + (!c ? "" : c.ok ? " ok" : c.cli ? " warn" : " bad");
  $("#conn-t1").textContent = !c ? "확인 중…" : (c.ok ? "Claude 연결됨" : "Claude 연결 안 됨");
  $("#conn-t2").textContent = !c ? "" : (c.ok ? (maskEmail(c.email) || c.method || "") : c.why);
  const rows = $("#conn-rows");
  if (!rows) return;
  const yn = (v, yes, no) => v ? `<dd>${yes}</dd>` : `<dd class="no">${no}</dd>`;
  rows.innerHTML = !c ? "" : [
    `<div><dt>실행 파일</dt>${yn(c.cli, "찾음", "못 찾음")}</div>`,
    `<div><dt>로그인</dt>${c.login ? `<dd>${c.email || "로그인됨"}</dd>`
      : `<dd class="hold">안 되어 있음</dd>`}</div>`,
    c.login && c.org ? `<div><dt>조직</dt><dd>${c.org}${c.plan ? " · " + c.plan : ""}</dd></div>` : "",
    `<div><dt>파이썬 붙임</dt>${yn(c.sdk, "claude-agent-sdk 있음",
      "claude-agent-sdk 없음 — setup.bat 을 다시 돌리세요")}</div>`,
    c.api_key_env
      ? `<div><dt>API 키</dt><dd class="hold">환경변수에 있음 — 파이프라인은 무시합니다</dd></div>` : "",
    c.path ? `<div><dt>경로</dt><dd style="font-weight:500;font-size:11.5px">${c.path}</dd></div>` : "",
  ].filter(Boolean).join("");
}

async function loadConn() {
  try { CONN = await api("/api/claude"); } catch { CONN = null; }
  drawConn();
}

function openConn(on) {
  $("#conn-scrim").hidden = !on;
  $("#conn-sheet").hidden = !on;
  if (on) loadConn();
}
$("#conn-btn").onclick = () => openConn(true);
$("#conn-close").onclick = () => openConn(false);
$("#conn-scrim").onclick = () => openConn(false);
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#conn-sheet").hidden) openConn(false);
});
$("#conn-refresh").onclick = async () => {
  await loadConn();
  toast(CONN && CONN.ok ? "연결됐습니다" : (CONN ? CONN.why : "확인하지 못했습니다"),
        !(CONN && CONN.ok));
};
for (const [id, act, label] of [
  ["#conn-login", "login", "로그인"],
  ["#conn-switch", "switch", "다른 계정으로"],
  ["#conn-logout", "logout", "로그아웃"],
]) {
  $(id).onclick = async () => {
    try {
      await post("/api/claude-act", { act });
      toast(`콘솔 창을 열었습니다 — ${label}을 마친 뒤 '다시 확인'을 누르세요`);
    } catch (e) { toast(e.message, true); }
  };
}

/* ── 접기 셋 ────────────────────────────────────────────────
 * 레일 · 서랍 · 도크가 따로 접힌다. 자막을 다듬을 때는 셋 다 접고 넓게,
 * 돌릴 때는 도크만 펴서 기록을 본다. 접힘은 localStorage 에 남는다.
 */
function setFlag(cls, on, key) {
  document.body.classList.toggle(cls, on);
  if (key) localStorage.setItem(key, on ? "1" : "");
}
const railOff = () => document.body.classList.contains("rail-off");
const drawerOff = () => document.body.classList.contains("drawer-off");

$("#rail-toggle").onclick = () => {
  setFlag("rail-off", !railOff(), "railOff");
  $("#rail-toggle").title = railOff() ? "메뉴 펼치기 (Ctrl+B)" : "메뉴 접기 (Ctrl+B)";
};
$("#drawer-toggle").onclick = () => {
  setFlag("drawer-off", !drawerOff(), "drawerOff");
  $("#drawer-toggle").title = drawerOff() ? "현황 펼치기 (Ctrl+J)" : "현황 접기 (Ctrl+J)";
};
function showDock(on) {
  setFlag("dock-on", on);
  $("#dock").hidden = !on;
}
$("#dock-toggle").onclick = () => {
  setFlag("dock-min", !document.body.classList.contains("dock-min"), "dockMin");
};
window.addEventListener("keydown", (e) => {
  if (!e.ctrlKey || e.altKey || e.metaKey) return;
  const k = e.key.toLowerCase();
  if (k === "b") { e.preventDefault(); $("#rail-toggle").click(); }
  if (k === "j") { e.preventDefault(); $("#drawer-toggle").click(); }
});
setFlag("rail-off", localStorage.getItem("railOff") === "1");
setFlag("drawer-off", localStorage.getItem("drawerOff") === "1");
setFlag("dock-min", localStorage.getItem("dockMin") === "1");


/* ══ 강의 고르기 · 묶음 보기 ═══════════════════════════════════════════════
 *
 * ★ **강의를 고르는 것이 첫 동작이다.** 120강까지 쌓이는데 안 고른 채로 아래
 *   값을 만지면 남의 강의를 덮어쓴다. 그래서 목록이 1 재료 맨 위에 있다.
 *
 * ★ 처음에는 lectures.js 로 갈라 뒀다가 여기로 합쳤다 — main.js 가 ES 모듈이라
 *   위의 $ · api · toast · run 이 모듈 밖에서 안 보인다(2026-09-02 실측).
 *   window 에 얹어 내보내는 방법도 있지만, 그러면 어디서 무엇이 보이는지가
 *   흐려진다. 같은 모듈 안에 두는 편이 읽기 쉽다.
 */

let LECS = [];
let BUNDLES = { bundles: [], upload: "" };

/* ── 강의 ───────────────────────────────────────────────────── */

async function loadLectures() {
  try {
    const r = await api("/api/lectures");
    LECS = r.lectures || [];
    // ★ 저장해 둔 강의 이름이 지금 «강의/» 에 없으면 버린다. 폴더 이름을
    //   바꾸거나 지운 뒤에도 그 이름을 붙들면, 화면이 없는 폴더를 보며
    //   «아직 안 만들었습니다» 만 되풀이한다 (묶음도 자막도 같이 빈다).
    if (TASK && !LECS.some((L) => L.task === TASK)) {
      const was = TASK;
      TASK = "";
      localStorage.removeItem("sc.task");
      toast(`«${was}» 강의가 없어 «${(LECS[0] || {}).task || "없음"}» 으로 돌립니다`);
      refresh().then(() => { loadBundles(); }).catch(() => {});
    }
    const el = $("#lec-hint");
    if (!LECS.length) {
      el.innerHTML = `<b>강의가 없습니다.</b> <code>${r.dir}</code> 안에 폴더를 만들고 `
        + `그 안에 <code>00</code> 을 만들어 재료를 넣으세요 — `
        + `mp4 · 번역 자막 srt · 대본 txt · slides 폴더.`;
    } else {
      el.innerHTML = `<code>${r.dir}</code> 를 읽었습니다. 폴더 하나가 강의 하나입니다 — `
        + `<b>고르면</b> 아래 재료 자리가 그 강의로 채워집니다.`;
    }
    drawLectures();
    await fixStalePaths();
  } catch (e) {
    $("#lec-hint").textContent = "강의 목록을 읽지 못했습니다: " + e.message;
  }
}

/* 저장해 둔 재료 자리가 **없어졌으면** 지금 고른 강의 것으로 되돌린다.
 *
 * ★ 경로 네 개는 사람이 고칠 수 있어 브라우저에 남긴다(fillPaths). 그런데
 *   프로젝트 폴더를 옮기거나 이름을 바꾸면 그 값만 옛 자리를 가리킨 채 남는다.
 *   화면은 멀쩡해 보이고 — 강의 카드도 «재료 준비됨» 이라 한다 — 「전부
 *   만들기」를 누르는 순간에만 «script 자리를 찾지 못했습니다: D:\…옛폴더\…»
 *   가 떴다 (2026-09-04 실측). 사람이 원인을 알 길이 없는 자리다.
 *
 *   있는 값은 건드리지 않는다. 같은 강의 안에서 다른 파일을 가리키게 고쳐 둔
 *   것도, 강의 폴더 밖의 원본을 가리키는 것도 그대로 산다 — **없는 자리만**
 *   버린다. 서버가 답을 못 하면 아무것도 안 고친다(멀쩡한 값을 날리는 쪽이
 *   더 나쁘다).
 */
async function fixStalePaths() {
  const saved = {};
  for (const k of PATH_KEYS) {
    const v = (localStorage.getItem("sc." + k) || "").trim();
    if (v) saved[k] = v;
  }
  if (!Object.keys(saved).length) return;
  let gone = [];
  try {
    const r = await post("/api/path-exists", { paths: saved });
    gone = PATH_KEYS.filter((k) => saved[k] && (r.exists || {})[k] === false);
  } catch { return; }
  if (!gone.length) return;
  const L = LECS.find((x) => x.task === task()) || {};
  for (const k of gone) {
    const next = L[k] || ((STATE.sceneDefaults || {})[k] || "");
    localStorage.setItem("sc." + k, next);
    const el = $("#sc-" + k);
    if (el) el.value = next;
  }
  toast(`없어진 재료 자리 ${gone.length}개를 «${task()}» 강의 것으로 되돌렸습니다`);
}

function drawLectures() {
  const host = $("#lec-list");
  if (!host) return;
  $("#lec-count").textContent = LECS.length ? `${LECS.length}개` : "";
  host.innerHTML = "";
  const now = task();
  for (const L of LECS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "lec" + (L.task === now ? " on" : "");
    // 진행 현황 — 씬·목소리·자막·묶음·아바타·완성 여섯 칸
    const done = [
      L.scenes > 0, L.voice > 0, L.subs_done > 0,
      L.bundles > 0, L.avatar > 0, L.preview > 0,
    ];
    const dots = done.map((x) => `<i class="${x ? "on" : ""}"></i>`).join("");
    const sub = L.scenes
      ? `씬 ${L.scenes} · 목소리 ${L.voice} · 묶음 ${L.bundles} · 아바타 ${L.avatar}`
      : (L.ready ? `재료 준비됨 · 슬라이드 ${L.slide_count}장` : `<span class="lec-warn">재료가 모자랍니다</span>`);
    b.innerHTML = `<span class="lec-name">${L.task}</span>`
      + `<span class="lec-sub">${sub}</span>`
      + `<span class="lec-dots" title="씬·목소리·자막·묶음·아바타·완성">${dots}</span>`;
    b.onclick = () => pickLecture(L);
    host.appendChild(b);
  }
}

/* 강의를 고른다 — 작업 이름과 재료 네 자리를 그 강의로 갈아 끼운다.
 * ★ localStorage 에 남긴다. 창을 다시 열어도 아까 고른 강의로 돌아온다. */
function pickLecture(L) {
  TASK = L.task;
  localStorage.setItem("sc.task", TASK);
  for (const k of ["script", "subs", "slides", "source"]) {
    const el = $("#sc-" + k);
    if (!el) continue;
    el.value = L[k] || "";
    localStorage.setItem("sc." + k, el.value);
  }
  drawLectures();
  toast(`${L.task} 을 골랐습니다`);
  refresh().then(() => { loadBundles(); }).catch(() => {});
}

/* 탐색기로 그 자리를 연다. 경로를 글자로만 보여 주면 사람이 그걸 복사해
   붙여 넣는 일을 대신 한다 — 120강이면 그 품이 그대로 쌓인다. */
function openHere(path) {
  post("/api/open", { path })
    .then(() => toast("폴더를 열었습니다"))
    .catch((e) => toast(e.message, true));
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-open]");
  if (b) openHere(b.dataset.open);
});

/* ── 아바타 — 보낼 것 / 받은 것 ────────────────────────────────────────────
 * 이 단계만 «내 컴퓨터 밖» 을 다닌다. 그래서 화면도 두 방향으로 갈라 둔다.
 * 보내기 칸은 **꺼낼 mp3**, 받기 칸은 **되돌려 놓은 영상**만 말한다.
 */
function drawAvatar() {
  const send = $("#p4-send"), recv = $("#p4-recv");
  if (!send || !recv) return;
  const rows = BUNDLES.bundles || [];
  const drop = ($("#sc-avatar") || {}).value === "drop";
  for (const c of ["#p4-out-card", "#p4-in-card"]) {
    const el = $(c); if (el) el.hidden = !drop;
  }
  if (!drop) return;
  if (!rows.length) {
    const why = `<p class="sc-hint">«<b>${task()}</b>» 에 묶음이 없습니다 — `
      + `<b>05 묶음</b>에서 만들거나, <b>00 재료</b>에서 강의를 다시 고르세요.</p>`;
    send.innerHTML = recv.innerHTML = why;
    return;
  }

  send.innerHTML = "";
  recv.innerHTML = "";
  for (const b of rows) {
    send.appendChild(sendCard(b));
    recv.appendChild(recvCard(b));
  }
  hydrateIcons(send); hydrateIcons(recv);
}

/* 보내기 칸 — 꺼낼 mp3 가 무엇이고 폴더가 어디인지만 말한다.
   올릴 mp3 는 세 갈래다: 통째 하나 · 장면별 · 씬별. 갈래를 적어 줘야
   «어느 걸 올려야 하나» 를 파일 이름으로 추측하지 않는다. */
const mp3Kind = (rel) => rel.startsWith("장면/") ? "장면"
  : rel.startsWith("씬/") ? "씬" : "통째";

function bundleHead(b) {
  const nos = b.scenes || [];
  return `<div class="bundle-h"><b>묶음 ${b.no}</b>`
    + `<span class="bundle-sec">씬 ${nos[0]}~${nos[nos.length - 1]} · ${mmss(b.sec)}</span></div>`;
}

function sendCard(b) {
  const d = document.createElement("div");
  d.className = "bundle";
  d.dataset.bundle = (Number(b.no) % 2) ? "odd" : "even";
  const all = b.mp3s || [];
  const main = all.filter((m) => mp3Kind(m.rel) !== "씬");
  const nSc = all.length - main.length;
  d.innerHTML = bundleHead(b)
    + `<div class="file-list">` + main.map((m) =>
        `<div class="file"><i class="file-k">${mp3Kind(m.rel)}</i>`
        + `<span class="file-n">${m.rel}</span>`
        + `<span class="file-s">${mmss(m.sec)} · ${m.mb}MB</span></div>`).join("")
    + (nSc ? `<div class="file"><i class="file-k">씬</i>`
             + `<span class="file-n">씬별로 ${nSc}개</span>`
             + `<span class="file-s">씬마다 따로 뽑을 때</span></div>` : "")
    + `</div><div class="bundle-acts">`
    + `<button type="button" class="btn-plain" data-open="${b.path}">`
    + `<span data-icon="folder" data-icon-size="14"></span>`
    + `<span>폴더 열기</span></button></div>`;
  return d;
}

/* 받기 칸 — 끌어다 놓는 자리다.
 * ★ 탐색기로 옮기게 하지 않는다. 이 칸이 이미 «어느 묶음» 인지 알고 있으니
 *   사람이 폴더를 다시 찾아 들어갈 이유가 없다. 놓으면 그 묶음 폴더에
 *   앉고, 목록에 뜨고, 바로 아래 단추로 붙인다.
 * ★ 그래서 여기엔 «폴더 열기» 를 두지 않는다. 두면 위 보내기 칸과 **같은
 *   폴더**를 여는 단추가 화면에 둘이 되고, 받기 칸이 «끌어다 놓는 자리» 가
 *   아니라 «폴더로 옮기는 자리» 처럼 읽힌다. 꺼낼 것은 위에서, 되돌릴 것은
 *   여기서 — 방향이 하나씩이어야 한다.
 * ★ 묶음마다 단추를 따로 둔다. 다섯 묶음이 다 오길 기다리지 않고 온 것부터
 *   붙여 확인할 수 있어야 한다 — 하나가 잘못 왔을 때 나머지가 멈추면 안 된다.
 */
function recvCard(b) {
  const d = document.createElement("div");
  d.className = "bundle drop-zone";
  d.dataset.bundle = (Number(b.no) % 2) ? "odd" : "even";
  const nos = b.scenes || [];
  const vids = b.vids || [];
  const av = b.avatar_scenes || [];
  const left = nos.filter((n) => !av.includes(n));
  const bdir = b.dir || ("bundle" + String(b.no).padStart(2, "0"));
  const secs = vids.reduce((a, v) => a + (Number(v.sec) || 0), 0);
  // 길이 합이 남은 씬 길이와 맞는지 — p4 가 볼 조건을 미리 보여 준다
  const fit = vids.length
    ? Math.abs(secs - Number(b.sec)) <= Math.max(3, 0.02 * Number(b.sec))
    : false;

  d.innerHTML = bundleHead(b)
    + `<div class="file-list">` + vids.map((v) =>
        `<div class="file"><i class="file-k ok">영상</i>`
        + `<span class="file-n">${v.name}</span>`
        + `<span class="file-s">${mmss(v.sec)} · ${v.mb}MB</span>`
        + `<button type="button" class="file-x" data-del="${v.name}" `
        + `data-bundle-dir="${bdir}" title="이 영상을 지웁니다">×</button></div>`).join("")
    + `</div>`
    + `<label class="drop-say">`
    + `<input type="file" accept="video/*,.webm,.mov,.mkv" multiple hidden />`
    + `<span data-icon="film" data-icon-size="15"></span>`
    + `<span>받은 영상을 <b>여기에 끌어다 놓거나</b> 눌러서 고르세요</span></label>`
    + `<div class="drop-bar" hidden><i></i><span></span></div>`
    + `<div class="bundle-sub">` + (vids.length
        ? (fit ? `<b style="color:var(--ok)">길이 합 ${mmss(secs)} — 묶음과 맞습니다</b>`
               : `길이 합 <b>${mmss(secs)}</b> / 묶음 <b>${mmss(b.sec)}</b> — `
                 + `아직 모자랍니다`) + " · "
        : "")
      + (left.length
          ? (av.length ? `붙은 씬 <b>${av.join(",")}</b> · ` : "")
            + `남은 씬 <b>${left.join(",")}</b>`
          : `<b style="color:var(--ok)">씬 ${nos.join(",")} 전부 붙었습니다</b>`)
    + `</div>`
    + `<div class="bundle-acts">`
    + `<button type="button" class="btn-ink sm" data-attach="${b.no}" `
    + (vids.length ? "" : "disabled ") + `>`
    + `<span data-icon="play" data-icon-size="14"></span>`
    + `<span>이 묶음 붙이기</span></button></div>`;

  // ── 끌어다 놓기 ─────────────────────────────────────────────────────────
  const inp = d.querySelector('input[type="file"]');
  inp.onchange = () => sendFiles(b, [...inp.files]);
  for (const ev of ["dragenter", "dragover"]) {
    d.addEventListener(ev, (e) => { e.preventDefault(); d.classList.add("over"); });
  }
  for (const ev of ["dragleave", "drop"]) {
    d.addEventListener(ev, (e) => { e.preventDefault(); d.classList.remove("over"); });
  }
  d.addEventListener("drop", (e) => {
    const fs = [...(e.dataTransfer.files || [])];
    if (fs.length) sendFiles(b, fs);
  });
  return d;
}

/* 파일을 그 묶음 폴더로 올린다. 한 번에 여러 개도 된다 — 도입 하나와
   본문 하나를 같이 놓는 것이 이 강의의 기본 모양이다. */
async function sendFiles(b, files) {
  const bdir = b.dir || ("bundle" + String(b.no).padStart(2, "0"));
  const card = [...$$(".drop-zone")].find((x) =>
    x.querySelector(`[data-attach="${b.no}"]`));
  const bar = card && card.querySelector(".drop-bar");
  const fill = bar && bar.querySelector("i");
  const say = bar && bar.querySelector("span");
  if (bar) bar.hidden = false;

  let i = 0;
  for (const f of files) {
    i += 1;
    if (say) say.textContent = `${i}/${files.length} ${f.name} 올리는 중…`;
    try {
      await upload(b, bdir, f, (pct) => { if (fill) fill.style.width = pct + "%"; });
    } catch (e) {
      if (bar) bar.hidden = true;
      return toast(`${f.name} — ${e.message}`, true);
    }
  }
  if (bar) bar.hidden = true;
  toast(`${files.length}개를 묶음 ${b.no} 에 넣었습니다`);
  loadBundles();
}

/* XHR 을 쓴다 — fetch 는 올리는 진행률을 알려 주지 않는다. 100MB 짜리를
   올리는 동안 아무 표시가 없으면 사람은 멈춘 줄로 안다. */
function upload(b, bdir, file, onPct) {
  const url = `/api/bundle-drop?task=${encodeURIComponent(task())}`
    + `&bundle=${encodeURIComponent(bdir)}`
    + `&name=${encodeURIComponent(file.name)}`;
  return new Promise((ok, no) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.upload.onprogress = (e) => {
      if (e.lengthComputable) onPct(Math.round(e.loaded / e.total * 100));
    };
    x.onload = () => {
      let j = {};
      try { j = JSON.parse(x.responseText); } catch { /* 본문이 없을 수도 */ }
      if (x.status >= 200 && x.status < 300) ok(j);
      else no(new Error(j.error || `올리지 못했습니다 (${x.status})`));
    };
    x.onerror = () => no(new Error("연결이 끊겼습니다"));
    x.send(file);
  });
}

/* 묶음 하나만 붙인다 — 그 묶음의 씬 범위만 p4 에 넘긴다. */
document.addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]");
  if (del) {
    if (!confirm(`${del.dataset.del} 을 지웁니다. 계속할까요?`)) return;
    try {
      await post("/api/bundle-drop-del", { task: task(),
        bundle: del.dataset.bundleDir, name: del.dataset.del });
      toast("지웠습니다");
      loadBundles();
    } catch (err) { toast(err.message, true); }
    return;
  }
  const at = e.target.closest("[data-attach]");
  if (at) {
    const b = (BUNDLES.bundles || []).find((x) => String(x.no) === at.dataset.attach);
    if (!b) return;
    const nos = b.scenes || [];
    runScenes("p4", `${nos[0]}-${nos[nos.length - 1]}`, at);
  }
});

/* ── 묶음 ───────────────────────────────────────────────────── */

async function loadBundles() {
  try {
    BUNDLES = await api(`/api/bundles?task=${encodeURIComponent(task())}`);
  } catch {
    BUNDLES = { bundles: [], upload: "" };
  }
  drawBundles();
  drawAvatar();
  drawP5Pick();
}

/* ── 09 «어느 묶음을 굽나» ────────────────────────────────────────────────
 *
 * ★ **묶음이 고르는 단위다.** 묶음 하나가 업체에 한 번 올리는 단위이고 아바타도
 *   그 단위로 온다. 그러니 굽는 것도 그 단위다 — 씬 서른둘을 하나씩 고르게
 *   하면 «묶음 2 가 왔으니 그것만 구워 보자» 를 8,9,10… 으로 옮겨 적어야 한다.
 *
 * ★ 아바타가 하나도 안 온 묶음은 **못 고르게** 둔다. 골라도 p5 가 건너뛴다
 *   (목소리와 아바타가 둘 다 있는 씬만 굽는다). 고를 수 있게 두면 «골랐는데
 *   왜 안 나오지» 가 된다 — 화면이 할 수 없는 일을 할 수 있는 척하면 안 된다.
 *
 * ★ 아무것도 안 고른 상태는 «아바타 온 것 전부» 로 읽는다. 처음 들어와서
 *   바로 실행을 누르는 사람이 제일 많고, 그때 아무것도 안 구워지면 안 된다.
 */
let P5PICK = null;          // Set(묶음 번호). null 이면 «아바타 온 것 전부»

const pickable = () => (BUNDLES.bundles || []).filter((b) => (b.avatar_scenes || []).length);
const pickedNos = () => {
  const ok = pickable().map((b) => Number(b.no));
  return P5PICK === null ? ok : ok.filter((n) => P5PICK.has(n));
};

function drawP5Pick() {
  const host = $("#p5-pick");
  if (!host) return;
  const rows = BUNDLES.bundles || [];
  if (!rows.length) { host.innerHTML = ""; return; }
  const sel = new Set(pickedNos());
  const nAll = pickable().length;
  const pickedRows = rows.filter((b) => sel.has(Number(b.no)));
  const nSc = pickedRows.reduce((a, b) => a + (b.avatar_scenes || []).length, 0);
  const sec = pickedRows.reduce((a, b) => a + Number(b.sec || 0), 0);

  host.innerHTML =
    `<label class="pick-row pick-all">`
    + `<input type="checkbox" id="p5-all"${sel.size === nAll && nAll ? " checked" : ""}`
    + (nAll ? "" : " disabled") + `>`
    + `<b>전체</b><span class="pick-say">아바타가 온 묶음만 고를 수 있습니다</span></label>`
    + rows.map((b) => {
      const nos = b.scenes || [];
      const nAv = (b.avatar_scenes || []).length;
      const done = Number(b.preview || 0);
      return `<label class="pick-row${nAv ? "" : " off"}">`
        + `<input type="checkbox" data-pick="${b.no}"`
        + (sel.has(Number(b.no)) ? " checked" : "") + (nAv ? "" : " disabled") + `>`
        + `<b>묶음 ${b.no}</b>`
        + `<span class="pick-sc">씬 ${nos[0]}~${nos[nos.length - 1]}</span>`
        + `<span class="pick-sec">${mmss(b.sec)}</span>`
        + `<span class="pick-st">` + (nAv
            ? `아바타 <b>${nAv}/${nos.length}</b>`
              + (done ? ` · 구움 <b>${done}/${nos.length}</b>` : "")
            : `<i>아직 아바타가 없습니다</i>`) + `</span></label>`;
    }).join("")
    + `<div class="pick-sum">` + (nSc
        ? `고른 묶음 <b>${pickedRows.length}개</b> · 구울 씬 <b>${nSc}개</b>`
          + ` · 묶음 길이 합 ${mmss(sec)}`
        : `<b style="color:var(--err)">고른 묶음이 없습니다</b> — `
          + `07 아바타에서 받은 영상을 먼저 붙이세요`) + `</div>`;
}

document.addEventListener("change", (e) => {
  const all = e.target.closest("#p5-all");
  if (all) {
    P5PICK = all.checked ? null : new Set();
    drawP5Pick();
    return;
  }
  const one = e.target.closest("[data-pick]");
  if (one) {
    if (P5PICK === null) P5PICK = new Set(pickedNos());
    const n = Number(one.dataset.pick);
    if (one.checked) P5PICK.add(n); else P5PICK.delete(n);
    drawP5Pick();
  }
});

function drawBundles() {
  const host = $("#bundle-list");
  if (!host) return;
  const rows = BUNDLES.bundles || [];
  host.innerHTML = "";
  if (!rows.length) {
    const j = cur();
    host.innerHTML = `<p class="sc-hint">`
      + (!j
          ? `«<b>${task()}</b>» 는 아직 <b>01 씬</b>부터 돌려야 합니다 — `
            + `이 강의에는 씬이 없습니다.`
          : `아직 묶음이 없습니다 — 아래 <b>실행</b>을 누르세요.`)
      + `</p>`;
    return;
  }
  for (const b of rows) {
    const sec = Number(b.sec) || 0;
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    const n = (b.scenes || []).length;
    const got = Number(b.avatar) || 0;
    const state = got >= n
      ? `<b style="color:var(--ok)">아바타 받음</b>`
      : `아바타 <b>안 받음</b> — 올릴음성.mp3 을 업체에 넣으세요`;
    const dir = `${BUNDLES.upload}\${b.dir || ("bundle" + String(b.no).padStart(2, "0"))}`;
    const d = document.createElement("div");
    d.className = "bundle";
    d.dataset.bundle = (Number(b.no) % 2) ? "odd" : "even";   // 씬 카드와 같은 색
    d.innerHTML =
      `<div class="bundle-h"><b>${b.dir || ("bundle" + String(b.no).padStart(2, "0"))}</b>`
      + `<span class="bundle-sec">${m}:${String(s).padStart(2, "0")}</span></div>`
      + `<div class="bundle-sub">씬 ${b.scenes[0]}~${b.scenes[b.scenes.length - 1]} `
      + `(${n}개) · ${state}</div>`
      + `<div class="bundle-t">${(b.titles || []).slice(0, 3).map((t) =>
            `<span>${(t || "").slice(0, 30)}</span>`).join("")}</div>`
      + `<div class="bundle-acts">`
      + `<button type="button" class="btn-plain" data-open="${dir}">`
      + `<span data-icon="folder" data-icon-size="14"></span>`
      + `<span>폴더 열기 — 올릴음성.mp3</span></button>`
      + `<span class="bundle-hint">여기서 mp3 를 꺼내 HeyGen 에 올리고, `
      + `<b>받은 영상을 이 폴더에 되돌려</b> 놓으세요</span></div>`;
    host.appendChild(d);
  }
  hydrateIcons(host);
  // ★ 빈 경우에도 **반드시 다시 쓴다.** 예전에는 upload 가 비면 건드리지
  //   않아, 아까 본 다른 강의의 경로가 그대로 남았다 — 「샘플」을 보면서
  //   「강의」 가 떠 있던 원인이다.
  const el = $("#bundle-where");
  if (el) {
    el.innerHTML = BUNDLES.upload
      ? `묶음 폴더는 <code>${BUNDLES.upload}</code> 에 있습니다. `
        + `폴더마다 <b>올릴음성.mp3</b> 을 꺼내 업체에 드래그드랍하고, `
        + `렌더된 영상을 <b>그 폴더에 되돌려</b> 놓으세요.`
      : `«<b>${task()}</b>» 에는 아직 묶음 폴더가 없습니다.`;
  }
}

/* ── 배선 ───────────────────────────────────────────────────── */

if ($("#btn-p3b")) $("#btn-p3b").onclick = () => run("p3b", "#btn-p3b");
if ($("#sc-bpack")) $("#sc-bpack").onchange = drawNotes;

loadLectures();
loadBundles();

/* ── 시작 ──────────────────────────────────────────────────── */
window.addEventListener("hashchange", route);
hydrateIcons(document);
renderSteps();
refresh().then(route).catch((e) => toast(e.message, true));
loadConn();
loadHeygen();
loadLangs();
