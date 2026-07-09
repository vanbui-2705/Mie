# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py

# Install Playwright browser (required first-time setup)
playwright install chromium
```

## Architecture

Single-file Tkinter desktop app (`app.py`) + a Playwright helper module (`browser.py`). No build system, no tests, no linting — edit and run directly.

### Data flow

- **Config** lives at `~/.ucmas_facebook_poster/config.json` — multi-account format with an `accounts[]` list, each containing `pages[]`. Old single-page formats are migrated on load via `migrate_old_config()`.
- **Post history** is stored in SQLite at `~/.ucmas_facebook_poster/poster.db` (table `posts`). The `Store` class wraps all DB access.
- **Browser profiles** for Playwright login are stored at `~/.ucmas_facebook_poster/browser_profiles/<account_id>/`.

### Key classes and their roles

| Class | File | Role |
|---|---|---|
| `PosterApp` | app.py | Main Tkinter app — builds all tabs, owns all UI state |
| `Store` | app.py | SQLite wrapper for post history |
| `FacebookApi` | app.py | Graph API calls (get pages, post text/photo/video, token exchange) |
| `GeminiApi` | app.py | Single static method calling Gemini generateContent endpoint |
| `PlaywrightManager` | browser.py | Opens Chrome for manual login and posts to personal timeline |
| `ContentGuard` | app.py | Heuristic spam/duplicate checker on post text |
| `FacebookAccount` / `FacebookPage` | app.py | Dataclasses serialized to/from config.json |

### Threading model

All network operations (API calls, Playwright) run in `threading.Thread` and communicate back to the UI via `self.events` (a `queue.Queue`). The `_process_events` method is polled every 150ms via `root.after`. Any new background work must follow this pattern — never call blocking I/O on the main thread.

### Two posting paths

1. **Graph API** — posts to Fanpages using page access tokens. Supports text, single photo, photo album (multi-photo), and video.
2. **Playwright** — posts to personal profile by driving a real Chrome instance. Requires prior browser login. Used only when `page.id == "me"`.

### Scheduling

A 30-second `root.after` tick (`_scheduler_tick`) checks for due scheduled posts in SQLite and fires them in a background thread. Scheduled posts serialize their destinations (pages) as JSON in the `media` column via `_serialize_scheduled_payload`.
