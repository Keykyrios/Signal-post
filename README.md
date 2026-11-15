# Signalpost — Norwegian company profile agent

Build a profile of any Norway-registered entity from its organisation number.
The agent queries the Brønnøysund open registers, verifies company websites
through Bing search or domain guessing, and reads dated news, open positions
and social-media links from verified sites. Every fact carries its source URL,
retrieval date, and (where applicable) reporting period.

## Quick start

```bash
# One company
python -m signalpost one 923609016

# 100-company smoke test
python -m signalpost all --n 100 --no-serve

# Evaluator command (JSONL input from Builderr)
python -m signalpost run --input companies.jsonl --out out
```

## Run instructions (evaluator)

```bash
python -m signalpost run --input <file> --out out
```

- **Input**: text file with one org number per line, or JSONL with `{"organisasjonsnummer": "..."}`.
- **Output**: `out/profiles.jsonl` (one JSON object per line, one per input company) and `out/profiles/<orgnr>.json`.
- **Budget**: default 1,800 requests, 40 minutes. No API keys needed.
- **Dependencies**: Python 3.9+ standard library only. No pip install required.
- **Cost**: $0.00 — no LLM calls, no paid APIs.

## What the agent does

1. **Registry lookup** — entity record, roles, annual accounts, sub-units from data.brreg.no (NLOD 2.0).
2. **Prefetch** — bulk entity lookup to save requests when processing many companies.
3. **Website discovery** — registry `hjemmeside` field, domain guessing (.no), Bing search.
4. **Website verification** — org number on page (strongest) or company name + registered town. Rejects directories (>4 org numbers), sole proprietorship name-only matches, and pages showing a different org number.
5. **News** — RSS/Atom feeds, JSON-LD `NewsArticle`/`BlogPosting`, HTML `<time>` tags near headings. Only dated items within 2 years are published.
6. **Job postings** — JSON-LD `JobPosting`, careers-page links matching ATS hosts or job-path patterns. Expired postings (past `validThrough`) are dropped.
7. **Social media** — LinkedIn, Facebook, Instagram, X, YouTube links extracted from verified company website only. Share buttons and generic pages are filtered out.
8. **Summary** — deterministic, built only from sourced facts. Explicitly lists what was not found.
9. **Terminal envelope** — 7-section output with explicit availability states (`available`, `not_available`).

## Output format

Each profile contains a `envelope` object with the required 7 sections:

1. `legal_identity` — org number, name, legal form, address, industry, employees, status
2. `annual_accounts` — revenue, operating result, net result, total assets, equity with period and currency
3. `leadership` — CEO, board chair, board members, auditor, accountant, sub-units
4. `web_presence` — verified website (with verification method), registry website, social profiles
5. `activity` — job postings and recent news with dates and source URLs
6. `evidence` — per-claim source, source URL, retrieval date, as-of date
7. `refresh` — checked_at, first_checked_at, changes detected, web status

## Safety rules

- A website is only accepted when its page shows the organisation number, or shows the full company name AND the registered town.
- Sole proprietorship names are personal names — the org number is required.
- Pages listing more than 4 valid org numbers are treated as directories and rejected.
- Pages showing a different org number are rejected.
- Search results are candidates only — never used as evidence.
- No LinkedIn, Meta, Glassdoor, Indeed scraping.
- No fabricated financial values — only from the accounts register.
- `not_available` is used when data genuinely cannot be found.

## Tests

```bash
python -m unittest discover -s tests -v
```

29 tests covering: org number validation, entity/role/account parsing, wrong-company rejection,
annual-account cross-company filtering, sub-unit fallback, change detection, depth planning,
website verification (org number, name+town, directory rejection, sole proprietorship), news date
filtering, RSS/Atom feed parsing, JSON-LD job posting parsing, social-link extraction, search
candidate filtering, DuckDuckGo parser, Bing search fallback, and full end-to-end pipeline.
