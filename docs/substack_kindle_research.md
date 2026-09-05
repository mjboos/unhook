# Research: Collecting Substack links and sending articles to Kindle

Goal: extend unhook so that Substack articles encountered while browsing (i.e.
links, not newsletters arriving by email) can be collected and delivered to
Kindle as EPUB digests, reusing the existing pipeline.

The problem splits into three independent parts:

1. **Link collection** — getting a URL from the browser/phone into the pipeline
2. **Article fetching** — turning a Substack URL into clean HTML + images
3. **EPUB build & delivery** — already solved by the existing code

## 1. Article fetching (verified)

Substack has no official API, but every publication exposes a JSON endpoint on
its own domain (including custom domains like `astralcodexten.com`):

```
GET https://<publication-domain>/api/v1/posts/<slug>
```

Verified 2026-08-01 with an unauthenticated request: the response includes
`title`, `subtitle`, `post_date`, `canonical_url`, `cover_image`,
`publishedBylines[].name`, and — critically — `body_html` with the full,
clean article HTML (no page chrome, no nav, no comments). For a free ACX post
this returned ~110 KB of article HTML. This is far cleaner than scraping the
web page and needs no headless browser.

Other useful endpoints:

- `GET /api/v1/archive?sort=new&limit=N` — recent posts with slugs and
  `audience` field (`everyone` vs `only_paid`)
- `GET /feed` — standard RSS per publication (only useful for a
  subscription-based model, not link collection)

### Paywalled posts

Verified: for an `audience: only_paid` post the unauthenticated endpoint
returns `body_html` of length 0. Attaching the `substack.sid` session cookie
from a logged-in browser session (DevTools → Application → Cookies →
substack.com) unlocks full content **for publications the account actually
subscribes to**. Established tools ([sbstck-dl](https://github.com/alexferrari88/sbstck-dl),
[substack-api on PyPI](https://pypi.org/project/substack-api/)) use exactly
this mechanism. Implications:

- Store the cookie as a GitHub Actions secret (`SUBSTACK_SID`); treat it like
  a password.
- The cookie is long-lived but does expire eventually — the pipeline should
  degrade gracefully (skip the post, note it in the digest or logs) rather
  than fail the run.

### How official/stable is this API?

**It is not official.** `/api/v1/*` is the internal JSON API that Substack's
own web frontend uses to render pages — undocumented, unsupported, and
changeable without notice. Substack *did* launch an official
[Developer API in 2026](https://support.substack.com/hc/en-us/articles/45099095296916-Substack-Developer-API),
but it is currently limited to public-profile lookups (gated behind an
[API ToS](https://substack.com/api-tos) agreement and manual approval) and has
no content/posts endpoints — it does not help this use case.

In practice the internal API is de facto very stable:

- It has existed for years — community wrappers date back to at least 2022–23
  ([substack-api first PyPI release May 2023](https://pypi.org/project/substack-api/),
  active through v1.3.0 in May 2026; a
  [custom front-end built on it in 2022](https://matthagy.substack.com/p/developing-a-custom-substack-front)).
  It was almost certainly available when unhook was first built, just obscure.
- Substack can't remove it wholesale without breaking their own site; the
  realistic risks are response-shape drift and IP throttling at scraper
  volumes ("Substack will throttle or block your IP if you make too many
  requests"). A personal digest making a handful of requests twice a week is
  indistinguishable from normal browsing traffic.
- Observed in practice (2026-08): some `*.substack.com` domains sit behind a
  Cloudflare bot heuristic that challenges Python's default TLS fingerprint
  (HTTP 403 with `cf-mitigated: challenge`) while custom domains did not.
  Requests succeed with a browser-like TLS cipher ordering, which
  `substack_service._make_client` now sets. The per-publication fail-soft
  behavior covers the case where a domain is challenged anyway.
- ToS honesty: like most platforms, Substack's general terms prohibit
  unauthorized automated access. Low-volume personal fetching of content you
  can already read (and, for paywalled posts, pay for) is widely done and has
  drawn no enforcement against the open-source tools doing it for 3+ years —
  but it is tolerated, not sanctioned.

Mitigations: keep the fetcher a small isolated module so the strategy is
swappable; fail soft (skip a post, log it) rather than fail the run. If the
JSON endpoint ever disappears, fallbacks exist: the article HTML page embeds
the same post JSON in `window._preloads`, and free posts are available via
each publication's RSS `/feed`.

### Discovering which publications to follow

Two endpoints answer "what do I subscribe to?", both verified 2026-09-05:

- `GET https://substack.com/api/v1/user/<handle>/public_profile` —
  unauthenticated. Returns a `subscriptions` array with an embedded
  `publication` (name, `subdomain`, `custom_domain`) plus `visibility`,
  `membership_state` and `type`. Note `membership_state: subscribed` means
  "has paid-tier access", **not** "is paying" — comped memberships
  (`type: comp`), gifts and trials all report `subscribed`, so it should
  never be presented to the user as evidence of a paid subscription.
  `free_signup` marks a free list member. **Only publicly visible subscriptions
  appear** — anything hidden from the profile is absent entirely, and a
  `subscriptionsTruncated` flag marks a clipped list. Note the endpoint
  works by handle, not numeric user id (the id form returns an error).
- `GET https://substack.com/api/v1/subscriptions` — requires the
  `substack.sid` cookie (HTTP 401 with `{"errors":[{"msg":"Please sign
  in"}]}` otherwise). Returns the complete list including hidden ones.

`unhook list-subscriptions` wraps both: it prefers the authenticated
endpoint when `SUBSTACK_SID` is set, falls back to the public profile, and
prints a ready-to-paste `SUBSTACK_PUBLICATIONS` value. The authenticated
response shape is parsed defensively (embedded `publication`, or
`publication_id` resolved against a sibling `publications` array) since it
could not be verified without a live cookie.

Keeping the cookie out of chat matters: it is a session credential, so it
belongs in `.env` / a GitHub secret that the command reads from the
environment, never pasted into a conversation or a commit.

### URL normalization

Shared Substack links come in several shapes that must be resolved to
`(publication_domain, slug)`:

- `https://pub.substack.com/p/<slug>` — direct
- `https://custom-domain.com/p/<slug>` — direct (API lives on same domain)
- `https://open.substack.com/pub/<pub>/p/<slug>?...` — app share links;
  follow the redirect to the canonical URL
- Links with tracking params (`?utm_...`, `?r=...`) — strip query string
- `https://substack.com/home/post/p-<id>` and `/@author/...` note links —
  follow redirects; if resolution fails, fall back to fetching the page and
  reading `<link rel="canonical">`

A dependency-free approach: `httpx.get(url, follow_redirects=True)`, take the
final URL, extract host and the path segment after `/p/`.

## 2. Link collection options

The constraint that shapes everything: unhook has **no server** — it is a CLI
plus scheduled GitHub Actions. So the collector must be a queue that a
workflow can poll, not an endpoint that receives pushes.

### Option A — Gmail label as link inbox (recommended v1)

Share a link from any browser/phone via the share sheet → Gmail → email it to
yourself. A Gmail filter (`from:me`, body contains `substack.com` — or a
subject prefix like `kindle:`) applies a label such as `kindle-links`. A new
CLI command polls that label, extracts URLs from message bodies, fetches the
articles, builds the EPUB, and the workflow emails it to the Kindle address.

- **Reuse**: `GmailService` (IMAP by label), the send-mail workflow step, all
  EPUB/image machinery. Zero new accounts, zero new secrets.
- **Friction**: 2–3 taps on mobile (share → Gmail → send). Acceptable.
- **State handling is free**: `since_days` windowing already exists; or move
  processed messages out of the label via IMAP so nothing is sent twice.

### Option B — Raindrop.io as link inbox (nicest UX)

[Raindrop.io](https://developer.raindrop.io/) (free tier) has polished browser
extensions and mobile share-sheet apps. Save a link with one click into a
`kindle` collection/tag. Its REST API (`https://api.raindrop.io/rest/v1/`)
supports fetching raindrops by collection/tag with a **test token that never
expires** (Settings → Integrations) — ideal for a GitHub Actions secret.
After processing, the workflow re-tags or archives the bookmark so it isn't
resent.

- **Friction**: 1 click / 2 taps — the best save experience.
- **Cost**: one new external account + one new secret; a small API client
  module (~50 lines with httpx).

### Option C — Telegram bot as link inbox

Share links to a personal bot from any share sheet; a workflow polls
`getUpdates` (long-poll pull — no server needed). **Caveat that kills it for
this project's cadence**: Telegram only retains unconfirmed updates for
[24 hours](https://core.telegram.org/bots/api#getupdates), so a twice-weekly
cron would silently lose links. It would force a daily "drain links into a
committed queue file" job — extra moving parts for no UX gain over Raindrop.

### Option D — Browser extension / bookmarklet → GitHub API

A small extension (or bookmarklet) that appends the current URL to a
`links/queue.json` in the repo via the GitHub contents API, or opens a
pre-filled GitHub issue labeled `kindle`; the workflow processes and clears
the queue. Works, and keeps everything in one repo — but requires embedding a
fine-grained PAT in the extension, building/maintaining the extension for
desktop **and** solving mobile separately (no extensions on mobile Chrome/
Safari without workarounds). Highest effort, worst mobile story. Not worth it
when A/B exist.

### Option E — Off-the-shelf (baseline to beat)

Amazon's own **Send to Kindle** browser extension/share target, Push to
Kindle, KTool, Readwise Reader all send single articles immediately. None of
them: batch into periodic digests, use your Substack session for paywalled
subscriber content, apply unhook's Kindle-friendly sanitization, or keep you
out of vendor lock-in. They're fine as a stopgap but don't meet the
"digestible periodic EPUB" goal of this project.

## 3. Pipeline integration (what gets reused)

Almost the entire Gmail pipeline transfers; `body_html` from the Substack API
is *cleaner* input than newsletter email HTML:

| Stage | Existing code | Reuse |
|---|---|---|
| HTML sanitization | `gmail_epub_service._sanitize_email_html` (bleach allowlist, boilerplate strip) | as-is (boilerplate regexes already target Substack chrome) |
| Image download + compression | `download_external_images`, `_compress_image` | as-is |
| Remote-image stripping / URL rewrite | `email_content.replace_external_image_urls`, `strip_remote_image_tags` | as-is |
| EPUB assembly (chapters, TOC with publication eyebrow) | `EmailEpubBuilder` | near as-is — generalize `EmailContent` (title/publication/published/html_body/external_image_urls) or introduce a shared `ArticleContent` dataclass |
| Delivery | `gmail-kindle.yml` send-mail step + EPUB validation step | copy |

New code needed:

- `substack_fetcher.py` — URL normalization + `/api/v1/posts/<slug>` client
  (httpx, optional `substack.sid` cookie), map JSON → `ArticleContent`
  (title, publication name from host or `publication` field, author byline,
  date, `body_html`, cover image prepended)
- Link-source module — Option A: extend `GmailService` usage with a second
  label + URL extraction from message bodies; Option B: small Raindrop client
- `cmd.py` — new command, e.g. `unhook substack-to-kindle --label kindle-links`
- `.github/workflows/substack-kindle.yml` — same shape as `gmail-kindle.yml`,
  running daily at 18:00 UTC with a matching one-day window

### Cadence and the missing de-duplication state

The digest is stateless: each run asks for "posts from the last N days" and
sends whatever it finds, with no record of what previous runs already sent.
That makes `SINCE_DAYS` and the cron schedule a matched pair —

- **window > gap between runs** → posts appear in several consecutive
  digests (a 4-day window on a daily schedule sends everything ~4 times);
- **window == gap** (the current daily/`1` setup) → each post is sent once,
  but the coverage is exactly contiguous, so anything published inside a
  scheduling delay or a failed run is missed permanently. GitHub's cron is
  best-effort and routinely runs minutes late under load, so small gaps are
  expected in practice.

Fixing that properly means keeping state: record the ids of posts already
sent (a committed JSON file, or a cache keyed by publication) and widen the
window for slack, filtering out anything already delivered. Until then the
current setting trades rare missed posts for never sending duplicates,
which is the better failure mode for a reading digest.

Estimated scope: ~300–400 lines of source + tests; no new heavyweight
dependencies (httpx already present).

## Should the API replace email ingestion entirely?

Once a Substack fetcher exists, the scheduled newsletter digest itself could
be produced by *pulling* from the API instead of parsing emails: keep a list
of subscribed publications, hit each one's
`/api/v1/archive?sort=new&limit=N`, take posts with `post_date` in the
window (verified: the archive response carries `post_date`, `audience`, and
`type` per post — a direct replacement for the `since_days` email
windowing), fetch each via `/api/v1/posts/<slug>`, and build the digest.
Ad-hoc link additions (public posts from unsubscribed publications, paid
posts you have access to) then just append to the same `(domain, slug)`
list — one pipeline, one EPUB, one send.

Why the API path is better for Substack content:

- **Cleaner input.** `body_html` is article-only. Most of the hard-won email
  code — table-layout stripping, boilerplate regexes, tracking-pixel
  removal, `substack.com/redirect` link mangling — exists to fight email
  HTML and becomes unnecessary.
- **No truncation.** Gmail clips messages over ~102 KB; long posts arrive
  cut off in email but always complete via the API.
- **Uniformity.** Scheduled subscriptions and ad-hoc links share every stage
  after the URL list is assembled.
- **Simpler plumbing.** No Gmail filters/labels for the Substack side;
  publication list lives in a config file in the repo (explicit, versioned).
  Auto-discovering subscriptions via the authenticated API is possible but
  a config list is simpler and avoids a hard auth dependency.

Why *not* to delete the email pipeline outright:

- **Non-Substack newsletters.** The email path is provider-agnostic (Ghost,
  beehiiv, Buttondown, …). The API path only covers Substack. Whether email
  can be fully retired is purely a question of what actually lands in the
  label today.
- **Paid content robustness — the one real tradeoff.** A paid subscriber
  *receives full content by email* with zero credentials, forever. The API
  needs a `substack.sid` cookie that eventually expires; when it does, paid
  posts silently come back empty until the secret is refreshed. Mitigation:
  when a post has `audience != everyone` and `body_html` is empty, fail loud
  (workflow warning / non-zero notice), and fall back to the email copy if
  the Gmail path still exists.

Sensible migration: build the fetcher for ad-hoc links first (needed
anyway), run API-based and email-based digests side by side for a cadence or
two to compare fidelity, then narrow the Gmail label filter to non-Substack
senders — keeping `gmail-to-kindle` as the fallback/generic path rather than
deleting it.

## Recommendation

1. **v1: Option A (Gmail label inbox).** No new accounts or secrets, reuses
   `GmailService`, and the phone share-sheet → Gmail flow is good enough to
   validate the habit. Fold delivery into the existing Mon/Thu cadence.
2. **v2: add Option B (Raindrop)** as an alternative link source behind the
   same fetcher/EPUB code if the email friction proves annoying — the link
   source is a ~50-line pluggable module either way.
3. **Paywalled content**: add optional `SUBSTACK_SID` secret support from the
   start (it's one cookie header on the fetch), skip-with-warning when absent
   or expired.

### Open questions

- Should non-Substack article links in the inbox be rejected, or handled via
  a generic readability-style extractor (e.g. `trafilatura`) as a later
  extension? The URL-normalization step is the natural dispatch point.
- Digest cadence: piggyback on the newsletter email (one Kindle email, two
  EPUBs) vs. separate workflow.

## Sources

- [Unofficial Substack API wrapper (NHagar/substack_api)](https://github.com/NHagar/substack_api)
- [substack-api on PyPI](https://pypi.org/project/substack-api/)
- [Unofficial Substack API reference — 129 verified endpoints](https://github.com/AnthonyDavidAdams/substack-api-reference)
- [Reverse-engineering the Substack API](https://iam.slys.dev/p/no-official-api-no-problem-how-i)
- [sbstck-dl — CLI Substack downloader with cookie auth](https://github.com/alexferrari88/sbstck-dl)
- [Raindrop.io API docs](https://developer.raindrop.io/)
- [Telegram Bot API — getUpdates 24h retention](https://core.telegram.org/bots/api#getupdates)
- Live verification (2026-08-01): `GET https://www.astralcodexten.com/api/v1/posts/<slug>` returns full `body_html` for free posts, empty for `only_paid` posts without a session cookie.
