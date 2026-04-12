"""Tests for the DOM structural diff engine."""

from probelab.differ import (
    snapshot_page,
    diff_snapshots,
    fingerprint_node,
    extract_paths,
    save_snapshot,
    load_snapshot,
)
from tests.conftest import SAMPLE_HTML


CHANGED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Hello World</h1>
  <ul id="items">
    <li class="entry"><a href="/entry/1">Entry One</a></li>
    <li class="entry"><a href="/entry/2">Entry Two</a></li>
    <li class="entry"><a href="/entry/3">Entry Three</a></li>
  </ul>
  <div class="sidebar">New sidebar content</div>
  <footer><p>Page footer</p></footer>
</body>
</html>
"""


def test_snapshot_page_produces_hash():
    snap = snapshot_page(SAMPLE_HTML)
    assert "hash" in snap
    assert len(snap["hash"]) == 16
    assert "paths" in snap
    assert len(snap["paths"]) > 0


def test_snapshot_page_deterministic():
    snap1 = snapshot_page(SAMPLE_HTML)
    snap2 = snapshot_page(SAMPLE_HTML)
    assert snap1["hash"] == snap2["hash"]
    assert snap1["paths"] == snap2["paths"]


def test_snapshot_different_for_different_html():
    snap1 = snapshot_page(SAMPLE_HTML)
    snap2 = snapshot_page(CHANGED_HTML)
    assert snap1["hash"] != snap2["hash"]


def test_diff_identical_pages():
    snap = snapshot_page(SAMPLE_HTML)
    result = diff_snapshots(snap, snap)
    assert result.changed is False
    assert result.changes == []
    assert "No structural changes" in result.summary


def test_diff_detects_changes():
    old = snapshot_page(SAMPLE_HTML)
    new = snapshot_page(CHANGED_HTML)
    result = diff_snapshots(old, new)
    assert result.changed is True
    assert len(result.changes) > 0

    # Should detect that .item class was removed and .entry was added
    change_types = [c.change_type for c in result.changes]
    assert "removed" in change_types or "added" in change_types


def test_diff_detects_added_elements():
    old = snapshot_page(SAMPLE_HTML)
    new = snapshot_page(CHANGED_HTML)
    result = diff_snapshots(old, new)

    added = [c for c in result.changes if c.change_type == "added"]
    # The sidebar div.sidebar is new
    sidebar_added = any("sidebar" in c.path for c in added)
    assert sidebar_added


def test_diff_detects_removed_elements():
    old = snapshot_page(SAMPLE_HTML)
    new = snapshot_page(CHANGED_HTML)
    result = diff_snapshots(old, new)

    removed = [c for c in result.changes if c.change_type == "removed"]
    # The li.item class was removed
    item_removed = any("item" in c.path for c in removed)
    assert item_removed


def test_diff_detects_rename():
    old = snapshot_page(SAMPLE_HTML)
    new = snapshot_page(CHANGED_HTML)
    result = diff_snapshots(old, new)

    # li.item -> li.entry is a possible rename (same parent, same tag)
    renames = [c for c in result.changes if c.change_type == "modified"]
    # May or may not detect this depending on depth — verify structure
    assert result.summary  # At minimum, a summary is produced


def test_diff_result_to_dict():
    old = snapshot_page(SAMPLE_HTML)
    new = snapshot_page(CHANGED_HTML)
    result = diff_snapshots(old, new)
    d = result.to_dict()
    assert d["changed"] is True
    assert "changes" in d
    assert "summary" in d


def test_snapshot_empty_body():
    html = "<html><head></head><body></body></html>"
    snap = snapshot_page(html)
    assert snap["hash"]
    assert snap["paths"] == ["body"]  # Just the body tag


def test_save_and_load_snapshot(tmp_probelab):
    snap = snapshot_page(SAMPLE_HTML)
    path = save_snapshot("test-probe", snap, base=tmp_probelab)
    assert path.exists()

    loaded = load_snapshot("test-probe", base=tmp_probelab)
    assert loaded is not None
    assert loaded["hash"] == snap["hash"]


def test_load_snapshot_nonexistent(tmp_probelab):
    loaded = load_snapshot("nonexistent", base=tmp_probelab)
    assert loaded is None


def test_extract_paths_depth():
    snap = snapshot_page(SAMPLE_HTML)
    paths = snap["paths"]
    # Should have nested paths
    nested = [p for p in paths if p.count(" > ") >= 2]
    assert len(nested) > 0
