#!/usr/bin/env python3
"""
Antigravity CLI (agy) - Telegram Bot Bridge v0.2.0
High-Performance Async Bridge with Live 1-Bubble Streaming, Deterministic Session Tracking,
FIFO Queue Management, Dynamic Heartbeat Monitor, and Clean Telegram HTML Formatting.
"""

import asyncio
import functools
import html
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
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

# Asynchronous Task Queues per user: user_id -> asyncio.Queue
user_queues: dict[str, asyncio.Queue] = {}

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
                    f"⛔ <b>Akses Ditolak</b>\nTelegram User ID Anda (<code>{user.id}</code>) belum terdaftar di whitelist bot.",
                    parse_mode="HTML",
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


def markdown_to_telegram_html(text: str) -> str:
    """
    Converts GitHub-flavored Markdown into clean, robust Telegram HTML.
    Eliminates raw asterisks, hashes, and unsupported protocols.
    """
    if not text:
        return ""

    # 1. Protect code blocks
    code_blocks: list[str] = []
    def save_code_block(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2)
        idx = len(code_blocks)
        escaped_code = html.escape(code.strip())
        tag = (
            f'<pre><code class="language-{lang}">{escaped_code}</code></pre>'
            if lang
            else f"<pre><code>{escaped_code}</code></pre>"
        )
        code_blocks.append(tag)
        return f"%%%CODE_BLOCK_{idx}%%%"

    text = re.sub(r"```(\w*)\n?([\s\S]*?)```", save_code_block, text)

    # 2. Convert local file links [`path`](file://...) to clean code elements
    file_links: list[str] = []
    def save_file_link(match: re.Match) -> str:
        cap = match.group(1).strip()
        if cap.startswith("`") and cap.endswith("`"):
            cap = cap[1:-1]
        idx = len(file_links)
        file_links.append(f"<code>{html.escape(cap)}</code>")
        return f"%%%FILE_LINK_{idx}%%%"

    text = re.sub(r"\[(.*?)\]\(file:\/\/[^\)]+\)", save_file_link, text)

    # 3. Protect inline code
    inline_codes: list[str] = []
    def save_inline_code(match: re.Match) -> str:
        code = match.group(1)
        idx = len(inline_codes)
        inline_codes.append(f"<code>{html.escape(code)}</code>")
        return f"%%%INLINE_CODE_{idx}%%%"

    text = re.sub(r"`([^`\n]+)`", save_inline_code, text)

    # 4. Escape remaining HTML entities in regular prose
    text = html.escape(text)

    # 5. Convert Headers: #, ##, ### -> <b>Header</b>
    text = re.sub(r"^(?:#{1,6})\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 6. Convert Bold: **text** or __text__ -> <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 7. Convert Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r"(?<!\w)\*([^\*\n]+)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", text)

    # 8. Strikethrough
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 9. HTTP/HTTPS hyperlinks
    text = re.sub(r"\[(.*?)\]\((https?:\/\/[^\s\)]+)\)", r'<a href="\2">\1</a>', text)

    # 10. Horizontal dividers
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "—————————————", text, flags=re.MULTILINE)

    # 11. Restore protected placeholders
    for idx, code_html in enumerate(file_links):
        text = text.replace(f"%%%FILE_LINK_{idx}%%%", code_html)
    for idx, code_html in enumerate(inline_codes):
        text = text.replace(f"%%%INLINE_CODE_{idx}%%%", code_html)
    for idx, block_html in enumerate(code_blocks):
        text = text.replace(f"%%%CODE_BLOCK_{idx}%%%", block_html)

    return text


async def send_clean_html_message(update: Update, text: str):
    """Split and transmit message formatted with safe Telegram HTML."""
    html_text = markdown_to_telegram_html(text)
    chunk_size = 4000
    for i in range(0, len(html_text), chunk_size):
        chunk = html_text[i : i + chunk_size]
        try:
            await update.message.reply_text(chunk, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Telegram HTML parse error: {e}. Falling back to clean plain text.")
            clean_plain = re.sub(r"<[^>]+>", "", chunk)
            await update.message.reply_text(clean_plain)


def extract_images_from_text(text: str) -> tuple[str, list[tuple[Path, str]]]:
    """Extracts referenced local images from Markdown syntax and filepaths."""
    found_images: list[tuple[Path, str]] = []
    seen_paths: set[str] = set()

    md_pattern = r"!\[(.*?)\]\(\s*(?:file:\/\/)?([^\s\)]+)\s*\)"

    def replace_md(match: re.Match) -> str:
        caption = match.group(1).strip()
        raw_path = match.group(2).strip()
        p = Path(raw_path).expanduser().resolve()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            if str(p) not in seen_paths:
                found_images.append((p, caption))
                seen_paths.add(str(p))
            return f"🖼️ <b>[{caption or p.name}]</b>"
        return match.group(0)

    cleaned_text = re.sub(md_pattern, replace_md, text)

    raw_path_pattern = r'(?<!\()(\/(?:Users|tmp|var|private)[^\s"\'<>`*]+\.(?:png|jpg|jpeg|webp|gif|bmp))'
    for match in re.finditer(raw_path_pattern, cleaned_text):
        raw_path = match.group(1)
        p = Path(raw_path).expanduser().resolve()
        if p.is_file() and str(p) not in seen_paths:
            found_images.append((p, p.name))
            seen_paths.add(str(p))

    return cleaned_text, found_images


async def dispatch_reply_with_media(update: Update, text: str):
    """Deliver processed message and send detected images as photo/document attachments."""
    cleaned_text, images = extract_images_from_text(text)

    if cleaned_text.strip():
        await send_clean_html_message(update, cleaned_text)

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


async def monitor_heartbeat(
    update: Update,
    user_id: str,
    done_event: asyncio.Event,
    get_last_activity_time,
):
    """Monitors stream activity and alerts user if inactive for >120s."""
    notified = False
    while not done_event.is_set():
        try:
            await asyncio.wait_for(done_event.wait(), timeout=10.0)
            break
        except asyncio.TimeoutError:
            pass

        inactive_seconds = time.time() - get_last_activity_time()
        if inactive_seconds > 120 and not notified:
            notified = True
            try:
                cancel_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛑 Hentikan Sekarang", callback_data=f"cancel_task:{user_id}")]
                ])
                await update.message.reply_text(
                    "⚠️ <b>Pemberitahuan Aktivitas:</b>\n"
                    "Tidak ada respons dari Antigravity selama 2 menit. "
                    "CLI kemungkinan sedang melakukan kompilasi/analisis berat, atau koneksi jaringan terputus.",
                    parse_mode="HTML",
                    reply_markup=cancel_kb,
                )
            except Exception:
                pass


async def execute_agy_turn(update: Update, context: ContextTypes.DEFAULT_TYPE, user_prompt: str):
    """Executes a prompt turn using NDJSON streaming with 1-bubble real-time progress."""
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id

    sessions = load_sessions()
    user_data = sessions.get(user_id, {})
    conv_id = user_data.get("conversation_id")
    selected_model = user_data.get("model", DEFAULT_MODEL)
    model_label = AVAILABLE_MODELS.get(selected_model, selected_model)

    cmd = [AGY_PATH, "-p", user_prompt, "--output-format", "stream-json"]
    if conv_id:
        cmd.extend(["--conversation", conv_id])
    if selected_model:
        cmd.extend(["--model", selected_model])
    if AUTO_APPROVE:
        cmd.append("--dangerously-skip-permissions")

    cancel_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Batalkan Proses", callback_data=f"cancel_task:{user_id}")]
    ])

    status_msg = await update.message.reply_text(
        f"⚙️ <b>Antigravity</b> (<i>{model_label}</i>) sedang mempersiapkan...",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )

    accumulated_text = ""
    current_status = "Sedang berpikir..."
    last_edit_time = time.time()
    last_stream_activity = time.time()
    done_event = asyncio.Event()

    heartbeat_task = asyncio.create_task(
        monitor_heartbeat(update, user_id, done_event, lambda: last_stream_activity)
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

        # Stream reader loop
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            last_stream_activity = time.time()
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            try:
                data = json.loads(line_str)
                event = data.get("event")

                # Deterministic conversation_id from stream init (No SQLite race condition!)
                if event == "init":
                    new_conv = data.get("conversation_id")
                    if new_conv:
                        sessions[user_id] = {
                            "conversation_id": new_conv,
                            "model": selected_model,
                        }
                        save_sessions(sessions)

                elif event == "step_update":
                    step = data.get("step_update", {})
                    stype = step.get("step_type")
                    delta = step.get("text_delta")
                    if delta:
                        accumulated_text += delta

                    if stype == "agent_response":
                        current_status = "✍️ Menulis jawaban..."
                    elif stype == "tool_call" or "tool" in str(stype):
                        tool_name = step.get("tool_name", "alat sistem")
                        current_status = f"🛠️ Menjalankan {tool_name}..."
                    elif stype == "user_input":
                        current_status = "🧠 Menganalisis instruksi..."

                elif event == "result":
                    res = data.get("result", {})
                    final_res = res.get("response")
                    if final_res:
                        accumulated_text = final_res

                # Single bubble debounced update (1.8s interval)
                now = time.time()
                if now - last_edit_time >= 1.8 and accumulated_text.strip():
                    last_edit_time = now
                    preview = (
                        accumulated_text[-400:]
                        if len(accumulated_text) > 400
                        else accumulated_text
                    )
                    bubble_text = (
                        f"⚙️ <b>Antigravity</b> (<i>{model_label}</i>)\n"
                        f"<b>Status:</b> {current_status}\n\n"
                        f"<code>{html.escape(preview.strip() or '...')}</code>"
                    )
                    try:
                        await status_msg.edit_text(
                            bubble_text,
                            parse_mode="HTML",
                            reply_markup=cancel_keyboard,
                        )
                    except Exception:
                        pass

            except json.JSONDecodeError:
                continue

        await proc.wait()

    except asyncio.CancelledError:
        logger.info(f"Task for user {user_id} was cancelled.")
        await update.message.reply_text("🛑 <b>Tugas telah dibatalkan.</b>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Terjadi error saat mengeksekusi agy:\n<code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        done_event.set()
        await heartbeat_task
        active_tasks.pop(user_id, None)

        try:
            await status_msg.delete()
        except Exception:
            pass

        final_reply = accumulated_text.strip() or "<i>(Tidak ada keluaran dari Antigravity)</i>"
        await dispatch_reply_with_media(update, final_reply)

        # Process next task in user's queue if any
        if user_id in user_queues and not user_queues[user_id].empty():
            try:
                next_update, next_context, next_prompt = user_queues[user_id].get_nowait()
                asyncio.create_task(execute_agy_turn(next_update, next_context, next_prompt))
            except asyncio.QueueEmpty:
                pass


async def enqueue_or_run_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_prompt: str):
    """Enqueues task if one is already running, or runs immediately."""
    user_id = str(update.effective_user.id)
    if user_id not in user_queues:
        user_queues[user_id] = asyncio.Queue()

    if user_id in active_tasks:
        await user_queues[user_id].put((update, context, user_prompt))
        qsize = user_queues[user_id].qsize()
        cancel_q_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Batalkan Semua Antrean", callback_data=f"cancel_queue:{user_id}")]
        ])
        await update.message.reply_text(
            f"📥 <b>Pesan Anda masuk ke antrean (#{qsize})</b>\n"
            f"Tugas yang sedang berjalan akan diselesaikan terlebih dahulu.",
            parse_mode="HTML",
            reply_markup=cancel_q_btn,
        )
        return

    await execute_agy_turn(update, context, user_prompt)


@check_auth
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🤖 <b>Antigravity CLI (agy) Bot Bridge v0.2.0</b>\n\n"
        "Bot siap menerima teks & gambar untuk diteruskan ke Antigravity AI Coding Agent.\n\n"
        "<b>Perintah Cepat:</b>\n"
        "• <code>/model</code> — Ganti model AI (Gemini Flash, Claude Sonnet, Opus)\n"
        "• <code>/menu</code> — Dashboard aksi cepat (Git status, sistem host, dll.)\n"
        "• <code>/stop</code> — Hentikan proses aktif yang sedang berjalan\n"
        "• <code>/new</code> — Reset sesi percakapan\n"
        "• <code>/session</code> — Cek ID sesi aktif\n"
        "• <code>/help</code> — Buka panduan bantuan\n\n"
        "<i>💡 Tekan tombol <b>[ ≡ Menu ]</b> di samping kiri kolom chat untuk akses perintah kapan saja.</i>"
    )
    # Remove any stuck bottom keyboard permanently
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())


@check_auth
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel active subprocess and flush queue."""
    user_id = str(update.effective_user.id)
    cancelled_something = False

    # 1. Terminate running process
    proc = active_tasks.get(user_id)
    if proc:
        try:
            proc.terminate()
            cancelled_something = True
        except Exception as e:
            logger.error(f"Error terminating process: {e}")

    # 2. Flush pending queue
    if user_id in user_queues:
        while not user_queues[user_id].empty():
            try:
                user_queues[user_id].get_nowait()
                cancelled_something = True
            except asyncio.QueueEmpty:
                break

    if cancelled_something:
        await update.message.reply_text("🛑 <b>Tugas dan antrean aktif berhasil dihentikan.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ Tidak ada tugas atau antrean yang sedang berjalan.")


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
        f"🤖 <b>Pilih Model Antigravity AI</b>\n\nModel aktif saat ini: <code>{current_model}</code>\nPilih model untuk sesi percakapan Anda:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


async def select_model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle model selection callback."""
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
            f"✅ <b>Model berhasil diubah!</b>\n\nModel aktif sekarang:\n<code>{model_label}</code> (<code>{model_key}</code>)",
            parse_mode="HTML",
        )


@check_auth
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display clean Quick Actions inline dashboard."""
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
        "🎛️ <b>Quick Actions Hub</b>\nPilih tindakan cepat di bawah ini:",
        reply_markup=reply_markup,
        parse_mode="HTML",
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
            await query.edit_message_text(f"📊 <b>Git Status:</b>\n<pre><code>{html.escape(res)}</code></pre>", parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ Gagal cek git: {e}")

    elif data == "menu:reset_session":
        sessions = load_sessions()
        if user_id in sessions:
            sessions[user_id]["conversation_id"] = None
            save_sessions(sessions)
        await query.edit_message_text("🔄 <b>Sesi direset.</b> Pesan berikutnya akan memulai percakapan baru.", parse_mode="HTML")

    elif data == "menu:sys_info":
        try:
            uname = os.uname()
            info = (
                f"💻 <b>Host OS</b>: <code>{uname.sysname} {uname.release} ({uname.machine})</code>\n"
                f"🕒 <b>Waktu Host</b>: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
                f"⚡ <b>Executable agy</b>: <code>{AGY_PATH}</code>"
            )
            await query.edit_message_text(info, parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"Host info error: {e}")

    elif data == "menu:info":
        sessions = load_sessions()
        u_data = sessions.get(user_id, {})
        conv = u_data.get("conversation_id") or "Belum ada (Sesi Baru)"
        model = u_data.get("model", DEFAULT_MODEL)
        label = AVAILABLE_MODELS.get(model, model)
        await query.edit_message_text(
            f"ℹ️ <b>Informasi Sesi Pengguna</b>\n• User ID: <code>{user_id}</code>\n• Model AI: <code>{label}</code>\n• Active Conv ID:\n<code>{conv}</code>",
            parse_mode="HTML",
        )

    elif data == "menu:close":
        await query.delete_message()


async def cancel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle task cancellation and queue cancellation callbacks."""
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
            await query.edit_message_text("🛑 <b>Tugas berhasil dibatalkan oleh pengguna.</b>", parse_mode="HTML")
        else:
            await query.edit_message_text("ℹ️ Tidak ada tugas aktif yang sedang berjalan.")

    elif data.startswith("cancel_queue:"):
        target_uid = data.split(":", 1)[1]
        user_id = str(update.effective_user.id)
        if target_uid != user_id:
            await query.answer("Hanya pemilik antrean yang dapat membatalkannya.", show_alert=True)
            return

        cleared = 0
        if user_id in user_queues:
            while not user_queues[user_id].empty():
                try:
                    user_queues[user_id].get_nowait()
                    cleared += 1
                except asyncio.QueueEmpty:
                    break
        await query.edit_message_text(f"🗑️ <b>Semua antrean ({cleared} pesan) berhasil dibatalkan.</b>", parse_mode="HTML")


@check_auth
async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    if user_id in sessions:
        sessions[user_id]["conversation_id"] = None
        save_sessions(sessions)
    await update.message.reply_text("🔄 <b>Sesi direset.</b> Pesan berikutnya akan memulai percakapan baru.", parse_mode="HTML")


@check_auth
async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    conv_id = sessions.get(user_id, {}).get("conversation_id")
    if conv_id:
        await update.message.reply_text(f"📌 <b>Active Conversation ID:</b>\n<code>{conv_id}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("Belum ada sesi aktif. Kirim pesan untuk memulai sesi.")


@check_auth
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>📖 Panduan Penggunaan Antigravity Bridge</b>\n\n"
        "Cukup ketik pesan teks atau kirim gambar untuk langsung berinteraksi dengan AI Coding Agent.\n\n"
        "<b>Daftar Perintah:</b>\n"
        "• <code>/menu</code> — Buka Quick Actions Hub (Git status, info host, dll.)\n"
        "• <code>/model</code> — Ganti model AI (Gemini Flash, Claude Sonnet, Opus)\n"
        "• <code>/stop</code> atau <code>/cancel</code> — Hentikan proses aktif dan bersihkan antrean\n"
        "• <code>/new</code> — Reset sesi percakapan untuk topik baru\n"
        "• <code>/session</code> — Cek ID sesi aktif dari Antigravity\n"
        "• <code>/help</code> — Menampilkan panduan bantuan ini\n\n"
        "<i>💡 Tips: Anda dapat menekan tombol <b>[ ≡ Menu ]</b> di samping kiri kolom chat untuk akses cepat perintah.</i>"
    )
    await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())


@check_auth
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    await enqueue_or_run_task(update, context, update.message.text.strip())


@check_auth
async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photos sent by the user to the bot."""
    if not update.message or not update.message.photo:
        return

    photo = update.message.photo[-1]  # Highest resolution
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
    await enqueue_or_run_task(update, context, prompt_with_image)


async def post_init(application):
    """Register native [≡ Menu] command list in Telegram client."""
    commands = [
        BotCommand("menu", "🎛️ Quick Actions Hub"),
        BotCommand("model", "🤖 Ganti Model AI Antigravity"),
        BotCommand("stop", "🛑 Batalkan Proses Berjalan"),
        BotCommand("new", "🔄 Reset Sesi Percakapan"),
        BotCommand("session", "📌 Cek ID Sesi Aktif"),
        BotCommand("help", "📖 Panduan Bantuan"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands successfully registered to Telegram menu.")


def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN belum diset di .env!")
        return

    print(f"Menggunakan executable agy di: {AGY_PATH}")
    if ALLOWED_USERS:
        print(f"Whitelist aktif untuk user ID: {', '.join(ALLOWED_USERS)}")
    else:
        print("PERINGATAN: Whitelist kosong, bot terbuka untuk publik.")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("cancel", stop_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("reset", new_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("help", help_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(select_model_callback, pattern=r"^select_model:"))
    app.add_handler(CallbackQueryHandler(menu_callback_handler, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(cancel_callback_handler, pattern=r"^(cancel_task|cancel_queue):"))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("Bot v0.2.0 berjalan dengan Live Streaming 1-Bubble. Tekan Ctrl+C untuk berhenti.")
    app.run_polling()


if __name__ == "__main__":
    main()
