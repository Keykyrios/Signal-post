"""Run the agent over a list of organisation numbers and write the results."""

import concurrent.futures as cf
import json
import os
import time

from . import agent, orgnr as orgnr_mod
from .http import BudgetExceeded, Client


def read_numbers(path):
    seen, out = [], set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            # Support JSONL format (Builderr sends org numbers as JSONL)
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    number = str(obj.get("organisasjonsnummer", obj.get("orgnr", "")))
                except (json.JSONDecodeError, AttributeError):
                    continue
            else:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                number = orgnr_mod.normalize(line)
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
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# Estimated requests per company at each depth
# depth 3 + web: entity(1) + roles(1) + subunits(1) + accounts(1) + proff(1) + verify(1-3) + crawl(0-2) = ~7-10
# depth 3 no web: ~4
# depth 2 + web: entity(1) + accounts(1) + proff(1) + verify(1-3) + crawl(0-2) = ~5-7
# depth 2 no web: ~2
# depth 1 + web: entity(1) + proff(1) + verify(1-3) + crawl(0-2) = ~4-6
# depth 1 no web: ~1
COST = {1: 1.1, 2: 2.1, 3: 4.1}
COST_WEB = {1: 5.0, 2: 6.0, 3: 8.0}  # With web discovery


def plan_depths(n, budget, force=None, web=True):
    """Pick how deep to look per company so the whole list fits the request budget.

    Every company gets at least the entity record. Spare budget upgrades companies in list order.
    """
    if n == 0:
        return [], []
    
    cost_table = COST_WEB if web else COST
    
    if force:
        return [force] * n, [web] * n
    
    # First try: all at depth 3 with web
    if web and n * COST_WEB[3] <= budget:
        return [3] * n, [True] * n
    
    # Try: all at depth 3 without web, then add web for as many as possible
    if n * COST[3] <= budget:
        depths = [3] * n
        remaining = budget - n * COST[3]
        web_cost_per = COST_WEB[3] - COST[3]  # ~4.4 extra per company for web
        web_count = min(n, int(remaining / web_cost_per))
        web_flags = [True] * web_count + [False] * (n - web_count)
        return depths, web_flags
    
    # Try: all at depth 2 with web
    if web and n * COST_WEB[2] <= budget:
        return [2] * n, [True] * n
    
    # Fallback: depth 2 without web, upgrade what we can
    base = 1
    for d in (3, 2):
        if n * COST[d] <= budget:
            base = d
            break
    
    if base >= 2:
        depths = [base] * n
        remaining = budget - n * COST[base]
        # Add web discovery for as many as fits
        web_cost_per = COST_WEB[base] - COST[base]
        web_count = min(n, int(remaining / web_cost_per)) if web_cost_per > 0 else 0
        web_flags = [True] * web_count + [False] * (n - web_count)
        return depths, web_flags
    
    # Worst case: depth 1, upgrade some to higher depths
    depths = [1] * n
    web_flags = [False] * n
    extra = budget - n * COST[1]
    
    # Upgrade to depth 2
    upgrade_cost = COST[2] - COST[1]
    k2 = min(n, int(extra / upgrade_cost))
    for i in range(k2):
        depths[i] = 2
        extra -= upgrade_cost
    
    # Add web for some
    if web and extra > 0:
        web_cost_per = COST_WEB[2] - COST[2]
        wk = min(k2, int(extra / web_cost_per)) if web_cost_per > 0 else 0
        for i in range(wk):
            web_flags[i] = True
    
    return depths, web_flags


def run(numbers, out_dir, workers=6, max_requests=1800, max_seconds=40 * 60,
        skip_fresh_hours=0, client=None, log=print, depth=None, web=True):
    started = time.monotonic()
    profile_dir = os.path.join(out_dir, "profiles")
    os.makedirs(profile_dir, exist_ok=True)
    client = client or Client(max_requests=max_requests, max_seconds=max_seconds)
    counts = {}
    skipped_budget = []
    web_stats = {"attempted": 0, "verified": 0, "news_found": 0, "jobs_found": 0}

    depths, web_flags = plan_depths(len(numbers), max_requests, depth, web=web)
    depth_map = dict(zip(numbers, depths))
    web_map = dict(zip(numbers, web_flags))
    
    log(f"  Plan: {sum(1 for d in depths if d==3)} full, {sum(1 for d in depths if d==2)} mid, {sum(1 for d in depths if d==1)} lite")
    log(f"  Web discovery: {sum(web_flags)} companies")

    def work(number):
        path = os.path.join(profile_dir, f"{number}.json")
        previous = _load(path)
        if previous and skip_fresh_hours and previous.get("status") == "active":
            try:
                checked = agent.dt.datetime.fromisoformat(previous["checked_at"])
                age = (agent.dt.datetime.now(agent.dt.timezone.utc) - checked).total_seconds() / 3600
                if age < skip_fresh_hours:
                    return number, previous, "fresh"
            except (KeyError, ValueError):
                pass
        do_web = web_map.get(number, False)
        profile = agent.build_profile(client, number, previous, 
                                       depth=depth_map[number], 
                                       web_discovery=do_web)
        _save(path, profile)
        return number, profile, "fetched"

    results = {}
    # Use fewer workers for web discovery to avoid rate limiting
    effective_workers = min(workers, 4) if web else workers
    
    with cf.ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = {pool.submit(work, n): n for n in numbers}
        done = 0
        for fut in cf.as_completed(futures):
            number = futures[fut]
            try:
                _, profile, how = fut.result()
                results[number] = profile
                counts[profile["status"]] = counts.get(profile["status"], 0) + 1
                # Track web stats
                facts = profile.get("facts", {})
                if "verified_website" in facts:
                    web_stats["verified"] += 1
                if "recent_news" in facts:
                    web_stats["news_found"] += 1
                if "job_postings" in facts:
                    web_stats["jobs_found"] += 1
            except BudgetExceeded:
                skipped_budget.append(number)
            done += 1
            if done % 25 == 0:
                elapsed = time.monotonic() - started
                log(f"  {done}/{len(numbers)} done, {client.requests_made} requests, {elapsed:.0f}s")

    # Ensure every input company has a result (missing ones get failed envelope)
    for number in numbers:
        if number not in results:
            results[number] = {
                "orgnr": number,
                "checked_at": agent.now_iso(),
                "schema": 2,
                "status": "failed",
                "facts": {},
                "changes": [],
                "explanation": ["Processing was interrupted by budget or time constraints."],
                "match": {"checksum_valid": orgnr_mod.is_valid(number)},
                "envelope": {"state": "failed", "reason": "budget_exceeded"},
                "summary": "Could not process this company within the available budget.",
            }

    ordered = [results[n] for n in numbers if n in results]
    jsonl = os.path.join(out_dir, "profiles.jsonl")
    with open(jsonl, "w", encoding="utf-8") as handle:
        for profile in ordered:
            handle.write(json.dumps(profile, ensure_ascii=False) + "\n")

    report = {
        "finished_at": agent.now_iso(),
        "companies_requested": len(numbers),
        "profiles_written": len(ordered),
        "not_processed_budget": len(skipped_budget),
        "status_counts": counts,
        "requests_made": client.requests_made,
        "depth_counts": {str(d): list(depths).count(d) for d in (1, 2, 3)},
        "web_discovery": web_stats,
        "seconds": round(time.monotonic() - started, 1),
        "external_api_cost_usd": 0.0,
        "model_calls": 0,
    }
    _save(os.path.join(out_dir, "run_report.json"), report)
    return ordered, report
