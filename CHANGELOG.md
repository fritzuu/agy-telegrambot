# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Voice Note (Audio message) transcription support (Whisper / Gemini Multimodal Audio).
- Document and script file upload handler (`.txt`, `.py`, `.log`).
- Interactive 1-Tap Admin Approval flow for requested access.
- Docker containerization & Docker Compose setup.

---

## [0.3.0] - 2026-11-11

### Added
- **Mobile Companion Suite (Away-from-Mac)**:
  - `/sys` & `/status`: Real-time macOS telemetry dashboard (Battery status/remaining, RAM usage, SSD space, CPU load averages 1/5/15m, and Uptime).
  - `/caffeinate [on/off]`: macOS anti-sleep daemon controller to keep the Mac awake during long tasks or while away.
  - `/screen` & `/screenshot`: Silent remote desktop capture (`screencapture -x`) with UUID-based temporary collision-free storage sent directly to Telegram.
  - `/projects` & `/fav`: Interactive Inline Keyboard project switcher with bookmarking capabilities (`⭐ Bookmark Folder Ini`).
  - `/get <file>`: Direct file delivery of documents, scripts, and artifacts from Mac to mobile Telegram.
  - `/sh <command>` & `$ <command>`: Instant zero-LLM bash runner executing in ~200ms with dangerous command pattern blocklist.
- **Dedicated Isolated Workspace & Custom Casual Persona**:
  - Auto-routes to `~/agy-workspace` by default with isolated `GEMINI.md` context rules to completely eliminate repository context leaks on `/new`.
  - Added `/pwd` and `/cd` commands for mobile directory inspection and navigation.
  - Injected custom casual gaul Indonesian persona ("gue-lu", natural humor, light roasting, mobile-optimized format).
- **Security Hardening & Stability**:
  - Enforced **Secure-by-Default** authorization: locks down bot automatically if `ALLOWED_TELEGRAM_USERS` is missing or empty, gracefully presenting user ID for onboarding.
  - Added strict sensitive path guard (`is_sensitive_path`) preventing `/get` exfiltration of `.ssh`, `.env`, `.aws`, `.git`, private keys, and shell history.
  - Added `SESSION_LOCK` and atomic file write (`.tmp` -> `os.replace`) to prevent corruption of `sessions.json`.
  - Implemented `await proc.wait()` timeout watchdog on all process terminations, permanently eliminating UNIX zombie processes (`<defunct>`).
  - Added `balance_html_tags` parser to maintain tag balance across split chunks, preventing Telegram `BadRequest: Can't parse entities` errors.
  - Added auto-rotation and cleanup of cached photo downloads in `downloads/` (24h expiry, max 30 files).

---

## [0.2.0] - 2026-11-11

### Added
- **Interactive Task Cancellation**:
  - Dynamic inline button `🛑 Batalkan Proses` attached to status message during prompt execution.
  - Commands `/stop` and `/cancel` to terminate running `agy` subprocess on demand.
- **Interactive Model Selection (`/model`)**:
  - Interactive Inline Keyboard to select Antigravity AI models (Gemini 3.8 Flash, Claude Sonnet 4.6, Claude Opus 4.6, GPT-OSS 120B).
  - Model preference persisted per-user and dynamically passed to `agy` via `--model`.
- **Quick Actions Hub (`/menu`)**:
  - Interactive dashboard for routine actions: Git Status, Reset Session, Host System Info, and Session/Model Info.
- **Security Whitelist (`ALLOWED_TELEGRAM_USERS`)**:
  - User ID access control via `.env` to prevent unauthorized execution of local commands.
- **Safe Markdown Parser Fallback**:
  - Automatic fallback to plain text if Telegram fails to parse entities, preventing dropped responses.

---

## [0.1.0] - 2026-11-11

### Added
- **Core Async Bridge**: Connects Telegram Bot with Google Antigravity CLI (`agy`) print mode.
- **Multi-turn Session Persistence**: Per-user conversation tracking synced with Antigravity SQLite database `conversation_summaries.db`.
- **Bidirectional Media Processing**: Automatic image discovery and uploads.
- **Typing Indicator Loop**: Background typing action during prompt execution.
- **Smart Message Chunking**: Slices long text exceeding 4096 characters.
- **Initial Commands**: `/start`, `/new`, `/reset`, `/session`, `/sendimg`, `/help`.
- **Open Source Governance & Documentation**: Dual-language README (EN & ID), MIT License, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, and GitHub templates.
