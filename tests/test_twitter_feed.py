"""Tests for Twitter feed fetching via twikit."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from unhook.twitter_feed import (
    _parse_twitter_timestamp,
    fetch_twitter_posts,
    fetch_user_tweets,
    load_twitter_users,
    map_tweets_to_content,
)


class TestLoadTwitterUsers:
    def test_loads_users_from_file(self, tmp_path):
        config_file = tmp_path / "users.txt"
        config_file.write_text("user1\n@user2\nuser3\n")

        users = load_twitter_users(config_file)

        assert users == ["user1", "user2", "user3"]

    def test_strips_at_prefix(self, tmp_path):
        config_file = tmp_path / "users.txt"
        config_file.write_text("@testuser\n")

        users = load_twitter_users(config_file)

        assert users == ["testuser"]

    def test_ignores_comments(self, tmp_path):
        config_file = tmp_path / "users.txt"
        config_file.write_text("user1\n# This is a comment\nuser2\n")

        users = load_twitter_users(config_file)

        assert users == ["user1", "user2"]

    def test_ignores_empty_lines(self, tmp_path):
        config_file = tmp_path / "users.txt"
        config_file.write_text("user1\n\n\nuser2\n")

        users = load_twitter_users(config_file)

        assert users == ["user1", "user2"]

    def test_returns_empty_list_if_file_not_found(self, tmp_path):
        users = load_twitter_users(tmp_path / "nonexistent.txt")

        assert users == []


class TestParseTwitterTimestamp:
    def test_parses_twitter_format(self):
        date_str = "Mon Jan 15 10:30:00 +0000 2024"

        result = _parse_twitter_timestamp(date_str)

        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parses_iso_format(self):
        date_str = "2024-01-15T10:30:00Z"

        result = _parse_twitter_timestamp(date_str)

        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_returns_now_for_none(self):
        result = _parse_twitter_timestamp(None)

        assert result.tzinfo == UTC
        assert (datetime.now(UTC) - result).total_seconds() < 5

    def test_returns_now_for_invalid_format(self):
        result = _parse_twitter_timestamp("invalid date string")

        assert result.tzinfo == UTC
        assert (datetime.now(UTC) - result).total_seconds() < 5


class TestMapTweetsToContent:
    def test_converts_tweet_to_post_content(self):
        tweets = [
            {
                "text": "Hello world!",
                "created_at": "Mon Jan 15 10:30:00 +0000 2024",
                "author": "testuser",
                "images": [],
                "is_retweet": False,
                "retweet_author": None,
            }
        ]

        posts = map_tweets_to_content(tweets, since_days=None)

        assert len(posts) == 1
        assert posts[0].body == "Hello world!"
        assert posts[0].author == "@testuser"

    def test_filters_by_date(self):
        old_tweet = {
            "text": "Old content",
            "created_at": "Mon Jan 01 00:00:00 +0000 2020",
            "author": "testuser",
            "images": [],
            "is_retweet": False,
            "retweet_author": None,
        }
        recent_tweet = {
            "text": "New content",
            "created_at": datetime.now(UTC).strftime("%a %b %d %H:%M:%S %z %Y"),
            "author": "testuser",
            "images": [],
            "is_retweet": False,
            "retweet_author": None,
        }

        posts = map_tweets_to_content([old_tweet, recent_tweet], since_days=7)

        assert len(posts) == 1
        assert posts[0].body == "New content"

    def test_extracts_images(self):
        tweets = [
            {
                "text": "Check this out",
                "created_at": datetime.now(UTC).strftime("%a %b %d %H:%M:%S %z %Y"),
                "author": "testuser",
                "images": ["https://example.com/pic.jpg"],
                "is_retweet": False,
                "retweet_author": None,
            }
        ]

        posts = map_tweets_to_content(tweets, since_days=None)

        assert posts[0].image_urls == ["https://example.com/pic.jpg"]

    def test_skips_empty_content(self):
        tweets = [
            {
                "text": "",
                "created_at": datetime.now(UTC).strftime("%a %b %d %H:%M:%S %z %Y"),
                "author": "testuser",
                "images": [],
                "is_retweet": False,
                "retweet_author": None,
            }
        ]

        posts = map_tweets_to_content(tweets, since_days=None)

        assert len(posts) == 0

    def test_handles_retweets(self):
        tweets = [
            {
                "text": "Original tweet content",
                "created_at": datetime.now(UTC).strftime("%a %b %d %H:%M:%S %z %Y"),
                "author": "retweeter",
                "images": [],
                "is_retweet": True,
                "retweet_author": "original_author",
            }
        ]

        posts = map_tweets_to_content(tweets, since_days=None)

        assert len(posts) == 1
        assert posts[0].author == "@original_author"
        assert posts[0].reposted_by == "@retweeter"


class TestFetchUserTweets:
    @patch("unhook.twitter_feed._fetch_user_tweets_async")
    def test_returns_tweets_on_success(self, mock_async_fetch):
        mock_async_fetch.return_value = [
            {
                "text": "Test tweet",
                "created_at": "Mon Jan 15 10:30:00 +0000 2024",
                "author": "testuser",
            }
        ]

        # Since fetch_user_tweets uses asyncio.run, we need to patch at that level
        with patch("unhook.twitter_feed.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "text": "Test tweet",
                    "created_at": "Mon Jan 15 10:30:00 +0000 2024",
                    "author": "testuser",
                }
            ]
            result = fetch_user_tweets("testuser")

        assert len(result) == 1
        assert result[0]["text"] == "Test tweet"

    @patch("unhook.twitter_feed.asyncio.run")
    def test_returns_empty_on_error(self, mock_run):
        mock_run.side_effect = Exception("Network error")

        result = fetch_user_tweets("testuser")

        assert result == []


class TestFetchTwitterPosts:
    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_user_tweets")
    def test_fetches_from_all_users(self, mock_fetch_tweets, mock_load_users):
        mock_load_users.return_value = ["user1", "user2"]
        mock_fetch_tweets.return_value = [
            {
                "text": "Content",
                "created_at": datetime.now(UTC).strftime("%a %b %d %H:%M:%S %z %Y"),
                "author": "user1",
                "images": [],
                "is_retweet": False,
                "retweet_author": None,
            }
        ]

        posts = fetch_twitter_posts(since_days=None)

        assert mock_fetch_tweets.call_count == 2
        assert len(posts) == 2

    @patch("unhook.twitter_feed.load_twitter_users")
    def test_returns_empty_if_no_users(self, mock_load_users):
        mock_load_users.return_value = []

        posts = fetch_twitter_posts()

        assert posts == []

    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_user_tweets")
    def test_respects_limit(self, mock_fetch_tweets, mock_load_users):
        mock_load_users.return_value = ["user1"]
        mock_fetch_tweets.return_value = [
            {
                "text": f"Content {i}",
                "created_at": (datetime.now(UTC) - timedelta(hours=i)).strftime(
                    "%a %b %d %H:%M:%S %z %Y"
                ),
                "author": "user1",
                "images": [],
                "is_retweet": False,
                "retweet_author": None,
            }
            for i in range(10)
        ]

        posts = fetch_twitter_posts(limit=5, since_days=None)

        assert len(posts) == 5

    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_user_tweets")
    def test_sorts_by_date_descending(self, mock_fetch_tweets, mock_load_users):
        mock_load_users.return_value = ["user1"]
        mock_fetch_tweets.return_value = [
            {
                "text": "Older",
                "created_at": "Mon Jan 01 00:00:00 +0000 2024",
                "author": "user1",
                "images": [],
                "is_retweet": False,
                "retweet_author": None,
            },
            {
                "text": "Newer",
                "created_at": "Tue Jan 02 00:00:00 +0000 2024",
                "author": "user1",
                "images": [],
                "is_retweet": False,
                "retweet_author": None,
            },
        ]

        posts = fetch_twitter_posts(since_days=None)

        assert posts[0].body == "Newer"
        assert posts[1].body == "Older"

    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_user_tweets")
    def test_handles_fetch_errors_gracefully(self, mock_fetch_tweets, mock_load_users):
        mock_load_users.return_value = ["user1", "user2"]
        # First user fails, second succeeds
        mock_fetch_tweets.side_effect = [
            [],  # user1 fails
            [
                {
                    "text": "Content from user2",
                    "created_at": datetime.now(UTC).strftime("%a %b %d %H:%M:%S %z %Y"),
                    "author": "user2",
                    "images": [],
                    "is_retweet": False,
                    "retweet_author": None,
                }
            ],
        ]

        posts = fetch_twitter_posts(since_days=None)

        assert len(posts) == 1
        assert posts[0].author == "@user2"


@pytest.mark.asyncio
class TestFetchUserTweetsAsync:
    async def test_activates_guest_client(self):
        """Test that the async function properly activates guest client."""
        with patch("twikit.guest.GuestClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.activate = AsyncMock()
            mock_client.get_user_by_screen_name = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            from unhook.twitter_feed import _fetch_user_tweets_async

            result = await _fetch_user_tweets_async("testuser")

            mock_client.activate.assert_called_once()
            assert result == []
