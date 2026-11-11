# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Telegram User ID Whitelist / Access Control via `.env`.
- Voice Note (Audio message) transcription support.
- Document and script file upload handler (`.txt`, `.py`, `.log`).
- Automatic fallback for Markdown parse errors.

---

## [0.1.0] - 2026-11-11

### Added
- **Core Async Bridge**: Connects Telegram Bot with Google Antigravity CLI (`agy`) print mode.
- **Multi-turn Session Persistence**: Per-user conversation tracking synced with Antigravity SQLite database `conversation_summaries.db`.
- **Bidirectional Media Processing**:
  - Automatically downloads photos sent by user in Telegram and passes filepath to `agy`.
  - Discovers local images in `agy` responses (both Markdown `![alt](path)` and local absolute file paths) and uploads them directly to Telegram.
- **Typing Indicator Loop**: Periodic background typing action during long-running tasks.
- **Smart Message Chunking**: Automatic slicing of responses exceeding Telegram's 4096-character limit into 4000-character segments.
- **Commands**:
  - `/start` - Initial welcome and usage instructions.
  - `/new` and `/reset` - Conversation context reset.
  - `/session` - Retrieve active Antigravity conversation ID.
  - `/sendimg <path>` - Transmit local host images on demand.
  - `/help` - Usage guide.
- **Tool Automation**: `AUTO_APPROVE_TOOLS` environment variable setting `--dangerously-skip-permissions`.
- **Cross-Platform Launcher**: `run.sh` script providing automated virtual environment setup and execution with `uv`.
- **Open Source Governance & Documentation**:
  - Dual-language documentation: `README.md` (English) and `README.id.md` (Bahasa Indonesia).
  - MIT License.
  - Contribution guidelines (`CONTRIBUTING.md`) and Code of Conduct (`CODE_OF_CONDUCT.md`).
  - GitHub issue and PR templates.
