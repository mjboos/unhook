"""Bluesky feed fetching functionality."""

import os
from datetime import UTC, date, datetime, timedelta

from atproto import Client
from dotenv import load_dotenv


def _get_author_identifier(post: dict) -> str | None:
    """Return a stable author identifier for a feed post."""

    author = post.get("post", {}).get("author", {})
    return author.get("did") or author.get("handle")


def _extract_reply_parent_uri(record: dict) -> str | None:
    """Extract the parent URI from a post record's reply field."""

    reply = record.get("reply") if isinstance(record, dict) else None
    if not isinstance(reply, dict):
        return None

    parent = reply.get("parent")
    if isinstance(parent, dict):
        if parent.get("uri"):
            return parent["uri"]
        ref = parent.get("ref")
        if isinstance(ref, dict) and ref.get("uri"):
            return ref["uri"]

    return None


def find_self_threads(posts: list[dict]) -> list[list[dict]]:
    """Group posts into author-consistent reply chains.

    A self thread is defined as a chain of two or more posts where each post
    replies directly to the previous one and every post shares the same author.
    Only posts present in ``posts`` are considered when constructing chains.
    """

    posts_by_uri: dict[str, dict] = {}
    parent_map: dict[str, str] = {}

    # First capture all posts by URI so we can evaluate author relationships.
    for post in posts:
        uri = post.get("post", {}).get("uri")
        if uri:
            posts_by_uri[uri] = post

    # Build parent mapping only when the parent exists locally and authors match.
    for post in posts:
        uri = post.get("post", {}).get("uri")
        record = post.get("post", {}).get("record", {})
        if not uri:
            continue

        parent_uri = _extract_reply_parent_uri(record)
        if not parent_uri:
            continue

        parent_post = posts_by_uri.get(parent_uri)
        if not parent_post:
            continue

        if _get_author_identifier(parent_post) != _get_author_identifier(post):
            continue

        parent_map[uri] = parent_uri

    threads: list[list[dict]] = []
    children = set(parent_map.keys())
    parents = set(parent_map.values())
    leaves = [uri for uri in children if uri not in parents]

    for leaf_uri in leaves:
        chain: list[dict] = []
        current_uri = leaf_uri

        while current_uri:
            post = posts_by_uri.get(current_uri)
            if not post:
                break

            chain.append(post)
            current_uri = parent_map.get(current_uri)

        if len(chain) > 1:
            chain.reverse()
            threads.append(chain)

    return threads


def consolidate_threads_to_posts(threads: list[list[dict]]) -> list[dict]:
    """Combine self threads into synthetic posts containing merged text and images."""

    consolidated: list[dict] = []

    for thread in threads:
        if not thread:
            continue

        root_post = thread[0].get("post", {})
        root_record = root_post.get("record", {})
        author = root_post.get("author", {})
        root_uri = root_post.get("uri") or ""
        root_cid = root_post.get("cid") or ""

        body_parts: list[str] = []
        images: list[dict] = []

        for entry in thread:
            post_data = entry.get("post", {})
            record = post_data.get("record", {})
            text = (record.get("text") or "").strip()
            if text:
                body_parts.append(text)

            embed = post_data.get("embed") or {}
            if isinstance(embed, dict):
                for image in embed.get("images") or []:
                    if isinstance(image, dict):
                        url = image.get("fullsize") or image.get("thumb")
                        if url:
                            images.append({"fullsize": url})

        consolidated.append(
            {
                "post": {
                    "uri": f"{root_uri}#thread",
                    "cid": f"{root_cid}-thread",
                    "author": author,
                    "record": {
                        "text": "\n\n".join(body_parts),
                        "created_at": root_record.get("created_at"),
                    },
                    "embed": {"images": images} if images else {},
                }
            }
        )

    return consolidated


def parse_timestamp(iso_string: str) -> datetime:
    """Parse ISO 8601 timestamp from Bluesky API.

    Args:
        iso_string: ISO 8601 formatted timestamp string
            (e.g., "2025-01-06T14:04:52.233Z")

    Returns:
        Timezone-aware datetime object in UTC
    """
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))


def fetch_feed_posts(
    limit: int = 100,
    since_days: int | None = 7,
    current_date: date | None = None,
    feed: str = "timeline",
) -> list[dict]:
    """
    Fetch the most recent posts from the authenticated user's Bluesky timeline.

    Args:
        limit: Maximum number of posts to fetch (default: 100)
        since_days: Only fetch posts from the last N days (default: 7).
                   Set to None to disable date filtering.
        current_date: Reference date for calculating the cutoff (default: None).
                     If None, uses today's date.
        feed: Which feed to request ("timeline" for home feed, "author" for only your
            posts).

    Returns:
        List of post dictionaries from the timeline

    Raises:
        ValueError: If required environment variables are missing
        Exception: If authentication or API request fails
    """
    # Load environment variables
    load_dotenv()

    handle = os.getenv("BLUESKY_HANDLE")
    password = os.getenv("BLUESKY_APP_PASSWORD")

    if not handle or not password:
        raise ValueError(
            "BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set in .env file"
        )

    # Calculate cutoff date if filtering is enabled
    if since_days is not None:
        reference_date = current_date if current_date is not None else date.today()
        # Convert date to datetime at start of day in UTC
        reference_datetime = datetime.combine(
            reference_date, datetime.min.time(), tzinfo=UTC
        )
        cutoff = reference_datetime - timedelta(days=since_days)
    else:
        cutoff = None

    if feed not in {"author", "timeline"}:
        raise ValueError('feed must be "author" or "timeline"')

    # Initialize client and authenticate
    client = Client()
    client.login(handle, password)

    all_posts: list[dict] = []
    cursor = None

    while len(all_posts) < limit:
        # Fetch a batch of posts (max 100 per request)
        batch_size = min(100, limit - len(all_posts))
        if feed == "timeline":
            response = client.get_timeline(limit=batch_size, cursor=cursor)
        else:
            response = client.get_author_feed(
                actor=handle, limit=batch_size, cursor=cursor
            )

        if not response.feed:
            break

        page_has_recent = False
        for item in response.feed:
            post_dict = item.model_dump()

            # Check if post is within date range
            if cutoff is not None:
                created_at_str = (
                    post_dict.get("post", {}).get("record", {}).get("created_at")
                )
                if created_at_str:
                    created_at = parse_timestamp(created_at_str)
                    if created_at < cutoff:
                        continue

            page_has_recent = True
            all_posts.append(post_dict)

            if len(all_posts) >= limit:
                break

        if cutoff is not None and not page_has_recent:
            break

        # Get cursor for next page
        cursor = response.cursor
        if not cursor:
            break

    return all_posts
