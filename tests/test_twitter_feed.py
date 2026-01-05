"""Tests for Twitter feed fetching via Nitter RSS."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from unhook.twitter_feed import (
    _clean_html_to_text,
    _extract_images_from_html,
    _fetch_rss_content,
    _get_nitter_instances,
    _is_retweet,
    _parse_rss_timestamp,
    fetch_twitter_posts,
    fetch_twitter_rss,
    load_twitter_users,
    map_twitter_entries_to_content,
)


class TestGetNitterInstances:
    def test_returns_defaults_when_no_env(self):
        with patch.dict("os.environ", {}, clear=True):
            instances = _get_nitter_instances()
            assert len(instances) >= 1
            assert "nitter.poast.org" in instances[0]

    def test_single_instance_override(self):
        with patch.dict("os.environ", {"NITTER_INSTANCE": "https://custom.nitter.com"}):
            instances = _get_nitter_instances()
            assert instances == ["https://custom.nitter.com"]

    def test_multiple_instances_override(self):
        with patch.dict(
            "os.environ", {"NITTER_INSTANCES": "https://a.com, https://b.com"}
        ):
            instances = _get_nitter_instances()
            assert instances == ["https://a.com", "https://b.com"]

    def test_strips_trailing_slashes(self):
        with patch.dict("os.environ", {"NITTER_INSTANCE": "https://example.com/"}):
            instances = _get_nitter_instances()
            assert instances == ["https://example.com"]


class TestFetchRssContent:
    @patch("unhook.twitter_feed.httpx.get")
    def test_returns_content_for_valid_rss(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/rss+xml"}
        mock_response.text = '<?xml version="1.0"?><rss><channel></channel></rss>'

        result = _fetch_rss_content("https://example.com/rss")

        assert result is not None
        assert "<rss>" in result

    @patch("unhook.twitter_feed.httpx.get")
    def test_returns_none_for_html_response(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<html><body>Error page</body></html>"

        result = _fetch_rss_content("https://example.com/rss")

        assert result is None

    @patch("unhook.twitter_feed.httpx.get")
    def test_returns_none_for_non_200(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.status_code = 503
        mock_response.headers = {}
        mock_response.text = "Service unavailable"

        result = _fetch_rss_content("https://example.com/rss")

        assert result is None


class TestFetchTwitterRss:
    @patch("unhook.twitter_feed._fetch_rss_content")
    def test_tries_multiple_instances_on_failure(self, mock_fetch):
        # First two fail, third succeeds
        valid_rss = (
            '<?xml version="1.0"?>'
            "<rss><channel><item><title>Test</title></item></channel></rss>"
        )
        mock_fetch.side_effect = [None, None, valid_rss]

        with patch(
            "unhook.twitter_feed._get_nitter_instances",
            return_value=["https://a.com", "https://b.com", "https://c.com"],
        ):
            fetch_twitter_rss("testuser")

        assert mock_fetch.call_count == 3

    @patch("unhook.twitter_feed._fetch_rss_content")
    def test_returns_empty_when_all_instances_fail(self, mock_fetch):
        mock_fetch.return_value = None

        with patch(
            "unhook.twitter_feed._get_nitter_instances",
            return_value=["https://a.com", "https://b.com"],
        ):
            result = fetch_twitter_rss("testuser")

        assert result == []


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


class TestParseRssTimestamp:
    def test_parses_published_parsed(self):
        entry = {"published_parsed": (2024, 1, 15, 10, 30, 0, 0, 15, 0)}

        result = _parse_rss_timestamp(entry)

        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_falls_back_to_updated_parsed(self):
        entry = {"updated_parsed": (2024, 2, 20, 14, 0, 0, 0, 51, 0)}

        result = _parse_rss_timestamp(entry)

        assert result.year == 2024
        assert result.month == 2
        assert result.day == 20

    def test_returns_now_if_no_timestamp(self):
        entry = {}

        result = _parse_rss_timestamp(entry)

        assert result.tzinfo == UTC
        assert (datetime.now(UTC) - result).total_seconds() < 5


class TestExtractImagesFromHtml:
    def test_extracts_image_urls(self):
        html = '<p>Text</p><img src="https://example.com/img.jpg"/>'

        urls = _extract_images_from_html(html)

        assert urls == ["https://example.com/img.jpg"]

    def test_extracts_multiple_images(self):
        html = '<img src="img1.jpg"><img src="img2.png">'

        urls = _extract_images_from_html(html)

        assert urls == ["img1.jpg", "img2.png"]

    def test_returns_empty_list_for_no_images(self):
        html = "<p>No images here</p>"

        urls = _extract_images_from_html(html)

        assert urls == []


class TestCleanHtmlToText:
    def test_converts_links_to_markdown(self):
        html = '<a href="https://example.com">Example</a>'

        text = _clean_html_to_text(html)

        assert text == "[Example](https://example.com)"

    def test_converts_br_to_newline(self):
        html = "Line 1<br>Line 2<br/>Line 3"

        text = _clean_html_to_text(html)

        assert "Line 1\nLine 2\nLine 3" in text

    def test_removes_html_tags(self):
        html = "<p><strong>Bold</strong> and <em>italic</em></p>"

        text = _clean_html_to_text(html)

        assert "Bold" in text
        assert "italic" in text
        assert "<" not in text

    def test_decodes_html_entities(self):
        html = "&amp; &lt; &gt; &quot; &#39;"

        text = _clean_html_to_text(html)

        assert "& < > \" '" in text

    def test_handles_empty_input(self):
        assert _clean_html_to_text("") == ""
        assert _clean_html_to_text(None) == ""


class TestIsRetweet:
    def test_detects_rt_by_prefix(self):
        entry = {"title": "RT by @someone: Original tweet"}

        assert _is_retweet(entry) is True

    def test_detects_reply_prefix(self):
        entry = {"title": "R to @someone: Reply text"}

        assert _is_retweet(entry) is True

    def test_returns_false_for_normal_tweet(self):
        entry = {"title": "Just a normal tweet"}

        assert _is_retweet(entry) is False


class TestMapTwitterEntriesToContent:
    def test_converts_entry_to_post_content(self):
        entries = [
            {
                "title": "Test tweet",
                "summary": "<p>Hello world!</p>",
                "published_parsed": (2024, 1, 15, 10, 30, 0, 0, 15, 0),
            }
        ]

        posts = map_twitter_entries_to_content(entries, "testuser", since_days=None)

        assert len(posts) == 1
        assert posts[0].body == "Hello world!"
        assert posts[0].author == "@testuser"

    def test_filters_by_date(self):
        old_entry = {
            "title": "Old tweet",
            "summary": "<p>Old content</p>",
            "published_parsed": (2020, 1, 1, 0, 0, 0, 0, 1, 0),
        }
        recent_entry = {
            "title": "New tweet",
            "summary": "<p>New content</p>",
            "published_parsed": tuple(datetime.now(UTC).timetuple()[:9]),
        }

        posts = map_twitter_entries_to_content(
            [old_entry, recent_entry], "testuser", since_days=7
        )

        assert len(posts) == 1
        assert posts[0].body == "New content"

    def test_extracts_images(self):
        entries = [
            {
                "title": "Tweet with image",
                "summary": '<p>Check this</p><img src="https://example.com/pic.jpg">',
                "published_parsed": tuple(datetime.now(UTC).timetuple()[:9]),
            }
        ]

        posts = map_twitter_entries_to_content(entries, "testuser", since_days=None)

        assert posts[0].image_urls == ["https://example.com/pic.jpg"]

    def test_skips_empty_content(self):
        entries = [
            {
                "title": "Empty",
                "summary": "",
                "published_parsed": tuple(datetime.now(UTC).timetuple()[:9]),
            }
        ]

        posts = map_twitter_entries_to_content(entries, "testuser", since_days=None)

        assert len(posts) == 0


class TestFetchTwitterPosts:
    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_twitter_rss")
    def test_fetches_from_all_users(self, mock_fetch_rss, mock_load_users):
        mock_load_users.return_value = ["user1", "user2"]
        mock_fetch_rss.return_value = [
            {
                "title": "Tweet",
                "summary": "<p>Content</p>",
                "published_parsed": tuple(datetime.now(UTC).timetuple()[:9]),
            }
        ]

        posts = fetch_twitter_posts(since_days=None)

        assert mock_fetch_rss.call_count == 2
        assert len(posts) == 2

    @patch("unhook.twitter_feed.load_twitter_users")
    def test_returns_empty_if_no_users(self, mock_load_users):
        mock_load_users.return_value = []

        posts = fetch_twitter_posts()

        assert posts == []

    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_twitter_rss")
    def test_respects_limit(self, mock_fetch_rss, mock_load_users):
        mock_load_users.return_value = ["user1"]
        mock_fetch_rss.return_value = [
            {
                "title": f"Tweet {i}",
                "summary": f"<p>Content {i}</p>",
                "published_parsed": tuple(
                    (datetime.now(UTC) - timedelta(hours=i)).timetuple()[:9]
                ),
            }
            for i in range(10)
        ]

        posts = fetch_twitter_posts(limit=5, since_days=None)

        assert len(posts) == 5

    @patch("unhook.twitter_feed.load_twitter_users")
    @patch("unhook.twitter_feed.fetch_twitter_rss")
    def test_sorts_by_date_descending(self, mock_fetch_rss, mock_load_users):
        mock_load_users.return_value = ["user1"]
        mock_fetch_rss.return_value = [
            {
                "title": "Older",
                "summary": "<p>Older</p>",
                "published_parsed": (2024, 1, 1, 0, 0, 0, 0, 1, 0),
            },
            {
                "title": "Newer",
                "summary": "<p>Newer</p>",
                "published_parsed": (2024, 1, 2, 0, 0, 0, 0, 2, 0),
            },
        ]

        posts = fetch_twitter_posts(since_days=None)

        assert posts[0].body == "Newer"
        assert posts[1].body == "Older"
