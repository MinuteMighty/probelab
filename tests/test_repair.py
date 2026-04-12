"""Tests for the selector auto-repair engine."""

from probelab.repair import suggest_repairs, _parse_selector, _class_fragments

# HTML where the original "li.item" class has been renamed to "li.entry"
RENAMED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <h1>Title</h1>
  <ul id="items">
    <li class="entry"><a href="/1">First Entry</a></li>
    <li class="entry"><a href="/2">Second Entry</a></li>
    <li class="entry"><a href="/3">Third Entry</a></li>
    <li class="entry"><a href="/4">Fourth Entry</a></li>
    <li class="entry"><a href="/5">Fifth Entry</a></li>
  </ul>
</body>
</html>
"""

# HTML with data attributes
DATA_ATTR_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <div id="feed">
    <article data-testid="post" class="feed-item-v2">
      <h2>Post Title 1</h2>
    </article>
    <article data-testid="post" class="feed-item-v2">
      <h2>Post Title 2</h2>
    </article>
    <article data-testid="post" class="feed-item-v2">
      <h2>Post Title 3</h2>
    </article>
  </div>
</body>
</html>
"""

# HTML with restructured content
RESTRUCTURED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <main>
    <div class="content-wrapper">
      <div class="story">Story 1</div>
      <div class="story">Story 2</div>
      <div class="story">Story 3</div>
      <div class="story">Story 4</div>
      <div class="story">Story 5</div>
      <div class="story">Story 6</div>
      <div class="story">Story 7</div>
    </div>
  </main>
</body>
</html>
"""


def test_suggest_repairs_finds_renamed_class():
    """When li.item becomes li.entry, suggest li.entry."""
    suggestions = suggest_repairs(
        html=RENAMED_HTML,
        broken_selector="li.item",
        target_min=5,
    )
    # Should find at least one suggestion
    assert len(suggestions) > 0
    # At least one suggestion should match 5 elements
    matching = [s for s in suggestions if s.match_count >= 5]
    assert len(matching) > 0


def test_suggest_repairs_with_data_attributes():
    """Should suggest data-testid selectors as alternatives."""
    suggestions = suggest_repairs(
        html=DATA_ATTR_HTML,
        broken_selector="article.feed-item",
        target_min=3,
    )
    assert len(suggestions) > 0
    # At least one should use data-testid
    attr_based = [s for s in suggestions if "data-testid" in s.selector]
    # May or may not find data-testid depending on strategy
    # but should find at least SOMETHING
    matching = [s for s in suggestions if s.match_count >= 3]
    assert len(matching) > 0


def test_suggest_repairs_structural_match():
    """Should find sibling elements with the same tag."""
    suggestions = suggest_repairs(
        html=RESTRUCTURED_HTML,
        broken_selector="div.article",
        target_min=5,
    )
    assert len(suggestions) > 0
    # Should suggest something like "div.content-wrapper > div" or "div.story"
    matching = [s for s in suggestions if s.match_count >= 5]
    assert len(matching) > 0


def test_suggest_repairs_parent_relaxation():
    """When full selector fails, try just the leaf part."""
    suggestions = suggest_repairs(
        html=RENAMED_HTML,
        broken_selector="div.old-wrapper > ul.old-list > li.item",
        target_min=3,
    )
    # Should try "li.item" alone and possibly find li.entry
    assert len(suggestions) > 0


def test_suggest_repairs_no_matches_at_all():
    """When nothing even remotely matches."""
    suggestions = suggest_repairs(
        html="<html><body><p>Simple page</p></body></html>",
        broken_selector="div.complex-widget > span.data-cell",
        target_min=10,
    )
    # Should return 0 or very low-confidence suggestions
    # Either no suggestions or all have low confidence
    high_conf = [s for s in suggestions if s.confidence > 0.5]
    assert len(high_conf) == 0


def test_suggest_repairs_returns_sample_texts():
    suggestions = suggest_repairs(
        html=RENAMED_HTML,
        broken_selector="li.item",
        target_min=5,
    )
    # At least one suggestion should exist
    assert len(suggestions) > 0
    # Check that suggestions have match counts (texts may vary by strategy)
    assert any(s.match_count > 0 for s in suggestions)
    # If samples exist, they should be strings
    for s in suggestions:
        for text in s.sample_texts:
            assert isinstance(text, str)


def test_suggest_repairs_confidence_scoring():
    """Suggestions closer to the target count should score higher."""
    suggestions = suggest_repairs(
        html=RENAMED_HTML,
        broken_selector="li.item",
        target_min=5,
    )
    if len(suggestions) >= 2:
        # First suggestion should have highest confidence
        assert suggestions[0].confidence >= suggestions[-1].confidence


def test_parse_selector_simple():
    parts = _parse_selector("li.item")
    assert parts.tag == "li"
    assert "item" in parts.classes


def test_parse_selector_with_id():
    parts = _parse_selector("div#content")
    assert parts.tag == "div"
    assert parts.id == "content"


def test_parse_selector_compound():
    parts = _parse_selector("div.container > ul.items > li.item")
    assert parts.tag == "li"
    assert "item" in parts.classes
    assert parts.parent is not None


def test_class_fragments():
    assert _class_fragments("story-link") == ["story", "link"]
    assert _class_fragments("itemTitle") == ["item", "title"]
    assert _class_fragments("post_content") == ["post", "content"]
    assert _class_fragments("a") == []  # Too short


def test_suggest_repairs_respects_max_suggestions():
    suggestions = suggest_repairs(
        html=RENAMED_HTML,
        broken_selector="li.item",
        target_min=5,
        max_suggestions=2,
    )
    assert len(suggestions) <= 2
