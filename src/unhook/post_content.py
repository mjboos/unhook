"""Helpers for working with feed post content."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from unhook.feed import parse_timestamp


@dataclass
class PostContent:
    """Representation of a feed post for EPUB creation."""

    title: str
    author: str
    published: datetime
    body: str
    image_urls: list[str]


def dedupe_posts(posts: Iterable[dict]) -> list[dict]:
    """Return posts with duplicate URIs removed while preserving order."""

    seen: set[str] = set()
    unique_posts: list[dict] = []

    for post in posts:
        uri = post.get("post", {}).get("uri")
        if uri and uri not in seen:
            seen.add(uri)
            unique_posts.append(post)

    return unique_posts


def map_posts_to_content(posts: Iterable[dict]) -> list[PostContent]:
    """Convert feed responses into :class:`PostContent` records."""

    mapped: list[PostContent] = []
    for raw in posts:
        post_data = raw.get("post", {})
        author_data = post_data.get("author", {})
        record = post_data.get("record", {})

        body = record.get("text", "").strip()
        created_at_str = record.get("created_at")
        published = (
            parse_timestamp(created_at_str) if created_at_str else datetime.now(UTC)
        )
        title = body.split("\n", 1)[0][:60] if body else "Untitled"
        image_urls = _extract_image_urls(post_data)

        mapped.append(
            PostContent(
                title=title or "Untitled",
                author=author_data.get("handle") or author_data.get("did", "unknown"),
                published=published,
                body=body,
                image_urls=image_urls,
            )
        )

    return mapped


def _extract_image_urls(post_data: dict) -> list[str]:
    """Extract image URLs from a feed post."""

    embed = post_data.get("embed") or {}
    if isinstance(embed, dict):
        images = embed.get("images") or []
        urls = []
        for image in images:
            if isinstance(image, dict):
                if image.get("fullsize"):
                    urls.append(image["fullsize"])
                elif image.get("thumb"):
                    urls.append(image["thumb"])
        return urls

    return []


__all__ = ["PostContent", "dedupe_posts", "map_posts_to_content"]
