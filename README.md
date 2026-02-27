# Unhook

Information on the internet often comes via a trade: give away your attentional agency and get interesting info. But you get hooked on feeds. Attention is your scarcest resource.

Unhook helps you reclaim your attention from social media and newsletters by periodically fetching content, filtering it, and compiling it into digestible EPUB digests you can read on your e-reader — on your own terms, without the endless scroll.

## How it works

1. **Feed fetching** — Fetch your Bluesky timeline (or author feed) and save posts to parquet files. Self-threads by the same author are detected and consolidated automatically.
2. **EPUB creation** — Convert fetched posts into an EPUB file, with images compressed and embedded. Posts are filtered by minimum length and sorted by date. Reposts are included separately with a higher length threshold. Quoted posts are inlined.
3. **Newsletter digests** — Fetch emails from a Gmail label via IMAP and export them as an EPUB, with inline and external images embedded. Newsletter boilerplate and tracking pixels are stripped.
4. **Kindle delivery** — Scheduled GitHub Actions workflows email EPUB digests to your Kindle address.

## Installation

Install dependencies using [uv](https://docs.astral.sh/uv/):

```console
$ pipx install uv
$ uv sync
```

## Configuration

### Bluesky credentials

Create a `.env` file with your Bluesky credentials:

```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_APP_PASSWORD=your-app-password
```

Generate an app password at: https://bsky.app/settings/app-passwords

### Gmail credentials (for newsletter digests)

Set these environment variables (or pass them as CLI options):

```
SMTP_USERNAME=your-gmail@gmail.com
GAPPPWD=your-gmail-app-password
```

## Usage

### Fetch Bluesky timeline

```console
$ uv run unhook fetch                                  # saves to YYYY-MM-DD.parquet (100 posts, last 7 days)
$ uv run unhook fetch --limit 50                       # fetch 50 posts
$ uv run unhook fetch --since-days 3                   # only posts from last 3 days
$ uv run unhook fetch --since-days 0                   # disable date filtering
$ uv run unhook fetch --feed author                    # fetch only your own posts
$ uv run unhook fetch --output my-feed.parquet         # custom filename
```

### Export Bluesky posts to EPUB

```console
$ uv run unhook export-epub                            # exports to exports/ directory
$ uv run unhook export-epub --limit 200                # fetch up to 200 posts
$ uv run unhook export-epub --min-length 100           # minimum post length (characters)
$ uv run unhook export-epub --repost-min-length 300    # minimum repost length
$ uv run unhook export-epub --file-prefix my-digest    # custom filename prefix
$ uv run unhook export-epub --output-dir ./out         # custom output directory
```

### Export Gmail newsletters to EPUB

```console
$ uv run unhook gmail-to-kindle                        # fetch from "newsletters-kindle" label
$ uv run unhook gmail-to-kindle --label newsletters    # custom Gmail label
$ uv run unhook gmail-to-kindle --since-days 4         # emails from last 4 days
$ uv run unhook gmail-to-kindle --output-dir ./out     # custom output directory
```

## Using GitHub Actions in your fork

After forking this repo, workflows run in your fork context, so you must configure your own secrets.

### 1) Enable workflows in your fork

In your fork, open **Actions** and enable workflows if GitHub prompts you.

### 2) Add repository secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

- `SMTP_USERNAME`: Gmail address used to send mail (for example `you@gmail.com`)
- `GAPPPWD`: Gmail app password for that sender account
- `AMAZON_KINDLE_ADDRESS`: Your Kindle send-to-Kindle email address
- `BLUESKY_HANDLE`: Your Bluesky handle (only needed for Bluesky workflows)
- `BLUESKY_APP_PASSWORD`: Bluesky app password (only needed for Bluesky workflows)

### 3) What each workflow does

- **`test.yml`** (push/PR to `main`): Runs tests and pre-commit checks on CI. No secrets required.
- **`integration.yml`** (manual only): Fetches Bluesky posts and exports an EPUB for smoke testing. Requires `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD`.
- **`kindle.yml`** (scheduled + manual): On Monday and Thursday at 18:00 UTC, fetches Bluesky posts, builds an EPUB, and emails it to your Kindle. Requires all Bluesky + Gmail/Kindle secrets.
- **`gmail-kindle.yml`** (scheduled + manual): On Monday and Thursday at 18:00 UTC, fetches Gmail newsletters by label, builds an EPUB, and emails it to your Kindle. Requires `SMTP_USERNAME`, `GAPPPWD`, `AMAZON_KINDLE_ADDRESS`.

Both `kindle.yml` and `gmail-kindle.yml` also support manual runs via **Run workflow** with custom inputs (for example `since_days`, `limit`, or `label`).

## Development

See [CLAUDE.md](CLAUDE.md) for development setup, commands, and architecture details.

## Notes on Bluesky self-thread detection

See `docs/self_thread_research.md` for details on how reply metadata appears in Bluesky feed items and how that affects self-thread extraction from the fetched timeline.
