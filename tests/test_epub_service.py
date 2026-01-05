"""Tests for the EPUB export service."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from ebooklib import ITEM_DOCUMENT, epub
from PIL import Image

from unhook.epub_service import (
    _build_repost_info,
    _compress_image,
    _filter_by_length,
    _filter_top_level_posts,
    _get_reposter_handle,
    _is_repost,
    download_images,
    export_recent_posts_to_epub,
)
from unhook.post_content import PostContent


@pytest.mark.asyncio
async def test_download_images_handles_failures(monkeypatch):
    responses = {"https://good.com/a.png": b"abc", "https://bad.com/b.png": None}

    async def mock_download(client, url):
        return responses.get(url)

    monkeypatch.setattr("unhook.epub_service._download_image", mock_download)

    result = await download_images(list(responses.keys()))
    assert "https://good.com/a.png" in result
    assert "https://bad.com/b.png" not in result


@pytest.mark.asyncio
async def test_export_recent_posts_to_epub(tmp_path, monkeypatch):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sample_feed = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": "Post body", "created_at": now},
                "embed": {"images": [{"fullsize": "https://example.com/image.jpg"}]},
            }
        }
    ]

    monkeypatch.setattr(
        "unhook.epub_service.fetch_feed_posts",
        lambda limit=200, since_days=1: sample_feed,
    )
    monkeypatch.setattr(
        "unhook.epub_service.download_images",
        AsyncMock(return_value={"https://example.com/image.jpg": b"img"}),
    )

    output_path = await export_recent_posts_to_epub(tmp_path, file_prefix="test")

    assert Path(output_path).exists()
    assert Path(output_path).suffix == ".epub"


@pytest.mark.asyncio
async def test_export_recent_posts_to_epub_consolidates_self_thread(
    tmp_path, monkeypatch
):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    long_body = "Top level post " + "x" * 120
    reply_body = "Reply body " + "y" * 120

    sample_feed = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": long_body, "created_at": now},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/2",
                "author": {"handle": "user.bsky.social"},
                "record": {
                    "text": reply_body,
                    "created_at": now,
                    "reply": {
                        "root": {
                            "uri": "at://did:plc:test/app.bsky.feed.post/1",
                            "cid": "rootcid",
                        },
                        "parent": {
                            "uri": "at://did:plc:test/app.bsky.feed.post/1",
                            "cid": "rootcid",
                        },
                    },
                },
            }
        },
    ]

    monkeypatch.setattr(
        "unhook.epub_service.fetch_feed_posts",
        lambda limit=200, since_days=1: sample_feed,
    )
    monkeypatch.setattr(
        "unhook.epub_service.download_images", AsyncMock(return_value={})
    )

    output_path = await export_recent_posts_to_epub(tmp_path, file_prefix="test")

    book = epub.read_epub(output_path)
    html_docs = [
        item.get_content().decode() for item in book.get_items_of_type(ITEM_DOCUMENT)
    ]
    combined_html = "\n".join(html_docs)

    assert "Top level post" in combined_html
    assert "Reply body" in combined_html

    content_docs = [doc for doc in html_docs if "Top level post" in doc]
    assert len(content_docs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "type_field",
    ["$type", "py_type"],
    ids=["json-format", "model-dump-format"],
)
async def test_export_recent_posts_includes_reposts_with_attribution(
    tmp_path, monkeypatch, type_field
):
    """Test reposts are included with 'Reposted by' header when meeting min length."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Create a repost that's long enough (>300 chars default)
    long_repost_text = "This is a reposted post with substantial content. " * 10

    sample_feed = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": "Original content" * 10, "created_at": now},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/2",
                "author": {"handle": "original.author.bsky.social"},
                "record": {"text": long_repost_text, "created_at": now},
            },
            "reason": {
                type_field: "app.bsky.feed.defs#reasonRepost",
                "by": {"handle": "reposter.bsky.social"},
            },
        },
    ]

    monkeypatch.setattr(
        "unhook.epub_service.fetch_feed_posts",
        lambda limit=200, since_days=1: sample_feed,
    )
    monkeypatch.setattr(
        "unhook.epub_service.download_images", AsyncMock(return_value={})
    )

    output_path = await export_recent_posts_to_epub(
        tmp_path, file_prefix="test", min_length=0, repost_min_length=0
    )

    book = epub.read_epub(output_path)
    html_docs = [
        item.get_content().decode() for item in book.get_items_of_type(ITEM_DOCUMENT)
    ]
    combined_html = "\n".join(html_docs)

    assert "Original content" in combined_html
    assert "reposted post with substantial content" in combined_html
    assert "Reposted by @reposter.bsky.social" in combined_html
    assert "original.author.bsky.social" in combined_html


@pytest.mark.asyncio
async def test_export_recent_posts_filters_short_reposts(tmp_path, monkeypatch):
    """Test reposts below repost_min_length are excluded."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    short_repost = "Short repost"  # Less than 300 chars

    sample_feed = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": "Original content" * 10, "created_at": now},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/2",
                "author": {"handle": "other.bsky.social"},
                "record": {"text": short_repost, "created_at": now},
            },
            "reason": {
                "py_type": "app.bsky.feed.defs#reasonRepost",
                "by": {"handle": "reposter.bsky.social"},
            },
        },
    ]

    monkeypatch.setattr(
        "unhook.epub_service.fetch_feed_posts",
        lambda limit=200, since_days=1: sample_feed,
    )
    monkeypatch.setattr(
        "unhook.epub_service.download_images", AsyncMock(return_value={})
    )

    # Use default repost_min_length of 300
    output_path = await export_recent_posts_to_epub(
        tmp_path, file_prefix="test", min_length=0
    )

    book = epub.read_epub(output_path)
    html_docs = [
        item.get_content().decode() for item in book.get_items_of_type(ITEM_DOCUMENT)
    ]
    combined_html = "\n".join(html_docs)

    assert "Original content" in combined_html
    assert "Short repost" not in combined_html


@pytest.mark.asyncio
async def test_export_recent_posts_aggregates_repost_threads(tmp_path, monkeypatch):
    """Test that reposted threads are consolidated into a single post."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Thread root text + reply should combine to > 300 chars
    root_text = "This is the start of a thread from the original author. " * 5
    reply_text = "This is the continuation of the thread by the same author. " * 5

    sample_feed = [
        {
            "post": {
                "uri": "at://did:plc:original/app.bsky.feed.post/1",
                "author": {"handle": "original.author", "did": "did:plc:original"},
                "record": {"text": root_text, "created_at": now},
            },
            "reason": {
                "py_type": "app.bsky.feed.defs#reasonRepost",
                "by": {"handle": "reposter.bsky.social"},
            },
        },
        {
            "post": {
                "uri": "at://did:plc:original/app.bsky.feed.post/2",
                "author": {"handle": "original.author", "did": "did:plc:original"},
                "record": {
                    "text": reply_text,
                    "created_at": now,
                    "reply": {
                        "root": {"uri": "at://did:plc:original/app.bsky.feed.post/1"},
                        "parent": {"uri": "at://did:plc:original/app.bsky.feed.post/1"},
                    },
                },
            },
            "reason": {
                "py_type": "app.bsky.feed.defs#reasonRepost",
                "by": {"handle": "reposter.bsky.social"},
            },
        },
    ]

    monkeypatch.setattr(
        "unhook.epub_service.fetch_feed_posts",
        lambda limit=200, since_days=1: sample_feed,
    )
    monkeypatch.setattr(
        "unhook.epub_service.download_images", AsyncMock(return_value={})
    )

    output_path = await export_recent_posts_to_epub(
        tmp_path, file_prefix="test", min_length=0, repost_min_length=0
    )

    book = epub.read_epub(output_path)
    html_docs = [
        item.get_content().decode() for item in book.get_items_of_type(ITEM_DOCUMENT)
    ]
    combined_html = "\n".join(html_docs)

    # Both parts of the thread should be in the output
    assert "start of a thread" in combined_html
    assert "continuation of the thread" in combined_html
    # Should have repost attribution
    assert "Reposted by" in combined_html

    # Thread should be consolidated - count occurrences of the author
    # (should appear once per consolidated thread, not twice)
    author_count = combined_html.count("original.author")
    assert author_count == 1, f"Expected 1 author occurrence, found {author_count}"


# Tests for _compress_image helper


def _create_test_image(
    width: int, height: int, mode: str = "RGB", img_format: str = "JPEG"
) -> bytes:
    """Create a test image in memory and return its bytes."""
    image = Image.new(mode, (width, height), color="red")
    output = BytesIO()
    if img_format == "JPEG" and mode == "RGBA":
        image = image.convert("RGB")
    image.save(output, format=img_format)
    return output.getvalue()


def test_compress_image_resizes_large_jpeg():
    """It resizes JPEG images larger than MAX_IMAGE_DIMENSION."""
    large_image = _create_test_image(2000, 1500, "RGB", "JPEG")
    result = _compress_image(large_image, "image/jpeg")

    # Verify the result is smaller
    with Image.open(BytesIO(result)) as img:
        assert img.width <= 1200
        assert img.height <= 1200


def test_compress_image_preserves_small_jpeg():
    """It does not resize JPEG images smaller than MAX_IMAGE_DIMENSION."""
    small_image = _create_test_image(800, 600, "RGB", "JPEG")
    result = _compress_image(small_image, "image/jpeg")

    with Image.open(BytesIO(result)) as img:
        assert img.width == 800
        assert img.height == 600


def test_compress_image_handles_png_with_transparency():
    """It preserves PNG format for images with transparency."""
    # Create RGBA image (with alpha channel)
    rgba_image = _create_test_image(100, 100, "RGBA", "PNG")
    result = _compress_image(rgba_image, "image/png")

    with Image.open(BytesIO(result)) as img:
        assert img.format == "PNG"


def test_compress_image_converts_opaque_png_to_jpeg():
    """It converts opaque PNG images to JPEG for better compression."""
    rgb_png = _create_test_image(100, 100, "RGB", "PNG")
    result = _compress_image(rgb_png, "image/png")

    with Image.open(BytesIO(result)) as img:
        assert img.format == "JPEG"


def test_compress_image_handles_webp():
    """It preserves WebP format."""
    webp_image = _create_test_image(100, 100, "RGB", "WEBP")
    result = _compress_image(webp_image, "image/webp")

    with Image.open(BytesIO(result)) as img:
        assert img.format == "WEBP"


def test_compress_image_returns_original_on_invalid_data():
    """It returns original content when image cannot be processed."""
    invalid_data = b"not an image"
    result = _compress_image(invalid_data, "image/jpeg")
    assert result == invalid_data


def test_compress_image_uses_format_from_bytes_when_media_type_unknown():
    """It detects format from image bytes when media type is None."""
    jpeg_image = _create_test_image(100, 100, "RGB", "JPEG")
    result = _compress_image(jpeg_image, None)

    with Image.open(BytesIO(result)) as img:
        assert img.format == "JPEG"


# Tests for _is_repost helper


class TestIsRepost:
    """Tests for _is_repost function."""

    def test_detects_repost_with_py_type_reason(self):
        """It detects reposts using py_type in reason."""
        post = {
            "post": {"uri": "at://test", "record": {}},
            "reason": {"py_type": "app.bsky.feed.defs#reasonRepost"},
        }
        assert _is_repost(post) is True

    def test_detects_repost_with_dollar_type_reason(self):
        """It detects reposts using $type in reason."""
        post = {
            "post": {"uri": "at://test", "record": {}},
            "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
        }
        assert _is_repost(post) is True

    def test_detects_repost_from_record_type(self):
        """It detects reposts from record $type field."""
        post = {
            "post": {
                "uri": "at://test",
                "record": {"$type": "app.bsky.feed.repost"},
            }
        }
        assert _is_repost(post) is True

    def test_returns_false_for_normal_post(self):
        """It returns False for non-repost posts."""
        post = {
            "post": {
                "uri": "at://test",
                "record": {"$type": "app.bsky.feed.post", "text": "Hello"},
            }
        }
        assert _is_repost(post) is False

    def test_handles_missing_reason(self):
        """It handles posts without a reason field."""
        post = {"post": {"uri": "at://test", "record": {"text": "Hello"}}}
        assert _is_repost(post) is False

    def test_handles_non_dict_reason(self):
        """It handles non-dict reason values."""
        post = {"post": {"uri": "at://test", "record": {}}, "reason": "not a dict"}
        assert _is_repost(post) is False

    def test_handles_non_dict_record(self):
        """It handles non-dict record values."""
        post = {"post": {"uri": "at://test", "record": "not a dict"}}
        assert _is_repost(post) is False


# Tests for _filter_by_length helper


class TestFilterByLength:
    """Tests for _filter_by_length function."""

    def test_filters_short_posts(self):
        """It excludes posts below the minimum length."""
        posts = [
            PostContent("Title", "author", datetime.now(UTC), "Short", []),
            PostContent("Title", "author", datetime.now(UTC), "A" * 100, []),
            PostContent("Title", "author", datetime.now(UTC), "B" * 50, []),
        ]
        result = _filter_by_length(posts, min_length=100)
        assert len(result) == 1
        assert result[0].body == "A" * 100

    def test_includes_posts_exactly_at_min_length(self):
        """It includes posts exactly at the minimum length."""
        posts = [
            PostContent("Title", "author", datetime.now(UTC), "A" * 50, []),
        ]
        result = _filter_by_length(posts, min_length=50)
        assert len(result) == 1

    def test_returns_empty_list_when_all_filtered(self):
        """It returns empty list when all posts are too short."""
        posts = [
            PostContent("Title", "author", datetime.now(UTC), "Short", []),
        ]
        result = _filter_by_length(posts, min_length=1000)
        assert result == []

    def test_handles_empty_input(self):
        """It handles empty input list."""
        result = _filter_by_length([], min_length=100)
        assert result == []


# Tests for _get_reposter_handle helper


class TestGetReposterHandle:
    """Tests for _get_reposter_handle function."""

    def test_extracts_handle_from_reason_by(self):
        """It extracts the reposter handle from reason.by."""
        post = {
            "reason": {"by": {"handle": "reposter.bsky.social"}},
            "post": {"uri": "at://test"},
        }
        assert _get_reposter_handle(post) == "reposter.bsky.social"

    def test_extracts_did_when_handle_missing(self):
        """It falls back to DID when handle is missing."""
        post = {
            "reason": {"by": {"did": "did:plc:reposter123"}},
            "post": {"uri": "at://test"},
        }
        assert _get_reposter_handle(post) == "did:plc:reposter123"

    def test_returns_none_when_no_reason(self):
        """It returns None when reason is missing."""
        post = {"post": {"uri": "at://test"}}
        assert _get_reposter_handle(post) is None

    def test_returns_none_when_reason_not_dict(self):
        """It returns None when reason is not a dict."""
        post = {"reason": "not a dict", "post": {"uri": "at://test"}}
        assert _get_reposter_handle(post) is None

    def test_returns_none_when_by_not_dict(self):
        """It returns None when reason.by is not a dict."""
        post = {"reason": {"by": "not a dict"}, "post": {"uri": "at://test"}}
        assert _get_reposter_handle(post) is None

    def test_returns_none_when_by_has_no_identifier(self):
        """It returns None when reason.by has neither handle nor did."""
        post = {"reason": {"by": {}}, "post": {"uri": "at://test"}}
        assert _get_reposter_handle(post) is None


# Tests for _build_repost_info helper


class TestBuildRepostInfo:
    """Tests for _build_repost_info function."""

    def test_builds_uri_to_reposter_mapping(self):
        """It builds a mapping from post URI to reposter handle."""
        reposts = [
            {
                "post": {"uri": "at://uri1"},
                "reason": {"by": {"handle": "reposter1.bsky.social"}},
            },
            {
                "post": {"uri": "at://uri2"},
                "reason": {"by": {"handle": "reposter2.bsky.social"}},
            },
        ]
        result = _build_repost_info(reposts)
        assert result == {
            "at://uri1": "reposter1.bsky.social",
            "at://uri2": "reposter2.bsky.social",
        }

    def test_skips_posts_without_uri(self):
        """It skips posts without a URI."""
        reposts = [
            {"post": {}, "reason": {"by": {"handle": "reposter.bsky.social"}}},
        ]
        result = _build_repost_info(reposts)
        assert result == {}

    def test_skips_posts_without_reposter(self):
        """It skips posts without a valid reposter."""
        reposts = [
            {"post": {"uri": "at://uri1"}, "reason": {}},
        ]
        result = _build_repost_info(reposts)
        assert result == {}

    def test_handles_empty_list(self):
        """It handles empty input list."""
        result = _build_repost_info([])
        assert result == {}


# Tests for _filter_top_level_posts helper


class TestFilterTopLevelPosts:
    """Tests for _filter_top_level_posts function."""

    def test_excludes_replies(self):
        """It excludes posts that are replies."""
        posts = [
            {"post": {"uri": "at://top", "record": {"text": "Top level"}}},
            {
                "post": {
                    "uri": "at://reply",
                    "record": {
                        "text": "Reply",
                        "reply": {"parent": {"uri": "at://other"}},
                    },
                }
            },
        ]
        result = _filter_top_level_posts(posts)
        assert len(result) == 1
        assert result[0]["post"]["uri"] == "at://top"

    def test_excludes_reposts(self):
        """It excludes reposts."""
        posts = [
            {"post": {"uri": "at://top", "record": {"text": "Top level"}}},
            {
                "post": {"uri": "at://repost", "record": {"text": "Reposted"}},
                "reason": {"py_type": "app.bsky.feed.defs#reasonRepost"},
            },
        ]
        result = _filter_top_level_posts(posts)
        assert len(result) == 1
        assert result[0]["post"]["uri"] == "at://top"

    def test_handles_empty_list(self):
        """It handles empty input list."""
        result = _filter_top_level_posts([])
        assert result == []

    def test_keeps_all_top_level_posts(self):
        """It keeps all top-level, non-repost posts."""
        posts = [
            {"post": {"uri": "at://a", "record": {"text": "A"}}},
            {"post": {"uri": "at://b", "record": {"text": "B"}}},
        ]
        result = _filter_top_level_posts(posts)
        assert len(result) == 2
