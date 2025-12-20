"""Service helpers for exporting feeds to EPUB."""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Iterable
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from unhook.epub_builder import EpubBuilder
from unhook.feed import (
    consolidate_threads_to_posts,
    fetch_feed_posts,
    find_self_threads,
)
from unhook.post_content import PostContent, dedupe_posts, map_posts_to_content

logger = logging.getLogger(__name__)
MAX_IMAGE_DIMENSION = 1200
JPEG_QUALITY = 65


async def _download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.content
    except Exception as exc:  # pragma: no cover - logging only
        logger.warning("Failed to download image %s: %s", url, exc)
        return None


def _compress_image(content: bytes, media_type: str | None) -> bytes:
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))

            output = BytesIO()
            image_format = (image.format or "").upper()

            if media_type == "image/jpeg" or image_format in {"JPEG", "JPG"}:
                image.convert("RGB").save(
                    output, format="JPEG", quality=JPEG_QUALITY, optimize=True
                )
                return output.getvalue()

            if media_type == "image/png" or image_format == "PNG":
                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    image.save(output, format="PNG", optimize=True)
                else:
                    image.convert("RGB").save(
                        output, format="JPEG", quality=JPEG_QUALITY, optimize=True
                    )
                return output.getvalue()

            if media_type == "image/webp" or image_format == "WEBP":
                image.save(output, format="WEBP", quality=JPEG_QUALITY, method=6)
                return output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:  # pragma: no cover - logging only
        logger.warning("Failed to compress image: %s", exc)
    except Exception as exc:  # pragma: no cover - logging only
        logger.warning("Unexpected error compressing image: %s", exc)

    return content


async def download_images(urls: list[str]) -> dict[str, bytes]:
    """Download images concurrently and return mapping of URL to bytes."""

    results: dict[str, bytes] = {}
    async with httpx.AsyncClient() as client:
        for url in {u for u in urls if u}:
            content = await _download_image(client, url)
            if content:
                media_type, _ = mimetypes.guess_type(url)
                results[url] = _compress_image(content, media_type)
    return results


async def export_recent_posts_to_epub(
    output_dir: Path | str,
    limit: int = 200,
    file_prefix: str = "posts",
    min_length: int = 100,
) -> Path:
    """Fetch posts, download assets, and build an EPUB file."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_posts = _filter_reposts(fetch_feed_posts(limit=limit))
    top_level_posts = _filter_top_level_posts(raw_posts)

    threads = find_self_threads(raw_posts)
    consolidated_threads = consolidate_threads_to_posts(threads)
    root_thread_uris = {thread[0].get("post", {}).get("uri") for thread in threads}

    merged_posts = [
        post
        for post in top_level_posts
        if post.get("post", {}).get("uri") not in root_thread_uris
    ]
    merged_posts.extend(consolidated_threads)

    unique_posts = dedupe_posts(merged_posts)
    content_posts: list[PostContent] = _filter_by_length(
        map_posts_to_content(unique_posts), min_length=min_length
    )
    content_posts = sorted(content_posts, key=lambda post: post.published)

    image_urls = [url for post in content_posts for url in post.image_urls]
    images = await download_images(image_urls) if image_urls else {}

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_path = output_dir / f"{file_prefix}-{timestamp}.epub"

    builder = EpubBuilder(title="Recent posts")
    builder.build(content_posts, images, output_path)

    logger.info("EPUB created at %s", output_path)
    return output_path


__all__ = ["export_recent_posts_to_epub", "download_images"]


def _filter_top_level_posts(posts: Iterable[dict]) -> list[dict]:
    """Exclude reply posts and keep only top-level entries."""

    filtered: list[dict] = []

    for post in posts:
        record = post.get("post", {}).get("record", {})
        if _is_repost(post):
            continue
        if record.get("reply") is not None:
            continue

        filtered.append(post)

    return filtered


def _filter_reposts(posts: Iterable[dict]) -> list[dict]:
    """Return posts excluding entries that are pure reposts."""

    return [post for post in posts if not _is_repost(post)]


def _is_repost(post: dict) -> bool:
    """Return ``True`` when a feed item is a repost/retweet equivalent."""

    reason = post.get("reason")
    if not isinstance(reason, dict):
        reason = {}

    reason_type = reason.get("$type") or ""
    if "reasonRepost" in reason_type:
        return True

    record = post.get("post", {}).get("record", {})
    if not isinstance(record, dict):
        return False

    record_type = record.get("$type") or ""
    return record_type == "app.bsky.feed.repost"


def _filter_by_length(
    posts: Iterable[PostContent], min_length: int
) -> list[PostContent]:
    """Return posts whose bodies are at least ``min_length`` characters long."""

    return [post for post in posts if len(post.body) >= min_length]
