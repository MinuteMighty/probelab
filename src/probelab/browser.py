"""Browser-based page fetching using Playwright.

Supports two modes:
1. **CDP** — connect to the user's real Chrome (best: has cookies, bypasses anti-bot)
2. **Headless** — launch a fresh Chromium (fallback: no cookies, may be blocked)

Install with: ``pip install probelab[browser]``
"""

from __future__ import annotations

import time

# Default CDP endpoint (Chrome launched with --remote-debugging-port=9222)
DEFAULT_CDP_URL = "http://localhost:9222"


def check_cdp_available(cdp_url: str = DEFAULT_CDP_URL) -> bool:
    """Check if a Chrome instance is reachable via CDP."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1)
        return True
    except Exception:
        return False


def fetch_with_cdp(url: str, timeout: int = 30, cdp_url: str = DEFAULT_CDP_URL) -> tuple[str, int]:
    """Fetch a page using the user's real Chrome via CDP.

    Connects to an already-running Chrome. Uses the user's cookies,
    extensions, and browser fingerprint — indistinguishable from
    manual browsing.

    Start Chrome with:
        google-chrome --remote-debugging-port=9222

    Or on macOS:
        /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
    """
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()

            # Try to reuse an existing tab that's already on this domain
            # (already rendered, has full JS state)
            target_domain = urlparse(url).netloc
            existing_page = None
            for page in context.pages:
                if urlparse(page.url).netloc == target_domain:
                    existing_page = page
                    break

            start = time.monotonic()

            if existing_page:
                # Reuse existing tab — reload to get fresh content
                existing_page.reload(wait_until="domcontentloaded")
                existing_page.wait_for_timeout(2000)
                html = existing_page.content()
            else:
                # Open new tab
                page = context.new_page()
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                html = page.content()
                page.close()

            elapsed_ms = int((time.monotonic() - start) * 1000)
            return html, elapsed_ms
        finally:
            browser.close()


def fetch_with_browser(url: str, timeout: int = 15) -> tuple[str, int]:
    """Fetch a page using headless Chromium (fallback, no cookies)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            start = time.monotonic()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            html = page.content()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            return html, elapsed_ms
        finally:
            browser.close()


def fetch_page(url: str, timeout: int = 30, cdp_url: str | None = None) -> tuple[str, int]:
    """Fetch a page, trying CDP first, then headless.

    Args:
        url: The URL to navigate to.
        timeout: Navigation timeout in seconds.
        cdp_url: CDP endpoint. If None, auto-detects on default port.

    Returns:
        (html, elapsed_ms)
    """
    # Try CDP (user's real Chrome)
    endpoint = cdp_url or DEFAULT_CDP_URL
    if check_cdp_available(endpoint):
        return fetch_with_cdp(url, timeout=timeout, cdp_url=endpoint)

    # Fall back to headless
    return fetch_with_browser(url, timeout=timeout)
