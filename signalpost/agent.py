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
SRC_WEBSITE = "Company website"
SRC_SEARCH = "Web search discovery"

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


def fetch_entity(client, orgnr):
    """Return (kind, status_code, body). kind is 'enhet', 'underenhet' or None."""
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
    add("website", entity.get("hjemmeside"))
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


def add_web_facts(facts, web_data, orgnr, retrieved_at):
    """Add web-discovered facts to the fact set."""
    if not web_data:
        return facts
    
    fs = FactSet(retrieved_at)
    fs.facts = dict(facts)  # Start with existing facts
    
    # Verified website
    if web_data.get("verified_website"):
        site_url = web_data["verified_website"]
        fs.add("verified_website", site_url, site_url, SRC_WEBSITE,
               extra={"verification_method": web_data.get("website_verification", "unknown")})
    
    # Social profiles
    for platform, url in web_data.get("social_profiles", {}).items():
        source_url = web_data.get("verified_website") or url
        fs.add(f"social_{platform}", url, source_url, SRC_WEBSITE,
               extra={"platform": platform})
    
    # News items
    news = web_data.get("news_items", [])
    if news:
        news_values = []
        for item in news[:5]:  # Max 5 news items
            entry = {"title": item["title"], "source_url": item.get("source_url", "")}
            if item.get("date"):
                entry["date"] = item["date"]
            news_values.append(entry)
        
        source_url = web_data.get("page_links", {}).get("news") or web_data.get("verified_website", "")
        fs.add("recent_news", news_values, source_url, SRC_WEBSITE,
               extra={"item_count": len(news_values)})
    
    # Job postings
    jobs = web_data.get("job_postings", [])
    if jobs:
        job_values = []
        for item in jobs[:5]:  # Max 5 job postings
            entry = {"title": item["title"], "source_url": item.get("source_url", "")}
            if item.get("date"):
                entry["date"] = item["date"]
            job_values.append(entry)
        
        source_url = web_data.get("page_links", {}).get("careers") or web_data.get("verified_website", "")
        fs.add("job_postings", job_values, source_url, SRC_WEBSITE,
               extra={"item_count": len(job_values)})
    
    # About text / company description from website
    if web_data.get("about_text"):
        source_url = web_data.get("page_links", {}).get("about") or web_data.get("verified_website", "")
        fs.add("website_description", web_data["about_text"], source_url, SRC_WEBSITE)
    
    return fs.facts


def generate_summary(profile, facts, entity):
    """Generate a human-readable company summary based on available facts."""
    parts = []
    name = facts.get("name", {}).get("value", "This company")
    legal_form = facts.get("legal_form", {}).get("value", "")
    industry = facts.get("industry_1", {}).get("value", "")
    activity = facts.get("stated_activity", {}).get("value", "")
    purpose = facts.get("stated_purpose", {}).get("value", "")
    municipality = facts.get("municipality", {}).get("value", "")
    employees = facts.get("employees", {}).get("value")
    status = profile.get("status", "active")
    web_desc = facts.get("website_description", {}).get("value", "")
    
    # Opening line
    if legal_form:
        parts.append(f"{name} is a {legal_form.lower()} registered in Norway")
    else:
        parts.append(f"{name} is registered in Norway")
    
    if municipality:
        parts[-1] += f", based in {municipality}"
    parts[-1] += "."
    
    # What they do
    if web_desc and len(web_desc) > 30:
        parts.append(f"According to their website: {web_desc}")
    elif activity:
        parts.append(f"Registered activity: {activity}")
    elif purpose:
        parts.append(f"Stated purpose: {purpose}")
    elif industry:
        parts.append(f"The company operates in: {industry}.")
    
    # Size / employees
    if employees is not None and employees > 0:
        parts.append(f"The company has {employees} registered employee(s).")
    
    # Financial snapshot
    revenue = facts.get("revenue", {})
    net_result = facts.get("net_result", {})
    if revenue.get("value") is not None:
        rev_val = revenue["value"]
        currency = revenue.get("currency", "NOK")
        period = revenue.get("as_of", "")
        parts.append(f"Latest filed revenue: {rev_val:,.0f} {currency} (period ending {period}).")
    if net_result.get("value") is not None:
        nr_val = net_result["value"]
        currency = net_result.get("currency", "NOK")
        if nr_val >= 0:
            parts.append(f"Net result: {nr_val:,.0f} {currency} (positive).")
        else:
            parts.append(f"Net result: {nr_val:,.0f} {currency} (negative).")
    
    # Leadership
    ceo = facts.get("ceo", {}).get("value", "")
    chair = facts.get("board_chair", {}).get("value", "")
    if ceo:
        parts.append(f"CEO/daglig leder: {ceo}.")
    if chair:
        parts.append(f"Board chair: {chair}.")
    
    # Website
    website = facts.get("verified_website", {}).get("value") or facts.get("website", {}).get("value")
    if website:
        parts.append(f"Website: {website}.")
    
    # Hiring
    jobs = facts.get("job_postings", {})
    if jobs.get("value"):
        count = len(jobs["value"]) if isinstance(jobs["value"], list) else 0
        if count > 0:
            parts.append(f"The company appears to be hiring, with {count} open position(s) listed on their website.")
    
    # News
    news = facts.get("recent_news", {})
    if news.get("value"):
        count = len(news["value"]) if isinstance(news["value"], list) else 0
        if count > 0:
            parts.append(f"The company has {count} recent news item(s) on their website.")
    
    # Status
    if status == "under_liquidation":
        parts.append("Note: The company is currently under liquidation.")
    elif status == "bankrupt":
        parts.append("Note: The company is registered as bankrupt.")
    elif status == "closed":
        parts.append("Note: The company is registered as closed.")
    
    # What we couldn't find
    missing = []
    if "verified_website" not in facts and "website" not in facts:
        missing.append("official website")
    if "revenue" not in facts and "total_assets" not in facts:
        missing.append("financial data")
    if "ceo" not in facts:
        missing.append("CEO/daglig leder")
    if "job_postings" not in facts:
        missing.append("job postings")
    if "recent_news" not in facts:
        missing.append("recent news")
    
    if missing:
        parts.append(f"Not found: {', '.join(missing)}.")
    
    return " ".join(parts)


def build_envelope(profile, facts):
    """Build the required terminal envelope with all 7 sections."""
    orgnr = profile["orgnr"]
    status = profile.get("status", "unknown")
    
    def _avail(key):
        """Return availability state for a fact."""
        if key in facts:
            return "available"
        return "not_available"
    
    envelope = {
        # Section 1: Legal identity and public brand
        "legal_identity": {
            "organisation_number": orgnr,
            "name": facts.get("name", {}).get("value"),
            "legal_form": facts.get("legal_form", {}).get("value"),
            "legal_form_code": facts.get("legal_form", {}).get("code"),
            "business_address": facts.get("business_address", {}).get("value"),
            "municipality": facts.get("municipality", {}).get("value"),
            "postal_address": facts.get("postal_address", {}).get("value"),
            "founded": facts.get("founded", {}).get("value"),
            "industry": facts.get("industry_1", {}).get("value"),
            "industry_code": facts.get("industry_1", {}).get("code"),
            "employees": facts.get("employees", {}).get("value"),
            "status": status,
        },
        
        # Section 2: Latest annual accounts
        "annual_accounts": {
            "state": _avail("revenue"),
            "revenue": facts.get("revenue", {}).get("value"),
            "operating_result": facts.get("operating_result", {}).get("value"),
            "net_result": facts.get("net_result", {}).get("value"),
            "total_assets": facts.get("total_assets", {}).get("value"),
            "equity": facts.get("equity", {}).get("value"),
            "currency": facts.get("revenue", {}).get("currency") or facts.get("total_assets", {}).get("currency"),
            "period_end": facts.get("revenue", {}).get("as_of") or facts.get("total_assets", {}).get("as_of"),
            "period_start": facts.get("revenue", {}).get("period_start") or facts.get("total_assets", {}).get("period_start"),
        },
        
        # Section 3: Leadership and registered workplaces
        "leadership": {
            "ceo": {"state": _avail("ceo"), "value": facts.get("ceo", {}).get("value")},
            "board_chair": {"state": _avail("board_chair"), "value": facts.get("board_chair", {}).get("value")},
            "board_size": {"state": _avail("board_size"), "value": facts.get("board_size", {}).get("value"),
                          "members": facts.get("board_size", {}).get("members")},
            "auditor": {"state": _avail("auditor"), "value": facts.get("auditor", {}).get("value")},
            "accountant": {"state": _avail("accountant"), "value": facts.get("accountant", {}).get("value")},
            "sub_units": {"state": _avail("sub_units"), "value": facts.get("sub_units", {}).get("value")},
        },
        
        # Section 4: Verified official website and company-owned profiles
        "web_presence": {
            "verified_website": {
                "state": _avail("verified_website"),
                "value": facts.get("verified_website", {}).get("value"),
                "verification_method": facts.get("verified_website", {}).get("verification_method"),
            },
            "registry_website": {
                "state": _avail("website"),
                "value": facts.get("website", {}).get("value"),
            },
            "social_profiles": {},
        },
        
        # Section 5: Hiring and dated public activity
        "activity": {
            "job_postings": {
                "state": _avail("job_postings"),
                "items": facts.get("job_postings", {}).get("value", []),
            },
            "recent_news": {
                "state": _avail("recent_news"),
                "items": facts.get("recent_news", {}).get("value", []),
            },
        },
        
        # Section 6: Claim-level evidence
        "evidence": {},
        
        # Section 7: Refresh metadata
        "refresh": {
            "checked_at": profile.get("checked_at"),
            "first_checked_at": profile.get("first_checked_at"),
            "changes_detected": len(profile.get("changes", [])),
        },
    }
    
    # Populate social profiles
    for key, fact in facts.items():
        if key.startswith("social_"):
            platform = key[7:]  # Remove "social_" prefix
            envelope["web_presence"]["social_profiles"][platform] = {
                "state": "available",
                "value": fact.get("value"),
                "source_url": fact.get("source_url"),
            }
    
    if not envelope["web_presence"]["social_profiles"]:
        envelope["web_presence"]["social_profiles"] = {"state": "not_available"}
    
    # Build evidence section
    for key, fact in facts.items():
        if isinstance(fact, dict) and "source_url" in fact:
            envelope["evidence"][key] = {
                "source": fact.get("source"),
                "source_url": fact.get("source_url"),
                "retrieved_at": fact.get("retrieved_at"),
                "as_of": fact.get("as_of"),
            }
    
    return envelope


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
ROLE_KEYS = ("ceo", "board_chair", "auditor", "accountant", "board_size", "sub_units")
WEB_KEYS = ("verified_website", "website_description", "recent_news", "job_postings")


def build_profile(client, raw, previous=None, depth=3, web_discovery=True):
    """depth 1: entity only. 2: plus annual accounts. 3: plus roles and sub-unit count.

    Sources skipped by depth keep the previous values with their original retrieval date,
    so a cheap run never deletes or re-dates facts it did not re-check.
    """
    """Return a profile dict. Never raises for ordinary data problems."""
    now = now_iso()
    orgnr = orgnr_mod.normalize(raw)
    profile = {"orgnr": orgnr, "checked_at": now, "schema": 2}

    if not orgnr_mod.is_valid(orgnr):
        profile.update(status="rejected", facts={}, changes=[],
                       explanation=["The input is not a valid Norwegian organisation number (9 digits, modulus-11 check)."],
                       match={"checksum_valid": False},
                       envelope={"state": "failed", "reason": "invalid_org_number"},
                       summary="Invalid organisation number.")
        return profile

    try:
        kind, code, entity = fetch_entity(client, orgnr)
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
                           explanation=["The register returned number '%s' for request '%s'. Nothing was published." % (returned, orgnr)],
                           envelope={"state": "failed", "reason": "org_number_mismatch"},
                           summary="Organisation number mismatch — no data published.")
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
        
        # Web discovery (new in v2)
        web_data = None
        if web_discovery and not deleted and kind == "enhet":
            try:
                from .web_discovery import discover_web_presence
                company_name = entity.get("navn", "")
                municipality = (dig(entity, "forretningsadresse", "kommune") or 
                              dig(entity, "beliggenhetsadresse", "kommune") or "")
                registry_website = entity.get("hjemmeside")
                
                web_data = discover_web_presence(
                    company_name, municipality, orgnr,
                    registry_website=registry_website, client=client
                )
                facts = add_web_facts(facts, web_data, orgnr, now)
            except BudgetExceeded:
                raise
            except Exception:
                pass  # Web discovery failure is not fatal
        
        skipped = (ACCOUNT_KEYS if depth < 2 else ()) + (ROLE_KEYS if depth < 3 else ())
        if not web_discovery:
            skipped = skipped + WEB_KEYS
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
        
        # Add web discovery notes to explanation
        if web_data:
            if web_data.get("verified_website"):
                method = web_data.get("website_verification", "verified")
                profile["explanation"].append(
                    f"Website {web_data['verified_website']} verified by {method}.")
                if web_data.get("social_profiles"):
                    platforms = ", ".join(web_data["social_profiles"].keys())
                    profile["explanation"].append(f"Social profiles found: {platforms}.")
                if web_data.get("news_items"):
                    profile["explanation"].append(
                        f"Found {len(web_data['news_items'])} news item(s) on the company website.")
                if web_data.get("job_postings"):
                    profile["explanation"].append(
                        f"Found {len(web_data['job_postings'])} job posting(s) on the company website.")
            else:
                profile["explanation"].append("No verified website could be found for this company.")
        
        if depth < 3 and not deleted:
            part = "annual accounts, roles and sub-units" if depth < 2 else "roles and sub-units"
            profile["explanation"].append(
                "To stay inside the daily request limit this run checked the entity record only for %s. "
                "Earlier values for them, if any, keep their original retrieval dates." % part)
            if depth < 2 and "revenue" not in facts and "total_assets" not in facts:
                profile["explanation"] = [n for n in profile["explanation"] if "Annual accounts exist" not in n]
        
        # Generate summary (new in v2)
        profile["summary"] = generate_summary(profile, facts, entity)
        
        # Build the terminal envelope (new in v2)
        profile["envelope"] = build_envelope(profile, facts)
        
        profile["first_checked_at"] = (previous or {}).get("first_checked_at", now)
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
                   match={"checksum_valid": True},
                   envelope={"state": status, "reason": note},
                   summary=note)
    return profile
