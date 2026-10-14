import copy
import json
import os
import tempfile
import unittest

from signalpost import agent, orgnr, runner, ui

GOOD = "923609016"   # valid check digit
OTHER = "984851006"  # valid check digit

ENTITY = {
    "organisasjonsnummer": GOOD, "navn": "TESTSELSKAP AS",
    "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
    "registreringsdatoEnhetsregisteret": "1995-01-02", "stiftelsesdato": "1994-12-01",
    "forretningsadresse": {"adresse": ["Testveien 1"], "postnummer": "0150", "poststed": "OSLO",
                           "kommune": "OSLO", "land": "Norge", "landkode": "NO"},
    "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmeringstjenester"},
    "antallAnsatte": 42, "registrertIMvaregisteret": True, "konkurs": False,
}
ROLES = {"rollegrupper": [
    {"roller": [
        {"type": {"kode": "DAGL"}, "person": {"navn": {"fornavn": "Kari", "etternavn": "Nordmann"}, "fodselsdato": "1970-01-01"}},
        {"type": {"kode": "LEDE"}, "person": {"navn": {"fornavn": "Ola", "etternavn": "Hansen"}}},
        {"type": {"kode": "MEDL"}, "person": {"navn": {"fornavn": "Eva", "etternavn": "Berg"}}, "fratraadt": True},
        {"type": {"kode": "REVI"}, "enhet": {"navn": ["REVISJON AS"]}},
    ]}]}
ACCOUNTS = [
    {"virksomhet": {"organisasjonsnummer": GOOD}, "valuta": "NOK",
     "regnskapsperiode": {"fraDato": "2023-01-01", "tilDato": "2023-12-31"},
     "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 1000.0}, "driftsresultat": 100.0}, "aarsresultat": 80.0},
     "eiendeler": {"sumEiendeler": 5000.0}, "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": 2000.0}}},
    {"virksomhet": {"organisasjonsnummer": GOOD}, "valuta": "NOK",
     "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
     "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 1200.0}, "driftsresultat": 150.0}, "aarsresultat": 90.0},
     "eiendeler": {"sumEiendeler": 5500.0}, "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": 2100.0}}},
]


class Fake:
    """Stands in for the HTTP client. Routes by URL suffix."""

    def __init__(self, routes):
        self.routes = routes
        self.requests_made = 0

    def get_json(self, url, params=None):
        self.requests_made += 1
        for suffix, answer in self.routes.items():
            if url.endswith(suffix):
                return answer
        return 404, None


def routes(entity=ENTITY, roles=ROLES, accounts=ACCOUNTS):
    return {
        f"/enheter/{GOOD}": (200, entity),
        f"/enheter/{GOOD}/roller": (200, roles),
        "/underenheter": (200, {"page": {"totalElements": 3}}),
        f"/regnskap/{GOOD}": (200, accounts),
    }


class OrgnrTests(unittest.TestCase):
    def test_checksum(self):
        self.assertTrue(orgnr.is_valid(GOOD))
        self.assertTrue(orgnr.is_valid("923 609 016"))
        self.assertFalse(orgnr.is_valid("923609017"))
        self.assertFalse(orgnr.is_valid("12345"))
        self.assertEqual(orgnr.normalize("NO 923609016 MVA"), GOOD)


class ProfileTests(unittest.TestCase):
    def test_facts_have_source_and_dates(self):
        p = agent.build_profile(Fake(routes()), GOOD)
        self.assertEqual(p["status"], "active")
        self.assertTrue(p["match"]["matches_request"])
        for key, fact in p["facts"].items():
            self.assertIn(GOOD, fact["source_url"], key)
            self.assertTrue(fact["retrieved_at"], key)
        self.assertEqual(p["facts"]["revenue"]["value"], 1200.0)
        self.assertEqual(p["facts"]["revenue"]["as_of"], "2024-12-31")
        self.assertEqual(p["facts"]["ceo"]["value"], "Kari Nordmann")
        self.assertEqual(p["facts"]["board_size"]["value"], 1)  # resigned member excluded
        self.assertEqual(p["facts"]["auditor"]["value"], "REVISJON AS")
        self.assertEqual(p["facts"]["sub_units"]["value"], 3)
        self.assertNotIn("1970", json.dumps(p))  # birth dates never stored

    def test_wrong_company_is_rejected(self):
        wrong = copy.deepcopy(ENTITY)
        wrong["organisasjonsnummer"] = OTHER
        p = agent.build_profile(Fake(routes(entity=wrong)), GOOD)
        self.assertEqual(p["status"], "rejected")
        self.assertEqual(p["facts"], {})

    def test_accounts_for_other_company_are_dropped(self):
        foreign = copy.deepcopy(ACCOUNTS)
        for item in foreign:
            item["virksomhet"]["organisasjonsnummer"] = OTHER
        p = agent.build_profile(Fake(routes(accounts=foreign)), GOOD)
        self.assertNotIn("revenue", p["facts"])

    def test_no_invented_financials(self):
        p = agent.build_profile(Fake({**routes(), f"/regnskap/{GOOD}": (404, None)}), GOOD)
        for key in ("revenue", "net_result", "total_assets", "equity", "operating_result"):
            self.assertNotIn(key, p["facts"])
        self.assertTrue(any("annual accounts" in n.lower() for n in p["explanation"]))

    def test_invalid_number_costs_no_requests(self):
        fake = Fake(routes())
        p = agent.build_profile(fake, "923609017")
        self.assertEqual(p["status"], "rejected")
        self.assertEqual(fake.requests_made, 0)

    def test_deleted_entity(self):
        r = routes()
        r[f"/enheter/{GOOD}"] = (410, {"organisasjonsnummer": GOOD, "slettedato": "2025-03-01"})
        p = agent.build_profile(Fake(r), GOOD)
        self.assertEqual(p["status"], "deleted")

    def test_subunit_fallback(self):
        sub = {"organisasjonsnummer": GOOD, "navn": "AVDELING", "beliggenhetsadresse": {"adresse": ["Veien 2"], "postnummer": "5003", "poststed": "BERGEN", "kommune": "BERGEN"}}
        r = {f"/enheter/{GOOD}": (404, None), f"/underenheter/{GOOD}": (200, sub),
             f"/regnskap/{GOOD}": (404, None)}
        p = agent.build_profile(Fake(r), GOOD)
        self.assertEqual(p["kind"], "underenhet")
        self.assertEqual(p["facts"]["business_address"]["value"], "Veien 2, 5003 BERGEN")

    def test_refresh_detects_change_and_keeps_first_seen(self):
        first = agent.build_profile(Fake(routes()), GOOD)
        changed = copy.deepcopy(ENTITY)
        changed["antallAnsatte"] = 55
        second = agent.build_profile(Fake(routes(entity=changed)), GOOD, previous=first)
        fields = {c["field"]: c for c in second["changes"]}
        self.assertEqual(fields["employees"]["old"], 42)
        self.assertEqual(fields["employees"]["new"], 55)
        self.assertEqual(second["facts"]["name"]["first_seen"], first["facts"]["name"]["first_seen"])
        self.assertEqual(second["facts"]["name"]["last_changed"], first["facts"]["name"]["last_changed"])

    def test_failed_refresh_keeps_previous(self):
        first = agent.build_profile(Fake(routes()), GOOD)
        down = Fake({f"/enheter/{GOOD}": (503, None)})
        second = agent.build_profile(down, GOOD, previous=first)
        self.assertEqual(second["facts"]["name"]["value"], "TESTSELSKAP AS")
        self.assertIn("refresh_note", second)


class RunTests(unittest.TestCase):
    def test_run_and_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles, report = runner.run([GOOD, "923609017"], tmp, client=Fake(routes()), log=lambda *_: None)
            self.assertEqual(report["profiles_written"], 2)
            self.assertEqual(report["external_api_cost_usd"], 0.0)
            page = ui.build(tmp)
            html = open(page, encoding="utf-8").read()
            self.assertIn("TESTSELSKAP AS", html)
            self.assertNotIn("—", html)  # no em-dashes anywhere on the page


if __name__ == "__main__":
    unittest.main()
