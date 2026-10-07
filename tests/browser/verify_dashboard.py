"""Browser verification of the Team B dashboard (Playwright driving the system Chrome, headless).

Optional tool, not collected by pytest and not a project dependency. Run it against a dashboard that
was started with a TEMPORARY review directory, so test decisions never reach the real reviews folder:

    python -m venv /tmp/pwvenv && /tmp/pwvenv/bin/pip install playwright        # uses installed Google Chrome
    python src/dashboard.py --port 8765 --reviews-dir /tmp/dash_reviews &
    /tmp/pwvenv/bin/python tests/browser/verify_dashboard.py OUT_DIR /tmp/dash_reviews EVAL_ID VARIANT_ID

OUT_DIR receives shots/*.png and pw_results.json. EVAL_ID is an evaluation posting and VARIANT_ID a
posting grouped with one (both must be refused). The reviewer used is "pwtest".
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

S, REVIEWS, EVAL_ID, VARIANT_ID = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
SHOTS = S / "shots"
BASE = "http://127.0.0.1:8765"
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
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
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

    # ------------------------------------------------------------ 3. review
    page.click("button[data-view=review]")
    page.fill("#reviewer", REVIEWER)
    page.dispatch_event("#reviewer", "change")
    expect(page.locator("#review-msg")).to_contain_text(f"Reviewing as {REVIEWER}")
    check("review: AI drafts label", "AI-generated, unreviewed drafts" in page.text_content("#view-review .banner"))
    check("review: 20 development postings", page.locator("#review-postings li").count() == 20)
    page.locator("#review-postings li", has_text=DUO).click()
    expect(page.locator("#review-detail .item").first).to_be_visible()
    ritems = page.locator("#review-detail .item")
    n0 = ritems.count()
    check("review: DISCUSS flags visible", page.locator("#review-detail .b-discuss").count() > 0,
          f"{page.locator('#review-detail .b-discuss').count()} flagged")
    shot(page, "09_review_posting")

    def item(i):
        return page.locator("#review-detail .item").nth(i)

    def wait_state(i, state):
        expect(item(i).locator(f".b-{state}").first).to_be_visible()

    first_id = item(0).get_attribute("data-item")
    item(0).get_by_role("button", name="Accept").click(); wait_state(0, "accepted")
    check("review: accept", True, first_id)
    item(1).get_by_role("button", name="Reject").click(); wait_state(1, "rejected")
    check("review: reject", True, item(1).get_attribute("data-item"))
    check("review: no redundant Accept on accepted / Reject on rejected",
          item(0).get_by_role("button", name="Accept").count() == 0 and item(1).get_by_role("button", name="Reject").count() == 0)
    item(0).get_by_role("button", name="Reopen").click(); wait_state(0, "pending")
    check("review: reopen", True)
    item(0).get_by_role("button", name="Accept").click(); wait_state(0, "accepted")
    item(2).get_by_role("button", name="Edit").click()
    expect(page.locator("#edit-dialog")).to_be_visible()
    page.fill("#edit-form [name=skill_statement]", "edited by browser test")
    page.click("#edit-save")
    expect(page.locator("#edit-dialog")).to_be_hidden()
    wait_state(2, "edited")
    check("review: edit", "edited by browser test" in item(2).text_content())
    shot(page, "10_review_after_actions")

    # add skill: invalid evidence, then repeated evidence needing an occurrence
    page.get_by_role("button", name="Add skill").click()
    page.fill("#edit-form [name=skill_statement]", "browser-test addition")
    page.fill("#edit-form [name=evidence_text]", "this phrase is not in the posting")
    page.wait_for_timeout(500)
    expect(page.locator("#edit-error")).to_contain_text("Not found")
    page.click("#edit-save")
    expect(page.locator("#edit-error")).to_contain_text("does not occur exactly")
    check("review: invalid evidence rejected with error", True, page.text_content("#edit-error"))
    shot(page, "11_review_invalid_evidence")
    page.fill("#edit-form [name=evidence_text]", "Duolingo")
    page.wait_for_timeout(600)
    opts = page.locator("#edit-form [name=occurrence] option").count() - 1
    expect(page.locator("#edit-error")).to_contain_text("choose an occurrence")
    page.select_option("#edit-form [name=occurrence]", value="")
    page.click("#edit-save")
    expect(page.locator("#edit-error")).to_contain_text("occurs")
    check("review: repeated evidence requires an occurrence", opts > 1, f"{opts} occurrences offered")
    shot(page, "12_review_repeated_evidence")
    dw = page.locator("#edit-dialog").evaluate("d => [d.scrollWidth, d.clientWidth]")
    check("review: dialog content fits (no clipping)", dw[0] <= dw[1] + 1, f"{dw}")
    page.select_option("#edit-form [name=occurrence]", value="2")
    page.click("#edit-save")
    expect(page.locator("#edit-dialog")).to_be_hidden()
    expect(page.locator("#review-detail .b-added").first).to_be_visible()
    check("review: add skill with chosen occurrence", page.locator("#review-detail .item").count() == n0 + 1)

    # add skill from a text selection in the posting
    page.evaluate("""() => { const box = document.querySelector('#review-detail .posting-text');
        const w = document.createTreeWalker(box, NodeFilter.SHOW_TEXT); let n;
        while ((n = w.nextNode())) { const i = n.data.indexOf('Partner with engineers'); if (i >= 0) {
          const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 'Partner with engineers'.length);
          const s = getSelection(); s.removeAllRanges(); s.addRange(r); break; } }
        box.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); }""")
    page.get_by_role("button", name="Add skill").click()
    ev = page.input_value("#edit-form [name=evidence_text]")
    check("review: selected text prefills evidence", ev == "Partner with engineers", repr(ev))
    page.fill("#edit-form [name=skill_statement]", "cross-functional partnering (browser test)")
    page.click("#edit-save")
    expect(page.locator("#edit-dialog")).to_be_hidden()
    check("review: add from selection", page.locator("#review-detail .item").count() == n0 + 2)
    shot(page, "13_review_added")

    # persistence after refresh
    page.reload(wait_until="networkidle")
    expect(page.locator("#view-review")).to_be_visible()  # last tab remembered
    check("persist: reviewer ID remembered", page.input_value("#reviewer") == REVIEWER)
    expect(page.locator("#snapshot")).to_have_text("20261006T171338Z")
    check("header: snapshot label filled when opening on the review tab", True)
    page.locator("#review-postings li", has_text=DUO).click()
    expect(page.locator("#review-detail .item").first).to_be_visible()
    states = page.eval_on_selector_all("#review-detail .item", "items => items.map(i => [i.dataset.item, [...i.querySelectorAll('.badge')].map(b => b.textContent)[0]])")
    st = dict(states)
    check("persist: decisions survive refresh",
          st.get(first_id) == "accepted" and list(st.values()).count("added") == 2 and "edited" in st.values() and "rejected" in st.values(),
          json.dumps(states[:3]))
    shot(page, "14_review_after_refresh")
    lines = [json.loads(l) for l in (REVIEWS / REVIEWER / "decisions.jsonl").read_text().splitlines()]
    check("persist: decisions written to the temporary review dir only",
          [d["action"] for d in lines] == ["accept", "reject", "reopen", "accept", "edit", "add", "add"],
          f"{len(lines)} lines in {REVIEWS}")

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
    m.close()

    # the two saves the test deliberately sent with invalid evidence return 400; Chrome logs those fetches
    expected = [e for e in errors if "status of 400" in e]
    unexpected = [e for e in errors if "status of 400" not in e]
    check("no unexpected console or page errors", not unexpected, "; ".join(unexpected[:5]))
    check("only the 2 deliberate invalid-evidence requests logged 400", len(expected) == 2, f"{len(expected)} x 400")
    browser.close()

passed = sum(ok for _, ok, _ in results)
print(f"\n{passed}/{len(results)} checks passed")
(S / "pw_results.json").write_text(json.dumps([{"check": n, "pass": ok, "detail": d} for n, ok, d in results], indent=1))
sys.exit(0 if passed == len(results) else 1)
