"""Browser end-to-end check of the viewer. Needs: playwright (pip), a built ui/dist, and a run folder.

    python -m signalpost serve --out out --port 8124 &
    python tests/ui_e2e.py http://127.0.0.1:8124/

Drives every control with real mouse and keyboard input and asserts on what the page does.
"""

import json
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8124/"
results = []
ROWBTN = "[role=listitem] [data-swipe-surface] > button:not([data-swipe-toggle])"


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def rows(pg):
    return pg.locator("[role=listitem]").count()


def stored(pg, key):
    return json.loads(pg.evaluate(f"localStorage.getItem('{key}') || '[]'"))


def send_command(pg, text):
    bar = pg.locator("textarea[aria-label=Prompt]")
    bar.click()
    bar.fill(text)
    bar.press("Enter")
    pg.wait_for_timeout(250)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 1360, "height": 900}, accept_downloads=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=URL.rstrip("/"))
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(URL)
        pg.wait_for_selector("[role=listitem]")
        pg.wait_for_timeout(1900)

        total = rows(pg)
        check("list renders profiles", total > 5, f"rows={total}")
        check("overview shows by default", pg.get_by_text("every fact sourced").count() == 1)
        check("hero stat shows the real number without scrolling", pg.locator("dd .num .sr-only").first.inner_text().strip() == str(total))
        check("webgl hero canvas present", pg.locator("canvas").count() >= 1)

        # --- open a company with a real mouse click
        first_name = pg.locator(ROWBTN).first.locator("span").first.inner_text()
        pg.locator(ROWBTN).first.click()
        pg.wait_for_timeout(500)
        check("click on a row opens the profile", pg.locator("article h2").inner_text() == first_name)
        check("url hash follows the selection", "#" in pg.url and pg.url.split("#")[1].isdigit())
        check("every fact shows a source link", pg.locator("article dd a[href^='https://data.brreg.no']").count() >= 3)

        # --- swipe a row to reveal Watch, then use it
        row = pg.locator("[role=listitem]").nth(2)
        box = row.bounding_box()
        pg.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + 30)
        pg.mouse.down()
        pg.mouse.move(box["x"] + box["width"] * 0.35, box["y"] + 30, steps=12)
        pg.mouse.up()
        pg.wait_for_timeout(500)
        watch = row.get_by_role("button", name="Watch")
        check("swiping a row reveals actions", watch.count() == 1 and watch.is_visible())
        target_id = row.locator("[data-orgnr]").get_attribute("data-orgnr")
        watch.click()
        pg.wait_for_timeout(400)
        check("swipe action Watch is stored", target_id in stored(pg, "signalpost.watched"), str(stored(pg, "signalpost.watched")))
        check("row now says watching", "watching" in row.inner_text())
        check("dragging a row did not open it", pg.locator("article h2").inner_text() == first_name)

        # --- command bar
        send_command(pg, first_name.split()[0])
        pg.wait_for_timeout(300)
        n_name = rows(pg)
        check("search by name filters the list", 1 <= n_name < total, f"{n_name}/{total}")
        send_command(pg, "/clear")
        check("/clear resets everything", rows(pg) == total)
        send_command(pg, "/bankrupt")
        n_bank = rows(pg)
        check("/bankrupt filters by status", 0 < n_bank < total, str(n_bank))
        check("summary line shows filters applied", pg.get_by_text("Clear all").count() >= 1)
        pg.get_by_text("Clear all").first.click()
        check("Clear all restores the list", rows(pg) == total)
        send_command(pg, "/nonsense")
        check("unknown command gets a message", pg.get_by_text("Unknown command /nonsense").count() == 1)
        send_command(pg, "912000028")
        check("search by organisation number", rows(pg) == 1)
        send_command(pg, "/clear")

        # --- filters panel
        pg.get_by_role("button", name="Filters and lookup").click()
        pg.wait_for_timeout(300)
        slots = pg.get_by_label("Organisation number, nine digits")
        check("filters panel opens", slots.count() >= 1)

        def type_number(num):
            slots.first.click()
            for _ in range(9):
                pg.keyboard.press("Backspace")
            pg.keyboard.type(num, delay=40)
            pg.wait_for_timeout(500)

        type_number("123456789")
        check("code slots reject a bad check digit", pg.get_by_text("check digit does not match").count() == 1)
        type_number("923609016")
        check("code slots say a valid number is not in this run", pg.get_by_text("not in this run").count() == 1)
        type_number("912000028")
        pg.wait_for_timeout(400)
        check("code slots open a number that is in the run", "912000028" in pg.locator("article").first.inner_text())

        # status select
        pg.get_by_role("button", name="Filter by status").click() if pg.get_by_role("button", name="Filter by status").count() else pg.locator("[aria-label='Filter by status']").first.click()
        pg.wait_for_timeout(300)
        pg.get_by_role("option", name="bankrupt").first.click()
        pg.wait_for_timeout(300)
        check("glide select filters by status", rows(pg) == n_bank, f"{rows(pg)} vs {n_bank}")
        pg.get_by_text("Clear all").first.click()

        # legal form chips
        chip = pg.get_by_role("radio", name="ENK")
        if chip.count():
            chip.first.click()
            pg.wait_for_timeout(300)
            n_enk = rows(pg)
            check("jelly radio filters by legal form", 0 < n_enk < total, str(n_enk))
            pg.get_by_role("radio", name="All").first.click()
            pg.wait_for_timeout(300)
            check("legal form All restores", rows(pg) == total)
        else:
            check("jelly radio present", False, "no ENK chip")

        # switch
        sw = pg.get_by_role("switch")
        sw.first.click()
        pg.wait_for_timeout(400)
        n_changed = rows(pg)
        check("squish switch limits to changed profiles", 0 < n_changed <= total, str(n_changed))
        sw.first.click()
        pg.wait_for_timeout(400)
        check("switch off restores", rows(pg) == total)

        # sort
        pg.get_by_role("radio", name="Changes").first.click() if pg.get_by_role("radio", name="Changes").count() else pg.get_by_text("Changes", exact=True).first.click()
        pg.wait_for_timeout(500)
        top = pg.locator("[role=listitem]").first.inner_text()
        check("rubber segment sorts by changes", "2 changes" in top or "3 changes" in top, top.replace("\n", " "))
        pg.get_by_role("radio", name="Name").first.click() if pg.get_by_role("radio", name="Name").count() else pg.get_by_text("Name", exact=True).first.click()

        # export tree
        pg.get_by_text("Companies in the list").first.click()
        pg.wait_for_timeout(500)
        with pg.expect_download() as dl:
            pg.get_by_text("CSV summary").first.click()
        csv_path = dl.value.path()
        text = open(csv_path, encoding="utf-8").read()
        check("export CSV downloads with header and rows", text.startswith("orgnr,name,status") and text.count("\n") == total + 1, f"lines={text.count(chr(10))}")
        with pg.expect_download() as dl2:
            pg.get_by_text("Profile as JSON").first.click()
        prof = json.loads(open(dl2.value.path(), encoding="utf-8").read())
        check("export profile JSON matches the open company", prof["orgnr"] == "912000028", prof.get("orgnr"))

        pg.get_by_role("button", name="Filters and lookup").click()

        # --- detail actions
        bell = pg.get_by_role("button", name="Watch", exact=False)
        pg.locator("article").get_by_role("button", name="Watch").first.click()
        pg.wait_for_timeout(600)
        check("bell toggle watches the company", "912000028" in stored(pg, "signalpost.watched"))
        pg.locator("article").get_by_role("button", name="Mark reviewed").click()
        pg.wait_for_timeout(500)
        check("fuse button marks reviewed immediately", "912000028" in stored(pg, "signalpost.reviewed"))
        undo = pg.locator("article").get_by_role("button", name="Undo")
        if undo.count():
            undo.first.click()
            pg.wait_for_timeout(500)
            check("undo inside the window reverts", "912000028" not in stored(pg, "signalpost.reviewed"))
        else:
            check("undo button appears", False)

        # section nav
        nav = pg.locator("nav[aria-label='On this profile']")
        check("line sidebar lists sections", nav.count() == 1 and "Changes" in nav.inner_text(), nav.inner_text()[:80] if nav.count() else "")
        before = pg.evaluate("window.scrollY")
        nav.get_by_text("Matching").first.click()
        pg.wait_for_timeout(1200)
        check("line sidebar scrolls to a section", pg.evaluate("window.scrollY") > before)

        # --- overview widgets
        pg.get_by_role("button", name="Signalpost overview").click()
        pg.wait_for_timeout(800)
        check("brand returns to overview", pg.get_by_text("every fact sourced").count() == 1)
        wl = pg.locator("section[aria-labelledby=watch-h]")
        check("folder float shows the watchlist", "company" in wl.inner_text() or "companies" in wl.inner_text())
        toggle = wl.locator("button[aria-expanded]")
        toggle.click()
        pg.wait_for_timeout(1000)
        names = [t for t in wl.locator("button:not([aria-expanded])").all_inner_texts() if t.strip()]
        check("folder opens and lists watched companies", len(names) >= 2, str(names)[:160])
        wl.locator("button:not([aria-expanded])").first.click(force=True)
        pg.wait_for_timeout(700)
        check("choosing a watched company opens its profile", pg.locator("article").count() == 1)
        pg.get_by_role("button", name="Signalpost overview").click()
        pg.wait_for_timeout(800)

        # shredder: drag the top card into the slit
        reviewed_before = len(stored(pg, "signalpost.reviewed"))
        card = pg.locator("section[aria-labelledby=queue-h] li").last
        cb = card.bounding_box()
        slit = pg.locator("section[aria-labelledby=queue-h] canvas").first.bounding_box()
        pg.mouse.move(cb["x"] + 60, cb["y"] + 28)
        pg.mouse.down()
        pg.mouse.move(cb["x"] + 60, cb["y"] + 80, steps=8)
        pg.mouse.move(cb["x"] + 60, slit["y"] + slit["height"] - 30, steps=20)
        pg.mouse.up()
        pg.wait_for_timeout(2500)
        check("shredder marks a dragged card reviewed", len(stored(pg, "signalpost.reviewed")) == reviewed_before + 1, f"{reviewed_before}->{len(stored(pg, 'signalpost.reviewed'))}")

        # header chip swap
        chip_btn = pg.locator("header [class*=isolate]").first
        t1 = pg.locator("header").inner_text()
        chip_btn.click()
        pg.wait_for_timeout(1400)
        t2 = pg.locator("header").inner_text()
        check("pixel swap toggles the run summary", t1 != t2 and "requests" in (t1 + t2), f"{t1!r} / {t2!r}")

        # persistence
        pg.reload()
        pg.wait_for_selector("[role=listitem]")
        check("watch and review state survives a reload", "912000028" in stored(pg, "signalpost.watched"))

        # keyboard path on a row
        pg.locator(ROWBTN).nth(1).focus()
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(400)
        check("Enter on a focused row opens it", pg.locator("article").count() == 1)

        check("no page errors or console errors", not errors, "; ".join(errors)[:300])
        b.close()

        # --- mobile
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        m = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True).new_page()
        m.goto(URL)
        m.wait_for_selector("[role=listitem]")
        m.wait_for_timeout(800)
        check("mobile has no horizontal scroll", not m.evaluate("document.documentElement.scrollWidth>innerWidth"))
        m.locator(ROWBTN).nth(3).click()
        m.wait_for_timeout(900)
        check("mobile row tap opens the profile and scrolls to it", m.locator("article").count() == 1 and m.evaluate("window.scrollY") > 300)
        b.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
