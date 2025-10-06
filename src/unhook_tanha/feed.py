"""Bluesky feed fetching functionality."""

import os

from atproto import Client
from dotenv import load_dotenv


def fetch_feed_posts(limit: int = 100) -> list[dict]:
    """
    Fetch the most recent posts from the authenticated user's Bluesky timeline.

    Args:
        limit: Maximum number of posts to fetch (default: 100)

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

    # Initialize client and authenticate
    client = Client()
    client.login(handle, password)

    # Fetch timeline using the convenience method
    response = client.get_timeline(limit=limit)

    # Extract feed items from response
    return [item.model_dump() for item in response.feed]
