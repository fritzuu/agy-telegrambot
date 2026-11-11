# Contributing to Antigravity CLI Telegram Bridge

Thank you for your interest in contributing! We welcome bug fixes, documentation improvements, and new feature proposals.

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Development Setup

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/<your-username>/agy-telegrambot.git
   cd agy-telegrambot
   ```

2. **Set up Virtual Environment**:
   Using `uv` (recommended):
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install "python-telegram-bot[job-queue]" python-dotenv
   ```
   Or standard `venv`:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install "python-telegram-bot[job-queue]" python-dotenv
   ```

3. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Add your test bot token
   ```

---

## Contribution Workflow

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Make your changes adhering to standard Python style:
   - Use PEP 8 guidelines.
   - Include type annotations (`dict[str, str]`, `Optional`, etc.).
   - Keep functions concise and adhere to Single Responsibility.
3. Test your changes locally before committing.
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: add audio voice note support`
   - `fix: resolve entity parsing failure in markdown`
   - `docs: update installation steps in README`
   - `chore: update dependencies`
5. Push to your fork and submit a Pull Request.

---

## Pull Request Guidelines

- Ensure your branch is up to date with `main`.
- Fill out the provided [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md).
- Describe clearly what changes were made and why.
- Confirm that no sensitive information (e.g. `.env` or tokens) is committed.
