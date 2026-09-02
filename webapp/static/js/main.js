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
 * run    : 이 단계가 돌리는 파이프라인 조각 (없으면 실행 없는 화면)
 * costs  : perso 를 실제로 부르는 단계 — $ 가 붙는다
 * rule   : 이 앞에 「넘기는 것」 구분선을 긋는다
 */
const STEPS = [
  { page: "p0",   name: "재료" },
  { page: "p1",   name: "씬",     run: "p1" },
  { page: "p2",   name: "목소리", run: "p2", costs: true },
  { page: "p2b",  name: "다국어 자막", run: "p2b" },
  { page: "p3",   name: "자막",   run: "p3" },
  { page: "p4",   name: "아바타", run: "p4", costs: true },
  { page: "p5",   name: "빌드",   run: "p5" },
  { page: "done", name: "결과",   rule: true },
];
const TASK = "lecture01";

let STATE = { scenes: [], sceneDefaults: null, cfg: null };
let PERSO = null, CONN = null;
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
const task = () => (STATE.scenes[0] && STATE.scenes[0].task) || TASK;

/* ── 좌측 순서 ──────────────────────────────────────────────
 * 상태 점은 scenes.json 이 채워진 정도로 정한다 — 파일이 사실이고 화면은
 * 그걸 비출 뿐이다. done(다 됨) · part(일부) · 없음(회색).
 */
function stepState(page) {
  const j = STATE.scenes[0];
  if (!j || !j.scenes.length) return page === "p0" ? "done" : "";
  const n = j.scenes.length;
  const got = {
    p0: n,
    p1: j.scenes.filter((s) => s.slide).length,
    p2: j.scenes.filter((s) => s.voice).length,
    p2b: j.scenes.filter((s) => s.cues > 0).length,
    p3: j.scenes.filter((s) => s.voice && s.cues > 0).length,
    p4: j.scenes.filter((s) => s.avatar).length,
    p5: j.scenes.filter((s) => s.preview).length,
    done: j.all ? n : 0,
  }[page] || 0;
  return got >= n ? "done" : got > 0 ? "part" : "";
}

function renderSteps() {
  const cur = (location.hash || "#/p0").replace("#/", "");
  $("#steps").innerHTML = STEPS.map((st, i) => `
    ${st.rule ? '<div class="step-rule"><span>넘기는 것</span></div>' : ""}
    <button class="step ${cur === st.page ? "on" : ""}" data-page="${st.page}">
      <span class="step-no">${i + 1}</span>
      <span class="step-name">${st.name}</span>
      ${st.costs ? '<span class="cost" title="perso 를 부르는 단계입니다">$</span>' : ""}
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
  if (to === "p4") drawScenes("#p4-out", "p4");
  if (to === "p5") drawScenes("#p5-out", "p5");
  if (to === "done") drawDone();
  drawNotes();
}

/* ── 상태 읽어 오기 ────────────────────────────────────────── */
async function refresh() {
  STATE = await api("/api/state");
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
  if (rg) $("#sc-range").value = rg;
  $("#sc-range").onchange = () => localStorage.setItem("sc.range", $("#sc-range").value.trim());
}
const styleOf = () => ($('input[name="style"]:checked') || {}).value || "panel";
const STYLE_NAME = { full: "전면샷", panel: "여백형" };
$$('input[name="style"]').forEach((r) => {
  r.onchange = () => { localStorage.setItem("sc.style", styleOf()); drawNotes(); };
});

/* 지금 화면이 서버로 보낼 값 한 벌 — 모든 단계가 같은 것을 보낸다.
   단계마다 다른 몸통을 만들면 「전부 만들기」와 「이 단계만」이 갈린다. */
function payload(step) {
  const b = { task: task(), step: step || "",
              scenes: $("#sc-range").value.trim() || "1-8",
              style: styleOf(),
              voice_engine: $("#sc-voice").value,
              avatar_engine: $("#sc-avatar").value,
              avatar_h: $("#sc-avh").value.trim(),
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
  const j = STATE.scenes[0];
  const n = j ? j.scenes.length : 0;
  const set = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };

  set("#p1-note", j && n
    ? `씬 <b>${n}개</b> · 합계 <b>${mmss(j.total)}</b> · 자막 ${j.scenes.reduce((a, s) => a + s.cues, 0)}개`
    : "아직 안 떼었습니다. 1 재료를 채우고 누르세요.");

  const v = $("#sc-voice").value;
  set("#p2-say", v === "source"
    ? "시연본 mp4 에서 씬 구간의 소리를 그대로 떼어 옵니다 — <b>진짜 우즈베크어이고 크레딧은 0</b>입니다."
    : v === "silent" ? "무음을 만듭니다. 배치만 볼 때 씁니다. <b>크레딧 0</b>."
    : `<b style="color:var(--err)">perso TTS 를 부릅니다 — 크레딧을 씁니다.</b>`
      + (PERSO && PERSO.ok ? "" : ` ${PERSO ? PERSO.why : ""}`));
  set("#p2-note", j ? `목소리 있는 씬 <b>${j.scenes.filter((s) => s.voice).length}/${n}</b>` : "");

  const withSubs = j ? j.scenes.filter((s) => s.cues > 0).length : 0;
  const names = picked.map((x) => (langByTag(x) || {}).name || x).join(" · ");
  set("#p2b-say", picked.length
    ? `<b>${names}</b> 로 옮깁니다. 맨 앞 «${(langByTag(picked[0]) || {}).name || picked[0]}» 가 `
      + "영상에 구워지고 나머지는 트랙으로 얹힙니다. "
      + "<b>Claude 로그인을 쓰므로 perso 크레딧도 API 키도 안 듭니다.</b>"
    : "언어를 하나 이상 고르세요.");
  set("#p2b-note", j
    ? (withSubs >= n && n
        ? `자막이 <b>${n}씬 모두</b> 있습니다 — 다시 만들려면 아래를 켜세요.`
        : `자막 있는 씬 <b>${withSubs}/${n}</b> — 대본에서 옮겨 채웁니다.`)
    : "");
  set("#p3-note", j
    ? `자막은 <b>목소리 길이에 맞춰</b> 시각이 다시 매겨집니다. 문구를 고치면 저장만 하면 됩니다.`
    : "");

  const av = $("#sc-avatar").value;
  set("#p4-say", av === "stub"
    ? "사람 모양 <b>임시 아바타</b>를 넣습니다 — 배경이 투명해서 진짜 아바타가 오면 같은 자리에 그대로 들어갑니다. <b>크레딧 0</b>."
    : `<b style="color:var(--err)">perso 아바타를 부릅니다 — 크레딧을 씁니다.</b>`
      + (PERSO && PERSO.ok ? "" : ` ${PERSO ? PERSO.why : ""}`));
  set("#p4-note", j ? `아바타 있는 씬 <b>${j.scenes.filter((s) => s.avatar).length}/${n}</b>` : "");

  const sm = $("#sc-submode").value;
  $("#p5-style").value = STYLE_NAME[styleOf()];
  set("#p5-say", (styleOf() === "panel"
      ? "슬라이드는 왼쪽 칸, 발표자는 오른쪽 칸. <b>슬라이드 아래가 자막 선에 붙습니다.</b>"
      : "슬라이드가 화면을 꽉 채우고 발표자가 그 위에 섭니다.")
    + " " + (sm === "burn" ? "자막은 <b>픽셀에 구워</b> 어디서나 보입니다."
      : sm === "soft" ? "자막은 <b>끌 수 있는 트랙</b>입니다 — 플레이어가 안 켜면 안 보입니다."
      : "자막은 영상에 안 넣고 <b>srt 로만</b> 넘깁니다."));
  set("#p5-note", j ? `구운 씬 <b>${j.scenes.filter((s) => s.preview).length}/${n}</b>` : "");
}
for (const id of ["#sc-voice", "#sc-avatar", "#sc-submode", "#sc-fit"])
  $(id).onchange = drawNotes;


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
  const saved = localStorage.getItem("sc.sublangs");
  picked = saved ? saved.split(",").filter(Boolean)
                 : [(STATE.scenes[0] || {}).sub_lang || "ru"];
  drawLangs();
}

const langByTag = (tag) => LANGS.langs.find((l) => l.tag === tag);

function drawLangs() {
  localStorage.setItem("sc.sublangs", picked.join(","));
  const j = STATE.scenes[0];

  // 고른 것 — 맨 앞이 기본 자막이다. 줄 수를 같이 보여 준다.
  const host = $("#lang-picked");
  if (host) {
    host.innerHTML = picked.length
      ? picked.map((tag, i) => {
          const l = langByTag(tag);
          const n = j && tag === j.sub_lang
            ? j.scenes.reduce((a, s) => a + s.cues, 0) : 0;
          return `<span class="lang-chip on" data-drop="${tag}">` +
            `<b>${l ? l.native : tag}</b> ${l ? l.name : ""}` +
            (i === 0 ? '<i class="lang-first">기본</i>' : "") +
            (n ? `<i class="lang-n">${n}줄</i>` : "") +
            `<i class="lang-x">×</i></span>`;
        }).join("")
      : '<span class="job-empty">아직 안 골랐습니다.</span>';
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
        `<div class="lang-row">` + ls.map((l) =>
          `<button type="button" class="lang-chip${picked.includes(l.tag) ? " on" : ""}" ` +
          `data-add="${l.tag}" title="${l.name} · 꼬리표 ${l.tag} · ${l.cps}자/초">` +
          `<b>${l.native}</b> ${l.name} <i class="lang-tag">${l.tag}</i></button>`).join("") +
        `</div></div>`;
    }).join("");
  }
}

document.addEventListener("click", (e) => {
  const add = e.target.closest("[data-add]");
  if (add) {
    const tag = add.dataset.add;
    picked = picked.includes(tag) ? picked.filter((x) => x !== tag) : [...picked, tag];
    drawLangs(); drawNotes(); return;
  }
  const drop = e.target.closest("[data-drop]");
  if (drop) {
    picked = picked.filter((x) => x !== drop.dataset.drop);
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
function drawProgress(cur, failed, running, steps) {
  const host = $("#dock-now");
  if (!host) return;
  const now = (steps || []).find((s) => s.key === cur);
  host.textContent = !running && cur === "done" ? "끝났습니다"
    : failed ? "멈췄습니다" : now ? now.label : "";
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
  drawProgress(s.step, s.failed, s.running, s.steps);
  if (!s.running) {
    clearInterval(poll); poll = null;
    $$(".btn-ink").forEach((b) => { b.disabled = false; });
    await refresh();
    if ((location.hash || "") === "#/p3") loadSubs();
    toast(s.failed ? "멈췄습니다 — 아래 기록을 보세요" : "끝났습니다", s.failed);
  }
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
$("#btn-p5").onclick = () => run("p5", "#btn-p5");

/* ── 씬 목록 ───────────────────────────────────────────────
 * 단계마다 같은 목록을 쓰되 **그 단계가 만든 것만** 굵게 보여 준다.
 * 목록을 단계마다 새로 짜면 씬 번호와 제목이 화면마다 달라 보인다.
 */
function drawScenes(hostSel, forStep) {
  const host = $(hostSel);
  if (!host) return;
  const j = STATE.scenes[0];
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
    const dots = [["슬라이드", s.slide], ["목소리", s.voice],
                  ["아바타", s.avatar], ["검수본", !!s.preview]]
      .map(([lab, on]) => `<i class="${on ? "on" : ""}" title="${lab}"></i>`).join("");
    c.innerHTML =
      `<div class="sc-h"><span class="sc-no">${String(s.no).padStart(2, "0")}</span>` +
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
  const j = STATE.scenes[0];
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

  if (j.all) {
    const whole = document.createElement("div");
    whole.className = "sc-whole";
    whole.innerHTML = `<div class="sc-cap">이어 붙인 한 편 — ${mmss(j.total)}</div>` +
      `<video controls preload="metadata" src="/api/scene-media?task=` +
      `${encodeURIComponent(j.task)}&rel=preview/${encodeURIComponent(j.all)}"></video>`;
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
  drawScenes("#sc-out", "p5");
  host.insertBefore(box, host.firstChild);
}

/* ── 4 자막 ────────────────────────────────────────────────── */
const subLang = () => {
  const m = /scene\d+\.([a-z]{2})\.srt/.exec($("#sub-scene").value || "");
  return m ? m[1] : (STATE.scenes[0] || {}).sub_lang || "ru";
};

async function loadSubs(file) {
  let d;
  try {
    d = await api(`/api/scene-subs?task=${encodeURIComponent(task())}` +
                  (file ? `&file=${encodeURIComponent(file)}` : ""));
  } catch { $("#cue-list").innerHTML =
      '<li class="job-empty">아직 자막이 없습니다 — 3 목소리를 먼저 만드세요.</li>'; return; }
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
    const dots = STEPS.filter((s) => s.run || s.page === "done")
      .map((s) => `<i class="${stepState(s.page) === "done" ? "on" : ""}" title="${s.name}"></i>`)
      .join("");
    li.innerHTML = `<button type="button"><span class="job-name">${j.task}</span>` +
      `<span class="job-meta">${mmss(j.total)} · 씬 ${j.scenes.length}개</span>` +
      `<span class="dots">${dots}</span></button>`;
    ul.appendChild(li);
  }
}
$("#job-filter").oninput = drawJobs;

/* ── perso 연결 ────────────────────────────────────────────
 * 키는 서버 파일(perso.local.json)에만 들어간다. 저장한 뒤 입력란을 비우는 것은
 * 화면을 녹화해 공유하는 일이 잦기 때문이다 — 상태는 문장으로만 말한다.
 */
async function loadPerso() {
  try { PERSO = await api("/api/perso"); } catch { PERSO = null; }
  if (PERSO && PERSO.voice_uz) $("#sc-voice-id").value = PERSO.voice_uz;
  if (PERSO && PERSO.avatar_id) $("#sc-avatar-id").value = PERSO.avatar_id;
  drawPersoWhy();
  drawNotes();
}

function drawPersoWhy() {
  const el = $("#sc-perso-why");
  const dot = $("#perso-dot");
  dot.className = "conn-dot" + (!PERSO ? "" : PERSO.ok ? " ok" : PERSO.key ? " warn" : " bad");
  $("#perso-t1").textContent = !PERSO ? "확인 중…" : PERSO.ok ? "perso 연결됨" : "perso 연결 안 됨";
  $("#perso-t2").textContent = !PERSO ? "" : PERSO.ok ? (PERSO.voice_uz || "") : "키를 넣으세요";
  if (!el) return;
  if (!PERSO) { el.textContent = "perso 상태를 읽지 못했습니다."; return; }
  const eps = PERSO.endpoints || {};
  const bits = [PERSO.key ? "키 <b>있음</b>" : "키 <b>없음</b>",
                "엔드포인트 " + (eps.tts && eps.avatar ? "<b>채워짐</b>" : "<b>비어 있음</b>")];
  if (PERSO.voice_uz) bits.push("보이스 <b>" + PERSO.voice_uz + "</b>");
  if (PERSO.avatar_id) bits.push("아바타 <b>" + PERSO.avatar_id + "</b>");
  el.innerHTML = bits.join(" · ") + " — " + PERSO.why;
  el.className = "sc-hint" + (PERSO.ok ? " ok" : "");
}
$("#perso-btn").onclick = () => { location.hash = "#/p0"; };

$("#btn-key").onclick = async () => {
  const key = $("#sc-key").value.trim();
  const voice = $("#sc-voice-id").value.trim();
  const av = $("#sc-avatar-id").value.trim();
  if (!key && !voice && !av) return toast("넣을 값이 없습니다", true);
  try {
    const r = await post("/api/perso-key",
                         { api_key: key, voice_uz: voice, avatar_id: av });
    PERSO = r.status;
    $("#sc-key").value = "";
    drawPersoWhy();
    drawNotes();
    toast("저장했습니다 — " + PERSO.why);
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

/* ── 시작 ──────────────────────────────────────────────────── */
window.addEventListener("hashchange", route);
hydrateIcons(document);
renderSteps();
refresh().then(route).catch((e) => toast(e.message, true));
loadConn();
loadPerso();
loadLangs();
