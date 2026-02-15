"""Tests for email content processing."""

from datetime import UTC, datetime

import pytest

from unhook.email_content import (
    EmailContent,
    parse_raw_email,
    replace_cid_references,
    replace_external_image_urls,
)
from unhook.gmail_service import RawEmail


@pytest.fixture
def sample_raw_email():
    """Create a sample RawEmail for testing."""
    return RawEmail(
        uid="123",
        subject="Test Newsletter",
        sender="newsletter@example.com",
        date=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
        html_body="<p>Hello <strong>World</strong></p>",
        text_body="Hello World",
        inline_images={},
    )


class TestEmailContent:
    """Tests for EmailContent dataclass."""

    def test_email_content_creation(self):
        """It creates EmailContent with all fields."""
        now = datetime.now(UTC)
        content = EmailContent(
            title="Test Title",
            html_body="<p>Body</p>",
            published=now,
            inline_images={"cid1": b"image"},
            external_image_urls=["https://example.com/img.jpg"],
        )
        assert content.title == "Test Title"
        assert content.html_body == "<p>Body</p>"
        assert content.published == now
        assert content.inline_images == {"cid1": b"image"}
        assert content.external_image_urls == ["https://example.com/img.jpg"]

    def test_email_content_defaults(self):
        """It uses empty defaults for images."""
        content = EmailContent(
            title="Test",
            html_body="<p>Body</p>",
            published=datetime.now(UTC),
        )
        assert content.inline_images == {}
        assert content.external_image_urls == []


class TestParseRawEmail:
    """Tests for parse_raw_email function."""

    def test_parses_html_email(self, sample_raw_email):
        """It parses email with HTML body."""
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert result.title == "Test Newsletter"
        assert "<p>Hello" in result.html_body
        assert result.published == sample_raw_email.date

    def test_uses_subject_as_title(self, sample_raw_email):
        """It uses email subject as title."""
        result = parse_raw_email(sample_raw_email)
        assert result.title == "Test Newsletter"

    def test_fallback_title_for_empty_subject(self, sample_raw_email):
        """It uses fallback title when subject is empty."""
        sample_raw_email.subject = ""
        result = parse_raw_email(sample_raw_email)
        assert result.title == "Untitled Email"

    def test_fallback_title_for_whitespace_subject(self, sample_raw_email):
        """It uses fallback title when subject is whitespace."""
        sample_raw_email.subject = "   "
        result = parse_raw_email(sample_raw_email)
        assert result.title == "Untitled Email"

    def test_uses_text_body_when_no_html(self, sample_raw_email):
        """It wraps text body in <pre> when HTML is missing."""
        sample_raw_email.html_body = None
        sample_raw_email.text_body = "Plain text content"
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert "<pre>" in result.html_body
        assert "Plain text content" in result.html_body

    def test_returns_none_when_no_content(self, sample_raw_email):
        """It returns None when email has no body content."""
        sample_raw_email.html_body = None
        sample_raw_email.text_body = None
        result = parse_raw_email(sample_raw_email)
        assert result is None

    def test_extracts_external_image_urls(self, sample_raw_email):
        """It extracts external image URLs from HTML."""
        sample_raw_email.html_body = """
        <p>Hello</p>
        <img src="https://example.com/image1.jpg" alt="Image 1">
        <img src="https://cdn.example.com/image2.png">
        """
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert "https://example.com/image1.jpg" in result.external_image_urls
        assert "https://cdn.example.com/image2.png" in result.external_image_urls

    def test_ignores_cid_images_in_external_urls(self, sample_raw_email):
        """It does not include cid: URLs in external URLs."""
        sample_raw_email.html_body = """
        <img src="cid:image001@example.com">
        <img src="https://example.com/external.jpg">
        """
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert len(result.external_image_urls) == 1
        assert "https://example.com/external.jpg" in result.external_image_urls

    def test_ignores_data_urls(self, sample_raw_email):
        """It does not include data: URLs in external URLs."""
        sample_raw_email.html_body = """
        <img src="data:image/png;base64,iVBORw0KGgo=">
        <img src="https://example.com/external.jpg">
        """
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert len(result.external_image_urls) == 1

    def test_preserves_inline_images(self, sample_raw_email):
        """It preserves inline images from raw email."""
        sample_raw_email.inline_images = {
            "image001": b"png_bytes",
            "image002": b"jpg_bytes",
        }
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert result.inline_images == sample_raw_email.inline_images

    def test_escapes_html_in_text_fallback(self, sample_raw_email):
        """It escapes HTML special chars in text body fallback."""
        sample_raw_email.html_body = None
        sample_raw_email.text_body = "<script>alert('xss')</script>"
        result = parse_raw_email(sample_raw_email)
        assert result is not None
        assert "<script>" not in result.html_body
        assert "&lt;script&gt;" in result.html_body


class TestReplaceCidReferences:
    """Tests for replace_cid_references function."""

    def test_replaces_cid_with_filename(self):
        """It replaces cid: references with local filenames."""
        html = '<img src="cid:image001@example.com" alt="Logo">'
        cid_map = {"image001@example.com": "images/inline_1.jpg"}
        result = replace_cid_references(html, cid_map)
        assert 'src="images/inline_1.jpg"' in result
        assert "cid:" not in result

    def test_replaces_multiple_cids(self):
        """It replaces multiple cid: references."""
        html = """
        <img src="cid:img1">
        <img src="cid:img2">
        """
        cid_map = {
            "img1": "images/1.jpg",
            "img2": "images/2.png",
        }
        result = replace_cid_references(html, cid_map)
        assert 'src="images/1.jpg"' in result
        assert 'src="images/2.png"' in result

    def test_keeps_unmatched_cids(self):
        """It keeps cid: references without mapping."""
        html = '<img src="cid:unknown">'
        cid_map = {"other": "images/other.jpg"}
        result = replace_cid_references(html, cid_map)
        assert 'src="cid:unknown"' in result

    def test_handles_single_quotes(self):
        """It handles cid: in single quotes."""
        html = "<img src='cid:image001'>"
        cid_map = {"image001": "images/1.jpg"}
        result = replace_cid_references(html, cid_map)
        assert 'src="images/1.jpg"' in result

    def test_handles_empty_html(self):
        """It handles empty HTML."""
        result = replace_cid_references("", {"cid": "file"})
        assert result == ""

    def test_handles_empty_mapping(self):
        """It handles empty mapping."""
        html = '<img src="cid:test">'
        result = replace_cid_references(html, {})
        assert result == html


class TestReplaceExternalImageUrls:
    """Tests for replace_external_image_urls function."""

    def test_replaces_url_with_filename(self):
        """It replaces external URLs with local filenames."""
        html = '<img src="https://example.com/image.jpg">'
        url_map = {"https://example.com/image.jpg": "images/ext_1.jpg"}
        result = replace_external_image_urls(html, url_map)
        assert 'src="images/ext_1.jpg"' in result
        assert "https://example.com" not in result

    def test_replaces_multiple_urls(self):
        """It replaces multiple external URLs."""
        html = """
        <img src="https://a.com/1.jpg">
        <img src="https://b.com/2.png">
        """
        url_map = {
            "https://a.com/1.jpg": "images/1.jpg",
            "https://b.com/2.png": "images/2.png",
        }
        result = replace_external_image_urls(html, url_map)
        assert "images/1.jpg" in result
        assert "images/2.png" in result

    def test_keeps_unmatched_urls(self):
        """It keeps URLs without mapping."""
        html = '<img src="https://unknown.com/img.jpg">'
        url_map = {"https://other.com/img.jpg": "images/other.jpg"}
        result = replace_external_image_urls(html, url_map)
        assert "https://unknown.com/img.jpg" in result

    def test_handles_empty_html(self):
        """It handles empty HTML."""
        result = replace_external_image_urls("", {"url": "file"})
        assert result == ""

    def test_handles_empty_mapping(self):
        """It handles empty mapping."""
        html = '<img src="https://example.com/img.jpg">'
        result = replace_external_image_urls(html, {})
        assert result == html
