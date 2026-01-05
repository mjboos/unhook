"""Twitter feed fetching via Nitter RSS."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import mktime

import feedparser

from unhook.post_content import PostContent

logger = logging.getLogger(__name__)

DEFAULT_NITTER_INSTANCE = "https://nitter.poast.org"
DEFAULT_CONFIG_FILE = "twitter_users.txt"


def load_twitter_users(config_path: Path | str | None = None) -> list[str]:
    """Load Twitter usernames from config file.

    Args:
        config_path: Path to config file. Defaults to twitter_users.txt in cwd.

    Returns:
        List of Twitter usernames (without @ prefix).
    """
    if config_path is None:
        config_path = Path(DEFAULT_CONFIG_FILE)
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        logger.warning("Twitter users config file not found: %s", config_path)
        return []

    users = []
    for line in config_path.read_text().splitlines():
        username = line.strip().lstrip("@")
        if username and not username.startswith("#"):
            users.append(username)

    return users


def fetch_twitter_rss(
    username: str,
    nitter_instance: str = DEFAULT_NITTER_INSTANCE,
) -> list[dict]:
    """Fetch RSS feed for a Twitter user via Nitter.

    Args:
        username: Twitter username (without @ prefix).
        nitter_instance: Nitter instance URL.

    Returns:
        List of RSS entry dicts from feedparser.
    """
    url = f"{nitter_instance}/{username}/rss"
    logger.info("Fetching Twitter RSS for @%s from %s", username, url)

    feed = feedparser.parse(url)

    if feed.bozo:
        logger.warning("Error parsing RSS for @%s: %s", username, feed.bozo_exception)
        return []

    if not feed.entries:
        logger.info("No entries found for @%s", username)
        return []

    logger.info("Fetched %d entries for @%s", len(feed.entries), username)
    return list(feed.entries)


def _parse_rss_timestamp(entry: dict) -> datetime:
    """Parse timestamp from RSS entry."""
    published = entry.get("published_parsed")
    if published:
        return datetime.fromtimestamp(mktime(published), tz=UTC)
    updated = entry.get("updated_parsed")
    if updated:
        return datetime.fromtimestamp(mktime(updated), tz=UTC)
    return datetime.now(UTC)


def _extract_images_from_html(html_content: str) -> list[str]:
    """Extract image URLs from HTML content."""
    img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
    return img_pattern.findall(html_content)


def _clean_html_to_text(html_content: str) -> str:
    """Convert HTML content to plain text, preserving links as markdown."""
    if not html_content:
        return ""

    text = html_content

    # Convert <a href="...">text</a> to [text](url)
    link_pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', re.IGNORECASE
    )
    text = link_pattern.sub(r"[\2](\1)", text)

    # Convert <br> and <br/> to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Convert <p> tags to double newlines
    text = re.sub(r"</?p[^>]*>", "\n\n", text, flags=re.IGNORECASE)

    # Remove remaining HTML tags (but not their content)
    text = re.sub(r"<[^>]+>", "", text)

    # Decode common HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # Clean up excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def _is_retweet(entry: dict) -> bool:
    """Check if an RSS entry is a retweet."""
    title = entry.get("title", "")
    return title.startswith("RT by @") or title.startswith("R to @")


def _extract_retweet_info(entry: dict) -> tuple[str | None, str | None]:
    """Extract retweeter handle and original author from retweet.

    Returns:
        Tuple of (retweeter_handle, original_author) or (None, None).
    """
    title = entry.get("title", "")

    # RT by @retweeter: Original tweet from @original_author
    rt_match = re.match(r"RT by @(\w+):", title)
    if rt_match:
        retweeter = rt_match.group(1)
        # Try to find original author in the content
        return retweeter, None

    return None, None


def map_twitter_entries_to_content(
    entries: list[dict],
    username: str,
    since_days: int | None = 7,
) -> list[PostContent]:
    """Convert RSS entries to PostContent objects.

    Args:
        entries: RSS entries from feedparser.
        username: Twitter username these entries belong to.
        since_days: Only include entries from the last N days. None to disable.

    Returns:
        List of PostContent objects.
    """
    if since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
    else:
        cutoff = None

    content_list: list[PostContent] = []

    for entry in entries:
        published = _parse_rss_timestamp(entry)

        if cutoff and published < cutoff:
            continue

        # Get the content - Nitter uses 'summary' for tweet text
        html_content = entry.get("summary", "") or entry.get("description", "")

        # Extract images before cleaning HTML
        image_urls = _extract_images_from_html(html_content)

        # Clean HTML to text
        body = _clean_html_to_text(html_content)

        if not body:
            continue

        # Generate title from first line
        title = body.split("\n", 1)[0][:60] if body else "Untitled"

        # Handle retweets
        reposted_by = None
        author = username
        if _is_retweet(entry):
            retweeter, _ = _extract_retweet_info(entry)
            if retweeter:
                reposted_by = retweeter
                # The actual author is in the username we're fetching
                # but this is a retweet, so swap
                author = username
                reposted_by = username
                # For retweets, we'd need to parse the original author from content
                # For simplicity, mark it as reposted by the timeline owner

        content_list.append(
            PostContent(
                title=title,
                author=f"@{author}",
                published=published,
                body=body,
                image_urls=image_urls,
                reposted_by=f"@{reposted_by}" if reposted_by else None,
            )
        )

    return content_list


def fetch_twitter_posts(
    config_path: Path | str | None = None,
    nitter_instance: str = DEFAULT_NITTER_INSTANCE,
    since_days: int | None = 7,
    limit: int = 100,
) -> list[PostContent]:
    """Fetch Twitter posts for all configured users.

    Args:
        config_path: Path to twitter_users.txt config file.
        nitter_instance: Nitter instance URL to use.
        since_days: Only include posts from the last N days.
        limit: Maximum total posts to return.

    Returns:
        List of PostContent objects, sorted by published date descending.
    """
    users = load_twitter_users(config_path)
    if not users:
        logger.warning("No Twitter users configured")
        return []

    all_posts: list[PostContent] = []

    for username in users:
        entries = fetch_twitter_rss(username, nitter_instance)
        posts = map_twitter_entries_to_content(entries, username, since_days)
        all_posts.extend(posts)

    # Sort by date descending and limit
    all_posts.sort(key=lambda p: p.published, reverse=True)
    return all_posts[:limit]


__all__ = [
    "load_twitter_users",
    "fetch_twitter_rss",
    "fetch_twitter_posts",
    "map_twitter_entries_to_content",
]
