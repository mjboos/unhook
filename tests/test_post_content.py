"""Tests for post content helpers."""

from datetime import UTC, datetime

import numpy as np
import pytest

from unhook.post_content import (
    PostContent,
    dedupe_posts,
    map_posts_to_content,
    _apply_link_facets,
    _extract_image_urls,
    _extract_quote_content,
    _extract_record_view,
    _is_view_record,
)


def test_dedupe_posts_removes_duplicate_uris():
    """It removes duplicate posts based on URI while keeping order."""

    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "record": {"text": "First"},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "record": {"text": "Duplicate"},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/2",
                "record": {"text": "Second"},
            }
        },
    ]

    unique = dedupe_posts(posts)

    assert len(unique) == 2
    assert unique[0]["post"]["record"]["text"] == "First"
    assert unique[1]["post"]["record"]["text"] == "Second"


def test_map_posts_to_content_extracts_images():
    """It maps feed responses into PostContent objects with images."""

    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/123",
                "author": {"handle": "example.bsky.social"},
                "record": {"text": "Hello world", "created_at": now_str},
                "embed": {
                    "images": [
                        {"thumb": "https://example.com/thumb.jpg"},
                        {"fullsize": "https://example.com/full.jpg"},
                    ]
                },
            }
        }
    ]

    mapped = map_posts_to_content(posts)

    assert len(mapped) == 1
    content: PostContent = mapped[0]
    assert content.title == "Hello world"
    assert content.author == "example.bsky.social"
    assert content.image_urls == [
        "https://example.com/thumb.jpg",
        "https://example.com/full.jpg",
    ]
    assert content.body == "Hello world"


def test_map_posts_to_content_appends_quoted_text():
    """It includes quoted post content when present."""

    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/123",
                "author": {"handle": "quoting.bsky.social"},
                "record": {"text": "My thoughts", "created_at": now_str},
                "embed": {
                    "$type": "app.bsky.embed.record#view",
                    "record": {
                        "uri": "at://did:plc:test/app.bsky.feed.post/456",
                        "cid": "bafyreigdtest",
                        "author": {"handle": "original.bsky.social"},
                        "value": {
                            "$type": "app.bsky.feed.post",
                            "text": "Original quoted text",
                            "createdAt": now_str,
                        },
                    },
                },
            }
        }
    ]

    mapped = map_posts_to_content(posts)

    assert len(mapped) == 1
    content: PostContent = mapped[0]
    assert content.author == "quoting.bsky.social"
    assert content.body == (
        "My thoughts\n\nQuoted from original.bsky.social:\nOriginal quoted text"
    )
    assert content.title == "My thoughts"


def test_map_posts_to_content_replaces_short_links_with_facets():
    """It converts link facets into markdown links for EPUB output."""

    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = "Read more at https://t.co/abc and enjoy."
    link_text = "https://t.co/abc"
    start = text.index(link_text)
    end = start + len(link_text)
    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/999",
                "author": {"handle": "example.bsky.social"},
                "record": {
                    "text": text,
                    "created_at": now_str,
                    "facets": [
                        {
                            "index": {"byteStart": start, "byteEnd": end},
                            "features": [
                                {
                                    "$type": "app.bsky.richtext.facet#link",
                                    "uri": "https://example.com/full",
                                }
                            ],
                        }
                    ],
                },
            }
        }
    ]

    mapped = map_posts_to_content(posts)

    assert len(mapped) == 1
    assert mapped[0].body == "Read more at [link1](https://example.com/full) and enjoy."


def test_map_posts_to_content_handles_numpy_image_arrays():
    """It tolerates numpy arrays when parsing embed images."""

    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/abc",
                "author": {"handle": "example.bsky.social"},
                "record": {"text": "Images here", "created_at": now_str},
                "embed": {
                    "images": np.array(
                        [
                            {"fullsize": "https://example.com/full.jpg"},
                            {"thumb": "https://example.com/thumb.jpg"},
                        ],
                        dtype=object,
                    )
                },
            }
        }
    ]

    mapped = map_posts_to_content(posts)

    assert mapped[0].image_urls == [
        "https://example.com/full.jpg",
        "https://example.com/thumb.jpg",
    ]


def test_map_posts_to_content_numbers_multiple_links():
    """It numbers multiple links in order of appearance."""

    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = "Check https://t.co/first then https://t.co/second."
    first = "https://t.co/first"
    second = "https://t.co/second"
    first_start = text.index(first)
    first_end = first_start + len(first)
    second_start = text.index(second)
    second_end = second_start + len(second)
    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/links",
                "author": {"handle": "example.bsky.social"},
                "record": {
                    "text": text,
                    "created_at": now_str,
                    "facets": [
                        {
                            "index": {"byteStart": first_start, "byteEnd": first_end},
                            "features": [
                                {
                                    "$type": "app.bsky.richtext.facet#link",
                                    "uri": "https://example.com/first",
                                }
                            ],
                        },
                        {
                            "index": {
                                "byteStart": second_start,
                                "byteEnd": second_end,
                            },
                            "features": [
                                {
                                    "$type": "app.bsky.richtext.facet#link",
                                    "uri": "https://example.com/second",
                                }
                            ],
                        },
                    ],
                },
            }
        }
    ]

    mapped = map_posts_to_content(posts)

    assert (
        mapped[0].body == "Check [link1](https://example.com/first) then "
        "[link2](https://example.com/second)."
    )


def test_map_posts_to_content_handles_numpy_facets():
    """It coerces numpy-backed facet arrays and keys from parquet exports."""

    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = "Visit https://t.co/example for more."
    link_text = "https://t.co/example"
    start = text.index(link_text)
    end = start + len(link_text)
    posts = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/facets",
                "author": {"handle": "example.bsky.social"},
                "record": {
                    "text": text,
                    "created_at": now_str,
                    "facets": np.array(
                        [
                            {
                                "index": {
                                    "byte_start": np.int64(start),
                                    "byte_end": np.int64(end),
                                },
                                "features": np.array(
                                    [
                                        {
                                            "py_type": ("app.bsky.richtext.facet#link"),
                                            "uri": "https://example.com/full",
                                        }
                                    ],
                                    dtype=object,
                                ),
                            }
                        ],
                        dtype=object,
                    ),
                },
            }
        }
    ]

    mapped = map_posts_to_content(posts)

    assert mapped[0].body == "Visit [link1](https://example.com/full) for more."


# Tests for _apply_link_facets edge cases


class TestApplyLinkFacets:
    """Tests for _apply_link_facets function."""

    def test_returns_empty_string_for_empty_input(self):
        """It returns empty string for empty text input."""
        assert _apply_link_facets("", []) == ""

    def test_returns_original_text_for_empty_facets(self):
        """It returns original text when facets list is empty."""
        assert _apply_link_facets("Hello world", []) == "Hello world"

    def test_ignores_non_dict_facets(self):
        """It ignores facet entries that are not dicts."""
        text = "Hello world"
        facets = ["not a dict", None, 123]
        assert _apply_link_facets(text, facets) == "Hello world"

    def test_ignores_facets_without_index(self):
        """It ignores facets without an index field."""
        text = "Hello world"
        facets = [{"features": [{"$type": "app.bsky.richtext.facet#link", "uri": "http://example.com"}]}]
        assert _apply_link_facets(text, facets) == "Hello world"

    def test_ignores_facets_with_invalid_byte_range(self):
        """It ignores facets with out-of-bounds byte ranges."""
        text = "Hello"
        facets = [
            {
                "index": {"byteStart": -1, "byteEnd": 5},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "http://example.com"}],
            }
        ]
        assert _apply_link_facets(text, facets) == "Hello"

    def test_ignores_facets_with_start_after_end(self):
        """It ignores facets where byteStart >= byteEnd."""
        text = "Hello"
        facets = [
            {
                "index": {"byteStart": 5, "byteEnd": 3},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "http://example.com"}],
            }
        ]
        assert _apply_link_facets(text, facets) == "Hello"

    def test_ignores_facets_without_link_feature(self):
        """It ignores facets that don't have a link feature type."""
        text = "Hello"
        facets = [
            {
                "index": {"byteStart": 0, "byteEnd": 5},
                "features": [{"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:test"}],
            }
        ]
        assert _apply_link_facets(text, facets) == "Hello"

    def test_ignores_link_feature_without_uri(self):
        """It ignores link features without a URI string."""
        text = "Hello"
        facets = [
            {
                "index": {"byteStart": 0, "byteEnd": 5},
                "features": [{"$type": "app.bsky.richtext.facet#link"}],  # Missing uri
            }
        ]
        assert _apply_link_facets(text, facets) == "Hello"

    def test_handles_unicode_text_correctly(self):
        """It handles multi-byte Unicode characters correctly."""
        # Emoji takes multiple bytes in UTF-8
        text = "Check 🔗 out"
        # The emoji is at byte position 6, occupies 4 bytes
        start = 6  # after "Check "
        end = 10  # after the emoji
        facets = [
            {
                "index": {"byteStart": start, "byteEnd": end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "http://link.com"}],
            }
        ]
        result = _apply_link_facets(text, facets)
        assert "[link1](http://link.com)" in result


# Tests for _extract_image_urls edge cases


class TestExtractImageUrls:
    """Tests for _extract_image_urls function."""

    def test_returns_empty_list_for_no_embed(self):
        """It returns empty list when there's no embed."""
        assert _extract_image_urls({}) == []
        assert _extract_image_urls({"embed": None}) == []

    def test_returns_empty_list_for_non_dict_embed(self):
        """It returns empty list when embed is not a dict."""
        assert _extract_image_urls({"embed": "not a dict"}) == []

    def test_returns_empty_list_for_embed_without_images(self):
        """It returns empty list when embed has no images field."""
        assert _extract_image_urls({"embed": {"$type": "app.bsky.embed.external"}}) == []

    def test_skips_non_dict_image_entries(self):
        """It skips image entries that are not dicts."""
        post_data = {"embed": {"images": ["not a dict", None, {"fullsize": "http://img.com"}]}}
        result = _extract_image_urls(post_data)
        assert result == ["http://img.com"]

    def test_prefers_fullsize_over_thumb(self):
        """It prefers fullsize URL over thumb when both are present."""
        post_data = {
            "embed": {
                "images": [{"fullsize": "http://full.jpg", "thumb": "http://thumb.jpg"}]
            }
        }
        result = _extract_image_urls(post_data)
        assert result == ["http://full.jpg"]

    def test_falls_back_to_thumb(self):
        """It uses thumb URL when fullsize is not available."""
        post_data = {"embed": {"images": [{"thumb": "http://thumb.jpg"}]}}
        result = _extract_image_urls(post_data)
        assert result == ["http://thumb.jpg"]

    def test_skips_images_without_urls(self):
        """It skips images that have neither fullsize nor thumb."""
        post_data = {"embed": {"images": [{"alt": "description only"}]}}
        result = _extract_image_urls(post_data)
        assert result == []


# Tests for _extract_quote_content edge cases


class TestExtractQuoteContent:
    """Tests for _extract_quote_content function."""

    def test_returns_none_for_no_embed(self):
        """It returns None, None when there's no embed."""
        assert _extract_quote_content({}) == (None, None)
        assert _extract_quote_content({"embed": None}) == (None, None)

    def test_returns_none_for_non_dict_embed(self):
        """It returns None, None when embed is not a dict."""
        assert _extract_quote_content({"embed": "not a dict"}) == (None, None)

    def test_returns_none_for_blocked_record(self):
        """It returns None, None for blocked quoted records."""
        post_data = {
            "embed": {
                "record": {
                    "$type": "app.bsky.embed.record#viewBlocked",
                    "uri": "at://blocked/post",
                }
            }
        }
        assert _extract_quote_content(post_data) == (None, None)

    def test_returns_none_for_not_found_record(self):
        """It returns None, None for not found quoted records."""
        post_data = {
            "embed": {
                "record": {
                    "$type": "app.bsky.embed.record#viewNotFound",
                    "uri": "at://missing/post",
                }
            }
        }
        assert _extract_quote_content(post_data) == (None, None)

    def test_returns_none_for_detached_record(self):
        """It returns None, None for detached quoted records."""
        post_data = {
            "embed": {
                "record": {
                    "$type": "app.bsky.embed.record#viewDetached",
                    "uri": "at://detached/post",
                }
            }
        }
        assert _extract_quote_content(post_data) == (None, None)

    def test_extracts_author_handle_and_text(self):
        """It extracts author handle and text from valid quoted record."""
        post_data = {
            "embed": {
                "record": {
                    "author": {"handle": "quoted.author"},
                    "value": {"text": "Quoted text content"},
                }
            }
        }
        author, text = _extract_quote_content(post_data)
        assert author == "quoted.author"
        assert text == "Quoted text content"

    def test_falls_back_to_did_for_author(self):
        """It falls back to DID when handle is not available."""
        post_data = {
            "embed": {
                "record": {
                    "author": {"did": "did:plc:author123"},
                    "value": {"text": "Quoted text"},
                }
            }
        }
        author, text = _extract_quote_content(post_data)
        assert author == "did:plc:author123"
        assert text == "Quoted text"

    def test_returns_none_text_for_non_string_value_text(self):
        """It returns None for text when value.text is not a string."""
        post_data = {
            "embed": {
                "record": {
                    "author": {"handle": "author"},
                    "value": {"text": 123},  # Not a string
                }
            }
        }
        author, text = _extract_quote_content(post_data)
        assert author == "author"
        assert text is None


# Tests for _extract_record_view edge cases


class TestExtractRecordView:
    """Tests for _extract_record_view function."""

    def test_returns_none_for_no_record(self):
        """It returns None when there's no record field."""
        assert _extract_record_view({}) is None

    def test_returns_none_for_non_dict_record(self):
        """It returns None when record is not a dict."""
        assert _extract_record_view({"record": "not a dict"}) is None

    def test_returns_direct_record_if_valid_view(self):
        """It returns the record directly if it looks like a view record."""
        embed = {
            "record": {
                "author": {"handle": "test"},
                "value": {"text": "content"},
            }
        }
        result = _extract_record_view(embed)
        assert result["author"]["handle"] == "test"

    def test_returns_nested_record_if_valid_view(self):
        """It returns nested record.record if it looks like a view record."""
        embed = {
            "record": {
                "record": {
                    "author": {"handle": "nested"},
                    "value": {"text": "nested content"},
                }
            }
        }
        result = _extract_record_view(embed)
        assert result["author"]["handle"] == "nested"

    def test_returns_none_for_invalid_record_structure(self):
        """It returns None when record doesn't match view structure."""
        embed = {"record": {"uri": "at://some/uri", "cid": "somecid"}}
        assert _extract_record_view(embed) is None


# Tests for _is_view_record helper


class TestIsViewRecord:
    """Tests for _is_view_record function."""

    def test_returns_true_for_valid_view_record(self):
        """It returns True when record has author dict and value dict."""
        record = {"author": {"handle": "test"}, "value": {"text": "content"}}
        assert _is_view_record(record) is True

    def test_returns_false_when_author_not_dict(self):
        """It returns False when author is not a dict."""
        record = {"author": "not a dict", "value": {"text": "content"}}
        assert _is_view_record(record) is False

    def test_returns_false_when_value_not_dict(self):
        """It returns False when value is not a dict."""
        record = {"author": {"handle": "test"}, "value": "not a dict"}
        assert _is_view_record(record) is False

    def test_returns_false_when_author_missing(self):
        """It returns False when author is missing."""
        record = {"value": {"text": "content"}}
        assert _is_view_record(record) is False

    def test_returns_false_when_value_missing(self):
        """It returns False when value is missing."""
        record = {"author": {"handle": "test"}}
        assert _is_view_record(record) is False


# Tests for dedupe_posts edge cases


class TestDedupePostsEdgeCases:
    """Additional edge case tests for dedupe_posts."""

    def test_handles_posts_without_uri(self):
        """It handles posts that don't have a URI field."""
        posts = [
            {"post": {"record": {"text": "No URI"}}},
            {"post": {"uri": "at://valid", "record": {"text": "Has URI"}}},
        ]
        result = dedupe_posts(posts)
        # Only the post with URI should be included
        assert len(result) == 1
        assert result[0]["post"]["uri"] == "at://valid"

    def test_handles_empty_list(self):
        """It handles empty input list."""
        assert dedupe_posts([]) == []

    def test_preserves_order_after_deduplication(self):
        """It preserves original order after removing duplicates."""
        posts = [
            {"post": {"uri": "at://1", "record": {"text": "First"}}},
            {"post": {"uri": "at://2", "record": {"text": "Second"}}},
            {"post": {"uri": "at://1", "record": {"text": "Duplicate of First"}}},
            {"post": {"uri": "at://3", "record": {"text": "Third"}}},
        ]
        result = dedupe_posts(posts)
        assert len(result) == 3
        assert [p["post"]["uri"] for p in result] == ["at://1", "at://2", "at://3"]


# Tests for map_posts_to_content edge cases


class TestMapPostsToContentEdgeCases:
    """Additional edge case tests for map_posts_to_content."""

    def test_handles_empty_text(self):
        """It handles posts with empty text."""
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        posts = [
            {
                "post": {
                    "uri": "at://test",
                    "author": {"handle": "author"},
                    "record": {"text": "", "created_at": now_str},
                }
            }
        ]
        result = map_posts_to_content(posts)
        assert result[0].title == "Untitled"
        assert result[0].body == ""

    def test_handles_whitespace_only_text(self):
        """It handles posts with whitespace-only text."""
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        posts = [
            {
                "post": {
                    "uri": "at://test",
                    "author": {"handle": "author"},
                    "record": {"text": "   \n\t  ", "created_at": now_str},
                }
            }
        ]
        result = map_posts_to_content(posts)
        assert result[0].body == ""
        assert result[0].title == "Untitled"

    def test_handles_missing_author_handle(self):
        """It falls back to DID when author handle is missing."""
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        posts = [
            {
                "post": {
                    "uri": "at://test",
                    "author": {"did": "did:plc:test123"},
                    "record": {"text": "Hello", "created_at": now_str},
                }
            }
        ]
        result = map_posts_to_content(posts)
        assert result[0].author == "did:plc:test123"

    def test_handles_missing_created_at(self):
        """It uses current time when created_at is missing."""
        posts = [
            {
                "post": {
                    "uri": "at://test",
                    "author": {"handle": "author"},
                    "record": {"text": "Hello"},
                }
            }
        ]
        result = map_posts_to_content(posts)
        # Just verify it doesn't crash and has a datetime
        assert result[0].published is not None

    def test_truncates_long_titles(self):
        """It truncates titles to 60 characters."""
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        long_text = "A" * 100
        posts = [
            {
                "post": {
                    "uri": "at://test",
                    "author": {"handle": "author"},
                    "record": {"text": long_text, "created_at": now_str},
                }
            }
        ]
        result = map_posts_to_content(posts)
        assert len(result[0].title) == 60

    def test_uses_first_line_for_title(self):
        """It uses the first line of text for the title."""
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        posts = [
            {
                "post": {
                    "uri": "at://test",
                    "author": {"handle": "author"},
                    "record": {"text": "First line\nSecond line", "created_at": now_str},
                }
            }
        ]
        result = map_posts_to_content(posts)
        assert result[0].title == "First line"
