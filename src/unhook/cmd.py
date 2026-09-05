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
        envvar="SMTP_USERNAME",
        help="Gmail address (or set SMTP_USERNAME env var)",
    ),
    gmail_app_password: str = typer.Option(
        None,
        envvar="GAPPPWD",
        help="Gmail app password (or set GAPPPWD env var)",
    ),
) -> None:
    """Fetch emails from Gmail by label and export as EPUB.

    Requires Gmail IMAP access with an app password.
    Set SMTP_USERNAME and GAPPPWD environment variables,
    or pass them as options.
    """
    from unhook.gmail_epub_service import export_gmail_to_epub
    from unhook.gmail_service import GmailConfig

    # Validate required credentials
    if not gmail_address:
        typer.echo(
            "Error: Gmail address required. Set SMTP_USERNAME env var",
            err=True,
        )
        raise typer.Exit(1)
    if not gmail_app_password:
        typer.echo(
            "Error: App password required. Set GAPPPWD env var",
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


@app.command()
def substack_to_kindle(
    publications: str = typer.Option(
        None,
        envvar="SUBSTACK_PUBLICATIONS",
        help=(
            "Comma-separated publications to fetch: subdomain (thezvi), "
            "domain (www.astralcodexten.com), or full URL"
        ),
    ),
    output_dir: Path = typer.Option(Path("exports"), help="Directory to save EPUBs"),
    since_days: int = typer.Option(4, help="Only include posts from the last N days"),
    file_prefix: str = typer.Option("substack", help="Filename prefix for the EPUB"),
    substack_sid: str = typer.Option(
        None,
        envvar="SUBSTACK_SID",
        help="substack.sid session cookie to unlock paywalled posts (optional)",
    ),
) -> None:
    """Fetch recent posts from Substack publications and export as EPUB.

    Uses Substack's JSON API directly instead of newsletter emails.
    Set SUBSTACK_PUBLICATIONS to a comma-separated list of publications,
    and optionally SUBSTACK_SID to include paywalled posts you subscribe to.
    """
    from unhook.substack_service import export_substack_to_epub, parse_publications

    if not publications:
        typer.echo(
            "Error: publications required. Set SUBSTACK_PUBLICATIONS env var",
            err=True,
        )
        raise typer.Exit(1)

    publication_urls = parse_publications(publications)
    if not publication_urls:
        typer.echo("Error: no valid publications in list", err=True)
        raise typer.Exit(1)

    output_path = asyncio.run(
        export_substack_to_epub(
            publications=publication_urls,
            output_dir=output_dir,
            since_days=since_days,
            file_prefix=file_prefix,
            sid=substack_sid,
        )
    )

    if output_path:
        typer.echo(f"Saved EPUB to {output_path}")
    else:
        typer.echo("No posts found matching criteria. Skipping.", err=True)
        raise typer.Exit(0)


@app.command()
def list_subscriptions(
    handle: str = typer.Option(
        None,
        help="Substack handle or profile URL (public subscriptions only)",
    ),
    substack_sid: str = typer.Option(
        None,
        envvar="SUBSTACK_SID",
        help=(
            "substack.sid session cookie (or set SUBSTACK_SID). Returns the "
            "full list, including subscriptions hidden from your profile"
        ),
    ),
    paid_only: bool = typer.Option(False, help="Only list paid-tier subscriptions"),
) -> None:
    """List your Substack subscriptions to build SUBSTACK_PUBLICATIONS.

    With SUBSTACK_SID set this reads your full subscription list. With only
    a handle it reads the publicly visible subscriptions from that profile.
    """
    from unhook.substack_service import format_publications_value
    from unhook.substack_service import list_subscriptions as fetch_subscriptions

    if not handle and not substack_sid:
        typer.echo(
            "Error: pass --handle, or set SUBSTACK_SID for the full list",
            err=True,
        )
        raise typer.Exit(1)

    subscriptions = asyncio.run(fetch_subscriptions(handle=handle, sid=substack_sid))

    if paid_only:
        subscriptions = [sub for sub in subscriptions if sub.is_paid]

    if not subscriptions:
        typer.echo("No subscriptions found.", err=True)
        raise typer.Exit(0)

    for subscription in subscriptions:
        tier = "paid" if subscription.is_paid else "free"
        host = subscription.base_url.removeprefix("https://")
        typer.echo(f"  {tier:5}  {subscription.name:<34.34}  {host}")

    typer.echo(f"\n{len(subscriptions)} subscription(s).")
    typer.echo("\nSUBSTACK_PUBLICATIONS value:")
    typer.echo(format_publications_value(subscriptions))


if __name__ == "__main__":
    app()  # pragma: no cover
