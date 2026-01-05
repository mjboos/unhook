"""Command-line interface."""

import asyncio
from datetime import date
from pathlib import Path

import pandas as pd
import typer

from unhook.epub_service import export_recent_posts_to_epub
from unhook.feed import fetch_feed_posts
from unhook.twitter_feed import fetch_twitter_posts

app = typer.Typer()


@app.command()
def main() -> None:
    """Unhook."""


@app.command()
def fetch(
    limit: int = typer.Option(100, help="Maximum number of posts to fetch"),
    since_days: int = typer.Option(
        7, help="Only fetch posts from the last N days (use 0 to disable)"
    ),
    output: str = typer.Option(
        None, help="Output filename (default: YYYY-MM-DD.parquet)"
    ),
    feed: str = typer.Option(
        "timeline",
        help=(
            "Source feed to fetch (timeline for home feed, author for only your posts)"
        ),
    ),
) -> None:
    """
    Fetch recent posts from your Bluesky timeline and save to parquet.

    Args:
        limit: Maximum number of posts to fetch (default: 100)
        since_days: Only fetch posts from the last N days (default: 7, use 0 to disable)
        output: Output filename (default: today's date as YYYY-MM-DD.parquet)
    """
    # Fetch posts (convert 0 to None to disable date filtering)
    posts = fetch_feed_posts(
        limit=limit,
        since_days=since_days if since_days > 0 else None,
        feed=feed,
    )

    # Convert to DataFrame
    df = pd.DataFrame(posts)

    # Determine output filename
    if output is None:
        output = f"{date.today().isoformat()}.parquet"

    # Save to parquet
    output_path = Path(output)
    df.to_parquet(output_path)

    typer.echo(f"Saved {len(posts)} posts to {output}")


@app.command()
def fetch_twitter(
    limit: int = typer.Option(100, help="Maximum number of posts to fetch"),
    since_days: int = typer.Option(
        7, help="Only fetch posts from the last N days (use 0 to disable)"
    ),
    output: str = typer.Option(
        None, help="Output filename (default: twitter-YYYY-MM-DD.json)"
    ),
    config: Path = typer.Option(
        None,
        "--config",
        help="Path to twitter_users.txt (default: ./twitter_users.txt)",
    ),
) -> None:
    """
    Fetch recent posts from Twitter via Nitter RSS and save to JSON.

    Reads the list of Twitter users from twitter_users.txt (one username per line).
    """
    import json

    posts = fetch_twitter_posts(
        config_path=config,
        since_days=since_days if since_days > 0 else None,
        limit=limit,
    )

    # Convert PostContent objects to dicts
    posts_data = [
        {
            "title": p.title,
            "author": p.author,
            "published": p.published.isoformat(),
            "body": p.body,
            "image_urls": p.image_urls,
            "reposted_by": p.reposted_by,
        }
        for p in posts
    ]

    # Determine output filename
    if output is None:
        output = f"twitter-{date.today().isoformat()}.json"

    # Save to JSON
    output_path = Path(output)
    output_path.write_text(json.dumps(posts_data, indent=2, ensure_ascii=False))

    typer.echo(f"Saved {len(posts)} Twitter posts to {output}")


@app.command()
def export_epub(
    output_dir: Path = typer.Option(Path("exports"), help="Directory to save EPUBs"),
    limit: int = typer.Option(200, help="Maximum number of Bluesky posts to fetch"),
    file_prefix: str = typer.Option("posts", help="Filename prefix for the EPUB"),
    min_length: int = typer.Option(
        100, help="Minimum length (in characters) a Bluesky post must have to include"
    ),
    repost_min_length: int = typer.Option(
        300,
        help="Minimum length (in characters) a Bluesky repost must have to include",
    ),
    twitter: bool = typer.Option(
        False, "--twitter", help="Include Twitter posts from configured users"
    ),
    twitter_config: Path = typer.Option(
        None,
        "--twitter-config",
        help="Path to twitter_users.txt (default: ./twitter_users.txt)",
    ),
    twitter_limit: int = typer.Option(
        100, "--twitter-limit", help="Maximum number of Twitter posts to fetch"
    ),
    twitter_min_length: int = typer.Option(
        50,
        "--twitter-min-length",
        help="Minimum length (in characters) a Twitter post must have to include",
    ),
) -> None:
    """Fetch recent posts and export them as an EPUB file."""

    output_path = asyncio.run(
        export_recent_posts_to_epub(
            output_dir=output_dir,
            limit=limit,
            file_prefix=file_prefix,
            min_length=min_length,
            repost_min_length=repost_min_length,
            include_twitter=twitter,
            twitter_config_path=twitter_config,
            twitter_limit=twitter_limit,
            twitter_min_length=twitter_min_length,
        )
    )
    typer.echo(f"Saved EPUB to {output_path}")


if __name__ == "__main__":
    app()  # pragma: no cover
