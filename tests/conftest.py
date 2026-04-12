"""Shared test fixtures."""

import pytest


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Hello World</h1>
  <ul id="items">
    <li class="item"><a href="/item/1">Item One</a></li>
    <li class="item"><a href="/item/2">Item Two</a></li>
    <li class="item"><a href="/item/3">Item Three</a></li>
    <li class="item"><a href="/item/4">Item Four</a></li>
    <li class="item"><a href="/item/5">Item Five</a></li>
  </ul>
  <div class="empty-section"></div>
  <footer><p>Page footer</p></footer>
</body>
</html>
"""

EMPTY_HTML = """
<!DOCTYPE html>
<html>
<head><title>Empty</title></head>
<body><div id="content"></div></body>
</html>
"""

MALFORMED_HTML = """
<html>
<body>
  <div class="item">
    <span>Unclosed span
    <a href="/link">Link</a>
  </div>
  <div class="item">Second</div>
</body>
"""


@pytest.fixture
def sample_html():
    return SAMPLE_HTML


@pytest.fixture
def empty_html():
    return EMPTY_HTML


@pytest.fixture
def tmp_probelab(tmp_path):
    """Create a temporary .probelab directory for testing."""
    probelab_dir = tmp_path / ".probelab" / "probes"
    probelab_dir.mkdir(parents=True)
    (tmp_path / ".probelab" / "snapshots").mkdir()
    (tmp_path / ".probelab" / "history").mkdir()
    return tmp_path
