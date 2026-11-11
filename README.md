# Antigravity CLI (`agy`) - Telegram Bot Bridge `v0.1`

<p align="center">
  <b>English</b> •
  <a href="README.id.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <a href="https://github.com/fritzuu/agy-telegrambot/releases"><img src="https://img.shields.io/badge/version-0.1.0-blue.svg?style=flat-square" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-brightgreen.svg?style=flat-square" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
  <a href="https://github.com/fritzuu/agy-telegrambot/issues"><img src="https://img.shields.io/github/issues/fritzuu/agy-telegrambot?style=flat-square" alt="Issues"></a>
  <a href="https://t.me/BotFather"><img src="https://img.shields.io/badge/telegram-bot-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
</p>

An intelligent, bidirectional bridge connecting **Telegram** chats directly with **Google Antigravity CLI (`agy`)**. Seamlessly control, interact with, and instruct your local AI coding agent on the go from your phone or desktop via Telegram.

---

## 🏛️ System Architecture

```mermaid
flowchart LR
    subgraph Client ["📱 User Client"]
        TG_APP["Telegram App (Mobile / Desktop)"]
    end

    subgraph Telegram_Cloud ["☁️ Telegram Cloud"]
        TG_API["Telegram Bot API"]
    end

    subgraph Host ["💻 Host Machine (macOS / Linux / Windows)"]
        direction TB
        BOT["bot.py (Python Async Bridge)"]
        SESS[("sessions.json (User Mapping)")]
        MEDIA[("downloads/ (Temporary Media)")]
        AGY_CLI["agy (Antigravity CLI Binary)"]
        AGY_DB[("conversation_summaries.db (SQLite)")]

        BOT <--> SESS
        BOT <--> MEDIA
        BOT -- "agy -p 'prompt' --conversation <id>" --> AGY_CLI
        AGY_CLI <--> AGY_DB
    end

    TG_APP <--> TG_API
    TG_API <--> BOT
```

---

## 🌟 Key Features (v0.1.0)

1. **Multi-turn Session Memory & Continuity**
   - Each Telegram user retains a persistent conversation state (`sessions.json` synchronized directly with Antigravity's internal SQLite database `conversation_summaries.db`).
   - The agent retains context from previous turns for natural, progressive dialogue.

2. **Bidirectional Media Processing**
   - **User ➡️ Agent**: Send photos or screenshots from Telegram with optional captions. The bridge saves them to `downloads/` and forwards them to `agy` for multimodal inspection.
   - **Agent ➡️ User**: When Antigravity outputs images, plots, or diagrams (via Markdown `![caption](path)` or local file paths), the bot automatically detects and uploads the media directly to your chat.

3. **Real-time Typing Status**
   - Sends periodic `typing...` actions while the CLI is executing tasks, researching code, or running shell commands.

4. **Smart Message Chunking**
   - Automatically segments large responses to prevent truncation or rejections caused by Telegram's 4096-character limit.

5. **Autonomous Execution Mode**
   - Configurable `AUTO_APPROVE_TOOLS=true` (`--dangerously-skip-permissions`) enables frictionless automation without interactive CLI terminal prompts.

6. **Built-in Telegram Commands**:
   - `/start` — Welcome message and quick instructions.
   - `/new` or `/reset` — Clears active conversation memory and starts fresh.
   - `/session` — Inspects your active Antigravity Conversation ID.
   - `/sendimg <path>` — Directly sends any local image from your host machine to Telegram.
   - `/help` — Displays usage guidance and available commands.

---

## 📋 Prerequisites

- **Python**: Version 3.10 or higher.
- **Package Manager**: [uv](https://docs.astral.sh/uv/) (recommended) or standard `pip`.
- **Antigravity CLI**: `agy` binary installed and authenticated on your host.
- **Telegram Account**: To create and configure a bot via `@BotFather`.

---

## 1. Connecting to Telegram

1. Open Telegram and search for the official **[@BotFather](https://t.me/BotFather)**.
2. Send:
   ```text
   /newbot
   ```
3. Follow the prompts:
   - **Bot Name**: e.g., `My Antigravity Assistant`
   - **Bot Username**: Must be unique and end in `bot` (e.g., `my_antigravity_bot`).
4. Copy the generated **HTTP API Token**:
   ```text
   7123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567
   ```
5. Create your `.env` configuration file from the template:
   ```bash
   cp .env.example .env
   ```
6. Paste your token into `.env`:
   ```env
   TELEGRAM_BOT_TOKEN="7123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567"
   AUTO_APPROVE_TOOLS=true
   ```

> [!CAUTION]
> Never share or commit your `.env` file containing your Telegram Bot Token to public repositories!

---

## 2. Connecting to Antigravity CLI (`agy`) Across Operating Systems

The bridge executes `agy` commands directly on your host operating system. Ensure `agy` is installed and accessible in your shell.

### 🍎 macOS
1. **Locate Binary**:
   By default, `agy` is located at `~/.local/bin/agy` or available in your global `PATH`:
   ```bash
   which agy
   # or
   ls -la ~/.local/bin/agy
   ```
2. **Add to PATH** (if not already included):
   Add this to `~/.zshrc` (or `~/.bash_profile`):
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```
   Apply changes with `source ~/.zshrc`.
3. **Verify Authentication**:
   ```bash
   agy -p "hello"
   ```

---

### 🐧 Linux (Ubuntu / Debian / Fedora / Arch)
1. **Verify Binary**:
   ```bash
   which agy
   ```
   Ensure the binary has executable permissions:
   ```bash
   chmod +x ~/.local/bin/agy
   ```
2. **Add to PATH**:
   Add the following line to `~/.bashrc`:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```
   Reload with `source ~/.bashrc`.
3. **Test CLI**:
   ```bash
   agy -p "check system status"
   ```

---

### 🪟 Windows

Two setup approaches are supported:

#### Option A: WSL 2 (Highly Recommended)
Running both the bot and `agy` inside **Windows Subsystem for Linux (WSL 2)** provides identical behavior and stability to Linux/macOS:
1. Open your WSL terminal (e.g., Ubuntu).
2. Follow the Linux setup instructions above.

#### Option B: Native Windows (PowerShell / Command Prompt)
1. **Add `agy.exe` to System PATH**:
   - Open *Environment Variables* in Windows.
   - Add the directory containing `agy.exe` (e.g., `%USERPROFILE%\.local\bin`) to your user or system `Path`.
   - Test in a new PowerShell window:
     ```powershell
     agy --version
     ```
2. **Configure Virtual Environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install "python-telegram-bot[job-queue]" python-dotenv
   ```
3. **Start the Bridge**:
   ```powershell
   python bot.py
   ```

---

## 3. Installation & Quickstart

### Quickstart (macOS / Linux)
Use the included automated launcher `run.sh` (powered by `uv`):
```bash
chmod +x run.sh
./run.sh
```

### Manual Installation (All Platforms)
```bash
# 1. Create virtual environment
python3 -m venv .venv

# 2. Activate virtual environment
# macOS/Linux:
source .venv/bin/activate
# Windows:
# .\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install "python-telegram-bot[job-queue]" python-dotenv

# 4. Start the bot
python3 bot.py
```

---

## 4. Running as a Background Daemon

Keep the bot running indefinitely even after closing your terminal session:

- **Using `tmux` (Recommended)**:
  ```bash
  tmux new -s agy-bot
  ./run.sh
  # Press Ctrl+B then D to detach
  # Reattach later: tmux attach -t agy-bot
  ```
- **Using `nohup`**:
  ```bash
  nohup ./run.sh > bot.log 2>&1 &
  ```
- **Using `pm2`**:
  ```bash
  pm2 start run.sh --name "agy-telegram-bot"
  pm2 save
  ```

---

## 5. Command Reference

| Command | Description |
| :--- | :--- |
| `/start` | Displays welcome message, status, and feature guide |
| `/new` or `/reset` | Clears active conversation memory to begin a fresh session |
| `/session` | Shows the active Antigravity `conversation_id` |
| `/sendimg <path>` | Transmits a specific local image from host to Telegram |
| `/help` | Displays usage instructions |

---

## 📁 Repository Structure

```text
agy-telegram-bot/
├── .github/              # Issue & PR templates
├── .env.example          # Environment variable template
├── .gitignore            # Git exclusion rules
├── CHANGELOG.md          # Release version history
├── CONTRIBUTING.md       # Contribution guidelines
├── CODE_OF_CONDUCT.md    # Contributor Covenant Code of Conduct
├── LICENSE               # MIT License
├── README.md             # Primary documentation (English)
├── README.id.md          # Indonesian documentation (Bahasa Indonesia)
├── bot.py                # Core async bridge (Telegram <-> Antigravity CLI)
├── run.sh                # Automated launcher with uv
├── sessions.json         # Telegram User ID to Conversation ID map
└── downloads/            # Temporary media storage for Telegram images
```

---

## 🤝 Contributing

Contributions are welcomed! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) for local development setup, code standards, and PR workflows. Please adhere to the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## 📄 License

This project is licensed under the MIT License - see the [`LICENSE`](LICENSE) file for details.
