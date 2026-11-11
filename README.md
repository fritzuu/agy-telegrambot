# Antigravity CLI (`agy`) - Telegram Bot Bridge `v0.1`

[![Version](https://img.shields.io/badge/version-0.1-blue.svg)](README.md)
[![Python](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Bridge cerdas dua arah untuk menghubungkan percakapan **Telegram** langsung dengan **Google Antigravity CLI (`agy`)**. Memungkinkan Anda mengontrol, memprogram, dan berdiskusi dengan AI coding agent Antigravity langsung dari ponsel atau desktop Telegram Anda secara persisten dan interaktif.

---

## 🌟 Fitur Utama (v0.1)

1. **Multi-turn Session Memory (Percakapan Bersambung)**
   - Setiap user Telegram memiliki sesi percakapan persisten (`sessions.json` yang disinkronkan langsung dengan database internal Antigravity `conversation_summaries.db`).
   - Bot mengingat konteks pembicaraan sebelumnya sehingga Anda dapat berdialog secara alami tanpa kehilangan arah.

2. **Dukungan Media Dua Arah (Two-Way Image Support)**
   - **Kirim Gambar ke Agent**: Kirim foto dari Telegram (dengan atau tanpa caption). Bot otomatis menyimpannya di folder `downloads/` dan memberikannya ke `agy` untuk dianalisis.
   - **Terima Gambar dari Agent**: Jika Antigravity menghasilkan gambar, diagram, atau merujuk path file lokal (`![caption](path)` atau path gambar lokal), bot akan mendeteksinya dan otomatis mengunggah gambar tersebut ke chat Telegram.

3. **Status Typing Real-Time**
   - Menampilkan indikator status *typing...* di Telegram selama Antigravity CLI sedang memproses prompt, menjalankan tools, atau menganalisis kode.

4. **Smart Message Chunking**
   - Secara otomatis memecah jawaban panjang dari agent agar tidak terpotong oleh batasan 4096 karakter dari API Telegram.

5. **Eksekusi Otomatis (Autonomous Execution)**
   - Dilengkapi opsi `AUTO_APPROVE_TOOLS=true` (`--dangerously-skip-permissions`) di file konfigurasi, memungkinkan agen menjalankan perintah shell atau tool tanpa terhambat prompt konfirmasi manual di terminal.

6. **Command Navigasi Bawaan**:
   - `/start` — Memulai interaksi & panduan ringkas.
   - `/new` atau `/reset` — Menghapus riwayat percakapan aktif dan memulai sesi baru.
   - `/session` — Memeriksa Conversation ID aktif dari Antigravity.
   - `/sendimg <path>` — Mengirimkan file gambar tertentu dari komputer host langsung ke Telegram.
   - `/help` — Menampilkan bantuan dan daftar fitur.

---

## 📋 Persyaratan Sistem

- **Python**: Versi 3.10 atau lebih baru.
- **Package Manager**: [uv](https://docs.astral.sh/uv/) (direkomendasikan) atau `pip` standar.
- **Antigravity CLI**: Executable `agy` sudah terpasang dan terautentikasi di sistem host.
- **Akun Telegram**: Untuk membuat bot via `@BotFather`.

---

## 1. Cara Menghubungkan ke Telegram

Ikuti langkah-langkah berikut untuk mendapatkan API Token bot Telegram Anda:

1. **Buka Telegram** dan cari akun resmi **[@BotFather](https://t.me/BotFather)**.
2. Kirim pesan:
   ```text
   /newbot
   ```
3. BotFather akan meminta:
   - **Nama Bot**: Misal `My Antigravity Assistant`
   - **Username Bot**: Harus unik dan berakhiran `bot` (contoh: `my_antigravity_bot` atau `agy_bridge_bot`).
4. Setelah selesai, BotFather akan memberikan **HTTP API Token** seperti contoh:
   ```text
   7123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567
   ```
5. Salin token tersebut, lalu buat/edit file `.env` di folder root project:
   ```bash
   cp .env.example .env  # jika ada, atau buat langsung .env
   ```
   Isi file `.env`:
   ```env
   TELEGRAM_BOT_TOKEN="7123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567"
   AUTO_APPROVE_TOOLS=true
   ```
   > **Catatan Keamanan**: Jangan pernah membagikan atau mengunggah file `.env` yang berisi token Telegram Anda ke repositori publik!

---

## 2. Cara Menghubungkan ke Antigravity CLI (`agy`) di Semua Platform OS

Bot ini berkomunikasi langsung dengan binary `agy` pada mesin host Anda. Pastikan `agy` sudah terpasang dan dapat dijalankan di terminal.

### 🍎 macOS
1. **Verifikasi Binary**:
   Pastikan binary `agy` tersedia. Secara default terpasang di `~/.local/bin/agy` atau melalui PATH sistem.
   ```bash
   which agy
   # atau
   ls -la ~/.local/bin/agy
   ```
2. **Tambahkan ke PATH** (jika belum terdeteksi di shell):
   Buka file `~/.zshrc` (atau `~/.bash_profile`), lalu tambahkan:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```
   Terapkan perubahan dengan `source ~/.zshrc`.
3. **Autentikasi**:
   Jalankan `agy` sekali di terminal dan pastikan sudah terhubung/login ke akun Anda:
   ```bash
   agy -p "halo"
   ```

---

### 🐧 Linux (Ubuntu / Debian / Fedora / Arch)
1. **Verifikasi Binary**:
   Periksa apakah `agy` ada di path:
   ```bash
   which agy
   ```
   Jika ditaruh di `~/.local/bin/agy`, pastikan permission file executable:
   ```bash
   chmod +x ~/.local/bin/agy
   ```
2. **Tambahkan ke PATH**:
   Tambahkan baris berikut ke `~/.bashrc`:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```
   Jalankan `source ~/.bashrc`.
3. **Autentikasi**:
   Verifikasi bahwa `agy` dapat mengeksekusi prompt:
   ```bash
   agy -p "cek status"
   ```

---

### 🪟 Windows

Untuk Windows, terdapat dua metode:

#### Opsi A: Menggunakan WSL 2 (Sangat Direkomendasikan)
Menjalankan bot dan `agy` di dalam **Windows Subsystem for Linux (WSL 2)** memberikan pengalaman yang paling stabil dan identik dengan Linux/macOS.
1. Buka terminal WSL (Ubuntu):
   ```bash
   cd ~
   git clone <repo-anda> agy-telegram-bot
   cd agy-telegram-bot
   ```
2. Ikuti panduan setup Linux di atas.

#### Opsi B: Native Windows (PowerShell / Command Prompt)
1. **Pastikan `agy.exe` ada di PATH Sistem**:
   - Buka *Environment Variables* di Windows.
   - Tambahkan direktori tempat `agy.exe` berada (misalnya `%USERPROFILE%\.local\bin` atau folder instalasi Antigravity Anda) ke variabel `PATH`.
   - Buka PowerShell baru dan uji:
     ```powershell
     agy --version
     ```
2. **Setup Python Virtual Environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install "python-telegram-bot[job-queue]" python-dotenv
   ```
3. **Konfigurasi Database Path**:
   Secara default pada Windows, database percakapan Antigravity berada di `%USERPROFILE%\.gemini\antigravity-cli\conversation_summaries.db`. Python `Path.home()` pada `bot.py` akan otomatis mengarah ke folder profil user Windows Anda.
4. **Jalankan Bot**:
   ```powershell
   python bot.py
   ```

---

## 3. Instalasi & Menjalankan Bot

### Langkah Cepat (macOS / Linux)

Gunakan script peluncur bawaan `run.sh` yang secara otomatis menyiapkan virtual environment menggunakan `uv`:

```bash
# 1. Masuk ke direktori
cd ~/agy-telegram-bot

# 2. Pastikan file script executable
chmod +x run.sh

# 3. Jalankan bot
./run.sh
```

### Langkah Manual (Semua OS)

Jika ingin menyiapkan dependensi secara manual:

```bash
# Buat virtual environment
python3 -m venv .venv

# Aktifkan venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1

# Install dependensi
pip install "python-telegram-bot[job-queue]" python-dotenv

# Jalankan bot
python3 bot.py
```

---

## 4. Menjalankan di Latar Belakang (Background Service)

Agar bot tetap berjalan meskipun Anda menutup jendela terminal:

### Menggunakan `tmux` / `screen` (Paling Praktis)
```bash
tmux new -s agy-bot
./run.sh
# Tekan Ctrl+B lalu D untuk detach
# Untuk kembali: tmux attach -t agy-bot
```

### Menggunakan `nohup`
```bash
nohup ./run.sh > bot.log 2>&1 &
```

### Menggunakan `pm2`
```bash
pm2 start run.sh --name "agy-telegram-bot"
pm2 save
```

---

## 5. Ringkasan Perintah Telegram

| Perintah | Deskripsi |
| :--- | :--- |
| `/start` | Menampilkan pesan sambutan dan status bot |
| `/new` atau `/reset` | Mengosongkan riwayat percakapan aktif dan memulai sesi baru |
| `/session` | Menampilkan `conversation_id` aktif yang digunakan oleh Antigravity |
| `/sendimg <path>` | Mengirimkan file gambar lokal dari komputer host ke chat Telegram |
| `/help` | Menampilkan panduan dan instruksi penggunaan |

---

## 📁 Struktur Direktori

```text
agy-telegram-bot/
├── .env                  # Token Telegram & konfigurasi flags (jangan di-commit)
├── .gitignore            # File yang diabaikan Git
├── README.md             # Dokumentasi proyek (v0.1)
├── bot.py                # Core application bridge Telegram <-> Antigravity CLI
├── run.sh                # Launcher script otomatis dengan uv
├── sessions.json         # Penyimpanan mapping user ID Telegram -> conversation ID
├── downloads/            # Direktori sementara foto dari Telegram user
└── bot.log               # Log eksekusi runtime
```

---

## 🛡️ Tips & Troubleshooting

- **Bot tidak merespons**: Pastikan `TELEGRAM_BOT_TOKEN` di `.env` sudah benar dan tidak ada proses bot lama yang berjalan bersamaan (menghindari konflik *polling*).
- **Executable `agy` tidak ditemukan**: Pastikan `which agy` mengembalikan path yang valid. Jika binary Anda berada di lokasi khusus, atur variabel `AGY_PATH` di baris atas `bot.py` atau pastikan symlink tersedia di `/usr/local/bin/agy` atau `~/.local/bin/agy`.
- **Izin Eksekusi Tools**: Jika Anda ingin agen selalu mengeksekusi perintah tanpa meminta persetujuan manual di terminal, pastikan `AUTO_APPROVE_TOOLS=true` diset di `.env`.
