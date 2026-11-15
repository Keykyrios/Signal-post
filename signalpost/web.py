"""Find a company's own website and read dated, linkable facts from it.

Nothing here is published unless the page proves it is about the requested company:

  * a website is accepted only if its page shows the organisation number, or shows the
    full legal name together with the registered town (never for sole proprietorships,
    whose names are people's names, and never for very short names);
  * pages that list many organisation numbers are directories and are rejected;
  * news, job postings and social links are read only from a verified site, and a news
    item is published only if a date is printed next to it.

Each web fact carries the page it came from, the date it was fetched, the date it refers
to, and the text that proved the match.
"""

import datetime as dt
import email.utils
import html as html_mod
import json
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

from . import orgnr as orgnr_mod
from .agent import FactSet, WEB_KEYS, dig, diff, now_iso

SRC_SITE = "Company's own website"
SRC_SUMMARY = "Signalpost summary of the sourced facts on this profile"

BLOCKED_HOSTS = (
    "proff.no", "1881.no", "gulesider.no", "facebook.com", "linkedin.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "brreg.no", "purehelp.no", "finn.no", "google.",
    "wikipedia.org", "bedriftsinfo.no", "opencorporates.com", "forvalt.no", "kompass.com",
    "regnskapstall.no", "bing.com", "duckduckgo.com", "tiktok.com", "pinterest.", "yelp.",
    "tripadvisor.", "trustpilot.", "dnb.no", "bisnode.", "creditsafe.", "lusha.com", "zoominfo.com",
    "rocketreach.co", "northdata.com", "yellowpages", "ntb.no", "e24.no", "dn.no", "nrk.no",
    "vg.no", "bt.no", "regjeringen.no", "altinn.no", "skatteetaten.no", "nav.no", "indeed.",
    "jooble.", "glassdoor.", "doffin.no", "telefonkatalogen.no", "firmaer.no", "brregstat.no",
)
COMPANY_SUFFIX = {"as", "asa", "ans", "da", "sa", "ba", "enk", "nuf", "ks", "stiftelse", "ltd", "gmbh", "ab", "oy", "inc", "llc"}
NEWS_WORDS = ("nyheter", "nyhet", "news", "aktuelt", "presse", "blogg", "blog", "siste-nytt", "artikler", "pressemeldinger")
JOB_WORDS = ("karriere", "ledige-stillinger", "ledige", "stilling", "jobb", "careers", "career", "jobs", "rekruttering", "work-with-us")
GENERIC_LINK_TEXT = {"karriere", "jobb", "jobber", "ledige stillinger", "stillinger", "les mer", "read more", "søk", "apply",
                     "se alle", "se alle stillinger", "flere stillinger", "alle stillinger", "open positions", "careers", "jobs",
                     "send søknad", "søk her", "til toppen", "hjem", "home", "kontakt oss", "om oss", "nyheter", "news"}
ATS_HOSTS = ("webcruiter.com", "easycruit.com", "recman.no", "jobylon.com", "varbi.com", "hrmanager.no", "teamtailor.com",
             "lever.co", "greenhouse.io", "workable.com", "personio.de", "personio.com", "reachmee.com", "jobbnorge.no",
             "smartrecruiters.com", "join.com", "cvpartner.com")
MONTHS = {"januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8,
          "september": 9, "oktober": 10, "november": 11, "desember": 12,
          "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7,
          "october": 10, "december": 12}
MAX_NEWS_AGE_DAYS = 730


# ---------------------------------------------------------------- helpers

def strip_tags(markup):
    markup = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?s)<!--.*?-->", " ", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", markup)
    text = html_mod.unescape(text).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def norm(text):
    text = html_mod.unescape(text or "").lower().replace("&", " og ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def core_name(name):
    return " ".join(t for t in norm(name).split() if t not in COMPANY_SUFFIX)


def host_of(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url, base_host):
    host = host_of(url)
    return bool(host) and (host == base_host or host.endswith("." + base_host) or base_host.endswith("." + host))


def blocked(url):
    host = host_of(url)
    return (not host) or any(b in host for b in BLOCKED_HOSTS)


def clean_url(url, base=None):
    if not url:
        return None
    url = html_mod.unescape(url.strip())
    if url.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
        return None
    if base:
        url = urllib.parse.urljoin(base, url)
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^https?://", url, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
            url = "https://" + url
        else:
            return None
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def iso_day(value):
    """Parse several date spellings to YYYY-MM-DD, or None."""
    if not value:
        return None
    value = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    try:
        if m:
            return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", value)
        if m:
            return dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        m = re.match(r"^(\d{1,2})\.?\s+([A-Za-zæøåÆØÅ]+)\.?\s+(\d{4})$", value)
        if m:
            return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])).isoformat() if m[2].lower() in MONTHS else None
    except ValueError:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def too_old(day, today):
    try:
        return (today - dt.date.fromisoformat(day)).days > MAX_NEWS_AGE_DAYS
    except ValueError:
        return True


def in_future(day, today):
    try:
        return dt.date.fromisoformat(day) > today + dt.timedelta(days=1)
    except ValueError:
        return True


# ---------------------------------------------------------------- search

import base64

class Searcher:
    """Web search. Brave API > Bing scrape > DuckDuckGo HTML, in that order."""

    def __init__(self, client, gap_seconds=1.2):
        self.client = client
        self.gap = gap_seconds
        self.lock = threading.Lock()
        self.last = 0.0
        self.queries = 0
        self.brave_key = os.environ.get("BRAVE_API_KEY")
        self.cost_per_query = float(os.environ.get("SIGNALPOST_SEARCH_COST_USD", "0") or 0)

    @property
    def cost_usd(self):
        return round(self.queries * self.cost_per_query, 4)

    def search(self, query, count=6):
        with self.lock:
            wait = self.gap - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.queries += 1
        if self.brave_key:
            code, body = self.client.get_json(
                "https://api.search.brave.com/res/v1/web/search",
                {"q": query, "count": count, "country": "no", "search_lang": "no"},
                headers={"X-Subscription-Token": self.brave_key},
            )
            if code == 200 and isinstance(body, dict):
                return [r.get("url") for r in (dig(body, "web", "results") or []) if r.get("url")][:count]
            return []
        # Try Bing first (more reliable), fall back to DuckDuckGo
        results = self._bing_search(query, count)
        if results:
            return results
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": "no-no"})
        code, text, _ = self.client.get_text(url)
        return parse_ddg(text)[:count] if code == 200 else []

    def _bing_search(self, query, count):
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "count": str(count)})
        code, text, _ = self.client.get_text(url)
        if code != 200 or not text:
            return []
        return parse_bing(text)[:count]


def parse_bing(text):
    """Extract URLs from Bing search result page."""
    urls = []
    # Extract from cite tags (clean URLs)
    for m in re.finditer(r'<cite[^>]*>(.*?)</cite>', text, re.S):
        cite = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        cite = cite.split(" ")[0].replace(" › ", "/").replace("›", "/")
        url = clean_url(cite)
        if url and not blocked(url):
            urls.append(url)
    # Also try the tracking links with base64-encoded URLs
    for m in re.finditer(r'<a[^>]+href="https://www\.bing\.com/ck/a[^"]*u=a1([A-Za-z0-9_-]+)', text):
        try:
            padded = m.group(1) + "=" * (4 - len(m.group(1)) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
            if decoded.startswith("http") and not blocked(decoded):
                urls.append(decoded)
        except Exception:
            pass
    # Deduplicate preserving order
    seen = set()
    unique = []
    for u in urls:
        h = host_of(u)
        if h and h not in seen:
            seen.add(h)
            unique.append(u)
    return unique


def parse_ddg(text):
    urls = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', text):
        href = html_mod.unescape(m.group(1))
        if "uddg=" in href:
            href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("uddg", [""])[0])
        elif href.startswith("//"):
            href = "https:" + href
        if href.startswith("http"):
            urls.append(href)
    return urls


# ---------------------------------------------------------------- verification

NUM_RE = re.compile(r"(?<!\d)(\d{3})[ . ]?(\d{3})[ . ]?(\d{3})(?!\d)")


def orgnrs_on_page(text):
    found = {}
    for m in NUM_RE.finditer(text):
        number = "".join(m.groups())
        if orgnr_mod.is_valid(number):
            found.setdefault(number, m.start())
    return found


def quote_around(text, pos, width=48):
    return re.sub(r"\s+", " ", text[max(0, pos - width): pos + width]).strip()


def title_of(markup):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
    parts = [html_mod.unescape(m.group(1))] if m else []
    for pat in (r'(?is)<meta[^>]+property=["\']og:site_name["\'][^>]*content=["\']([^"\']+)',
                r'(?is)<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:site_name["\']'):
        mm = re.search(pat, markup)
        if mm:
            parts.append(html_mod.unescape(mm.group(1)))
    parts += [strip_tags(mm.group(1)) for mm in re.finditer(r"(?is)<h1[^>]*>(.*?)</h1>", markup)]
    return " | ".join(parts)


def verify_page(markup, company):
    """Return (level, evidence) if the page is provably about this company, else (None, reason)."""
    text = strip_tags(markup)
    if len(text) < 80:
        return None, "page has too little text to check"
    numbers = orgnrs_on_page(text)
    if len(numbers) > 4:
        return None, "page lists many organisation numbers (looks like a directory)"
    if company["orgnr"] in numbers:
        return "orgnr_on_page", 'page shows the organisation number: "%s"' % quote_around(text, numbers[company["orgnr"]])
    if numbers:
        return None, "page shows a different organisation number (%s) and not this one" % next(iter(numbers))
    if company.get("legal_code") == "ENK":
        return None, "sole proprietorship names are personal names, so the organisation number is required"
    core = core_name(company["name"])
    if len(core.split()) < 2 and len(core) < 9:
        return None, "the name is too short to be matched by name alone"
    hay, title = norm(text), norm(title_of(markup))
    pattern = r"(?<!\w)" + re.escape(core) + r"(?!\w)"
    town = norm(company.get("town") or "")
    if not re.search(pattern, hay):
        return None, "page does not show the company name"
    if not re.search(pattern, title) and len(re.findall(pattern, hay)) < 2:
        return None, "the company name appears only once and not in the page title"
    if not town or not re.search(r"(?<!\w)" + re.escape(town) + r"(?!\w)", hay):
        return None, "page does not show the registered town (%s)" % (company.get("town") or "unknown")
    return "name_and_town", 'page shows the name "%s" and the registered town "%s"' % (company["name"], company["town"])


# ---------------------------------------------------------------- reading a verified site

LINK_RE = re.compile(r'(?is)<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>')


def anchors(markup, base):
    out = []
    for m in LINK_RE.finditer(markup):
        url = clean_url(m.group(1), base)
        if url:
            out.append((url, strip_tags(m.group(2))[:160]))
    return out


def find_links(markup, base, base_host):
    news, jobs, social = [], [], {}
    for url, text in anchors(markup, base):
        path = urllib.parse.urlsplit(url.lower()).path
        if same_site(url, base_host):
            slug = path + " " + norm(text).replace(" ", "-")
            if any(w in slug for w in JOB_WORDS):
                jobs.append(url)
            elif any(w in slug for w in NEWS_WORDS):
                news.append(url)
        host = host_of(url)
        segs = [s for s in path.split("/") if s]
        if host.endswith("linkedin.com") and len(segs) >= 2 and segs[0] == "company":
            social.setdefault("social_linkedin", url)
        elif host.endswith("facebook.com") and segs and "sharer" not in path and segs[0] not in (
                "share", "plugins", "tr", "dialog", "login", "policies", "help"):
            social.setdefault("social_facebook", url)
        elif host.endswith("instagram.com") and segs and segs[0] not in ("p", "explore", "accounts", "reel", "share"):
            social.setdefault("social_instagram", url)
        elif host in ("x.com", "twitter.com") and segs and segs[0] not in ("intent", "share", "home", "i", "search"):
            social.setdefault("social_x", url)
        elif host.endswith("youtube.com") and segs and (segs[0].startswith("@") or segs[0] in ("channel", "c", "user")):
            social.setdefault("social_youtube", url)
    shortest = lambda urls: sorted(dict.fromkeys(urls), key=lambda u: (len(urllib.parse.urlsplit(u).path), u))
    return shortest(news), shortest(jobs), social


def feed_links(markup, base):
    out = []
    for m in re.finditer(r"(?is)<link\b[^>]*>", markup):
        tag = m.group(0)
        if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            h = re.search(r'href=["\']([^"\']+)', tag)
            url = clean_url(h.group(1), base) if h else None
            if url:
                out.append(url)
    return out


def parse_feed(text):
    """Return (title, link, day) tuples from RSS or Atom. Items without a date are dropped."""
    try:
        root = ET.fromstring(text.strip().encode("utf-8"))
    except (ET.ParseError, ValueError):
        return []
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        fields = {}
        for ch in el:
            t = ch.tag.split("}")[-1]
            if t == "link":
                fields.setdefault("link", ch.get("href") or (ch.text or "").strip())
            elif t in ("title", "pubDate", "published", "updated", "date"):
                fields.setdefault(t, (ch.text or "").strip())
        day = iso_day(fields.get("pubDate") or fields.get("published") or fields.get("date") or fields.get("updated"))
        if fields.get("title") and fields.get("link") and day:
            items.append((html_mod.unescape(fields["title"]), fields["link"], day))
    return items


def jsonld_blocks(markup):
    out = []
    for m in re.finditer(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', markup):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                out.append(node)
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return out


def _types(node):
    t = node.get("@type")
    return [t] if isinstance(t, str) else (t if isinstance(t, list) else [])


def news_from_html(markup, base):
    """Return (title, link, day) tuples that have a printed date. Never guesses a date."""
    items = []
    for node in jsonld_blocks(markup):
        if any(t in ("NewsArticle", "BlogPosting", "Article") for t in _types(node)):
            day = iso_day(node.get("datePublished") or node.get("dateCreated"))
            title = node.get("headline") or node.get("name")
            link = clean_url(node.get("url") or dig(node, "mainEntityOfPage", "@id") or "", base)
            if day and title and link:
                items.append((html_mod.unescape(str(title)), link, day))
    for block in re.finditer(r"(?is)<(article|li|div)\b[^>]*>((?:(?!</\1>).){20,1500})</\1>", markup):
        inner = block.group(2)
        t = re.search(r'(?is)<time\b[^>]*datetime=["\']([^"\']+)', inner)
        day = iso_day(t.group(1)) if t else None
        if not day:
            m = re.search(r"\b(\d{1,2}\.\s?[A-Za-zæøå]+\s\d{4}|\d{1,2}\.\d{1,2}\.\d{4})\b", strip_tags(inner))
            day = iso_day(m.group(1)) if m else None
        if not day:
            continue
        links = [(u, x) for u, x in anchors(inner, base) if len(x) >= 12]
        if links:
            items.append((links[0][1], links[0][0], day))
    return items


def pick_newest_news(items, base_host, today):
    best = None
    for title, link, day in items:
        link = clean_url(link)
        if not link or not same_site(link, base_host) or in_future(day, today):
            continue
        if best is None or day > best[2]:
            best = (title.strip(), link, day)
    return best


def jobs_from_html(markup, base, base_host, today):
    """Return (title, url, posted_day_or_None) for open postings listed on a careers page."""
    found = []
    for node in jsonld_blocks(markup):
        if "JobPosting" in _types(node):
            valid = iso_day(node.get("validThrough"))
            if valid and valid < today.isoformat():
                continue
            if node.get("title"):
                found.append((html_mod.unescape(str(node["title"])),
                              clean_url(node.get("url") or "", base) or base, iso_day(node.get("datePosted"))))
    if found:
        return found[:5]
    for url, text in anchors(markup, base):
        if not (8 <= len(text) <= 90) or norm(text) in GENERIC_LINK_TEXT or url.rstrip("/") == base.rstrip("/"):
            continue
        path = urllib.parse.urlsplit(url.lower()).path
        on_ats = any(host_of(url).endswith(a) for a in ATS_HOSTS)
        looks_job = re.search(r"/(stilling|stillinger|jobb|jobs?|ledig|position|vacanc|career|karriere)[a-z-]*/[^/]+", path)
        if (on_ats or (same_site(url, base_host) and looks_job)) and url not in [f[1] for f in found]:
            found.append((text, url, None))
    return found[:5]


# ---------------------------------------------------------------- orchestration

def _name_slug(name):
    """Convert a company name to a .no domain slug."""
    text = core_name(name)
    text = re.sub(r"[^a-z0-9\s\-æøåäöü]", "", text)
    text = text.replace("æ", "ae").replace("ø", "o").replace("å", "a")
    text = text.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return re.sub(r"\s+", "-", text.strip())


def _candidates(company, searcher, allow_search):
    seen, out = set(), []

    def add(url, tag):
        url = clean_url(url)
        if url and not blocked(url) and host_of(url) not in seen:
            seen.add(host_of(url))
            out.append((url, tag))

    if company.get("declared_site"):
        add(company["declared_site"], "declared in the register")

    # Domain guessing: try company-name.no (safe for Norwegian companies)
    slug = _name_slug(company["name"])
    if slug and len(slug) >= 4:
        add("https://www.%s.no" % slug, "domain guess (.no)")
        # For multi-word names, try first distinctive word
        parts = slug.split("-")
        if len(parts) >= 2 and len(parts[0]) >= 5:
            add("https://www.%s.no" % parts[0], "domain guess (short .no)")

    if allow_search and searcher and len(out) < 3:
        query = '"%s" %s' % (company["name"], company.get("town") or "")
        for url in searcher.search(query.strip()):
            parts = urllib.parse.urlsplit(url)
            add(urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/", "", "")), "search result")
            if len(out) >= 4:
                break
    return out[:4]


def company_view(profile):
    facts = profile.get("facts") or {}
    addr = dig(facts, "business_address", "value") or ""
    m = re.search(r"\b\d{4}\s+([^\d,]+)$", addr)
    return {
        "orgnr": profile["orgnr"],
        "name": dig(facts, "name", "value") or "",
        "town": (m.group(1).strip() if m else "") or dig(facts, "municipality", "value") or "",
        "legal_code": dig(facts, "legal_form", "code"),
        "declared_site": profile.get("register_site") or "",
    }


def enrich(client, profile, searcher=None, allow_search=True, today=None):
    """Return (web_facts, notes, status). status is verified, no_site or error.

    Raises BudgetExceeded when the budget runs out; the caller keeps the previous values.
    """
    today = today or dt.date.today()
    company = company_view(profile)
    notes, fs = [], FactSet(now_iso())
    if not company["name"]:
        return {}, ["No company name is available, so no web search was made."], "no_site"

    verified, errors, rejected = None, 0, 0
    for url, how in _candidates(company, searcher, allow_search):
        code, markup, final = client.get_text(url)
        if code != 200 or not markup:
            errors += 1
            notes.append("Could not open %s (%s, HTTP %s)." % (url, how, code))
            continue
        level, evidence = verify_page(markup, company)
        if level:
            verified = (final, markup, level, evidence, how)
            break
        rejected += 1
        notes.append("Rejected %s (%s): %s." % (final, how, evidence))

    if not verified:
        notes.append("No own website could be verified, so no news, jobs or social pages are published.")
        return {}, notes, ("error" if errors and not rejected else "no_site")

    site, markup, level, evidence, how = verified
    base_host = host_of(site)
    fs.add("own_website", site, site, SRC_SITE, extra={"match": level, "evidence": evidence, "found_via": how})
    notes.append("Website %s accepted (%s): %s." % (site, how, evidence))

    news_links, job_links, social = find_links(markup, site, base_host)
    for key, url in social.items():
        fs.add(key, url, site, SRC_SITE, extra={"evidence": "linked from the company's own website"})

    newest, feeds = None, feed_links(markup, site)
    if feeds:
        code, text, _ = client.get_text(feeds[0])
        if code == 200:
            newest = pick_newest_news(parse_feed(text), base_host, today)
    if newest is None and news_links:
        code, text, final = client.get_text(news_links[0])
        if code == 200:
            newest = pick_newest_news(news_from_html(text, final), base_host, today)
    if newest is None and not news_links:
        newest = pick_newest_news(news_from_html(markup, site), base_host, today)
    if newest:
        title, link, day = newest
        if too_old(day, today):
            notes.append("The newest dated item on the site is from %s, which is older than two years, so it is not published." % day)
        else:
            fs.add("news_latest", title, link, SRC_SITE, as_of=day,
                   extra={"evidence": "listed with the date %s on the company's own website" % day})
    else:
        notes.append("No dated news item was found on the company's own website.")

    if job_links:
        code, text, final = client.get_text(job_links[0])
        if code == 200:
            fs.add("careers_page", final, final, SRC_SITE, extra={"evidence": "careers page on the company's own website"})
            posts = jobs_from_html(text, final, base_host, today)
            if posts:
                posted = [p[2] for p in posts if p[2]]
                fs.add("open_positions", [p[0] for p in posts], final, SRC_SITE, as_of=max(posted) if posted else None,
                       extra={"evidence": "listed as open on the careers page when it was fetched",
                              "links": [p[1] for p in posts]})
            else:
                notes.append("The careers page lists no open positions.")
        else:
            notes.append("The careers page could not be opened (HTTP %s)." % code)
    else:
        notes.append("No careers page is linked from the company's own website.")
    if not social:
        notes.append("No social media page is linked from the company's own website.")
    return fs.facts, notes, "verified"


def not_found(facts):
    gaps = []
    if "own_website" not in facts:
        gaps.append("a verified own website")
    if "news_latest" not in facts:
        gaps.append("a recent dated news item")
    if "open_positions" not in facts:
        gaps.append("an open job posting")
    if not any(k.startswith("social_") for k in facts):
        gaps.append("a social media page")
    return gaps


def summarize(facts, gaps):
    """A short written summary built only from facts already on the profile."""
    f = lambda k: dig(facts, k, "value")
    if not f("name"):
        return None
    first = str(f("name"))
    if f("legal_form"):
        first += " (%s)" % str(f("legal_form")).lower()
    if f("municipality"):
        first += " is based in " + str(f("municipality")).title()
    else:
        first += " is listed"
    if f("registered_in_enhetsregisteret"):
        first += ", registered in the Brønnøysund register on %s" % f("registered_in_enhetsregisteret")
    bits = [first + "."]
    if f("industry_1"):
        bits.append("Its main industry in the register is %s." % str(f("industry_1")).lower())
    if f("employees") is not None:
        bits.append("The register lists %s employees." % f("employees"))
    if f("own_website"):
        shows = "the organisation number" if dig(facts, "own_website", "match") == "orgnr_on_page" else "the company name and town"
        bits.append("Its own website, %s, shows %s." % (f("own_website"), shows))
    if f("news_latest"):
        bits.append('The newest dated item on that site is "%s" (%s).' % (f("news_latest"), dig(facts, "news_latest", "as_of")))
    if f("open_positions"):
        bits.append("Open positions listed: %s." % "; ".join(f("open_positions")[:3]))
    names = {"social_linkedin": "LinkedIn", "social_facebook": "Facebook", "social_instagram": "Instagram",
             "social_x": "X", "social_youtube": "YouTube"}
    socials = sorted(names[k] for k in facts if k in names)
    if socials:
        bits.append("The site links to its %s page." % " and ".join(socials))
    if gaps:
        bits.append("Not found: %s." % ", ".join(gaps))
    return " ".join(bits)


def merge_web(profile, web_facts, notes, status):
    """Merge fresh web facts into the profile, keeping history. A failed lookup keeps earlier values."""
    now = now_iso()
    facts = profile.setdefault("facts", {})
    old_web = {k: facts[k] for k in WEB_KEYS if k in facts}
    profile["web"] = {"status": status, "checked_at": now, "notes": notes}
    if status == "error":
        profile["web"]["notes"] = notes + ["The lookup failed, so earlier web facts, if any, are kept."]
        profile["explanation"] = [n for n in profile.get("explanation", []) if not n.startswith("Web: ")] + ["Web: " + n for n in profile["web"]["notes"]]
        return profile
    base_facts = {k: v for k, v in facts.items() if k not in WEB_KEYS}
    merged = dict(base_facts)
    merged.update(web_facts)
    gaps = not_found(merged)
    text = summarize(merged, gaps)
    if text:
        merged["summary"] = {"value": text, "source": SRC_SUMMARY,
                             "source_url": dig(merged, "own_website", "source_url") or dig(merged, "name", "source_url"),
                             "retrieved_at": now, "evidence": "built only from the facts listed on this profile"}
    only_web, changes = diff({"facts": old_web}, {k: v for k, v in merged.items() if k in WEB_KEYS}, now)
    changes = [c for c in changes if c["field"] != "summary"]
    profile["facts"] = {**base_facts, **only_web}
    profile["changes"] = (profile.get("changes") or []) + changes
    profile["history"] = ((profile.get("history") or []) + changes)[-50:]
    profile["not_found"] = gaps
    profile["explanation"] = [n for n in profile.get("explanation", []) if not n.startswith("Web: ")] + ["Web: " + n for n in notes]
    return profile


# ---------------------------------------------------------------- terminal envelope

def _avail(facts, key):
    return "available" if key in facts else "not_available"


def build_envelope(profile):
    """Build the required 7-section terminal envelope from a completed profile."""
    facts = profile.get("facts") or {}
    orgnr = profile["orgnr"]
    status = profile.get("status", "unknown")
    f = lambda k: dig(facts, k, "value")

    # Section 1: Legal identity and public brand
    legal_identity = {
        "organisation_number": orgnr,
        "name": f("name"),
        "legal_form": f("legal_form"),
        "legal_form_code": dig(facts, "legal_form", "code"),
        "business_address": f("business_address"),
        "municipality": f("municipality"),
        "postal_address": f("postal_address"),
        "founded": f("founded"),
        "industry": f("industry_1"),
        "industry_code": dig(facts, "industry_1", "code"),
        "employees": f("employees"),
        "status": status,
    }

    # Section 2: Latest annual accounts and available history
    annual_accounts = {
        "state": _avail(facts, "revenue"),
        "revenue": f("revenue"),
        "operating_result": f("operating_result"),
        "net_result": f("net_result"),
        "total_assets": f("total_assets"),
        "equity": f("equity"),
        "currency": dig(facts, "revenue", "currency") or dig(facts, "total_assets", "currency"),
        "period_end": dig(facts, "revenue", "as_of") or dig(facts, "total_assets", "as_of"),
        "period_start": dig(facts, "revenue", "period_start") or dig(facts, "total_assets", "period_start"),
    }

    # Section 3: Leadership and registered workplaces
    leadership = {
        "ceo": {"state": _avail(facts, "ceo"), "value": f("ceo")},
        "board_chair": {"state": _avail(facts, "board_chair"), "value": f("board_chair")},
        "board_size": {"state": _avail(facts, "board_size"), "value": f("board_size"),
                       "members": dig(facts, "board_size", "members")},
        "auditor": {"state": _avail(facts, "auditor"), "value": f("auditor")},
        "accountant": {"state": _avail(facts, "accountant"), "value": f("accountant")},
        "sub_units": {"state": _avail(facts, "sub_units"), "value": f("sub_units")},
    }

    # Section 4: Verified official website and company-owned profiles
    social_profiles = {}
    for key in facts:
        if key.startswith("social_"):
            platform = key[7:]
            social_profiles[platform] = {
                "state": "available",
                "value": facts[key].get("value"),
                "source_url": facts[key].get("source_url"),
            }
    web_presence = {
        "verified_website": {
            "state": _avail(facts, "own_website"),
            "value": f("own_website"),
            "verification_method": dig(facts, "own_website", "match"),
            "evidence": dig(facts, "own_website", "evidence"),
        },
        "registry_website": {
            "state": "available" if profile.get("register_site") else "not_available",
            "value": profile.get("register_site"),
        },
        "social_profiles": social_profiles or {"state": "not_available"},
    }

    # Section 5: Hiring and dated public activity from permitted sources
    activity = {
        "job_postings": {
            "state": _avail(facts, "open_positions"),
            "items": f("open_positions") or [],
            "careers_page": f("careers_page"),
        },
        "recent_news": {
            "state": _avail(facts, "news_latest"),
            "latest_title": f("news_latest"),
            "latest_date": dig(facts, "news_latest", "as_of"),
            "source_url": dig(facts, "news_latest", "source_url"),
        },
    }

    # Section 6: Claim-level evidence and availability state
    evidence = {}
    for key, fact in facts.items():
        if isinstance(fact, dict) and "source_url" in fact:
            evidence[key] = {
                "source": fact.get("source"),
                "source_url": fact.get("source_url"),
                "retrieved_at": fact.get("retrieved_at"),
                "as_of": fact.get("as_of"),
            }
            if fact.get("evidence"):
                evidence[key]["evidence"] = fact["evidence"]

    # Section 7: Refresh metadata and material changes
    refresh = {
        "checked_at": profile.get("checked_at"),
        "first_checked_at": profile.get("first_checked_at"),
        "changes_detected": len(profile.get("changes", [])),
        "web_status": dig(profile, "web", "status") or "not_checked",
    }

    return {
        "legal_identity": legal_identity,
        "annual_accounts": annual_accounts,
        "leadership": leadership,
        "web_presence": web_presence,
        "activity": activity,
        "evidence": evidence,
        "refresh": refresh,
    }


def empty_envelope(orgnr, status, reason, checked_at):
    """Build a complete 7-section envelope with not_available states for error/missing cases."""
    return {
        "legal_identity": {
            "organisation_number": orgnr,
            "name": None,
            "legal_form": None,
            "status": status,
        },
        "annual_accounts": {"state": "not_available"},
        "leadership": {
            "ceo": {"state": "not_available"},
            "board_chair": {"state": "not_available"},
            "board_size": {"state": "not_available"},
            "auditor": {"state": "not_available"},
            "accountant": {"state": "not_available"},
            "sub_units": {"state": "not_available"},
        },
        "web_presence": {
            "verified_website": {"state": "not_available"},
            "registry_website": {"state": "not_available"},
            "social_profiles": {"state": "not_available"},
        },
        "activity": {
            "job_postings": {"state": "not_available"},
            "recent_news": {"state": "not_available"},
        },
        "evidence": {},
        "refresh": {
            "checked_at": checked_at,
            "first_checked_at": checked_at,
            "changes_detected": 0,
            "state": status,
            "note": reason,
        },
    }
