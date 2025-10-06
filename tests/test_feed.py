"""Test cases for the feed module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from unhook_tanha.feed import fetch_feed_posts


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv("BLUESKY_HANDLE", "test.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-password")


@pytest.fixture
def sample_timeline_response():
    """Sample timeline response data."""
    return MagicMock(
        feed=[
            MagicMock(
                model_dump=lambda: {
                    "post": {
                        "uri": "at://did:plc:test/app.bsky.feed.post/1",
                        "cid": "cid1",
                        "author": {
                            "did": "did:plc:test",
                            "handle": "test.bsky.social",
                        },
                        "record": {
                            "text": "Test post 1",
                            "createdAt": "2025-10-06T12:00:00Z",
                        },
                    }
                }
            ),
            MagicMock(
                model_dump=lambda: {
                    "post": {
                        "uri": "at://did:plc:test/app.bsky.feed.post/2",
                        "cid": "cid2",
                        "author": {
                            "did": "did:plc:test",
                            "handle": "test.bsky.social",
                        },
                        "record": {
                            "text": "Test post 2",
                            "createdAt": "2025-10-06T13:00:00Z",
                        },
                    }
                }
            ),
        ]
    )


def test_fetch_feed_posts_success(mock_env_vars, sample_timeline_response):
    """It fetches posts successfully with mocked client."""
    with patch("unhook_tanha.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = sample_timeline_response

        result = fetch_feed_posts(limit=100)

        mock_client.login.assert_called_once_with("test.bsky.social", "test-password")
        mock_client.get_timeline.assert_called_once_with(limit=100)
        assert len(result) == 2
        assert result[0]["post"]["record"]["text"] == "Test post 1"
        assert result[1]["post"]["record"]["text"] == "Test post 2"


def test_fetch_feed_posts_custom_limit(mock_env_vars, sample_timeline_response):
    """It passes custom limit parameter correctly."""
    with patch("unhook_tanha.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = sample_timeline_response

        fetch_feed_posts(limit=50)

        mock_client.get_timeline.assert_called_once_with(limit=50)


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
    with patch("unhook_tanha.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.login.side_effect = Exception("Authentication failed")

        with pytest.raises(Exception, match="Authentication failed"):
            fetch_feed_posts()


def test_fetch_feed_posts_api_error(mock_env_vars):
    """It raises exception on API error."""
    with patch("unhook_tanha.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            fetch_feed_posts()


@pytest.mark.integration
def test_fetch_feed_posts_integration():
    """Integration test - fetches real posts from Bluesky."""
    from dotenv import load_dotenv

    # Load environment variables from .env file
    load_dotenv()

    # Skip if credentials are not available
    if not os.getenv("BLUESKY_HANDLE") or not os.getenv("BLUESKY_APP_PASSWORD"):
        pytest.skip("Bluesky credentials not available")

    result = fetch_feed_posts(limit=10)

    assert isinstance(result, list)
    assert len(result) <= 10
    if len(result) > 0:
        # Verify basic structure of returned posts
        assert "post" in result[0]
        assert "uri" in result[0]["post"]
