"""Bluesky feed fetching functionality."""

import os
from datetime import date, datetime, timedelta, timezone

from atproto import Client
from dotenv import load_dotenv


def parse_timestamp(iso_string: str) -> datetime:
    """Parse ISO 8601 timestamp from Bluesky API.

    Args:
        iso_string: ISO 8601 formatted timestamp string (e.g., "2025-01-06T14:04:52.233Z")

    Returns:
        Timezone-aware datetime object in UTC
    """
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))


def fetch_feed_posts(
    limit: int = 100,
    since_days: int | None = 7,
    current_date: date | None = None,
) -> list[dict]:
    """
    Fetch the most recent posts from the authenticated user's Bluesky timeline.

    Args:
        limit: Maximum number of posts to fetch (default: 100)
        since_days: Only fetch posts from the last N days (default: 7).
                   Set to None to disable date filtering.
        current_date: Reference date for calculating the cutoff (default: None).
                     If None, uses today's date.

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
        reference_datetime = datetime.combine(reference_date, datetime.min.time(), tzinfo=timezone.utc)
        cutoff = reference_datetime - timedelta(days=since_days)
    else:
        cutoff = None

    # Initialize client and authenticate
    client = Client()
    client.login(handle, password)

    all_posts: list[dict] = []
    cursor = None

    while len(all_posts) < limit:
        # Fetch a batch of posts (max 100 per request)
        batch_size = min(100, limit - len(all_posts))
        response = client.get_timeline(limit=batch_size, cursor=cursor)

        if not response.feed:
            break

        for item in response.feed:
            post_dict = item.model_dump()

            # Check if post is within date range
            if cutoff is not None:
                created_at_str = post_dict.get("post", {}).get("record", {}).get("created_at")
                if created_at_str:
                    created_at = parse_timestamp(created_at_str)
                    if created_at < cutoff:
                        # Stop fetching - we've gone past the date limit
                        return all_posts

            all_posts.append(post_dict)

            if len(all_posts) >= limit:
                break

        # Get cursor for next page
        cursor = response.cursor
        if not cursor:
            break

    return all_posts
