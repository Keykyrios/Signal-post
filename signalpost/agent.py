"""Build and refresh one company profile from the Bronnoysund open registers.

Rules the agent follows:
  * Every fact carries its source URL, the date it was retrieved, and (when the
    register states one) the date the fact refers to.
  * A fact is published only if the register returned it. Nothing is estimated.
  * A response is accepted only when the organisation number inside it equals
    the requested one. Otherwise the whole profile is rejected.
"""

import datetime as dt

from . import orgnr as orgnr_mod
from .http import BudgetExceeded

BASE = "https://data.brreg.no/enhetsregisteret/api"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"

SRC_ENHET = "Enhetsregisteret (Bronnoysund Register Centre)"
SRC_ROLLER = "Enhetsregisteret roles"
SRC_ACCOUNTS = "Regnskapsregisteret (annual accounts)"

MAX_HISTORY = 50


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def dig(obj, *path):
    """Safe nested lookup that returns None instead of raising."""
    for key in path:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _address(block):
    if not isinstance(block, dict):
        return None
    lines = block.get("adresse") or []
    if isinstance(lines, str):
        lines = [lines]
    parts = [p for p in lines if p]
    town = " ".join(p for p in (block.get("postnummer"), block.get("poststed")) if p)
    if town:
        parts.append(town)
    if block.get("land") and block.get("landkode") not in (None, "NO"):
        parts.append(block["land"])
    text = ", ".join(parts)
    return text or None


class FactSet:
    """Collects facts for one profile."""

    def __init__(self, retrieved_at):
        self.retrieved_at = retrieved_at
        self.facts = {}

    def add(self, key, value, url, source, as_of=None, extra=None):
        if value is None or value == "" or value == []:
            return
        fact = {
            "value": value,
            "source": source,
            "source_url": url,
            "retrieved_at": self.retrieved_at,
        }
        if as_of:
            fact["as_of"] = as_of
        if extra:
            fact.update(extra)
        self.facts[key] = fact


def status_from(entity, deleted):
    if deleted:
        return "deleted"
    if entity.get("konkurs"):
        return "bankrupt"
    if entity.get("underAvvikling"):
        return "under_liquidation"
    if entity.get("underTvangsavviklingEllerTvangsopplosning"):
        return "forced_dissolution"
    if entity.get("nedleggelsesdato"):
        return "closed"
    return "active"


def prefetch(client, numbers, chunk=100):
    """Look up many legal entities in a few requests. Returns {orgnr: body}.

    Only entries whose returned number is one we asked for are kept. Anything missing or odd
    is simply absent, and the per-company lookup (with all its checks) handles it.
    """
    cache = {}
    valid = [n for n in numbers if orgnr_mod.is_valid(n)]
    for i in range(0, len(valid), chunk):
        part = valid[i:i + chunk]
        code, body = client.get_json(f"{BASE}/enheter", {"organisasjonsnummer": ",".join(part), "size": chunk})
        if code != 200 or not isinstance(body, dict):
            continue
        for row in (body.get("_embedded") or {}).get("enheter") or []:
            number = orgnr_mod.normalize(row.get("organisasjonsnummer", "")) if isinstance(row, dict) else ""
            if number in part:
                cache[number] = row
    return cache


def fetch_entity(client, orgnr, cache=None):
    """Return (kind, status_code, body). kind is 'enhet', 'underenhet' or None."""
    if cache and orgnr in cache:
        return "enhet", 200, cache[orgnr]
    code, body = client.get_json(f"{BASE}/enheter/{orgnr}")
    if code == 200 and isinstance(body, dict):
        return "enhet", code, body
    if code == 410:
        return "enhet", code, body or {}
    if code == 404:
        code2, body2 = client.get_json(f"{BASE}/underenheter/{orgnr}")
        if code2 == 200 and isinstance(body2, dict):
            return "underenhet", code2, body2
        if code2 == 410:
            return "underenhet", code2, body2 or {}
        return None, code2, body2
    return None, code, body


def _person_name(person):
    if not isinstance(person, dict):
        return None
    name = person.get("navn")
    if isinstance(name, dict):
        parts = [name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn")]
    else:
        parts = [person.get("fornavn"), person.get("mellomnavn"), person.get("etternavn")]
    text = " ".join(p for p in parts if p)
    return text or None


def parse_roles(data):
    """Return active role holders only. Birth dates are never read or stored."""
    found = {"ceo": [], "chair": [], "board": [], "auditor": [], "accountant": []}
    for group in (data or {}).get("rollegrupper") or []:
        for role in group.get("roller") or []:
            if role.get("fratraadt") or role.get("avregistrert"):
                continue
            code = dig(role, "type", "kode")
            holder = _person_name(role.get("person")) or dig(role, "enhet", "navn")
            if isinstance(holder, list):
                holder = " ".join(holder)
            if not holder:
                continue
            if code == "DAGL":
                found["ceo"].append(holder)
            elif code == "LEDE":
                found["chair"].append(holder)
                found["board"].append(holder)
            elif code in ("MEDL", "NEST"):
                found["board"].append(holder)
            elif code == "REVI":
                found["auditor"].append(holder)
            elif code == "REGN":
                found["accountant"].append(holder)
    return found


def parse_accounts(data, orgnr):
    """Return the newest statement, or None. Rejects statements for another company."""
    if not isinstance(data, list) or not data:
        return None
    candidates = []
    for item in data:
        if not isinstance(item, dict):
            continue
        owner = dig(item, "virksomhet", "organisasjonsnummer")
        if owner is not None and orgnr_mod.normalize(owner) != orgnr:
            continue
        end = dig(item, "regnskapsperiode", "tilDato") or ""
        candidates.append((end, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def build_facts(kind, entity, roles, accounts, subunit_total, orgnr, retrieved_at):
    fs = FactSet(retrieved_at)
    base = "enheter" if kind == "enhet" else "underenheter"
    url = f"{BASE}/{base}/{orgnr}"
    add = lambda key, value, as_of=None, extra=None: fs.add(key, value, url, SRC_ENHET, as_of, extra)

    add("name", entity.get("navn"))
    add("legal_form", dig(entity, "organisasjonsform", "beskrivelse"),
        extra={"code": dig(entity, "organisasjonsform", "kode")})
    add("registered_in_enhetsregisteret", entity.get("registreringsdatoEnhetsregisteret"),
        as_of=entity.get("registreringsdatoEnhetsregisteret"))
    add("founded", entity.get("stiftelsesdato") or entity.get("oppstartsdato"),
        as_of=entity.get("stiftelsesdato") or entity.get("oppstartsdato"))
    add("business_address",
        _address(entity.get("forretningsadresse") or entity.get("beliggenhetsadresse")))
    add("municipality",
        dig(entity, "forretningsadresse", "kommune") or dig(entity, "beliggenhetsadresse", "kommune"))
    add("postal_address", _address(entity.get("postadresse")))
    for n in (1, 2, 3):
        code = entity.get(f"naeringskode{n}") or {}
        add(f"industry_{n}", code.get("beskrivelse"), extra={"code": code.get("kode")})
    if entity.get("antallAnsatte") is not None:
        add("employees", entity.get("antallAnsatte"))
    add("institutional_sector", dig(entity, "institusjonellSektorkode", "beskrivelse"),
        extra={"code": dig(entity, "institusjonellSektorkode", "kode")})
    if entity.get("registrertIMvaregisteret") is not None:
        add("vat_registered", bool(entity["registrertIMvaregisteret"]))
    if entity.get("registrertIForetaksregisteret") is not None:
        add("in_business_register", bool(entity["registrertIForetaksregisteret"]))
    add("email", entity.get("epostadresse"))
    add("phone", entity.get("telefon") or entity.get("mobil"))
    purpose = entity.get("vedtektsfestetFormaal")
    if isinstance(purpose, list):
        purpose = " ".join(purpose)
    add("stated_purpose", purpose)
    activity = entity.get("aktivitet")
    if isinstance(activity, list):
        activity = " ".join(activity)
    add("stated_activity", activity)
    add("parent_organisation", entity.get("overordnetEnhet"))
    add("bankruptcy_date", entity.get("konkursdato"), as_of=entity.get("konkursdato"))
    add("liquidation_start", entity.get("underAvviklingDato"), as_of=entity.get("underAvviklingDato"))
    add("closed_on", entity.get("nedleggelsesdato"), as_of=entity.get("nedleggelsesdato"))
    add("deleted_on", entity.get("slettedato"), as_of=entity.get("slettedato"))
    add("last_filed_accounts_year", entity.get("sisteInnsendteAarsregnskap"))
    if subunit_total is not None:
        add("sub_units", subunit_total, extra={"source_url_note": "count of registered sub-units"})
        fs.facts["sub_units"]["source_url"] = f"{BASE}/underenheter?overordnetEnhet={orgnr}"

    if roles is not None:
        rurl = f"{BASE}/enheter/{orgnr}/roller"
        for key, label in (("ceo", "ceo"), ("chair", "board_chair"),
                           ("auditor", "auditor"), ("accountant", "accountant")):
            if roles[key]:
                fs.add(label, "; ".join(roles[key]), rurl, SRC_ROLLER)
        if roles["board"]:
            fs.add("board_size", len(roles["board"]), rurl, SRC_ROLLER,
                   extra={"members": roles["board"]})

    if accounts:
        aurl = f"{ACCOUNTS}/{orgnr}"
        period_end = dig(accounts, "regnskapsperiode", "tilDato")
        period_start = dig(accounts, "regnskapsperiode", "fraDato")
        currency = accounts.get("valuta")
        meta = {"currency": currency, "period_start": period_start}
        money = {
            "revenue": dig(accounts, "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter"),
            "operating_result": dig(accounts, "resultatregnskapResultat", "driftsresultat", "driftsresultat"),
            "net_result": dig(accounts, "resultatregnskapResultat", "aarsresultat"),
            "total_assets": dig(accounts, "eiendeler", "sumEiendeler"),
            "equity": dig(accounts, "egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
        }
        for key, value in money.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fs.add(key, value, aurl, SRC_ACCOUNTS, as_of=period_end, extra=dict(meta))
    return fs.facts


def explain(profile, kind, accounts_code, roles_code, entity, facts):
    notes = []
    notes.append(
        "Matched on organisation number %s: checksum valid, and the register returned the same number."
        % profile["orgnr"]
    )
    if kind == "underenhet":
        notes.append("This number is a sub-unit (business location), not a legal entity. Facts come from the sub-unit register.")
    if profile["status"] != "active":
        notes.append("Register status is '%s'. Facts describe the last registered state." % profile["status"])
    if "revenue" not in facts and "total_assets" not in facts:
        if accounts_code == 404:
            notes.append("No annual accounts are published for this number. Small sole proprietorships and many associations are not required to file.")
        elif accounts_code in (0, None) or (accounts_code and accounts_code >= 500):
            notes.append("The accounts register could not be reached in this run. Previous values are kept if they exist.")
        else:
            notes.append("Annual accounts exist but contained no usable figures.")
    if roles_code not in (200, None) and "ceo" not in facts:
        notes.append("Role information was not available (HTTP %s)." % roles_code)
    if entity.get("organisasjonsform", {}).get("kode") in ("ENK",):
        notes.append("Sole proprietorship: the owner is the legal person, so no separate board is registered.")
    return notes


def diff(previous, facts, now):
    """Compare new facts to the stored profile. Returns (facts_with_dates, changes)."""
    prev_facts = (previous or {}).get("facts", {})
    changes = []
    for key, fact in facts.items():
        old = prev_facts.get(key)
        if old and old.get("value") == fact["value"] and old.get("as_of") == fact.get("as_of"):
            fact["first_seen"] = old.get("first_seen", old.get("retrieved_at", now))
            fact["last_changed"] = old.get("last_changed", fact["first_seen"])
        else:
            fact["first_seen"] = old.get("first_seen", now) if old else now
            fact["last_changed"] = now
            if old:
                changes.append({"field": key, "old": old.get("value"), "new": fact["value"],
                                "detected_at": now, "old_as_of": old.get("as_of"), "new_as_of": fact.get("as_of")})
    for key, old in prev_facts.items():
        if key not in facts:
            changes.append({"field": key, "old": old.get("value"), "new": None,
                            "detected_at": now, "note": "no longer reported by the source"})
    return facts, changes


ACCOUNT_KEYS = ("revenue", "operating_result", "net_result", "total_assets", "equity")
WEB_KEYS = ("own_website", "news_latest", "open_positions", "careers_page", "social_linkedin",
            "social_facebook", "social_instagram", "social_x", "social_youtube", "summary")
ROLE_KEYS = ("ceo", "board_chair", "auditor", "accountant", "board_size", "sub_units")


def build_profile(client, raw, previous=None, depth=3, cache=None):
    """depth 1: entity only. 2: plus annual accounts. 3: plus roles and sub-unit count.

    Sources skipped by depth keep the previous values with their original retrieval date,
    so a cheap run never deletes or re-dates facts it did not re-check.
    """
    """Return a profile dict. Never raises for ordinary data problems."""
    now = now_iso()
    orgnr = orgnr_mod.normalize(raw)
    profile = {"orgnr": orgnr, "checked_at": now, "schema": 1}

    if not orgnr_mod.is_valid(orgnr):
        profile.update(status="rejected", facts={}, changes=[],
                       explanation=["The input is not a valid Norwegian organisation number (9 digits, modulus-11 check)."],
                       match={"checksum_valid": False})
        return profile

    try:
        kind, code, entity = fetch_entity(client, orgnr, cache)
        if kind is None:
            if code == 404:
                note = "No entity or sub-unit with this number exists in the register."
                status = "not_found"
            else:
                note = "The register could not be reached (HTTP %s). The previous profile, if any, is kept." % code
                status = "error"
            return _keep_previous(profile, previous, status, note)

        returned = orgnr_mod.normalize((entity or {}).get("organisasjonsnummer", orgnr if code == 410 else ""))
        if returned != orgnr:
            profile.update(status="rejected", facts={}, changes=[],
                           match={"checksum_valid": True, "requested": orgnr, "returned": returned,
                                  "matches_request": False},
                           explanation=["The register returned number '%s' for request '%s'. Nothing was published." % (returned, orgnr)])
            return profile

        deleted = code == 410
        roles = accounts = None
        roles_code = accounts_code = None
        subunits = None
        if not deleted:
            if kind == "enhet" and depth >= 3:
                roles_code, rdata = client.get_json(f"{BASE}/enheter/{orgnr}/roller")
                if roles_code == 200:
                    roles = parse_roles(rdata)
                s_code, sdata = client.get_json(f"{BASE}/underenheter",
                                                {"overordnetEnhet": orgnr, "size": 1})
                if s_code == 200:
                    subunits = dig(sdata, "page", "totalElements")
            if depth >= 2:
                accounts_code, adata = client.get_json(f"{ACCOUNTS}/{orgnr}")
                if accounts_code == 200:
                    accounts = parse_accounts(adata, orgnr)

        facts = build_facts(kind, entity, roles, accounts, subunits, orgnr, now)
        skipped = (ACCOUNT_KEYS if depth < 2 else ()) + (ROLE_KEYS if depth < 3 else ()) + WEB_KEYS
        for key in skipped:
            old = ((previous or {}).get("facts") or {}).get(key)
            if old and key not in facts:
                facts[key] = dict(old)
        facts, changes = diff(previous, facts, now)
        prior_history = (previous or {}).get("history", [])
        history = (prior_history + changes)[-MAX_HISTORY:]
        status = status_from(entity, deleted)
        profile.update(status=status, kind=kind, facts=facts, changes=changes, history=history,
                       match={"checksum_valid": True, "requested": orgnr, "returned": returned,
                              "matches_request": True, "registry": "underenheter" if kind == "underenhet" else "enheter"})
        profile["explanation"] = explain(profile, kind, accounts_code, roles_code, entity, facts)
        if depth < 3 and not deleted:
            part = "annual accounts, roles and sub-units" if depth < 2 else "roles and sub-units"
            profile["explanation"].append(
                "To stay inside the daily request limit this run checked the entity record only for %s. "
                "Earlier values for them, if any, keep their original retrieval dates." % part)
            if depth < 2 and "revenue" not in facts and "total_assets" not in facts:
                profile["explanation"] = [n for n in profile["explanation"] if "Annual accounts exist" not in n]
        profile["first_checked_at"] = (previous or {}).get("first_checked_at", now)
        # The register's own "homepage" entry is only a lead to check, never published as a fact.
        profile["register_site"] = entity.get("hjemmeside") or None
        for key in ("web", "not_found"):
            if (previous or {}).get(key) is not None:
                profile[key] = previous[key]
        profile["explanation"] += ["Web: " + n for n in dig(previous or {}, "web", "notes") or []]
        return profile
    except BudgetExceeded:
        raise


def _keep_previous(profile, previous, status, note):
    if previous and previous.get("facts"):
        kept = dict(previous)
        kept["refresh_note"] = note
        kept["last_failed_refresh"] = profile["checked_at"]
        kept["explanation"] = list(previous.get("explanation", [])) + [note]
        return kept
    profile.update(status=status, facts={}, changes=[], explanation=[note],
                   match={"checksum_valid": True})
    return profile
