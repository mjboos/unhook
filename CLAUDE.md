# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unhook is a tool designed to help users reclaim their attention from social media feeds and newsletters by periodically fetching content, filtering it based on preferences, and creating digestible EPUB summaries for e-readers. The architecture:

1. **Feed fetching**: Fetch Bluesky timeline or author feed posts, with self-thread detection and consolidation, and save to parquet files
2. **EPUB creation**: Filter posts by length, deduplicate, handle reposts and quoted posts, download and compress images, and export as EPUB
3. **Newsletter digests**: Fetch emails from Gmail via IMAP by label, parse HTML/plain-text content with inline and external images, strip boilerplate, and export as EPUB
4. **Kindle delivery**: Scheduled GitHub Actions workflows email EPUBs to a Kindle address (weekly for Bluesky, twice weekly for newsletters)

## Development Setup

Install dependencies using uv:
```bash
uv sync
```

Install pre-commit hooks:
```bash
uv run pre-commit install
```

Configure Bluesky credentials in `.env` file:
```bash
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_APP_PASSWORD=your-app-password
```

Generate an app password at: https://bsky.app/settings/app-passwords

For Gmail/newsletter features, set environment variables:
```bash
SMTP_USERNAME=your-gmail@gmail.com
GAPPPWD=your-gmail-app-password
```

## Commands

### Fetching Bluesky Timeline
Fetch recent posts from your Bluesky timeline and save to parquet:
```bash
uv run unhook fetch                                  # saves to YYYY-MM-DD.parquet (100 posts, last 7 days)
uv run unhook fetch --limit 50                       # fetch 50 posts
uv run unhook fetch --since-days 3                   # only posts from last 3 days
uv run unhook fetch --since-days 0                   # disable date filtering
uv run unhook fetch --feed author                    # fetch only your own posts
uv run unhook fetch --output my-feed.parquet         # custom filename
```

### Exporting to EPUB
Export Bluesky posts as an EPUB file:
```bash
uv run unhook export-epub                            # exports to exports/ directory
uv run unhook export-epub --limit 200                # fetch up to 200 posts
uv run unhook export-epub --min-length 100           # minimum post length (characters)
uv run unhook export-epub --repost-min-length 300    # minimum repost length
uv run unhook export-epub --file-prefix my-digest    # custom filename prefix
uv run unhook export-epub --output-dir ./out         # custom output directory
```

### Gmail to Kindle EPUB
Fetch emails from a Gmail label and export as EPUB:
```bash
uv run unhook gmail-to-kindle                        # fetch from "newsletters-kindle" label
uv run unhook gmail-to-kindle --label newsletters    # custom Gmail label
uv run unhook gmail-to-kindle --since-days 4         # emails from last 4 days
uv run unhook gmail-to-kindle --output-dir ./out     # custom output directory
```

### Testing
Run all tests with coverage:
```bash
uv run pytest --cov src
```

Run tests excluding integration tests (faster):
```bash
uv run pytest --cov src -m "not integration"
```

Run only integration tests (requires credentials):
```bash
uv run pytest -m integration
```

Run tests via tox:
```bash
uv run tox
```

Run a single test file:
```bash
uv run pytest tests/test_cmd.py
```

Run a specific test:
```bash
uv run pytest tests/test_cmd.py::test_main_succeeds
```

### Linting and Formatting
Format code:
```bash
uv run ruff format
```

Lint code:
```bash
uv run ruff check
```

Auto-fix linting issues:
```bash
uv run ruff check --fix
```

Run all pre-commit checks:
```bash
uv run pre-commit run -a
```

Or via tox:
```bash
uv run tox -e pre-commit
```

## Code Architecture

### Entry Point
- CLI entry point: `src/unhook/cmd.py` using Typer framework
- Console script: `unhook` command defined in `pyproject.toml`
- Commands:
  - `fetch`: Fetch Bluesky timeline posts and save to parquet
  - `export-epub`: Fetch posts and export as EPUB with images
  - `gmail-to-kindle`: Fetch Gmail emails by label and export as EPUB

### Project Structure
- `src/unhook/`: Main source code
  - `cmd.py`: CLI commands using Typer
  - `feed.py`: Bluesky feed fetching, self-thread detection, and thread consolidation
  - `post_content.py`: Post content extraction, deduplication, link facet handling, and quote post inlining
  - `constants.py`: Bluesky API type constants and helpers
  - `epub_builder.py`: EPUB file builder for Bluesky posts (markdown to HTML, image embedding)
  - `epub_service.py`: Orchestrates feed fetching, image downloading/compression, repost handling, and EPUB export
  - `gmail_service.py`: Gmail IMAP client for fetching emails by label
  - `email_content.py`: Email content parsing (HTML/text bodies, inline images, external image extraction)
  - `gmail_epub_service.py`: Gmail-to-EPUB pipeline (HTML sanitization, boilerplate stripping, image handling, EPUB building)
- `tests/`: Test files mirroring source structure
  - `conftest.py`: Shared fixtures (`make_post`, `make_repost`, `make_post_mock`, `mock_env_vars`, etc.)
- `docs/`: Documentation
  - `self_thread_research.md`: Research notes on Bluesky reply metadata for thread detection
- `.github/workflows/`: CI/CD workflows
  - `test.yml`: Runs tests and pre-commit on push/PR to main (Ubuntu + Windows, Python 3.12)
  - `integration.yml`: Manual dispatch for Bluesky integration test with EPUB export
  - `kindle.yml`: Weekly Bluesky EPUB to Kindle (Saturday 18:00 UTC)
  - `gmail-kindle.yml`: Twice-weekly Gmail newsletter EPUB to Kindle (Mon/Thu 18:00 UTC)
- `.env`: Credentials (not committed to git)
- Minimum Python version: 3.12

### Key Dependencies
- `atproto`: Official AT Protocol/Bluesky Python SDK for API access
- `python-dotenv`: Environment variable management
- `pandas`: Data manipulation and parquet file I/O
- `pyarrow`: Parquet format support
- `typer`: CLI framework
- `ebooklib`: EPUB file generation
- `bleach`: HTML sanitization for EPUB content
- `markdown2`: Markdown to HTML conversion for post text
- `httpx`: Async HTTP client for image downloading
- `pillow`: Image compression and format conversion for EPUB

### Authentication
- Bluesky: Uses app passwords (not main account password), loaded from `.env` via `python-dotenv`
- Gmail: Uses app passwords via IMAP (SMTP_USERNAME + GAPPPWD environment variables)
- `fetch_feed_posts()` in `feed.py` handles Bluesky authentication and API calls
- `GmailService` in `gmail_service.py` handles Gmail IMAP connection

### Data Flow
- **Bluesky → EPUB**: `fetch_feed_posts()` → self-thread detection → thread consolidation → repost separation → `map_posts_to_content()` → length filtering → image download/compression → `EpubBuilder.build()`
- **Gmail → EPUB**: `GmailService.fetch_emails_by_label()` → `parse_raw_email()` → HTML sanitization (strip styles/scripts/boilerplate/tracking pixels) → image download → CID/URL replacement → `EmailEpubBuilder.build()`
- Posts saved as parquet files with nested post data (one row per feed item)

### Code Quality Requirements
- Coverage requirement: 90% minimum (configured in pyproject.toml)
- Ruff for linting and formatting (line length: 88, target: py312)
- Ruff lint rules: E, F, W, I, N, UP
- Pre-commit hooks enforce: formatting, linting, secret detection (gitleaks), large file check, TOML/YAML validation, trailing whitespace, end-of-file newlines
- Integration tests marked with `@pytest.mark.integration` (can be skipped)
- All commands use `uv run` to ensure proper virtual environment activation
- Build system: hatchling

## Agent Instructions

- **Always use `uv run` to run Python commands** — never invoke `python`, `pytest`, `ruff`, or other Python tools directly. Use `uv run python`, `uv run pytest`, `uv run ruff`, etc. This ensures the correct virtual environment and dependencies are used.
