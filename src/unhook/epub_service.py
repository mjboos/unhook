"""Service helpers for exporting feeds to EPUB."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from unhook.epub_builder import EpubBuilder
from unhook.feed import fetch_feed_posts, parse_timestamp
from unhook.post_content import PostContent, dedupe_posts, map_posts_to_content

logger = logging.getLogger(__name__)


async def _download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.content
    except Exception as exc:  # pragma: no cover - logging only
        logger.warning("Failed to download image %s: %s", url, exc)
        return None


async def download_images(urls: list[str]) -> dict[str, bytes]:
    """Download images concurrently and return mapping of URL to bytes."""

    results: dict[str, bytes] = {}
    async with httpx.AsyncClient() as client:
        for url in {u for u in urls if u}:
            content = await _download_image(client, url)
            if content:
                results[url] = content
    return results


async def export_recent_posts_to_epub(
    output_dir: Path | str,
    limit: int = 200,
    hours: int = 24,
    file_prefix: str = "posts",
    min_length: int = 100,
) -> Path:
    """Fetch recent posts, download assets, and build an EPUB file."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_posts = fetch_feed_posts(limit=limit, since_days=1)
    recent_posts = _filter_recent_posts(raw_posts, hours=hours)
    unique_posts = dedupe_posts(recent_posts)
    content_posts: list[PostContent] = _filter_by_length(
        map_posts_to_content(unique_posts), min_length=min_length
    )

    image_urls = [url for post in content_posts for url in post.image_urls]
    images = await download_images(image_urls) if image_urls else {}

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_path = output_dir / f"{file_prefix}-{timestamp}.epub"

    builder = EpubBuilder(title=f"Recent posts ({hours}h)")
    builder.build(content_posts, images, output_path)

    logger.info("EPUB created at %s", output_path)
    return output_path


__all__ = ["export_recent_posts_to_epub", "download_images"]


def _filter_recent_posts(posts: list[dict], hours: int) -> list[dict]:
    """Keep only posts created within the last ``hours`` relative to now."""

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    filtered: list[dict] = []

    for post in posts:
        created_at = post.get("post", {}).get("record", {}).get("created_at")
        if not created_at:
            continue

        parsed = parse_timestamp(created_at)
        if parsed >= cutoff:
            filtered.append(post)

    return filtered


def _filter_by_length(
    posts: Iterable[PostContent], min_length: int
) -> list[PostContent]:
    """Return posts whose bodies are at least ``min_length`` characters long."""

    return [post for post in posts if len(post.body) >= min_length]
