#!/usr/bin/env python3
"""
Antigravity CLI (agy) - Telegram Bot Bridge v0.2.0
Connects Telegram messages to Antigravity CLI print-mode with session persistence,
interactive model selection, task cancellation, quick action hub, and automatic media detection.
"""

import asyncio
import functools
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
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

# Allowed Telegram User IDs (comma-separated). If empty, bot is open to all.
raw_allowed = os.getenv("ALLOWED_TELEGRAM_USERS", "").strip()
ALLOWED_USERS: set[str] = {u.strip() for u in raw_allowed.split(",") if u.strip()}

DB_PATH = Path.home() / ".gemini" / "antigravity-cli" / "conversation_summaries.db"
AGY_PATH = shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

AVAILABLE_MODELS = {
    "gemini-3.8-flash-high": "⚡ Gemini 3.8 Flash (High)",
    "gemini-3.8-flash-medium": "✨ Gemini 3.8 Flash (Medium)",
    "gemini-3.8-flash-low": "🌱 Gemini 3.8 Flash (Low)",
    "claude-sonnet-4-6": "🧠 Claude Sonnet 4.6 (Thinking)",
    "claude-opus-4-6-thinking": "👑 Claude Opus 4.6 (Thinking)",
    "gpt-oss-120b-medium": "🌐 GPT-OSS 120B (Medium)",
}
DEFAULT_MODEL = "gemini-3.8-flash-medium"

# In-memory registry of running tasks: user_id -> asyncio.subprocess.Process
active_tasks: dict[str, asyncio.subprocess.Process] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def check_auth(func):
    """Decorator to enforce whitelist user authorization."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user and ALLOWED_USERS and str(user.id) not in ALLOWED_USERS:
            logger.warning(f"Unauthorized access attempt by user ID {user.id} (@{user.username})")
            if update.message:
                await update.message.reply_text(
                    f"⛔ **Akses Ditolak**\nTelegram User ID Anda (`{user.id}`) belum terdaftar di whitelist bot.",
                    parse_mode="Markdown",
                )
            elif update.callback_query:
                await update.callback_query.answer("⛔ Akses ditolak: ID Anda belum terdaftar.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def load_sessions() -> dict[str, dict]:
    """Load sessions supporting both legacy string format and v0.2 structured format."""
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                normalized: dict[str, dict] = {}
                for uid, val in data.items():
                    if isinstance(val, str):
                        normalized[uid] = {
                            "conversation_id": val,
                            "model": DEFAULT_MODEL,
                        }
                    elif isinstance(val, dict):
                        normalized[uid] = {
                            "conversation_id": val.get("conversation_id"),
                            "model": val.get("model", DEFAULT_MODEL),
                        }
                return normalized
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
    return {}


def save_sessions(sessions: dict[str, dict]) -> None:
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
    """Split and send message with safe Markdown fallback."""
    chunk_size = 4000
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            # Fallback to plain text if Markdown parsing fails
            await update.message.reply_text(chunk)


def extract_images_from_text(text: str) -> tuple[str, list[tuple[Path, str]]]:
    """
    Extracts local image filepaths from Markdown format ![alt](path) and raw paths.
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

    # 2. Match raw local file paths: /Users/.../something.png
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

    if cleaned_text.strip():
        await send_chunked_message(update, cleaned_text)

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

    if user_id in active_tasks:
        await update.message.reply_text(
            "⏳ Anda masih memiliki tugas yang sedang berjalan. Tunggu hingga selesai atau gunakan /stop untuk membatalkannya."
        )
        return

    sessions = load_sessions()
    user_data = sessions.get(user_id, {})
    conv_id = user_data.get("conversation_id")
    selected_model = user_data.get("model", DEFAULT_MODEL)

    # Build agy command
    cmd = [AGY_PATH, "-p", user_prompt]
    if conv_id:
        cmd.extend(["--conversation", conv_id])
    if selected_model:
        cmd.extend(["--model", selected_model])
    if AUTO_APPROVE:
        cmd.append("--dangerously-skip-permissions")

    # Send status message with interactive Cancel button
    cancel_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Batalkan Proses", callback_data=f"cancel_task:{user_id}")]
    ])
    status_msg = await update.message.reply_text(
        f"⚙️ *Antigravity ({AVAILABLE_MODELS.get(selected_model, selected_model)}) sedang memproses...*",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard,
    )

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
        active_tasks[user_id] = proc

        stdout, stderr = await proc.communicate()
        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()

        # Update session conversation_id if new
        latest_id = get_latest_conversation_id()
        if latest_id:
            if user_id not in sessions:
                sessions[user_id] = {"conversation_id": latest_id, "model": selected_model}
            else:
                sessions[user_id]["conversation_id"] = latest_id
            save_sessions(sessions)

        reply = out_text or err_text or "_(Tidak ada output dari agent)_"
        await dispatch_reply_with_media(update, reply)

    except asyncio.CancelledError:
        logger.info(f"Task for user {user_id} was cancelled.")
        await update.message.reply_text("🛑 *Tugas telah dibatalkan.*", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Terjadi error saat menjalankan agy:\n{e}")
    finally:
        active_tasks.pop(user_id, None)
        stop_typing.set()
        await typing_task
        try:
            await status_msg.delete()
        except Exception:
            pass


@check_auth
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🤖 **Antigravity CLI (agy) Bot Bridge v0.2.0**\n\n"
        "Bot siap menerima teks & gambar, lalu meneruskannya ke Antigravity CLI.\n\n"
        "Fitur Utama:\n"
        "• `/model` - Ganti model AI (Gemini Flash, Claude Sonnet, Opus)\n"
        "• `/menu` - Akses cepat Git status, sistem host, & info sesi\n"
        "• `/stop` atau tombol 'Batalkan' - Hentikan proses aktif\n"
        "• `/new` - Reset sesi percakapan\n"
        "• `/session` - Cek ID sesi aktif\n"
        "• `/sendimg <path>` - Kirim gambar lokal host ke chat\n"
        "• `/help` - Panduan bantuan lengkap\n"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


@check_auth
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any active agy subprocess for this user."""
    user_id = str(update.effective_user.id)
    proc = active_tasks.get(user_id)
    if proc:
        try:
            proc.terminate()
        except Exception as e:
            logger.error(f"Error terminating process: {e}")
        await update.message.reply_text("🛑 *Perintah pembatalan dikirim ke Antigravity CLI.*", parse_mode="Markdown")
    else:
        await update.message.reply_text("ℹ️ Tidak ada tugas aktif yang sedang berjalan.")


@check_auth
async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display interactive inline model switcher."""
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_model = sessions.get(user_id, {}).get("model", DEFAULT_MODEL)

    keyboard = []
    for model_key, model_label in AVAILABLE_MODELS.items():
        is_selected = " ✅" if model_key == current_model else ""
        keyboard.append([
            InlineKeyboardButton(f"{model_label}{is_selected}", callback_data=f"select_model:{model_key}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🤖 **Pilih Model Antigravity AI**\n\nModel aktif saat ini: `{current_model}`\nSilakan pilih model untuk sesi Anda:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def select_model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle model selection from inline keyboard."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("select_model:"):
        model_key = data.split(":", 1)[1]
        user_id = str(update.effective_user.id)
        if model_key not in AVAILABLE_MODELS:
            await query.edit_message_text("❌ Model tidak valid.")
            return

        sessions = load_sessions()
        if user_id not in sessions:
            sessions[user_id] = {"conversation_id": None, "model": model_key}
        else:
            sessions[user_id]["model"] = model_key
        save_sessions(sessions)

        model_label = AVAILABLE_MODELS[model_key]
        await query.edit_message_text(
            f"✅ **Model berhasil diubah!**\n\nModel aktif sekarang:\n`{model_label}` (`{model_key}`)",
            parse_mode="Markdown",
        )


@check_auth
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display Quick Actions hub."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Git Status", callback_data="menu:git_status"),
            InlineKeyboardButton("🔄 Reset Sesi", callback_data="menu:reset_session"),
        ],
        [
            InlineKeyboardButton("🔍 Info Host", callback_data="menu:sys_info"),
            InlineKeyboardButton("ℹ️ Info Sesi", callback_data="menu:info"),
        ],
        [
            InlineKeyboardButton("❌ Tutup Menu", callback_data="menu:close"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎛️ **Quick Actions Hub (v0.2.0)**\nPilih tindakan cepat di bawah ini:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Quick Actions callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user_id = str(update.effective_user.id)

    if data == "menu:git_status":
        await query.edit_message_text("⏳ Memeriksa status git...")
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "status", "-s",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            res = stdout.decode().strip() or "Bersih (tidak ada file berubah)."
            await query.edit_message_text(f"📊 **Git Status:**\n```\n{res}\n```", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Gagal cek git: {e}")

    elif data == "menu:reset_session":
        sessions = load_sessions()
        if user_id in sessions:
            sessions[user_id]["conversation_id"] = None
            save_sessions(sessions)
        await query.edit_message_text("🔄 Sesi direset. Pesan berikutnya akan memulai percakapan baru.")

    elif data == "menu:sys_info":
        try:
            uname = os.uname()
            info = (
                f"💻 **Host OS**: `{uname.sysname} {uname.release} ({uname.machine})`\n"
                f"🕒 **Waktu Host**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                f"⚡ **Executable agy**: `{AGY_PATH}`"
            )
            await query.edit_message_text(info, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"Host info error: {e}")

    elif data == "menu:info":
        sessions = load_sessions()
        u_data = sessions.get(user_id, {})
        conv = u_data.get("conversation_id") or "Belum ada (Sesi Baru)"
        model = u_data.get("model", DEFAULT_MODEL)
        label = AVAILABLE_MODELS.get(model, model)
        await query.edit_message_text(
            f"ℹ️ **Informasi Sesi Pengguna**\n• User ID: `{user_id}`\n• Model AI: `{label}`\n• Active Conv ID:\n`{conv}`",
            parse_mode="Markdown",
        )

    elif data == "menu:close":
        await query.delete_message()


async def cancel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle task cancellation callback from inline button."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("cancel_task:"):
        target_uid = data.split(":", 1)[1]
        user_id = str(update.effective_user.id)
        if target_uid != user_id:
            await query.answer("Hanya pemilik task yang dapat membatalkannya.", show_alert=True)
            return

        proc = active_tasks.get(user_id)
        if proc:
            try:
                proc.terminate()
            except Exception as e:
                logger.error(f"Error terminating proc: {e}")
            await query.edit_message_text("🛑 *Tugas berhasil dibatalkan oleh pengguna.*", parse_mode="Markdown")
        else:
            await query.edit_message_text("ℹ️ Tidak ada tugas aktif yang sedang berjalan.")


@check_auth
async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    if user_id in sessions:
        sessions[user_id]["conversation_id"] = None
        save_sessions(sessions)
    await update.message.reply_text("🔄 Sesi direset. Pesan berikutnya akan memulai percakapan baru.")


@check_auth
async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    conv_id = sessions.get(user_id, {}).get("conversation_id")
    if conv_id:
        await update.message.reply_text(f"📌 Active Conversation ID:\n`{conv_id}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Belum ada sesi aktif. Kirim pesan untuk memulai sesi.")


@check_auth
async def sendimg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows manual sending of any image path on the host."""
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


@check_auth
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Panduan Penggunaan v0.2.0**\n\n"
        "- Kirim teks langsung untuk bertanya/memberi perintah ke `agy`.\n"
        "- `/model` : Pilih model AI (Gemini Flash, Claude Sonnet, Opus).\n"
        "- `/menu` : Akses cepat Git status, info sistem host, & info sesi.\n"
        "- `/stop` atau `/cancel` : Hentikan proses yang sedang berjalan.\n"
        "- Kirim foto untuk dianalisis oleh `agy`.\n"
        "- `/sendimg <path>` : Kirim file gambar lokal host ke Telegram.\n"
        "- `/new` : Mulai sesi percakapan baru."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


@check_auth
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    await run_agy_prompt(update, context, update.message.text.strip())


@check_auth
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
    if ALLOWED_USERS:
        print(f"Whitelist aktif untuk user ID: {', '.join(ALLOWED_USERS)}")
    else:
        print("PERINGATAN: Whitelist kosong, bot terbuka untuk publik.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("cancel", stop_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("reset", new_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("sendimg", sendimg_command))
    app.add_handler(CommandHandler("help", help_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(select_model_callback, pattern=r"^select_model:"))
    app.add_handler(CallbackQueryHandler(menu_callback_handler, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(cancel_callback_handler, pattern=r"^cancel_task:"))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("Bot v0.2.0 berjalan. Tekan Ctrl+C untuk berhenti.")
    app.run_polling()


if __name__ == "__main__":
    main()
