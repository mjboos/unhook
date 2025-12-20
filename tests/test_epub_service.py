"""Tests for the EPUB export service."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from ebooklib import ITEM_DOCUMENT, epub

from unhook.epub_service import download_images, export_recent_posts_to_epub


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
