"use strict";
// Team B dashboard. Talks only to this localhost server; all data is inserted as text (never as HTML).

const $ = (s, r = document) => r.querySelector(s);
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const badge = (text, cls) => el("span", { class: `badge b-${cls}`, text });
async function api(path, extraHeaders = {}) {
  const r = await fetch(path, { headers: { Accept: "application/json", ...extraHeaders } });
  const j = await r.json();
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { data: j, status: r.status });
  return j;
}
async function post(path, body, extraHeaders = {}) {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard": "1", ...extraHeaders },
    body: JSON.stringify(body),
  });
  let j;
  try { j = await r.json(); } catch { j = { error: `HTTP ${r.status}` }; }
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { data: j, status: r.status });
  return Object.assign(j, { httpStatus: r.status });
}
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};
const fmt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString());
const card = (k, v, small) => el("div", { class: "card" }, el("div", { class: "k", text: k }), el("div", { class: "v" + (small ? " small" : ""), text: v }));
const MENTION = { direct: "individual requirement", illustrative_example: "illustrative example", category: "category of examples" };

// Posting text with highlighted evidence. Segments come from the server, which validated offsets.
function renderText(segments, onPick, classFor) {
  const box = el("div", { class: "posting-text", tabindex: "0" });
  for (const s of segments) {
    if (!s.ids.length) { box.append(document.createTextNode(s.text)); continue; }
    const extra = classFor ? classFor(s.ids) : "";
    box.append(el("mark", { class: [s.ids.length > 1 ? "multi" : "", extra].join(" ").trim(), "data-ids": s.ids.join(" "),
      title: `${s.ids.length} record(s)`, onclick: () => onPick && onPick(s.ids) }, s.text));
  }
  return box;
}
function focusIds(root, ids) {
  root.querySelectorAll(".focus").forEach((n) => n.classList.remove("focus"));
  root.querySelectorAll("mark[data-ids]").forEach((m) => {
    if (m.dataset.ids.split(" ").some((i) => ids.includes(i))) m.classList.add("focus");
  });
  ids.forEach((id) => { const c = root.querySelector(`[data-item="${CSS.escape(id)}"]`); if (c) c.classList.add("focus"); });
  const first = root.querySelector(`[data-item="${CSS.escape(ids[0])}"]`);
  if (first) first.scrollIntoView({ block: "nearest" });
}

// ---------------------------------------------------------------- tabs
const views = ["corpus", "extraction", "review"];
const loaded = {};
function show(view) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
  views.forEach((v) => { $(`#view-${v}`).hidden = v !== view; });
  store.set("tab", view);
  if (!loaded[view]) { loaded[view] = true; ({ corpus: loadCorpus, extraction: loadRuns, review: loadReview })[view](); }
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

// ---------------------------------------------------------------- 1. corpus
let facetsDone = false;
async function loadCorpus() {
  const p = new URLSearchParams({ employer: $("#f-employer").value, seniority: $("#f-seniority").value,
    exclusion: $("#f-exclusion").value, q: $("#f-q").value });
  const d = await api(`/api/corpus?${p}`);
  $("#snapshot").textContent = d.snapshot_id;
  if (!facetsDone) {
    facetsDone = true;
    d.facets.employers.forEach((e) => $("#f-employer").append(el("option", { value: e, text: e })));
    d.facets.seniority.forEach((e) => $("#f-seniority").append(el("option", { value: e, text: e })));
    d.facets.exclusions.forEach((e) => $("#f-exclusion").append(el("option", { value: e, text: `Excluded: ${e}` })));
    const m = d.metrics || {};
    $("#corpus-metrics").replaceChildren(card("Postings", fmt(d.total)), card("Usable", fmt(m.usable_rows)),
      card("Flagged / excluded", fmt(m.flagged_rows)), card("Employers", fmt(d.facets.employers.length)),
      card("Median words", fmt(m.word_count_usable_median)), card("Near-duplicate pairs", fmt(m.near_duplicate_candidate_pairs)),
      card("Held out (text hidden)", fmt(d.held_out_count)));
    $("#corpus-figures").replaceChildren(...d.figures.map((f) =>
      el("figure", {}, el("img", { src: `/figures/${encodeURIComponent(f)}`, alt: f.replace(/[_.]/g, " "), loading: "lazy" }),
        el("figcaption", { class: "muted", text: f }))));
    if (!d.figures.length) $("#corpus-figures").append(el("p", { class: "muted", text: "No figures found in reports/figures." }));
  }
  $("#corpus-count").textContent = `${d.shown} of ${d.total} shown`;
  const tb = $("#corpus-table tbody");
  tb.replaceChildren(...d.postings.map((r) => {
    const status = r.excluded ? badge(`excluded: ${r.exclusion_reason}`, "warn")
      : r.held_out ? badge("held out", "pending") : r.selection_split ? badge(r.selection_split, "direct") : badge("usable", "ok");
    const tr = el("tr", {}, el("td", { text: r.company_name }), el("td", { text: r.title }),
      el("td", { text: r.seniority || "—" }), el("td", { text: fmt(r.word_count) }), el("td", {}, status));
    tr.addEventListener("click", () => { tb.querySelectorAll(".sel").forEach((x) => x.classList.remove("sel")); tr.classList.add("sel"); corpusDetail(r); });
    return tr;
  }));
  if (!d.postings.length) tb.append(el("tr", {}, el("td", { colspan: "5", class: "empty-state", text: "No postings match these filters." })));
}
async function corpusDetail(r) {
  const box = $("#corpus-detail");
  box.className = "detail";
  const head = [el("h2", { text: r.title }), el("p", { class: "muted", text: `${r.company_name} · ${r.location || "—"} · ${r.posting_id}` })];
  if (r.excluded) head.push(el("p", {}, badge(`excluded: ${r.exclusion_reason}`, "warn")));
  if (r.held_out) {
    box.replaceChildren(...head, el("p", { class: "empty-state", text: "Held out: this posting is in the evaluation set (or is a variant grouped with one). Its text is not shown in the dashboard." }));
    return;
  }
  try {
    const d = await api(`/api/corpus/posting?posting_id=${encodeURIComponent(r.posting_id)}`);
    box.replaceChildren(...head, el("div", { class: "posting-text" }, d.clean_text));
  } catch (e) { box.replaceChildren(...head, el("p", { class: "error", text: e.message })); }
}
["#f-employer", "#f-seniority", "#f-exclusion"].forEach((s) => $(s).addEventListener("change", loadCorpus));
let qTimer; $("#f-q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(loadCorpus, 250); });

// ---------------------------------------------------------------- 2. extraction
async function loadRuns() {
  const d = await api("/api/runs");
  $("#snapshot").textContent = d.snapshot_id;
  const sel = $("#run-select");
  sel.replaceChildren(...d.runs.map((r) => el("option", { value: r.run_id, text: `${r.run_id} · ${r.model} · ${r.n_statements ?? 0} statements` })));
  if (!d.runs.length) {
    $("#run-empty").textContent = "No saved runs in data/extraction/runs/.";
    $("#run-detail").replaceChildren(document.createTextNode("No extraction results yet. Run src/extract_skills.py first."));
    return;
  }
  sel.onchange = () => loadRun(sel.value);
  loadRun(d.runs[0].run_id);
}
async function loadRun(runId) {
  const d = await api(`/api/run?run_id=${encodeURIComponent(runId)}`);
  const u = d.token_usage_billed || {};
  $("#run-meta").replaceChildren(card("Run ID", d.run_id, true), card("Model", d.model, true),
    card("Provider access", d.provider_access || "—", true), card("Brief p.7 compliance", d.brief_p7_compliance || "—", true),
    card("Prompt / schema", `${d.prompt_version} / ${d.schema_version}`, true),
    card("Input tokens (billed)", `${fmt(d.llm_tokens_in)}  (uncached ${fmt(u.input_tokens)}, cache write ${fmt(u.cache_creation_input_tokens)}, read ${fmt(u.cache_read_input_tokens)})`, true),
    card("Output tokens", fmt(d.llm_tokens_out)),
    card("API calls / cache hits", `${fmt(d.api_calls)} / ${fmt(d.cache_hits)}`),
    card("Results", Object.entries(d.counts || {}).map(([k, v]) => `${k} ${v}`).join(" · "), true));
  const list = $("#run-postings");
  list.replaceChildren(...d.postings.map((p) => {
    const li = el("li", {}, el("div", { class: "t", text: p.title }), el("div", { class: "m", text: `${p.company_name} · ${p.posting_id}` }),
      el("div", {}, p.status ? [badge(p.status, p.status === "ok" ? "ok" : p.status === "zero_skills" ? "unspecified" : "warn"),
        badge(`${p.n_statements} accepted`, "direct"), p.n_rejected ? badge(`${p.n_rejected} rejected`, "warn") : null]
        : badge("no result in this run", "unspecified")));
    li.addEventListener("click", () => { list.querySelectorAll(".sel").forEach((x) => x.classList.remove("sel")); li.classList.add("sel"); runPosting(d.run_id, p.posting_id); });
    return li;
  }));
  $("#run-detail").className = "detail empty-state";
  $("#run-detail").textContent = "Select a development posting.";
}
async function runPosting(runId, pid) {
  const box = $("#run-detail");
  box.className = "detail";
  const d = await api(`/api/run/posting?run_id=${encodeURIComponent(runId)}&posting_id=${encodeURIComponent(pid)}`);
  const head = [el("h2", { text: d.title }), el("p", { class: "muted", text: `${d.posting_id} · ${d.label}` })];
  if (d.empty) {
    box.replaceChildren(...head, el("p", { class: "empty-state", text: "No extraction result for this posting in this run." }));
    return;
  }
  const r = d.result;
  const meta = el("dl", { class: "kv" }, el("dt", { text: "Status" }), el("dd", { text: r.status + (r.error ? ` — ${r.error}` : "") }),
    el("dt", { text: "Tokens in / out" }), el("dd", { text: `${fmt((r.usage.input_tokens || 0) + (r.usage.cache_creation_input_tokens || 0) + (r.usage.cache_read_input_tokens || 0))} / ${fmt(r.usage.output_tokens)}` }),
    el("dt", { text: "Cache" }), el("dd", { text: r.cache_hit ? "hit (no new spend)" : "API call" }),
    el("dt", { text: "Request ID" }), el("dd", { text: r.request_id || "—" }));
  const legend = el("div", { class: "legend" }, "Highlights:", el("mark", { text: "requirement" }), el("mark", { class: "m-illus", text: "illustrative example" }),
    el("mark", { class: "m-cat", text: "category" }), el("mark", { class: "multi", text: "overlap" }), "· Mention type:", badge("individual requirement", "direct"),
    badge("illustrative example", "illustrative_example"), badge("category of examples", "category"),
    "· Requirement:", badge("required", "required"), badge("preferred", "preferred"), badge("unspecified", "unspecified"));
  const rel = Object.fromEntries(d.statements.map((s) => [s.statement_id, s.mention_relation]));
  const tint = (ids) => { const k = new Set(ids.map((i) => rel[i])); return k.size === 1 && k.has("illustrative_example") ? "m-illus" : k.size === 1 && k.has("category") ? "m-cat" : ""; };
  const text = renderText(d.segments, (ids) => focusIds(box, ids), tint);
  const items = el("div", { class: "items" }, d.statements.map((s) => {
    const rel = s.mention_relation;
    return el("div", { class: `item ${rel === "illustrative_example" ? "illustrative" : rel}`, "data-item": s.statement_id,
      onclick: () => focusIds(box, [s.statement_id]) },
      el("div", {}, el("span", { class: "stmt", text: s.text }), " ",
        badge(s.requirement_status, s.requirement_status), badge(MENTION[rel] || rel, rel),
        rel === "illustrative_example" && s.example_of ? el("span", { class: "muted", text: `example of “${s.example_of}”` }) : null,
        s.alternative_group ? badge(`alternative ${s.alternative_group}`, "category") : null,
        s.offset_valid ? null : badge("offset invalid — not highlighted", "warn")),
      el("div", { class: "ev", text: `“${s.source_span}”  [${s.evidence_start}:${s.evidence_end}] · ${s.evidence_resolution}${s.section ? ` · ${s.section}` : ""}` }),
      (s.warnings || []).map((w) => el("div", { class: "notes" }, badge("warning", "warn"), w)),
      s.model_notes ? el("div", { class: "notes", text: `Model note: ${s.model_notes}` }) : null);
  }));
  const rej = d.rejected.length
    ? el("div", { class: "items" }, d.rejected.map((x) => el("div", { class: "item state-rejected" },
      el("div", {}, el("span", { class: "stmt", text: x.record.skill_statement }), " ", badge("rejected", "warn")),
      el("div", { class: "ev", text: `“${x.record.evidence_text}”` }), el("div", { class: "notes", text: x.reason }))))
    : el("p", { class: "muted", text: "No rejected records." });
  box.replaceChildren(...head, meta, legend, text, el("h3", { text: `Accepted statements (${d.statements.length})` }), items,
    el("h3", { text: `Rejected records (${d.rejected.length})` }), rej);
}

// ---------------------------------------------------------------- 3. review (development drafts + independent evaluation)
const R = {
  mode: store.get("review-mode") === "evaluation" ? "evaluation" : "development",
  reviewer: store.get("reviewer") || "",
  overview: null, view: null, pid: null, filter: "all", busy: false, lastSelection: "",
};
const REVIEWER_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const evalStarted = () => { try { return sessionStorage.getItem("eval-started") === "1"; } catch { return false; } };
const modeHeaders = () => (R.mode === "evaluation" ? { "X-Dashboard-Mode": "evaluation" } : {});
const newRequestId = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : `${Date.now()}${Math.random().toString(36).slice(2, 12)}`);
const STATE_LABEL = { pending: "pending", accepted: "accepted", edited: "edited", rejected: "rejected", added: "added", split: "split" };
const POSTING_STATUS = { completed: ["reviewed", "ok"], in_progress: ["in progress", "edited"], not_started: ["not started", "unspecified"],
  completion_invalidated: ["completion invalidated", "warn"] };

function setStatus(kind, text, onReload) {
  const box = $("#save-status");
  box.className = `save-status ${kind}`;
  box.replaceChildren(document.createTextNode(text));
  if (onReload) box.append(" ", el("button", { type: "button", class: "ghost", text: "Reload posting", onclick: onReload }));
}
function setBusy(on) { R.busy = on; document.body.classList.toggle("busy", on); }

function renderModeChrome() {
  document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === R.mode)));
  $("#source-wrap").hidden = R.mode === "evaluation";
  $("#review-banner").textContent = R.mode === "evaluation"
    ? "Independent evaluation annotation: original text only, empty skill lists. No AI drafts, predictions or suggestions are shown."
    : "AI-generated, unreviewed drafts (development postings). Your decisions are recorded separately; drafts and clean text are never modified.";
  $("#review-banner").className = R.mode === "evaluation" ? "banner eval" : "banner ai";
  const gate = R.mode === "evaluation" && !evalStarted();
  $("#eval-gate").hidden = !gate;
  const ready = REVIEWER_RE.test(R.reviewer) && !gate;
  $("#review-grid").hidden = !ready;
  $("#review-empty").hidden = ready || gate;
  $("#reviewer").value = R.reviewer;
}

async function loadReview() {
  renderModeChrome();
  if ($("#review-grid").hidden) return;
  const p = new URLSearchParams({ mode: R.mode, reviewer: R.reviewer, source: $("#review-source").value });
  try {
    R.overview = await api(`/api/review?${p}`, modeHeaders());
    $("#snapshot").textContent = R.overview.snapshot_id;
    renderPostingList();
    const remembered = store.get(`review-pid-${R.mode}`);
    const ids = R.overview.postings.map((x) => x.posting_id);
    const pid = ids.includes(R.pid) ? R.pid : ids.includes(remembered) ? remembered : ids[0];
    if (pid) await openPosting(pid);
  } catch (e) { setStatus("error", e.message); }
}
function renderPostingList() {
  const o = R.overview;
  $("#review-progress").textContent = `${o.mode === "evaluation" ? "Evaluation" : "Development"}: ${o.progress.completed}/${o.progress.total} postings marked reviewed · ${o.progress.in_progress} in progress · guidelines v${o.guidelines.version}`;
  $("#review-postings").replaceChildren(...o.postings.map((x) => {
    const [label, cls] = POSTING_STATUS[x.status];
    const li = el("li", { class: x.posting_id === R.pid ? "sel" : "", "data-pid": x.posting_id },
      el("div", { class: "t", text: x.title }), el("div", { class: "m", text: `${x.company_name} · ${x.posting_id}` }),
      el("div", {}, badge(label, cls),
        x.counts.pending ? badge(`${x.counts.pending} pending`, "pending") : null,
        x.counts.discussion_open ? badge(`${x.counts.discussion_open} DISCUSS`, "discuss") : null,
        o.mode === "evaluation" || !x.counts.pending ? badge(`${x.counts.active} skills`, "direct") : null));
    li.addEventListener("click", () => openPosting(x.posting_id));
    return li;
  }));
}
async function refreshOverview() {
  try {
    const p = new URLSearchParams({ mode: R.mode, reviewer: R.reviewer, source: $("#review-source").value });
    R.overview = await api(`/api/review?${p}`, modeHeaders());
    renderPostingList();
  } catch { /* the posting view is still correct; the list refreshes on the next load */ }
}
async function openPosting(pid) {
  R.pid = pid;
  store.set(`review-pid-${R.mode}`, pid);
  document.querySelectorAll("#review-postings li").forEach((li) => li.classList.toggle("sel", li.dataset.pid === pid));
  const p = new URLSearchParams({ mode: R.mode, reviewer: R.reviewer, source: $("#review-source").value, posting_id: pid });
  try {
    R.view = await api(`/api/review/posting?${p}`, modeHeaders());
    renderPosting();
  } catch (e) { setStatus("error", e.message); }
}
function step(delta) {
  const ids = (R.overview?.postings || []).map((x) => x.posting_id);
  const i = ids.indexOf(R.pid);
  if (i >= 0 && ids[i + delta]) openPosting(ids[i + delta]);
}

// --- one posting: text pane + cards pane
function renderPosting() {
  const v = R.view;
  const byId = Object.fromEntries(v.items.map((i) => [i.annotation_id, i]));
  const tint = (ids) => {
    const states = new Set(ids.map((i) => byId[i]?.state));
    return states.size === 1 && states.has("pending") ? "m-pending" : states.size === 1 && (states.has("accepted") || states.has("edited") || states.has("added")) ? "m-active" : "";
  };
  const text = renderText(v.segments, (ids) => focusItem(ids[0]), tint);
  text.id = "review-text-body";
  text.addEventListener("mouseup", () => { const s = String(window.getSelection()); if (s.trim()) { R.lastSelection = s; $("#sel-hint").textContent = `Selected: “${s.slice(0, 70)}${s.length > 70 ? "…" : ""}”`; } });
  const pd = v.posting_discussion;
  const postingNote = v.mode === "development" && pd.note
    ? el("details", { class: "notes-box" }, el("summary", {}, "Posting notes (AI provenance)", pd.required ? badge(pd.resolved ? "discussion resolved" : "DISCUSS — unresolved", pd.resolved ? "ok" : "discuss") : null),
      el("div", { class: "notes", text: pd.note }), pd.resolved ? el("div", { class: "notes", text: `Resolved: ${pd.reason}` }) : null)
    : null;
  const postingResolve = v.mode === "development" && pd.required && !pd.resolved
    ? el("div", { class: "warnbox" }, "This posting has a posting-level DISCUSS note. ", el("button", { type: "button", class: "ghost", text: "Resolve posting discussion", onclick: () => openResolve(null) }))
    : null;
  $("#review-text").replaceChildren(...[  // replaceChildren would print null as text
    el("h2", { text: v.title }), el("p", { class: "muted", text: `${v.company_name} · ${v.posting_id} · text sha ${v.clean_text_sha256.slice(0, 10)} · ${v.text_length.toLocaleString()} characters` }),
    postingNote, postingResolve,
    el("p", { id: "sel-hint", class: "muted", text: "Select text below to use it as evidence." }), text].filter(Boolean));
  renderCards();
}
function counts() { return R.view.counts; }
const FILTERS = [
  ["all", "All", (c) => c.total, () => true],
  ["pending", "Pending", (c) => c.pending, (i) => i.state === "pending"],
  ["accepted", "Accepted", (c) => c.accepted, (i) => i.state === "accepted"],
  ["edited", "Edited", (c) => c.edited, (i) => i.state === "edited" || (i.origin === "reviewer" && i.edited && i.active)],
  ["rejected", "Rejected", (c) => c.rejected, (i) => i.state === "rejected"],
  ["added", "Added / split parts", (c) => c.added, (i) => i.state === "added"],
  ["discussion", "Discussion (open)", (c) => c.discussion_open, (i) => i.discussion_open],
];
function renderCards() {
  const v = R.view, c = counts();
  const chips = el("div", { class: "chips", role: "group", "aria-label": "Filter records" }, FILTERS
    .filter(([k]) => R.mode === "development" || ["all", "added", "rejected", "discussion"].includes(k))
    .map(([k, label, n]) => el("button", { type: "button", class: `chip${R.filter === k ? " on" : ""}`, "aria-pressed": String(R.filter === k), onclick: () => { R.filter = k; renderCards(); } }, `${label} `, el("span", { class: "n", text: String(n(c)) }))));
  const f = (FILTERS.find(([k]) => k === R.filter) || FILTERS[0])[3];
  const shown = v.items.filter(f);
  const cards = shown.length ? shown.map(card2) : [el("p", { class: "empty-state", text: v.items.length ? "No records match this filter." : R.mode === "evaluation" ? "No skills recorded yet. Read the posting and add every skill it states." : "No draft records for this posting." })];
  $("#review-cards").replaceChildren(
    el("div", { class: "row between" }, el("h3", { text: `Records · ${c.active} active · ${c.pending} pending` }),
      el("button", { type: "button", text: "Add skill", onclick: () => openEdit(null) })),
    chips, el("div", { class: "items" }, cards), completionPanel());
}
function card2(it) {
  const c = it.current, draft = it.origin === "draft";
  const disc = it.discussion;
  const flags = [
    disc.required ? (disc.resolved ? badge("discussion resolved", "ok")
      : it.discussion_open ? badge("DISCUSS — unresolved", "discuss")
      : badge(`DISCUSS — set aside (${it.state})`, "unspecified")) : null,
    it.flags.includes("illustrative") ? badge("illustrative example", "illustrative_example") : null,
    it.flags.includes("suggested_addition") ? badge("AI-suggested addition", "warn") : null,
    c.alternative_group_id ? badge(`alternative ${c.alternative_group_id}`, "category") : null,
    it.split_from ? badge(`split from ${it.split_from}`, "added") : null,
    it.stale ? badge("STALE: draft changed since decided", "warn") : null,
    it.active && !it.offset_valid ? badge("offset invalid", "warn") : null,
  ];
  const act = (label, cls, fn) => el("button", { type: "button", class: cls, text: label, onclick: (ev) => { ev.stopPropagation(); fn(); } });
  const buttons = [];
  if (it.state !== "split") {
    if (draft && (it.state !== "accepted" || it.stale)) buttons.push(act("Accept", "", () => decide(it, "accept")));
    if (it.state !== "rejected") buttons.push(act("Edit", "ghost", () => openEdit(it)), act("Split", "ghost", () => openSplit(it)));
    if (it.state !== "rejected") buttons.push(act(R.mode === "evaluation" ? "Delete" : "Reject", "danger", () => decide(it, R.mode === "evaluation" ? "delete" : "reject")));
    if ((draft && ["accepted", "edited", "rejected"].includes(it.state)) || (!draft && it.state === "rejected")) buttons.push(act("Reopen", "ghost", () => decide(it, "reopen")));
    if (it.discussion_open) buttons.push(act("Resolve discussion", "ghost", () => openResolve(it)));
  }
  const notes = draft && it.draft ? it.draft.review_notes : "";
  const details = el("details", { class: "notes-box" }, el("summary", { text: "Details" }),
    notes ? el("div", { class: "notes", text: notes }) : null,
    !draft || c.review_notes !== notes ? (c.review_notes ? el("div", { class: "notes", text: `Reviewer notes: ${c.review_notes}` }) : null) : null,
    disc.resolved ? el("div", { class: "notes", text: `Discussion resolved: ${disc.reason}` }) : null,
    it.split_into.length ? el("div", { class: "notes", text: `Split into: ${it.split_into.join(", ")}` }) : null,
    el("div", { class: "notes", text: `ID ${it.annotation_id} · origin ${draft ? "AI-assisted draft" : "reviewer"}` }),
    it.history.length ? el("ol", { class: "history" }, it.history.map((h) => el("li", { text: `${h.timestamp} · ${h.reviewer_id} · ${h.action}${h.reason ? ` — ${h.reason}` : ""}` }))) : null);
  return el("div", { class: `item state-${it.state}${it.discussion_open || it.stale ? " flagged" : ""}`, "data-item": it.annotation_id, tabindex: "0",
    onclick: () => focusItem(it.annotation_id), onkeydown: (e) => { if (e.key === "Enter" && e.target === e.currentTarget) focusItem(it.annotation_id); } },
    el("div", {}, el("span", { class: "stmt", text: c.skill_statement || "(no statement)" }), " ", badge(STATE_LABEL[it.state] || it.state, it.state),
      c.required_or_preferred ? badge(c.required_or_preferred, c.required_or_preferred) : null, c.skill_category ? el("span", { class: "muted", text: c.skill_category }) : null, flags),
    el("div", { class: "ev", text: `“${c.evidence_text}”  [${c.evidence_start}:${c.evidence_end}]` }),
    details, buttons.length ? el("div", { class: "actions" }, buttons) : null);
}
function focusItem(id) {
  const pane = $("#review-text-body"), cardsPane = $("#review-cards");
  document.querySelectorAll("#view-review .focus").forEach((n) => n.classList.remove("focus"));
  const marks = [...pane.querySelectorAll("mark[data-ids]")].filter((m) => m.dataset.ids.split(" ").includes(id));
  marks.forEach((m) => m.classList.add("focus"));
  if (marks[0]) marks[0].scrollIntoView({ block: "center", behavior: "smooth" });
  const card = cardsPane.querySelector(`[data-item="${CSS.escape(id)}"]`);
  if (card) { card.classList.add("focus"); card.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
}

// --- writes: one request at a time, idempotent, versioned
async function send(extra, label) {
  if (R.busy) return null;
  setBusy(true);
  setStatus("saving", `Saving ${label}…`);
  const body = { reviewer_id: R.reviewer, mode: R.mode, source: $("#review-source").value, posting_id: R.view.posting_id,
    expected_version: R.view.version, expected_source_sha: R.view.draft_sha, client_request_id: newRequestId(), ...extra };
  try {
    let res;
    try { res = await post("/api/review/decision", body, modeHeaders()); }
    catch (e) { if (e instanceof TypeError) res = await post("/api/review/decision", body, modeHeaders()); else throw e; } // network retry: same request id, never written twice
    R.view = res.state;
    renderPosting();
    setStatus("saved", res.created ? `Saved: ${label}` : `Already saved: ${label} (duplicate request ignored)`);
    refreshOverview();
    return res;
  } catch (e) {
    if (e.status === 409 && (e.data?.current_version !== undefined || e.data?.current_source_sha !== undefined)) {
      setStatus("error", `Conflict: ${e.message}`, () => openPosting(R.view.posting_id));
    } else setStatus("error", `Not saved: ${e.message}`);
    throw e;
  } finally { setBusy(false); }
}
const decide = (it, action) => send({ annotation_id: it.annotation_id, action }, `${action} ${it.annotation_id}`).catch(() => {});

// --- dialogs
function wireDialog(dlg, onSubmit) {
  const form = dlg.querySelector("form");
  dlg.querySelector(".dlg-cancel").addEventListener("click", () => dlg.close());
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = form.querySelector(".edit-error"), save = form.querySelector(".dlg-save");
    if (save.disabled) return;
    save.disabled = true; err.textContent = "";
    try { await onSubmit(form); dlg.close(); }
    catch (e) {
      err.textContent = e.message;
      if (e.data?.occurrences) form.querySelectorAll(".occ-target").forEach((f) => f.dispatchEvent(new Event("input")));
    } finally { save.disabled = false; }
  });
}
// evidence + occurrence picker for one field group
function bindEvidence(root) {
  const ev = root.querySelector("[name=evidence_text]"), sel = root.querySelector("[name=occurrence]");
  const err = root.closest("form").querySelector(".edit-error");
  ev.classList.add("occ-target");
  let t;
  const refresh = async (keepStart) => {
    sel.replaceChildren(el("option", { value: "", text: "—" }));
    const v = ev.value;
    if (!v || !R.view) return;
    try {
      const p = new URLSearchParams({ mode: R.mode, posting_id: R.view.posting_id, evidence: v });
      const d = await api(`/api/locate?${p}`, modeHeaders());
      if (!d.occurrences.length) { err.textContent = "Not found in the posting: evidence must match exactly."; return; }
      if (d.occurrences.length > 1) err.textContent = `“${v.slice(0, 40)}” appears ${d.occurrences.length} times: choose the occurrence.`;
      else if (err.textContent.startsWith("Not found") || err.textContent.includes("appears")) err.textContent = "";
      d.occurrences.forEach((o, i) => sel.append(el("option", { value: String(i + 1), text: `#${i + 1} at ${o}: …${(d.contexts[i] || "").replace(/\s+/g, " ")}…` })));
      const keep = d.occurrences.indexOf(keepStart);
      sel.value = d.occurrences.length === 1 ? "1" : keep >= 0 ? String(keep + 1) : "";
    } catch (e) { err.textContent = e.message; }
  };
  ev.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => refresh(null), 250); });
  root._refresh = refresh;
  const use = root.querySelector(".use-sel");
  if (use) use.addEventListener("click", () => { if (R.lastSelection.trim()) { ev.value = R.lastSelection.trim(); refresh(null); } });
}
function fields(root) {
  const g = (n) => root.querySelector(`[name=${n}]`);
  const out = { skill_statement: g("skill_statement").value, evidence_text: g("evidence_text").value,
    required_or_preferred: g("required_or_preferred").value, skill_category: g("skill_category").value,
    alternative_group_id: g("alternative_group_id").value, review_notes: g("review_notes").value };
  if (g("occurrence").value) out.occurrence = Number(g("occurrence").value);
  return out;
}
function fillFields(root, c) {
  for (const k of ["skill_statement", "evidence_text", "required_or_preferred", "skill_category", "alternative_group_id", "review_notes"]) root.querySelector(`[name=${k}]`).value = c[k] || "";
  root._refresh(c.evidence_start === undefined ? null : Number(c.evidence_start));
}
const editDlg = $("#edit-dialog");
let editing = null;
bindEvidence($("#edit-form"));
wireDialog(editDlg, async (form) => {
  const f = fields(form);
  await send(editing ? { action: "edit", annotation_id: editing.annotation_id, ...f } : { action: "add", ...f }, editing ? `edit ${editing.annotation_id}` : "new skill");
});
function openEdit(it) {
  editing = it;
  $("#edit-title").textContent = it ? `Edit ${it.annotation_id}` : (R.mode === "evaluation" ? "Add skill (independent)" : "Add skill");
  $("#edit-form .edit-error").textContent = "";
  fillFields($("#edit-form"), it ? it.current : { skill_statement: "", evidence_text: R.lastSelection.trim(), required_or_preferred: "unspecified" });
  editDlg.showModal();
}
// split
const splitDlg = $("#split-dialog");
let splitting = null;
function partForm(n, c) {
  const box = el("fieldset", { class: "part" }, el("legend", { text: `Part ${n}` }),
    el("label", {}, "Skill statement", el("input", { name: "skill_statement", required: true })),
    el("label", {}, "Evidence text (exact)", el("textarea", { name: "evidence_text", rows: "2", required: true })),
    el("div", { class: "row" }, el("button", { type: "button", class: "ghost use-sel", text: "Use selected text" })),
    el("label", {}, "Occurrence", el("select", { name: "occurrence" }, el("option", { value: "", text: "—" }))),
    el("div", { class: "row" },
      el("label", {}, "Requirement", el("select", { name: "required_or_preferred" }, ["required", "preferred", "unspecified"].map((x) => el("option", { text: x })))),
      el("label", {}, "Category", el("select", { name: "skill_category" }, el("option", { value: "", text: "—" }), ["technical", "tool", "domain_knowledge", "transferable"].map((x) => el("option", { text: x })))),
      el("label", {}, "Alternative group", el("input", { name: "alternative_group_id", placeholder: "optional" }))),
    el("label", {}, "Review notes", el("input", { name: "review_notes" })));
  $("#split-parts").append(box);
  bindEvidence(box);
  fillFields(box, c);
}
$("#split-add").addEventListener("click", () => partForm($("#split-parts").children.length + 1, { required_or_preferred: splitting?.current.required_or_preferred || "unspecified" }));
wireDialog(splitDlg, async () => {
  const parts = [...$("#split-parts").children].map(fields);
  await send({ action: "split", annotation_id: splitting.annotation_id, parts }, `split ${splitting.annotation_id} into ${parts.length}`);
});
function openSplit(it) {
  splitting = it;
  $("#split-from").textContent = `Splitting “${it.current.skill_statement}” (${it.annotation_id}). The original is kept in the history and marked as split; each part gets its own evidence.`;
  $("#split-parts").replaceChildren();
  $("#split-form .edit-error").textContent = "";
  // parts start with the original's evidence and requirement, but not its notes: AI provenance (and any
  // DISCUSS flag) stays on the original, which the parts reference through split_from
  const base = { ...it.current, skill_statement: "", review_notes: "", alternative_group_id: "" };
  partForm(1, base); partForm(2, base);
  splitDlg.showModal();
}
// resolve discussion
const resolveDlg = $("#resolve-dialog");
let resolving = null;
wireDialog(resolveDlg, async (form) => {
  await send({ action: "resolve_discussion", annotation_id: resolving ? resolving.annotation_id : "__posting__", reason: form.elements.reason.value },
    `resolve discussion${resolving ? ` on ${resolving.annotation_id}` : " (posting)"}`);
});
function openResolve(it) {
  resolving = it;
  $("#resolve-what").textContent = it ? `${it.current.skill_statement} (${it.annotation_id})` : "Posting-level discussion note";
  $("#resolve-form").reset();
  $("#resolve-form .edit-error").textContent = "";
  resolveDlg.showModal();
}

// --- completion
function completionPanel() {
  const v = R.view, c = v.counts;
  const box = el("div", { class: "complete" }, el("h3", { text: "Posting completion" }));
  if (v.status === "completed") {
    const cc = v.completion;
    box.append(el("p", {}, badge("marked reviewed", "ok"), ` by ${R.reviewer} at ${cc.timestamp} · guidelines v${cc.completion.guidelines.version}${cc.completion.zero_skills ? " · deliberate zero-skill posting" : ""}`),
      el("button", { type: "button", class: "ghost", text: "Reopen posting", onclick: () => send({ action: "reopen_posting" }, "reopen posting").catch(() => {}) }));
    return box;
  }
  if (v.status === "completion_invalidated") box.append(el("p", { class: "warnbox", text: "This posting was marked reviewed, but a later change invalidated that. Reconfirm below." }));
  if (v.blocking.length) {
    box.append(el("p", { class: "muted", text: "Before it can be marked reviewed:" }),
      el("ul", { class: "blocking" }, v.blocking.map((b) => el("li", {}, b.annotation_id === "__posting__" ? "Posting: " : el("a", { href: "#", onclick: (e) => { e.preventDefault(); R.filter = "all"; renderCards(); focusItem(b.annotation_id); }, text: b.annotation_id }), ` — ${b.reason}`))));
  }
  const read = el("input", { type: "checkbox", id: "c-read" }), missing = el("input", { type: "checkbox", id: "c-missing" });
  const zero = c.active === 0 ? el("input", { type: "checkbox", id: "c-zero" }) : null;
  const btn = el("button", { type: "button", text: "Mark posting reviewed", disabled: true });
  const sync = () => { btn.disabled = v.blocking.length > 0 || !read.checked || !missing.checked || (zero && !zero.checked); };
  [read, missing, zero].forEach((x) => x && x.addEventListener("change", sync));
  btn.addEventListener("click", () => send({ action: "complete_posting", confirm_read_full_text: read.checked, confirm_checked_missing_skills: missing.checked, confirm_zero_skills: zero ? zero.checked : false }, "posting marked reviewed").catch(() => {}));
  box.append(el("label", { class: "check" }, read, "I read the full job description."),
    el("label", { class: "check" }, missing, "I checked the posting for missing skills."),
    zero ? el("label", { class: "check" }, zero, "This posting deliberately has no skill statements (zero-skill posting).") : null,
    el("p", { class: "muted", text: `${c.active} active record(s) will be exported. Completion records your ID, the time, the text hash${R.mode === "development" ? ", the AI draft version" : ""} and the guidelines version.` }), btn);
  return box;
}

// --- export
const exportDlg = $("#export-dialog");
let lastExport = null;
async function previewExport() {
  $("#export-error").textContent = "";
  try {
    const p = new URLSearchParams({ mode: R.mode, reviewer: R.reviewer, source: $("#review-source").value });
    const d = lastExport = await api(`/api/export/preview?${p}`, modeHeaders());
    const head = el("p", {}, badge(d.status === "complete" ? "COMPLETE (fully reviewed)" : "PARTIAL", d.status === "complete" ? "ok" : "warn"), badge("not gold", "unspecified"),
      ` ${d.postings.completed}/${d.total_postings} postings marked reviewed · ${d.postings.in_progress} in progress · ${d.skill_row_count} skill rows`);
    const probs = d.problems.length ? el("div", { class: "warnbox" }, el("strong", { text: `${d.problems.length} validation problem(s):` }), el("ul", {}, d.problems.slice(0, 20).map((x) => el("li", { text: x }))))
      : el("p", { class: "muted", text: "Validation: no problems (annotations.validate)." });
    const table = el("div", { class: "table-wrap small" }, el("table", {}, el("thead", {}, el("tr", {}, ["posting", "statement", "evidence", "req", "notes"].map((h) => el("th", { text: h })))),
      el("tbody", {}, d.skill_rows.slice(0, 60).map((r) => el("tr", {}, el("td", { text: r.posting_id.split(":").slice(1).join(":") }), el("td", { text: r.skill_statement }), el("td", { text: r.evidence_text.slice(0, 60) }), el("td", { text: r.required_or_preferred }), el("td", { class: "muted", text: r.review_notes.slice(0, 90) }))))));
    $("#export-summary").replaceChildren(head, el("p", { class: "muted", text: d.note }), probs, d.skill_rows.length ? table : el("p", { class: "muted", text: "No skill rows yet." }));
    $("#export-dl-skills").disabled = $("#export-dl-review").disabled = false;
    $("#export-write").disabled = d.problems.length > 0 || (!d.skill_row_count && !d.postings.completed);
  } catch (e) { $("#export-error").textContent = e.message; }
}
async function download(file) {
  const p = new URLSearchParams({ mode: R.mode, reviewer: R.reviewer, source: $("#review-source").value, file });
  try {
    const r = await fetch(`/api/export/download?${p}`, { headers: modeHeaders() });
    if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    const blob = await r.blob();
    const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || file;
    const a = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) { $("#export-error").textContent = e.message; }
}
$("#export-open").addEventListener("click", () => { if (!REVIEWER_RE.test(R.reviewer)) { setStatus("error", "Set your reviewer ID first."); return; } $("#export-summary").textContent = "Press “Preview” to build the export."; exportDlg.showModal(); });
$("#export-close").addEventListener("click", () => exportDlg.close());
$("#export-preview").addEventListener("click", previewExport);
$("#export-dl-skills").addEventListener("click", () => download("skills.csv"));
$("#export-dl-review").addEventListener("click", () => download("postings_review.csv"));
$("#export-write").addEventListener("click", async () => {
  const b = $("#export-write");
  if (b.disabled) return;
  b.disabled = true;
  $("#export-error").textContent = "";
  try {
    const r = await post("/api/export", { reviewer_id: R.reviewer, mode: R.mode, source: $("#review-source").value }, modeHeaders());
    $("#export-summary").prepend(el("p", { class: "save-status saved", text: `Written (${r.written.status}, not gold): ${r.written.path}` }));
  } catch (e) { $("#export-error").textContent = e.message; b.disabled = false; }
});

// --- toolbar
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  if (R.busy || b.dataset.mode === R.mode) return;
  R.mode = b.dataset.mode; R.pid = null; R.view = null; R.filter = "all";
  store.set("review-mode", R.mode);
  setStatus("", "");
  loadReview();
}));
$("#reviewer-set").addEventListener("click", () => {
  const v = $("#reviewer").value.trim();
  if (!REVIEWER_RE.test(v) || v.startsWith("ai_") || v.startsWith("ai-")) { setStatus("error", "Reviewer ID: lowercase letters, digits, _ or - (max 32), and not an AI workspace name."); return; }
  R.reviewer = v; store.set("reviewer", v); setStatus("saved", `Reviewing as ${v}`); loadReview();
});
$("#reviewer").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#reviewer-set").click(); });
$("#review-source").addEventListener("change", () => { R.pid = null; loadReview(); });
$("#eval-confirm").addEventListener("change", (e) => { $("#eval-start").disabled = !e.target.checked; });
$("#eval-start").addEventListener("click", () => { try { sessionStorage.setItem("eval-started", "1"); } catch { /* per-tab only */ } loadReview(); });
$("#prev-posting").addEventListener("click", () => step(-1));
$("#next-posting").addEventListener("click", () => step(1));
window.addEventListener("beforeunload", (e) => { if (R.busy) { e.preventDefault(); e.returnValue = ""; } });

show(views.includes(store.get("tab")) ? store.get("tab") : "corpus");
