# Signalpost Agent — Research and Abstention Policy

## Identity resolution

The organisation number from Brønnøysundregistrene is the stable key for every company. No fact is published under a company unless the register returned the same organisation number we requested.

### Website verification

A candidate website is accepted only if the page contains:
1. The exact organisation number (strongest signal), OR
2. The company's legal name (normalized, case-insensitive)

Directory and aggregator sites (proff.no, gulesider.no, 1881.no, etc.) are excluded by domain filter. Social media platforms are excluded as primary websites.

### Social media profiles

Social links are extracted only from the verified company website. We do not search for social profiles independently — they must be linked from the company's own site.

### News and job postings

News items and job postings are extracted only from the company's own website (pages linked from the verified homepage). We do not use third-party job boards or news aggregators as evidence sources.

## Abstention policy

The agent returns `not_available` rather than guessing when:
- No website can be verified for the company
- A web page does not clearly belong to the exact company
- A parent brand, franchise, or sister company page is found instead
- Financial data is missing from the register

The agent never:
- Fabricates financial values
- Uses search results as claim evidence (only for candidate discovery)
- Scrapes LinkedIn, Glassdoor, Indeed, or Meta platforms
- Uses unofficial or unauthorized scrapers
- Silently converts missing values to zero

## Source hierarchy

1. **Official registers** (Brønnøysundregistrene APIs — NLOD 2.0)
2. **Registry-provided website** (hjemmeside field, then verified)
3. **Domain-guessed website** (company-name.no/.com, then verified)
4. **Proff.no public page** (to find website URL only)
5. **Verified company website** (for social, news, jobs, about text)

## What we do NOT use

- LinkedIn (access restrictions)
- Facebook/Meta (access restrictions for scraping)
- Glassdoor (access restrictions)
- Indeed (access restrictions)
- Google/Bing search APIs (no API key available)
- Any unofficial scrapers or clients
- Any paid APIs or LLMs
