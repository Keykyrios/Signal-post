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


def run(numbers, out_dir, workers=6, max_requests=1800, max_seconds=40 * 60,
        skip_fresh_hours=0, client=None, log=print):
    started = time.monotonic()
    profile_dir = os.path.join(out_dir, "profiles")
    os.makedirs(profile_dir, exist_ok=True)
    client = client or Client(max_requests=max_requests, max_seconds=max_seconds)
    counts = {}
    skipped_budget = []

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
        profile = agent.build_profile(client, number, previous)
        _save(path, profile)
        return number, profile, "fetched"

    results = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, n): n for n in numbers}
        done = 0
        for fut in cf.as_completed(futures):
            number = futures[fut]
            try:
                _, profile, how = fut.result()
                results[number] = profile
                counts[profile["status"]] = counts.get(profile["status"], 0) + 1
            except BudgetExceeded:
                skipped_budget.append(number)
            done += 1
            if done % 50 == 0:
                log(f"  {done}/{len(numbers)} done, {client.requests_made} requests used")

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
        "seconds": round(time.monotonic() - started, 1),
        "external_api_cost_usd": 0.0,
        "model_calls": 0,
    }
    _save(os.path.join(out_dir, "run_report.json"), report)
    return ordered, report
