"""Tests for the Gmail IMAP service."""

import email
from datetime import UTC, datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from unhook.gmail_service import GmailConfig, GmailService, RawEmail


@pytest.fixture
def gmail_config():
    """Create a test Gmail configuration."""
    return GmailConfig(
        email_address="test@gmail.com",
        app_password="test-app-password",
        label="newsletters-kindle",
    )


@pytest.fixture
def mock_imap_connection():
    """Create a mock IMAP connection."""
    return MagicMock()


class TestGmailConfig:
    """Tests for GmailConfig dataclass."""

    def test_default_label(self):
        """It uses 'newsletters-kindle' as default label."""
        config = GmailConfig(
            email_address="test@gmail.com",
            app_password="password",
        )
        assert config.label == "newsletters-kindle"

    def test_custom_label(self):
        """It allows custom label."""
        config = GmailConfig(
            email_address="test@gmail.com",
            app_password="password",
            label="custom-label",
        )
        assert config.label == "custom-label"


class TestGmailService:
    """Tests for GmailService class."""

    def test_connect_establishes_connection(self, gmail_config):
        """It connects to Gmail IMAP server."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn

            service = GmailService(gmail_config)
            service.connect()

            mock_imap.assert_called_once_with("imap.gmail.com", 993)
            mock_conn.login.assert_called_once_with(
                "test@gmail.com", "test-app-password"
            )

    def test_disconnect_closes_connection(self, gmail_config):
        """It logs out and closes the connection."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn

            service = GmailService(gmail_config)
            service.connect()
            service.disconnect()

            mock_conn.logout.assert_called_once()

    def test_context_manager(self, gmail_config):
        """It works as a context manager."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                assert service._connection is not None

            mock_conn.logout.assert_called_once()

    def test_fetch_emails_raises_when_not_connected(self, gmail_config):
        """It raises RuntimeError when not connected."""
        service = GmailService(gmail_config)

        with pytest.raises(RuntimeError, match="Not connected"):
            service.fetch_emails_by_label()

    def test_fetch_emails_selects_label(self, gmail_config):
        """It selects the configured label."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b""])
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                service.fetch_emails_by_label()

            mock_conn.select.assert_called_once()
            call_args = mock_conn.select.call_args[0]
            assert "newsletters-kindle" in call_args[0]

    def test_fetch_emails_returns_empty_when_label_not_found(self, gmail_config):
        """It returns empty list when label selection fails."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.select.return_value = ("NO", [b"Label not found"])
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                result = service.fetch_emails_by_label()

            assert result == []

    def test_fetch_emails_returns_empty_when_no_messages(self, gmail_config):
        """It returns empty list when no messages match."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b""])
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                result = service.fetch_emails_by_label()

            assert result == []

    def test_format_label_path_simple(self, gmail_config):
        """It returns simple labels unchanged."""
        service = GmailService(gmail_config)
        assert service._format_label_path("INBOX") == "INBOX"

    def test_format_label_path_with_spaces(self, gmail_config):
        """It quotes labels with spaces."""
        service = GmailService(gmail_config)
        assert service._format_label_path("My Label") == '"My Label"'

    def test_format_label_path_with_slash(self, gmail_config):
        """It quotes labels with slashes (nested labels)."""
        service = GmailService(gmail_config)
        assert service._format_label_path("Parent/Child") == '"Parent/Child"'


class TestRawEmailParsing:
    """Tests for email parsing within GmailService."""

    def test_decode_header_plain(self, gmail_config):
        """It decodes plain ASCII headers."""
        service = GmailService(gmail_config)
        assert service._decode_header("Test Subject") == "Test Subject"

    def test_decode_header_encoded(self, gmail_config):
        """It decodes encoded headers."""
        service = GmailService(gmail_config)
        # =?utf-8?Q? encoded header
        result = service._decode_header("=?utf-8?Q?Test_Subject?=")
        assert "Test" in result and "Subject" in result

    def test_decode_header_none(self, gmail_config):
        """It handles None headers."""
        service = GmailService(gmail_config)
        assert service._decode_header(None) == ""

    def test_parse_date_valid(self, gmail_config):
        """It parses valid email date strings."""
        service = GmailService(gmail_config)
        date_str = "Mon, 01 Jan 2024 12:00:00 +0000"
        result = service._parse_date(date_str)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1

    def test_parse_date_invalid(self, gmail_config):
        """It returns current time for invalid dates."""
        service = GmailService(gmail_config)
        result = service._parse_date("invalid date")
        now = datetime.now(UTC)
        # Should be close to now
        assert abs((result - now).total_seconds()) < 60

    def test_parse_date_empty(self, gmail_config):
        """It returns current time for empty date."""
        service = GmailService(gmail_config)
        result = service._parse_date("")
        now = datetime.now(UTC)
        assert abs((result - now).total_seconds()) < 60

    def test_extract_uid_from_response(self, gmail_config):
        """It extracts UID from IMAP fetch response."""
        service = GmailService(gmail_config)
        data = [(b"1 (UID 12345 RFC822 {1000}", b"email content")]
        result = service._extract_uid(data)
        assert result == "12345"

    def test_extract_uid_missing(self, gmail_config):
        """It returns empty string when UID not found."""
        service = GmailService(gmail_config)
        data = [(b"1 (RFC822 {1000}", b"email content")]
        result = service._extract_uid(data)
        assert result == ""


class TestRawEmailDataclass:
    """Tests for RawEmail dataclass."""

    def test_raw_email_creation(self):
        """It creates RawEmail with all fields."""
        now = datetime.now(UTC)
        raw = RawEmail(
            uid="123",
            subject="Test Subject",
            sender="sender@example.com",
            date=now,
            html_body="<p>Hello</p>",
            text_body="Hello",
            inline_images={"cid1": b"image_bytes"},
        )
        assert raw.uid == "123"
        assert raw.subject == "Test Subject"
        assert raw.sender == "sender@example.com"
        assert raw.date == now
        assert raw.html_body == "<p>Hello</p>"
        assert raw.text_body == "Hello"
        assert raw.inline_images == {"cid1": b"image_bytes"}

    def test_raw_email_optional_bodies(self):
        """It allows None for html_body and text_body."""
        raw = RawEmail(
            uid="123",
            subject="Test",
            sender="test@example.com",
            date=datetime.now(UTC),
            html_body=None,
            text_body=None,
            inline_images={},
        )
        assert raw.html_body is None
        assert raw.text_body is None


def _build_mime_email(
    subject="Test Subject",
    sender="sender@example.com",
    date="Mon, 01 Jan 2024 12:00:00 +0000",
    html_body=None,
    text_body=None,
    inline_images=None,
):
    """Build a real MIME email message for testing."""
    if html_body or text_body or inline_images:
        msg = MIMEMultipart("related")
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))
        for cid, img_bytes in (inline_images or {}).items():
            img_part = MIMEImage(img_bytes, _subtype="png")
            img_part.add_header("Content-ID", f"<{cid}>")
            msg.attach(img_part)
    else:
        msg = MIMEText("fallback", "plain")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["Date"] = date
    return msg


class TestFetchSingleEmail:
    """Tests for _fetch_single_email."""

    def test_fetch_single_email_success(self, gmail_config):
        """It parses a single email from IMAP fetch response."""
        mime_msg = _build_mime_email(html_body="<p>Hello</p>")
        raw_bytes = mime_msg.as_bytes()

        service = GmailService(gmail_config)
        service._connection = MagicMock()
        service._connection.fetch.return_value = (
            "OK",
            [(b"1 (UID 42 RFC822 {1000}", raw_bytes), b")"],
        )

        result = service._fetch_single_email(b"1")

        assert result is not None
        assert result.uid == "42"
        assert result.subject == "Test Subject"
        assert result.sender == "sender@example.com"
        assert result.html_body is not None
        assert "<p>Hello</p>" in result.html_body

    def test_fetch_single_email_not_connected(self, gmail_config):
        """It returns None when not connected."""
        service = GmailService(gmail_config)
        assert service._fetch_single_email(b"1") is None

    def test_fetch_single_email_bad_status(self, gmail_config):
        """It returns None on non-OK status."""
        service = GmailService(gmail_config)
        service._connection = MagicMock()
        service._connection.fetch.return_value = ("NO", [])

        assert service._fetch_single_email(b"1") is None

    def test_fetch_single_email_no_raw_bytes(self, gmail_config):
        """It returns None when data has no tuple with bytes."""
        service = GmailService(gmail_config)
        service._connection = MagicMock()
        service._connection.fetch.return_value = ("OK", [b"not a tuple"])

        assert service._fetch_single_email(b"1") is None


class TestParseEmailMessage:
    """Tests for _parse_email_message."""

    def test_parse_multipart_html(self, gmail_config):
        """It extracts HTML body from multipart email."""
        mime_msg = _build_mime_email(
            html_body="<p>Newsletter content</p>",
            text_body="Plain text version",
        )

        service = GmailService(gmail_config)
        result = service._parse_email_message(
            "100", email.message_from_bytes(mime_msg.as_bytes())
        )

        assert result.uid == "100"
        assert result.html_body is not None
        assert "Newsletter content" in result.html_body
        assert result.text_body is not None
        assert "Plain text version" in result.text_body

    def test_parse_multipart_with_inline_images(self, gmail_config):
        """It extracts inline images by Content-ID."""
        img_bytes = b"\x89PNG\r\n\x1a\nfake"
        mime_msg = _build_mime_email(
            html_body="<img src='cid:logo123'>",
            inline_images={"logo123": img_bytes},
        )

        service = GmailService(gmail_config)
        result = service._parse_email_message(
            "101", email.message_from_bytes(mime_msg.as_bytes())
        )

        assert "logo123" in result.inline_images
        assert result.inline_images["logo123"] == img_bytes

    def test_parse_multipart_skips_attachments(self, gmail_config):
        """It skips parts with attachment disposition."""
        msg = MIMEMultipart()
        msg.attach(MIMEText("<p>Body</p>", "html"))
        attachment = MIMEText("attached file", "plain")
        attachment.add_header("Content-Disposition", "attachment", filename="file.txt")
        msg.attach(attachment)
        msg["Subject"] = "Test"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"

        service = GmailService(gmail_config)
        result = service._parse_email_message(
            "102", email.message_from_bytes(msg.as_bytes())
        )

        assert result.html_body is not None
        assert "Body" in result.html_body

    def test_parse_non_multipart_html(self, gmail_config):
        """It handles non-multipart HTML email."""
        msg = MIMEText("<p>Simple HTML</p>", "html")
        msg["Subject"] = "Simple"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"

        service = GmailService(gmail_config)
        result = service._parse_email_message(
            "103", email.message_from_bytes(msg.as_bytes())
        )

        assert result.html_body is not None
        assert "Simple HTML" in result.html_body
        assert result.text_body is None

    def test_parse_non_multipart_plain_text(self, gmail_config):
        """It handles non-multipart plain text email."""
        msg = MIMEText("Plain text only", "plain")
        msg["Subject"] = "Plain"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"

        service = GmailService(gmail_config)
        result = service._parse_email_message(
            "104", email.message_from_bytes(msg.as_bytes())
        )

        assert result.text_body is not None
        assert "Plain text only" in result.text_body
        assert result.html_body is None


class TestDecodePayload:
    """Tests for _decode_payload."""

    def test_decode_payload_utf8(self, gmail_config):
        """It decodes UTF-8 payloads."""
        part = MIMEText("Hello world", "plain", "utf-8")
        service = GmailService(gmail_config)
        result = service._decode_payload(part)
        assert "Hello world" in result

    def test_decode_payload_empty(self, gmail_config):
        """It returns empty string for empty payload."""
        part = MagicMock()
        part.get_payload.return_value = None
        part.get_content_charset.return_value = "utf-8"
        service = GmailService(gmail_config)
        assert service._decode_payload(part) == ""


class TestFetchEmailsByLabelLoop:
    """Tests for the fetch loop in fetch_emails_by_label."""

    def test_fetch_emails_returns_parsed_emails(self, gmail_config):
        """It fetches and returns parsed emails from message IDs."""
        mime_msg = _build_mime_email(html_body="<p>Newsletter</p>")
        raw_bytes = mime_msg.as_bytes()

        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"1 2"])
            mock_conn.fetch.return_value = (
                "OK",
                [(b"1 (UID 10 RFC822 {1000}", raw_bytes), b")"],
            )
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                result = service.fetch_emails_by_label(since_days=7)

            assert len(result) == 2
            assert all(isinstance(r, RawEmail) for r in result)

    def test_fetch_emails_skips_failed_messages(self, gmail_config):
        """It continues past individual email fetch failures."""
        mime_msg = _build_mime_email(html_body="<p>Good</p>")
        raw_bytes = mime_msg.as_bytes()

        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"1 2"])
            # First fetch raises, second succeeds
            mock_conn.fetch.side_effect = [
                Exception("IMAP error"),
                ("OK", [(b"2 (UID 20 RFC822 {500}", raw_bytes), b")"]),
            ]
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                result = service.fetch_emails_by_label(since_days=7)

            assert len(result) == 1

    def test_fetch_emails_skips_none_results(self, gmail_config):
        """It skips emails that parse to None."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"1"])
            mock_conn.fetch.return_value = ("NO", [])
            mock_imap.return_value = mock_conn

            with GmailService(gmail_config) as service:
                result = service.fetch_emails_by_label(since_days=7)

            assert result == []

    def test_disconnect_swallows_logout_exception(self, gmail_config):
        """It swallows exceptions during logout."""
        with patch("unhook.gmail_service.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.logout.side_effect = OSError("connection reset")
            mock_imap.return_value = mock_conn

            service = GmailService(gmail_config)
            service.connect()
            service.disconnect()  # Should not raise

            assert service._connection is None
