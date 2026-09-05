"""Tests for the Substack EPUB export service."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from ebooklib import ITEM_DOCUMENT, epub

from unhook.substack_service import (
    _make_client,
    _parse_post_date,
    _parse_subscriptions,
    _publication_name,
    export_substack_to_epub,
    fetch_authenticated_subscriptions,
    fetch_post,
    fetch_public_subscriptions,
    fetch_publication_contents,
    fetch_recent_post_slugs,
    format_publications_value,
    list_subscriptions,
    normalize_handle,
    normalize_publication_url,
    parse_publications,
    post_to_email_content,
    publication_base_url,
)

BASE_URL = "https://example.substack.com"


def recent_iso(days_ago: int = 1) -> str:
    """Return an ISO timestamp relative to now.

    Export tests derive their cutoff from ``since_days`` relative to the
    current date, so fixture dates must be relative too — hardcoded dates
    silently fall outside the window as time passes.
    """
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def make_post_json(
    slug: str = "test-post",
    title: str = "Test Post",
    body_html: str = "<p>Hello world</p>",
    audience: str = "everyone",
    **overrides,
) -> dict:
    """Build a minimal Substack post JSON payload."""
    post = {
        "slug": slug,
        "title": title,
        "subtitle": "",
        "body_html": body_html,
        "audience": audience,
        "post_date": "2026-08-01T12:00:00.000Z",
        "cover_image": None,
        "publishedBylines": [
            {
                "name": "Author Name",
                "publicationUsers": [{"publication": {"name": "Example Publication"}}],
            }
        ],
    }
    post.update(overrides)
    return post


class TestNormalizePublicationUrl:
    """Tests for normalize_publication_url."""

    def test_bare_subdomain(self):
        """It expands a bare subdomain to a substack.com URL."""
        assert normalize_publication_url("thezvi") == "https://thezvi.substack.com"

    def test_domain(self):
        """It passes through a domain unchanged."""
        result = normalize_publication_url("www.astralcodexten.com")
        assert result == "https://www.astralcodexten.com"

    def test_full_url(self):
        """It strips scheme and path from a full URL."""
        result = normalize_publication_url("https://thezvi.substack.com/p/some-post")
        assert result == "https://thezvi.substack.com"

    def test_trailing_slash(self):
        """It strips trailing slashes."""
        result = normalize_publication_url("thezvi.substack.com/")
        assert result == "https://thezvi.substack.com"

    def test_whitespace(self):
        """It strips surrounding whitespace."""
        assert normalize_publication_url("  thezvi ") == "https://thezvi.substack.com"

    def test_empty_raises(self):
        """It raises for an empty spec."""
        with pytest.raises(ValueError):
            normalize_publication_url("   ")


class TestParsePublications:
    """Tests for parse_publications."""

    def test_comma_separated(self):
        """It parses a comma-separated list."""
        result = parse_publications("thezvi, www.astralcodexten.com")
        assert result == [
            "https://thezvi.substack.com",
            "https://www.astralcodexten.com",
        ]

    def test_newline_separated(self):
        """It accepts newline separators."""
        result = parse_publications("thezvi\nastralcodexten")
        assert result == [
            "https://thezvi.substack.com",
            "https://astralcodexten.substack.com",
        ]

    def test_skips_empty_entries(self):
        """It skips empty entries between separators."""
        assert parse_publications("thezvi,,  ,") == ["https://thezvi.substack.com"]

    def test_empty_string(self):
        """It returns an empty list for an empty string."""
        assert parse_publications("") == []


class TestParsePostDate:
    """Tests for _parse_post_date."""

    def test_iso_with_z(self):
        """It parses ISO timestamps with Z suffix."""
        result = _parse_post_date("2026-07-31T23:58:42.971Z")
        assert result == datetime(2026, 7, 31, 23, 58, 42, 971000, tzinfo=UTC)

    def test_naive_gets_utc(self):
        """It assumes UTC for naive timestamps."""
        result = _parse_post_date("2026-07-31T23:58:42")
        assert result is not None
        assert result.tzinfo is UTC

    def test_invalid_returns_none(self):
        """It returns None for unparseable values."""
        assert _parse_post_date("not-a-date") is None

    def test_none_returns_none(self):
        """It returns None for missing values."""
        assert _parse_post_date(None) is None


class TestPublicationName:
    """Tests for _publication_name."""

    def test_from_bylines(self):
        """It reads the publication name from the byline JSON."""
        assert _publication_name(make_post_json(), BASE_URL) == "Example Publication"

    def test_fallback_to_host(self):
        """It falls back to the host without www/substack.com noise."""
        post = make_post_json(publishedBylines=[])
        assert _publication_name(post, "https://thezvi.substack.com") == "thezvi"
        assert (
            _publication_name(post, "https://www.astralcodexten.com")
            == "astralcodexten.com"
        )

    def test_handles_missing_nested_fields(self):
        """It tolerates bylines without publication info."""
        post = make_post_json(
            publishedBylines=[{"name": "A", "publicationUsers": [{}]}]
        )
        assert _publication_name(post, BASE_URL) == "example"


class TestPostToEmailContent:
    """Tests for post_to_email_content."""

    def test_maps_fields(self):
        """It maps title, body, date, and publication."""
        content = post_to_email_content(make_post_json(), BASE_URL)
        assert content is not None
        assert content.title == "Test Post"
        assert "<p>Hello world</p>" in content.html_body
        assert content.publication == "Example Publication"
        assert content.published == datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        assert content.inline_images == {}

    def test_empty_body_returns_none(self):
        """It returns None for posts without accessible content."""
        assert post_to_email_content(make_post_json(body_html=""), BASE_URL) is None
        assert post_to_email_content(make_post_json(body_html="  "), BASE_URL) is None

    def test_subtitle_prepended_and_escaped(self):
        """It prepends the subtitle with HTML escaped."""
        post = make_post_json(subtitle="A <b>bold</b> claim")
        content = post_to_email_content(post, BASE_URL)
        assert content is not None
        assert "A &lt;b&gt;bold&lt;/b&gt; claim" in content.html_body
        assert content.html_body.index("claim") < content.html_body.index("Hello")

    def test_cover_image_prepended(self):
        """It prepends the cover image so it gets embedded."""
        post = make_post_json(cover_image="https://img.example.com/cover.png")
        content = post_to_email_content(post, BASE_URL)
        assert content is not None
        assert '<img src="https://img.example.com/cover.png"' in content.html_body
        assert "https://img.example.com/cover.png" in content.external_image_urls

    def test_extracts_body_image_urls(self):
        """It collects external image URLs from the body."""
        body = '<p>Hi</p><img src="https://img.example.com/a.jpg">'
        content = post_to_email_content(make_post_json(body_html=body), BASE_URL)
        assert content is not None
        assert content.external_image_urls == ["https://img.example.com/a.jpg"]

    def test_untitled_fallback(self):
        """It falls back to a placeholder title."""
        content = post_to_email_content(make_post_json(title=""), BASE_URL)
        assert content is not None
        assert content.title == "Untitled Post"

    def test_bad_date_falls_back_to_now(self):
        """It falls back to the current time for unparseable dates."""
        content = post_to_email_content(make_post_json(post_date="bad"), BASE_URL)
        assert content is not None
        assert content.published.tzinfo is not None


def _mock_client(responses: dict[str, object]) -> MagicMock:
    """Build a mock httpx client mapping URL substrings to JSON payloads."""

    async def get(url, params=None):
        for fragment, payload in responses.items():
            if fragment in url:
                response = MagicMock()
                response.json.return_value = payload
                response.raise_for_status.return_value = None
                return response
        raise AssertionError(f"Unexpected URL {url}")

    client = MagicMock()
    client.get = AsyncMock(side_effect=get)
    return client


class TestFetchRecentPostSlugs:
    """Tests for fetch_recent_post_slugs."""

    @pytest.mark.asyncio
    async def test_filters_by_date(self):
        """It only returns slugs published on or after the cutoff."""
        archive = [
            {"slug": "new-post", "post_date": "2026-08-05T10:00:00.000Z"},
            {"slug": "old-post", "post_date": "2026-07-01T10:00:00.000Z"},
            {"slug": "no-date"},
        ]
        client = _mock_client({"/api/v1/archive": archive})
        since = datetime(2026, 8, 1, tzinfo=UTC)
        slugs = await fetch_recent_post_slugs(client, BASE_URL, since)
        assert slugs == ["new-post"]

    @pytest.mark.asyncio
    async def test_fetch_post(self):
        """It fetches a single post's JSON."""
        post = make_post_json()
        client = _mock_client({"/api/v1/posts/test-post": post})
        result = await fetch_post(client, BASE_URL, "test-post")
        assert result["title"] == "Test Post"


class TestFetchPublicationContents:
    """Tests for fetch_publication_contents."""

    @pytest.mark.asyncio
    async def test_returns_contents(self):
        """It fetches and maps posts within the window."""
        archive = [{"slug": "test-post", "post_date": "2026-08-01T12:00:00.000Z"}]
        client = _mock_client(
            {
                "/api/v1/archive": archive,
                "/api/v1/posts/test-post": make_post_json(),
            }
        )
        since = datetime(2026, 7, 30, tzinfo=UTC)
        contents, skipped = await fetch_publication_contents(client, BASE_URL, since)
        assert len(contents) == 1
        assert contents[0].title == "Test Post"
        assert skipped == []

    @pytest.mark.asyncio
    async def test_collects_paywalled_skips(self):
        """It records paywalled posts that came back empty."""
        archive = [{"slug": "paid-post", "post_date": "2026-08-01T12:00:00.000Z"}]
        client = _mock_client(
            {
                "/api/v1/archive": archive,
                "/api/v1/posts/paid-post": make_post_json(
                    slug="paid-post", body_html="", audience="only_paid"
                ),
            }
        )
        since = datetime(2026, 7, 30, tzinfo=UTC)
        contents, skipped = await fetch_publication_contents(client, BASE_URL, since)
        assert contents == []
        assert skipped == [f"{BASE_URL}/p/paid-post"]

    @pytest.mark.asyncio
    async def test_skips_empty_free_posts_silently(self):
        """It drops free posts with empty bodies without flagging them."""
        archive = [{"slug": "audio-post", "post_date": "2026-08-01T12:00:00.000Z"}]
        client = _mock_client(
            {
                "/api/v1/archive": archive,
                "/api/v1/posts/audio-post": make_post_json(
                    slug="audio-post", body_html=""
                ),
            }
        )
        since = datetime(2026, 7, 30, tzinfo=UTC)
        contents, skipped = await fetch_publication_contents(client, BASE_URL, since)
        assert contents == []
        assert skipped == []

    @pytest.mark.asyncio
    async def test_continues_after_post_fetch_error(self):
        """It skips posts whose fetch fails and keeps going."""
        archive = [
            {"slug": "broken", "post_date": "2026-08-01T12:00:00.000Z"},
            {"slug": "test-post", "post_date": "2026-08-01T12:00:00.000Z"},
        ]

        async def get(url, params=None):
            if "/api/v1/archive" in url:
                response = MagicMock()
                response.json.return_value = archive
                response.raise_for_status.return_value = None
                return response
            if "broken" in url:
                raise RuntimeError("boom")
            response = MagicMock()
            response.json.return_value = make_post_json()
            response.raise_for_status.return_value = None
            return response

        client = MagicMock()
        client.get = AsyncMock(side_effect=get)
        since = datetime(2026, 7, 30, tzinfo=UTC)
        contents, _ = await fetch_publication_contents(client, BASE_URL, since)
        assert len(contents) == 1


class TestMakeClient:
    """Tests for _make_client."""

    @pytest.mark.asyncio
    async def test_sets_sid_cookie(self):
        """It attaches the substack.sid cookie when provided."""
        async with _make_client(sid="secret-cookie") as client:
            assert client.cookies.get("substack.sid") == "secret-cookie"

    @pytest.mark.asyncio
    async def test_no_cookie_by_default(self):
        """It sets no cookies without a sid."""
        async with _make_client() as client:
            assert len(client.cookies) == 0


class TestExportSubstackToEpub:
    """Tests for export_substack_to_epub."""

    @pytest.mark.asyncio
    async def test_creates_epub(self, tmp_path, monkeypatch):
        """It builds an EPUB from fetched posts."""
        archive = [{"slug": "test-post", "post_date": recent_iso()}]
        client = _mock_client(
            {
                "/api/v1/archive": archive,
                "/api/v1/posts/test-post": make_post_json(),
            }
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        result = await export_substack_to_epub(
            publications=[BASE_URL],
            output_dir=tmp_path,
            since_days=30,
        )

        assert result is not None
        assert result.exists()
        book = epub.read_epub(str(result))
        docs = [
            item
            for item in book.get_items_of_type(ITEM_DOCUMENT)
            if "email_" in item.get_name()
        ]
        assert len(docs) == 1
        assert b"Hello world" in docs[0].get_content()

    @pytest.mark.asyncio
    async def test_no_posts_returns_none(self, tmp_path, monkeypatch):
        """It returns None when nothing is found."""
        client = _mock_client({"/api/v1/archive": []})
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        result = await export_substack_to_epub(
            publications=[BASE_URL], output_dir=tmp_path
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_continues_after_archive_error(self, tmp_path, monkeypatch, caplog):
        """One failing publication does not fail the digest."""
        archive = [{"slug": "test-post", "post_date": recent_iso()}]

        async def get(url, params=None):
            if "bad.substack.com" in url:
                raise RuntimeError("cloudflare challenge")
            response = MagicMock()
            response.raise_for_status.return_value = None
            if "/api/v1/archive" in url:
                response.json.return_value = archive
            else:
                response.json.return_value = make_post_json()
            return response

        client = MagicMock()
        client.get = AsyncMock(side_effect=get)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        result = await export_substack_to_epub(
            publications=["https://bad.substack.com", BASE_URL],
            output_dir=tmp_path,
            since_days=30,
        )
        assert result is not None
        assert "Failed to fetch archive" in caplog.text

    @pytest.mark.asyncio
    async def test_warns_on_paywalled_skips(self, tmp_path, monkeypatch, caplog):
        """It logs a loud warning listing skipped paywalled posts."""
        archive = [
            {"slug": "free-post", "post_date": recent_iso()},
            {"slug": "paid-post", "post_date": recent_iso()},
        ]
        client = _mock_client(
            {
                "/api/v1/archive": archive,
                "/api/v1/posts/free-post": make_post_json(slug="free-post"),
                "/api/v1/posts/paid-post": make_post_json(
                    slug="paid-post", body_html="", audience="only_paid"
                ),
            }
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        result = await export_substack_to_epub(
            publications=[BASE_URL], output_dir=tmp_path, since_days=30
        )
        assert result is not None
        assert "paywalled" in caplog.text
        assert "paid-post" in caplog.text

    @pytest.mark.asyncio
    async def test_sorts_newest_first(self, tmp_path, monkeypatch):
        """It orders chapters newest first."""
        now = datetime.now(UTC)
        archive = [
            {"slug": "older", "post_date": (now - timedelta(days=2)).isoformat()},
            {"slug": "newer", "post_date": (now - timedelta(days=1)).isoformat()},
        ]
        client = _mock_client(
            {
                "/api/v1/archive": archive,
                "/api/v1/posts/older": make_post_json(
                    slug="older",
                    title="Older Post",
                    post_date=(now - timedelta(days=2)).isoformat(),
                ),
                "/api/v1/posts/newer": make_post_json(
                    slug="newer",
                    title="Newer Post",
                    post_date=(now - timedelta(days=1)).isoformat(),
                ),
            }
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        result = await export_substack_to_epub(
            publications=[BASE_URL], output_dir=tmp_path, since_days=30
        )
        assert result is not None
        book = epub.read_epub(str(result))
        first_chapter = next(
            item
            for item in book.get_items_of_type(ITEM_DOCUMENT)
            if item.get_name() == "email_1.xhtml"
        )
        assert b"Newer Post" in first_chapter.get_content()


def make_subscription_json(
    name: str = "Example Publication",
    subdomain: str = "example",
    custom_domain: str | None = None,
    membership_state: str = "subscribed",
    visibility: str = "public",
    sub_type: str | None = None,
    **overrides,
) -> dict:
    """Build a minimal subscription entry from a public profile payload."""
    subscription = {
        "membership_state": membership_state,
        "visibility": visibility,
        "type": sub_type,
        "publication": {
            "id": 1,
            "name": name,
            "subdomain": subdomain,
            "custom_domain": custom_domain,
        },
    }
    subscription.update(overrides)
    return subscription


class TestNormalizeHandle:
    """Tests for normalize_handle."""

    def test_bare_handle(self):
        """It passes through a bare handle."""
        assert normalize_handle("moritzboos") == "moritzboos"

    def test_at_prefix(self):
        """It strips a leading @."""
        assert normalize_handle("@moritzboos") == "moritzboos"

    def test_profile_url(self):
        """It extracts the handle from a profile URL."""
        assert normalize_handle("https://substack.com/@moritzboos") == "moritzboos"

    def test_profile_subpage_url(self):
        """It ignores trailing profile sub-pages."""
        result = normalize_handle("https://substack.com/@moritzboos/notes")
        assert result == "moritzboos"

    def test_whitespace(self):
        """It strips surrounding whitespace."""
        assert normalize_handle("  @moritzboos  ") == "moritzboos"


class TestPublicationBaseUrl:
    """Tests for publication_base_url."""

    def test_prefers_custom_domain(self):
        """It prefers the custom domain when present."""
        publication = {"subdomain": "acx", "custom_domain": "www.astralcodexten.com"}
        assert publication_base_url(publication) == "https://www.astralcodexten.com"

    def test_falls_back_to_subdomain(self):
        """It builds a substack.com URL from the subdomain."""
        publication = {"subdomain": "thezvi", "custom_domain": None}
        assert publication_base_url(publication) == "https://thezvi.substack.com"

    def test_returns_none_without_domain(self):
        """It returns None when no domain can be derived."""
        assert publication_base_url({"name": "Nameless"}) is None


class TestParseSubscriptions:
    """Tests for _parse_subscriptions."""

    def test_public_profile_shape(self):
        """It parses the public-profile payload with embedded publications."""
        payload = {"subscriptions": [make_subscription_json()]}
        result = _parse_subscriptions(payload)
        assert len(result) == 1
        assert result[0].name == "Example Publication"
        assert result[0].base_url == "https://example.substack.com"
        assert result[0].has_paid_tier_access is True

    def test_bare_list_shape(self):
        """It parses a bare list of subscriptions."""
        result = _parse_subscriptions([make_subscription_json()])
        assert len(result) == 1

    def test_authenticated_shape_with_publication_ids(self):
        """It resolves publication_id against a sibling publications array."""
        payload = {
            "subscriptions": [{"publication_id": 7, "membership_state": "subscribed"}],
            "publications": [
                {"id": 7, "name": "Linked Pub", "subdomain": "linked"},
            ],
        }
        result = _parse_subscriptions(payload)
        assert len(result) == 1
        assert result[0].name == "Linked Pub"
        assert result[0].base_url == "https://linked.substack.com"

    def test_free_signup_not_paid(self):
        """It marks free list members as not paid."""
        payload = {
            "subscriptions": [make_subscription_json(membership_state="free_signup")]
        }
        assert _parse_subscriptions(payload)[0].has_paid_tier_access is False

    def test_comped_membership_flagged(self):
        """It distinguishes comped access from a purchased membership."""
        payload = {
            "subscriptions": [
                make_subscription_json(membership_state="subscribed", sub_type="comp")
            ]
        }
        subscription = _parse_subscriptions(payload)[0]
        assert subscription.has_paid_tier_access is True
        assert subscription.is_comped is True

    def test_purchased_membership_not_comped(self):
        """It does not flag a plain paid membership as comped."""
        payload = {"subscriptions": [make_subscription_json(sub_type=None)]}
        subscription = _parse_subscriptions(payload)[0]
        assert subscription.has_paid_tier_access is True
        assert subscription.is_comped is False

    def test_deduplicates_by_base_url(self):
        """It drops duplicate publications."""
        payload = {
            "subscriptions": [make_subscription_json(), make_subscription_json()]
        }
        assert len(_parse_subscriptions(payload)) == 1

    def test_skips_entries_without_publication(self):
        """It skips subscriptions with no resolvable publication."""
        payload = {"subscriptions": [{"membership_state": "subscribed"}, "junk"]}
        assert _parse_subscriptions(payload) == []

    def test_unexpected_payload(self):
        """It returns an empty list for unexpected payload types."""
        assert _parse_subscriptions("nonsense") == []

    def test_name_falls_back_to_url(self):
        """It falls back to the base URL when a publication has no name."""
        payload = {"subscriptions": [make_subscription_json(name="")]}
        assert _parse_subscriptions(payload)[0].name == "https://example.substack.com"


class TestFetchSubscriptions:
    """Tests for the subscription fetch helpers."""

    @pytest.mark.asyncio
    async def test_fetch_public_subscriptions(self):
        """It fetches public subscriptions for a handle."""
        payload = {"subscriptions": [make_subscription_json()]}
        client = _mock_client({"/public_profile": payload})
        result = await fetch_public_subscriptions(client, "@someone")
        assert len(result) == 1
        called_url = client.get.await_args.args[0]
        assert called_url.endswith("/api/v1/user/someone/public_profile")

    @pytest.mark.asyncio
    async def test_fetch_public_warns_when_truncated(self, caplog):
        """It warns when Substack truncates the public list."""
        payload = {
            "subscriptions": [make_subscription_json()],
            "subscriptionsTruncated": True,
        }
        client = _mock_client({"/public_profile": payload})
        await fetch_public_subscriptions(client, "someone")
        assert "truncated" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_fetch_authenticated_subscriptions(self):
        """It fetches the signed-in account's subscriptions."""
        payload = {"subscriptions": [make_subscription_json()]}
        client = _mock_client({"/api/v1/subscriptions": payload})
        result = await fetch_authenticated_subscriptions(client)
        assert len(result) == 1


class TestListSubscriptions:
    """Tests for the list_subscriptions entry point."""

    @pytest.mark.asyncio
    async def test_requires_handle_or_sid(self):
        """It raises when given neither a handle nor a cookie."""
        with pytest.raises(ValueError):
            await list_subscriptions()

    @pytest.mark.asyncio
    async def test_prefers_authenticated_endpoint(self, monkeypatch):
        """It uses the authenticated endpoint when a cookie is present."""
        payload = {"subscriptions": [make_subscription_json(name="Private Pub")]}
        client = _mock_client({"/api/v1/subscriptions": payload})
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )
        result = await list_subscriptions(sid="cookie")
        assert result[0].name == "Private Pub"

    @pytest.mark.asyncio
    async def test_falls_back_to_public_profile(self, monkeypatch, caplog):
        """It falls back to the public profile when auth fails."""
        payload = {"subscriptions": [make_subscription_json(name="Public Pub")]}

        async def get(url, params=None):
            if "/api/v1/subscriptions" in url:
                raise RuntimeError("401 Unauthorized")
            response = MagicMock()
            response.json.return_value = payload
            response.raise_for_status.return_value = None
            return response

        client = MagicMock()
        client.get = AsyncMock(side_effect=get)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        result = await list_subscriptions(handle="someone", sid="stale-cookie")
        assert result[0].name == "Public Pub"
        assert "falling back" in caplog.text

    @pytest.mark.asyncio
    async def test_auth_error_propagates_without_handle(self, monkeypatch):
        """It re-raises auth failures when no handle is available."""

        async def get(url, params=None):
            raise RuntimeError("401 Unauthorized")

        client = MagicMock()
        client.get = AsyncMock(side_effect=get)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "unhook.substack_service._make_client", lambda sid=None: client
        )

        with pytest.raises(RuntimeError):
            await list_subscriptions(sid="stale-cookie")


class TestFormatPublicationsValue:
    """Tests for format_publications_value."""

    def test_renders_comma_separated_hosts(self):
        """It renders hosts without the scheme."""
        subscriptions = _parse_subscriptions(
            {
                "subscriptions": [
                    make_subscription_json(subdomain="thezvi"),
                    make_subscription_json(
                        name="ACX", custom_domain="www.astralcodexten.com"
                    ),
                ]
            }
        )
        result = format_publications_value(subscriptions)
        assert result == "thezvi.substack.com, www.astralcodexten.com"

    def test_round_trips_into_parse_publications(self):
        """Its output parses back into publication base URLs."""
        subscriptions = _parse_subscriptions(
            {"subscriptions": [make_subscription_json(subdomain="thezvi")]}
        )
        value = format_publications_value(subscriptions)
        assert parse_publications(value) == ["https://thezvi.substack.com"]

    def test_empty(self):
        """It renders an empty string for no subscriptions."""
        assert format_publications_value([]) == ""
