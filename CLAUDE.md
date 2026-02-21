# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unhook Tanha is a tool designed to help users reclaim their attention from social media feeds by periodically fetching content, filtering it based on preferences, and creating digestible summaries. The three-part architecture:

1. **Feed fetching**: Get feed content and save it (currently implemented for Bluesky)
2. **Digest creation**: Filter saved content based on user preferences (not yet implemented)
3. **Digest delivery**: Send via email in e-reader-compatible format (not yet implemented)

Current implementation fetches Bluesky timeline posts and saves them to parquet files for later processing.

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

## Commands

### Fetching Bluesky Timeline
Fetch recent posts from your Bluesky timeline and save to parquet:
```bash
uv run unhook-tanha fetch                           # saves to YYYY-MM-DD.parquet with 100 posts
uv run unhook-tanha fetch --limit 50                # fetch 50 posts
uv run unhook-tanha fetch --output my-feed.parquet  # custom filename
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

Run only integration tests (requires Bluesky credentials):
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
- CLI entry point: `src/unhook_tanha/cmd.py` using Typer framework
- Console script: `unhook-tanha` command defined in `pyproject.toml`
- Main commands:
  - `fetch`: Fetch Bluesky timeline posts and save to parquet

### Project Structure
- `src/unhook_tanha/`: Main source code
  - `cmd.py`: CLI commands using Typer
  - `feed.py`: Bluesky feed fetching logic using atproto SDK
- `tests/`: Test files mirroring source structure
- `.env`: Bluesky credentials (not committed to git)
- Minimum Python version: 3.12

### Key Dependencies
- `atproto`: Official AT Protocol/Bluesky Python SDK for API access
- `python-dotenv`: Environment variable management
- `pandas`: Data manipulation and parquet file I/O
- `pyarrow`: Parquet format support
- `typer`: CLI framework

### Authentication
- Uses Bluesky app passwords (not main account password)
- Credentials loaded from `.env` file via `python-dotenv`
- `fetch_feed_posts()` in `feed.py` handles authentication and API calls

### Data Format
- Posts fetched from Bluesky timeline are saved as parquet files
- Each row in parquet file represents one feed item with nested post data
- Default filename format: `YYYY-MM-DD.parquet`

### Code Quality Requirements
- Coverage requirement: 80% minimum (configured in pyproject.toml)
- Ruff for linting and formatting (line length: 88)
- Pre-commit hooks enforce: formatting, linting, secret detection (gitleaks), TOML/YAML validation, file cleanup
- Integration tests marked with `@pytest.mark.integration` (can be skipped)
- All commands use `uv run` to ensure proper virtual environment activation

## Agent Instructions

- **Always use `uv run` to run Python commands** — never invoke `python`, `pytest`, `ruff`, or other Python tools directly. Use `uv run python`, `uv run pytest`, `uv run ruff`, etc. This ensures the correct virtual environment and dependencies are used.
