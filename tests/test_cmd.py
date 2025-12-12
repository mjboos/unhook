"""Test cases for the __main__ module."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import typer
from typer.testing import CliRunner

from unhook.cmd import app, main


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


@pytest.fixture
def sample_posts():
    """Sample posts data."""
    return [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "record": {"text": "Test post 1"},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/2",
                "record": {"text": "Test post 2"},
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
            assert df.iloc[0]["post"]["record"]["text"] == "Test post 1"
            assert df.iloc[1]["post"]["record"]["text"] == "Test post 2"


def test_fetch_writes_actual_file(runner: CliRunner, sample_posts, tmp_path):
    """Integration test - verify file is written and readable."""
    with patch("unhook.cmd.fetch_feed_posts") as mock_fetch:
        mock_fetch.return_value = sample_posts

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, ["fetch", "--output", "output.parquet"])

            assert result.exit_code == 0

            output_file = Path("output.parquet")
            assert output_file.exists()
            assert output_file.stat().st_size > 0

            # Verify it's a valid parquet file
            df = pd.read_parquet(output_file)
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2
