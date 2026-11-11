#!/usr/bin/env python3
"""
Antigravity CLI (agy) - Telegram Bot Bridge
Connects Telegram messages to Antigravity CLI print-mode with session persistence
and automatic image file detection/transmission.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTO_APPROVE = os.getenv("AUTO_APPROVE_TOOLS", "false").lower() == "true"
SESSIONS_FILE = BASE_DIR / "sessions.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path.home() / ".gemini" / "antigravity-cli" / "conversation_summaries.db"
AGY_PATH = shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def load_sessions() -> dict[str, str]:
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
    return {}


def save_sessions(sessions: dict[str, str]) -> None:
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving sessions: {e}")


def get_latest_conversation_id() -> str | None:
    """Fetch the most recent conversation_id from Antigravity database."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_id FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 1;"
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error querying conversation db: {e}")
        return None


async def send_typing_periodically(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            continue


async def send_chunked_message(update: Update, text: str):
    """Split and send message within Telegram's 4096 character limit."""
    chunk_size = 4000
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        await update.message.reply_text(chunk)


def extract_images_from_text(text: str) -> tuple[str, list[tuple[Path, str]]]:
    """
    Extracts local image filepaths from Markdown format ![alt](path)
    and standalone paths, replaces markdown image syntax with a cleaner label,
    and returns (cleaned_text, list_of_valid_images).
    """
    found_images: list[tuple[Path, str]] = []
    seen_paths: set[str] = set()

    # 1. Match Markdown images: ![caption](path)
    md_pattern = r'!\[(.*?)\]\(\s*(?:file:\/\/)?([^\s\)]+)\s*\)'

    def replace_md(match: re.Match) -> str:
        caption = match.group(1).strip()
        raw_path = match.group(2).strip()
        p = Path(raw_path).expanduser().resolve()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            if str(p) not in seen_paths:
                found_images.append((p, caption))
                seen_paths.add(str(p))
            return f"🖼️ *[{caption or p.name}]*"
        return match.group(0)

    cleaned_text = re.sub(md_pattern, replace_md, text)

    # 2. Match raw local file paths not already wrapped in markdown: /Users/.../something.png
    raw_path_pattern = r'(?<!\()(\/(?:Users|tmp|var|private)[^\s"\'<>`*]+\.(?:png|jpg|jpeg|webp|gif|bmp))'
    for match in re.finditer(raw_path_pattern, cleaned_text):
        raw_path = match.group(1)
        p = Path(raw_path).expanduser().resolve()
        if p.is_file() and str(p) not in seen_paths:
            found_images.append((p, p.name))
            seen_paths.add(str(p))

    return cleaned_text, found_images


async def dispatch_reply_with_media(update: Update, text: str):
    """Clean text, send message, and upload all referenced image files."""
    cleaned_text, images = extract_images_from_text(text)

    # Send text first if there is any readable content
    if cleaned_text.strip():
        await send_chunked_message(update, cleaned_text)

    # Send all discovered images
    for img_path, caption in images:
        cap = f"🖼️ {caption}" if caption else None
        try:
            with open(img_path, "rb") as f:
                await update.message.reply_photo(photo=f, caption=cap)
        except Exception as pe:
            logger.warning(f"Could not send photo {img_path}: {pe}. Trying as document...")
            try:
                with open(img_path, "rb") as f:
                    await update.message.reply_document(document=f, caption=cap)
            except Exception as de:
                logger.error(f"Failed to send image document {img_path}: {de}")
                await update.message.reply_text(f"⚠️ Gagal mengirim file gambar: {img_path.name}")


async def run_agy_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, user_prompt: str):
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id

    sessions = load_sessions()
    conv_id = sessions.get(user_id)

    # Build agy command
    cmd = [AGY_PATH, "-p", user_prompt]
    if conv_id:
        cmd.extend(["--conversation", conv_id])
    if AUTO_APPROVE:
        cmd.append("--dangerously-skip-permissions")

    # Start typing indicator loop
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_periodically(context, chat_id, stop_typing)
    )

    try:
        env = os.environ.copy()
        env["PATH"] = f"{Path.home()}/.local/bin:{env.get('PATH', '')}"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await proc.communicate()
        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()

        # Update session conversation_id if new
        latest_id = get_latest_conversation_id()
        if latest_id:
            sessions[user_id] = latest_id
            save_sessions(sessions)

        reply = out_text or err_text or "_(Tidak ada output dari agent)_"
        await dispatch_reply_with_media(update, reply)

    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Terjadi error saat menjalankan agy:\n{e}")
    finally:
        stop_typing.set()
        await typing_task


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🤖 **Antigravity CLI (agy) Bot Bridge**\n\n"
        "Bot siap menerima teks & gambar, lalu meneruskannya ke Antigravity CLI.\n\n"
        "Fitur:\n"
        "• Kirim gambar dari Mac otomatis tampil sebagai foto di sini!\n"
        "• Kirim foto dari Telegram ke bot untuk dianalisis oleh `agy`.\n"
        "• `/new` - Reset sesi percakapan\n"
        "• `/session` - Cek ID sesi aktif\n"
        "• `/sendimg <path>` - Kirim langsung file gambar dari Mac\n"
        "• `/help` - Panduan bantuan\n"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    if user_id in sessions:
        del sessions[user_id]
        save_sessions(sessions)
    await update.message.reply_text("🔄 Sesi direset. Pesan berikutnya akan memulai percakapan baru.")


async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    conv_id = sessions.get(user_id)
    if conv_id:
        await update.message.reply_text(f"📌 Active Conversation ID:\n`{conv_id}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Belum ada sesi aktif. Kirim pesan untuk memulai sesi.")


async def sendimg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows manual sending of any image path on the Mac."""
    if not context.args:
        await update.message.reply_text("Penggunaan: `/sendimg /path/ke/file_gambar.png`", parse_mode="Markdown")
        return

    filepath_str = " ".join(context.args).strip()
    p = Path(filepath_str).expanduser().resolve()
    if not p.is_file():
        await update.message.reply_text(f"❌ File tidak ditemukan:\n`{p}`", parse_mode="Markdown")
        return

    try:
        with open(p, "rb") as f:
            await update.message.reply_photo(photo=f, caption=f"🖼️ `{p.name}`", parse_mode="Markdown")
    except Exception as e:
        try:
            with open(p, "rb") as f:
                await update.message.reply_document(document=f, caption=f"📁 `{p.name}`", parse_mode="Markdown")
        except Exception as e2:
            await update.message.reply_text(f"❌ Gagal mengirim file: {e2}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Panduan Penggunaan**\n\n"
        "- Kirim teks langsung untuk bertanya/memberi perintah ke `agy`.\n"
        "- Jika jawaban agy menampilkan path gambar di Mac, bot langsung upload fotonya.\n"
        "- Kirim foto dari HP untuk dianalisis oleh `agy`.\n"
        "- Gunakan `/sendimg <path>` untuk mengirim file gambar apa saja dari Mac.\n"
        "- Gunakan `/new` jika ingin ganti topik baru."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    await run_agy_prompt(update, context, update.message.text.strip())


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photos sent by the user to the bot."""
    if not update.message or not update.message.photo:
        return

    photo = update.message.photo[-1]  # Get highest resolution
    caption = update.message.caption or "Analisis gambar ini."

    file = await context.bot.get_file(photo.file_id)
    timestamp = int(time.time() * 1000)
    saved_path = DOWNLOADS_DIR / f"tele_photo_{timestamp}.jpg"

    await file.download_to_drive(custom_path=str(saved_path))
    logger.info(f"Downloaded user photo to {saved_path}")

    # Feed prompt with the local image path to agy
    prompt_with_image = (
        f"[User mengirim file gambar dari Telegram, tersimpan di: {saved_path}]\n"
        f"{caption}"
    )
    await run_agy_prompt(update, context, prompt_with_image)


def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN belum diset di .env!")
        return

    print(f"Menggunakan executable agy di: {AGY_PATH}")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("reset", new_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("sendimg", sendimg_command))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("Bot berjalan dengan media support. Tekan Ctrl+C untuk berhenti.")
    app.run_polling()


if __name__ == "__main__":
    main()
