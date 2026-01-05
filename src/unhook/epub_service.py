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

from unhook.constants import BSKY_REASON_REPOST, BSKY_REPOST_TYPE, get_type_field
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
    repost_min_length: int = 300,
) -> Path:
    """Fetch posts, download assets, and build an EPUB file."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_posts = fetch_feed_posts(limit=limit)

    # Split into native posts and reposts
    native_posts = [p for p in all_posts if not _is_repost(p)]
    reposts = [p for p in all_posts if _is_repost(p)]

    # Process native posts: filter top-level and find threads
    top_level_native = _filter_top_level_posts(native_posts)
    native_threads = find_self_threads(native_posts)
    consolidated_native = consolidate_threads_to_posts(native_threads)
    native_thread_roots = {
        thread[0].get("post", {}).get("uri") for thread in native_threads
    }

    merged_native = [
        post
        for post in top_level_native
        if post.get("post", {}).get("uri") not in native_thread_roots
    ]
    merged_native.extend(consolidated_native)

    # Process reposts: find threads among reposted content
    repost_threads = find_self_threads(reposts)
    consolidated_reposts = consolidate_threads_to_posts(repost_threads)
    repost_thread_roots = {
        thread[0].get("post", {}).get("uri") for thread in repost_threads
    }

    # Get standalone reposts (not part of threads) - only top-level posts
    standalone_reposts = [
        post
        for post in reposts
        if post.get("post", {}).get("uri") not in repost_thread_roots
        and post.get("post", {}).get("record", {}).get("reply") is None
    ]

    # Build repost info mapping (URI -> reposter handle)
    repost_info = _build_repost_info(reposts)

    # Convert to content
    native_content = _filter_by_length(
        map_posts_to_content(dedupe_posts(merged_native)), min_length=min_length
    )

    # For reposts (standalone + consolidated threads)
    all_repost_posts = standalone_reposts + consolidated_reposts
    repost_content = _filter_by_length(
        _map_reposts_to_content(dedupe_posts(all_repost_posts), repost_info),
        min_length=repost_min_length,
    )

    # Merge and sort by published date
    content_posts = native_content + repost_content
    content_posts = sorted(content_posts, key=lambda post: post.published, reverse=True)

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


def _is_repost(post: dict) -> bool:
    """Return ``True`` when a feed item is a repost/retweet equivalent."""

    reason = post.get("reason")
    if not isinstance(reason, dict):
        reason = {}

    reason_type = get_type_field(reason)
    if BSKY_REASON_REPOST in reason_type:
        return True

    record = post.get("post", {}).get("record", {})
    if not isinstance(record, dict):
        return False

    record_type = get_type_field(record)
    return record_type == BSKY_REPOST_TYPE


def _filter_by_length(
    posts: Iterable[PostContent], min_length: int
) -> list[PostContent]:
    """Return posts whose bodies are at least ``min_length`` characters long."""

    return [post for post in posts if len(post.body) >= min_length]


def _get_reposter_handle(post: dict) -> str | None:
    """Extract the handle of the user who reposted this content."""

    reason = post.get("reason")
    if not isinstance(reason, dict):
        return None

    by = reason.get("by")
    if not isinstance(by, dict):
        return None

    return by.get("handle") or by.get("did")


def _build_repost_info(reposts: list[dict]) -> dict[str, str]:
    """Build a mapping from post URI to reposter handle."""

    info: dict[str, str] = {}
    for post in reposts:
        uri = post.get("post", {}).get("uri")
        reposter = _get_reposter_handle(post)
        if uri and reposter:
            info[uri] = reposter
    return info


def _map_reposts_to_content(
    posts: Iterable[dict], repost_info: dict[str, str]
) -> list[PostContent]:
    """Convert repost feed responses into PostContent with reposted_by set."""

    content_list = map_posts_to_content(posts)

    # Match content back to repost info using URI patterns
    posts_list = list(posts)
    for idx, content in enumerate(content_list):
        if idx < len(posts_list):
            post = posts_list[idx]
            uri = post.get("post", {}).get("uri", "")
            # For consolidated threads, URI ends with #thread
            base_uri = uri.replace("#thread", "") if uri.endswith("#thread") else uri
            reposter = repost_info.get(uri) or repost_info.get(base_uri)
            if reposter:
                content.reposted_by = reposter

    return content_list
