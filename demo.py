#!/usr/bin/env python3
"""
probelab end-to-end demo: detect, diagnose, repair.

Simulates a site redesign that breaks your selector, then shows probelab
catching the breakage, explaining what changed, and suggesting a fix.

Run:  python demo.py
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Two versions of the same "site": before and after a redesign
# ---------------------------------------------------------------------------

SITE_V1 = """<!DOCTYPE html>
<html>
<head><title>TechNews - Top Stories</title></head>
<body>
  <nav class="main-nav"><a href="/">Home</a></nav>
  <div id="content">
    <h1>Top Stories</h1>
    <ul class="story-list">
      <li class="story-item"><a class="story-link" href="/s/1">AI Agents Are Replacing Browser Extensions</a><span class="score">342 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/2">Rust Compiler Hits 4x Speed Improvement</a><span class="score">281 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/3">Why SQLite Is the Only Database You Need</a><span class="score">256 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/4">OpenCLI Reaches 15K GitHub Stars</a><span class="score">198 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/5">The End of Kubernetes? Docker Compose Strikes Back</a><span class="score">187 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/6">Python 3.14 Drops the GIL for Good</a><span class="score">176 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/7">New MCP Protocol Cuts Token Usage by 60%</a><span class="score">154 pts</span></li>
      <li class="story-item"><a class="story-link" href="/s/8">Building a Startup With Only AI Agents</a><span class="score">143 pts</span></li>
    </ul>
  </div>
  <footer class="site-footer"><p>&copy; 2026 TechNews</p></footer>
</body>
</html>"""

# After redesign: classes renamed, structure slightly changed
SITE_V2 = """<!DOCTYPE html>
<html>
<head><title>TechNews - Top Stories</title></head>
<body>
  <nav class="topnav"><a href="/">Home</a></nav>
  <main id="content">
    <h1>Top Stories</h1>
    <div class="feed">
      <article class="feed-entry"><a class="entry-title" href="/s/1">AI Agents Are Replacing Browser Extensions</a><span class="points">342 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/2">Rust Compiler Hits 4x Speed Improvement</a><span class="points">281 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/3">Why SQLite Is the Only Database You Need</a><span class="points">256 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/4">OpenCLI Reaches 15K GitHub Stars</a><span class="points">198 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/5">The End of Kubernetes? Docker Compose Strikes Back</a><span class="points">187 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/6">Python 3.14 Drops the GIL for Good</a><span class="points">176 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/7">New MCP Protocol Cuts Token Usage by 60%</a><span class="points">154 pts</span></article>
      <article class="feed-entry"><a class="entry-title" href="/s/8">Building a Startup With Only AI Agents</a><span class="points">143 pts</span></article>
    </div>
  </main>
  <footer class="site-footer"><p>&copy; 2026 TechNews</p></footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Tiny HTTP server that serves whichever version we tell it to
# ---------------------------------------------------------------------------

current_html = SITE_V1


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(current_html.encode())

    def log_message(self, *args):
        pass  # Silence server logs


def start_server(port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

def banner(text: str) -> None:
    width = 64
    print(flush=True)
    print("=" * width, flush=True)
    print(f"  {text}", flush=True)
    print("=" * width, flush=True)
    print(flush=True)


def step(n: int, text: str) -> None:
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    print(f"\n\033[1;36m--- Step {n}: {text} ---\033[0m\n", flush=True)


def run_probelab(*args: str) -> None:
    """Run probelab CLI in the demo working directory."""
    import subprocess
    import sys
    sys.stdout.flush()
    result = subprocess.run(
        [sys.executable, "-m", "probelab", *args],
        cwd=workdir,
    )
    sys.stdout.flush()
    return result.returncode


def main():
    global current_html, workdir

    port = 18932
    server = start_server(port)
    url = f"http://127.0.0.1:{port}"

    # Use a temp directory so we don't pollute the repo
    workdir = tempfile.mkdtemp(prefix="probelab-demo-")

    try:
        banner("probelab end-to-end demo: detect, diagnose, repair")

        print("A fake news site is running locally. Your scraper depends on")
        print(f"the CSS selector  li.story-item a.story-link  to extract headlines.")
        print(f"Site URL: {url}")

        # -- Step 1: Create the probe --
        step(1, "Create a probe for the news site")
        run_probelab(
            "init", "technews",
            "--url", url,
            "--select", "li.story-item a.story-link",
            "--expect-min", "5",
        )

        # -- Step 2: First check — everything healthy --
        step(2, "Run health check (site is normal)")
        run_probelab("check")

        # Run a few more times silently to build baseline history
        print("(Running 4 more checks to build baseline history...)", flush=True)
        import subprocess, sys
        for _ in range(4):
            subprocess.run(
                [sys.executable, "-m", "probelab", "check", "--format", "json"],
                cwd=workdir, stdout=subprocess.DEVNULL,
            )

        # -- Step 3: Show baseline --
        step(3, "View learned baseline")
        run_probelab("baseline", "technews")

        # -- Step 4: Site redesign happens --
        step(4, "SITE REDESIGN: classes and structure change overnight")
        current_html = SITE_V2
        time.sleep(0.1)

        print('The site renamed:')
        print('  li.story-item     ->  article.feed-entry')
        print('  a.story-link      ->  a.entry-title')
        print('  ul.story-list     ->  div.feed')
        print()
        print("Your selector  li.story-item a.story-link  now matches 0 elements.")
        print("But the site returns HTTP 200. No error in your logs.")
        print("Without probelab, you wouldn't know until users complain.")

        # -- Step 5: probelab catches it --
        step(5, "Run health check (probelab catches the breakage)")
        run_probelab("check", "--html", "report.html")
        print(f"\n  HTML report: {Path(workdir) / 'report.html'}")

        # -- Step 6: Inspect the diff --
        step(6, "Inspect DOM structural changes")
        run_probelab("diff", "technews")

        # -- Step 7: Check history --
        step(7, "Review probe history")
        run_probelab("history", "technews")

        # -- Step 8: Apply the repair --
        step(8, "Apply suggested repair: update the selector")
        print("probelab suggested alternative selectors. Let's update the probe:\n")

        # Read the current probe, update it
        import tomli_w
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        probe_path = Path(workdir) / ".probelab" / "probes" / "technews.toml"
        with open(probe_path, "rb") as f:
            data = tomllib.load(f)

        old_sel = data["probe"]["checks"][0]["selector"]
        new_sel = "article.feed-entry a.entry-title"
        data["probe"]["checks"][0]["selector"] = new_sel

        with open(probe_path, "wb") as f:
            tomli_w.dump(data, f)

        print(f'  Old selector: {old_sel}')
        print(f'  New selector: {new_sel}')

        # -- Step 9: Verify the fix --
        step(9, "Verify: run health check with updated selector")
        run_probelab("check")

        banner("Demo complete")
        print("The full loop:")
        print("  1. Define a web contract (probe)")
        print("  2. Site changes overnight")
        print("  3. probelab detects: BROKEN")
        print("  4. probelab diagnoses: DOM diff shows what changed")
        print("  5. probelab suggests: replacement selectors")
        print("  6. You update the probe -> HEALTHY again")
        print()
        print("This is what 'web contract monitoring' means.")
        print()

    finally:
        # Copy HTML report out before cleanup
        report_src = Path(workdir) / "report.html"
        if report_src.exists():
            report_dst = Path.cwd() / "demo-report.html"
            shutil.copy2(report_src, report_dst)
            print(f"  Report saved to: {report_dst}")

        server.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
