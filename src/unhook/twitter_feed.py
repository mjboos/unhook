"""Twitter feed fetching via twikit GuestClient."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from unhook.post_content import PostContent

logger = logging.getLogger(__name__)

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


async def _fetch_user_tweets_async(
    username: str,
    limit: int = 20,
) -> list[dict]:
    """Fetch tweets for a user using twikit GuestClient.

    Args:
        username: Twitter username (without @ prefix).
        limit: Maximum number of tweets to fetch.

    Returns:
        List of tweet dicts with keys: text, created_at, author, images, is_retweet
    """
    try:
        from twikit.guest import GuestClient
    except ImportError:
        logger.error("twikit is not installed. Run: pip install twikit")
        return []

    client = GuestClient()

    try:
        # Activate guest token
        await client.activate()
        logger.info("Activated twikit guest client")

        # Get user by screen name to get their ID
        user = await client.get_user_by_screen_name(username)
        if not user:
            logger.warning("User @%s not found", username)
            return []

        logger.info("Found user @%s (id: %s)", username, user.id)

        # Get user's tweets
        tweets_result = await client.get_user_tweets(user.id, "Tweets")
        if not tweets_result:
            logger.info("No tweets found for @%s", username)
            return []

        tweets = []
        count = 0
        for tweet in tweets_result:
            if count >= limit:
                break

            tweet_data = {
                "text": tweet.text or "",
                "created_at": tweet.created_at,
                "author": username,
                "tweet_id": tweet.id,
                "is_retweet": False,
                "retweet_author": None,
                "images": [],
            }

            # Check if it's a retweet
            if hasattr(tweet, "retweeted_tweet") and tweet.retweeted_tweet:
                tweet_data["is_retweet"] = True
                if hasattr(tweet.retweeted_tweet, "user"):
                    tweet_data["retweet_author"] = (
                        tweet.retweeted_tweet.user.screen_name
                    )

            # Extract media/images
            if hasattr(tweet, "media") and tweet.media:
                for media in tweet.media:
                    if hasattr(media, "media_url_https"):
                        tweet_data["images"].append(media.media_url_https)
                    elif hasattr(media, "url"):
                        tweet_data["images"].append(media.url)

            tweets.append(tweet_data)
            count += 1

        logger.info("Fetched %d tweets for @%s", len(tweets), username)
        return tweets

    except Exception as e:
        logger.warning("Error fetching tweets for @%s: %s", username, e)
        return []


def fetch_user_tweets(username: str, limit: int = 20) -> list[dict]:
    """Synchronous wrapper for fetching user tweets.

    Args:
        username: Twitter username (without @ prefix).
        limit: Maximum number of tweets to fetch.

    Returns:
        List of tweet dicts.
    """
    try:
        return asyncio.run(_fetch_user_tweets_async(username, limit))
    except Exception as e:
        logger.warning("Error in async tweet fetch for @%s: %s", username, e)
        return []


def _parse_twitter_timestamp(date_str: str | None) -> datetime:
    """Parse Twitter timestamp string to datetime.

    Twitter uses format like: "Mon Jan 06 12:34:56 +0000 2025"
    """
    if not date_str:
        return datetime.now(UTC)

    try:
        # Twitter format: "Mon Jan 06 12:34:56 +0000 2025"
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt
    except ValueError:
        pass

    try:
        # Try ISO format as fallback
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt
    except ValueError:
        pass

    logger.debug("Could not parse date: %s", date_str)
    return datetime.now(UTC)


def map_tweets_to_content(
    tweets: list[dict],
    since_days: int | None = 7,
) -> list[PostContent]:
    """Convert tweet dicts to PostContent objects.

    Args:
        tweets: Tweet dicts from fetch_user_tweets.
        since_days: Only include tweets from the last N days. None to disable.

    Returns:
        List of PostContent objects.
    """
    if since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
    else:
        cutoff = None

    content_list: list[PostContent] = []

    for tweet in tweets:
        published = _parse_twitter_timestamp(tweet.get("created_at"))

        if cutoff and published < cutoff:
            continue

        body = tweet.get("text", "")
        if not body:
            continue

        # Generate title from first line
        title = body.split("\n", 1)[0][:60] if body else "Untitled"

        author = tweet.get("author", "unknown")
        is_retweet = tweet.get("is_retweet", False)
        retweet_author = tweet.get("retweet_author")

        # For retweets, the original author posted it, retweeted by timeline owner
        if is_retweet and retweet_author:
            reposted_by = f"@{author}"
            author = retweet_author
        else:
            reposted_by = None

        content_list.append(
            PostContent(
                title=title,
                author=f"@{author}",
                published=published,
                body=body,
                image_urls=tweet.get("images", []),
                reposted_by=reposted_by,
            )
        )

    return content_list


def fetch_twitter_posts(
    config_path: Path | str | None = None,
    since_days: int | None = 7,
    limit: int = 100,
) -> list[PostContent]:
    """Fetch Twitter posts for all configured users.

    Args:
        config_path: Path to twitter_users.txt config file.
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
        tweets = fetch_user_tweets(username, limit=50)
        posts = map_tweets_to_content(tweets, since_days)
        all_posts.extend(posts)

    # Sort by date descending and limit
    all_posts.sort(key=lambda p: p.published, reverse=True)
    return all_posts[:limit]


__all__ = [
    "load_twitter_users",
    "fetch_user_tweets",
    "fetch_twitter_posts",
    "map_tweets_to_content",
]
