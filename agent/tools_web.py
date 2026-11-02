import logging
import re
from html.parser import HTMLParser

import requests
from langchain_core.tools import tool

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    from scrapling.fetchers import Fetcher as _ScraplingFetcher
except Exception:  # pragma: no cover - optional dependency
    _ScraplingFetcher = None

logging.getLogger("scrapling").setLevel(logging.WARNING)

FETCH_TIMEOUT = 20
MAX_FETCH_CHARS = 8000
USER_AGENT = "KRATOS-agent/1.0"


class _TextExtractor(HTMLParser):
    """Collect visible text and the <title>, skipping script/style/noscript."""

    _SKIP_TAGS = ("script", "style", "noscript")

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self.title_parts = []
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data.strip())
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.text_parts.append(text)


def _html_to_text(html: str, url: str = ""):
    """Return (title, readable_text) for an HTML document.

    Uses trafilatura to pull the main article text when available (drops
    navigation, ads, footers), falling back to a full visible-text extraction.
    """
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        extractor = None

    title = ""
    if extractor is not None:
        title = " ".join(p for p in extractor.title_parts if p).strip()

    if trafilatura is not None:
        try:
            extracted = trafilatura.extract(
                html, url=url or None, include_comments=False, include_tables=True
            )
        except Exception:
            extracted = None
        if extracted and extracted.strip():
            return title, extracted

    if extractor is None:
        return "", html
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(extractor.text_parts))
    return title, text


def _decode(raw, encoding):
    if isinstance(raw, bytes):
        try:
            return raw.decode(encoding or "utf-8", errors="replace")
        except (LookupError, TypeError):
            return raw.decode("utf-8", errors="replace")
    return raw


def _fetch_via_scrapling(url: str):
    """Return (content_type, body) using Scrapling's stealth HTTP fetcher.

    For non-HTML content the raw response body is returned (Scrapling would
    otherwise wrap plain text in an <html><body> skeleton). Returns None when
    Scrapling is unavailable, the page errors, or the request fails, so the
    caller can fall back to plain requests.
    """
    if _ScraplingFetcher is None:
        return None
    try:
        page = _ScraplingFetcher.get(url, timeout=FETCH_TIMEOUT)
        status = getattr(page, "status", None)
        if status is not None and status >= 400:
            return None
        headers = getattr(page, "headers", None) or {}
        ctype = headers.get("content-type", "") if hasattr(headers, "get") else ""
        if ctype and "html" not in ctype.lower():
            raw = getattr(page, "body", None)
            if raw is not None:
                return ctype, _decode(raw, getattr(page, "encoding", None))
        body = getattr(page, "html_content", None)
        if body is None:
            body = str(page)
        return ctype, body
    except Exception:
        return None


def _http_get(url: str):
    """GET a URL and return (title, text).

    Prefers Scrapling's stealth HTTP fetcher (better header/TLS fingerprinting),
    falling back to requests. Raises on network/HTTP errors.
    """
    fetched = _fetch_via_scrapling(url)
    if fetched is not None:
        content_type, body = fetched
        if not content_type or "html" in content_type.lower():
            return _html_to_text(body, url=url)
        return "", body

    response = requests.get(
        url, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type.lower():
        return _html_to_text(response.text, url=url)
    return "", response.text


def _github_blob_to_raw(url: str) -> str:
    """Rewrite a github.com blob/raw URL to its raw.githubusercontent.com form."""
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/(.+)", url.strip()
    )
    if not match:
        return url
    owner, repo, rest = match.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{rest}"


@tool
def fetch_url(url: str) -> str:
    """Fetch a URL and return its readable text (title, then main content).

    Uses a stealth HTTP fetch (Scrapling) and extracts the main article text
    (trafilatura). Use this after web_search to read a specific page in full.
    JavaScript-only pages may still return little text; say so rather than
    guessing the contents.
    """
    if not re.match(r"https?://", url.strip()):
        return "Error: url must start with http:// or https://"
    try:
        title, text = _http_get(url.strip())
    except requests.RequestException as e:
        return f"Error fetching {url}: {e}"
    if len(text) > MAX_FETCH_CHARS:
        text = text[:MAX_FETCH_CHARS] + "\n... (content truncated)"
    header = f"# {title}\n\n" if title else ""
    return header + (text.strip() or "(no readable text found on the page)")


@tool
def scrape_github_file(url: str) -> str:
    """Fetch the raw content of a file from a public GitHub URL.

    Accepts github.com/owner/repo/blob/... or .../raw/... URLs and rewrites them
    to raw.githubusercontent.com. Also accepts a raw.githubusercontent.com URL.
    """
    raw_url = _github_blob_to_raw(url)
    try:
        _, text = _http_get(raw_url)
    except requests.RequestException as e:
        return f"Error fetching {url}: {e}"
    if len(text) > MAX_FETCH_CHARS:
        text = text[:MAX_FETCH_CHARS] + "\n... (file truncated)"
    return text.strip() or "(empty file)"


web_tools = [fetch_url, scrape_github_file]
