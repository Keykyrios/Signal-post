# Signalpost agent

Give it Norwegian organisation numbers. It returns a profile per company: facts, a source link and retrieval date for every fact, the date each fact refers to, and a plain-language note on how the company was matched. Re-running refreshes profiles and records what changed.

## Run it

Python 3.9+, standard library only. No install step, no API key. The viewer is prebuilt in `ui/dist`, so Node is not needed to run it.

One command: find 1,000 companies, build the profiles, open the viewer at http://127.0.0.1:8000

```
python -m signalpost all
```

Or step by step:

```
python -m signalpost discover --n 1000 --out companies.txt
python -m signalpost run --input companies.txt --out out
python -m signalpost serve --out out
```

Files written:

- `out/profiles/<orgnr>.json` and `out/profiles.jsonl`: the profiles
- `out/run_report.json`: companies, status counts, requests used, seconds, cost, depth used
- Viewer: search, filters, per-fact source links, change history, "how this was matched", CSV and JSON export

Other commands: `python -m signalpost one 923609016` prints one profile. Tests: `python -m unittest discover -s tests`. Viewer end-to-end test (needs Playwright): `python tests/ui_e2e.py http://127.0.0.1:8000/`.

Rebuild the viewer after editing `ui/src`: `cd ui && npm install && npm run build`.

## Sources

All from the Brønnøysund Register Centre open APIs (NLOD 2.0 licence):

- Enhetsregisteret: `/enheter/{orgnr}`, falling back to `/underenheter/{orgnr}`, plus sub-unit count
- Enhetsregisteret roles: `/enheter/{orgnr}/roller`
- Regnskapsregisteret: `/regnskap/{orgnr}` (newest annual accounts)

## How it stays correct

- Input must pass the modulus-11 check digit before any request is made.
- The organisation number in each response must equal the requested one. If not, the profile is rejected and nothing is published.
- Accounts naming a different company are dropped.
- Financial values are published only if the register returned a number. Nothing is estimated or filled in.
- Resigned role holders are excluded. Birth dates are never read or stored.
- Each fact keeps `first_seen`, `last_changed`, `retrieved_at` and, where the register gives one, `as_of`. Changed or removed facts go to `changes` and `history`.
- If a refresh fails (register down), the previous profile is kept and annotated.
- Deleted, bankrupt, liquidating and closed entities are reported with that status.

## Limits and cost

Defaults stop at 1,800 requests and 40 minutes, under the daily 2,000 requests and 45 minutes.

A full profile costs about 4 requests (entity, roles, sub-unit count, accounts), so 1,000 full profiles would break the daily cap. The run therefore plans depth up front so the whole list fits the budget:

- depth 3: entity, roles, sub-units, accounts (about 4 requests each)
- depth 2: entity and accounts (about 2)
- depth 1: entity record only (about 1)

For 1,000 companies at 1,800 requests, every company gets the entity record and about 700 also get annual accounts. A shallower run never deletes or re-dates facts it did not re-check: earlier values keep their original retrieval date and the profile says so. Run again the next day to deepen more profiles. Force a depth with `--depth N`.

- Model/API: no LLM and no paid API. Registers only.
- Expected run cost: $0.00 declared external API cost.
- `--skip-fresh-hours N` reuses profiles checked recently and saves requests.

## Not covered

The registers do not publish ownership, shareholders, or history before the latest filed accounts. The agent does not scrape company websites, because matching a web page to the right company is the main source of wrong-company errors.

## Viewer credits

React 19, Vite, Tailwind, Motion, Hugeicons. Interface components are vendored from React Bits (MIT with Commons Clause) and Componentry (MIT): click-spark, shredder, bell-toggle, code-slots, branched-menu, folder-float, glide-select, fuse-button, jelly-radio, rubber-segment, swipe-row, squish-switch, pixel-swap, line-sidebar, prompt-bar, webgl-liquid. Several were edited for theme colours, accessibility labels and sizing.
