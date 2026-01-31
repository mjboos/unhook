"""Email content processing for EPUB creation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unhook.gmail_service import RawEmail

logger = logging.getLogger(__name__)

# Regex to find external image URLs in HTML
_IMG_SRC_PATTERN = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)

# Regex to find cid: references in HTML (inline images)
_CID_PATTERN = re.compile(r'src=["\']cid:([^"\']+)["\']', re.IGNORECASE)


@dataclass
class EmailContent:
    """Processed email content ready for EPUB creation."""

    title: str
    html_body: str
    published: datetime
    inline_images: dict[str, bytes] = field(default_factory=dict)
    external_image_urls: list[str] = field(default_factory=list)


def parse_raw_email(raw: RawEmail) -> EmailContent | None:
    """Convert a RawEmail to EmailContent for EPUB generation.

    Args:
        raw: RawEmail from Gmail service.

    Returns:
        EmailContent ready for EPUB, or None if email cannot be processed.
    """
    # Use HTML body if available, fall back to text
    html_body = raw.html_body
    if not html_body:
        if raw.text_body:
            # Wrap plain text in basic HTML
            escaped_text = _escape_html(raw.text_body)
            html_body = f"<pre>{escaped_text}</pre>"
        else:
            logger.warning("Email %s has no content", raw.uid)
            return None

    # Extract external image URLs
    external_urls = _extract_external_image_urls(html_body)

    # Use subject as title, with fallback
    title = raw.subject.strip() if raw.subject else ""
    if not title:
        title = "Untitled Email"

    return EmailContent(
        title=title,
        html_body=html_body,
        published=raw.date,
        inline_images=raw.inline_images,
        external_image_urls=external_urls,
    )


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _extract_external_image_urls(html: str) -> list[str]:
    """Extract URLs of external images from HTML content.

    Only extracts http/https URLs, not cid: or data: URLs.
    """
    urls: list[str] = []
    for match in _IMG_SRC_PATTERN.finditer(html):
        src = match.group(1)
        if src.startswith(("http://", "https://")):
            urls.append(src)
    return urls


def replace_cid_references(html: str, cid_to_filename: dict[str, str]) -> str:
    """Replace cid: references in HTML with local filenames.

    Args:
        html: HTML content with cid: references.
        cid_to_filename: Mapping from content ID to EPUB filename.

    Returns:
        HTML with cid: replaced by local filenames.
    """

    def replace_cid(match: re.Match) -> str:
        cid = match.group(1)
        filename = cid_to_filename.get(cid)
        if filename:
            return f'src="{filename}"'
        # Keep original if no mapping found
        return match.group(0)

    return _CID_PATTERN.sub(replace_cid, html)


def replace_external_image_urls(html: str, url_to_filename: dict[str, str]) -> str:
    """Replace external image URLs in HTML with local filenames.

    Args:
        html: HTML content with external image URLs.
        url_to_filename: Mapping from URL to EPUB filename.

    Returns:
        HTML with external URLs replaced by local filenames.
    """
    for url, filename in url_to_filename.items():
        html = html.replace(url, filename)
    return html


__all__ = [
    "EmailContent",
    "parse_raw_email",
    "replace_cid_references",
    "replace_external_image_urls",
]
