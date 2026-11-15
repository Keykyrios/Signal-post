"""HTTP client with a hard request budget and wall-clock deadline.

The daily test allows 2,000 outbound requests and 45 minutes. This client stops
before either limit is crossed, so a run always ends cleanly with a report.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "signalpost/1.0 (open-data profile agent; Brreg NLOD 2.0 data)"
WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class BudgetExceeded(Exception):
    """Raised when the request budget or the time budget is used up."""


class Client:
    def __init__(self, max_requests=1800, max_seconds=40 * 60, timeout=20, retries=2):
        self.max_requests = max_requests
        self.deadline = time.monotonic() + max_seconds
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        self.requests_made = 0

    def _reserve(self):
        with self._lock:
            if self.requests_made >= self.max_requests:
                raise BudgetExceeded("request budget used up")
            if time.monotonic() >= self.deadline:
                raise BudgetExceeded("time budget used up")
            self.requests_made += 1

    def get_text(self, url, max_bytes=1_500_000):
        """Fetch a web page once (no retries, to save budget). Returns (status, text, final_url)."""
        self._reserve()
        req = urllib.request.Request(url, headers={
            "User-Agent": WEB_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "nb,no;q=0.9,en;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(max_bytes)
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(charset, "replace")
                except LookupError:
                    text = raw.decode("utf-8", "replace")
                return resp.status, text, resp.geturl()
        except urllib.error.HTTPError as err:
            return err.code, "", url
        except Exception:
            return 0, "", url

    def get_json(self, url, params=None, headers=None):
        """Return (status_code, parsed_json_or_None). Network failures return (0, None)."""
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        last_status = 0
        for attempt in range(self.retries + 1):
            self._reserve()
            req = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    return resp.status, (json.loads(body) if body.strip() else None)
            except urllib.error.HTTPError as err:
                last_status = err.code
                body = None
                try:
                    raw = err.read().decode("utf-8", "replace")
                    body = json.loads(raw) if raw.strip() else None
                except Exception:
                    body = None
                if err.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return err.code, body
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
                last_status = 0
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
        return last_status, None
