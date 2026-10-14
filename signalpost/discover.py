"""Pick a spread of organisation numbers from the register for building a 1,000+ profile set."""

import random

from .http import Client

BASE = "https://data.brreg.no/enhetsregisteret/api/enheter"
FORMS = ["AS", "ENK", "NUF", "ANS", "DA", "SA", "FLI", "STI", "ASA", "BRL", "KS", "ORGL"]


def discover(n, seed=2026, client=None, log=print):
    """Random pages across legal forms. The API caps paging at 10,000 rows per query."""
    client = client or Client(max_requests=400)
    rng = random.Random(seed)
    found = []
    seen = set()
    attempts = 0
    while len(found) < n and attempts < 120:
        attempts += 1
        form = rng.choice(FORMS)
        page = rng.randint(0, 40 if form != "AS" else 99)
        code, body = client.get_json(BASE, {"organisasjonsform": form, "size": 100, "page": page})
        if code != 200 or not isinstance(body, dict):
            continue
        rows = (body.get("_embedded") or {}).get("enheter") or []
        rng.shuffle(rows)
        for row in rows[:25]:
            number = str(row.get("organisasjonsnummer", ""))
            if number and number not in seen:
                seen.add(number)
                found.append(number)
        if attempts % 10 == 0:
            log(f"  discovered {len(found)} numbers")
    return found[:n]
