# Signalpost agent

Give it Norwegian organisation numbers. It returns a profile per company: facts, a source link and retrieval date for every fact, the date each fact refers to, and a plain-language note on how the company was matched. Re-running refreshes profiles and records what changed.

## Run it

Python 3.9+, standard library only. No install step, no API key.

```
python -m signalpost run --input companies.txt --out out
```

Then open `out/index.html`. Files written:

- `out/profiles/<orgnr>.json` and `out/profiles.jsonl`: the profiles
- `out/run_report.json`: companies, status counts, requests used, seconds, cost
- `out/index.html`: browsable viewer (works offline, light and dark)

To build a 1,000 company set first:

```
python -m signalpost discover --n 1000 --out companies.txt
python -m signalpost run --input companies.txt --out out
```

Other commands: `python -m signalpost one 923609016` prints one profile; `python -m signalpost ui --out out` rebuilds the page. Tests: `python -m unittest discover -s tests`.

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

Defaults stop at 1,800 requests and 40 minutes, under the daily 2,000 requests and 45 minutes. About 4 requests per company, so 100 companies use roughly 400.

- Model/API: no LLM and no paid API. Registers only.
- Expected run cost: $0.00 declared external API cost.
- Use `--skip-fresh-hours N` to reuse profiles checked recently and save requests.

## Not covered

The registers do not publish ownership, shareholders, or history before the latest filed accounts. The agent does not scrape company websites, because matching a web page to the right company is the main source of wrong-company errors.
