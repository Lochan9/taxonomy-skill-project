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
async function api(path) {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  const j = await r.json();
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { data: j, status: r.status });
  return j;
}
async function post(body) {
  const r = await fetch("/api/review/decision", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard": "1" }, body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { data: j, status: r.status });
  return j;
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

// ---------------------------------------------------------------- 3. review
let current = null, lastSelection = "";
const reviewer = () => $("#reviewer").value.trim();
$("#reviewer").value = store.get("reviewer") || "";
$("#reviewer").addEventListener("change", () => { store.set("reviewer", reviewer()); loadReview(); });
$("#review-source").addEventListener("change", loadReview);
async function loadReview() {
  const msg = $("#review-msg");
  const p = new URLSearchParams({ source: $("#review-source").value });
  if (reviewer()) p.set("reviewer", reviewer());
  try {
    const d = await api(`/api/review?${p}`);
    $("#snapshot").textContent = d.snapshot_id;
    msg.textContent = reviewer() ? `Reviewing as ${reviewer()}` : "Enter a reviewer ID to record decisions.";
    const list = $("#review-postings");
    list.replaceChildren(...d.postings.map((x) => {
      const li = el("li", {}, el("div", { class: "t", text: x.title }), el("div", { class: "m", text: `${x.company_name} · ${x.posting_id}` }),
        el("div", {}, badge(`${x.n_draft} draft`, "direct"), x.n_pending ? badge(`${x.n_pending} pending`, "pending") : badge("all decided", "ok"),
          x.n_discuss ? badge(`${x.n_discuss} DISCUSS`, "discuss") : null));
      li.addEventListener("click", () => { list.querySelectorAll(".sel").forEach((y) => y.classList.remove("sel")); li.classList.add("sel"); reviewPosting(x.posting_id); });
      return li;
    }));
  } catch (e) { msg.textContent = e.message; }
}
async function reviewPosting(pid) {
  const box = $("#review-detail");
  box.className = "detail";
  const p = new URLSearchParams({ source: $("#review-source").value, posting_id: pid });
  if (reviewer()) p.set("reviewer", reviewer());
  const d = await api(`/api/review/posting?${p}`);
  current = d;
  const text = renderText(d.segments, (ids) => focusIds(box, ids));
  text.addEventListener("mouseup", () => { const s = String(window.getSelection()); if (s.trim()) { lastSelection = s; $("#sel-hint").textContent = `Selected: “${s.slice(0, 80)}”`; } });
  const items = el("div", { class: "items" }, d.items.map((it) => reviewItem(it, box)));
  box.replaceChildren(el("h2", { text: d.title }), el("p", { class: "muted", text: `${d.posting_id} · ${d.label}` }),
    d.posting_notes ? el("p", { class: "notes", text: d.posting_notes }) : null,
    el("p", { id: "sel-hint", class: "muted", text: "Tip: select text in the posting to use it as evidence." }), text,
    el("div", { class: "row" }, el("button", { onclick: () => openEdit(null), text: "Add skill" })),
    el("h3", { text: `Records (${d.items.length}) · pending ${d.items.filter((i) => i.state === "pending").length}` }), items);
}
function reviewItem(it, box) {
  const c = it.current;
  const flagged = it.flags.includes("discuss") || it.flags.includes("suggested_addition");
  const notes = (it.draft && it.draft.review_notes) || c.review_notes || "";
  const decide = async (action) => {
    if (!reviewer()) { $("#review-msg").textContent = "Enter a reviewer ID first."; return; }
    try { await post({ reviewer_id: reviewer(), source: current.source, posting_id: current.posting_id, annotation_id: it.annotation_id, action }); reviewPosting(current.posting_id); loadReview(); }
    catch (e) { $("#review-msg").textContent = e.message; }
  };
  return el("div", { class: `item state-${it.state}${flagged ? " flagged" : ""}`, "data-item": it.annotation_id, onclick: (ev) => { if (ev.target.tagName !== "BUTTON") focusIds(box, [it.annotation_id]); } },
    el("div", {}, el("span", { class: "stmt", text: c.skill_statement }), " ", badge(it.state, it.state), badge(c.required_or_preferred, c.required_or_preferred),
      it.flags.includes("discuss") ? badge("DISCUSS — unresolved", "discuss") : null,
      it.flags.includes("illustrative") ? badge("illustrative example", "illustrative_example") : null,
      it.flags.includes("suggested_addition") ? badge("AI-suggested addition", "warn") : null,
      c.alternative_group_id ? badge(`alternative ${c.alternative_group_id}`, "category") : null,
      it.origin === "reviewer" ? badge("added by reviewer", "added") : null,
      it.offset_valid ? null : badge("offset invalid", "warn")),
    el("div", { class: "ev", text: `“${c.evidence_text}”  [${c.evidence_start}:${c.evidence_end}] · ${it.annotation_id}` }),
    notes ? el("div", { class: "notes", text: notes }) : null,
    it.decision ? el("div", { class: "notes", text: `Decision: ${it.decision.action} by ${it.decision.reviewer_id} at ${it.decision.timestamp}` }) : null,
    el("div", { class: "actions" },
      it.origin === "draft" && it.state !== "accepted" ? el("button", { text: "Accept", onclick: () => decide("accept") }) : null,
      el("button", { class: "ghost", text: "Edit", onclick: () => openEdit(it) }),
      it.state !== "rejected" ? el("button", { class: "danger", text: "Reject", onclick: () => decide("reject") }) : null,
      it.state !== "pending" && it.origin === "draft" ? el("button", { class: "ghost", text: "Reopen", onclick: () => decide("reopen") }) : null));
}

// edit / add dialog
const dlg = $("#edit-dialog"), form = $("#edit-form");
let editing = null, locTimer;
function openEdit(it) {
  if (!reviewer()) { $("#review-msg").textContent = "Enter a reviewer ID first."; return; }
  editing = it;
  const c = it ? it.current : { skill_statement: "", evidence_text: lastSelection.trim(), required_or_preferred: "unspecified", skill_category: "", alternative_group_id: "", review_notes: "" };
  $("#edit-title").textContent = it ? `Edit ${it.annotation_id}` : "Add skill";
  for (const k of ["skill_statement", "evidence_text", "required_or_preferred", "skill_category", "alternative_group_id", "review_notes"]) form.elements[k].value = c[k] || "";
  if (it && lastSelection.trim() && confirm("Use your selected text as the new evidence?")) form.elements.evidence_text.value = lastSelection.trim();
  $("#edit-error").textContent = "";
  refreshOccurrences(it ? Number(c.evidence_start) : null);
  dlg.showModal();
}
async function refreshOccurrences(keepStart, serverMessage) {
  const sel = form.elements.occurrence, ev = form.elements.evidence_text.value;
  sel.replaceChildren(el("option", { value: "", text: "—" }));
  if (!ev || !current) return;
  try {
    const d = await api(`/api/locate?posting_id=${encodeURIComponent(current.posting_id)}&evidence=${encodeURIComponent(ev)}`);
    if (!d.occurrences.length) { $("#edit-error").textContent = "Not found in the posting: evidence must match exactly."; return; }
    $("#edit-error").textContent = d.occurrences.length > 1 ? `Appears ${d.occurrences.length} times: choose an occurrence.` : "";
    d.occurrences.forEach((o, i) => sel.append(el("option", { value: String(i + 1), text: `#${i + 1} at ${o}: …${(d.contexts[i] || "").replace(/\s+/g, " ")}…` })));
    const keep = d.occurrences.indexOf(keepStart);
    sel.value = d.occurrences.length === 1 ? "1" : keep >= 0 ? String(keep + 1) : "";
    if (serverMessage) $("#edit-error").textContent = serverMessage;  // keep the server's reason visible
  } catch (e) { $("#edit-error").textContent = e.message; }
}
form.elements.evidence_text.addEventListener("input", () => { clearTimeout(locTimer); locTimer = setTimeout(() => refreshOccurrences(null), 300); });
form.addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const f = form.elements;
  const body = { reviewer_id: reviewer(), source: current.source, posting_id: current.posting_id, action: editing ? "edit" : "add",
    annotation_id: editing ? editing.annotation_id : undefined, skill_statement: f.skill_statement.value,
    evidence_text: f.evidence_text.value, required_or_preferred: f.required_or_preferred.value, skill_category: f.skill_category.value,
    alternative_group_id: f.alternative_group_id.value, review_notes: f.review_notes.value };
  if (f.occurrence.value) body.occurrence = Number(f.occurrence.value);
  try { await post(body); dlg.close(); lastSelection = ""; reviewPosting(current.posting_id); loadReview(); }
  catch (e) { $("#edit-error").textContent = e.message; if (e.data && e.data.occurrences) refreshOccurrences(null, e.message); }
});

show(views.includes(store.get("tab")) ? store.get("tab") : "corpus");
