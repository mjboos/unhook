"""Test cases for the feed module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Import shared helpers from conftest - pytest makes these available
from tests.conftest import make_post, make_post_mock
from unhook.feed import (
    consolidate_threads_to_posts,
    fetch_feed_posts,
    find_self_threads,
    parse_timestamp,
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


def test_fetch_feed_posts_author_feed(mock_env_vars, sample_timeline_response):
    """It can request the author feed explicitly."""
    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_author_feed.return_value = sample_timeline_response

        fetch_feed_posts(limit=25, feed="author")

        mock_client.get_author_feed.assert_called_once_with(
            actor="test.bsky.social",
            limit=25,
            cursor=None,
        )


def test_find_self_threads_simple_chain():
    """It groups replies from the same author into an ordered chain."""

    root = make_post("at://root", "did:author:1", "First")
    reply = make_post("at://reply", "did:author:1", "Second", parent_uri="at://root")

    threads = find_self_threads([root, reply])

    assert len(threads) == 1
    uris = [post["post"]["uri"] for post in threads[0]]
    assert uris == ["at://root", "at://reply"]

    consolidated = consolidate_threads_to_posts(threads)
    assert consolidated[0]["post"]["record"]["text"] == "First\n\nSecond"


def test_find_self_threads_handles_branches():
    """It produces separate chains when replies branch from the same root."""

    root = make_post("at://root", "did:author:1", "Start")
    mid = make_post("at://mid", "did:author:1", "Middle", parent_uri="at://root")
    tail = make_post("at://tail", "did:author:1", "Tail", parent_uri="at://mid")
    sibling = make_post(
        "at://sibling", "did:author:1", "Sibling", parent_uri="at://root"
    )

    threads = find_self_threads([root, mid, tail, sibling])
    assert len(threads) == 2

    thread_uris = {tuple(post["post"]["uri"] for post in thread) for thread in threads}
    assert {
        ("at://root", "at://mid", "at://tail"),
        ("at://root", "at://sibling"),
    } == thread_uris


def test_find_self_threads_ignores_mixed_authors():
    """It ignores replies from different authors when building chains."""

    root = make_post("at://root", "did:author:1", "First")
    foreign_reply = make_post(
        "at://foreign", "did:author:2", "Not mine", parent_uri="at://root"
    )

    threads = find_self_threads([root, foreign_reply])

    assert threads == []


def test_consolidate_threads_collects_images():
    """It carries over images from all posts in a thread."""

    root = make_post(
        "at://root", "did:author:1", "First", images=["https://example.com/1.jpg"]
    )
    reply = make_post(
        "at://reply",
        "did:author:1",
        "Second",
        parent_uri="at://root",
        images=["https://example.com/2.jpg"],
    )

    consolidated = consolidate_threads_to_posts([[root, reply]])
    images = consolidated[0]["post"].get("embed", {}).get("images", [])

    assert len(images) == 2
    assert {img["fullsize"] for img in images} == {
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
    }


def test_extract_reply_parent_uri_nested_ref():
    """It extracts parent URI from nested ref structure."""
    from unhook.feed import _extract_reply_parent_uri

    # When parent has no direct URI but has a ref with URI
    record = {"reply": {"parent": {"ref": {"uri": "at://ref-uri"}}}}
    assert _extract_reply_parent_uri(record) == "at://ref-uri"


def test_extract_reply_parent_uri_no_reply():
    """It returns None when record has no reply field."""
    from unhook.feed import _extract_reply_parent_uri

    assert _extract_reply_parent_uri({"text": "hello"}) is None
    assert _extract_reply_parent_uri("not a dict") is None


def test_find_self_threads_posts_without_uri():
    """It ignores posts that have no URI."""
    post_no_uri = {"post": {"author": {"did": "did:1"}, "record": {"text": "hi"}}}
    normal = make_post("at://normal", "did:1", "Normal post")
    threads = find_self_threads([post_no_uri, normal])
    assert threads == []


def test_fetch_feed_posts_invalid_feed(mock_env_vars):
    """It raises ValueError for invalid feed parameter."""
    with pytest.raises(ValueError, match='feed must be "author" or "timeline"'):
        fetch_feed_posts(feed="invalid")


def test_fetch_feed_posts_empty_response(mock_env_vars):
    """It returns empty list when API returns no feed items."""
    empty_response = MagicMock(feed=[], cursor=None)

    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = empty_response

        result = fetch_feed_posts(limit=100)

        assert result == []


def test_fetch_feed_posts_stops_when_all_posts_old(mock_env_vars):
    """It stops pagination when entire page is older than cutoff."""
    now = datetime.now(UTC)

    old_response = MagicMock(
        feed=[
            make_post_mock(
                1,
                "Very old post",
                (now - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            ),
        ],
        cursor="more_pages",
    )

    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = old_response

        result = fetch_feed_posts(limit=100, since_days=7)

        assert result == []
        # Should not follow cursor when all posts are old
        assert mock_client.get_timeline.call_count == 1


def test_fetch_feed_posts_respects_limit_mid_page(mock_env_vars):
    """It stops collecting when limit is reached mid-page."""
    now = datetime.now(UTC)
    ts = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    response = MagicMock(
        feed=[
            make_post_mock(1, "Post 1", ts),
            make_post_mock(2, "Post 2", ts),
            make_post_mock(3, "Post 3", ts),
        ],
        cursor="more",
    )

    with patch("unhook.feed.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_timeline.return_value = response

        result = fetch_feed_posts(limit=2, since_days=7)

        assert len(result) == 2
