"""Integration tests using real newsletter .eml files as fixtures.

These tests exercise the full parsing and EPUB building pipeline
with real Substack newsletter emails to catch formatting issues
that synthetic test data might miss.
"""

import email
from pathlib import Path

import pytest
from ebooklib import ITEM_DOCUMENT, epub

from unhook.email_content import parse_raw_email
from unhook.gmail_epub_service import EmailEpubBuilder, _sanitize_email_html
from unhook.gmail_service import GmailConfig, GmailService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def gmail_service():
    """Create a GmailService for calling parse methods."""
    config = GmailConfig(email_address="test@example.com", app_password="unused")
    return GmailService(config)


@pytest.fixture
def ai_guide_msg():
    """Load the AI guide newsletter as an email.Message."""
    raw = (FIXTURES_DIR / "ai_guide_newsletter.eml").read_bytes()
    return email.message_from_bytes(raw)


@pytest.fixture
def waymo_msg():
    """Load the Waymo newsletter as an email.Message."""
    raw = (FIXTURES_DIR / "waymo_newsletter.eml").read_bytes()
    return email.message_from_bytes(raw)


class TestEmailParsing:
    """Test GmailService._parse_email_message with real emails."""

    def test_parses_ai_guide_subject(self, gmail_service, ai_guide_msg):
        """It extracts the correct subject from the AI guide newsletter."""
        result = gmail_service._parse_email_message("1", ai_guide_msg)
        assert result.subject == "A Guide to Which AI to Use in the Agentic Era"

    def test_parses_ai_guide_sender(self, gmail_service, ai_guide_msg):
        """It extracts the sender from the AI guide newsletter."""
        result = gmail_service._parse_email_message("1", ai_guide_msg)
        assert "oneusefulthing@substack.com" in result.sender

    def test_parses_ai_guide_html_body(self, gmail_service, ai_guide_msg):
        """It extracts the HTML body from a multipart newsletter."""
        result = gmail_service._parse_email_message("1", ai_guide_msg)
        assert result.html_body is not None
        assert len(result.html_body) > 1000

    def test_parses_ai_guide_text_body(self, gmail_service, ai_guide_msg):
        """It extracts the plain text fallback body."""
        result = gmail_service._parse_email_message("1", ai_guide_msg)
        assert result.text_body is not None
        assert len(result.text_body) > 100

    def test_parses_waymo_subject(self, gmail_service, waymo_msg):
        """It extracts the correct subject from the Waymo newsletter."""
        result = gmail_service._parse_email_message("2", waymo_msg)
        assert "Waymo" in result.subject

    def test_parses_waymo_sender(self, gmail_service, waymo_msg):
        """It extracts the sender from the Waymo newsletter."""
        result = gmail_service._parse_email_message("2", waymo_msg)
        assert "understandingai@substack.com" in result.sender

    def test_no_inline_images_in_substack(self, gmail_service, ai_guide_msg, waymo_msg):
        """Substack newsletters use external images, not CID inline."""
        ai = gmail_service._parse_email_message("1", ai_guide_msg)
        waymo = gmail_service._parse_email_message("2", waymo_msg)
        assert ai.inline_images == {}
        assert waymo.inline_images == {}


class TestEmailContentConversion:
    """Test parse_raw_email with real newsletter data."""

    def test_ai_guide_has_external_images(self, gmail_service, ai_guide_msg):
        """It extracts external image URLs from the HTML body."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        content = parse_raw_email(raw)
        assert content is not None
        assert len(content.external_image_urls) > 0
        assert all(url.startswith("https://") for url in content.external_image_urls)

    def test_waymo_has_external_images(self, gmail_service, waymo_msg):
        """It extracts external image URLs from the Waymo newsletter."""
        raw = gmail_service._parse_email_message("2", waymo_msg)
        content = parse_raw_email(raw)
        assert content is not None
        assert len(content.external_image_urls) > 0

    def test_title_matches_subject(self, gmail_service, ai_guide_msg):
        """It uses the email subject as the content title."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        content = parse_raw_email(raw)
        assert content.title == "A Guide to Which AI to Use in the Agentic Era"


class TestHtmlSanitization:
    """Test _sanitize_email_html with real newsletter HTML."""

    def test_strips_style_tags(self, gmail_service, ai_guide_msg):
        """It removes <style> blocks from newsletter HTML."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        sanitized = _sanitize_email_html(raw.html_body)
        assert "<style" not in sanitized

    def test_strips_script_tags(self, gmail_service, waymo_msg):
        """It removes <script> blocks from newsletter HTML."""
        raw = gmail_service._parse_email_message("2", waymo_msg)
        sanitized = _sanitize_email_html(raw.html_body)
        assert "<script" not in sanitized

    def test_strips_substack_boilerplate(self, gmail_service, ai_guide_msg):
        """It removes Substack chrome like 'Read in app'."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        sanitized = _sanitize_email_html(raw.html_body)
        assert "Read in app" not in sanitized

    def test_preserves_content(self, gmail_service, ai_guide_msg):
        """It preserves the actual newsletter content after sanitization."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        sanitized = _sanitize_email_html(raw.html_body)
        assert len(sanitized) > 1000
        assert "chatbot" in sanitized.lower()

    def test_reduces_html_size(self, gmail_service, ai_guide_msg):
        """Sanitization significantly reduces HTML size by stripping cruft."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        sanitized = _sanitize_email_html(raw.html_body)
        assert len(sanitized) < len(raw.html_body)


class TestEpubBuild:
    """Test building an EPUB from real newsletter data (no network)."""

    def test_builds_epub_from_newsletters(
        self, gmail_service, ai_guide_msg, waymo_msg, tmp_path
    ):
        """It builds a valid EPUB from real newsletter emails."""
        emails = [
            gmail_service._parse_email_message("1", ai_guide_msg),
            gmail_service._parse_email_message("2", waymo_msg),
        ]
        contents = [parse_raw_email(e) for e in emails]

        builder = EmailEpubBuilder()
        output = tmp_path / "test.epub"
        builder.build(contents, external_images={}, output_path=output)

        assert output.exists()
        assert output.stat().st_size > 0

    def test_epub_has_one_chapter_per_email(
        self, gmail_service, ai_guide_msg, waymo_msg, tmp_path
    ):
        """It creates separate chapters for each newsletter."""
        emails = [
            gmail_service._parse_email_message("1", ai_guide_msg),
            gmail_service._parse_email_message("2", waymo_msg),
        ]
        contents = [parse_raw_email(e) for e in emails]

        builder = EmailEpubBuilder()
        output = tmp_path / "test.epub"
        builder.build(contents, external_images={}, output_path=output)

        book = epub.read_epub(str(output))
        html_items = [
            item
            for item in book.get_items_of_type(ITEM_DOCUMENT)
            if item.get_name() != "nav.xhtml"
        ]
        assert len(html_items) == 2

    def test_epub_contains_newsletter_content(
        self, gmail_service, ai_guide_msg, waymo_msg, tmp_path
    ):
        """It includes actual newsletter text in the EPUB."""
        emails = [
            gmail_service._parse_email_message("1", ai_guide_msg),
            gmail_service._parse_email_message("2", waymo_msg),
        ]
        contents = [parse_raw_email(e) for e in emails]

        builder = EmailEpubBuilder()
        output = tmp_path / "test.epub"
        builder.build(contents, external_images={}, output_path=output)

        book = epub.read_epub(str(output))
        all_html = "\n".join(
            item.get_content().decode()
            for item in book.get_items_of_type(ITEM_DOCUMENT)
        )
        assert "Waymo" in all_html
        assert "chatbot" in all_html.lower()

    def test_epub_no_style_or_script_in_output(
        self, gmail_service, ai_guide_msg, tmp_path
    ):
        """It produces clean EPUB without style/script tags."""
        raw = gmail_service._parse_email_message("1", ai_guide_msg)
        content = parse_raw_email(raw)

        builder = EmailEpubBuilder()
        output = tmp_path / "test.epub"
        builder.build([content], external_images={}, output_path=output)

        book = epub.read_epub(str(output))
        all_html = "\n".join(
            item.get_content().decode()
            for item in book.get_items_of_type(ITEM_DOCUMENT)
        )
        assert "<style" not in all_html
        assert "<script" not in all_html
