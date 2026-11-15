import datetime as dt
import unittest

from signalpost import agent, web

ORG = "923609016"

HOME = """<html><head><title>Testselskap AS - Oslo</title>
<link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body>
<h1>Testselskap AS</h1><p>Vi leverer tjenester fra Oslo til hele landet. Kontakt oss for mer informasjon om det vi tilbyr.</p>
<a href="/karriere">Karriere</a><a href="/nyheter">Nyheter</a>
<a href="https://www.linkedin.com/company/testselskap">LinkedIn</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">Share</a>
<footer>Testselskap AS, org.nr 923 609 016 MVA, Oslo</footer></body></html>"""
FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Ny avtale signert</title><link>https://testselskap.no/nyheter/avtale</link><pubDate>Mon, 03 Nov 2025 09:00:00 +0100</pubDate></item>
<item><title>Eldre sak</title><link>https://testselskap.no/nyheter/eldre</link><pubDate>Mon, 03 Mar 2025 09:00:00 +0100</pubDate></item>
<item><title>Fremmed sak</title><link>https://other.com/x</link><pubDate>Tue, 04 Nov 2025 09:00:00 +0100</pubDate></item>
</channel></rss>"""
JOBS = """<html><body><h1>Karriere</h1>
<a href="/stillinger/utvikler-backend">Backend-utvikler</a><a href="/stillinger/">Ledige stillinger</a>
<a href="/jobb/prosjektleder-oslo">Prosjektleder Oslo</a></body></html>"""
DIRECTORY = "<html><title>Firmaoversikt</title><body>" + ("Selskap 923 609 016 og 914 778 271 og 987 654 321 og 810 034 882 og 923 609 024 og 999 999 999. " * 3) + "Testselskap AS Oslo</body></html>"
OTHER = "<html><title>Annet Selskap AS</title><body><h1>Annet Selskap AS</h1><p>Org.nr 914 778 271. Vi holder til i Bergen og tilbyr mange ulike tjenester til kunder i hele regionen.</p></body></html>"
NAME_TOWN = ("<html><title>Testselskap AS</title><body><h1>Testselskap AS</h1><p>Testselskap AS holder til i Oslo og leverer "
             "tjenester til bedrifter over hele landet, med mange års erfaring.</p></body></html>")
NAME_ONLY = ("<html><title>Testselskap AS</title><body><h1>Testselskap AS</h1><p>Testselskap AS leverer tjenester til bedrifter "
             "over hele landet, med mange års erfaring i bransjen og en lang rekke kunder.</p></body></html>")


class FakeClient:
    def __init__(self, pages):
        self.pages, self.requests_made, self.seen = pages, 0, []

    def get_text(self, url, max_bytes=0):
        self.requests_made += 1
        self.seen.append(url)
        return (200, self.pages[url], url) if url in self.pages else (404, "", url)


def profile(code="AS"):
    return {"orgnr": ORG, "register_site": "testselskap.no", "facts": {
        "name": {"value": "Testselskap AS", "source_url": "u"},
        "legal_form": {"value": "Aksjeselskap", "code": code},
        "municipality": {"value": "OSLO"},
        "business_address": {"value": "Gate 1, 0150 OSLO"},
    }, "explanation": ["Matched."], "history": [], "changes": []}


class WebTests(unittest.TestCase):
    today = dt.date(2025, 11, 20)

    def pages(self):
        return {"https://testselskap.no/": HOME, "https://testselskap.no/feed.xml": FEED,
                "https://testselskap.no/karriere": JOBS}

    def run_enrich(self, pages, **kw):
        return web.enrich(FakeClient(pages), kw.pop("p", None) or profile(), kw.pop("searcher", None), today=kw.pop("today", self.today))

    def test_verified_site_news_jobs_social(self):
        facts, notes, status = self.run_enrich(self.pages())
        self.assertEqual(status, "verified")
        self.assertEqual(facts["own_website"]["match"], "orgnr_on_page")
        self.assertIn("923 609 016", facts["own_website"]["evidence"])
        self.assertEqual(facts["news_latest"]["value"], "Ny avtale signert")
        self.assertEqual(facts["news_latest"]["as_of"], "2025-11-03")
        self.assertTrue(facts["news_latest"]["source_url"].startswith("https://testselskap.no/"))
        self.assertEqual(facts["open_positions"]["value"], ["Backend-utvikler", "Prosjektleder Oslo"])
        self.assertIn("linkedin.com/company", facts["social_linkedin"]["value"])
        self.assertNotIn("social_facebook", facts)  # a share button is not a company page

    def test_other_company_page_is_rejected(self):
        facts, notes, status = self.run_enrich({"https://testselskap.no/": OTHER})
        self.assertEqual((facts, status), ({}, "no_site"))
        self.assertTrue(any("different organisation number" in n for n in notes))

    def test_directory_page_is_rejected(self):
        facts, _, _ = self.run_enrich({"https://testselskap.no/": DIRECTORY})
        self.assertEqual(facts, {})

    def test_name_and_town_without_number(self):
        facts, _, _ = self.run_enrich({"https://testselskap.no/": NAME_TOWN})
        self.assertEqual(facts["own_website"]["match"], "name_and_town")

    def test_name_without_town_is_rejected(self):
        facts, _, _ = self.run_enrich({"https://testselskap.no/": NAME_ONLY})
        self.assertEqual(facts, {})

    def test_sole_proprietorship_needs_the_number(self):
        facts, _, _ = self.run_enrich({"https://testselskap.no/": NAME_TOWN}, p=profile("ENK"))
        self.assertEqual(facts, {})

    def test_blocked_directory_hosts(self):
        self.assertTrue(web.blocked("https://www.proff.no/selskap/x"))
        self.assertTrue(web.blocked("https://no.linkedin.com/company/x"))
        self.assertFalse(web.blocked("https://testselskap.no/"))

    def test_news_without_date_is_not_published(self):
        pages = self.pages()
        pages["https://testselskap.no/feed.xml"] = "<rss><channel><item><title>X</title><link>https://testselskap.no/a</link></item></channel></rss>"
        facts, notes, _ = self.run_enrich(pages)
        self.assertNotIn("news_latest", facts)
        self.assertTrue(any("No dated news" in n for n in notes))

    def test_old_news_is_not_published(self):
        facts, _, _ = self.run_enrich(self.pages(), today=dt.date(2028, 1, 1))
        self.assertNotIn("news_latest", facts)

    def test_html_news_page_with_time_tag(self):
        home = HOME.replace('<link rel="alternate" type="application/rss+xml" href="/feed.xml">', "")
        news = '<article><time datetime="2025-10-01">1. oktober 2025</time><a href="/nyheter/a">Vi flytter til nytt kontor</a></article>'
        facts, _, _ = self.run_enrich({"https://testselskap.no/": home, "https://testselskap.no/nyheter": news})
        self.assertEqual(facts["news_latest"]["value"], "Vi flytter til nytt kontor")
        self.assertEqual(facts["news_latest"]["as_of"], "2025-10-01")

    def test_jsonld_job_posting_and_expired_posting(self):
        jobs = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Sykepleier","datePosted":"2025-11-01",'
                '"validThrough":"2099-01-01","url":"https://testselskap.no/j/1"}</script>'
                '<script type="application/ld+json">{"@type":"JobPosting","title":"Utgått","validThrough":"2020-01-01"}</script>')
        pages = self.pages()
        pages["https://testselskap.no/karriere"] = "<html><body>" + jobs + "</body></html>"
        facts, _, _ = self.run_enrich(pages)
        self.assertEqual(facts["open_positions"]["value"], ["Sykepleier"])
        self.assertEqual(facts["open_positions"]["as_of"], "2025-11-01")

    def test_merge_summary_not_found_and_failed_lookup_keeps_old(self):
        p = profile()
        facts, notes, status = self.run_enrich(self.pages(), p=p)
        web.merge_web(p, facts, notes, status)
        self.assertIn("own_website", p["facts"])
        self.assertIn("Testselskap AS", p["facts"]["summary"]["value"])
        self.assertNotIn("—", p["facts"]["summary"]["value"])
        self.assertEqual(p["not_found"], [])
        before = dict(p["facts"]["own_website"])
        web.merge_web(p, {}, ["Could not open x"], "error")
        self.assertEqual(p["facts"]["own_website"], before)
        web.merge_web(p, {}, ["no site"], "no_site")
        self.assertNotIn("own_website", p["facts"])
        self.assertIn("a verified own website", p["not_found"])
        self.assertTrue(any(c["field"] == "own_website" and c["new"] is None for c in p["history"]))

    def test_search_candidates_are_filtered(self):
        class S:
            queries = 0
            def search(self, q):
                return ["https://www.proff.no/x", "https://testselskap.no/side", "https://no.linkedin.com/c"]
        p = profile()
        p["register_site"] = ""
        pages = self.pages()
        pages["https://www.testselskap.no/"] = pages["https://testselskap.no/"]  # domain guess variant
        c = FakeClient(pages)
        facts, _, status = web.enrich(c, p, S(), today=self.today)
        self.assertEqual(status, "verified")
        self.assertFalse(any("proff" in u for u in c.seen))

    def test_ddg_parser(self):
        html = '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftestselskap.no%2F&rut=1">x</a>'
        self.assertEqual(web.parse_ddg(html), ["https://testselskap.no/"])

    def test_prefetch_keeps_only_requested_numbers(self):
        class C:
            def get_json(self, url, params=None, headers=None):
                return 200, {"_embedded": {"enheter": [{"organisasjonsnummer": ORG, "navn": "A"},
                                                       {"organisasjonsnummer": "914778271", "navn": "B"}]}}
        self.assertEqual(list(agent.prefetch(C(), [ORG, "123456789"])), [ORG])


if __name__ == "__main__":
    unittest.main()


class RunWebTests(unittest.TestCase):
    def test_run_with_web_step_end_to_end(self):
        import json, tempfile
        from signalpost import runner
        from test_agent import Fake, routes, GOOD

        class Both(Fake):
            def __init__(self, routes_, pages):
                super().__init__(routes_)
                self.pages, self.text_calls = pages, 0

            def get_text(self, url, max_bytes=0):
                self.text_calls += 1
                self.requests_made += 1
                return (200, self.pages[url], url) if url in self.pages else (404, "", url)

        home_content = HOME.replace("923 609 016", " ".join([GOOD[:3], GOOD[3:6], GOOD[6:]]))
        pages = {"https://testselskap.no/": home_content,
                 "https://www.testselskap.no/": home_content}
        client = Both(routes(), pages)
        with tempfile.TemporaryDirectory() as tmp:
            profiles, report = runner.run([GOOD], tmp, client=client, log=lambda *_: None,
                                          searcher=type("S", (), {"queries": 0, "cost_usd": 0.0, "search": lambda s, q: ["https://testselskap.no/x"]})())
            saved = json.load(open(f"{tmp}/profiles/{GOOD}.json"))
        self.assertEqual(report["web_step"]["verified"], 1)
        self.assertEqual(report["profiles_with_verified_website"], 1)
        self.assertIn("own_website", saved["facts"])
        self.assertIn("summary", saved["facts"])
        self.assertIn("envelope", saved)
