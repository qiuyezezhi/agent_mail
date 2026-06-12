# Changelog

## 0.2.0 - 2026-06-12

- Added the single global `main-agent` model with `register --main`.
- Added `set-main` for safe main-agent switching.
- Routed messages addressed to the main-agent to local system notifications on macOS and Windows instead of watcher resume.
- Updated `init --agents` so the first newly registered agent becomes the main-agent automatically.
- Expanded docs and tests for the new registration and watcher semantics.

## 0.1.0 - 2026-06-12

- Initial public import of `agent-notify`.
- Included local queue management, watcher integration, `direnv` setup, and cross-agent reply routing.
