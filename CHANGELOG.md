# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Live 1-Bubble Streaming**: Real-time response streaming inside a single Telegram message bubble with throttled editing to prevent flood limits.
- **Asynchronous FIFO Task Queue**: Sequential user message queuing via `asyncio.Queue` preventing race conditions and concurrent command overlaps.
- **Robust Telegram HTML Formatting**: Dedicated `markdown_to_telegram_html` parser to sanitize and format markdown directly to Telegram HTML.
- **Native Telegram Bot Commands**: Auto-registration of `[ ≡ Menu ]` native commands list via `post_init`.

### Removed
- Deprecated `/sendimg` command in favor of direct bidirectional multimodal uploads.

### Planned
- Voice Note (Audio message) transcription support.
- Document and script file upload handler (`.txt`, `.py`, `.log`).
- Docker containerization & Docker Compose setup.

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
