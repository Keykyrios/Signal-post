# Signalpost Agent — Research and Abstention Policy

## Source policy
- **Primary**: Brønnøysund Register Centre APIs (data.brreg.no) under NLOD 2.0
- **Web verification**: Company's own verified website only
- **Search**: Bing web search for website discovery (candidates only, never evidence)
- **Domain guessing**: company-name.no patterns (Norwegian TLD only)
- **Blocked sources**: LinkedIn, Facebook, Instagram, X, YouTube, Glassdoor, Indeed, Finn.no, Proff.no, 1881.no and other directories are never scraped. Social links are only extracted when linked from a verified company website.

## Verification requirements
- Organisation number on page = strongest match (always accept)
- Company name + registered town = secondary match (reject for ENK, require 2+ word names)
- Pages with >4 valid org numbers = directory (always reject)
- Pages showing a different org number = wrong company (always reject)

## Abstention policy
- Return `not_available` when information genuinely cannot be found
- Return `ambiguous` when the company match is uncertain
- Never turn absence into zero
- Never fabricate financial values
- Better to miss data than publish under the wrong company
