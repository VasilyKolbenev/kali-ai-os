import sys
import os
import argparse
import urllib.parse
import json
from html.parser import HTMLParser
from urllib.parse import urlparse

# Bundled inside KALI — make the kernel package importable so egress can flow
# through the fail-closed SSRF guard instead of raw urllib (the --url is
# user/voice-supplied, a third-party-reachable SSRF path).
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)
from kernel.sandbox.http_client import (  # noqa: E402
    HttpRequest,
    SandboxHttpClient,
    SandboxHttpError,
)

_AGENT = "web-surfer"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_DDG_HOST = "lite.duckduckgo.com"


def _guarded_get(url: str, allowed_hosts: list[str]) -> str:
    """GET ``url`` through the SSRF-guarded client and return the body text.

    The guard blocks private/loopback/link-local targets (SSRF), re-checks every
    redirect, and enforces the host whitelist. Raises ``SandboxHttpError`` on a
    block or transport failure — callers translate that into an error string.

    Args:
        url: Absolute URL to fetch.
        allowed_hosts: Host whitelist passed to the guard.

    Returns:
        The decoded response body.
    """
    client = SandboxHttpClient(_AGENT, allowed_domains=allowed_hosts)
    resp = client.request(
        HttpRequest(url=url, headers={"User-Agent": _USER_AGENT}, timeout=10.0)
    )
    return resp.body.decode("utf-8", errors="ignore")

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.in_script_or_style = False

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style', 'noscript']:
            self.in_script_or_style = True

    def handle_endtag(self, tag):
        if tag in ['script', 'style', 'noscript']:
            self.in_script_or_style = False

    def handle_data(self, data):
        if not self.in_script_or_style:
            clean = data.strip()
            if clean:
                self.text.append(clean)

def _extract_text(html: str) -> str:
    """Strip scripts/styles and collapse an HTML document to visible text."""
    extractor = TextExtractor()
    extractor.feed(html)
    return " ".join(extractor.text)


def fetch_url(url: str) -> str:
    # The URL is user/voice-supplied — route through the SSRF guard, which
    # blocks private/loopback/link-local hosts and re-checks redirects. By
    # design web-surfer fetches arbitrary PUBLIC pages, so the host allowlist is
    # the requested host itself; the private-IP block (not the allowlist) is the
    # real SSRF defense here. Require https to avoid cleartext/MITM.
    if not url.lower().startswith("https://"):
        return "Error fetching URL: only https:// URLs are allowed"
    host = (urlparse(url).hostname or "").lower()
    try:
        html = _guarded_get(url, allowed_hosts=[host] if host else [])
    except SandboxHttpError as e:
        return f"Error fetching URL: {str(e)}"
    text = _extract_text(html)
    # Limit to ~4000 chars to avoid overloading LLM context
    if len(text) > 4000:
        text = text[:4000] + "... [TRUNCATED]"
    return text

def search_duckduckgo(query: str) -> str:
    # DuckDuckGo Lite HTML version — fixed host, fetched via GET through the
    # guard (the guard's whitelist is the DDG host).
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://{_DDG_HOST}/lite/?q={encoded_query}"
    try:
        html = _guarded_get(url, allowed_hosts=[_DDG_HOST])
    except SandboxHttpError as e:
        return f"Error searching: {str(e)}"
    # Very basic extraction: DDG lite has result snippets
    text = _extract_text(html)
    # Find where results start
    if "Web Results" in text:
        text = text[text.find("Web Results"):]
    if len(text) > 4000:
        text = text[:4000] + "... [TRUNCATED]"
    return text

def main():
    parser = argparse.ArgumentParser(description="Web Surfer Agent Tool")
    parser.add_argument("--url", type=str, help="Fetch and extract text from a specific URL")
    parser.add_argument("--search", type=str, help="Search the web and return snippets")
    
    args = parser.parse_args()
    
    result = {}
    if args.url:
        result["url"] = args.url
        result["content"] = fetch_url(args.url)
    elif args.search:
        result["query"] = args.search
        result["results"] = search_duckduckgo(args.search)
    else:
        result["error"] = "Must provide --url or --search"
        
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
