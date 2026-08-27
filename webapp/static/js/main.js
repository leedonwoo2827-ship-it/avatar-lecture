/* mp42perso 화면 — 네 화면(돌리기 · 자막 · 컷 · 결과)을 한 파일에 둔다.
 *
 * 화면이 넷뿐이라 라우터를 따로 두지 않는다. 해시가 바뀌면 section 하나를
 * 보이고 나머지를 숨긴다 — 그래서 진행 중인 로그가 화면을 옮겨도 살아 있다
 * (언마운트하지 않는다).
 */
"use strict";
import { hydrateIcons } from "/static/js/icons.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* 자막 한 줄 최대 글자수 — scripts/common.py 의 CUE_MAX_CHARS 와 같은 값이어야
   한다. 여기서 다르면 화면은 통과라고 하는데 check.py 는 실패라고 한다. */
const CUE_MAX = { ru: 42, uz: 46, en: 46, ko: 30 };
const CHUNK_MAX = 28 * 60;   // scripts/common.py CHUNK_MAX_SEC
const PERSO_MAX = 30 * 60;   // scripts/common.py PERSO_LIMIT_SEC

let STATE = { bundles: [], jobs: [], steps: [], cfg: null };
let picked = null;      // 고른 번들 경로
let curWs = null;       // 자막·컷 화면이 보고 있는 워크스페이스
let cues = [];          // 자막 화면의 현재 큐
let cutRows = [];       // 컷 화면의 현재 조각

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

/* ── 화면 갈아타기 ─────────────────────────────────────────── */
function route() {
  const to = (location.hash || "#/run").replace("#/", "");
  $$(".page").forEach((p) => { p.hidden = p.dataset.page !== to; });
  $$(".side-nav a").forEach((a) => {
    if (a.getAttribute("href") === `#/${to}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  if (to === "subs") loadSubs();
  if (to === "cuts") loadCuts();
  if (to === "out") drawOut();
}

/* ── 상태 읽어 오기 ────────────────────────────────────────── */
async function refresh() {
  STATE = await api("/api/state");
  applyCfg();
  drawBundles();
  drawJobs();
  fillWsSelects();
  if (!$('.page[data-page="out"]').hidden) drawOut();
}

/* ── 강의 고르기 ────────────────────────────────────────────
 * 강의 백 개대가 기본 규모다. 그래서 두 모드를 둔다.
 *   카드     3열 — 강의가 몇 개일 때
 *   촘촘히   12열 타일 — 백 개대를 한 화면에 넣을 때
 * 촘촘히에서 타일 라벨은 폴더 이름 앞의 `NNN강` 만 남긴다. 이름을 다 넣으면
 * 10열이 안 된다. 전체 이름은 title 로 뜬다.
 */
/* 타일 라벨은 **번호만**이다. 폴더 이름이 `121강` 이든 `121샘플` 이든 앞의 숫자가
   곧 그 강의다. 12열에서 타일 폭이 72px 뿐이라 뒤에 뭐라도 붙으면 잘려서
   번호를 못 읽는다 — 전체 이름은 제목 옆 내역과 title 로 본다. */
const tileLabel = (name) => {
  const m = /^(\d+)/.exec(name);
  return m ? m[1] : name;
};

function bundleDetail(b) {
  if (!b) return "";
  const bits = [];
  if (b.video) bits.push(`영상 <b>${b.video}</b>`);
  bits.push(b.slides ? `슬라이드 <b>${b.slides}장</b>` : "슬라이드 없음");
  if (b.subs.length) bits.push(`자막 원문 ${b.subs.length}개`);
  if (b.problems.length) bits.push(`<span class="bad">${b.problems[0]}</span>`);
  return `<b>${b.name}</b> — ${bits.join(" · ")}`;
}
const showDetail = (b) => { $("#pick-detail").innerHTML = bundleDetail(b); };

/* 기본 언어는 서버(config.local.json)가 정한다. 한 번만 맞추고, 그 뒤에는
   사람이 고른 값을 건드리지 않는다. */
let cfgDone = false;
function applyCfg() {
  if (cfgDone || !STATE.cfg) return;
  cfgDone = true;
  const set = (sel, v) => {
    const el = $(sel);
    if (v && [...el.options].some((o) => o.value === v)) el.value = v;
  };
  set("#opt-lang", STATE.cfg.audio_lang);
  set("#opt-sub", STATE.cfg.sub_lang);
  drawSay();
}

function drawBundles() {
  const ul = $("#bundle-list");
  const dense = $("#pv-dense").getAttribute("aria-pressed") === "true";
  ul.className = "pick-list" + (dense ? " dense" : "");
  ul.innerHTML = "";
  if (!STATE.bundles.length) {
    ul.innerHTML = '<li class="job-empty">재료\ 안에 폴더가 없습니다.</li>';
    return;
  }
  for (const b of STATE.bundles) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.title = b.name;
    btn.setAttribute("aria-pressed", String(picked === b.path));
    // ★ 타일에는 이름만 넣는다. 121개를 훑는 화면이라 타일마다 설명이 붙으면
    //   눈이 못 따라간다. 상태는 점 하나로, 내역은 제목 옆 한 자리로 보낸다.
    const dotCls = b.problems.length ? "bad" : (b.slides ? "" : "no-slides");
    btn.innerHTML =
      `<span class="pick-name">${tileLabel(b.name)}</span>` +
      `<span class="tile-dot ${dotCls}"></span>`;
    btn.disabled = b.problems.length > 0;
    // 짚기만 해도 내역이 제목 옆에 뜬다 — 툴팁을 기다리지 않아도 훑을 수 있다
    btn.onmouseenter = () => showDetail(b);
    btn.onfocus = () => showDetail(b);
    btn.onclick = () => {
      picked = b.path;
      $("#run-note").textContent = `${b.name} — 돌릴 준비가 됐습니다.`;
      $("#btn-run").disabled = false;
      showDetail(b);
      drawBundles();
    };
    li.appendChild(btn);
    ul.appendChild(li);
  }
  // 아무것도 안 짚었으면 고른 것을, 그것도 없으면 쓸 수 있는 첫 개를 보여 준다
  const cur = STATE.bundles.find((b) => b.path === picked)
           || STATE.bundles.find((b) => !b.problems.length);
  if (!$("#pick-detail").innerHTML) showDetail(cur);
}

$("#bundle-list").addEventListener("mouseleave", () => {
  const cur = STATE.bundles.find((b) => b.path === picked);
  showDetail(cur || STATE.bundles.find((b) => !b.problems.length));
});
for (const [id, dense] of [["#pv-card", false], ["#pv-dense", true]]) {
  $(id).onclick = () => {
    $("#pv-card").setAttribute("aria-pressed", String(!dense));
    $("#pv-dense").setAttribute("aria-pressed", String(dense));
    localStorage.setItem("pickDense", dense ? "1" : "");
    drawBundles();
  };
}

/* ── 오른쪽 서랍 — 폴더마다 진행 현황 ──────────────────────── */
function drawJobs() {
  const ul = $("#job-list");
  const q = ($("#job-filter").value || "").trim().toLowerCase();
  const rows = q ? STATE.jobs.filter((j) => j.name.toLowerCase().includes(q)) : STATE.jobs;
  $("#drawer-count").textContent = String(STATE.jobs.length);
  ul.innerHTML = "";
  if (!rows.length) {
    ul.innerHTML = `<li class="job-empty">${q ? "찾는 것이 없습니다" : "아직 없습니다"}</li>`;
    return;
  }
  for (const j of rows) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.title = j.name;
    btn.setAttribute("aria-current", String(curWs === j.name));
    // 막대에 단계 이름을 달아 둔다 — 설명문을 화면에 두지 않아도 뜻을 잃지 않는다
    // 막대는 폴더만 보고 판단할 수 있는 단계들(s1~s7). s3b 는 자막 언어를
    // 알아야 판단이 되므로 여기서 빼 둔다.
    const ds = STATE.dotSteps || STATE.steps;
    const dots = ds
      .map((st) => `<i class="${j.steps[st.key] ? "on" : ""}" ` +
                   `title="${st.key} ${st.label}"></i>`).join("");
    const done = ds.filter((st) => j.steps[st.key]).length;
    const meta = j.duration
      ? `${mmss(j.duration)} · 조각 ${j.chunks.length}개 · ${done}/${ds.length}단계`
      : "돌리는 중";
    btn.innerHTML = `<span class="job-name">${j.name}</span>` +
      `<span class="job-meta">${meta}</span><span class="dots">${dots}</span>`;
    btn.onclick = () => {
      curWs = j.name;
      location.hash = "#/out";
      fillWsSelects();
      drawJobs();
    };
    li.appendChild(btn);
    ul.appendChild(li);
  }
}
$("#job-filter").oninput = drawJobs;

/* ── 돌리기 ────────────────────────────────────────────────── */
let logSeen = 0, poll = null;

function drawSteps(cur, failed, running) {
  const ol = $("#steps");
  ol.innerHTML = "";
  let past = true;
  for (const [i, s] of STATE.steps.entries()) {
    const li = document.createElement("li");
    let cls = "";
    if (s.key === cur) { cls = failed ? "fail" : "now"; past = false; }
    else if (past) cls = "done";
    li.className = cls;
    li.innerHTML = `<span class="n">${i + 1}</span><span>${s.label}</span>`;
    ol.appendChild(li);
  }
  if (!running && !failed && cur === "done") {
    $$("#steps li").forEach((li) => { li.className = "done"; });
  }
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
  drawSteps(s.step, s.failed, s.running);
  if (!s.running) {
    clearInterval(poll); poll = null;
    $("#btn-run").disabled = false;
    $("#run-note").textContent = s.failed
      ? "멈췄습니다 — 아래 기록을 보세요."
      : "끝났습니다. 왼쪽 '결과'에서 확인하세요.";
    if (s.ws) curWs = s.ws;
    await refresh();
    toast(s.failed ? "멈췄습니다" : "끝났습니다", s.failed);
  }
}

$("#btn-run").onclick = async () => {
  if (!picked) return;
  $("#btn-run").disabled = true;
  $("#prog-card").hidden = false;
  showDock(true);
  $("#log").textContent = "";
  logSeen = 0;
  $("#run-note").textContent = "돌고 있습니다. 전사가 가장 오래 걸립니다.";
  try {
    await post("/api/run", {
      bundle: picked, lang: $("#opt-lang").value,
      sub_lang: $("#opt-sub").value, model: $("#opt-model").value,
    });
  } catch (e) {
    $("#btn-run").disabled = false;
    return toast(e.message, true);
  }
  if (poll) clearInterval(poll);
  poll = setInterval(tick, 1000);
  tick();
};

/* ── 워크스페이스 고르는 select 채우기 ─────────────────────── */
function fillWsSelects() {
  for (const id of ["#sub-ws", "#cut-ws"]) {
    const sel = $(id);
    const keep = sel.value;
    sel.innerHTML = "";
    for (const j of STATE.jobs) {
      const o = document.createElement("option");
      o.value = j.name; o.textContent = j.name;
      sel.appendChild(o);
    }
    if (keep && STATE.jobs.some((j) => j.name === keep)) sel.value = keep;
    else if (curWs) sel.value = curWs;
  }
}

/* ── 자막 다듬기 ───────────────────────────────────────────── */
function subLang() {
  const m = /subs\.([a-z]{2})\.srt/.exec($("#sub-file").value || "");
  return m ? m[1] : "ru";
}

async function loadSubs(file) {
  const ws = $("#sub-ws").value;
  if (!ws) { $("#cue-list").innerHTML = ""; return; }
  let d;
  try {
    d = await api(`/api/subs?ws=${encodeURIComponent(ws)}` +
                  (file ? `&file=${encodeURIComponent(file)}` : ""));
  } catch (e) { return toast(e.message, true); }
  const sel = $("#sub-file");
  sel.innerHTML = "";
  for (const f of d.files) {
    const o = document.createElement("option");
    o.value = f; o.textContent = f;
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
    const n = c.text.length;
    if (n > max) li.classList.add("over");
    li.innerHTML = `<span class="cue-i">${c.i}</span>` +
      `<span class="cue-t">${mmss(c.start)}</span>`;
    const inp = document.createElement("input");
    const cnt = document.createElement("span");
    inp.type = "text"; inp.value = c.text;
    cnt.className = "cue-n"; cnt.textContent = String(n);
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

$("#sub-ws").onchange = () => loadSubs();
$("#sub-file").onchange = () => loadSubs($("#sub-file").value);
$("#btn-sub-save").onclick = async () => {
  try {
    const r = await post("/api/subs", {
      ws: $("#sub-ws").value, file: $("#sub-file").value, cues,
    });
    toast(`저장했습니다 — ${r.saved}개. s4부터 다시 돌리면 반영됩니다.`);
  } catch (e) { toast(e.message, true); }
};

/* ── 컷 옮기기 ─────────────────────────────────────────────── */
function loadCuts() {
  const ws = $("#cut-ws").value;
  const j = STATE.jobs.find((x) => x.name === ws);
  cutRows = j ? j.chunks.map((c) => ({ ...c })) : [];
  drawCuts();
}

function drawCuts() {
  const host = $("#cut-list");
  host.innerHTML = "";
  if (!cutRows.length) {
    host.innerHTML = '<p class="job-empty">조각이 없습니다 — s4를 먼저 돌리세요.</p>';
    return;
  }
  for (const c of cutRows) {
    const row = document.createElement("div");
    row.className = "cut-row";
    const len = c.end - c.start;
    row.innerHTML = `<div class="cut-name">chunk${String(c.no).padStart(2, "0")}</div>`;
    const f = document.createElement("div");
    f.className = "cut-fields";
    const mk = (label, key) => {
      const l = document.createElement("label");
      l.textContent = label;
      const i = document.createElement("input");
      i.type = "text"; i.value = c[key].toFixed(2);
      i.onchange = () => {
        const v = parseFloat(i.value);
        if (!Number.isNaN(v)) { c[key] = v; drawCuts(); }
      };
      l.appendChild(i);
      return l;
    };
    f.append(mk("시작(초)", "start"), mk("끝(초)", "end"));
    const badge = document.createElement("span");
    badge.className = "cut-len" + (len > CHUNK_MAX ? " over" : "");
    badge.textContent = mmss(len) +
      (len > PERSO_MAX ? "  perso 한계 초과!" : len > CHUNK_MAX ? "  마진 없음" : "");
    f.appendChild(badge);
    row.appendChild(f);
    const bar = document.createElement("div");
    bar.className = "cut-bar";
    const fill = document.createElement("i");
    fill.style.width = Math.min(100, (len / PERSO_MAX) * 100).toFixed(1) + "%";
    if (len > CHUNK_MAX) fill.className = "over";
    bar.appendChild(fill);
    row.appendChild(bar);
    host.appendChild(row);
  }
}

$("#cut-ws").onchange = loadCuts;
$("#btn-cut-save").onclick = async () => {
  try {
    const r = await post("/api/chunks", { ws: $("#cut-ws").value, chunks: cutRows });
    toast(`저장했습니다 — ${r.saved}조각. s6부터 다시 돌리면 반영됩니다.`);
    await refresh();
  } catch (e) { toast(e.message, true); }
};

/* ── 결과 ──────────────────────────────────────────────────── */
function drawOut() {
  const host = $("#out-list");
  host.innerHTML = "";
  if (!STATE.jobs.length) {
    host.innerHTML = '<p class="job-empty">아직 돌린 것이 없습니다.</p>';
    return;
  }
  for (const j of STATE.jobs) {
    const box = document.createElement("div");
    box.className = "out-job";
    box.innerHTML = `<div class="out-head"><h2>${j.name}</h2>` +
      `<span>${j.source || ""} · ${mmss(j.duration)} · 슬라이드 ${j.slides}장</span></div>`;
    const grid = document.createElement("div");
    grid.className = "chunk-grid";
    if (!j.chunks.length) {
      grid.innerHTML = '<p class="job-empty">조각이 아직 없습니다.</p>';
    }
    for (const c of j.chunks) {
      const r = document.createElement("div");
      r.className = "chunk-row";
      const len = c.end - c.start;
      r.innerHTML =
        `<span class="chunk-no">chunk${String(c.no).padStart(2, "0")}</span>` +
        `<span class="chunk-len">${mmss(len)}</span>` +
        `<span class="chunk-note">${mmss(c.start)} ~ ${mmss(c.end)}` +
        (len > PERSO_MAX ? " · perso 한계 초과" : "") + "</span>";
      grid.appendChild(r);
    }
    box.appendChild(grid);
    const acts = document.createElement("div");
    acts.className = "out-acts";
    const mk = (label, path, iconName) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn-plain";
      b.innerHTML = `<span data-icon="${iconName}" data-icon-size="14"></span>` +
        `<span>${label}</span>`;
      b.onclick = () => post("/api/open", { path })
        .then(() => toast("폴더를 열었습니다"))
        .catch((e) => toast(e.message, true));
      return b;
    };
    acts.append(
      mk("perso에 올릴 폴더", j.perso, "folder"),
      mk("검수용 영상", j.preview, "film"),
      mk("작업 폴더 전체", j.path, "folder"),
    );
    box.appendChild(acts);
    host.appendChild(box);
    hydrateIcons(box);
  }
}


/* ── 접기 세 개 ─────────────────────────────────────────────
 * 레일 · 서랍 · 도크가 **따로** 접힌다. 필요가 서로 다르다 —
 *   자막을 다듬을 때는 셋 다 접고 넓게,
 *   배치를 돌릴 때는 서랍만 펴고 현황을 보고,
 *   막혔을 때는 도크만 펴서 기록을 본다.
 * 접힘 상태는 localStorage 에 남는다. 창을 다시 열면 그대로다 —
 * 매번 접는 것이 일이 되면 접는 기능이 없는 것과 같다.
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

/* 손이 키보드에 있을 때 — 260820 과 같은 자리(Ctrl+B)를 쓴다. */
window.addEventListener("keydown", (e) => {
  if (!e.ctrlKey || e.altKey || e.metaKey) return;
  const k = e.key.toLowerCase();
  if (k === "b") { e.preventDefault(); $("#rail-toggle").click(); }
  if (k === "j") { e.preventDefault(); $("#drawer-toggle").click(); }
});

/* 지난 값 되살리기 */
setFlag("rail-off", localStorage.getItem("railOff") === "1");
setFlag("drawer-off", localStorage.getItem("drawerOff") === "1");
setFlag("dock-min", localStorage.getItem("dockMin") === "1");
if (localStorage.getItem("pickDense") === "1") {
  $("#pv-card").setAttribute("aria-pressed", "false");
  $("#pv-dense").setAttribute("aria-pressed", "true");
}



/* ── 고른 언어를 문장으로 다시 읽어 주기 ───────────────────
 * select 두 개를 눈으로 견주면 어느 쪽이 음성이고 어느 쪽이 자막인지 매번 다시
 * 생각하게 된다. 그래서 고른 값을 문장으로 한 번 더 말한다.
 */
const LANG_NAME = { ru: "러시아어", uz: "우즈벡어", ko: "한국어", en: "영어" };

function drawSay() {
  const a = $("#opt-lang").value, b = $("#opt-sub").value;
  const m = $("#opt-model").value;
  const same = a === b;
  $("#opt-say").innerHTML =
    `영상에서 <b>${LANG_NAME[a]}</b>를 듣고 <span class="arrow">→</span> ` +
    `자막은 <b>${LANG_NAME[b]}</b>로 만듭니다.` +
    (same
      ? " 같은 언어라 번역 단계(s3b)는 건너뜁니다."
      : ` 번역은 <b>Claude</b>가 초벌을 만듭니다 — 타임코드는 그대로 두고 본문만 갈아끼웁니다.`) +
    ` 전사 모델은 <b>${m}</b>.` +
    (!same && !(CONN && CONN.ok)
      ? ' <b style="color:var(--err)">Claude 연결이 안 되어 있어 번역 단계에서 멈춥니다.</b>'
      : "");
}
for (const id of ["#opt-lang", "#opt-sub", "#opt-model"]) $(id).onchange = drawSay;

/* ── Claude 연결 ────────────────────────────────────────────
 * 자막 번역(s3b)에만 쓰인다. s1~s7 은 이것 없이도 다 돈다.
 * 로그인 자체는 화면이 못 한다 — OAuth 는 브라우저와 CLI 가 주고받는 것이라
 * 중간에서 토큰을 만지면 안 된다. 그래서 콘솔 창을 열어 주고, 사람이 마치면
 * '다시 확인'을 누른다.
 */
let CONN = null;

/* 화면을 녹화해 밖에 공유하는 일이 잦다. 레일 단추는 늘 보이는 자리라 계정을
   가려 둔다 — 전체는 패널을 열었을 때만 보인다. */
function maskEmail(e) {
  const m = /^(.{1,2})[^@]*(@.+)$/.exec(e || "");
  return m ? `${m[1]}****${m[2]}` : (e || "");
}

function drawConn() {
  const c = CONN;
  const dot = $("#conn-dot");
  dot.className = "conn-dot" + (
    !c ? "" : c.ok ? " ok" : (c.cli ? " warn" : " bad"));
  $("#conn-t1").textContent = !c ? "확인 중…" : (c.ok ? "Claude 연결됨" : "Claude 연결 안 됨");
  $("#conn-t2").textContent = !c ? "" : (c.ok ? (maskEmail(c.email) || c.method || "") : c.why);
  $("#conn-btn").title = !c ? "Claude 연결 상태" : `Claude — ${c.why}`;

  const rows = $("#conn-rows");
  if (!rows) return;
  const yn = (v, yes, no) => v
    ? `<dd>${yes}</dd>`
    : `<dd class="no">${no}</dd>`;
  rows.innerHTML = !c ? "" : [
    `<div><dt>실행 파일</dt>${yn(c.cli, "찾음", "못 찾음")}</div>`,
    `<div><dt>로그인</dt>${c.login
      ? `<dd>${c.email || "로그인됨"}</dd>`
      : `<dd class="hold">안 되어 있음</dd>`}</div>`,
    c.login && c.org ? `<div><dt>조직</dt><dd>${c.org}${c.plan ? " · " + c.plan : ""}</dd></div>` : "",
    `<div><dt>파이썬 붙임</dt>${yn(c.sdk, "claude-agent-sdk 있음",
      "claude-agent-sdk 없음 — setup.bat 을 다시 돌리세요")}</div>`,
    c.api_key_env
      ? `<div><dt>API 키</dt><dd class="hold">환경변수에 있음 — 파이프라인은 무시합니다</dd></div>`
      : "",
    c.path ? `<div><dt>경로</dt><dd style="font-weight:500;font-size:11.5px">${c.path}</dd></div>` : "",
  ].filter(Boolean).join("");
}

async function loadConn() {
  try { CONN = await api("/api/claude"); } catch { CONN = null; }
  drawConn();
  drawSay();   // 번역이 필요한데 연결이 없으면 그 경고가 문장에 붙는다
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

/* ── 시작 ──────────────────────────────────────────────────── */
window.addEventListener("hashchange", route);
hydrateIcons(document);
drawSay();
refresh().then(route).catch((e) => toast(e.message, true));
loadConn();
