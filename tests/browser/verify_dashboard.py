"""Browser verification of the Team B dashboard (Playwright driving the system Chrome, headless).

Optional tool, not collected by pytest and not a project dependency. Run it against a dashboard that
was started with a TEMPORARY review directory, so test decisions never reach the real reviews folder:

    python -m venv /tmp/pwvenv && /tmp/pwvenv/bin/pip install playwright        # uses installed Google Chrome
    python src/dashboard.py --port 8765 --reviews-dir /tmp/dash_reviews --reviewed-dir /tmp/dash_reviewed &
    /tmp/pwvenv/bin/python tests/browser/verify_dashboard.py OUT_DIR /tmp/dash_reviews /tmp/dash_reviewed EVAL_ID VARIANT_ID

OUT_DIR receives shots/*.png and pw_results.json. The script first asks the server where it writes and
refuses to run unless that is the given temporary folders. Set DASH_URL to use another port. EVAL_ID is an evaluation posting and VARIANT_ID a
posting grouped with one (both must be refused). The reviewer used is "pwtest".
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

S, REVIEWS, REVIEWED, EVAL_ID, VARIANT_ID = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
SHOTS = S / "shots"
BASE = os.environ.get("DASH_URL", "http://127.0.0.1:8765")

# Safety: refuse to run unless the server writes to the SAME temporary folders given here. Otherwise a
# dashboard already running on the port (with the real reviews/ and reviewed/) would receive test data.
import urllib.error
import urllib.request
try:
    with urllib.request.urlopen(BASE + "/api/review/storage", timeout=10) as _r:
        _storage = json.load(_r)
except (urllib.error.URLError, ValueError) as _e:
    sys.exit(f"REFUSING TO RUN: the server at {BASE} does not report where it writes ({_e}); it may be an "
             f"older dashboard using the real folders.")
if Path(_storage["reviews_dir"]) != REVIEWS.resolve() or Path(_storage["reviewed_dir"]) != REVIEWED.resolve():
    sys.exit(f"REFUSING TO RUN: the server at {BASE} writes to {_storage}, not to the temporary folders "
             f"{REVIEWS} / {REVIEWED}. Start the dashboard with those --reviews-dir/--reviewed-dir, or set DASH_URL.")
REVIEWER = "pwtest"
DUO = "greenhouse:duolingo:8675713002"
RH = "greenhouse:robinhood:4738660"
results, errors = [], []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def wait_js(page, fn, timeout=10000):
    """Poll a JS function; the page CSP forbids the string eval used by Playwright's waitForFunction."""
    for _ in range(timeout // 100):
        if page.evaluate(fn):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {fn}")


def shot(page, name, full=False):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=full)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("dialog", lambda d: d.accept())  # the "use selected text?" confirm

    # ------------------------------------------------------------ 1. corpus
    page.goto(BASE + "/", wait_until="networkidle")
    rows = page.locator("#corpus-table tbody tr")
    expect(rows.first).to_be_visible()
    check("corpus: all postings listed", rows.count() == 470, f"{rows.count()} rows")
    check("corpus: metric cards", page.locator("#corpus-metrics .card").count() == 7)
    wrap = page.locator(".table-wrap")
    sw = wrap.evaluate("e => [e.scrollWidth, e.clientWidth]")
    check("corpus: table columns fit (no horizontal clipping)", sw[0] <= sw[1] + 1, f"scrollWidth {sw[0]} / clientWidth {sw[1]}")
    shot(page, "01_corpus")
    page.click(".figs summary")
    wait_js(page, "() => [...document.querySelectorAll('#corpus-figures img')].every(i => i.complete && i.naturalWidth > 0)")
    widths = page.eval_on_selector_all("#corpus-figures img", "imgs => imgs.map(i => i.naturalWidth)")
    check("corpus: 5 figures load", len(widths) == 5 and all(w > 0 for w in widths), str(widths))
    shot(page, "02_corpus_figures")
    page.click(".figs summary")

    page.select_option("#f-employer", "Robinhood")
    wait_js(page, "() => document.querySelector('#corpus-count').textContent.startsWith('159 of')")
    emps = set(page.eval_on_selector_all("#corpus-table tbody tr td:first-child", "t => t.map(x => x.textContent)"))
    check("corpus: employer filter", emps == {"Robinhood"}, page.text_content("#corpus-count"))
    page.select_option("#f-seniority", "senior")
    page.wait_for_timeout(300)
    sen = set(page.eval_on_selector_all("#corpus-table tbody tr td:nth-child(3)", "t => t.map(x => x.textContent)"))
    check("corpus: seniority filter", sen == {"senior"}, page.text_content("#corpus-count"))
    page.fill("#f-q", "data engineering")
    page.wait_for_timeout(600)
    titles = page.eval_on_selector_all("#corpus-table tbody tr td:nth-child(2)", "t => t.map(x => x.textContent)")
    check("corpus: title search", titles and all("data engineering" in t.lower() for t in titles), f"{len(titles)}: {titles[:3]}")
    shot(page, "03_corpus_filtered")
    page.locator("#corpus-table tbody tr", has_text="Senior Software Engineer, Data Engineering").first.click()
    expect(page.locator("#corpus-detail .posting-text")).to_contain_text("Data Engineering team")
    check("corpus: development posting text opens", True)
    page.select_option("#f-employer", "")
    page.select_option("#f-seniority", "")
    page.fill("#f-q", "")
    page.select_option("#f-exclusion", "excluded")
    page.wait_for_timeout(600)
    check("corpus: exclusion filter", rows.count() == 2 and page.locator("#corpus-table .b-warn").count() == 2,
          page.text_content("#corpus-count"))
    page.select_option("#f-exclusion", "")
    page.wait_for_timeout(600)
    held_row = page.locator("#corpus-table tbody tr", has=page.locator(".b-pending")).first
    held_row.click()
    expect(page.locator("#corpus-detail")).to_contain_text("Held out")
    check("held-out: corpus shows notice, no text", page.locator("#corpus-detail .posting-text").count() == 0)
    shot(page, "04_corpus_held_out")
    scrolled = wrap.evaluate("e => { e.scrollTop = e.scrollHeight; return [e.scrollTop > 0, e.scrollHeight > e.clientHeight]; }")
    check("corpus: table scrolls internally", all(scrolled), str(scrolled))

    # ------------------------------------------------------------ 2. extraction
    page.click("button[data-view=extraction]")
    expect(page.locator("#run-meta .card").first).to_be_visible()
    meta = page.text_content("#run-meta")
    check("extraction: run, model, tokens, compliance shown",
          all(s in meta for s in ["skx-20261007T003601Z", "claude-sonnet-5-5", "14,266", "7,860", "unresolved"]))
    check("extraction: AI label", "AI-generated, unreviewed" in page.text_content("#view-extraction .banner"))
    lis = page.locator("#run-postings li")
    check("extraction: 20 development postings listed", lis.count() == 20)
    check("extraction: 3 ok, 17 without result",
          page.locator("#run-postings .b-ok").count() == 3 and page.locator("#run-postings li", has_text="no result in this run").count() == 17)
    shot(page, "05_extraction_overview")
    page.locator("#run-postings li", has_text=RH).click()
    expect(page.locator("#run-detail .item").first).to_be_visible()
    items = page.locator("#run-detail .items").first.locator(".item")
    check("extraction: 16 statements for Robinhood", items.count() == 16)
    illus = page.locator("#run-detail .item.illustrative")
    check("extraction: illustrative examples distinguished", illus.count() == 7 and
          page.locator("#run-detail .item.illustrative .b-illustrative_example").count() == 7, f"{illus.count()} illustrative")
    check("extraction: requirement badges", page.locator("#run-detail .items .b-required").count() >= 10)
    marks = page.eval_on_selector_all("#run-detail .posting-text mark", "m => m.map(x => x.textContent)")
    spans = page.eval_on_selector_all("#run-detail .items .ev", "e => e.map(x => x.textContent)")
    check("extraction: evidence highlighted", len(marks) > 0 and page.locator("#run-detail .b-warn", has_text="offset invalid").count() == 0,
          f"{len(marks)} highlighted segments")
    illus_marks = page.eval_on_selector_all("#run-detail .posting-text mark.m-illus", "m => m.map(x => x.textContent)")
    check("extraction: illustrative evidence tinted differently in text", {"Spark", "Flink"} <= set(illus_marks) and "Presto" not in illus_marks, str(illus_marks))
    page.locator("#run-detail .posting-text mark", has_text="Airflow").click()
    check("extraction: clicking evidence focuses its statement",
          "Airflow" in (page.locator("#run-detail .item.focus").first.text_content() or ""))
    shot(page, "06_extraction_robinhood")
    page.locator("#run-detail .item.illustrative").first.scroll_into_view_if_needed()
    shot(page, "07_extraction_illustrative")
    page.locator("#run-postings li", has_text="greenhouse:figma:6013304004").click()
    expect(page.locator("#run-detail")).to_contain_text("No extraction result for this posting in this run.")
    check("extraction: empty state", True)
    shot(page, "08_extraction_empty")

    # ------------------------------------------------------------ 3. review: development workflow
    ILL = "greenhouse:duolingo:8863967002"   # Illustrator, Intern: 5 AI drafts, 4 with DISCUSS
    log = REVIEWS / REVIEWER / "decisions.jsonl"
    nlog = lambda: len(log.read_text().splitlines()) if log.is_file() else 0
    expected_4xx = 0

    def card(aid):
        return page.locator(f"#review-cards .item[data-item='{aid}']")

    def saved(text_fragment="Saved"):
        expect(page.locator("#save-status")).to_contain_text(text_fragment, timeout=8000)

    def click_action(aid, label):
        card(aid).get_by_role("button", name=label, exact=True).click()

    page.click("button[data-view=review]")
    page.click(".seg button[data-mode=development]")
    expect(page.locator("#review-empty")).to_be_visible()
    check("review: grid hidden until a reviewer ID is set", page.locator("#review-grid").is_hidden())
    page.fill("#reviewer", REVIEWER)
    page.click("#reviewer-set")
    expect(page.locator("#review-postings li").first).to_be_visible()
    check("review: 20 development postings", page.locator("#review-postings li").count() == 20)
    check("review: overall progress shown", "0/20 postings marked reviewed" in page.text_content("#review-progress"),
          page.text_content("#review-progress"))
    page.locator("#review-postings li", has_text=ILL).click()
    expect(page.locator("#review-text")).to_contain_text(ILL)
    expect(card("ai_draft-0068")).to_be_visible()
    check("review: text beside cards", page.locator("#review-text .posting-text").is_visible() and page.locator("#review-cards .item").count() == 5)
    chips = page.locator("#review-cards .chip").all_text_contents()
    check("review: filter counts", any(c.startswith("Pending 5") for c in chips) and any(c.startswith("Discussion (open) 4") for c in chips), str(chips))
    det = card("ai_draft-0071").locator("details")
    check("review: provenance notes behind Details, DISCUSS visible",
          det.get_attribute("open") is None and card("ai_draft-0071").locator(".b-discuss").is_visible())
    card("ai_draft-0068").locator(".stmt").click()
    page.wait_for_timeout(500)
    in_view = page.evaluate("""() => { const m = document.querySelector('#review-text-body mark.focus'); if (!m) return false;
        const r = m.getBoundingClientRect(), p = document.querySelector('#review-text').getBoundingClientRect();
        return r.top >= p.top - 1 && r.bottom <= p.bottom + 1 && m.textContent.includes('illustrating in creative software'); }""")
    check("review: clicking a card highlights and scrolls to its evidence", in_view)
    shot(page, "20_review_dev_posting")

    # accept / reject / reopen / edit
    click_action("ai_draft-0068", "Accept"); saved("Saved: accept")
    check("review: accept", card("ai_draft-0068").locator(".b-accepted").is_visible())
    click_action("ai_draft-0071", "Reject"); saved("Saved: reject")
    click_action("ai_draft-0071", "Reopen"); saved("Saved: reopen")
    check("review: reject then reopen returns to pending", card("ai_draft-0071").locator(".b-pending").is_visible())
    click_action("ai_draft-0071", "Edit")
    page.fill("#edit-form [name=skill_statement]", "independent working")
    page.select_option("#edit-form [name=required_or_preferred]", "unspecified")
    page.select_option("#edit-form [name=skill_category]", "transferable")
    page.fill("#edit-form [name=review_notes]", "browser test edit")
    page.click("#edit-form .dlg-save")
    expect(page.locator("#edit-dialog")).to_be_hidden(); saved("Saved: edit")
    check("review: edit (wording, requirement, category, notes)", "independent working" in card("ai_draft-0071").text_content()
          and card("ai_draft-0071").locator(".b-edited").is_visible())

    # resolve a discussion with a recorded reason
    click_action("ai_draft-0071", "Resolve discussion")
    page.fill("#resolve-form [name=reason]", "stated as an ability in the duty list")
    page.click("#resolve-form .dlg-save")
    expect(page.locator("#resolve-dialog")).to_be_hidden(); saved("Saved: resolve")
    check("review: discussion resolved with reason", card("ai_draft-0071").locator(".b-ok", has_text="discussion resolved").is_visible())

    # split a combined skill into two traceable parts
    click_action("ai_draft-0072", "Split")
    parts = page.locator("#split-parts fieldset")
    parts.nth(0).locator("[name=skill_statement]").fill("small-group collaboration")
    parts.nth(0).locator("[name=evidence_text]").fill("in small groups")
    parts.nth(1).locator("[name=skill_statement]").fill("completing illustration projects")
    parts.nth(1).locator("[name=evidence_text]").fill("complete challenging illustration projects")
    page.wait_for_timeout(500)
    page.click("#split-form .dlg-save")
    expect(page.locator("#split-dialog")).to_be_hidden(); saved("Saved: split")
    split_parts = page.locator("#review-cards .item", has=page.locator(".badge", has_text="split from ai_draft-0072"))
    check("review: split into 2 parts with history", split_parts.count() == 2 and card("ai_draft-0072").locator(".b-split").is_visible())
    shot(page, "21_review_after_split")

    # Figma accepted + discussion resolved; Photoshop rejected
    click_action("ai_draft-0069", "Accept"); saved("Saved: accept")
    click_action("ai_draft-0069", "Resolve discussion")
    page.fill("#resolve-form [name=reason]", "named as acceptable software (illustrative)")
    page.click("#resolve-form .dlg-save"); expect(page.locator("#resolve-dialog")).to_be_hidden(); saved("Saved: resolve")
    click_action("ai_draft-0070", "Reject"); saved("Saved: reject")
    check("review: rejected DISCUSS record shown as set aside, not blocking",
          card("ai_draft-0070").locator(".badge", has_text="set aside (rejected)").is_visible())

    # add skill: invalid evidence, then repeated evidence needing an occurrence
    page.locator("#review-cards").get_by_role("button", name="Add skill").click()
    page.fill("#edit-form [name=skill_statement]", "browser-test addition")
    page.fill("#edit-form [name=evidence_text]", "this phrase is not in the posting")
    page.click("#edit-form .dlg-save"); expected_4xx += 1
    expect(page.locator("#edit-form .edit-error")).to_contain_text("does not occur exactly")
    check("review: invalid evidence error, nothing saved", page.locator("#edit-dialog").is_visible())
    shot(page, "22_review_invalid_evidence")
    page.fill("#edit-form [name=evidence_text]", "Duolingo")
    page.wait_for_timeout(600)
    opts = page.locator("#edit-form [name=occurrence] option").count() - 1
    page.select_option("#edit-form [name=occurrence]", value="")
    page.click("#edit-form .dlg-save"); expected_4xx += 1
    expect(page.locator("#edit-form .edit-error")).to_contain_text("choose an occurrence")
    check("review: repeated evidence requires choosing the occurrence", opts > 1, f"{opts} occurrences")
    page.select_option("#edit-form [name=occurrence]", value="2")
    page.click("#edit-form .dlg-save")
    expect(page.locator("#edit-dialog")).to_be_hidden(); saved("Saved: new skill")
    added = page.locator("#review-cards .item", has_text="browser-test addition")
    check("review: add skill with chosen occurrence", added.count() == 1 and added.locator(".b-added").is_visible())

    # duplicate clicks: two fast clicks on Reject write once
    n_before = nlog()
    btn = added.get_by_role("button", name="Reject", exact=True)
    btn.click(click_count=2, delay=10)
    saved("Saved: reject"); page.wait_for_timeout(400)
    check("review: double click writes one decision", nlog() == n_before + 1, f"{nlog() - n_before} new lines")
    added.get_by_role("button", name="Reopen", exact=True).click(); saved("Saved: reopen")

    # completion: blocked, then confirmed
    cbtn = page.locator(".complete button", has_text="Mark posting reviewed")
    check("review: completion disabled until confirmations", cbtn.is_disabled())
    page.check("#c-read"); page.check("#c-missing")
    check("review: no blocking items left", page.locator(".complete .blocking").count() == 0)
    cbtn.click(); saved("Saved: posting marked reviewed")
    check("review: posting marked reviewed", page.locator(".complete .b-ok", has_text="marked reviewed").is_visible())
    expect(page.locator("#review-progress")).to_contain_text("1/20 postings marked reviewed")
    check("review: progress updates", True)
    shot(page, "23_review_completed")
    # changing a completed posting invalidates the completion
    click_action("ai_draft-0068", "Reopen"); saved("Saved: reopen")
    expect(page.locator(".complete .warnbox")).to_contain_text("invalidated")
    expect(page.locator("#review-postings li.sel .badge", has_text="completion invalidated")).to_be_visible()
    check("review: change invalidates completion", True)
    click_action("ai_draft-0068", "Accept"); saved("Saved: accept")
    page.check("#c-read"); page.check("#c-missing")
    page.locator(".complete button", has_text="Mark posting reviewed").click(); saved("Saved: posting marked reviewed")

    # refresh: everything restored from the decision log
    page.reload(wait_until="networkidle")
    expect(page.locator("#review-cards .item").first).to_be_visible()
    check("persist: reviewer, mode and posting restored", page.input_value("#reviewer") == REVIEWER
          and page.locator("#review-postings li.sel", has_text=ILL).count() == 1)
    check("persist: decisions and completion survive refresh",
          page.locator(".complete .b-ok", has_text="marked reviewed").is_visible()
          and card("ai_draft-0072").locator(".b-split").is_visible() and card("ai_draft-0070").locator(".b-rejected").is_visible())
    shot(page, "24_review_after_refresh")

    # previous / next navigation
    page.click("#next-posting")
    expect(page.locator("#review-postings li.sel")).not_to_have_attribute("data-pid", ILL)
    nxt = page.locator("#review-postings li.sel").get_attribute("data-pid")
    page.click("#prev-posting")
    expect(page.locator("#review-postings li.sel")).to_have_attribute("data-pid", ILL)
    check("review: previous / next navigation", nxt != ILL)

    # stale version in a second tab: a clear conflict, not an overwrite
    page2 = ctx.new_page()
    page2.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page2.goto(BASE + "/", wait_until="networkidle")
    SOC = "greenhouse:duolingo:8810661002"
    page2.locator("#review-postings li", has_text=SOC).click()
    expect(page2.locator("#review-text")).to_contain_text(SOC)
    page.locator("#review-postings li", has_text=SOC).click()
    expect(page.locator("#review-text")).to_contain_text(SOC)
    first_aid = page.locator("#review-cards .item").first.get_attribute("data-item")
    page.locator(f"#review-cards .item[data-item='{first_aid}']").get_by_role("button", name="Accept", exact=True).click(); saved("Saved: accept")
    n_before = nlog()
    page2.locator(f"#review-cards .item[data-item='{first_aid}']").get_by_role("button", name="Reject", exact=True).click(); expected_4xx += 1
    expect(page2.locator("#save-status")).to_contain_text("Conflict")
    check("integrity: stale tab gets a conflict, nothing overwritten", nlog() == n_before)
    shot(page2, "25_review_conflict")
    page2.locator("#save-status").get_by_role("button", name="Reload posting").click()
    expect(page2.locator(f"#review-cards .item[data-item='{first_aid}'] .b-accepted")).to_be_visible()
    check("integrity: reload shows the other tab's decision", True)
    page2.close()

    # export: preview, download, write
    page.click("#export-open")
    page.click("#export-preview")
    expect(page.locator("#export-summary")).to_contain_text("PARTIAL")
    summary = page.text_content("#export-summary")
    check("export: partial preview, not gold, validated", "not gold" in summary and "no problems" in summary, summary[:160])
    with page.expect_download() as dl:
        page.click("#export-dl-skills")
    path = dl.value.path()
    header = Path(path).read_text().splitlines()[0]
    check("export: download skills.csv in the annotation format", header.startswith("snapshot_id,posting_id,annotation_id,skill_statement"), dl.value.suggested_filename)
    page.click("#export-write")
    expect(page.locator("#export-summary .save-status")).to_contain_text("Written (partial, not gold)")
    written = page.text_content("#export-summary .save-status").split(": ", 1)[1].strip()
    check("export: written to a new reviewed folder", written.startswith(str(REVIEWED)) and (Path(written) / "skills.csv").is_file(), written)
    shot(page, "26_export_preview")
    page.click("#export-close")

    # ------------------------------------------------------------ 4. independent evaluation mode
    page.click(".seg button[data-mode=evaluation]")
    expect(page.locator("#eval-gate")).to_be_visible()
    check("evaluation: explicit gate before any text", page.locator("#review-grid").is_hidden() and page.locator("#eval-start").is_disabled())
    shot(page, "27_eval_gate")
    page.check("#eval-confirm"); page.click("#eval-start")
    expect(page.locator("#review-postings li")).to_have_count(80)
    check("evaluation: 80 evaluation postings", True)
    page.locator("#review-postings li", has_text=EVAL_ID).click()
    expect(page.locator("#review-text")).to_contain_text(EVAL_ID)
    expect(page.locator("#review-cards .empty-state")).to_be_visible()
    check("evaluation: empty skill list, no highlights, no AI wording",
          page.locator("#review-text mark").count() == 0 and page.locator("#review-cards .item").count() == 0
          and "AI-generated" not in page.text_content("#review-text"))
    head_text = page.evaluate("() => [...document.querySelectorAll('#review-text > :not(.posting-text)')].map(e => e.textContent).join(' ')")
    check("evaluation: no stray 'null' text in the posting header", "null" not in head_text, head_text[:80])
    shot(page, "28_eval_posting")
    word = page.evaluate("""() => { const t = document.querySelector('#review-text-body').textContent;
        const m = t.match(/[A-Z][a-z]{5,}/); return m ? m[0] : null; }""")
    page.evaluate("""(w) => { const box = document.querySelector('#review-text-body');
        const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT); let n;
        while ((n = walker.nextNode())) { const i = n.data.indexOf(w); if (i >= 0) { const r = document.createRange();
          r.setStart(n, i); r.setEnd(n, i + w.length); const s = getSelection(); s.removeAllRanges(); s.addRange(r); break; } }
        box.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); }""", word)
    page.locator("#review-cards").get_by_role("button", name="Add skill").click()
    check("evaluation: selected text fills evidence", page.input_value("#edit-form [name=evidence_text]") == word, word)
    page.fill("#edit-form [name=skill_statement]", "evaluation browser test skill")
    page.wait_for_timeout(500)
    if page.locator("#edit-form [name=occurrence] option").count() > 2:
        page.select_option("#edit-form [name=occurrence]", value="1")
    page.click("#edit-form .dlg-save"); expect(page.locator("#edit-dialog")).to_be_hidden(); saved("Saved: new skill")
    eitem = page.locator("#review-cards .item").first
    eitem.get_by_role("button", name="Delete", exact=True).click(); saved("Saved: delete")
    eitem = page.locator("#review-cards .item").first
    eitem.get_by_role("button", name="Reopen", exact=True).click(); saved("Saved: reopen")
    page.check("#c-read"); page.check("#c-missing")
    page.locator(".complete button", has_text="Mark posting reviewed").click(); saved("Saved: posting marked reviewed")
    check("evaluation: add, delete, reopen, complete", page.locator(".complete .b-ok", has_text="marked reviewed").is_visible())
    page.click("#export-open"); page.click("#export-preview")
    expect(page.locator("#export-summary")).to_contain_text("PARTIAL")
    check("evaluation: own export, 1/80 reviewed", "1/80 postings marked reviewed" in page.text_content("#export-summary"))
    page.click("#export-close")
    ev_events = [json.loads(l) for l in log.read_text().splitlines() if json.loads(l)["mode"] == "evaluation"]
    check("evaluation: decisions logged in evaluation mode with no draft source",
          ev_events and all(e["source"] == "none" and e["source_skills_sha256"] is None for e in ev_events), f"{len(ev_events)} events")
    for path in [f"/api/review/posting?mode=evaluation&posting_id={EVAL_ID}&reviewer={REVIEWER}",
                 f"/api/review?mode=evaluation&reviewer={REVIEWER}"]:
        r = page.request.get(BASE + path)
        check(f"evaluation: {path.split('?')[0]} refused without the explicit mode header", r.status == 403, str(r.status))
    page.click(".seg button[data-mode=development]")
    expect(page.locator("#review-postings li")).to_have_count(20)
    check("evaluation: switching back shows development drafts again", True)

    # held-out texts via the API from the page context
    for path in [f"/api/corpus/posting?posting_id={EVAL_ID}", f"/api/corpus/posting?posting_id={VARIANT_ID}",
                 f"/api/review/posting?source=ai_revised&posting_id={EVAL_ID}",
                 f"/api/run/posting?run_id=skx-20261007T003601Z&posting_id={EVAL_ID}",
                 f"/api/locate?posting_id={EVAL_ID}&evidence=the"]:
        r = page.request.get(BASE + path)
        check(f"held-out: {path.split('?')[0]} refused", r.status == 403, str(r.status))
    r = page.request.post(BASE + "/api/review/decision", data=json.dumps({"reviewer_id": REVIEWER, "source": "ai_revised",
                          "posting_id": EVAL_ID, "action": "add"}), headers={"Content-Type": "application/json", "X-Dashboard": "1"})
    check("held-out: decision on evaluation posting refused", r.status == 403, str(r.status))

    # narrow viewport layout
    m = browser.new_context(viewport={"width": 390, "height": 844})
    mp = m.new_page()
    mp.goto(BASE + "/", wait_until="networkidle")
    mp.wait_for_selector("#corpus-table tbody tr")
    over = mp.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    check("mobile: no horizontal page scroll (corpus)", over <= 0, f"overflow {over}px")
    mp.screenshot(path=str(SHOTS / "15_mobile_corpus.png"))
    mp.click("button[data-view=extraction]")
    mp.locator("#run-postings li", has_text=RH).click()
    mp.wait_for_selector("#run-detail .item")
    over = mp.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    check("mobile: no horizontal page scroll (extraction)", over <= 0, f"overflow {over}px")
    mp.screenshot(path=str(SHOTS / "16_mobile_extraction.png"))
    mp.click("button[data-view=review]")
    mp.fill("#reviewer", REVIEWER); mp.click("#reviewer-set")
    mp.wait_for_selector("#review-cards .item")
    over = mp.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    check("mobile: no horizontal page scroll (review)", over <= 0, f"overflow {over}px")
    mp.screenshot(path=str(SHOTS / "29_mobile_review.png"))
    m.close()

    # deliberate failures (invalid evidence, missing occurrence, stale-tab conflict) return 400/409; Chrome logs those
    expected = [e for e in errors if "status of 400" in e or "status of 409" in e]
    unexpected = [e for e in errors if e not in expected]
    check("no unexpected console or page errors", not unexpected, "; ".join(unexpected[:5]))
    check("only the deliberate failed requests were logged", len(expected) == expected_4xx, f"{len(expected)} logged / {expected_4xx} deliberate")
    browser.close()

passed = sum(ok for _, ok, _ in results)
print(f"\n{passed}/{len(results)} checks passed")
(S / "pw_results.json").write_text(json.dumps([{"check": n, "pass": ok, "detail": d} for n, ok, d in results], indent=1))
sys.exit(0 if passed == len(results) else 1)
