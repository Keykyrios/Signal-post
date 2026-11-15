"""Discover and verify company websites, crawl for news/jobs/social links.

Strategy:
1. Use the registry's own hjemmeside field (already fetched)
2. Try common domain patterns (company-name.no, company-name.com)
3. Use Proff.no public company page to find website links
4. Verify by checking if the page contains the company name or org number
5. Crawl verified sites for careers/news pages and social media links
"""

import re
import time
import urllib.parse
import urllib.request
import urllib.error
import json
import html
import ssl
import datetime as dt
import threading

from .http import BudgetExceeded

USER_AGENT = "signalpost/2.0 (open-data profile agent; Brreg NLOD 2.0 data)"

# Social media patterns
SOCIAL_PATTERNS = {
    "facebook": re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._\-]+/?', re.I),
    "instagram": re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9._\-]+/?', re.I),
    "twitter": re.compile(r'https?://(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9._\-]+/?', re.I),
    "youtube": re.compile(r'https?://(?:www\.)?youtube\.com/(?:channel|c|user|@)[a-zA-Z0-9._\-/]+/?', re.I),
    "tiktok": re.compile(r'https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9._\-]+/?', re.I),
    "linkedin": re.compile(r'https?://(?:www\.)?linkedin\.com/company/[a-zA-Z0-9._\-]+/?', re.I),
}

# Domains to skip (not company websites)
SKIP_DOMAINS = {
    "proff.no", "purehelp.no", "gulesider.no", "1881.no",
    "brreg.no", "brrreg.no", "forvalt.no", "finanstilsynet.no",
    "skatteetaten.no", "ssb.no", "lovdata.no", "regnskapstall.no",
    "allabolag.no", "firmanytt.no", "bedrift.no",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
    "x.com", "youtube.com", "tiktok.com", "pinterest.com",
    "wikipedia.org", "wikidata.org",
    "dnb.no", "sb1.no", "google.com", "google.no",
    "bing.com", "duckduckgo.com",
}

_fetch_lock = threading.Lock()


def _get_domain(url):
    """Extract the domain from a URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host.lower()
    except Exception:
        return ""


def _is_skip_domain(url):
    """Check if URL is on a domain we should skip."""
    domain = _get_domain(url)
    for skip in SKIP_DOMAINS:
        if domain == skip or domain.endswith("." + skip):
            return True
    return False


def _fetch_page(url, timeout=10):
    """Fetch a web page. Returns (status, text) or (0, None) on failure."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "no,nb,nn,en;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            ct = resp.headers.get("content-type", "")
            if "html" not in ct.lower() and "text" not in ct.lower():
                return resp.status, None
            body = resp.read(300_000).decode("utf-8", "replace")
            return resp.status, body
    except Exception:
        return 0, None


def _clean_text(html_text):
    """Strip HTML tags for simple text matching."""
    if not html_text:
        return ""
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html_text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_name(name):
    """Normalize a company name for comparison."""
    if not name:
        return ""
    name = re.sub(r'\s+(AS|ASA|ANS|DA|SA|ENK|NUF|KS|STI|FLI|BRL|BA)\s*$', '', name, flags=re.I)
    return name.lower().strip()


def _name_to_slug(name):
    """Convert company name to a URL-friendly slug for domain guessing."""
    name = _normalize_name(name)
    # Remove special chars, keep alphanumeric and spaces
    name = re.sub(r'[^a-z0-9\s\-æøåäöü]', '', name)
    # Norwegian chars
    name = name.replace('æ', 'ae').replace('ø', 'o').replace('å', 'a')
    name = name.replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')
    name = re.sub(r'\s+', '-', name.strip())
    return name


def generate_candidate_urls(company_name, registry_website=None):
    """Generate candidate website URLs from company name."""
    candidates = []
    
    # 1. Registry website (highest priority)
    if registry_website:
        url = registry_website.strip()
        if not url.startswith("http"):
            url = "https://" + url
        candidates.append(url)
    
    # 2. Domain guessing
    slug = _name_to_slug(company_name)
    if slug and len(slug) >= 3:
        # Try common TLDs
        for tld in [".no", ".com"]:
            candidates.append(f"https://www.{slug}{tld}")
            candidates.append(f"https://{slug}{tld}")
        
        # For multi-word names, also try just the first word
        words = slug.split("-")
        if len(words) >= 2 and len(words[0]) >= 3:
            for tld in [".no", ".com"]:
                candidates.append(f"https://www.{words[0]}{tld}")
    
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in candidates:
        normalized = url.lower().rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            unique.append(url)
    
    return unique


def fetch_proff_website(orgnr, client=None):
    """Try to get the company website from Proff.no's public page."""
    try:
        if client:
            client._reserve()
        
        url = f"https://www.proff.no/bransjesok?q={orgnr}"
        status, page = _fetch_page(url, timeout=8)
        if not page:
            return None
        
        # Look for external website links on the Proff page
        # Proff shows the company's website in its listing
        website_match = re.search(
            r'href="(https?://(?!(?:www\.)?proff\.no)[^"]+)"[^>]*>[^<]*(?:hjemmeside|nettside|website|besøk)',
            page, re.I
        )
        if website_match:
            url = website_match.group(1)
            if not _is_skip_domain(url):
                return url
        
        # Also try to find any external link that's not a known directory
        ext_links = re.findall(r'href="(https?://(?!(?:www\.)?(?:proff|purehelp|gulesider|1881|brreg)\.no)[^"]+)"', page, re.I)
        for link in ext_links:
            if not _is_skip_domain(link):
                domain = _get_domain(link)
                # Skip generic sites
                if domain and len(domain) > 4 and '.' in domain:
                    return link
        
        return None
    except BudgetExceeded:
        raise
    except Exception:
        return None


def verify_website(url, company_name, orgnr, client=None):
    """Verify that a URL belongs to the given company.
    
    Returns (verified: bool, page_html: str, verification_method: str)
    """
    if client:
        client._reserve()
    
    status, page_html = _fetch_page(url)
    if not page_html or status == 0:
        return False, None, None
    
    text = _clean_text(page_html)
    text_lower = text.lower()
    
    # Check 1: org number on the page (strongest signal)
    if orgnr in text:
        return True, page_html, "org_number_on_page"
    
    # Formatted org number (e.g., "923 609 016")
    formatted = f"{orgnr[:3]} {orgnr[3:6]} {orgnr[6:]}"
    if formatted in text:
        return True, page_html, "org_number_on_page"
    
    # Check 2: Full company name appears on the page
    norm_name = _normalize_name(company_name)
    if len(norm_name) >= 4 and norm_name in text_lower:
        return True, page_html, "company_name_on_page"
    
    # Check 3: Significant parts of the name (multi-word names)
    words = norm_name.split()
    if len(words) >= 2:
        significant = [w for w in words if len(w) > 3]
        if len(significant) >= 2 and all(w in text_lower for w in significant[:3]):
            return True, page_html, "name_words_on_page"
    
    return False, page_html, None


def extract_social_links(page_html):
    """Extract social media profile links from HTML."""
    if not page_html:
        return {}
    
    found = {}
    for platform, pattern in SOCIAL_PATTERNS.items():
        matches = pattern.findall(page_html)
        if matches:
            url = matches[0].rstrip('/"\'').split("?")[0].split("#")[0].rstrip("/")
            if url and len(url) > 20:
                found[platform] = url
    
    return found


def find_page_links(page_html, base_url):
    """Find links to interesting pages (careers, news, about, etc.)."""
    if not page_html:
        return {}
    
    found = {}
    base_domain = _get_domain(base_url)
    parsed_base = urllib.parse.urlparse(base_url)
    
    link_pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    for match in link_pattern.finditer(page_html):
        href = match.group(1)
        link_text = _clean_text(match.group(2)).lower()
        
        # Resolve relative URLs
        if href.startswith("/"):
            href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
        elif not href.startswith("http"):
            continue
        
        link_domain = _get_domain(href)
        if link_domain != base_domain:
            continue
        
        path = urllib.parse.urlparse(href).path.lower()
        
        # Careers/jobs
        for keyword in ["karriere", "jobb", "jobs", "careers", "career", 
                        "ledige-stillinger", "stillinger", "stilling"]:
            if keyword in path or keyword in link_text:
                if "careers" not in found:
                    found["careers"] = href
                break
        
        # News/blog
        for keyword in ["nyheter", "news", "aktuelt", "blogg", "blog", "pressemeldinger", "presse"]:
            if keyword in path or keyword in link_text:
                if "news" not in found:
                    found["news"] = href
                break
        
        # About
        for keyword in ["om-oss", "about", "om/", "about-us", "hvem-er-vi"]:
            if keyword in path or keyword in link_text:
                if "about" not in found:
                    found["about"] = href
                break
        
        # Contact
        for keyword in ["kontakt", "contact"]:
            if keyword in path or keyword in link_text:
                if "contact" not in found:
                    found["contact"] = href
                break
    
    return found


def extract_dated_items(page_html, page_url, item_type="news"):
    """Extract dated items (news articles, job postings) from a page."""
    if not page_html:
        return []
    
    items = []
    
    date_pattern = re.compile(
        r'(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d{2})'
        r'|(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})'
    )
    
    # Look for article/item structures
    article_pattern = re.compile(
        r'<(?:article|div|li|section)[^>]*class="[^"]*(?:news|article|post|job|career|stilling|nyhet|aktuelt|item|entry|card)[^"]*"[^>]*>(.*?)</(?:article|div|li|section)>',
        re.I | re.S
    )
    
    for match in article_pattern.finditer(page_html):
        block = match.group(1)
        block_text = _clean_text(block)
        
        title_match = re.search(r'<(?:h[1-4]|a)[^>]*>(.*?)</(?:h[1-4]|a)>', block, re.I | re.S)
        title = _clean_text(title_match.group(1)) if title_match else None
        
        date_match = date_pattern.search(block_text)
        date_str = None
        if date_match:
            groups = date_match.groups()
            if groups[0]:
                date_str = f"{groups[2]}-{groups[1].zfill(2)}-{groups[0].zfill(2)}"
            elif groups[3]:
                date_str = f"{groups[3]}-{groups[4].zfill(2)}-{groups[5].zfill(2)}"
        
        link_match = re.search(r'href="([^"]+)"', block, re.I)
        link = None
        if link_match:
            href = link_match.group(1)
            if href.startswith("/"):
                parsed = urllib.parse.urlparse(page_url)
                link = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif href.startswith("http"):
                link = href
        
        if title and len(title) > 5 and len(title) < 300:
            item = {
                "title": title[:200],
                "type": item_type,
                "source_url": link or page_url,
            }
            if date_str:
                item["date"] = date_str
            items.append(item)
    
    # Fallback: look for <time> elements near headings
    if not items:
        time_pattern = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*>', re.I)
        heading_pattern = re.compile(r'<h[2-4][^>]*>(.*?)</h[2-4]>', re.I | re.S)
        
        times = [(m.start(), m.group(1)) for m in time_pattern.finditer(page_html)]
        headings = [(m.start(), _clean_text(m.group(1))) for m in heading_pattern.finditer(page_html)]
        
        for hpos, htitle in headings:
            if not htitle or len(htitle) < 5 or len(htitle) > 300:
                continue
            # Find nearest time element
            nearest_time = None
            min_dist = 2000
            for tpos, tval in times:
                dist = abs(hpos - tpos)
                if dist < min_dist:
                    min_dist = dist
                    nearest_time = tval[:10]  # Just the date part
            
            if nearest_time:
                items.append({
                    "title": htitle[:200],
                    "type": item_type,
                    "date": nearest_time,
                    "source_url": page_url,
                })
    
    return items[:10]


def discover_web_presence(company_name, municipality, orgnr, registry_website=None, client=None):
    """Full web discovery pipeline for one company."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    result = {
        "verified_website": None,
        "website_verification": None,
        "social_profiles": {},
        "news_items": [],
        "job_postings": [],
        "page_links": {},
        "about_text": None,
        "retrieved_at": now,
    }
    
    # Step 1: Generate candidate URLs
    candidates = generate_candidate_urls(company_name, registry_website)
    
    # Step 2: Try Proff.no for website (one request, often has the URL)
    try:
        proff_url = fetch_proff_website(orgnr, client)
        if proff_url and proff_url not in candidates:
            candidates.insert(0, proff_url)
    except BudgetExceeded:
        raise
    except Exception:
        pass
    
    if not candidates:
        return result
    
    # Step 3: Try to verify each candidate (max 3 attempts)
    verified_url = None
    page_html = None
    verification_method = None
    
    for url in candidates[:4]:
        if _is_skip_domain(url):
            continue
        try:
            verified, phtml, method = verify_website(url, company_name, orgnr, client)
            if verified:
                verified_url = url
                page_html = phtml
                verification_method = method
                break
        except BudgetExceeded:
            raise
        except Exception:
            continue
    
    if not verified_url:
        return result
    
    result["verified_website"] = verified_url
    result["website_verification"] = verification_method
    
    # Step 4: Extract social links from homepage
    result["social_profiles"] = extract_social_links(page_html)
    
    # Step 5: Find interesting page links
    result["page_links"] = find_page_links(page_html, verified_url)
    
    # Step 6: Extract about text
    if page_html:
        meta_desc = re.search(r'<meta\s+[^>]*name="description"\s+content="([^"]+)"', page_html, re.I)
        if not meta_desc:
            meta_desc = re.search(r'<meta\s+content="([^"]+)"\s+[^>]*name="description"', page_html, re.I)
        if meta_desc:
            desc = html.unescape(meta_desc.group(1)).strip()
            if len(desc) > 20:
                result["about_text"] = desc[:500]
    
    # Step 7: Crawl news page if found
    news_url = result["page_links"].get("news")
    if news_url:
        try:
            if client:
                client._reserve()
            status, news_html = _fetch_page(news_url)
            if news_html:
                result["news_items"] = extract_dated_items(news_html, news_url, "news")
        except BudgetExceeded:
            raise
        except Exception:
            pass
    
    # Step 8: Crawl careers page if found
    careers_url = result["page_links"].get("careers")
    if careers_url:
        try:
            if client:
                client._reserve()
            status, careers_html = _fetch_page(careers_url)
            if careers_html:
                result["job_postings"] = extract_dated_items(careers_html, careers_url, "job_posting")
        except BudgetExceeded:
            raise
        except Exception:
            pass
    
    # Step 9: If no about text yet, try the about page
    if not result["about_text"] and result["page_links"].get("about"):
        try:
            if client:
                client._reserve()
            status, about_html = _fetch_page(result["page_links"]["about"])
            if about_html:
                meta_desc2 = re.search(r'<meta\s+[^>]*name="description"\s+content="([^"]+)"', about_html, re.I)
                if meta_desc2:
                    desc = html.unescape(meta_desc2.group(1)).strip()
                    if len(desc) > 20:
                        result["about_text"] = desc[:500]
                if not result["about_text"]:
                    # Try first substantial paragraph
                    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', about_html, re.I | re.S)
                    for p in paragraphs:
                        text = _clean_text(p)
                        if len(text) > 50:
                            result["about_text"] = text[:500]
                            break
        except BudgetExceeded:
            raise
        except Exception:
            pass
    
    return result
