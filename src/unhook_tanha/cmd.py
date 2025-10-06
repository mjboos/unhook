"""Command-line interface."""

from datetime import date
from pathlib import Path

import pandas as pd
import typer

from unhook_tanha.feed import fetch_feed_posts

app = typer.Typer()


@app.command()
def main() -> None:
    """Unhook Tanha."""


@app.command()
def fetch(
    limit: int = typer.Option(100, help="Maximum number of posts to fetch"),
    output: str = typer.Option(
        None, help="Output filename (default: YYYY-MM-DD.parquet)"
    ),
) -> None:
    """
    Fetch recent posts from your Bluesky timeline and save to parquet.

    Args:
        limit: Maximum number of posts to fetch (default: 100)
        output: Output filename (default: today's date as YYYY-MM-DD.parquet)
    """
    # Fetch posts
    posts = fetch_feed_posts(limit=limit)

    # Convert to DataFrame
    df = pd.DataFrame(posts)

    # Determine output filename
    if output is None:
        output = f"{date.today().isoformat()}.parquet"

    # Save to parquet
    output_path = Path(output)
    df.to_parquet(output_path)

    typer.echo(f"Saved {len(posts)} posts to {output}")


if __name__ == "__main__":
    app()  # pragma: no cover
