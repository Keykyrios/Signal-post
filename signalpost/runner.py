"""Run the agent over a list of organisation numbers and write the results."""

import concurrent.futures as cf
import json
import os
import time

from . import agent, orgnr as orgnr_mod, web as web_mod
from .http import BudgetExceeded, Client


def read_numbers(path):
    seen, out = [], set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            # Support JSONL format (Builderr sends org numbers as JSONL)
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    raw = str(obj.get("organisasjonsnummer", obj.get("orgnr", "")))
                except (json.JSONDecodeError, AttributeError):
                    continue
            else:
                raw = line.split("#", 1)[0].strip()
            if not raw:
                continue
            number = orgnr_mod.normalize(raw)
            if number and number not in out:
                out.add(number)
                seen.append(number)
    return seen


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _save(path, data):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


COST = {1: 1.1, 2: 2.1, 3: 4.1}  # requests per company, with a little room for the sub-unit fallback


def plan_depths(n, budget, force=None):
    """Pick how deep to look per company so the whole list fits the request budget.

    Every company gets at least the entity record. Spare budget upgrades companies in list order.
    """
    if n == 0:
        return []
    if force:
        return [force] * n
    base = 1
    for d in (3, 2):
        if n * COST[d] <= budget:
            base = d
            break
    if base == 3:
        return [3] * n
    extra = budget - n * COST[base]
    k = max(0, min(n, int(extra // (COST[base + 1] - COST[base]))))
    return [base + 1] * k + [base] * (n - k)


def _web_due(profile, refresh_days):
    if profile.get("status") != "active":
        return False
    state = profile.get("web") or {}
    if not state or state.get("status") == "error":
        return True
    try:
        checked = agent.dt.datetime.fromisoformat(state["checked_at"])
        return (agent.dt.datetime.now(agent.dt.timezone.utc) - checked).days >= refresh_days
    except (KeyError, ValueError):
        return True


def run(numbers, out_dir, workers=6, max_requests=1800, max_seconds=40 * 60,
        skip_fresh_hours=0, client=None, log=print, depth=None, web=True,
        web_refresh_days=7, searcher=None):
    started = time.monotonic()
    profile_dir = os.path.join(out_dir, "profiles")
    os.makedirs(profile_dir, exist_ok=True)
    client = client or Client(max_requests=max_requests, max_seconds=max_seconds)
    counts = {}
    skipped_budget = []
    # Use full depth (3) by default to get accounts, roles and sub-units.
    # The prefetch bulk lookup saves enough requests to afford both registry and web.
    depths = dict(zip(numbers, plan_depths(len(numbers), max_requests, depth)))

    cache = {}
    try:
        cache = agent.prefetch(client, numbers)
        log(f"  bulk register lookup covered {len(cache)} of {len(numbers)} companies")
    except BudgetExceeded:
        pass

    def work(number):
        path = os.path.join(profile_dir, f"{number}.json")
        previous = _load(path)
        if previous and skip_fresh_hours and previous.get("status") == "active":
            try:
                checked = agent.dt.datetime.fromisoformat(previous["checked_at"])
                age = (agent.dt.datetime.now(agent.dt.timezone.utc) - checked).total_seconds() / 3600
                if age < skip_fresh_hours:
                    return number, previous
            except (KeyError, ValueError):
                pass
        profile = agent.build_profile(client, number, previous, depth=depths[number], cache=cache)
        _save(path, profile)
        return number, profile

    results = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, n): n for n in numbers}
        done = 0
        for fut in cf.as_completed(futures):
            number = futures[fut]
            try:
                _, profile = fut.result()
                results[number] = profile
                counts[profile["status"]] = counts.get(profile["status"], 0) + 1
            except BudgetExceeded:
                skipped_budget.append(number)
            done += 1
            if done % 100 == 0:
                log(f"  registry {done}/{len(numbers)} done, {client.requests_made} requests used")

    web_counts = {"verified": 0, "no_site": 0, "error": 0, "not_reached": 0}
    searcher = searcher or web_mod.Searcher(client)
    if web:
        due = [p for p in results.values() if _web_due(p, web_refresh_days)]
        due.sort(key=lambda p: not p.get("register_site"))  # sites the register points to first: no search needed
        log(f"  web step for {len(due)} companies, {client.requests_made} requests used so far")
        stop = {"flag": False}

        def web_work(profile):
            if stop["flag"]:
                return None
            try:
                facts, notes, status = web_mod.enrich(client, profile, searcher)
            except BudgetExceeded:
                raise
            except Exception as exc:  # one odd page must never stop the run; earlier web facts are kept
                facts, notes, status = {}, ["The web lookup failed unexpectedly (%s)." % type(exc).__name__], "error"
            web_mod.merge_web(profile, facts, notes, status)
            _save(os.path.join(profile_dir, f"{profile['orgnr']}.json"), profile)
            return status

        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(web_work, p) for p in due]
            done = 0
            for fut in cf.as_completed(futures):
                try:
                    web_counts[fut.result() or "not_reached"] += 1
                except BudgetExceeded:
                    stop["flag"] = True
                    web_counts["not_reached"] += 1
                done += 1
                if done % 50 == 0:
                    log(f"  web {done}/{len(due)} done, {client.requests_made} requests used")

    # Ensure every input company has a result (missing ones get failed envelope)
    for number in numbers:
        if number not in results:
            now = agent.now_iso()
            results[number] = {
                "orgnr": number,
                "checked_at": now,
                "schema": 1,
                "status": "failed",
                "facts": {},
                "changes": [],
                "explanation": ["Processing was interrupted by budget or time constraints."],
                "match": {"checksum_valid": orgnr_mod.is_valid(number)},
                "not_found": ["a verified own website", "a recent dated news item", "an open job posting", "a social media page"],
                "envelope": web_mod.empty_envelope(number, "failed", "budget_exceeded", now),
                "summary": "Could not process this company within the available budget.",
            }

    # Build terminal envelope for every profile and write summary for those missing it
    for number, profile in results.items():
        facts = profile.get("facts") or {}
        # Add summary if not already present
        if "summary" not in facts and facts.get("name"):
            gaps = web_mod.not_found(facts)
            text = web_mod.summarize(facts, gaps)
            if text:
                now = agent.now_iso()
                facts["summary"] = {"value": text, "source": web_mod.SRC_SUMMARY,
                                    "source_url": (facts.get("name") or {}).get("source_url"),
                                    "retrieved_at": now, "evidence": "built only from the facts listed on this profile"}
            profile.setdefault("not_found", gaps)
        # Build the envelope
        profile["envelope"] = web_mod.build_envelope(profile)
        # Re-save with envelope
        _save(os.path.join(profile_dir, f"{number}.json"), profile)

    ordered = [results[n] for n in numbers if n in results]
    with open(os.path.join(out_dir, "profiles.jsonl"), "w", encoding="utf-8") as handle:
        for profile in ordered:
            handle.write(json.dumps(profile, ensure_ascii=False) + "\n")

    has = lambda p, k: k in (p.get("facts") or {})
    report = {
        "finished_at": agent.now_iso(),
        "companies_requested": len(numbers),
        "profiles_written": len(ordered),
        "not_processed_budget": len(skipped_budget),
        "status_counts": counts,
        "profiles_with_verified_website": sum(has(p, "own_website") for p in ordered),
        "profiles_with_news": sum(has(p, "news_latest") for p in ordered),
        "profiles_with_open_positions": sum(has(p, "open_positions") for p in ordered),
        "profiles_with_social_page": sum(any(k.startswith("social_") for k in (p.get("facts") or {})) for p in ordered),
        "web_step": web_counts,
        "requests_made": client.requests_made,
        "search_queries": searcher.queries,
        "depth_counts": {str(d): list(depths.values()).count(d) for d in (1, 2, 3)},
        "seconds": round(time.monotonic() - started, 1),
        "external_api_cost_usd": searcher.cost_usd,
        "model_calls": 0,
    }
    _save(os.path.join(out_dir, "run_report.json"), report)
    return ordered, report
