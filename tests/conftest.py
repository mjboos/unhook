"""Shared pytest fixtures and helpers for unhook tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest


def make_post(
    uri: str,
    author: str,
    text: str,
    parent_uri: str | None = None,
    images: list[str] | None = None,
    created_at: str | None = None,
    reason: dict | None = None,
) -> dict:
    """Create a minimal post dictionary for testing.

    Args:
        uri: The post URI.
        author: The author DID.
        text: The post text content.
        parent_uri: Optional parent URI for reply threads.
        images: Optional list of image URLs.
        created_at: Optional ISO timestamp string (defaults to now).
        reason: Optional reason dict (e.g., for reposts).

    Returns:
        A post dictionary matching the Bluesky feed structure.
    """
    if created_at is None:
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    record: dict = {"text": text, "created_at": created_at}
    if parent_uri:
        record["reply"] = {"parent": {"uri": parent_uri}}

    embed = {"images": [{"fullsize": url} for url in images]} if images else {}

    # Extract a simple handle from the DID for testing
    handle_base = author.split(":")[-1] if ":" in author else author
    post = {
        "post": {
            "uri": uri,
            "cid": f"cid-{uri.split('/')[-1]}",
            "author": {"did": author, "handle": f"{handle_base}.bsky.social"},
            "record": record,
            "embed": embed,
        }
    }

    if reason:
        post["reason"] = reason

    return post


def make_post_mock(post_id: int, text: str, created_at: str) -> MagicMock:
    """Create a mock post object that returns a dict on model_dump().

    Args:
        post_id: Numeric post identifier.
        text: The post text content.
        created_at: ISO timestamp string.

    Returns:
        A MagicMock with a model_dump method.
    """
    return MagicMock(
        model_dump=lambda post_id=post_id, text=text, created_at=created_at: {
            "post": {
                "uri": f"at://did:plc:test/app.bsky.feed.post/{post_id}",
                "cid": f"cid{post_id}",
                "author": {
                    "did": "did:plc:test",
                    "handle": "test.bsky.social",
                },
                "record": {
                    "text": text,
                    "created_at": created_at,
                },
            }
        }
    )


def make_repost(
    uri: str,
    author: str,
    text: str,
    reposter_handle: str,
    created_at: str | None = None,
    type_field: str = "py_type",
) -> dict:
    """Create a repost dictionary for testing.

    Args:
        uri: The original post URI.
        author: The original author DID.
        text: The post text content.
        reposter_handle: The handle of the user who reposted.
        created_at: Optional ISO timestamp string.
        type_field: Field name for the type (py_type or $type).

    Returns:
        A repost dictionary matching the Bluesky feed structure.
    """
    post = make_post(uri, author, text, created_at=created_at)
    post["reason"] = {
        type_field: "app.bsky.feed.defs#reasonRepost",
        "by": {"handle": reposter_handle},
    }
    return post


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock Bluesky environment variables."""
    monkeypatch.setenv("BLUESKY_HANDLE", "test.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-password")


@pytest.fixture
def sample_timeline_response():
    """Sample timeline response data with recent posts."""
    now = datetime.now(UTC)
    return MagicMock(
        feed=[
            make_post_mock(
                1,
                "Test post 1",
                (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            ),
            make_post_mock(
                2,
                "Test post 2",
                (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            ),
        ],
        cursor=None,
    )


@pytest.fixture
def now_timestamp() -> str:
    """Return a current UTC timestamp in Bluesky format."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
