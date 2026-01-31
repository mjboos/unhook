"""Gmail IMAP service for fetching emails by label."""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993


@dataclass
class GmailConfig:
    """Configuration for Gmail IMAP connection."""

    email_address: str
    app_password: str
    label: str = "newsletters-kindle"


@dataclass
class RawEmail:
    """Raw email data from IMAP."""

    uid: str
    subject: str
    sender: str
    date: datetime
    html_body: str | None
    text_body: str | None
    inline_images: dict[str, bytes]  # content_id -> image bytes


class GmailService:
    """Service for fetching emails from Gmail via IMAP."""

    def __init__(self, config: GmailConfig) -> None:
        self.config = config
        self._connection: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        """Establish connection to Gmail IMAP server."""
        self._connection = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT)
        self._connection.login(self.config.email_address, self.config.app_password)
        logger.info("Connected to Gmail IMAP as %s", self.config.email_address)

    def disconnect(self) -> None:
        """Close the IMAP connection."""
        if self._connection:
            try:
                self._connection.logout()
            except Exception:  # noqa: BLE001
                pass
            self._connection = None

    def __enter__(self) -> GmailService:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()

    def fetch_emails_by_label(
        self,
        since_days: int = 1,
    ) -> list[RawEmail]:
        """Fetch emails with the configured label from the last N days.

        Args:
            since_days: Only fetch emails from the last N days.

        Returns:
            List of RawEmail objects.
        """
        if not self._connection:
            msg = "Not connected to Gmail. Call connect() first."
            raise RuntimeError(msg)

        # Select the label/folder
        label_path = self._format_label_path(self.config.label)
        status, _ = self._connection.select(label_path, readonly=True)
        if status != "OK":
            logger.warning("Could not select label %s", self.config.label)
            return []

        # Build search criteria for recent emails
        since_date = datetime.now(UTC) - timedelta(days=since_days)
        date_str = since_date.strftime("%d-%b-%Y")

        # Search using IMAP SINCE criteria
        status, data = self._connection.search(None, f"SINCE {date_str}")
        if status != "OK" or not data[0]:
            logger.info(
                "No emails found in label %s since %s", self.config.label, date_str
            )
            return []

        message_ids = data[0].split()
        logger.info("Found %d emails in label %s", len(message_ids), self.config.label)

        emails: list[RawEmail] = []
        for msg_id in message_ids:
            try:
                raw_email = self._fetch_single_email(msg_id)
                if raw_email:
                    emails.append(raw_email)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch email %s: %s", msg_id, exc)
                continue

        return emails

    def _format_label_path(self, label: str) -> str:
        """Format label name for IMAP selection.

        Gmail labels with special characters need quoting.
        Nested labels use '/' as separator.
        """
        # Gmail uses forward slash for nested labels
        # If label contains spaces or special chars, quote it
        if " " in label or "/" in label:
            return f'"{label}"'
        return label

    def _fetch_single_email(self, msg_id: bytes) -> RawEmail | None:
        """Fetch and parse a single email by message ID."""
        if not self._connection:
            return None

        status, data = self._connection.fetch(msg_id, "(RFC822 UID)")
        if status != "OK" or not data or not data[0]:
            return None

        # Extract UID from response
        uid = self._extract_uid(data)

        # Parse email content
        raw_bytes = data[0][1] if isinstance(data[0], tuple) else None
        if not raw_bytes:
            return None

        msg = email.message_from_bytes(raw_bytes)
        return self._parse_email_message(uid, msg)

    def _extract_uid(self, data: list) -> str:
        """Extract UID from IMAP fetch response."""
        # Response format: (b'1 (UID 123 RFC822 {size}', b'...')
        if data and isinstance(data[0], tuple):
            header = data[0][0]
            if isinstance(header, bytes):
                match = re.search(rb"UID (\d+)", header)
                if match:
                    return match.group(1).decode()
        return ""

    def _parse_email_message(self, uid: str, msg: Message) -> RawEmail:
        """Parse an email.message.Message into RawEmail."""
        subject = self._decode_header(msg.get("Subject", ""))
        sender = self._decode_header(msg.get("From", ""))
        date = self._parse_date(msg.get("Date", ""))

        html_body: str | None = None
        text_body: str | None = None
        inline_images: dict[str, bytes] = {}

        if msg.is_multipart():
            for part in self._walk_parts(msg):
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments (we only want inline content)
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/html" and not html_body:
                    html_body = self._decode_payload(part)
                elif content_type == "text/plain" and not text_body:
                    text_body = self._decode_payload(part)
                elif content_type.startswith("image/"):
                    # Extract inline images by Content-ID
                    content_id = part.get("Content-ID", "")
                    if content_id:
                        # Remove angle brackets from Content-ID
                        cid = content_id.strip("<>")
                        payload = part.get_payload(decode=True)
                        if payload:
                            inline_images[cid] = payload
        else:
            content_type = msg.get_content_type()
            if content_type == "text/html":
                html_body = self._decode_payload(msg)
            elif content_type == "text/plain":
                text_body = self._decode_payload(msg)

        return RawEmail(
            uid=uid,
            subject=subject,
            sender=sender,
            date=date,
            html_body=html_body,
            text_body=text_body,
            inline_images=inline_images,
        )

    def _walk_parts(self, msg: Message) -> Iterator[Message]:
        """Recursively walk all message parts."""
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            yield part

    def _decode_header(self, header: str | None) -> str:
        """Decode an email header value."""
        if not header:
            return ""

        decoded_parts = email.header.decode_header(header)
        result = []
        for content, charset in decoded_parts:
            if isinstance(content, bytes):
                result.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(content)
        return "".join(result)

    def _decode_payload(self, part: Message) -> str:
        """Decode the payload of a message part."""
        payload = part.get_payload(decode=True)
        if not payload:
            return ""

        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    def _parse_date(self, date_str: str) -> datetime:
        """Parse email date string to datetime."""
        if not date_str:
            return datetime.now(UTC)

        try:
            # email.utils.parsedate_to_datetime handles most email date formats
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(date_str)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except Exception:  # noqa: BLE001
            return datetime.now(UTC)


__all__ = ["GmailConfig", "GmailService", "RawEmail"]
