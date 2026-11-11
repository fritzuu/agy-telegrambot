# Antigravity CLI (`agy`) - Telegram Bot Bridge `v0.2.0`

<p align="center">
  <a href="README.md">English</a> •
  <b>Bahasa Indonesia</b>
</p>

<p align="center">
  <a href="https://github.com/fritzuu/agy-telegrambot/releases"><img src="https://img.shields.io/badge/version-0.2.0-blue.svg?style=flat-square" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-brightgreen.svg?style=flat-square" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
  <a href="https://github.com/fritzuu/agy-telegrambot/issues"><img src="https://img.shields.io/github/issues/fritzuu/agy-telegrambot?style=flat-square" alt="Issues"></a>
  <a href="https://t.me/BotFather"><img src="https://img.shields.io/badge/telegram-bot-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
</p>

Bridge cerdas dua arah untuk menghubungkan percakapan **Telegram** langsung dengan **Google Antigravity CLI (`agy`)**. Memungkinkan Anda mengontrol, memprogram, dan berdiskusi dengan AI coding agent Antigravity langsung dari Telegram (ponsel maupun desktop) secara persisten dan interaktif.

---

## 🏛️ Arsitektur Sistem

```mermaid
flowchart LR
    subgraph Client ["📱 Klien Pengguna"]
        TG_APP["Telegram App (Mobile / Desktop)"]
    end

    subgraph Telegram_Cloud ["☁️ Telegram Cloud"]
        TG_API["Telegram Bot API"]
    end

    subgraph Host ["💻 Komputer Host (macOS / Linux / Windows)"]
        direction TB
        BOT["bot.py (Python Async Bridge v0.2.0)"]
        SESS[("sessions.json (Status User & Model)")]
        MEDIA[("downloads/ (Temporary Media)")]
        AGY_CLI["agy (Antigravity CLI Binary)"]
        AGY_DB[("conversation_summaries.db (SQLite)")]

        BOT <--> SESS
        BOT <--> MEDIA
        BOT -- "agy -p 'prompt' --model <model> --conversation <id>" --> AGY_CLI
        AGY_CLI <--> AGY_DB
    end

    TG_APP <--> TG_API
    TG_API <--> BOT
```

---

## 🌟 Fitur Utama (v0.2.0)

1. **Pemilihan Model Interaktif (`/model`)**
   - Pilih dan ganti model AI Antigravity langsung melalui Inline Keyboard Telegram:
     - `Gemini 3.8 Flash (High / Medium / Low)`
     - `Claude Sonnet 4.6 (Thinking)`
     - `Claude Opus 4.6 (Thinking)`
     - `GPT-OSS 120B (Medium)`
   - Preferensi model disimpan per-user dan otomatis disematkan via parameter `--model`.

2. **Pembatalan Proses Real-Time (`/stop` & Tombol Inline)**
   - Tombol dinamis `🛑 Batalkan Proses` muncul di bawah status eksekusi.
   - Command `/stop` atau `/cancel` langsung menghentikan proses `agy` yang berjalan di komputer host.

3. **Quick Actions Hub (`/menu`)**
   - Dashboard tombol cepat untuk: `📊 Git Status`, `🔄 Reset Sesi`, `🔍 Info Sistem Host`, dan `ℹ️ Info Sesi/Model`.

4. **Whitelist Akses Pengguna (`ALLOWED_TELEGRAM_USERS`)**
   - Batasi akses eksekusi terminal hanya untuk ID Telegram yang terdaftar di file `.env`.

5. **Multi-turn Session Memory (Percakapan Bersambung)**
   - Mengingat riwayat sesi percakapan per user Telegram (`sessions.json` disinkronkan langsung dengan `conversation_summaries.db`).

6. **Dukungan Media Dua Arah (Two-Way Image Support)**
   - Kirim foto dari HP untuk dianalisis oleh `agy`, dan terima otomatis gambar/diagram yang direferensikan oleh agent.

7. **Smart Chunking & Safe Markdown Fallback**
   - Pemecahan pesan panjang otomatis (limit 4096 karakter Telegram) dengan fallback otomatis ke teks biasa jika ada error parsing format Markdown.

---

## 📋 Persyaratan Sistem

- **Python**: Versi 3.10 atau lebih baru.
- **Package Manager**: [uv](https://docs.astral.sh/uv/) (direkomendasikan) atau `pip` standar.
- **Antigravity CLI**: Executable `agy` sudah terpasang dan terautentikasi di sistem host.
- **Akun Telegram**: Untuk membuat bot via `@BotFather`.

---

## 1. Cara Menghubungkan ke Telegram

1. Buka Telegram dan cari akun resmi **[@BotFather](https://t.me/BotFather)**.
2. Kirim `/newbot` lalu tentukan nama dan username bot.
3. Salin **HTTP API Token** yang diberikan.
4. Buat file `.env` dari template:
   ```bash
   cp .env.example .env
   ```
5. Isi konfigurasi `.env`:
   ```env
   TELEGRAM_BOT_TOKEN="7123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567"
   AUTO_APPROVE_TOOLS=true
   ALLOWED_TELEGRAM_USERS="id_telegram_anda"
   ```

---

## 2. Cara Menghubungkan ke Antigravity CLI (`agy`) di Semua Platform OS

- **macOS**: Pastikan binary `agy` ada di `~/.local/bin/agy` dan tercantum di `~/.zshrc`.
- **Linux**: Pastikan izin executable (`chmod +x ~/.local/bin/agy`) dan ekspor PATH di `~/.bashrc`.
- **Windows**: Disarankan menggunakan **WSL 2**, atau daftarkan direktori `agy.exe` ke Environment Variables Windows.

---

## 3. Instalasi & Menjalankan Bot

```bash
git clone https://github.com/fritzuu/agy-telegrambot.git
cd agy-telegrambot

chmod +x run.sh
./run.sh
```

---

## 4. Menjalankan di Latar Belakang (Background Service)

- **Menggunakan `tmux`**:
  ```bash
  tmux new -s agy-bot
  ./run.sh
  # Tekan Ctrl+B lalu D untuk detach
  ```
- **Menggunakan `pm2`**:
  ```bash
  pm2 start run.sh --name "agy-telegram-bot"
  pm2 save
  ```

---

## 5. Ringkasan Perintah Telegram

| Perintah | Deskripsi |
| :--- | :--- |
| `/start` | Menampilkan pesan sambutan, model aktif, dan panduan |
| `/model` | **[Baru di v0.2.0]** Menu interaktif pemilihan model AI |
| `/menu` | **[Baru di v0.2.0]** Dashboard aksi cepat (Git status, sistem, reset) |
| `/stop` / `/cancel` | **[Baru di v0.2.0]** Menghentikan proses task yang sedang berjalan |
| `/new` atau `/reset` | Mengosongkan riwayat percakapan aktif dan memulai sesi baru |
| `/session` | Menampilkan `conversation_id` aktif yang digunakan oleh Antigravity |
| `/help` | Menampilkan panduan dan instruksi penggunaan |

---

## 📁 Struktur Direktori

```text
agy-telegram-bot/
├── .github/              # Issue & PR templates
├── .env.example          # Template konfigurasi environment
├── .gitignore            # Aturan pengecualian file Git
├── CHANGELOG.md          # Riwayat perubahan per versi
├── CONTRIBUTING.md       # Panduan kontribusi
├── CODE_OF_CONDUCT.md    # Kode etik komunitas
├── LICENSE               # Lisensi MIT
├── README.md             # Dokumentasi utama (English)
├── README.id.md          # Dokumentasi Bahasa Indonesia
├── bot.py                # Core application bridge Telegram <-> Antigravity CLI (v0.2.0)
├── run.sh                # Launcher script otomatis dengan uv
├── sessions.json         # Status pengguna & preferensi model
└── downloads/            # Direktori sementara foto dari Telegram user
```

---

## 📄 Lisensi

Didistribusikan di bawah Lisensi MIT. Lihat [`LICENSE`](LICENSE) untuk informasi lebih lanjut.
