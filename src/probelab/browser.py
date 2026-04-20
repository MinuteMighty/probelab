"""Browser-based page fetching using Playwright.

Supports two modes:
1. **CDP** — connect to the user's real Chrome (best: has cookies, bypasses anti-bot)
2. **Headless** — launch a fresh Chromium (fallback: no cookies, may be blocked)

Install with: ``pip install probelab[browser]``
"""

from __future__ import annotations

import os
import platform
import subprocess
import time

# Default CDP endpoint (Chrome launched with --remote-debugging-port=9222)
DEFAULT_CDP_URL = "http://localhost:9222"
CDP_PORT = 9222


def check_cdp_available(cdp_url: str = DEFAULT_CDP_URL) -> bool:
    """Check if a Chrome instance is reachable via CDP."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2)
        return True
    except Exception:
        return False


def find_chrome_binary() -> str | None:
    """Find the Chrome/Chromium binary on this system."""
    system = platform.system()

    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]
    elif system == "Linux":
        candidates = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
        ]
    elif system == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = []

    for path in candidates:
        if os.path.isfile(path):
            return path
        # For Linux: check if it's in PATH
        if system == "Linux" and not path.startswith("/"):
            import shutil
            found = shutil.which(path)
            if found:
                return found

    return None


def ensure_chrome_cdp(cdp_url: str = DEFAULT_CDP_URL, quiet: bool = False) -> bool:
    """Ensure Chrome is running with CDP enabled. Launch it if not.

    Uses the user's real Chrome profile (existing cookies, logins, extensions).
    Returns True if CDP is available after this call.
    """
    # Already running?
    if check_cdp_available(cdp_url):
        return True

    chrome = find_chrome_binary()
    if not chrome:
        return False

    # Use the user's real profile directory
    system = platform.system()
    if system == "Darwin":
        user_data_dir = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    elif system == "Linux":
        user_data_dir = os.path.expanduser("~/.config/google-chrome")
    elif system == "Windows":
        user_data_dir = os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")
    else:
        user_data_dir = ""

    # Launch Chrome with debugging enabled
    cmd = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
    ]

    if user_data_dir and os.path.isdir(user_data_dir):
        cmd.append(f"--user-data-dir={user_data_dir}")

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False

    # Wait for CDP to become available (Chrome takes a moment to start)
    for _ in range(15):
        time.sleep(0.5)
        if check_cdp_available(cdp_url):
            return True

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


def fetch_page(url: str, timeout: int = 30, cdp_url: str | None = None, auto_launch: bool = True) -> tuple[str, int]:
    """Fetch a page, trying CDP first, then headless.

    Args:
        url: The URL to navigate to.
        timeout: Navigation timeout in seconds.
        cdp_url: CDP endpoint. If None, auto-detects on default port.
        auto_launch: If True, auto-launch Chrome with CDP if not running.

    Returns:
        (html, elapsed_ms)
    """
    endpoint = cdp_url or DEFAULT_CDP_URL

    # Try CDP (user's real Chrome with cookies)
    if check_cdp_available(endpoint):
        return fetch_with_cdp(url, timeout=timeout, cdp_url=endpoint)

    # Auto-launch Chrome with CDP if requested
    if auto_launch:
        if ensure_chrome_cdp(endpoint):
            return fetch_with_cdp(url, timeout=timeout, cdp_url=endpoint)

    # Fall back to headless (no cookies, may be blocked)
    return fetch_with_browser(url, timeout=timeout)
