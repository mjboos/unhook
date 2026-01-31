"""Command-line interface."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pandas as pd
import typer

from unhook.epub_service import export_recent_posts_to_epub
from unhook.feed import fetch_feed_posts

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
def export_epub(
    output_dir: Path = typer.Option(Path("exports"), help="Directory to save EPUBs"),
    limit: int = typer.Option(200, help="Maximum number of posts to fetch"),
    file_prefix: str = typer.Option("posts", help="Filename prefix for the EPUB"),
    min_length: int = typer.Option(
        100, help="Minimum length (in characters) a post must have to include"
    ),
    repost_min_length: int = typer.Option(
        300,
        help="Minimum length (in characters) a repost must have to include",
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
        )
    )
    typer.echo(f"Saved EPUB to {output_path}")


@app.command()
def gmail_to_kindle(
    output_dir: Path = typer.Option(Path("exports"), help="Directory to save EPUBs"),
    since_days: int = typer.Option(1, help="Only include emails from the last N days"),
    file_prefix: str = typer.Option("newsletters", help="Filename prefix for the EPUB"),
    label: str = typer.Option(
        "newsletters-kindle", help="Gmail label to fetch emails from"
    ),
    gmail_address: str = typer.Option(
        None,
        envvar="GMAIL_ADDRESS",
        help="Gmail address (or set GMAIL_ADDRESS env var)",
    ),
    gmail_app_password: str = typer.Option(
        None,
        envvar="GMAIL_APP_PASSWORD",
        help="Gmail app password (or set GMAIL_APP_PASSWORD env var)",
    ),
) -> None:
    """Fetch emails from Gmail by label and export as EPUB.

    Requires Gmail IMAP access with an app password.
    Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD environment variables,
    or pass them as options.
    """
    from unhook.gmail_epub_service import export_gmail_to_epub
    from unhook.gmail_service import GmailConfig

    # Validate required credentials
    if not gmail_address:
        typer.echo(
            "Error: Gmail address required. Set GMAIL_ADDRESS or --gmail-address",
            err=True,
        )
        raise typer.Exit(1)
    if not gmail_app_password:
        typer.echo(
            "Error: App password required. Set GMAIL_APP_PASSWORD env var",
            err=True,
        )
        raise typer.Exit(1)

    config = GmailConfig(
        email_address=gmail_address,
        app_password=gmail_app_password,
        label=label,
    )

    output_path = asyncio.run(
        export_gmail_to_epub(
            config=config,
            output_dir=output_dir,
            since_days=since_days,
            file_prefix=file_prefix,
        )
    )

    if output_path:
        typer.echo(f"Saved EPUB to {output_path}")
    else:
        typer.echo("No emails found matching criteria. Skipping.", err=True)
        raise typer.Exit(0)


if __name__ == "__main__":
    app()  # pragma: no cover
