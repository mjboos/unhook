"""Tests for the Gmail EPUB export service."""

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from ebooklib import ITEM_DOCUMENT, epub
from PIL import Image

from unhook.email_content import EmailContent
from unhook.gmail_epub_service import (
    EmailEpubBuilder,
    _compress_image,
    _sanitize_email_html,
    _strip_email_boilerplate,
    _strip_small_images,
    download_external_images,
    export_gmail_to_epub,
)
from unhook.gmail_service import GmailConfig, RawEmail


def _create_test_image(
    width: int, height: int, mode: str = "RGB", img_format: str = "JPEG"
) -> bytes:
    """Create a test image in memory and return its bytes."""
    image = Image.new(mode, (width, height), color="blue")
    output = BytesIO()
    if img_format == "JPEG" and mode == "RGBA":
        image = image.convert("RGB")
    image.save(output, format=img_format)
    return output.getvalue()


class TestSanitizeEmailHtml:
    """Tests for _sanitize_email_html function."""

    def test_preserves_allowed_tags(self):
        """It preserves allowed HTML tags."""
        html = "<p>Hello <strong>World</strong></p>"
        result = _sanitize_email_html(html)
        assert "<p>" in result
        assert "<strong>" in result

    def test_removes_script_tags_and_content(self):
        """It removes script tags and their content."""
        html = "<p>Hello</p><script>alert('xss')</script>"
        result = _sanitize_email_html(html)
        assert "<script>" not in result
        assert "alert" not in result

    def test_removes_style_tags_and_content(self):
        """It removes style tags and their CSS content."""
        html = "<p>Hello</p><style>body{color:red} @media{}</style>"
        result = _sanitize_email_html(html)
        assert "<style>" not in result
        assert "color:red" not in result
        assert "@media" not in result

    def test_removes_head_section(self):
        """It removes the entire <head> section including styles and title."""
        html = (
            "<html><head><title>Test</title>"
            "<style>.foo{margin:0}</style></head>"
            "<body><p>Content</p></body></html>"
        )
        result = _sanitize_email_html(html)
        assert ".foo" not in result
        assert "margin:0" not in result
        assert "<p>Content</p>" in result

    def test_preserves_img_tags(self):
        """It preserves img tags with allowed attributes."""
        html = '<img src="image.jpg" alt="Test">'
        result = _sanitize_email_html(html)
        assert "<img" in result
        assert 'src="image.jpg"' in result
        assert 'alt="Test"' in result

    def test_strips_table_layout_but_keeps_content(self):
        """It strips table tags (email layout) but preserves cell text."""
        html = "<table><tr><td>Cell</td></tr></table>"
        result = _sanitize_email_html(html)
        assert "<table>" not in result
        assert "<tr>" not in result
        assert "<td>" not in result
        assert "Cell" in result

    def test_strips_small_images(self):
        """It removes tracking pixels and small icon images."""
        html = '<img src="track.png" width="1" height="1"><p>Keep</p>'
        result = _sanitize_email_html(html)
        assert "track.png" not in result
        assert "Keep" in result

    def test_keeps_large_images(self):
        """It preserves content images with large dimensions."""
        html = '<img src="photo.jpg" width="550" height="300">'
        result = _sanitize_email_html(html)
        assert "photo.jpg" in result

    def test_strips_width_height_from_images(self):
        """It removes width/height attributes from images for Kindle reflow."""
        html = '<img src="photo.jpg" width="550" height="300">'
        result = _sanitize_email_html(html)
        assert 'width="550"' not in result
        assert 'height="300"' not in result
        assert 'src="photo.jpg"' in result

    def test_preserves_lists(self):
        """It preserves list elements."""
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = _sanitize_email_html(html)
        assert "<ul>" in result
        assert "<li>" in result


class TestStripSmallImages:
    """Tests for _strip_small_images function."""

    def test_strips_1x1_tracking_pixel(self):
        html = '<img src="pixel.png" width="1" height="1">'
        assert "pixel.png" not in _strip_small_images(html)

    def test_strips_icon_sized_images(self):
        html = '<img src="icon.png" width="18" height="18">'
        assert "icon.png" not in _strip_small_images(html)

    def test_keeps_content_images(self):
        html = '<img src="photo.jpg" width="550" height="300">'
        assert "photo.jpg" in _strip_small_images(html)

    def test_keeps_images_without_dimensions(self):
        html = '<img src="photo.jpg" alt="test">'
        assert "photo.jpg" in _strip_small_images(html)

    def test_strips_when_one_dimension_present_and_small(self):
        html = '<img src="spacer.gif" width="1">'
        assert "spacer.gif" not in _strip_small_images(html)

    def test_keeps_image_with_one_large_dimension(self):
        html = '<img src="banner.jpg" width="550">'
        assert "banner.jpg" in _strip_small_images(html)


class TestStripEmailBoilerplate:
    """Tests for _strip_email_boilerplate function."""

    def test_strips_forwarded_email_subscribe(self):
        html = 'Forwarded this email? <a href="#">Subscribe here</a> for more'
        result = _strip_email_boilerplate(html)
        assert "Forwarded this email" not in result
        assert "Subscribe here" not in result

    def test_strips_read_in_app(self):
        html = '<a href="https://example.com"><span>READ IN APP</span></a>'
        result = _strip_email_boilerplate(html)
        assert "READ IN APP" not in result

    def test_strips_upgrade_to_paid(self):
        html = '<a href="#"><span>Upgrade to paid</span></a>'
        result = _strip_email_boilerplate(html)
        assert "Upgrade to paid" not in result

    def test_strips_unsubscribe(self):
        html = '<a href="https://example.com/unsub"><span>Unsubscribe</span></a>'
        result = _strip_email_boilerplate(html)
        assert "Unsubscribe" not in result

    def test_strips_zero_width_spacer_divs(self):
        html = "<div>\u200f \u00ad\u200f \u00ad</div><p>Content</p>"
        result = _strip_email_boilerplate(html)
        assert "<p>Content</p>" in result
        assert "\u200f" not in result

    def test_preserves_article_content(self):
        html = "<p>This is the actual article content about technology.</p>"
        result = _strip_email_boilerplate(html)
        assert "actual article content" in result


class TestCompressImage:
    """Tests for _compress_image function."""

    def test_resizes_large_image(self):
        """It resizes images larger than MAX_IMAGE_DIMENSION."""
        large_image = _create_test_image(2000, 1500, "RGB", "JPEG")
        data, media_type = _compress_image(large_image, "image/jpeg")

        with Image.open(BytesIO(data)) as img:
            assert img.width <= 1200
            assert img.height <= 1200
        assert media_type == "image/jpeg"

    def test_preserves_small_image_dimensions(self):
        """It does not resize small images."""
        small_image = _create_test_image(800, 600, "RGB", "JPEG")
        data, media_type = _compress_image(small_image, "image/jpeg")

        with Image.open(BytesIO(data)) as img:
            assert img.width == 800
            assert img.height == 600
        assert media_type == "image/jpeg"

    def test_handles_png_with_transparency(self):
        """It preserves PNG format for images with transparency."""
        rgba_image = _create_test_image(100, 100, "RGBA", "PNG")
        data, media_type = _compress_image(rgba_image, "image/png")

        with Image.open(BytesIO(data)) as img:
            assert img.format == "PNG"
        assert media_type == "image/png"

    def test_converts_opaque_png_to_jpeg(self):
        """It converts opaque PNG to JPEG."""
        rgb_png = _create_test_image(100, 100, "RGB", "PNG")
        data, media_type = _compress_image(rgb_png, "image/png")

        with Image.open(BytesIO(data)) as img:
            assert img.format == "JPEG"
        assert media_type == "image/jpeg"

    def test_converts_tiff_to_jpeg(self):
        """It converts TIFF to JPEG for EPUB compatibility."""
        tiff_image = _create_test_image(100, 100, "RGB", "TIFF")
        data, media_type = _compress_image(tiff_image, "image/tiff")

        with Image.open(BytesIO(data)) as img:
            assert img.format == "JPEG"
        assert media_type == "image/jpeg"

    def test_returns_original_on_invalid_data(self):
        """It returns original content for invalid image data."""
        invalid_data = b"not an image"
        data, media_type = _compress_image(invalid_data, "image/jpeg")
        assert data == invalid_data
        assert media_type == "image/jpeg"


@pytest.mark.asyncio
async def test_download_external_images_success(monkeypatch):
    """It downloads and compresses external images."""
    test_image = _create_test_image(100, 100, "RGB", "JPEG")

    async def mock_download(client, url):
        if "good" in url:
            return test_image
        return None

    monkeypatch.setattr("unhook.gmail_epub_service._download_image", mock_download)

    urls = ["https://good.com/image.jpg", "https://bad.com/missing.jpg"]
    result = await download_external_images(urls)

    assert "https://good.com/image.jpg" in result
    assert "https://bad.com/missing.jpg" not in result


@pytest.mark.asyncio
async def test_download_external_images_deduplicates(monkeypatch):
    """It deduplicates URLs before downloading."""
    download_count = 0
    test_image = _create_test_image(100, 100, "RGB", "JPEG")

    async def mock_download(client, url):
        nonlocal download_count
        download_count += 1
        return test_image

    monkeypatch.setattr("unhook.gmail_epub_service._download_image", mock_download)

    urls = [
        "https://example.com/image.jpg",
        "https://example.com/image.jpg",  # duplicate
        "https://example.com/image.jpg",  # duplicate
    ]
    await download_external_images(urls)

    assert download_count == 1


@pytest.mark.asyncio
async def test_download_external_images_empty_list():
    """It handles empty URL list."""
    result = await download_external_images([])
    assert result == {}


class TestEmailEpubBuilder:
    """Tests for EmailEpubBuilder class."""

    def test_builds_epub_with_single_email(self, tmp_path):
        """It builds EPUB from single email."""
        email = EmailContent(
            title="Test Newsletter",
            html_body="<p>Hello World</p>",
            published=datetime.now(UTC),
        )
        output_path = tmp_path / "test.epub"

        builder = EmailEpubBuilder(title="Test Digest")
        result = builder.build([email], {}, output_path)

        assert result.exists()
        assert result.suffix == ".epub"

    def test_builds_epub_with_multiple_emails(self, tmp_path):
        """It builds EPUB with multiple chapters."""
        emails = [
            EmailContent(
                title="Newsletter 1",
                html_body="<p>Content 1</p>",
                published=datetime.now(UTC),
            ),
            EmailContent(
                title="Newsletter 2",
                html_body="<p>Content 2</p>",
                published=datetime.now(UTC),
            ),
        ]
        output_path = tmp_path / "test.epub"

        builder = EmailEpubBuilder()
        result = builder.build(emails, {}, output_path)

        book = epub.read_epub(str(result))
        docs = list(book.get_items_of_type(ITEM_DOCUMENT))
        # Should have nav + 2 email chapters
        assert len(docs) >= 2

    def test_includes_inline_images(self, tmp_path):
        """It embeds inline images in EPUB."""
        test_image = _create_test_image(100, 100, "RGB", "JPEG")
        email = EmailContent(
            title="Email with Image",
            html_body='<p>Image: <img src="cid:test123"></p>',
            published=datetime.now(UTC),
            inline_images={"test123": test_image},
        )
        output_path = tmp_path / "test.epub"

        builder = EmailEpubBuilder()
        result = builder.build([email], {}, output_path)

        book = epub.read_epub(str(result))
        items = list(book.get_items())
        image_items = [i for i in items if i.media_type and "image" in i.media_type]
        assert len(image_items) >= 1

    def test_includes_external_images(self, tmp_path):
        """It embeds downloaded external images."""
        test_image = _create_test_image(100, 100, "RGB", "JPEG")
        email = EmailContent(
            title="Email with External Image",
            html_body='<img src="https://example.com/img.jpg">',
            published=datetime.now(UTC),
            external_image_urls=["https://example.com/img.jpg"],
        )
        external_images = {
            "https://example.com/img.jpg": (test_image, "image/jpeg"),
        }
        output_path = tmp_path / "test.epub"

        builder = EmailEpubBuilder()
        result = builder.build([email], external_images, output_path)

        book = epub.read_epub(str(result))
        items = list(book.get_items())
        image_items = [i for i in items if i.media_type and "image" in i.media_type]
        assert len(image_items) >= 1

    def test_sanitizes_html_content(self, tmp_path):
        """It sanitizes HTML by removing script tags and content."""
        email = EmailContent(
            title="Email with Script",
            html_body="<p>Hello</p><script>evil()</script>",
            published=datetime.now(UTC),
        )
        output_path = tmp_path / "test.epub"

        builder = EmailEpubBuilder()
        result = builder.build([email], {}, output_path)

        book = epub.read_epub(str(result))
        docs = [
            item.get_content().decode()
            for item in book.get_items_of_type(ITEM_DOCUMENT)
        ]
        combined = "\n".join(docs)
        assert "<script>" not in combined
        assert "evil" not in combined

    def test_strips_css_from_html_content(self, tmp_path):
        """It strips CSS content from email HTML, not just style tags."""
        email = EmailContent(
            title="Email with CSS",
            html_body=("<style>@media{.foo{color:red}}</style><p>Actual content</p>"),
            published=datetime.now(UTC),
        )
        output_path = tmp_path / "test.epub"

        builder = EmailEpubBuilder()
        result = builder.build([email], {}, output_path)

        book = epub.read_epub(str(result))
        docs = [
            item.get_content().decode()
            for item in book.get_items_of_type(ITEM_DOCUMENT)
        ]
        combined = "\n".join(docs)
        assert "@media" not in combined
        assert "color:red" not in combined
        assert "Actual content" in combined

    def test_creates_output_directory(self, tmp_path):
        """It creates output directory if it doesn't exist."""
        email = EmailContent(
            title="Test",
            html_body="<p>Content</p>",
            published=datetime.now(UTC),
        )
        nested_path = tmp_path / "nested" / "dir" / "test.epub"

        builder = EmailEpubBuilder()
        result = builder.build([email], {}, nested_path)

        assert result.exists()
        assert result.parent.exists()


@pytest.mark.asyncio
async def test_export_gmail_to_epub_success(tmp_path, monkeypatch):
    """It exports Gmail emails to EPUB."""
    now = datetime.now(UTC)
    raw_emails = [
        RawEmail(
            uid="1",
            subject="Newsletter 1",
            sender="news@example.com",
            date=now,
            html_body="<p>Content 1</p>",
            text_body=None,
            inline_images={},
        ),
        RawEmail(
            uid="2",
            subject="Newsletter 2",
            sender="news@example.com",
            date=now,
            html_body="<p>Content 2</p>",
            text_body=None,
            inline_images={},
        ),
    ]

    mock_service = MagicMock()
    mock_service.fetch_emails_by_label.return_value = raw_emails
    mock_service.__enter__ = MagicMock(return_value=mock_service)
    mock_service.__exit__ = MagicMock(return_value=None)

    with patch("unhook.gmail_epub_service.GmailService", return_value=mock_service):
        config = GmailConfig(
            email_address="test@gmail.com",
            app_password="password",
            label="newsletters",
        )
        result = await export_gmail_to_epub(
            config=config,
            output_dir=tmp_path,
            since_days=1,
        )

    assert result is not None
    assert result.exists()
    assert result.suffix == ".epub"


@pytest.mark.asyncio
async def test_export_gmail_to_epub_no_emails(tmp_path, monkeypatch):
    """It returns None when no emails found."""
    mock_service = MagicMock()
    mock_service.fetch_emails_by_label.return_value = []
    mock_service.__enter__ = MagicMock(return_value=mock_service)
    mock_service.__exit__ = MagicMock(return_value=None)

    with patch("unhook.gmail_epub_service.GmailService", return_value=mock_service):
        config = GmailConfig(
            email_address="test@gmail.com",
            app_password="password",
        )
        result = await export_gmail_to_epub(
            config=config,
            output_dir=tmp_path,
        )

    assert result is None


@pytest.mark.asyncio
async def test_export_gmail_to_epub_skips_failed_parsing(tmp_path, monkeypatch):
    """It skips emails that fail to parse."""
    now = datetime.now(UTC)
    raw_emails = [
        RawEmail(
            uid="1",
            subject="Good Email",
            sender="good@example.com",
            date=now,
            html_body="<p>Good content</p>",
            text_body=None,
            inline_images={},
        ),
        RawEmail(
            uid="2",
            subject="Bad Email",
            sender="bad@example.com",
            date=now,
            html_body=None,  # No content - will fail parsing
            text_body=None,
            inline_images={},
        ),
    ]

    mock_service = MagicMock()
    mock_service.fetch_emails_by_label.return_value = raw_emails
    mock_service.__enter__ = MagicMock(return_value=mock_service)
    mock_service.__exit__ = MagicMock(return_value=None)

    with patch("unhook.gmail_epub_service.GmailService", return_value=mock_service):
        config = GmailConfig(
            email_address="test@gmail.com",
            app_password="password",
        )
        result = await export_gmail_to_epub(
            config=config,
            output_dir=tmp_path,
        )

    assert result is not None
    # Should have created EPUB with just the good email
    book = epub.read_epub(str(result))
    docs = [
        item.get_content().decode() for item in book.get_items_of_type(ITEM_DOCUMENT)
    ]
    combined = "\n".join(docs)
    assert "Good content" in combined


@pytest.mark.asyncio
async def test_export_gmail_to_epub_sorts_by_date(tmp_path, monkeypatch):
    """It sorts emails by date (newest first)."""
    raw_emails = [
        RawEmail(
            uid="1",
            subject="Older Email",
            sender="news@example.com",
            date=datetime(2024, 1, 1, tzinfo=UTC),
            html_body="<p>Older</p>",
            text_body=None,
            inline_images={},
        ),
        RawEmail(
            uid="2",
            subject="Newer Email",
            sender="news@example.com",
            date=datetime(2024, 1, 15, tzinfo=UTC),
            html_body="<p>Newer</p>",
            text_body=None,
            inline_images={},
        ),
    ]

    mock_service = MagicMock()
    mock_service.fetch_emails_by_label.return_value = raw_emails
    mock_service.__enter__ = MagicMock(return_value=mock_service)
    mock_service.__exit__ = MagicMock(return_value=None)

    with patch("unhook.gmail_epub_service.GmailService", return_value=mock_service):
        config = GmailConfig(
            email_address="test@gmail.com",
            app_password="password",
        )
        result = await export_gmail_to_epub(
            config=config,
            output_dir=tmp_path,
        )

    book = epub.read_epub(str(result))
    docs = list(book.get_items_of_type(ITEM_DOCUMENT))
    # First content chapter should be newer email
    content_docs = [
        d
        for d in docs
        if "Newer" in d.get_content().decode() or "Older" in d.get_content().decode()
    ]
    first_content = content_docs[0].get_content().decode() if content_docs else ""
    assert "Newer" in first_content
