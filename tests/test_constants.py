"""Tests for shared constants and utilities."""

from unhook.constants import (
    BSKY_EMBED_RECORD_VIEW_BLOCKED,
    BSKY_EMBED_RECORD_VIEW_DETACHED,
    BSKY_EMBED_RECORD_VIEW_NOT_FOUND,
    BSKY_LINK_FACET,
    BSKY_POST_TYPE,
    BSKY_REASON_REPOST,
    BSKY_REPOST_TYPE,
    get_type_field,
)


class TestGetTypeField:
    """Tests for the get_type_field utility function."""

    def test_returns_dollar_type_field(self):
        """It returns the $type field when present."""
        obj = {"$type": "app.bsky.feed.post"}
        assert get_type_field(obj) == "app.bsky.feed.post"

    def test_returns_py_type_field(self):
        """It returns the py_type field when $type is absent."""
        obj = {"py_type": "app.bsky.feed.defs#reasonRepost"}
        assert get_type_field(obj) == "app.bsky.feed.defs#reasonRepost"

    def test_prefers_dollar_type_over_py_type(self):
        """It prefers $type over py_type when both are present."""
        obj = {"$type": "dollar", "py_type": "py"}
        assert get_type_field(obj) == "dollar"

    def test_returns_empty_string_when_no_type_field(self):
        """It returns empty string when neither type field is present."""
        obj = {"author": "test"}
        assert get_type_field(obj) == ""

    def test_returns_empty_string_for_empty_dict(self):
        """It returns empty string for empty dict."""
        assert get_type_field({}) == ""

    def test_returns_empty_string_for_non_dict(self):
        """It returns empty string for non-dict inputs."""
        assert get_type_field(None) == ""  # type: ignore[arg-type]
        assert get_type_field([]) == ""  # type: ignore[arg-type]
        assert get_type_field("string") == ""  # type: ignore[arg-type]
        assert get_type_field(123) == ""  # type: ignore[arg-type]

    def test_handles_empty_string_type_field(self):
        """It treats empty string $type as falsy and falls back to py_type."""
        obj = {"$type": "", "py_type": "fallback"}
        assert get_type_field(obj) == "fallback"

    def test_handles_none_type_field(self):
        """It treats None $type as falsy and falls back to py_type."""
        obj = {"$type": None, "py_type": "fallback"}
        assert get_type_field(obj) == "fallback"


class TestConstants:
    """Tests that constants have expected values."""

    def test_bluesky_type_constants_are_strings(self):
        """All Bluesky type constants should be non-empty strings."""
        constants = [
            BSKY_POST_TYPE,
            BSKY_REPOST_TYPE,
            BSKY_REASON_REPOST,
            BSKY_LINK_FACET,
            BSKY_EMBED_RECORD_VIEW_BLOCKED,
            BSKY_EMBED_RECORD_VIEW_NOT_FOUND,
            BSKY_EMBED_RECORD_VIEW_DETACHED,
        ]
        for const in constants:
            assert isinstance(const, str)
            assert len(const) > 0

    def test_embed_view_constants_are_distinct(self):
        """Embed view type constants should all be different."""
        embed_views = {
            BSKY_EMBED_RECORD_VIEW_BLOCKED,
            BSKY_EMBED_RECORD_VIEW_NOT_FOUND,
            BSKY_EMBED_RECORD_VIEW_DETACHED,
        }
        assert len(embed_views) == 3
