"""Tests for the Gmail IMAP service."""

from datetime import UTC, datetime
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
