"""Substack API client and EPUB export service.

Fetches recent posts from Substack publications via their unofficial JSON
API (``/api/v1/archive`` and ``/api/v1/posts/<slug>``) and exports them as
an EPUB using the same machinery as the Gmail newsletter pipeline.  The
API's ``body_html`` is article-only content, so no email boilerplate
stripping is needed beyond the shared sanitization step.

Paywalled posts return an empty ``body_html`` unless a valid
``substack.sid`` session cookie is provided for an account subscribed to
the publication.
"""

from __future__ import annotations

import logging
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from unhook.email_content import (
    EmailContent,
    _escape_html,
    _extract_external_image_urls,
)
from unhook.gmail_epub_service import EmailEpubBuilder, download_external_images

logger = logging.getLogger(__name__)

# Browser-like TLS cipher ordering.  Cloudflare's bot heuristics challenge
# Python's default TLS fingerprint on some publications (HTTP 403 with
# ``cf-mitigated: challenge``) while accepting this ordering.
_TLS_CIPHERS = ":".join(
    [
        "ECDHE-ECDSA-AES128-GCM-SHA256",
        "ECDHE-RSA-AES128-GCM-SHA256",
        "ECDHE-ECDSA-AES256-GCM-SHA384",
        "ECDHE-RSA-AES256-GCM-SHA384",
        "ECDHE-ECDSA-CHACHA20-POLY1305",
        "ECDHE-RSA-CHACHA20-POLY1305",
        "AES128-GCM-SHA256",
        "AES256-GCM-SHA384",
    ]
)

ARCHIVE_LIMIT = 50
REQUEST_TIMEOUT = 30.0
USER_AGENT = "Mozilla/5.0 (compatible; unhook)"
SID_COOKIE_NAME = "substack.sid"


def normalize_publication_url(publication: str) -> str:
    """Resolve a publication spec to its base URL.

    Accepts a bare subdomain (``thezvi``), a domain
    (``thezvi.substack.com``, ``www.astralcodexten.com``), or a full URL,
    and returns ``https://<host>``.  The API lives on the publication's own
    host, including custom domains.
    """
    pub = publication.strip().rstrip("/")
    if not pub:
        raise ValueError("Empty publication spec")
    if "://" in pub:
        pub = pub.split("://", 1)[1]
    host = pub.split("/", 1)[0]
    if "." not in host:
        host = f"{host}.substack.com"
    return f"https://{host}"


def parse_publications(spec: str) -> list[str]:
    """Parse a comma- or newline-separated publication list into base URLs."""
    urls: list[str] = []
    for chunk in spec.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            urls.append(normalize_publication_url(chunk))
    return urls


def _parse_post_date(value: str | None) -> datetime | None:
    """Parse an ISO timestamp like ``2026-07-31T23:58:42.971Z``."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _make_client(sid: str | None = None) -> httpx.AsyncClient:
    """Create an HTTP client, optionally authenticated with a session cookie."""
    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers(_TLS_CIPHERS)
    cookies = {SID_COOKIE_NAME: sid} if sid else None
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        cookies=cookies,
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
        verify=ssl_context,
    )


async def fetch_recent_post_slugs(
    client: httpx.AsyncClient, base_url: str, since: datetime
) -> list[str]:
    """Fetch slugs of posts published on or after ``since``."""
    response = await client.get(
        f"{base_url}/api/v1/archive",
        params={"sort": "new", "limit": ARCHIVE_LIMIT},
    )
    response.raise_for_status()
    slugs: list[str] = []
    for item in response.json():
        post_date = _parse_post_date(item.get("post_date"))
        if post_date is None or post_date < since:
            continue
        if item.get("slug"):
            slugs.append(item["slug"])
    return slugs


async def fetch_post(client: httpx.AsyncClient, base_url: str, slug: str) -> dict:
    """Fetch the full JSON of a single post."""
    response = await client.get(f"{base_url}/api/v1/posts/{slug}")
    response.raise_for_status()
    return response.json()


def _publication_name(post: dict, base_url: str) -> str:
    """Derive the publication name from post JSON, falling back to the host."""
    for byline in post.get("publishedBylines") or []:
        for pub_user in byline.get("publicationUsers") or []:
            name = (pub_user.get("publication") or {}).get("name")
            if name:
                return name
    host = base_url.split("://", 1)[-1]
    return host.removeprefix("www.").removesuffix(".substack.com")


def post_to_email_content(post: dict, base_url: str) -> EmailContent | None:
    """Map Substack post JSON onto the shared newsletter content model.

    Returns None when the post has no accessible body (paywalled posts
    without authentication, or non-text posts).
    """
    body = (post.get("body_html") or "").strip()
    if not body:
        return None

    title = (post.get("title") or "").strip() or "Untitled Post"
    parts: list[str] = []
    subtitle = (post.get("subtitle") or "").strip()
    if subtitle:
        parts.append(f"<p><em>{_escape_html(subtitle)}</em></p>")
    cover = post.get("cover_image")
    if cover:
        parts.append(f'<img src="{cover}" alt=""/>')
    parts.append(body)
    html_body = "\n".join(parts)

    published = _parse_post_date(post.get("post_date")) or datetime.now(UTC)

    return EmailContent(
        title=title,
        html_body=html_body,
        published=published,
        publication=_publication_name(post, base_url),
        external_image_urls=_extract_external_image_urls(html_body),
    )


def _is_paywalled(post: dict) -> bool:
    return post.get("audience") not in (None, "everyone")


async def fetch_publication_contents(
    client: httpx.AsyncClient, base_url: str, since: datetime
) -> tuple[list[EmailContent], list[str]]:
    """Fetch recent posts of one publication as content objects.

    Returns ``(contents, skipped_paywalled_urls)``.  Fetch errors for
    individual posts are logged and skipped so one bad post cannot fail
    the digest.
    """
    contents: list[EmailContent] = []
    skipped: list[str] = []
    slugs = await fetch_recent_post_slugs(client, base_url, since)
    for slug in slugs:
        try:
            post = await fetch_post(client, base_url, slug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch %s/p/%s: %s", base_url, slug, exc)
            continue
        content = post_to_email_content(post, base_url)
        if content is None:
            if _is_paywalled(post):
                skipped.append(f"{base_url}/p/{slug}")
            continue
        contents.append(content)
    return contents, skipped


async def export_substack_to_epub(
    publications: list[str],
    output_dir: Path | str,
    since_days: int = 4,
    file_prefix: str = "substack",
    sid: str | None = None,
) -> Path | None:
    """Fetch recent posts from publications and export to EPUB.

    Args:
        publications: Base URLs of publications (see ``parse_publications``).
        output_dir: Directory to save the EPUB file.
        since_days: Only include posts from the last N days.
        file_prefix: Prefix for the output filename.
        sid: Optional ``substack.sid`` cookie to unlock paywalled posts.

    Returns:
        Path to the created EPUB file, or None if no posts found.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    since = datetime.now(UTC) - timedelta(days=since_days)

    contents: list[EmailContent] = []
    skipped_paywalled: list[str] = []
    async with _make_client(sid) as client:
        for base_url in publications:
            try:
                pub_contents, skipped = await fetch_publication_contents(
                    client, base_url, since
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch archive for %s: %s", base_url, exc)
                continue
            contents.extend(pub_contents)
            skipped_paywalled.extend(skipped)

    if skipped_paywalled:
        # Fail loud: an expired substack.sid silently empties paid posts,
        # so surface exactly which posts were dropped.
        logger.warning(
            "Skipped %d paywalled post(s) with no accessible content "
            "(check the substack.sid cookie): %s",
            len(skipped_paywalled),
            ", ".join(skipped_paywalled),
        )

    if not contents:
        logger.warning(
            "No posts found in the last %d days for %d publication(s)",
            since_days,
            len(publications),
        )
        return None

    contents.sort(key=lambda c: c.published, reverse=True)

    all_external_urls: list[str] = []
    for content in contents:
        all_external_urls.extend(content.external_image_urls)
    external_images = await download_external_images(all_external_urls)
    logger.info(
        "Downloaded %d/%d external images",
        len(external_images),
        len(set(all_external_urls)),
    )

    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"{file_prefix}-{timestamp}.epub"
    builder = EmailEpubBuilder(title=f"Substack - {timestamp}")
    return builder.build(contents, external_images, output_path)


__all__ = [
    "export_substack_to_epub",
    "fetch_post",
    "fetch_publication_contents",
    "fetch_recent_post_slugs",
    "normalize_publication_url",
    "parse_publications",
    "post_to_email_content",
]
