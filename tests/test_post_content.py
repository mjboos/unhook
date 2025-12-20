"""Tests for post content helpers."""

from datetime import UTC, datetime

from unhook.post_content import PostContent, dedupe_posts, map_posts_to_content


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
