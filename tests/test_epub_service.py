"""Tests for the EPUB export service."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from unhook.epub_service import download_images, export_recent_posts_to_epub


@pytest.mark.asyncio
async def test_download_images_handles_failures(monkeypatch):
    responses = {"https://good.com/a.png": b"abc", "https://bad.com/b.png": None}

    async def mock_download(client, url):
        return responses.get(url)

    monkeypatch.setattr("unhook.epub_service._download_image", mock_download)

    result = await download_images(list(responses.keys()))
    assert "https://good.com/a.png" in result
    assert "https://bad.com/b.png" not in result


@pytest.mark.asyncio
async def test_export_recent_posts_to_epub(tmp_path, monkeypatch):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sample_feed = [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/1",
                "author": {"handle": "user.bsky.social"},
                "record": {"text": "Post body", "created_at": now},
                "embed": {"images": [{"fullsize": "https://example.com/image.jpg"}]},
            }
        }
    ]

    monkeypatch.setattr(
        "unhook.epub_service.fetch_feed_posts",
        lambda limit=200, since_days=1: sample_feed,
    )
    monkeypatch.setattr(
        "unhook.epub_service.download_images",
        AsyncMock(return_value={"https://example.com/image.jpg": b"img"}),
    )

    output_path = await export_recent_posts_to_epub(tmp_path, file_prefix="test")

    assert Path(output_path).exists()
    assert Path(output_path).suffix == ".epub"
