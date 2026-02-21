"""Service for exporting Gmail emails to EPUB."""

from __future__ import annotations

import logging
import mimetypes
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import bleach
import httpx
from ebooklib import epub
from PIL import Image, UnidentifiedImageError

from unhook.email_content import (
    EmailContent,
    parse_raw_email,
    replace_cid_references,
    replace_external_image_urls,
)
from unhook.gmail_service import GmailConfig, GmailService

logger = logging.getLogger(__name__)

MAX_IMAGE_DIMENSION = 1200
JPEG_QUALITY = 65

# HTML tags allowed in email content for EPUB
# NOTE: table/tbody/thead/tr/td/th are intentionally excluded.
# Newsletter emails use deeply nested table layouts for positioning which
# Kindle cannot reflow, causing it to fall back to fixed-layout (image)
# rendering.  With strip=True bleach removes the tags but keeps text content.
ALLOWED_TAGS = [
    "a",
    "abbr",
    "acronym",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "u",
    "ul",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt"],
}

# Pixel threshold: images with *all* stated dimensions at or below this value
# are stripped (tracking pixels, social-action icons, tiny spacer GIFs, …).
_SMALL_IMAGE_PX = 50


def _strip_non_body_content(html: str) -> str:
    """Remove <head>, <style>, and <script> blocks including their content.

    ``bleach.clean`` with ``strip=True`` removes disallowed *tags* but keeps
    the text content inside them.  For ``<style>`` and ``<script>`` elements
    that text is CSS / JS which should never appear as visible content in the
    EPUB.  This helper removes both the tags and their inner text *before*
    bleach processes the remaining markup.
    """
    # Remove <head>…</head> (contains <title>, <style>, <meta>, etc.)
    html = re.sub(r"<head[\s>].*?</head>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all <style>…</style> blocks (may appear outside <head>)
    html = re.sub(r"<style[\s>].*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all <script>…</script> blocks
    html = re.sub(
        r"<script[\s>].*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    return html


def _strip_small_images(html: str, max_size: int = _SMALL_IMAGE_PX) -> str:
    """Remove ``<img>`` tags whose explicit dimensions are tiny.

    Targets tracking pixels (1x1), social-action icons (18x18 / 36x36),
    and similar decorative images that add no value in an EPUB.
    Images without explicit width/height attributes are kept.
    """

    def _replace(match: re.Match) -> str:
        tag = match.group(0)
        w_match = re.search(r'width=["\']?(\d+)', tag)
        h_match = re.search(r'height=["\']?(\d+)', tag)
        if not w_match and not h_match:
            return tag  # no dimensions → keep
        w = int(w_match.group(1)) if w_match else 0
        h = int(h_match.group(1)) if h_match else 0
        if max(w, h) <= max_size:
            return ""
        return tag

    return re.sub(r"<img\b[^>]*/?>", _replace, html, flags=re.IGNORECASE)


_BOILERPLATE_LINK_TEXTS = [
    "read in app",
    "upgrade to paid",
    "start writing",
    "unsubscribe",
]


def _strip_email_boilerplate(html: str) -> str:
    """Remove common newsletter boilerplate that is not article content.

    Targets Substack-style chrome (action buttons, subscribe prompts, footers)
    but is broad enough to catch similar patterns from other providers.
    """
    # Zero-width / soft-hyphen spacer divs used as preheader padding
    html = re.sub(
        r"<div>[\u200b-\u200f\u00ad\ufeff\s\u034f]+</div>",
        "",
        html,
    )
    # "Forwarded this email? Subscribe here for more"
    # The span limit is generous because Substack embeds very long redirect URLs.
    html = re.sub(
        r"Forwarded this email\?.{0,3000}?for more",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove individual <a>…</a> tags whose text contains boilerplate.
    # The inner pattern (?:(?!</a>).)* matches one <a> without crossing its
    # closing tag, avoiding the greedy-match-across-document pitfall.
    def _check_link(match: re.Match) -> str:
        content_lower = match.group(0).lower()
        for text in _BOILERPLATE_LINK_TEXTS:
            if text in content_lower:
                return ""
        return match.group(0)

    html = re.sub(
        r"<a\b[^>]*>(?:(?!</a>).)*?</a>",
        _check_link,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove empty <a> tags left after image/icon stripping
    html = re.sub(r"<a\b[^>]*>\s*</a>", "", html, flags=re.IGNORECASE)

    return html


def _sanitize_email_html(html: str) -> str:
    """Sanitize HTML content for EPUB embedding."""
    html = _strip_non_body_content(html)
    html = _strip_small_images(html)
    html = _strip_email_boilerplate(html)
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    )


def _compress_image(content: bytes, media_type: str | None) -> tuple[bytes, str]:
    """Compress image for EPUB embedding.

    Returns a ``(bytes, media_type)`` tuple.  The output is always in an
    EPUB-compatible format (JPEG, PNG, or GIF).
    """
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))

            output = BytesIO()
            has_transparency = image.mode in {"RGBA", "LA"} or (
                "transparency" in image.info
            )

            if has_transparency:
                image.save(output, format="PNG", optimize=True)
                return output.getvalue(), "image/png"

            image.convert("RGB").save(
                output, format="JPEG", quality=JPEG_QUALITY, optimize=True
            )
            return output.getvalue(), "image/jpeg"

    except (UnidentifiedImageError, OSError) as exc:
        logger.warning("Failed to compress image: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error compressing image: %s", exc)

    return content, media_type or "image/jpeg"


async def _download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Download a single image from URL."""
    try:
        response = await client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to download image %s: %s", url, exc)
        return None


async def download_external_images(
    urls: list[str],
) -> dict[str, tuple[bytes, str]]:
    """Download external images concurrently.

    Args:
        urls: List of image URLs to download.

    Returns:
        Mapping from URL to ``(image_bytes, media_type)`` tuples.
    """
    results: dict[str, tuple[bytes, str]] = {}
    unique_urls = list(set(url for url in urls if url))

    if not unique_urls:
        return results

    async with httpx.AsyncClient() as client:
        for url in unique_urls:
            content = await _download_image(client, url)
            if content:
                media_type, _ = mimetypes.guess_type(url)
                results[url] = _compress_image(content, media_type)

    return results


def _guess_media_type(url_or_cid: str) -> str:
    """Guess media type from URL or content ID."""
    media_type, _ = mimetypes.guess_type(url_or_cid)
    return media_type or "image/jpeg"


def _generate_image_filename(prefix: str, index: int, media_type: str) -> str:
    """Generate a unique filename for an image."""
    extension = mimetypes.guess_extension(media_type) or ".jpg"
    return f"images/{prefix}_{index}{extension}"


class EmailEpubBuilder:
    """Build EPUB files from email content."""

    def __init__(self, title: str = "Newsletter Digest", language: str = "en") -> None:
        self.title = title
        self.language = language

    def build(
        self,
        emails: list[EmailContent],
        external_images: dict[str, tuple[bytes, str]],
        output_path: Path,
    ) -> Path:
        """Build an EPUB file from email content.

        Args:
            emails: List of EmailContent to include.
            external_images: Mapping of URL to ``(bytes, media_type)`` tuples.
            output_path: Path to write the EPUB file.

        Returns:
            Path to the created EPUB file.
        """
        book = epub.EpubBook()
        book.set_identifier("unhook-gmail-export")
        book.set_title(self.title)
        book.set_language(self.language)

        chapters: list[epub.EpubHtml] = []
        image_counter = 0

        for idx, email_content in enumerate(emails, start=1):
            chapter_title = email_content.title[:80]
            chapter_filename = f"email_{idx}.xhtml"

            # Process images for this email
            html_body = email_content.html_body
            cid_to_filename: dict[str, str] = {}
            url_to_filename: dict[str, str] = {}

            # Handle inline images (CID references)
            for cid, image_bytes in email_content.inline_images.items():
                image_counter += 1
                guessed_type = _guess_media_type(cid)
                compressed, media_type = _compress_image(image_bytes, guessed_type)
                filename = _generate_image_filename("inline", image_counter, media_type)

                image_item = epub.EpubItem(
                    uid=f"img_{image_counter}",
                    file_name=filename,
                    media_type=media_type,
                    content=compressed,
                )
                book.add_item(image_item)
                cid_to_filename[cid] = filename

            # Handle external images
            for url in email_content.external_image_urls:
                if url in external_images:
                    image_counter += 1
                    image_data, media_type = external_images[url]
                    filename = _generate_image_filename(
                        "ext", image_counter, media_type
                    )

                    image_item = epub.EpubItem(
                        uid=f"img_{image_counter}",
                        file_name=filename,
                        media_type=media_type,
                        content=image_data,
                    )
                    book.add_item(image_item)
                    url_to_filename[url] = filename

            # Replace image references in HTML
            html_body = replace_cid_references(html_body, cid_to_filename)
            html_body = replace_external_image_urls(html_body, url_to_filename)

            # Sanitize HTML
            sanitized_html = _sanitize_email_html(html_body)

            # Create chapter
            chapter = epub.EpubHtml(
                title=chapter_title,
                file_name=chapter_filename,
                lang=self.language,
            )
            chapter.content = (
                f"<h1>{bleach.clean(chapter_title)}</h1>\n{sanitized_html}"
            )

            book.add_item(chapter)
            chapters.append(chapter)

        # Build table of contents and spine
        book.toc = [(epub.Section("Newsletters"), chapters)]
        book.spine = ["nav", *chapters]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # Write EPUB
        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), book)

        logger.info("EPUB created at %s with %d emails", output_path, len(emails))
        return output_path


async def export_gmail_to_epub(
    config: GmailConfig,
    output_dir: Path | str,
    since_days: int = 1,
    file_prefix: str = "newsletters",
) -> Path | None:
    """Fetch emails from Gmail and export to EPUB.

    Args:
        config: Gmail configuration.
        output_dir: Directory to save the EPUB file.
        since_days: Only include emails from the last N days.
        file_prefix: Prefix for the output filename.

    Returns:
        Path to the created EPUB file, or None if no emails found.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Fetch emails from Gmail
    with GmailService(config) as service:
        raw_emails = service.fetch_emails_by_label(since_days=since_days)

    if not raw_emails:
        logger.warning(
            "No emails found in label '%s' from the last %d days",
            config.label,
            since_days,
        )
        return None

    # Parse emails to content
    email_contents: list[EmailContent] = []
    for raw in raw_emails:
        try:
            content = parse_raw_email(raw)
            if content:
                email_contents.append(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse email '%s': %s", raw.subject, exc)
            continue

    if not email_contents:
        logger.warning("No emails could be parsed successfully")
        return None

    # Sort by date (newest first)
    email_contents.sort(key=lambda e: e.published, reverse=True)

    # Collect all external image URLs
    all_external_urls: list[str] = []
    for content in email_contents:
        all_external_urls.extend(content.external_image_urls)

    # Download external images
    external_images = await download_external_images(all_external_urls)
    logger.info(
        "Downloaded %d/%d external images",
        len(external_images),
        len(set(all_external_urls)),
    )

    # Build EPUB
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"{file_prefix}-{timestamp}.epub"

    builder = EmailEpubBuilder(title=f"Newsletters - {timestamp}")
    return builder.build(email_contents, external_images, output_path)


__all__ = ["EmailEpubBuilder", "export_gmail_to_epub"]
