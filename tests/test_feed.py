"""Test cases for the feed module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from unhook.feed import fetch_feed_posts, parse_timestamp


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv("BLUESKY_HANDLE", "test.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-password")


def make_post_mock(post_id: int, text: str, created_at: str):
    """Create a mock post object with the given data."""
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


def test_fetch_feed_posts_success(mock_env_vars, sample_timeline_response):
    """It fetches posts successfully with mocked client."""
    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = sample_timeline_response

        result = fetch_feed_posts(limit=100)

        mock_client.login.assert_called_once_with("test.bsky.social", "test-password")
        mock_client.get_timeline.assert_called_once_with(limit=100, cursor=None)
        assert len(result) == 2
        assert result[0]["post"]["record"]["text"] == "Test post 1"
        assert result[1]["post"]["record"]["text"] == "Test post 2"


def test_fetch_feed_posts_custom_limit(mock_env_vars, sample_timeline_response):
    """It passes custom limit parameter correctly."""
    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = sample_timeline_response

        fetch_feed_posts(limit=50)

        mock_client.get_timeline.assert_called_once_with(limit=50, cursor=None)


def test_fetch_feed_posts_missing_credentials(monkeypatch):
    """It raises ValueError when credentials are missing."""
    monkeypatch.setenv("BLUESKY_HANDLE", "")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "")

    with pytest.raises(
        ValueError,
        match="BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set in .env file",
    ):
        fetch_feed_posts()


def test_fetch_feed_posts_auth_failure(mock_env_vars):
    """It raises exception on authentication failure."""
    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.login.side_effect = Exception("Authentication failed")

        with pytest.raises(Exception, match="Authentication failed"):
            fetch_feed_posts()


def test_fetch_feed_posts_api_error(mock_env_vars):
    """It raises exception on API error."""
    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            fetch_feed_posts()


def test_parse_timestamp():
    """It parses ISO 8601 timestamps correctly."""
    # Test with Z suffix
    result = parse_timestamp("2025-10-06T12:00:00Z")
    assert result == datetime(2025, 10, 6, 12, 0, 0, tzinfo=UTC)

    # Test with microseconds
    result = parse_timestamp("2025-10-06T12:00:00.123456Z")
    assert result == datetime(2025, 10, 6, 12, 0, 0, 123456, tzinfo=UTC)

    # Test with explicit timezone offset
    result = parse_timestamp("2025-10-06T12:00:00+00:00")
    assert result == datetime(2025, 10, 6, 12, 0, 0, tzinfo=UTC)


def test_fetch_feed_posts_filters_old_posts(mock_env_vars):
    """It stops fetching when posts are older than since_days."""
    now = datetime.now(UTC)
    old_response = MagicMock(
        feed=[
            make_post_mock(
                1,
                "Recent post",
                (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            ),
            make_post_mock(
                2,
                "Old post",
                (now - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
            ),
        ],
        cursor=None,
    )

    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = old_response

        result = fetch_feed_posts(limit=100, since_days=7)

        # Should only return the recent post
        assert len(result) == 1
        assert result[0]["post"]["record"]["text"] == "Recent post"


def test_fetch_feed_posts_no_date_filter(mock_env_vars):
    """It fetches all posts when since_days is None."""
    now = datetime.now(UTC)
    old_response = MagicMock(
        feed=[
            make_post_mock(
                1,
                "Recent post",
                (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            ),
            make_post_mock(
                2,
                "Old post",
                (now - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            ),
        ],
        cursor=None,
    )

    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = old_response

        result = fetch_feed_posts(limit=100, since_days=None)

        # Should return both posts
        assert len(result) == 2


def test_fetch_feed_posts_pagination(mock_env_vars):
    """It follows pagination cursors to fetch more posts."""
    now = datetime.now(UTC)

    # First page response with cursor
    first_response = MagicMock(
        feed=[
            make_post_mock(
                1,
                "Post 1",
                (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            ),
        ],
        cursor="cursor_page_2",
    )

    # Second page response without cursor (last page)
    second_response = MagicMock(
        feed=[
            make_post_mock(
                2,
                "Post 2",
                (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            ),
        ],
        cursor=None,
    )

    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.side_effect = [first_response, second_response]

        result = fetch_feed_posts(limit=100, since_days=7)

        # Should return posts from both pages
        assert len(result) == 2
        assert mock_client.get_timeline.call_count == 2
