"use strict";
// dojo web: a hash-routed single page over the local JSON API. No dependencies.
// Everything from the server goes into the DOM as text (h() never sets innerHTML).

const TOKEN = document.querySelector('meta[name="dojo-token"]').content;
const VIEW = document.getElementById("view");
let META = null;
let renderSeq = 0;
let timers = [];
let syncing = false;
const COUNTS = { today: "", upsolve: "", retry: "" };

// ---- plumbing ------------------------------------------------------------------------------

async function api(path, body) {
  const opts = { headers: { "X-Dojo-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let r;
  try { r = await fetch(path, opts); } catch { throw new Error("dojo web isn't running: start it with `dojo web`"); }
  let data = null;
  try { data = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}
const settle = p => p.then(v => v, () => null);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "value") value = v;
    else if (k === "checked") el.checked = !!v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") setStyle(el, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  if (value !== undefined) el.value = value;
  return el;
}
function setStyle(el, styles) {
  for (const [k, v] of Object.entries(styles)) {
    if (v === null || v === undefined) continue;
    if (k.startsWith("--")) el.style.setProperty(k, v); else el.style[k] = v;
  }
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
// replaceChildren() that takes nested arrays and skips null, like h().
function fill(el, ...kids) { el.replaceChildren(); return append(el, kids); }
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "style") setStyle(el, v);
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
}

// `code` spans inside server sentences ("run `dojo stress`") become <code>.
function rich(text) {
  return String(text ?? "").split(/(`[^`]+`)/).map(p => p.length > 1 && p.startsWith("`") && p.endsWith("`") ? h("code", {}, p.slice(1, -1)) : p);
}

function toast(text, kind = "ok") {
  const root = document.getElementById("toast-root");
  const el = h("div", { class: "toast", role: kind === "err" ? "alert" : "status", style: { "--c": kind === "err" ? "var(--bad)" : "var(--good)" } },
    h("span", { class: "vmark" }, kind === "err" ? "!" : "✓"),
    h("span", { class: "msg" }, rich(text)),
    h("button", { type: "button", "aria-label": "Dismiss", onclick: () => el.remove() }, "×"));
  root.append(el);
  while (root.children.length > 3) root.firstElementChild.remove();
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 4200);
}

async function busy(btn, fn) {
  if (btn) { btn.disabled = true; btn.classList.add("busy"); }
  try { return await fn(); }
  catch (e) { toast(e.message, "err"); return undefined; }
  finally { if (btn) { btn.disabled = false; btn.classList.remove("busy"); } }
}

function store(key, val) {
  try {
    if (val === undefined) return localStorage.getItem("dojo." + key);
    localStorage.setItem("dojo." + key, val);
  } catch { /* storage blocked: the page still works, it just forgets */ }
  return null;
}
function every(ms, fn) { fn(); timers.push(setInterval(fn, ms)); }
function stagger(el) {
  [...el.children].forEach((c, i) => c.style.setProperty("--i", String(Math.min(i, 14))));
  el.classList.add("stagger");
  return el;
}

const ICONS = {
  external: ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
  refresh: ["M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", "M8 16H3v5"],
  arrow: ["M5 12h14", "m12 5 7 7-7 7"],
  download: ["M12 15V3", "m7 10 5 5 5-5", "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"],
  check: ["M20 6 9 17l-5-5"],
  copy: ["M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"],
  moon: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"],
};
function icon(name, size = 14, width = 2.2) {
  const svg = s("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": width, "aria-hidden": "true" },
    (ICONS[name] || []).map(d => s("path", { d })));
  if (name === "copy") svg.prepend(s("rect", { width: 14, height: 14, x: 8, y: 8 }));
  return svg;
}
function playIcon() {
  return s("svg", { width: 13, height: 13, viewBox: "0 0 24 24", fill: "currentColor", "aria-hidden": "true" }, s("polygon", { points: "6 3 20 12 6 21 6 3" }));
}

// ---- formatting ----------------------------------------------------------------------------
// The server sends wall-clock times in your timezone (ISO with offset); dates are read from the
// text so the page shows exactly what the CLI shows.

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = n => String(n).padStart(2, "0");

function wall(iso) {
  const [date, time = "00:00"] = String(iso).replace(" ", "T").split("T");
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return { y, m, d, hh, mm, dow: new Date(Date.UTC(y, m - 1, d)).getUTCDay(), day: Date.UTC(y, m - 1, d) / 864e5 };
}
function fmtDate(iso) { const w = wall(iso); return `${DAYS[w.dow]} ${pad(w.d)} ${MONTHS[w.m - 1]}`; }
function fmtDM(iso) { const w = wall(iso); return `${w.d} ${MONTHS[w.m - 1]}`; }
function fmtHM(iso) { const w = wall(iso); return `${pad(w.hh)}:${pad(w.mm)}`; }
function daysBetween(a, b) { return Math.round(wall(b).day - wall(a).day); }
function tsIso(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function todayIso() { return META ? META.today : tsIso(Date.now() / 1000).slice(0, 10); }
function fmtAge(sec) {
  sec = Math.max(0, sec);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  if (sec < 172800) return `${Math.round(sec / 3600)} h`;
  return `${Math.round(sec / 86400)} days`;
}
function ago(ts) {
  const sec = Date.now() / 1000 - ts;
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))} min ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)} h ago`;
  if (sec < 86400 * 14) return `${Math.round(sec / 86400)} d ago`;
  return `${Math.round(sec / 604800)} wk ago`;
}
function fmtDur(sec) {
  const m = Math.round(sec / 60);
  return `${Math.floor(m / 60)} h ${pad(m % 60)} m`;
}
function untilShort(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), hr = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return d ? `${d} d ${hr} h` : `${hr} h ${pad(m)} m`;
}
function untilClock(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), hr = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return d > 1 ? `${d} d ${pad(hr)} h` : `${pad(d * 24 + hr)}:${pad(m)}:${pad(sec % 60)}`;
}
function secondsTo(iso) { return (Date.parse(iso) - Date.now()) / 1000; }
function pct(x) { return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`; }
function plural(n, word, many) { return `${n} ${n === 1 ? word : (many || word + "s")}`; }
function cap(t) { return t ? t[0].toUpperCase() + t.slice(1) : ""; }
function ms(sec) { return `${Math.max(0, Math.round(sec * 1000))} ms`; }
function tilde(path) { return String(path || "").replace(/^\/home\/[^/]+/, "~").replace(/^\/root(?=\/)/, "~"); }
function lastLine(text) { return String(text || "").trim().split("\n").filter(Boolean).pop() || ""; }
function dedent(lines) {
  const used = lines.filter(l => l.trim());
  const ind = used.length ? Math.min(...used.map(l => l.match(/^\s*/)[0].length)) : 0;
  return lines.map(l => l.slice(ind)).join("\n").replace(/\s+$/, "");
}

// ---- ratings -------------------------------------------------------------------------------

const RANK_VARS = [[2400, "gm"], [2100, "master"], [1900, "cm"], [1600, "expert"], [1400, "specialist"], [1200, "pupil"], [-1e9, "newbie"]];
const RANK_BANDS = [[0, 1200, "newbie"], [1200, 1400, "pupil"], [1400, 1600, "specialist"], [1600, 1900, "expert"],
  [1900, 2100, "cm", "cand. master"], [2100, 2400, "master"], [2400, 5000, "gm", "grandmaster"]];
function rkVar(r) {
  if (r === null || r === undefined) return "var(--muted)";
  for (const [lo, k] of RANK_VARS) if (r >= lo) return `var(--rk-${k})`;
  return "var(--rk-newbie)";
}
function rankName(r) {
  const ranks = (META && META.ranks) || [];
  let name = "newbie";
  for (const k of [...ranks].sort((a, b) => a.low - b.low)) if (r >= k.low) name = k.name;
  return name;
}
function rk(r, size = "") {
  if (r === null || r === undefined) return h("span", { class: `rk unrated ${size}` }, "unrated");
  return h("span", { class: `rk ${size}`, style: { color: rkVar(r) } }, r);
}

// ---- shell ---------------------------------------------------------------------------------

const NAV = [
  ["Codeforces", [["", "Home"], ["today", "Today", "today"], ["upsolve", "Upsolve", "upsolve"], ["retry", "Re-solve", "retry"],
    ["weak", "Weak tags"], ["contests", "Contests"], ["stats", "Stats"]]],
  ["Code", [["judge", "Judge"], ["java", "Java sheet"]]],
  ["Courses", [["drill", "Drills"], ["solve", "Solve"]]],
];
const LABELS = Object.fromEntries(NAV.flatMap(([, items]) => items.map(([id, label]) => [id, label])));

function hashParts() { return location.hash.replace(/^#\/?/, "").split("/"); }

function renderNav() {
  const cur = hashParts()[0];
  const groups = phone => NAV.map(([group, items]) => h("div", { class: "nav-group" },
    h("div", { class: "label-s" }, group),
    items.map(([id, label, count]) => h("a", {
      class: "nav-item", href: "#/" + id, "aria-current": cur === id ? "page" : null, onclick: phone ? closeMenu : null,
    }, h("span", { class: "mark" }), h("span", { class: "grow" }, label), count ? h("span", { class: "count" }, COUNTS[count]) : null))));
  document.getElementById("nav").replaceChildren(...groups(false));
  document.getElementById("phone-menu").replaceChildren(...groups(true), h("div", { class: "fresh mono" }, freshText()));
  document.getElementById("menu-label").textContent = LABELS[cur] || "dojo";
}
function closeMenu() {
  document.getElementById("phone-menu").hidden = true;
  document.getElementById("menu-btn").setAttribute("aria-expanded", "false");
}
document.getElementById("menu-btn").addEventListener("click", () => {
  const menu = document.getElementById("phone-menu");
  menu.hidden = !menu.hidden;
  document.getElementById("menu-btn").setAttribute("aria-expanded", String(!menu.hidden));
});

function dataAge() {
  const at = META && META.fetched_at && META.fetched_at.status;
  return at ? Date.now() / 1000 - at : null;
}
function freshText() {
  if (syncing) return "syncing…";
  const age = dataAge();
  return age === null ? "no data yet" : age < 60 ? "data just now" : `data ${fmtAge(age)} old`;
}
function paintMeta() {
  const who = document.getElementById("who");
  if (META) {
    who.replaceChildren(h("span", { class: "handle", style: { color: rkVar(META.rating) } }, META.handle), rk(META.rating));
    document.getElementById("phone-rating").replaceChildren(rk(META.rating, "rk-s"));
  }
  paintFresh();
}
function paintFresh() {
  const age = dataAge();
  const stale = syncing || age === null || age > 86400;
  document.getElementById("fresh-label").textContent = freshText();
  document.querySelector(".side .fresh").classList.toggle("stale", stale);
  for (const b of document.querySelectorAll("[data-sync]")) {
    b.disabled = syncing || !!(META && META.offline);
    b.title = META && META.offline ? "dojo web was started with --offline" : "Refresh Codeforces data";
  }
  for (const l of document.querySelectorAll("[data-sync-label]")) l.textContent = syncing ? "Syncing…" : "Sync";
  document.getElementById("syncbar").hidden = !syncing;
  const banner = document.getElementById("banner");
  if (!syncing && age !== null && age > 86400 && !(META && META.offline)) {
    banner.replaceChildren(h("div", { class: "banner" }, h("span", { class: "sq" }),
      h("span", { class: "grow" }, h("strong", {}, `Data is ${fmtAge(age)} old.`), " Plan, upsolve list and rating may be behind your latest submissions."),
      h("button", { type: "button", onclick: doSync }, "Sync")));
  } else banner.replaceChildren();
  const menuFresh = document.querySelector("#phone-menu .fresh");
  if (menuFresh) menuFresh.textContent = freshText();
}

async function doSync() {
  if (syncing) return;
  if (META && META.offline) { toast("dojo web was started with --offline, so there's nothing to sync.", "err"); return; }
  const before = freshText();
  syncing = true; paintFresh();
  try {
    META = await api("/api/sync", {});
    toast(`Synced with Codeforces · rating ${META.rating ?? "unrated"}`);
    syncing = false; paintMeta();
    refreshCounts();
    route(true);
  } catch (e) {
    toast(`Sync failed: ${e.message}. Still showing ${before.replace(/^data /, "data ")}.`, "err");
  } finally {
    syncing = false; paintFresh();
  }
}
for (const b of document.querySelectorAll("[data-sync]")) b.addEventListener("click", doSync);

function theme() { return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark"; }
function setTheme(t, save = true) {
  document.documentElement.setAttribute("data-theme", t);
  if (save) store("theme", t);
  for (const b of document.querySelectorAll("[data-theme-opt]")) b.setAttribute("aria-checked", String(b.dataset.themeOpt === t));
}
for (const b of document.querySelectorAll("[data-theme-opt]")) b.addEventListener("click", () => setTheme(b.dataset.themeOpt));
document.getElementById("theme-toggle").addEventListener("click", () => setTheme(theme() === "dark" ? "light" : "dark"));
if (window.matchMedia) {
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", e => { if (!store("theme")) setTheme(e.matches ? "light" : "dark", false); });
}

function setCount(key, value) { COUNTS[key] = value; renderNav(); }
async function refreshCounts() {
  const [t, u, r] = await Promise.all([settle(api("/api/today")), settle(api("/api/upsolve")), settle(api("/api/retry"))]);
  if (t) COUNTS.today = `${t.done}/${t.total}`;
  if (u) COUNTS.upsolve = String(u.items.length);
  if (r) COUNTS.retry = String(r.due.length);
  renderNav();
}

// ---- router --------------------------------------------------------------------------------

const ROUTES = {};

async function route(soft = false) {
  const seq = ++renderSeq;
  timers.forEach(clearInterval); timers = [];
  const [name, ...rest] = hashParts();
  renderNav(); closeMenu();
  document.title = name && LABELS[name] ? `${LABELS[name]} · dojo` : "dojo";
  const fn = ROUTES[name] || notFound;
  const skel = soft ? null : setTimeout(() => { if (seq === renderSeq) VIEW.replaceChildren(skeleton()); }, 150);
  let node;
  try { node = await fn(rest.map(decodeURIComponent)); }
  catch (e) { node = errorScreen(e); }
  clearTimeout(skel);
  if (seq !== renderSeq) return;
  if (!soft) node.classList.add("enter");
  VIEW.replaceChildren(node);
  if (!soft && name !== route.last) { VIEW.focus({ preventScroll: true }); window.scrollTo(0, 0); }
  route.last = name;
  if (node.afterMount) node.afterMount();
}
window.addEventListener("hashchange", () => route());

function skeleton() {
  return h("div", { class: "skel", "aria-busy": "true" },
    h("div", {}, h("div", { class: "bar1" }), h("div", { class: "bar2" })),
    h("div", { class: "rule" }),
    h("div", { class: "cards" }, h("span"), h("span"), h("span")),
    h("div", {}, ["40%", "55%", "32%", "48%", "38%", "60%"].map(w =>
      h("div", { class: "srow" }, h("span"), h("span"), h("span", { style: { width: w } })))),
    h("div", { class: "mono" }, "loading from the cache…"));
}
function head(kicker, title, { lede, tools } = {}) {
  return h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "label" }, kicker), h("h1", {}, title), lede ? h("p", { class: "lede" }, lede) : null),
    tools ? h("div", { class: "head-tools" }, tools) : null);
}
function errorScreen(e) {
  const offlineHint = /no cached|sync|network|offline/i.test(e.message) && !(META && META.offline);
  return h("div", { class: "screen" }, head("Something went wrong", "Couldn't load this page"),
    h("div", { class: "ruled empty" }, h("strong", {}, rich(e.message)),
      h("span", {}, offlineHint ? "Syncing fetches fresh data from Codeforces." : "The terminal running `dojo web` may say more."),
      h("div", { class: "btn-row", style: { marginTop: "10px" } },
        h("button", { class: "btn", type: "button", onclick: () => route() }, "Try again"),
        offlineHint ? h("button", { class: "btn btn-primary", type: "button", onclick: doSync }, "Sync") : null)));
}
function notFound() {
  return h("div", { class: "screen" }, head("dojo", "Not here"),
    h("div", { class: "ruled empty" }, h("strong", {}, "No such page."), h("span", {}, h("a", { href: "#/" }, "Go home"))));
}
function seg(options, value, onChange, label, cls = "") {
  return h("div", { class: `seg ${cls}`, role: "radiogroup", "aria-label": label }, options.map(([v, text]) =>
    h("button", { type: "button", role: "radio", "aria-checked": String(v === value), onclick: () => onChange(v) }, text)));
}
function openLink(url, label = "Open", cls = "btn btn-sm") {
  return h("a", { class: cls, href: url, target: "_blank", rel: "noopener" }, label, icon("external", 13));
}
function newFileButton(key, java, cls = "btn btn-sm") {
  return h("button", {
    class: cls, type: "button", title: `create the solution file (dojo new ${key}${java ? " --java" : ""})`,
    onclick: e => busy(e.currentTarget, () => createFile(key, java)),
  }, "New file");
}
async function createFile(key, java) {
  const r = await api("/api/new", { id: key, java: !!java });
  if (r.code !== 0) throw new Error(lastLine(r.output) || "dojo new failed");
  if (r.path) {
    sessionStorage.setItem("dojo.judgeFile", r.path);
    toast(`Created ${tilde(r.path)} · it's selected in Judge`);
  } else toast(lastLine(r.output));
  return r;
}

// ---- home ----------------------------------------------------------------------------------

const SLOT = { warmup: "warm-up", core: "core", stretch: "stretch", java: "java", upsolve: "upsolve", retry: "retry" };
const COMMANDS = {
  today: ["Today's plan", "#/today", "today's plan"], new: ["Today's plan", "#/today", "a new solution file"],
  stress: ["Open Judge", "#/judge", "a stress test"], test: ["Open Judge", "#/judge", "the judge"],
  upsolve: ["Upsolve", "#/upsolve", "the upsolve list"], contests: ["Contests", "#/contests", "Contests"],
  weak: ["Weak tags", "#/weak", "your weak tags"], retry: ["Re-solve", "#/retry", "the re-solve list"],
  drill: ["Drills", "#/drill", "a drill"], status: ["Stats", "#/stats", "your stats"],
};
function insight(text) {
  let action = null;
  const out = String(text).replace(/`dojo (\w+)[^`]*`/g, (m, cmd) => {
    const c = COMMANDS[cmd];
    if (!c) return m;
    action = action || c;
    return c[2];
  });
  return { text: out, action };
}
function heroCopy(item, st) {
  const gap = st.last_ac ? daysBetween(st.last_ac, todayIso()) : null;
  const lead = gap !== null && gap >= 3 ? `One clean accepted solution ends a ${gap}-day gap. `
    : st.week_solved < st.week_goal ? `${st.week_goal - st.week_solved} more this week reaches your goal of ${st.week_goal}. ` : "";
  const tail = {
    warmup: "Read it twice, write it once, submit. Ten minutes is enough.",
    core: "It targets a weak tag at your level. Give it 30 minutes, then read the editorial.",
    stretch: "Hard but within reach: 40 minutes, then read the editorial.",
    java: "Solve it in Java for CIS 201. New file gives you class Main with fast input.",
    upsolve: `${cap(item.note || "from one of your contests")}. Upsolving rounds you took part in is the fastest way to climb.`,
    retry: "Solve it again from a blank file, without looking at your old code.",
  }[item.slot] || "";
  return lead + tail;
}
function rowNote(item, showTags) {
  if (item.done) return "Accepted";
  switch (item.slot) {
    case "warmup": return "Ten minutes. Read twice, code once.";
    case "core": return showTags && item.focus_tag ? `Focus tag · ${item.focus_tag}` : "Aimed at a weak tag · 30 minutes, then the editorial";
    case "stretch": return "40 minutes, then read the editorial";
    case "java": return "Solve it in Java";
    default: return cap(item.note || "");
  }
}
function roundsLabel(hist) {
  const divs = new Set(hist.map(r => (r.contest_name.match(/\((Div\. \d)\)/) || [])[1] || "?"));
  return divs.size === 1 && !divs.has("?") ? plural(hist.length, `${[...divs][0]} round`) : plural(hist.length, "rated round");
}

ROUTES[""] = async () => {
  const [st, plan, cons, drills] = await Promise.all([
    api("/api/status"), settle(api("/api/today")), settle(api("/api/contests")), settle(api("/api/drill/topics"))]);
  if (plan) COUNTS.today = `${plan.done}/${plan.total}`;
  const now = META ? wall(META.now) : wall(tsIso(Date.now() / 1000));
  const today = todayIso();
  const weekDay = Math.min(7, Math.max(1, daysBetween(st.week_start, today) + 1));
  const city = META ? META.timezone.split("/").pop().replace(/_/g, " ") : "";

  const top = h("div", { class: "home-top" },
    h("div", { class: "label" }, `${DAYS[now.dow]} ${pad(now.d)} ${MONTHS[now.m - 1]} · ${pad(now.hh)}:${pad(now.mm)} ${city} · week day ${weekDay} of 7`),
    h("div", { class: "mono" }, freshText()));

  const items = plan ? plan.items : [];
  const next = items.find(i => !i.done);
  let hero;
  if (next) {
    hero = h("div", { class: "hero-next" },
      h("div", { class: "label" }, `Do this next · ${SLOT[next.slot] || next.label}`),
      h("div", { class: "hero-title" }, h("span", { class: "pid" }, next.key), h("span", { class: "pname" }, next.name), rk(next.rating, "rk-l")),
      h("p", {}, heroCopy(next, st)),
      h("div", { class: "btn-row" },
        openLink(next.url, "Open on Codeforces", "btn btn-primary btn-lg"),
        newFileButton(next.key, next.slot === "java", "btn btn-lg"),
        h("a", { class: "btn btn-ghost btn-lg", href: "#/today" }, `Today's plan · ${plan.done}/${plan.total}`)));
  } else if (plan) {
    hero = h("div", { class: "hero-next" },
      h("div", { class: "label" }, "Today's plan · done"),
      h("div", { class: "hero-title" }, h("span", { class: "pname" }, `All ${plan.total} solved today`)),
      h("p", {}, "That's the day's work. Upsolve one more from a recent round, or spend ten minutes on a course drill."),
      h("div", { class: "btn-row" }, h("a", { class: "btn btn-primary btn-lg", href: "#/upsolve" }, "Upsolve", icon("arrow")),
        h("a", { class: "btn btn-lg", href: "#/drill" }, "Drills")));
  } else {
    hero = h("div", { class: "hero-next" }, h("div", { class: "label" }, "Do this next"),
      h("p", {}, "Today's plan needs the problemset. Sync once to download it."),
      h("div", { class: "btn-row" }, h("button", { class: "btn btn-primary btn-lg", type: "button", onclick: doSync }, "Sync")));
  }

  const statsRow = h("section", { class: "grid-auto stagger", style: { "--min": "240px" } },
    weekBlock(st, weekDay), streakBlock(st), contestBlock(cons));

  const ins = (st.insights || []).slice(0, 3).map((x, i) => {
    const { text, action } = insight(x.text);
    return h("div", { class: "insight" }, h("span", { class: "n" }, pad(i + 1)), h("p", {}, rich(text)),
      action ? h("a", { href: action[1] }, `${action[0]} →`) : null);
  });
  const left = h("div", { class: "block", style: { gap: "0" } }, h("div", { class: "label", style: { paddingBottom: "6px" } }, "What to change"),
    ins.length ? ins : h("p", { class: "muted", style: { padding: "12px 0" } }, "Nothing stands out. Keep the daily plan going."));

  const right = h("div", { style: { display: "flex", flexDirection: "column", gap: "24px", minWidth: "0" } });
  if (plan) {
    right.append(h("div", { class: "block", style: { gap: "0" } },
      h("div", { class: "block-head", style: { paddingBottom: "6px" } }, h("span", { class: "label" }, "Today's plan"), h("span", { class: "meta" }, `${plan.done}/${plan.total} done`)),
      items.map(it => h("a", { class: "plan-mini" + (it.done ? " done" : ""), href: "#/today" },
        h("span", { class: "box" }), h("span", { class: "slot" }, SLOT[it.slot] || it.label), h("span", { class: "pid" }, it.key),
        h("span", { class: "pname" }, it.name), rk(it.rating, "rk-s")))));
  }
  const dc = drillCard(drills);
  if (dc) right.append(dc);

  const node = h("div", { class: "screen loose" }, top,
    h("section", { class: "hero" }, hero, ratingPanel(st)),
    statsRow,
    h("section", { class: "home-grid" }, left, right));
  return node;
};

function ratingPanel(st) {
  const r = st.rating, target = st.target, hist = st.rating_history || [];
  const panel = h("div", { class: "hero-rating" }, h("div", { class: "label" }, "Rating"));
  if (r === null || r === undefined) {
    panel.append(h("div", { class: "rating-line" }, h("span", { class: "big muted" }, "—"), h("span", { class: "muted" }, "unrated →"),
      h("span", { class: "tgt", style: { color: rkVar(target) } }, target)),
      h("p", { class: "muted" }, "Your first rated Div. 3 or Div. 4 round sets your rating."));
    return panel;
  }
  const width = Math.min(100, Math.max(0, r / target * 100));
  const ticks = hist.slice(0, -1).map(x => x.new).filter(v => v > 0 && v < target);
  const shown = hist.length > 6 ? hist.slice(-6) : hist;
  panel.append(
    h("div", { class: "rating-line" },
      h("span", { class: "big", style: { color: rkVar(r) } }, r),
      h("span", { class: "muted" }, `${st.rank || rankName(r)} →`),
      h("span", { class: "tgt", style: { color: rkVar(target) } }, target),
      h("span", { class: "muted" }, (st.target_name || rankName(target)).toLowerCase())),
    h("div", {},
      h("div", { class: "progress", style: { color: rkVar(r) } },
        h("div", { class: "fill grow-x", style: { width: width + "%" } }),
        ticks.map(v => h("div", { class: "tick", style: { left: (v / target * 100) + "%" } }))),
      h("div", { class: "progress-scale" }, h("span", {}, "0"),
        h("strong", {}, r >= target ? "target reached" : `${target - r} to go`), h("span", {}, target))),
    h("div", { class: "history" },
      hist.length > shown.length ? h("span", {}, "…") : null,
      shown.map((x, i) => [
        i === 0 && hist.length === shown.length ? null : h("span", { class: x.delta >= 0 ? "good" : "bad" }, (x.delta >= 0 ? "+" : "") + x.delta),
        h("span", { class: i === shown.length - 1 ? "now" : "" }, x.new)]),
      hist.length ? h("span", {}, `· ${roundsLabel(hist)}`) : h("span", {}, "no rated rounds yet")));
  return panel;
}
function weekBlock(st, weekDay) {
  const goal = st.week_goal || 10, n = st.week_solved || 0;
  const left = 7 - weekDay;
  return h("div", { class: "block" },
    h("div", { class: "label" }, "This week"),
    h("div", { class: "stat-big" }, h("span", { class: "n" }, n), h("span", { class: "of" }, `/ ${goal} solved`)),
    h("div", { class: "week-cells", style: { "--n": String(goal) } }, Array.from({ length: goal }, (_, i) => h("span", { class: i < n ? "on" : "" }))),
    h("div", { class: "note" }, `Week started ${fmtDate(st.week_start)} · ${left === 0 ? "last day" : plural(left, "day") + " left"}`));
}
function streakBlock(st) {
  const msg = st.streak === 0 ? "One AC today starts it again." : st.active_today ? "Kept today." : "Solve one today to keep it.";
  return h("div", { class: "block" },
    h("div", { class: "label" }, "Streak"),
    h("div", { class: "stat-big" }, h("span", { class: "n" }, st.streak), h("span", { class: "of" }, `${st.streak === 1 ? "day" : "days"} · best ${st.best_streak}`)),
    h("div", { class: "note" }, msg));
}
function contestBlock(cons) {
  const list = (cons || []).filter(c => !c.div1_only && !c.running);
  const c = list.find(x => x.recommended) || list[0];
  const block = h("div", { class: "block" }, h("div", { class: "label" }, "Next contest"));
  if (!c) {
    block.append(h("div", { class: "clock muted" }, "—"), h("div", { class: "note" }, cons ? "No rounds announced yet." : "Contest list unavailable. Sync to fetch it."));
    return block;
  }
  const clock = h("div", { class: "clock" });
  const when = h("span", {});
  block.append(clock, h("div", { class: "contest-mini" }, h("a", { class: "plain-link", href: c.url, target: "_blank", rel: "noopener" }, h("strong", {}, c.name)), h("br"),
    h("span", {}, `${fmtDate(c.start)} ${fmtHM(c.start)} · in `, when, c.recommended ? [" · ", h("span", { class: "accent" }, "★"), " suits you"] : null)));
  every(1000, () => { const sec = secondsTo(c.start); clock.textContent = untilClock(sec); when.textContent = untilShort(sec); });
  return block;
}
function drillCard(drills) {
  if (!drills || !drills.suggest) return null;
  const t = drills.topics.find(x => x.key === drills.suggest.key);
  if (!t) return null;
  const { level, count } = drillPrefs();
  return h("div", { class: "drill-card" },
    h("div", { class: "label" }, `Suggested drill · ${t.course} ${drills.courses[t.course] || ""}`),
    h("div", { class: "title" }, t.title),
    h("div", { class: "muted" }, `${cap(drills.suggest.why)} · ${count} questions · level ${Math.min(level, t.levels)}`),
    h("a", { class: "btn", href: `#/drill/${t.key}` }, "Start drill", icon("arrow")));
}

// ---- today ---------------------------------------------------------------------------------

ROUTES.today = async () => {
  let plan = await api("/api/today");
  let showTags = store("showTags") === "1";
  const root = h("div", { class: "screen tight" });

  function paint() {
    setCount("today", `${plan.done}/${plan.total}`);
    const tagSwitch = h("button", { class: "switch", type: "button", role: "switch", "aria-checked": String(showTags),
      onclick: () => { showTags = !showTags; store("showTags", showTags ? "1" : "0"); paint(); } },
    h("span", { class: "track" }, h("span", { class: "knob" })), "Show tags ", h("span", { class: "muted" }, "(spoilers)"));
    const reroll = h("button", { class: "btn", type: "button", onclick: e => busy(e.currentTarget, async () => {
      plan = await api("/api/today/reroll", {});
      toast("Rerolled the problems you haven't solved");
      paint();
    }) }, icon("refresh"), "Reroll");
    const list = stagger(h("div", { class: "ruled" }, plan.items.map(it => h("div", { class: "trow" + (it.done ? " done" : "") },
      h("span", { class: "tbox", title: it.done ? "Accepted on Codeforces" : "Ticks itself when Codeforces reports an AC", "aria-label": it.done ? `${it.key} solved` : `${it.key} not solved` },
        it.done ? icon("check", 14, 3.2) : null),
      h("span", { class: "slot" }, SLOT[it.slot] || it.label),
      h("span", { class: "pid" }, it.key),
      h("div", { class: "body" },
        h("a", { class: "pname", href: it.url, target: "_blank", rel: "noopener" }, it.name),
        h("span", { class: "tnote" }, rowNote(it, showTags)),
        showTags && it.tags && it.tags.length ? h("div", { class: "tags" }, it.tags.map(t => h("span", { class: "pill" }, t))) : null),
      rk(it.rating),
      h("div", { class: "btn-group" },
        openLink(it.url),
        newFileButton(it.key, it.slot === "java"),
        it.done ? null : h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: e => busy(e.currentTarget, async () => {
          const r = await api("/api/today/skip", { ref: it.key });
          plan = r;
          toast(r.replacement ? `Skipped ${r.skipped} · ${r.replacement} takes its place` : `Skipped ${r.skipped} · nothing left to replace it with`);
          paint();
        }) }, "Skip"))))));
    root.replaceChildren(
      head(`Today · ${fmtDate(plan.day)}` + (plan.rerolls ? ` · rerolled ${plan.rerolls}×` : ""), `${plan.done} of ${plan.total} done`, { tools: [tagSwitch, reroll] }),
      h("div", { class: "segs", style: { "--n": String(plan.total) } }, plan.items.map(it => h("span", { class: it.done ? "good" : "" }))),
      list,
      h("div", { class: "note" }, "Rows tick themselves when Codeforces reports an AC. A skipped problem is never planned again."));
  }
  paint();
  return root;
};

// ---- upsolve -------------------------------------------------------------------------------

let upsolveAll = false;
ROUTES.upsolve = async () => {
  const data = await api("/api/upsolve" + (upsolveAll ? "?all=1" : ""));
  if (!upsolveAll) setCount("upsolve", String(data.items.length));
  const groups = [];
  for (const it of data.items) {
    let g = groups.find(x => x.id === it.contest_id);
    if (!g) groups.push(g = { id: it.contest_id, first: it, rows: [] });
    g.rows.push(it);
  }
  const root = h("div", { class: "screen" },
    head(`Codeforces · ${plural(data.items.length, "unsolved problem")} from ${plural(groups.length, "contest")}`, "Upsolve"));
  if (!groups.length) {
    root.append(h("div", { class: "ruled empty" }, h("strong", {}, "Nothing to upsolve."),
      h("span", {}, data.hidden ? `${plural(data.hidden, "harder problem")} above ${data.comfort + 500} are hidden.` : "Every problem from your contests at your level is solved. Enter a round to fill this list.")));
  }
  for (const g of groups) {
    const f = g.first;
    root.append(h("section", { class: "ruled" },
      h("div", { class: "section-head group-head" },
        h("h2", {}, h("a", { href: f.contest_url, target: "_blank", rel: "noopener" }, f.contest_name)),
        h("span", { class: "muted" }, fmtDate(tsIso(f.contest_time))),
        f.delta !== null && f.delta !== undefined ? h("span", { class: "mono " + (f.delta >= 0 ? "good" : "bad"), style: { fontWeight: "700" } }, (f.delta >= 0 ? "+" : "") + f.delta) : h("span", { class: "muted" }, "unrated for you"),
        f.rank ? h("span", { class: "mono muted" }, `rank ${f.rank}`) : null,
        f.rating_after ? rk(f.rating_after) : null),
      stagger(h("div", {}, g.rows.map(r => h("div", { class: "prow" },
        h("span", { class: "pid" }, r.key), h("span", { class: "pname" }, r.name, r.attempted ? h("span", { class: "muted", style: { fontSize: "13px" } }, " · attempted") : null),
        rk(r.rating), h("div", { class: "btn-group" }, openLink(r.url), newFileButton(r.key, false))))))));
  }
  if (data.hidden || upsolveAll) {
    root.append(h("div", { class: "more" },
      upsolveAll ? "Showing every unsolved problem." : `${plural(data.hidden, "harder problem")} above ${data.comfort + 500} hidden.`,
      h("button", { class: "btn btn-sm", type: "button", onclick: () => { upsolveAll = !upsolveAll; route(true); } }, upsolveAll ? "Hide the hard ones" : "Show all")));
  }
  return root;
};

// ---- re-solve ------------------------------------------------------------------------------

ROUTES.retry = async () => {
  const data = await api("/api/retry");
  setCount("retry", String(data.due.length));
  const today = todayIso();
  const resolves = [...data.due, ...data.later].sort((a, b) => String(a.due).localeCompare(String(b.due)));
  const stages = data.stages || 3;
  const total = resolves.length + data.unsolved.length;
  const root = h("div", { class: "screen" },
    head(`Codeforces · ${plural(total, "problem")}`, "Re-solve",
      { lede: "Problems that took several failed attempts come back three times, after 3, 10 and 30 days, to be solved again from a blank file." }));

  const due = h("section", { class: "ruled" },
    h("div", { class: "section-head" }, h("h2", {}, "Due re-solves"), h("span", { class: "count" }, data.later.length ? `${data.due.length} due · ${data.later.length} later` : `${data.due.length} due`)));
  if (!resolves.length) {
    due.append(h("div", { class: "empty row-rule" }, h("strong", {}, "No re-solves due — nice."),
      h("span", {}, "Problems you solve after 2+ failed attempts show up here a few days later.")));
  } else if (!data.due.length) {
    due.append(h("div", { class: "empty row-rule" }, h("strong", {}, "No re-solves due — nice."),
      h("span", {}, `The next one comes back ${fmtDate(resolves[0].due)}. Today's plan is the place to be.`)));
  }
  due.append(stagger(h("div", {}, resolves.map(r => {
    const stage = (r.stage ?? 0) + 1;
    const d = String(r.due);
    const isDue = d <= today;
    return h("div", { class: "prow rrow" },
      h("span", { class: "pid" }, r.key),
      h("a", { class: "pname plain-link", href: r.url, target: "_blank", rel: "noopener" }, r.name),
      rk(r.rating),
      h("span", { class: "stages" }, h("span", { class: "dots" }, Array.from({ length: stages }, (_, i) =>
        h("span", { class: i + 1 < stage ? "done" : i + 1 === stage ? "now" : "" }))), `stage ${stage} of ${stages}`),
      h("span", { class: "due" + (isDue ? " now" : "") }, d === today ? "due today" : isDue ? `due since ${fmtDM(d)}` : fmtDate(d)),
      h("span", { class: "fails" }, `${r.wrong} failed`),
      h("button", { class: "btn btn-sm", type: "button", onclick: e => busy(e.currentTarget, async () => {
        const res = await api("/api/retry/done", { key: r.key });
        toast(res.next_due ? `${r.key} re-solved · back ${fmtDate(res.next_due)}` : `${r.key} retired · ${stages} clean re-solves`);
        route(true);
      }) }, "Mark re-solved"));
  }))));
  root.append(due);

  const uns = h("section", { class: "ruled" },
    h("div", { class: "section-head" }, h("h2", {}, "Still unsolved"), h("span", { class: "count" }, String(data.unsolved.length))));
  if (!data.unsolved.length) uns.append(h("div", { class: "empty row-rule" }, h("strong", {}, "Everything you tried is solved."), h("span", {}, "Attempted-but-unaccepted problems land here.")));
  else uns.append(h("div", { class: "unsolved-grid" }, data.unsolved.map(r => h("div", { class: "urow" },
    h("span", { class: "pid" }, r.key),
    h("a", { href: r.url, target: "_blank", rel: "noopener", title: r.source ? `${r.name} · ${r.source}` : r.name }, r.name),
    rk(r.rating, "rk-s"),
    h("span", { class: "wa" }, `${r.wrong} WA`)))));
  root.append(uns);
  return root;
};

// ---- weak tags -----------------------------------------------------------------------------

let weakBand = null;
ROUTES.weak = async () => {
  const doc = await api("/api/weak" + (weakBand ? `?band=${encodeURIComponent(weakBand)}` : ""));
  const [lo, hi] = doc.default_band || doc.band;
  const bands = [[lo, Math.max(lo + 100, hi - 200)], [lo, hi], [lo + 200, hi + 200]].map(([a, b]) => `${a}-${b}`);
  const cur = `${doc.band[0]}-${doc.band[1]}`;
  if (!bands.includes(cur)) bands.push(cur);
  const bandText = `${doc.band[0]}–${doc.band[1]}`;
  const focus = doc.focus || [];
  const tags = doc.tags.filter(t => t.importance >= (doc.show_min_importance || 0) || focus.includes(t.tag))
    .sort((a, b) => b.focus - a.focus);
  const maxFocus = Math.max(1e-9, ...tags.map(t => t.focus));
  const root = h("div", { class: "screen" },
    head("Codeforces · compared with problems at your level", "Weak tags", {
      tools: [h("span", { class: "muted", style: { fontSize: "13px" } }, "Rating band"),
        seg(bands.map(b => [b, b.replace("-", "–")]), cur, b => { weakBand = b; route(true); }, "Rating band")],
    }));
  if (focus.length) {
    root.append(stagger(h("div", { class: "top3" }, focus.map((t, i) => h("div", {},
      h("span", { class: "n" }, pad(i + 1)), h("strong", {}, t), h("span", { class: "muted" }, cap(doc.reasons[t] || "")))))));
  }
  if (!tags.length) {
    root.append(h("div", { class: "ruled empty" }, h("strong", {}, `No tagged solves rated ${bandText}.`), h("span", {}, "Try a wider band.")));
    return root;
  }
  root.append(h("div", { class: "scroll-x" }, h("table", { class: "table weak-table" },
    h("thead", {}, h("tr", {}, ["Tag", "Share at level", "Solved / expected", "Fail rate", "Focus score"].map((t, i) => h("th", { style: i === 4 ? { width: "32%" } : null }, t)))),
    h("tbody", {}, tags.map(t => {
      const score = Math.round(t.focus / maxFocus * 100);
      const top = focus.includes(t.tag);
      return h("tr", { class: top ? "top" : "" },
        h("td", {}, t.tag),
        h("td", { class: "num" }, `${Math.round(t.importance * 100)}%`),
        h("td", { class: "num" }, h("span", { class: t.solved < t.expected * 0.6 ? "bad" : "", style: { fontWeight: "700" } }, t.solved), h("span", { class: "muted" }, ` / ${t.expected.toFixed(1)}`)),
        h("td", { class: "num" }, t.attempts ? pct(t.failed_attempts / t.attempts) : "—"),
        h("td", {}, h("div", { class: "bar" }, h("div", { class: "track" }, h("div", { class: "fill grow-x", style: { width: score + "%" } })), h("span", { class: "mono" }, score))));
    })))));
  root.append(h("div", { class: "note" },
    `Focus score weighs how often a tag appears in problems rated ${bandText} against your solves and fail rate. ` +
    `Expected = solves you'd have if your ${doc.tagged_solved} tagged solves matched the band's tag mix.` +
    (doc.untagged_solved ? ` ${doc.untagged_solved} of your ${doc.solved_total} solves are group problems without tags and aren't counted.` : "")));
  return root;
};

// ---- contests ------------------------------------------------------------------------------

ROUTES.contests = async () => {
  const list = (await api("/api/contests")).filter(c => !c.div1_only);
  const offset = list.length ? (list[0].start.match(/([+-]\d\d):?(\d\d)$/) || []) : [];
  const utc = offset[1] ? ` (UTC${offset[1].replace(/^([+-])0/, "$1")}${offset[2] !== "00" ? ":" + offset[2] : ""})` : "";
  const city = META ? META.timezone.split("/").pop().replace(/_/g, " ") : "your timezone";
  const icsAll = `/api/contests.ics?t=${encodeURIComponent(TOKEN)}&rec=1`;
  const root = h("div", { class: "screen tight" },
    head(`Codeforces · times in ${city}${utc}`, "Contests", {
      tools: list.some(c => c.recommended) ? h("a", { class: "btn", href: icsAll, download: "codeforces.ics" }, icon("download"), "Add all ★ to calendar (.ics)") : null,
    }),
    h("div", { class: "legend" },
      h("span", {}, h("span", { class: "accent" }, "★"), " suits you · Div. 2/3/4, Educational"),
      h("span", {}, h("span", { class: "warn" }, "⚠"), " clashes with a class"),
      h("span", {}, h("span", { class: "info" }, icon("moon", 12, 2.4)), " late night")));
  if (!list.length) {
    root.append(h("div", { class: "ruled empty" }, h("strong", {}, "No upcoming contests announced."),
      h("span", {}, "Codeforces usually posts rounds about a week ahead. Upsolve or re-solve in the meantime.")));
    return root;
  }
  const rows = list.map(c => {
    const cd = h("span", { class: "mono" });
    const cdLabel = h("span", { class: "label-s" }, c.running ? "ends in" : "starts in");
    timersTick(() => { cd.textContent = untilShort(secondsTo(c.running ? c.end : c.start)); });
    const endsNextDay = wall(c.end).day !== wall(c.start).day;
    return h("div", { class: "crow" },
      h("div", { class: "when" }, h("span", { class: "label" }, fmtDate(c.start)), h("span", { class: "mono" }, fmtHM(c.start))),
      h("div", { class: "what" },
        h("div", { class: "title" }, h("a", { href: c.url, target: "_blank", rel: "noopener" }, c.name), c.division ? h("span", { class: "badge" }, c.division) : null,
          c.running ? h("span", { class: "badge good" }, "running") : null),
        h("div", { class: "marks" }, h("span", {}, fmtDur(c.duration)),
          c.recommended ? h("span", { class: "accent" }, "★ suits you") : null,
          (c.clashes || []).map(x => h("span", { class: "warn" }, `⚠ ${x.what} ${x.start}–${x.end}`)),
          c.late ? h("span", { class: "info" }, icon("moon", 12, 2.4), " late night") : endsNextDay ? h("span", { class: "info" }, icon("moon", 12, 2.4), ` ends ${fmtHM(c.end)}`) : null)),
      h("div", { class: "cd" }, cdLabel, cd),
      h("a", { class: "btn btn-sm btn-ghost", href: `/api/contests.ics?t=${encodeURIComponent(TOKEN)}&id=${c.id}`, download: `contest-${c.id}.ics` }, "Add to calendar"));
  });
  root.append(stagger(h("div", { class: "ruled" }, rows)));
  return root;
};
function timersTick(fn) { every(1000, fn); }

// ---- stats ---------------------------------------------------------------------------------

const VERDICTS = {
  WRONG_ANSWER: ["WA", "var(--bad)"], OK: ["OK", "var(--good)"], TIME_LIMIT_EXCEEDED: ["TLE", "var(--warn)"],
  MEMORY_LIMIT_EXCEEDED: ["MLE", "var(--warn)"], RUNTIME_ERROR: ["RE", "var(--warn)"], COMPILATION_ERROR: ["CE", "var(--info)"],
  PARTIAL: ["partial", "var(--muted)"], IDLENESS_LIMIT_EXCEEDED: ["ILE", "var(--warn)"], CHALLENGED: ["hacked", "var(--bad)"],
  SKIPPED: ["skipped", "var(--muted)"],
};

ROUTES.stats = async () => {
  const st = await api("/api/status");
  const hist = st.rating_history || [];
  return h("div", { class: "screen loose" },
    head(`Codeforces · ${st.solved_total} solved · ${plural(st.contests, "rated round")}`, "Stats"),
    h("section", { class: "grid-auto", style: { "--min": "420px", gap: "32px" } },
      h("div", { class: "block" }, h("div", { class: "block-head" }, h("span", { class: "label" }, "Rating"), h("span", { class: "meta" }, plural(hist.length, "rated round"))),
        hist.length ? ratingChart(hist, st.target) : h("p", { class: "muted" }, "No rated rounds yet. Your first Div. 3 or Div. 4 starts the chart.")),
      h("div", { class: "block" }, h("div", { class: "block-head" }, h("span", { class: "label" }, `Weekly solves · goal ${st.week_goal}`),
        h("span", { class: "meta" }, `weeks start ${DAYS[wall(st.week_start).dow] === "Sat" ? "Saturday" : DAYS[wall(st.week_start).dow]}`)),
        weeklyChart((st.weekly || []).slice(-12), st.week_goal))),
    heatmap(st),
    h("section", { class: "grid-auto", style: { "--min": "420px", gap: "32px" } }, verdictBlock(st), byRatingBlock(st)));
};

function ratingChart(hist, target) {
  const max = Math.max(target, ...hist.map(r => r.new));
  const top = Math.ceil((max + 150) / 200) * 200;
  const X0 = 44, X1 = 590, Y0 = 220, Y1 = 20;
  const y = v => Y0 - Math.max(0, v) / top * (Y0 - Y1);
  const n = hist.length;
  const [a, b] = n <= 3 ? [110, 490] : [70, 560];
  const x = i => n === 1 ? (X0 + X1) / 2 : a + i * (b - a) / (n - 1);
  const bands = RANK_BANDS.filter(([lo]) => lo < top).map(([lo, hi, key, name]) => {
    const yt = y(Math.min(hi, top)), yb = y(lo);
    return [s("rect", { x: X0, y: yt, width: X1 - X0, height: yb - yt, fill: `var(--rk-${key})`, opacity: key === "newbie" ? .12 : .15 }),
      yb - yt >= 16 ? s("text", { x: X1 - 6, y: key === "newbie" ? yb - 8 : yt + 16, "text-anchor": "end", "font-size": 11, "font-weight": 600, fill: `var(--rk-${key})` }, name || key) : null];
  });
  const ticks = [0, ...RANK_BANDS.map(([lo]) => lo).filter(v => v > 0 && v <= top)];
  const mid = Math.round(target / 2 / 100) * 100;
  if (ticks.every(t => Math.abs(t - mid) > 150)) ticks.push(mid);
  const every_ = Math.ceil(n / 8);
  return s("svg", { class: "chart", viewBox: "0 0 600 250", role: "img", "aria-label": `Rating ${hist.map(r => r.new).join(", ")} against a ${target} target` },
    bands,
    s("g", { "font-size": 11, fill: "var(--muted)", class: "mono-t" }, ticks.map(t => s("text", { x: X0 - 6, y: y(t) + 4, "text-anchor": "end" }, t))),
    s("line", { x1: X0, y1: y(target), x2: X1, y2: y(target), stroke: "var(--text)", "stroke-width": 1.5, "stroke-dasharray": "6 5" }),
    s("text", { x: X0 + 8, y: y(target) - 6, "font-size": 11, "font-weight": 700, fill: "var(--text)" }, `target ${target}`),
    n > 1 ? s("polyline", { class: "draw", pathLength: 1, points: hist.map((r, i) => `${x(i)},${y(r.new)}`).join(" "), fill: "none", stroke: "var(--text)", "stroke-width": 2.5 }) : null,
    s("g", { stroke: "var(--bg)", "stroke-width": 2 }, hist.map((r, i) => s("rect", { x: x(i) - 5, y: y(r.new) - 5, width: 10, height: 10, fill: rkVar(r.new) },
      s("title", {}, `${r.contest_name}: ${r.old} → ${r.new} (${r.delta >= 0 ? "+" : ""}${r.delta}), rank ${r.rank}`)))),
    s("g", { "font-size": 12, "font-weight": 700, fill: "var(--text)", class: "mono-t" }, hist.map((r, i) => n <= 12 || i % every_ === 0 || i === n - 1 ? s("text", { x: x(i), y: y(r.new) - 13, "text-anchor": "middle" }, r.new) : null)),
    s("g", { "font-size": 11, fill: "var(--muted)" }, hist.map((r, i) => i % every_ === 0 || i === n - 1 ? s("text", { x: x(i), y: 240, "text-anchor": "middle" }, fmtDM(tsIso(r.time))) : null)));
}

function weeklyChart(weeks, goal) {
  if (!weeks.length) return h("p", { class: "muted" }, "No solves yet.");
  const max = Math.max(goal * 2, ...weeks.map(w => w.solved));
  const top = Math.ceil(max / 10) * 10;
  const y = v => 220 - v / top * 200;
  let lastMonth = null;
  return s("svg", { class: "chart", viewBox: "0 0 600 250", role: "img", "aria-label": `Weekly solves for ${weeks.length} weeks against a goal of ${goal}` },
    s("g", { "font-size": 11, fill: "var(--muted)", class: "mono-t" }, [0, top / 2, top].map(t => s("text", { x: 30, y: y(t) + 4, "text-anchor": "end" }, t))),
    s("line", { x1: 36, y1: 220, x2: 596, y2: 220, stroke: "var(--rule)", "stroke-width": 2 }),
    weeks.map((w, i) => {
      const bx = 44 + i * 46, v = w.solved, wd = wall(w.week);
      const label = lastMonth === wd.m ? String(wd.d) : `${wd.d} ${MONTHS[wd.m - 1]}`;
      lastMonth = wd.m;
      return [
        v ? s("rect", { class: "grow-y", style: { "--i": String(i) }, x: bx, y: y(v), width: 34, height: 220 - y(v), fill: v >= goal ? "var(--text)" : "var(--muted)" },
          s("title", {}, `week of ${fmtDate(w.week)}: ${v} solved`)) : null,
        v ? s("text", { x: bx + 17, y: y(v) - 6, "text-anchor": "middle", "font-size": 11, "font-weight": 700, fill: "var(--text)", class: "mono-t" }, v) : null,
        s("text", { x: bx + 17, y: 240, "text-anchor": "middle", "font-size": 10, fill: "var(--muted)" }, label)];
    }),
    s("line", { x1: 36, y1: y(goal), x2: 596, y2: y(goal), stroke: "var(--accent)", "stroke-width": 2, "stroke-dasharray": "6 5" }),
    s("text", { x: 594, y: y(goal) - 6, "text-anchor": "end", "font-size": 11, "font-weight": 700, fill: "var(--accent-ink)" }, `goal ${goal}`));
}

function heatmap(st) {
  const days = st.heatmap || [];
  const weekStartDow = wall(st.week_start).dow;
  const padN = days.length ? (wall(days[0].date).dow - weekStartDow + 7) % 7 : 0;
  const cells = [...Array.from({ length: padN }, () => null), ...days];
  const level = v => v === 0 ? 0 : v < 2 ? 1 : v < 4 ? 2 : v < 7 ? 3 : 4;
  const cols = Math.ceil(cells.length / 7);
  const months = [];
  let prev = null;
  for (let c = 0; c < cols; c++) {
    const first = cells.slice(c * 7, c * 7 + 7).find(Boolean);
    if (!first) continue;
    const m = wall(first.date).m;
    if (m !== prev && (prev !== null || c === 0)) months.push([c, MONTHS[m - 1]]);
    prev = m;
  }
  const total = days.reduce((a, d) => a + d.solved, 0);
  const active = days.filter(d => d.solved).length;
  return h("section", { class: "block" },
    h("div", { class: "block-head" }, h("span", { class: "label" }, `Activity · ${Math.round(days.length / 7)} weeks · ${total} solved on ${plural(active, "day")}`),
      h("span", { class: "heat-legend" }, "less", [0, 1, 2, 3, 4].map(l => h("span", { style: { background: `var(--hm-${l})` } })), "more")),
    h("div", { class: "heat-wrap" },
      h("div", { class: "heat" }, cells.map(d => d ? h("span", { class: `l${level(d.solved)}`, title: `${fmtDate(d.date)} · ${plural(d.solved, "solve")}` }) : h("span", { class: "future" }))),
      h("div", { class: "heat-months", style: { marginTop: "8px" } }, months.map(([c, label]) => h("span", { style: { gridColumn: `${c + 1} / span 4`, gridRow: "1" } }, label)))));
}

function verdictBlock(st) {
  const rows = Object.entries(st.verdicts || {}).map(([k, n]) => [...(VERDICTS[k] || [k.toLowerCase().replace(/_/g, " "), "var(--muted)"]), n])
    .sort((a, b) => b[2] - a[2]);
  const total = rows.reduce((a, r) => a + r[2], 0);
  return h("div", { class: "block", style: { gap: "14px" } },
    h("span", { class: "label" }, `Verdicts · ${total} submissions`),
    h("div", { class: "vbar" }, rows.map(([k, c, n]) => h("span", { title: `${k} ${n}`, style: { "--c": c, flex: String(n) } }))),
    h("div", { class: "vgrid" }, rows.map(([k, c, n]) => h("div", {}, h("span", { class: "verdict", style: { "--c": c } }, k), h("span", { class: "n" }, n)))),
    h("div", { class: "kpis" },
      h("div", {}, h("div", { class: "mono" }, st.wa_per_ac === null || st.wa_per_ac === undefined ? "—" : st.wa_per_ac.toFixed(2)), h("div", { class: "muted" }, "WA per AC")),
      h("div", {}, h("div", { class: "mono" }, pct(st.first_try_rate)), h("div", { class: "muted" }, "accepted on first try"))));
}

function byRatingBlock(st) {
  const counts = Object.fromEntries(Object.entries(st.by_rating || {}).map(([k, v]) => [Number(k), v]));
  const keys = Object.keys(counts).map(Number);
  const block = h("div", { class: "block" }, h("span", { class: "label" }, "Solves by problem rating"));
  if (!keys.length) { block.append(h("p", { class: "muted" }, "No rated problemset solves yet.")); return block; }
  const lo = Math.min(...keys), hi = Math.max(...keys, Math.min(st.target, lo + 800));
  const cols = [];
  for (let r = lo; r <= hi; r += 100) cols.push([r, counts[r] || 0]);
  const max = Math.max(...cols.map(c => c[1]));
  const W = Math.max(420, 12 + cols.length * 46);
  const hgt = v => v ? Math.max(3, v / max * 140) : 0;
  block.append(s("svg", { class: "chart", viewBox: `0 0 ${W} 200`, role: "img", "aria-label": "Solves by problem rating" },
    s("line", { x1: 0, y1: 170, x2: W, y2: 170, stroke: "var(--rule)", "stroke-width": 2 }),
    cols.map(([r, v], i) => [
      v ? s("rect", { class: "grow-y", style: { "--i": String(i) }, x: 6 + i * 46, y: 170 - hgt(v), width: 34, height: hgt(v), fill: rkVar(r) }, s("title", {}, `${r}: ${v} solved`)) : null,
      v ? s("text", { x: 23 + i * 46, y: 164 - hgt(v), "text-anchor": "middle", "font-size": 12, "font-weight": 700, fill: "var(--text)", class: "mono-t" }, v) : null,
      s("text", { x: 23 + i * 46, y: 188, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)", class: "mono-t" }, r)])));
  const total = cols.reduce((a, c) => a + c[1], 0);
  const lowest = cols[0];
  const comfort = st.comfort || lo;
  block.append(h("div", { class: "note" }, lowest[1] > total / 2
    ? `${lowest[1]} of ${total} rated solves are ${lowest[0]}s. The jump to ${st.target} lives in the ${Math.max(lo + 100, comfort)}–${st.target - 100} columns.`
    : `Comfort rating ${comfort}: the 75th percentile of what you solved in the last 90 days.`));
  return block;
}

// ---- judge ---------------------------------------------------------------------------------

const LANG = { cpp: "C++", cc: "C++", cxx: "C++", c: "C", java: "Java", py: "Python" };
const VERDICT_C = { AC: "var(--good)", WA: "var(--bad)", TLE: "var(--warn)", RE: "var(--warn)", RAN: "var(--info)", BRUTE: "var(--warn)", CE: "var(--info)" };
const VERDICT_NAME = { WA: "wrong answer", TLE: "time limit exceeded", RE: "runtime error", AC: "accepted", RAN: "ran" };

ROUTES.judge = async () => {
  const data = await api("/api/files");
  const S = {
    files: data.files, editor: data.editor, root: data.root,
    sel: sessionStorage.getItem("dojo.judgeFile") || (data.files[0] && data.files[0].path) || null,
    debug: store("judgeDebug") === "1", n: Number(store("stressN")) || 300, customOn: false, custom: "", java: false, run: null, busy: false,
  };
  const left = h("div", { class: "judge-left" });
  const right = h("div", { class: "judge-right" });
  const out = h("div", { class: "out" });
  const file = () => S.files.find(f => f.path === S.sel) || (S.sel ? { path: S.sel, name: S.sel.split("/").pop(), samples: null } : null);

  async function reloadFiles(select) {
    const d = await api("/api/files");
    S.files = d.files;
    if (select) S.sel = select;
    paintLeft(); paintRight();
  }
  function paintLeft() {
    const idIn = h("input", { class: "input", id: "newpid", placeholder: "2254B", autocomplete: "off", spellcheck: "false" });
    const create = h("button", { class: "btn btn-primary", type: "button", onclick: e => busy(e.currentTarget, async () => {
      const id = idIn.value.trim();
      if (!id) throw new Error("Type a problem id like 2254B, or paste its link");
      const r = await createFile(id, S.java);
      idIn.value = "";
      await reloadFiles(r.path || S.sel);
    }) }, "Create");
    idIn.addEventListener("keydown", e => { if (e.key === "Enter") create.click(); });
    const helper = f => /^(brute|gen)\.|_(brute|gen)\.\w+$/.test(f.name);
    const shown = S.files.filter(f => !helper(f)).slice(0, 8);
    if (S.sel && !shown.some(f => f.path === S.sel)) { const f = file(); if (f) shown.unshift(f); }
    fill(left,
      h("div", { class: "judge-new" },
        h("label", { class: "label", for: "newpid" }, "New solution"),
        h("div", { class: "row" }, idIn, create),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.java, onchange: e => { S.java = e.target.checked; } }), "Java")),
      h("div", { class: "label-s" }, "Recent files"),
      shown.length ? shown.map(f => h("button", { class: "file", type: "button", "aria-current": String(f.path === S.sel),
        onclick: () => { S.sel = f.path; S.run = null; sessionStorage.setItem("dojo.judgeFile", f.path); paintLeft(); paintRight(); } },
      h("span", { class: "fname" }, f.name),
      h("span", { class: "muted" }, [LANG[f.name.split(".").pop()] || "file", f.mtime ? `edited ${ago(f.mtime)}` : null,
        f.samples ? plural(f.samples, "sample") : f.samples === 0 ? "no samples" : null].filter(Boolean).join(" · "))))
        : h("p", { class: "muted", style: { padding: "10px 0", fontSize: "14px" } }, `No solution files in ${tilde(S.root)} yet. Create one above.`));
  }
  function paintRight() {
    const f = file();
    if (!f) {
      right.replaceChildren(h("div", { class: "out" }, h("div", { class: "out-body" }, h("div", { class: "out-text muted" }, "Pick a solution on the left, or create one from a problem id."))));
      return;
    }
    const runBtn = h("button", { class: "btn btn-primary", type: "button", disabled: S.busy, onclick: () => run("test") }, playIcon(), "Run tests");
    const nIn = h("input", { type: "number", min: "1", max: "100000", value: String(S.n), "aria-label": "Stress test count",
      onchange: e => { S.n = Math.max(1, Math.min(100000, Number(e.target.value) || 300)); store("stressN", String(S.n)); } });
    const custom = h("textarea", { class: "textarea", rows: "4", placeholder: "1\nAABBA", value: S.custom, spellcheck: "false",
      oninput: e => { S.custom = e.target.value; } });
    right.replaceChildren(
      h("div", { class: "judge-file" }, h("span", { class: "fname" }, f.name),
        h("span", { class: "muted" }, `${tilde(f.path)}${f.samples !== null && f.samples !== undefined ? ` · ${plural(f.samples, "saved sample")}` : ""}`)),
      h("div", { class: "judge-tools" },
        runBtn,
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.debug, onchange: e => { S.debug = e.target.checked; store("judgeDebug", S.debug ? "1" : "0"); } }), "debug build"),
        h("div", { class: "stress-group" }, h("button", { class: "btn", type: "button", disabled: S.busy, onclick: () => run("stress") }, "Stress"), h("label", {}, "n=", nIn)),
        h("button", { class: "btn", type: "button", onclick: e => busy(e.currentTarget, async () => {
          const r = await api("/api/judge", { action: "init", file: f.path });
          if (r.code !== 0) throw new Error(lastLine(r.output));
          const done = r.output.split("\n").map(l => l.trim()).filter(l => /^(wrote|kept)\b/.test(l)).map(l => l.replace(/\s{2,}.*/, ""));
          toast(`${done.join(" · ") || "brute + gen ready"} · fill them in, then Stress`);
        }) }, "Create brute + gen"),
        h("button", { class: "btn btn-ghost", type: "button", onclick: e => busy(e.currentTarget, async () => {
          await api("/api/open", { file: f.path });
          toast(`Opened ${f.name} in ${S.editor || "your editor"}`);
        }) }, "Open in editor")),
      h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
        h("button", { class: "toggle-link", type: "button", "aria-expanded": String(S.customOn), onclick: () => { S.customOn = !S.customOn; paintRight(); } },
          h("span", { class: "mono" }, S.customOn ? "−" : "+"), "Custom input"),
        S.customOn ? custom : null),
      out);
    paintOut();
  }
  function paintOut() {
    const f = file();
    const R = S.run;
    let status, body = [];
    if (!R) {
      status = ["var(--muted)", "idle", ""];
      body.push(h("div", { class: "out-text muted" }, "No run yet. ", h("strong", { style: { color: "var(--text)" } }, "Run tests"),
        f && f.samples === 0 ? " runs your custom input (this file has no CPH samples); " : " compiles and checks the saved samples; ",
        h("strong", { style: { color: "var(--text)" } }, "Stress"), " compares against a brute force on random inputs."));
    } else {
      body.push(h("div", { class: "out-cmd" }, `$ ${R.command}`));
      if (R.phase === "running") {
        status = R.action === "stress" ? ["var(--warn)", "stress", `${S.n} random tests · comparing with the brute force`] : ["var(--warn)", "compiling and running…", S.debug ? "debug build" : ""];
      } else if (R.phase === "error") {
        status = ["var(--bad)", "couldn't run", ""];
        body.push(h("div", { class: "out-text" }, rich(R.error)));
      } else if (R.result.error) {
        status = ["var(--bad)", R.result.stage === "build" ? "compile error" : "error", R.result.file || ""];
        body.push(h("pre", { class: "err-pre" }, R.result.error));
      } else if (R.action === "test") {
        [status, body] = testOutput(R, body);
      } else {
        [status, body] = stressOutput(R, body);
      }
    }
    const [c, title, sub] = status;
    out.replaceChildren(
      h("div", { class: "out-status" + (R && R.phase === "running" ? " running" : ""), style: { "--c": c } }, h("span", { class: "sq" }), h("strong", {}, title), sub ? h("span", { class: "muted" }, sub) : null),
      h("div", { class: "out-body" + (R && R.phase === "done" ? " pop" : "") }, body));
  }
  async function run(action) {
    const f = file();
    if (!f || S.busy) return;
    const base = f.name;
    S.busy = true;
    S.run = { action, phase: "running", command: action === "test" ? `dojo test ${base}${S.customOn && S.custom.trim() ? " < input" : ""}${S.debug ? " --debug" : ""}` : `dojo stress ${base} -n ${S.n}${S.debug ? " --debug" : ""}` };
    paintRight();
    try {
      const r = await api("/api/judge", { action, file: f.path, debug: S.debug, n: S.n, input: action === "test" && S.customOn ? S.custom : "" });
      S.run = { action, phase: "done", command: r.command, result: r.result, seconds: r.seconds };
    } catch (e) {
      S.run = { ...S.run, phase: "error", error: e.message };
    }
    S.busy = false;
    paintRight();
  }

  paintLeft(); paintRight();
  return h("div", { class: "screen tight" }, head("Code", "Judge"), h("div", { class: "judge" }, left, right));
};

function ioBox(title, text, cls = "") {
  return h("div", { class: cls }, h("div", { class: "label-s" }, title), h("pre", {}, text === null || text === undefined || text === "" ? "(empty)" : String(text).replace(/\n$/, "")));
}
function testOutput(R, body) {
  const res = R.result, tests = res.tests || [];
  const failed = tests.filter(t => ["WA", "RE", "TLE"].includes(t.verdict));
  let status;
  if (failed.length) {
    const f = failed[0];
    status = ["var(--bad)", `${failed.length} of ${tests.length} failed`, `${sampleLabel(f.label)} · ${VERDICT_NAME[f.verdict] || f.verdict}`];
  } else if (res.judged) {
    status = ["var(--good)", `${res.judged}/${res.judged} passed`, `slowest ${ms(res.slowest)} of ${res.tl} s`];
  } else {
    status = ["var(--info)", "ran", "no expected output to compare against"];
  }
  for (const w of (res.warnings || []).slice(0, 4)) body.push(h("div", { class: "warn", style: { whiteSpace: "pre-wrap", padding: "2px 0" } }, w));
  tests.forEach((t, i) => {
    const c = VERDICT_C[t.verdict] || "var(--muted)";
    const extra = [];
    if (t.verdict === "WA") {
      if (t.message) extra.push(h("div", { class: "out-text", style: { padding: "8px 0 0", color: "var(--bad)" } }, t.message));
      extra.push(h("div", { class: "diff" }, ioBox("Input", t.input), ioBox("Expected", t.expected), ioBox("Got", t.got, "bad-box")));
    } else if (t.verdict === "RE" || t.verdict === "TLE") {
      extra.push(h("div", { class: "diff" }, ioBox("Input", t.input), t.stderr ? ioBox("stderr", t.stderr, "bad-box") : ioBox("Output so far", t.got)));
      if (t.message) extra.push(h("div", { class: "out-text muted", style: { padding: "6px 0 0" } }, t.message));
    } else if (t.verdict === "RAN") {
      extra.push(h("div", { class: "diff" }, ioBox("Input", t.input), ioBox("Output", t.got)));
      if (t.stderr) extra.push(h("div", { class: "diff" }, ioBox("stderr", t.stderr)));
    }
    body.push(h("div", { class: "tcase" },
      h("div", { class: "tcase-head" }, h("span", { class: "muted" }, `#${i + 1}`), h("span", { class: "verdict", style: { "--c": c } }, t.verdict),
        h("span", { class: "lbl" }, sampleLabel(t.label)), h("span", { class: "ms" }, t.verdict === "TLE" ? `>${res.tl} s` : ms(t.seconds))),
      extra));
  });
  if (!failed.length && res.judged) body.push(h("div", { class: "out-text muted" }, "Samples are the easy cases. Before submitting, press Stress."));
  if (failed.some(t => t.verdict === "RE") && !res.debug && res.lang === "cpp") body.push(h("div", { class: "out-text muted" }, "Crash? Tick debug build and run again: it names the line that went out of bounds."));
  return [status, body];
}
function sampleLabel(label) { const m = /^#(\d+)$/.exec(label || ""); return m ? `sample ${m[1]}` : label; }
function stressOutput(R, body) {
  const r = R.result;
  let status;
  if (r.ok) {
    status = ["var(--good)", "stress passed", `${r.iterations} / ${r.n}`];
    body.push(h("div", { class: "out-text" }, `${r.iterations} random tests, no mismatch against ${r.brute}. Your slowest run ${ms(r.max_seconds)}, the brute force's ${ms(r.brute_max_seconds)}.`));
    if (r.distinct === 1 && r.iterations > 1) body.push(h("div", { class: "out-text warn" }, "Every test was the same: make the generator use its seed (seed_from_argv() from dojo.gen, or argv[1])."));
    else body.push(h("div", { class: "out-text muted" }, "Still WA on Codeforces? Widen the generator (n = 1, equal values, max values) and stress again."));
  } else {
    const brute = r.verdict === "BRUTE";
    status = ["var(--bad)", brute ? "the brute force failed" : "stress found a mismatch", `test ${r.iterations} · seed ${r.seed}`];
    body.push(h("div", { class: "out-text" }, brute ? `The brute force failed on random test ${r.iterations}. Fix ${r.brute} first.`
      : [`${VERDICT_NAME[r.verdict] ? cap(VERDICT_NAME[r.verdict]) : "Mismatch"} on random test `, h("strong", {}, r.iterations), ` of ${r.n}${r.reason ? ": " + r.reason : "."}`]));
    body.push(h("div", { class: "diff" }, ioBox("Input", r.input),
      brute ? ioBox(`stderr (${r.brute})`, r.stderr, "bad-box") : [ioBox("Your output", r.got, "bad-box"), ioBox("Brute force", r.expected, "good-box")]));
    if (!brute && r.stderr) body.push(h("div", { class: "diff" }, ioBox("stderr", r.stderr, "bad-box")));
    if (r.saved) body.push(h("div", { class: "out-text muted" }, `Saved to ${tilde(r.saved)} (with fail.out and fail.ans) so you can trace it by hand.`));
  }
  return [status, body];
}

// ---- drills --------------------------------------------------------------------------------

function drillPrefs() {
  return { level: Number(store("drillLevel")) || 2, count: Number(store("drillCount")) || 5 };
}

ROUTES.drill = async rest => (rest[0] ? drillSession(rest[0]) : drillTopics());

async function drillTopics() {
  const data = await api("/api/drill/topics");
  const prefs = drillPrefs();
  const courses = Object.keys(data.courses);
  const root = h("div", { class: "screen" },
    head(`Courses · ${plural(data.topics.length, "topic")}`, "Drills", {
      tools: [
        h("div", { class: "head-tools", style: { gap: "8px" } }, h("span", { class: "muted", style: { fontSize: "13px" } }, "Level"),
          seg([[1, "1"], [2, "2"], [3, "3"]], prefs.level, v => { store("drillLevel", String(v)); route(true); }, "Level")),
        h("div", { class: "head-tools", style: { gap: "8px" } }, h("span", { class: "muted", style: { fontSize: "13px" } }, "Questions"),
          seg([[5, "5"], [10, "10"], [20, "20"]], prefs.count, v => { store("drillCount", String(v)); route(true); }, "Question count")),
        h("a", { class: "btn btn-primary", href: "#/drill/mix", style: { minWidth: "150px" } }, "Mix all topics")],
    }));
  for (const code of courses) {
    const topics = data.topics.filter(t => t.course === code);
    if (!topics.length) continue;
    root.append(h("section", { class: "ruled" },
      h("div", { class: "course-head" }, h("span", { class: "mono" }, code), h("h2", {}, data.courses[code]),
        h("a", { class: "btn btn-sm btn-ghost", href: `#/drill/${topics.map(t => t.key).join(",")}`, style: { marginLeft: "auto" } }, `Mix ${code}`)),
      stagger(h("div", { class: "topics" }, topics.map(t => {
        const acc = t.recent_accuracy !== null && t.recent_accuracy !== undefined ? t.recent_accuracy : t.attempts ? t.correct / t.attempts : null;
        return h("a", { class: "topic" + (data.suggest && data.suggest.key === t.key ? " suggested" : ""), href: `#/drill/${t.key}`, title: t.summary },
          h("strong", {}, t.title),
          h("span", { class: "sum" }, t.summary),
          h("span", { class: "foot" }, h("span", {}, "accuracy ", h("span", { class: "mono" }, pct(acc))), h("span", {}, t.last_ts ? ago(t.last_ts) : "never")));
      })))));
  }
  return root;
}

// A prompt is lead text, an indented block (data, an expression) and the question after it.
function splitPrompt(text) {
  const before = [], block = [], after = [];
  for (const ln of String(text).split("\n")) {
    if (!ln.trim()) continue;
    if (/^\s/.test(ln) && !after.length) block.push(ln);
    else if (block.length) after.push(ln.trim());
    else before.push(ln.trim());
  }
  if (!block.length && before.length === 1) {
    const m = before[0].match(/^(.*?\b(?:for|of))\s+(F\(.+)$/);
    if (m) return { lead: [m[1]], box: m[2], after: [] };
  }
  return { lead: before, box: block.length ? dedent(block) : "", after };
}
function promptView(text) {
  const p = splitPrompt(text);
  const wide = p.box.split("\n").length > 3 || p.box.split("\n").some(l => l.length > 44);
  return h("div", { class: "q-stack" },
    p.lead.map(l => h("div", { class: "q-text" }, l)),
    p.box ? h("div", { class: "q-expr" + (wide ? " wide" : "") }, p.box) : null,
    p.after.map(l => h("div", { class: "q-text" }, l)));
}
function promptSummary(text) {
  const p = splitPrompt(text);
  return (p.box && p.box.split("\n").length === 1 ? p.box : [...p.lead, ...p.after].join(" ")) || String(text).split("\n")[0];
}
// Worked solutions: an unindented line opens a step, the indented lines under it are its table.
function parseSteps(text) {
  const steps = [];
  let cur = null;
  for (const ln of String(text || "").split("\n")) {
    if (!ln.trim()) continue;
    if (/^\s/.test(ln)) {
      if (!cur) steps.push(cur = { say: [], body: [] });
      cur.body.push(ln);
    } else {
      if (!cur || cur.body.length) steps.push(cur = { say: [], body: [] });
      cur.say.push(ln);
    }
  }
  return steps.map(st => ({ say: st.say, body: st.body.length ? dedent(st.body) : "" }));
}
function stepsView(text, answer, topic) {
  const steps = parseSteps(text);
  const shown = answer === undefined || answer === null ? null
    : topic === "kmap" || topic === "simplify" ? `F = ${answer}` : topic === "minterms" ? `F = Σm(${answer})` : String(answer);
  return h("div", { class: "steps" }, steps.map((st, i) => h("div", { class: "step" },
    h("span", { class: "n" }, pad(i + 1)),
    h("div", { class: "inner" },
      st.body ? [h("strong", {}, rich(st.say[0] || "")), st.say.slice(1).map(l => h("span", { class: "say muted" }, rich(l)))] : st.say.map(l => h("span", { class: "say" }, rich(l))),
      st.body ? h("pre", {}, st.body) : null))),
  shown ? h("div", { class: "final" }, h("span", { class: "sq" }), h("div", {}, shown)) : null);
}
const ANSWER_HELP = {
  kmap: ["Use ' for NOT and + between terms. Term order doesn't matter."],
  simplify: ["Use ' for NOT and + between terms. Term order doesn't matter."],
  minterms: ["Minterm numbers, separated by spaces or commas."],
};

async function drillSession(spec) {
  const keys = spec === "mix" ? [] : spec.split(",").filter(Boolean);
  const { level, count } = drillPrefs();
  const topicsData = await api("/api/drill/topics");
  const byKey = Object.fromEntries(topicsData.topics.map(t => [t.key, t]));
  const S = { i: 0, results: [], q: null, phase: "ask", hint: null, retry: null, input: "", verdict: null, after: null };
  const root = h("div", { class: "screen drill" });
  let inputEl = null;

  async function load() {
    S.q = await api("/api/drill/next", { topics: keys, level, seed: Math.floor(Math.random() * 1e9) });
    Object.assign(S, { phase: "ask", hint: null, retry: null, input: "", verdict: null });
  }
  async function answer(text) {
    const r = await api("/api/drill/answer", { id: S.q.id, answer: text });
    if (r.kind === "hint") { S.hint = r.hint; return; }
    if (r.kind === "retry") { S.retry = r.message + (r.expect ? ` · expected: ${r.expect}` : ""); return; }
    S.verdict = r;
    S.phase = "answered";
    S.results.push({ ok: r.ok, revealed: r.revealed, hint: !!S.hint, summary: promptSummary(S.q.prompt), topic: S.q.topic });
  }
  async function submit(btn) {
    if (S.phase !== "ask") return;
    if (!S.input.trim()) { S.retry = "Type an answer first."; paint(); return; }
    await busy(btn, async () => { await answer(S.input); paint(true); });
  }
  async function next(btn) {
    if (S.i + 1 >= count) {
      S.phase = "summary";
      S.after = await settle(api("/api/drill/topics"));
      paint(true);
      return;
    }
    await busy(btn, async () => { S.i++; await load(); paint(true); });
  }

  function paint(fresh = false) {
    const q = S.q, t = byKey[q.topic] || {};
    const segs = h("div", { class: "segs", style: { "--n": String(count) } }, Array.from({ length: count }, (_, i) => {
      const r = S.results[i];
      return h("span", { class: r ? (r.ok ? "good" : "bad") : i === S.i && S.phase !== "summary" ? "cur" : "" });
    }));
    const meta = h("div", { class: "drill-meta" },
      h("div", { class: "mono" }, S.phase === "summary" ? `${keys.length === 1 ? (t.title || q.title) : "mixed topics"} · level ${level} · ${count} questions`
        : `${q.course} · ${q.title} · level ${q.level} · question ${S.i + 1} of ${count}`),
      h("a", { class: "btn btn-sm btn-ghost", href: "#/drill" }, S.phase === "summary" ? "All topics" : "End session"));
    if (S.phase === "summary") { root.replaceChildren(meta, segs, summary()); return; }

    const [lab, example] = String(q.expect || "answer").split(/, e\.g\.\s*/);
    inputEl = h("input", { class: "input input-xl", id: "drill-answer", value: S.input, autocomplete: "off", spellcheck: "false", placeholder: example || "",
      readonly: S.phase === "answered", "aria-describedby": "drill-help",
      oninput: e => { S.input = e.target.value; if (S.retry) { S.retry = null; retryEl.replaceChildren(); } },
      onkeydown: e => { if (e.key === "Enter") { e.preventDefault(); S.phase === "ask" ? submit(submitBtn) : next(nextBtn); } } });
    const retryEl = h("div", { class: "retry-msg", role: "alert" }, S.retry || "");
    let submitBtn = null, nextBtn = null;
    const parts = [
      promptView(q.prompt),
      h("div", { class: "field" },
        h("label", { class: "label", for: "drill-answer" }, `Your answer · ${lab}`),
        inputEl,
        ANSWER_HELP[q.topic] ? h("div", { class: "note", id: "drill-help" }, ANSWER_HELP[q.topic]) : null,
        retryEl),
      S.hint && S.phase === "ask" ? h("div", { class: "callout", style: { "--c": "var(--info)" } }, h("strong", {}, "Hint"), h("span", {}, rich(S.hint))) : null,
    ];
    if (S.phase === "ask") {
      submitBtn = h("button", { class: "btn btn-primary btn-lg btn-wide", type: "button", onclick: e => submit(e.currentTarget) }, "Submit", h("span", { class: "kbd" }, "↵ Enter"));
      parts.push(h("div", { class: "btn-row" }, submitBtn,
        q.has_hint && !S.hint ? h("button", { class: "btn btn-lg", type: "button", onclick: e => busy(e.currentTarget, async () => { await answer("?"); paint(); }) }, "Hint") : null,
        h("button", { class: "btn btn-ghost btn-lg", type: "button", onclick: e => busy(e.currentTarget, async () => { await answer("!"); paint(true); }) },
          "Show solution ", h("span", { class: "muted", style: { fontWeight: "400" } }, "· counts as wrong"))));
    } else {
      const v = S.verdict, last = S.results[S.results.length - 1];
      const c = v.ok ? "var(--good)" : "var(--bad)";
      inputEl.style.borderColor = c;
      const title = v.ok ? "Correct" : v.revealed ? "Solution shown" : "Not quite";
      const sub = v.ok ? (last.hint ? "With a hint · counted as correct" : v.message || "Right answer")
        : v.revealed ? "Counted as wrong · read the steps, then try the next one cold"
          : `You wrote ${S.input.trim()}${v.message ? " · " + v.message : ""}`;
      nextBtn = h("button", { class: "btn btn-primary btn-lg btn-wide", type: "button", onclick: e => next(e.currentTarget) },
        S.i + 1 >= count ? "See results" : "Next question", h("span", { class: "kbd" }, "↵"));
      parts.push(h("div", { class: "pop", style: { display: "flex", flexDirection: "column", gap: "22px" } },
        h("div", { class: "verdict-bar", style: { "--c": c } }, h("span", { class: "vmark" }, v.ok ? "✓" : "×"),
          h("div", { class: "what" }, h("strong", {}, title), h("span", { class: "muted" }, sub)), nextBtn),
        h("div", { class: "steps" }, h("div", { class: "label" }, "Worked solution"), stepsView(v.solution, v.answer, q.topic))));
    }
    root.replaceChildren(meta, segs, h("div", { class: "drill-body" + (fresh ? " pop" : "") }, parts));
    requestAnimationFrame(() => inputEl && inputEl.focus({ preventScroll: S.phase === "answered" }));
  }

  function summary() {
    const score = S.results.filter(r => r.ok).length;
    let note = score === count ? "Clean sheet." : "Topics you miss come up first in the next suggestion.";
    if (keys.length === 1 && S.after) {
      const t = S.after.topics.find(x => x.key === keys[0]);
      if (t && t.recent_accuracy !== null && t.recent_accuracy !== undefined) note = `${t.title} accuracy now ${pct(t.recent_accuracy)} · ${note}`;
    }
    return h("div", { class: "drill-body pop" },
      h("div", { class: "label" }, "Session complete"),
      h("div", { class: "score" }, h("span", { class: "n" }, score), h("span", { class: "of" }, `/ ${count}`), h("span", { class: "muted" }, note)),
      h("div", { class: "row-rule" }, S.results.map((r, i) => h("div", { class: "sum-row" },
        h("span", { class: "vmark vmark-s", style: { "--c": r.ok ? "var(--good)" : "var(--bad)" } }, r.ok ? "✓" : "×"),
        h("span", { class: "mono muted" }, pad(i + 1)),
        h("span", { class: "expr", title: r.summary }, r.summary),
        h("span", { class: "how" }, r.ok ? (r.hint ? "with hint" : "correct") : r.revealed ? "solution shown" : "wrong")))),
      h("div", { class: "btn-row" },
        h("button", { class: "btn btn-primary btn-lg", type: "button", style: { minWidth: "180px" }, onclick: () => route() }, "Practise again"),
        h("a", { class: "btn btn-lg", href: "#/drill" }, "Pick another topic")));
  }

  // Enter moves on from an answered question wherever the focus is (the answer box re-renders).
  const onKey = e => {
    if (!root.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (e.key !== "Enter" || S.phase !== "answered" || e.target === inputEl || /^(BUTTON|A|TEXTAREA)$/.test(e.target.tagName)) return;
    e.preventDefault();
    next(root.querySelector(".verdict-bar .btn-primary"));
  };
  document.addEventListener("keydown", onKey);

  await load();
  paint();
  return root;
}

// ---- solve ---------------------------------------------------------------------------------

// The first format in a topic's usage line, as a ready-to-edit problem: quotes, [optional] parts
// and "…" dropped, "a|b" choices narrowed to a.
function usageExample(usage) {
  let first = String(usage || "").split(" · ")[0].trim();
  const q = first[0];
  if (q === "'" || q === '"') {
    const end = first.indexOf(q, 1);
    if (end > 0) first = first.slice(1, end) + first.slice(end + 1);
  }
  return first.replace(/\s*\[[^\]]*\]/g, "").replace(/\s*…/g, "").replace(/(\w+)\|[\w|]+/g, "$1").trim();
}

ROUTES.solve = async () => {
  const data = await api("/api/drill/topics");
  const topics = data.topics.filter(t => t.solve_usage);
  const S = { topic: topics.some(t => t.key === store("solveTopic")) ? store("solveTopic") : (topics.find(t => t.key === "kmap") || topics[0]).key,
    mode: "solve", text: null, check: "", result: null, err: null };
  const root = h("div", { class: "screen solve" });

  async function go(btn) {
    const text = S.text ?? usageExample(cur().solve_usage);
    if (S.mode === "check" && !S.check.trim()) { toast("Type your answer in the My answer box first", "err"); return; }
    await busy(btn, async () => {
      S.result = await api("/api/solve", { topic: S.topic, text, check: S.mode === "check" ? S.check : null });
      paint(true);
    });
  }
  const cur = () => topics.find(t => t.key === S.topic);

  function paint(fresh = false) {
    const t = cur();
    const select = h("select", { class: "select", "aria-label": "Topic", value: S.topic, onchange: e => { S.topic = e.target.value; store("solveTopic", S.topic); S.text = null; S.result = null; S.check = ""; paint(); } },
      Object.keys(data.courses).map(code => h("optgroup", { label: `${code} · ${data.courses[code]}` },
        topics.filter(x => x.course === code).map(x => h("option", { value: x.key }, x.title)))));
    const goBtn = h("button", { class: "btn btn-primary btn-lg btn-wide", type: "button", style: { alignSelf: "flex-start", minWidth: "200px", marginTop: "4px" }, onclick: e => go(e.currentTarget) },
      S.mode === "check" ? "Check" : "Solve", h("span", { class: "kbd" }, "Ctrl ↵"));
    const keys = e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey || e.target.tagName === "INPUT")) { e.preventDefault(); go(goBtn); } };
    const textarea = h("textarea", { class: "textarea textarea-l", id: "solve-in", rows: "3", spellcheck: "false", value: S.text ?? usageExample(t.solve_usage),
      oninput: e => { S.text = e.target.value; }, onkeydown: keys });
    const usage = String(t.solve_usage).split(" · ");
    const out = [];
    if (S.result && S.mode === "check" && S.result.verdict) {
      const v = S.result.verdict;
      if (v.retry) out.push(h("div", { class: "callout pop", style: { "--c": "var(--warn)" } }, h("strong", {}, "Couldn't read that"), h("span", {}, `${v.message}${v.expect ? " · expected: " + v.expect : ""}`)));
      else out.push(h("div", { class: "verdict-bar pop", style: { "--c": v.ok ? "var(--good)" : "var(--bad)" } }, h("span", { class: "vmark" }, v.ok ? "✓" : "×"),
        h("div", { class: "what" }, h("strong", {}, v.ok ? "Right." : "Not right. Switch to step by step to see why."), v.message ? h("span", { class: "muted" }, v.message) : null)));
    } else if (S.result && S.mode === "solve") {
      out.push(h("div", { class: "drill-body" + (fresh ? " pop" : "") },
        h("div", { class: "label" }, "Read as"), promptView(S.result.prompt),
        h("div", { class: "label" }, "Step by step"), stepsView(S.result.solution, S.result.answer, S.topic)));
    }
    fill(root,
      head("Courses · your own homework", "Solve"),
      h("div", { class: "solve-controls" },
        h("label", { class: "field label" }, "Topic", select),
        seg([["solve", "Step by step"], ["check", "Check my answer"]], S.mode, m => { S.mode = m; S.result = null; paint(); }, "Mode", "seg-text")),
      h("div", { class: "solve-grid" },
        h("div", { class: "field", style: { gap: "10px" } },
          h("label", { class: "label", for: "solve-in" }, "Problem"), textarea,
          S.mode === "check" ? [h("label", { class: "label", for: "solve-ans", style: { marginTop: "4px" } }, "My answer"),
            h("input", { class: "input input-l", id: "solve-ans", spellcheck: "false", value: S.check, placeholder: t.key === "kmap" ? "A'C' + AC" : "", oninput: e => { S.check = e.target.value; }, onkeydown: keys })] : null,
          goBtn),
        h("div", { class: "syntax" },
          h("div", { class: "label" }, `Input syntax · ${t.title}`),
          usage.map(u => h("div", { class: "line" }, u.replace(/^or /, "or: "))),
          /\[/.test(t.solve_usage) ? h("div", { class: "note" }, "Parts in [brackets] are optional; a|b means pick one.") : null,
          h("div", { class: "note" }, "Example ", h("span", { class: "mono", style: { color: "var(--text)" } }, usageExample(t.solve_usage))))),
      out);
  }
  paint();
  return root;
};

// ---- java sheet ----------------------------------------------------------------------------

ROUTES.java = async rest => {
  const secs = await api("/api/java");
  let current = rest[0] || (secs[0] && secs[0].key);
  const tabs = h("div", { class: "tabs", role: "navigation", "aria-label": "Sections" });
  const paintTabs = () => tabs.replaceChildren(...secs.map(sec => h("button", { type: "button", "aria-current": String(sec.key === current),
    onclick: () => { current = sec.key; paintTabs(); document.getElementById("java-" + sec.key).scrollIntoView({ behavior: "smooth", block: "start" }); } }, sec.title)));
  paintTabs();
  const root = h("div", { class: "screen java" },
    head("Code · C++ → Java for competitive programming", "Java sheet",
      { lede: "CIS 201 is taught in Java. Every snippet compiles with JDK 21; New file with Java ticked gives you a ready class Main." }),
    tabs,
    secs.map(sec => h("section", { class: "jsec", id: "java-" + sec.key },
      h("h2", {}, sec.title),
      groupBullets(sec.blocks).map(b => b.type === "bullets" ? h("ul", { class: "bullets" }, b.items.map(x => h("li", {}, rich(x))))
        : b.type === "text" ? prose(b.text)
        : b.type === "table" ? h("div", { class: "scroll-x" }, h("table", { class: "table", style: { minWidth: "480px" } },
          h("thead", {}, h("tr", {}, b.header.map((x, i) => h("th", { style: i === 0 ? { width: "42%" } : null }, x)))),
          h("tbody", {}, b.rows.map(r => h("tr", {}, r.map(c => h("td", {}, c)))))))
          : codeBlock(sec, b)))));
  if (rest[0]) root.afterMount = () => { const el = document.getElementById("java-" + rest[0]); if (el) el.scrollIntoView(); };
  return root;
};
// Consecutive "- " text blocks become one list.
function groupBullets(blocks) {
  const out = [];
  for (const b of blocks) {
    const m = b.type === "text" && /^\s*- ([\s\S]*)$/.exec(b.text);
    if (m && out.length && out[out.length - 1].type === "bullets") out[out.length - 1].items.push(m[1]);
    else if (m) out.push({ type: "bullets", items: [m[1]] });
    else out.push(b);
  }
  return out;
}
// Sheet text is plain lines; "- " lines become a list.
function prose(text) {
  const lines = String(text).split("\n").filter(l => l.trim());
  if (lines.length && lines.every(l => /^\s*- /.test(l))) return h("ul", { class: "bullets" }, lines.map(l => h("li", {}, rich(l.replace(/^\s*- /, "")))));
  return h("p", {}, rich(text));
}
function codeBlock(sec, b) {
  const name = /\bclass Main\b/.test(b.code) ? "Main.java" : (b.code.match(/\bclass (\w+)/) || [])[1] ? `${b.code.match(/\bclass (\w+)/)[1]}.java` : "snippet";
  return h("div", { class: "code" },
    h("div", { class: "code-head" }, h("span", { class: "mono" }, name),
      h("button", { type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(b.code); toast(`Copied the ${sec.title} snippet`); }
        catch { toast("Couldn't reach the clipboard: select the code and copy it by hand", "err"); }
      } }, icon("copy", 13, 2), "Copy")),
    h("pre", {}, b.code),
    b.stdin || b.expect ? h("div", { class: "io" }, b.stdin ? h("span", {}, "input ", h("b", {}, b.stdin.trim())) : null, b.expect ? h("span", {}, "prints ", h("b", {}, b.expect.trim())) : null) : null);
}

// ---- start ---------------------------------------------------------------------------------

(async function boot() {
  setTheme(theme(), false);
  renderNav();
  try {
    META = await api("/api/meta");
    paintMeta();
    for (const w of META.warnings || []) console.warn("dojo:", w);
  } catch (e) {
    toast(e.message, "err");
    paintFresh();
  }
  route();
  refreshCounts();
  setInterval(paintFresh, 60000);
})();
