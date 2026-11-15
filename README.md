# Signalpost agent

Give it Norwegian organisation numbers. It returns a company profile: registry facts, verified website, social media profiles, recent news, job postings, and a human-readable summary. Every fact carries a source link, retrieval date, and the date it refers to. Re-running refreshes profiles and records what changed.

## Run it

Python 3.9+, standard library only (uses `urllib`, `json`, `html`, `ssl`, `re`, `concurrent.futures`). No install step, no API key, no pip dependencies. The viewer is prebuilt in `ui/dist`, so Node is not needed to run it.

**One command** — build profiles for companies from a file, open the viewer:

```
python -m signalpost run --input companies.txt --out out
python -m signalpost serve --out out
```

Or discover + build + serve in one shot:

```
python -m signalpost all
```

### Official evaluation run

The evaluator supplies a file of organisation numbers. Run:

```
python -m signalpost run --input <supplied-file> --out out
```

This reads org numbers from plain text (one per line) or JSONL format, builds a full profile for each, and writes exactly one terminal envelope per company to `out/profiles.jsonl`.

## What it finds

### From official registers (Brønnøysundregistrene)
- Legal identity: name, legal form, address, municipality, industry codes, employees
- Annual accounts: revenue, operating result, net result, total assets, equity
- Leadership: CEO, board chair, board members, auditor, accountant
- Sub-units and registered workplaces

### From the web (new in v2)
- **Verified website**: searched via DuckDuckGo, verified by org number or company name on the page
- **Social media profiles**: Facebook, Instagram, Twitter/X, YouTube, TikTok — extracted from the company's own website
- **Recent news**: dated news items from the company's news/blog page
- **Job postings**: dated job listings from the company's careers page
- **Company description**: meta description or about-page text from the verified website

### Generated
- **Human-readable summary**: what the company does, key financials, leadership, web presence, and what was not found
- **Terminal envelope**: all 7 required sections with explicit availability states

## How it stays correct

- Input must pass the modulus-11 check digit before any request is made.
- The organisation number in each response must equal the requested one. If not, the profile is rejected and nothing is published.
- **Website verification**: a candidate URL is only accepted if the page contains the organisation number or the company's legal name. Directory sites (proff.no, gulesider.no, etc.) are excluded.
- Social profiles and news items are only published when found on the verified company website.
- Accounts naming a different company are dropped.
- Financial values are published only if the register returned a number. Nothing is estimated.
- Resigned role holders are excluded. Birth dates are never read or stored.
- Each fact keeps `first_seen`, `last_changed`, `retrieved_at` and, where the register gives one, `as_of`.
- If a refresh fails (register down), the previous profile is kept and annotated.
- Deleted, bankrupt, liquidating and closed entities are reported with that status.
- Every company in the input gets exactly one result, even if nothing was found (`not_available` / `failed` states).

## Output format

Each profile contains:
- `facts`: key-value facts with source, source_url, retrieved_at, as_of
- `summary`: human-readable company description
- `envelope`: terminal envelope with all 7 required sections
- `explanation`: how the company was matched and what was found/not found
- `changes` / `history`: what changed since the last run

## Budget and cost

Defaults: 1,800 requests and 40 minutes (under the daily 2,000/45min limit).

A full profile with web discovery costs about 6-8 requests. The planner allocates depth and web discovery based on the total budget:
- depth 3 + web: entity, roles, sub-units, accounts, search, website verify, page crawl (~8 requests)
- depth 3 no web: entity, roles, sub-units, accounts (~4 requests)
- depth 2 + web: entity, accounts, search, website verify, page crawl (~6 requests)
- depth 1 no web: entity record only (~1 request)

For 100 companies at 1,800 requests: all get depth 3 + web discovery.
For 1,000 companies at 1,800 requests: the planner allocates depth 2 for most companies, with web discovery for a subset.

- Model/API: no LLM and no paid API.
- Expected run cost: $0.00 declared external API cost.
- `--no-web` flag skips web discovery (registry data only, like v1).
- `--skip-fresh-hours N` reuses profiles checked recently.

## Sources

All from permitted public sources:

1. **Brønnøysund Register Centre open APIs** (NLOD 2.0 licence):
   - Enhetsregisteret: `/enheter/{orgnr}`, `/underenheter/{orgnr}`, sub-unit count
   - Enhetsregisteret roles: `/enheter/{orgnr}/roller`
   - Regnskapsregisteret: `/regnskap/{orgnr}` (newest annual accounts)

2. **DuckDuckGo HTML search** (public, no API key): for website candidate discovery only. Search results are not used as evidence — only to find candidates that are then independently verified.

3. **Company-owned websites** (public pages): verified by matching org number or company name. Only the company's own pages are crawled for news, jobs, and social links.

## Commands

```
python -m signalpost run --input FILE --out DIR    # build profiles from a file of org numbers
python -m signalpost all                           # discover + build + serve
python -m signalpost one 923609016                 # print one profile as JSON
python -m signalpost serve --out DIR               # open the React viewer
python -m signalpost discover --n 1000             # discover org numbers
```

## Tests

```
python -m unittest discover -s tests
```

## Viewer

The prebuilt React viewer at `ui/dist` provides:
- Search by company name or org number
- Filters by status, legal form, municipality
- Per-fact source links (click any fact to see its source URL)
- Change history tracking
- "How this was matched" explanation per company
- CSV and JSON export

Rebuild after editing `ui/src`: `cd ui && npm install && npm run build`.

## Viewer credits

React 19, Vite, Tailwind, Motion, Hugeicons. Interface components are vendored from React Bits (MIT with Commons Clause) and Componentry (MIT).
