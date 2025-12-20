"""Tests for post content helpers."""

from datetime import UTC, datetime

import numpy as np

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
