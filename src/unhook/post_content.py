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
    reposted_by: str | None = None


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
        facets = record.get("facets")
        if not isinstance(facets, list) and hasattr(facets, "tolist"):
            facets = facets.tolist()
        if isinstance(facets, list):
            body = _apply_link_facets(body, facets)
        quote_author, quote_text = _extract_quote_content(post_data)
        if quote_text:
            label = quote_author or "quoted post"
            quoted_section = f"Quoted from {label}:\n{quote_text}"
            body = f"{body}\n\n{quoted_section}" if body else quoted_section

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
        images = embed.get("images")
        if images is None:
            images = []
        elif not isinstance(images, list):
            if hasattr(images, "tolist"):
                images = images.tolist()
            else:
                images = []
        urls = []
        for image in images:
            if isinstance(image, dict):
                if image.get("fullsize"):
                    urls.append(image["fullsize"])
                elif image.get("thumb"):
                    urls.append(image["thumb"])
        return urls

    return []


def _apply_link_facets(text: str, facets: list[dict]) -> str:
    """Replace text ranges with numbered markdown links based on facets."""

    if not text or not facets:
        return text

    byte_text = text.encode("utf-8")
    replacements: list[tuple[int, int, str]] = []

    def coerce_int(value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def normalize_list(value: object) -> list:
        if isinstance(value, list):
            return value
        if hasattr(value, "tolist"):
            normalized = value.tolist()
            return normalized if isinstance(normalized, list) else []
        return []

    for facet in facets:
        if not isinstance(facet, dict):
            continue
        index = facet.get("index")
        if not isinstance(index, dict):
            continue
        byte_start = coerce_int(index.get("byteStart") or index.get("byte_start"))
        byte_end = coerce_int(index.get("byteEnd") or index.get("byte_end"))
        if byte_start is None or byte_end is None:
            continue
        if byte_start < 0 or byte_end > len(byte_text) or byte_start >= byte_end:
            continue

        features = normalize_list(facet.get("features"))
        link_feature = next(
            (
                feature
                for feature in features
                if isinstance(feature, dict)
                and (feature.get("$type") or feature.get("py_type"))
                == "app.bsky.richtext.facet#link"
                and isinstance(feature.get("uri"), str)
            ),
            None,
        )
        if not link_feature:
            continue

        replacements.append((byte_start, byte_end, link_feature["uri"]))

    numbered: list[tuple[int, int, str, str]] = []
    for idx, (byte_start, byte_end, uri) in enumerate(sorted(replacements), start=1):
        numbered.append((byte_start, byte_end, uri, f"link{idx}"))

    for byte_start, byte_end, uri, label in sorted(numbered, reverse=True):
        replacement = f"[{label}]({uri})".encode()
        byte_text = byte_text[:byte_start] + replacement + byte_text[byte_end:]

    return byte_text.decode("utf-8", errors="replace")


def _extract_quote_content(post_data: dict) -> tuple[str | None, str | None]:
    """Return the author handle/DID and text of a quoted post, if present."""

    embed = post_data.get("embed") or {}
    if not isinstance(embed, dict):
        return None, None

    record_view = _extract_record_view(embed)

    if not isinstance(record_view, dict):
        return None, None

    if record_view.get("$type") in {
        "app.bsky.embed.record#viewBlocked",
        "app.bsky.embed.record#viewNotFound",
        "app.bsky.embed.record#viewDetached",
    }:
        return None, None

    author = (
        record_view.get("author") if isinstance(record_view.get("author"), dict) else {}
    )
    value = (
        record_view.get("value") if isinstance(record_view.get("value"), dict) else {}
    )

    author_identifier = author.get("handle") or author.get("did")
    quoted_text = value.get("text") if isinstance(value.get("text"), str) else None

    return author_identifier, quoted_text


def _extract_record_view(embed: dict) -> dict | None:
    """Return the nested record view for quoted posts."""

    record = embed.get("record")
    if not isinstance(record, dict):
        return None

    if _is_view_record(record):
        return record

    nested = record.get("record")
    if isinstance(nested, dict) and _is_view_record(nested):
        return nested

    return None


def _is_view_record(candidate: dict) -> bool:
    """Return whether the candidate looks like a quoted record view."""

    return isinstance(candidate.get("author"), dict) and isinstance(
        candidate.get("value"), dict
    )


__all__ = ["PostContent", "dedupe_posts", "map_posts_to_content"]
