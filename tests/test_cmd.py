"""Test cases for the __main__ module."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
import typer
from ebooklib import ITEM_DOCUMENT, epub
from typer.testing import CliRunner

from unhook.cmd import app, main
from unhook.post_content import PostContent


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


@pytest.fixture
def sample_posts():
    """Sample posts data."""
    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    long_body_1 = "Test post 1 " + "x" * 110
    long_body_2 = "Test post 2 " + "y" * 115
    return [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": long_body_1, "created_at": created_at},
                "embed": {
                    "images": [
                        {
                            "fullsize": "https://example.com/image1.jpg",
                            "thumb": "https://example.com/thumb1.jpg",
                        }
                    ]
                },
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/2",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": long_body_2, "created_at": created_at},
                "embed": {
                    "images": [
                        {
                            "fullsize": "https://example.com/image2.jpg",
                            "thumb": "https://example.com/thumb2.jpg",
                        }
                    ]
                },
            }
        },
    ]


def test_main_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    result = runner.invoke(app, ["main"])
    assert result.exit_code == 0
    app_cust = typer.Typer()
    app_cust.command()(main)
    result = runner.invoke(app_cust)
    assert result.exit_code == 0


def test_fetch_command_default_filename(runner: CliRunner, sample_posts, tmp_path):
    """It saves file with default date-based filename."""
    with patch("unhook.cmd.fetch_feed_posts") as mock_fetch:
        mock_fetch.return_value = sample_posts

        with patch("unhook.cmd.date") as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2025-10-06"

            # Change to temp directory
            with runner.isolated_filesystem(temp_dir=tmp_path):
                result = runner.invoke(app, ["fetch"])

                assert result.exit_code == 0
                assert "Saved 2 posts to 2025-10-06.parquet" in result.stdout
                assert Path("2025-10-06.parquet").exists()


def test_fetch_command_custom_filename(runner: CliRunner, sample_posts, tmp_path):
    """It saves file with custom filename."""
    with patch("unhook.cmd.fetch_feed_posts") as mock_fetch:
        mock_fetch.return_value = sample_posts

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, ["fetch", "--output", "custom.parquet"])

            assert result.exit_code == 0
            assert "Saved 2 posts to custom.parquet" in result.stdout
            assert Path("custom.parquet").exists()


def test_fetch_command_mocked_posts_in_file(runner: CliRunner, sample_posts, tmp_path):
    """It writes mocked posts data to parquet file correctly."""
    with patch("unhook.cmd.fetch_feed_posts") as mock_fetch:
        mock_fetch.return_value = sample_posts

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, ["fetch", "--output", "test.parquet"])

            assert result.exit_code == 0

            # Read the file back and verify contents
            df = pd.read_parquet("test.parquet")
            assert len(df) == 2
            assert df.iloc[0]["post"]["record"]["text"].startswith("Test post 1")
            assert df.iloc[1]["post"]["record"]["text"].startswith("Test post 2")


def test_fetch_writes_actual_file(runner: CliRunner, sample_posts, tmp_path):
    """Integration test - export fetched posts to an EPUB file."""

    with (
        patch("unhook.epub_service.fetch_feed_posts") as mock_fetch,
        patch("unhook.epub_service.download_images", AsyncMock()) as mock_download,
    ):
        mock_fetch.return_value = sample_posts
        mock_download.return_value = {
            "https://example.com/image1.jpg": b"img1",
            "https://example.com/image2.jpg": b"img2",
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                app,
                [
                    "export-epub",
                    "--output-dir",
                    "exports",
                    "--file-prefix",
                    "integration",
                ],
            )

            assert result.exit_code == 0

            exports_dir = Path("exports")
            epub_files = sorted(exports_dir.glob("integration-*.epub"))

            assert len(epub_files) == 1
            book = epub.read_epub(epub_files[0])
            html_docs = [
                item.get_content().decode()
                for item in book.get_items_of_type(ITEM_DOCUMENT)
            ]
            combined_html = "\n".join(html_docs)
            assert "Test post 1" in combined_html
            assert "Test post 2" in combined_html


@pytest.fixture
def sample_twitter_posts():
    """Sample Twitter PostContent objects."""
    return [
        PostContent(
            title="Tweet 1",
            author="@testuser",
            published=datetime.now(UTC),
            body="This is a test tweet",
            image_urls=[],
            reposted_by=None,
        ),
        PostContent(
            title="Tweet 2",
            author="@anotheruser",
            published=datetime.now(UTC),
            body="Another test tweet with more content",
            image_urls=["https://example.com/pic.jpg"],
            reposted_by="@testuser",
        ),
    ]


def test_fetch_twitter_command_saves_json(
    runner: CliRunner, sample_twitter_posts, tmp_path
):
    """It saves Twitter posts to JSON file."""
    with patch("unhook.cmd.fetch_twitter_posts") as mock_fetch:
        mock_fetch.return_value = sample_twitter_posts

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, ["fetch-twitter", "--output", "twitter.json"])

            assert result.exit_code == 0
            assert "Saved 2 Twitter posts to twitter.json" in result.stdout
            assert Path("twitter.json").exists()

            # Verify JSON structure
            data = json.loads(Path("twitter.json").read_text())
            assert len(data) == 2
            assert data[0]["author"] == "@testuser"
            assert data[0]["body"] == "This is a test tweet"
            assert data[1]["reposted_by"] == "@testuser"


def test_fetch_twitter_command_default_filename(
    runner: CliRunner, sample_twitter_posts, tmp_path
):
    """It saves file with default date-based filename."""
    with patch("unhook.cmd.fetch_twitter_posts") as mock_fetch:
        mock_fetch.return_value = sample_twitter_posts

        with patch("unhook.cmd.date") as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2025-01-05"

            with runner.isolated_filesystem(temp_dir=tmp_path):
                result = runner.invoke(app, ["fetch-twitter"])

                assert result.exit_code == 0
                assert "twitter-2025-01-05.json" in result.stdout
                assert Path("twitter-2025-01-05.json").exists()


def test_fetch_twitter_command_empty_result(runner: CliRunner, tmp_path):
    """It handles empty results gracefully."""
    with patch("unhook.cmd.fetch_twitter_posts") as mock_fetch:
        mock_fetch.return_value = []

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, ["fetch-twitter", "--output", "empty.json"])

            assert result.exit_code == 0
            assert "Saved 0 Twitter posts" in result.stdout

            data = json.loads(Path("empty.json").read_text())
            assert data == []
