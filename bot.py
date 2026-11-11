#!/usr/bin/env python3
"""
Antigravity CLI (agy) - Telegram Bot Bridge v0.2.0
High-Performance Async Bridge with Live 1-Bubble Streaming, Deterministic Session Tracking,
FIFO Queue Management, Dynamic Heartbeat Monitor, HTTP Connection Pooling,
Image Preprocessing, Isolated Workspace Routing, and Custom Casual Persona.
"""

import asyncio
import functools
import html
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
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
from telegram.request import HTTPXRequest

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTO_APPROVE = os.getenv("AUTO_APPROVE_TOOLS", "false").lower() == "true"
SESSIONS_FILE = BASE_DIR / "sessions.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Default dedicated isolated workspace for Telegram bot tasks
DEFAULT_WORKSPACE = Path.home() / "agy-workspace"
DEFAULT_WORKSPACE.mkdir(parents=True, exist_ok=True)

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
DEFAULT_MODEL = "gemini-3.8-flash-high"

# Dedicated Casual & Chillout Persona for Telegram Bot
TELEGRAM_PERSONA_INSTRUCTION = """[SYSTEM INSTRUCTION: TELEGRAM BOT PERSONAL ASSISTANT]
Kamu adalah AI Personal Assistant pribadi yang terhubung langsung melalui chat Telegram.
Karakter & Gaya Komunikasi Utama:
1. Super santai, gaul, chillout, friendly, asik layaknya teman ngoding akrab di tongkrongan ("gue-lu" / bahasa kasual santai). JAUHI gaya bahasa kaku, formal korporat, atau basa-basi robotik seperti "Tentu, ini adalah langkah-langkahnya" atau "Baik, saya akan membantu Anda".
2. Natural humor & jokes: Suka ngelempar jokes lucu secara natural kalau ada bahannya (nggak maksa garing).
3. Roasting tipis-tipis secara akrab/lucu kalau user blunder koding, salah ketik, atau nanya hal aneh, tapi langsung kasih solusi yang cerdas, solutif, dan to-the-point!
4. Format layar HP (Telegram): Jawaban harus padat, to-the-point, enak dibaca di mobile (gunakan poin singkat, formatting tebal/kode yang rapi). Hindari teks esai panjang bertele-tele kecuali diminta.
5. Workspace & Isolasi: Saat sesi baru dimulai, kamu berada di workspace bersih. Jangan berasumsi sedang mengerjakan bot ini atau proyek lama kecuali user menyebutkannya atau berada di folder terkait.
"""

# Global concurrency limiter: maximum 2 heavy tasks across all users to preserve host RAM/CPU
GLOBAL_SEMAPHORE = asyncio.Semaphore(2)

# In-memory registry of running tasks: user_id -> asyncio.subprocess.Process
active_tasks: dict[str, asyncio.subprocess.Process] = {}

# Asynchronous Task Queues per user: user_id -> asyncio.Queue
user_queues: dict[str, asyncio.Queue] = {}

# Background caffeinate process handle
active_caffeinate_proc: Optional[asyncio.subprocess.Process] = None

# Destructive command patterns blocked in /sh
DANGEROUS_SH_PATTERNS = [
    r"rm\s+-rf\s+[\/~]",
    r"mkfs",
    r"dd\s+if=",
    r":\(\)\{.*\}",
    r">(\s*)\/dev\/[sh]da",
]

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
    """Load sessions supporting conversation ID, selected model, active workspace, and favorite projects."""
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                normalized: dict[str, dict] = {}
                default_favs = [str(DEFAULT_WORKSPACE), str(BASE_DIR)]
                for uid, val in data.items():
                    uid_str = str(uid)
                    if isinstance(val, str):
                        normalized[uid_str] = {
                            "conversation_id": val,
                            "model": DEFAULT_MODEL,
                            "workspace": str(DEFAULT_WORKSPACE),
                            "favorites": list(default_favs),
                        }
                    elif isinstance(val, dict):
                        favs = val.get("favorites")
                        if not isinstance(favs, list) or not favs:
                            favs = list(default_favs)
                        normalized[uid_str] = {
                            "conversation_id": val.get("conversation_id"),
                            "model": val.get("model", DEFAULT_MODEL),
                            "workspace": val.get("workspace", str(DEFAULT_WORKSPACE)),
                            "favorites": favs,
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


async def perform_full_reset(user_id: str) -> None:
    """
    Safely and deterministically resets a user session:
    1. Kills any active agy subprocess for this user.
    2. Purges any pending messages in user's queue.
    3. Explicitly wipes conversation_id in sessions.json so agy starts completely anew.
    """
    proc = active_tasks.pop(user_id, None)
    if proc:
        try:
            proc.terminate()
        except Exception as e:
            logger.warning(f"Error terminating process on reset: {e}")

    if user_id in user_queues:
        while not user_queues[user_id].empty():
            try:
                user_queues[user_id].get_nowait()
            except asyncio.QueueEmpty:
                break

    sessions = load_sessions()
    current_model = sessions.get(user_id, {}).get("model", DEFAULT_MODEL)
    current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))
    current_favs = sessions.get(user_id, {}).get("favorites") or [str(DEFAULT_WORKSPACE), str(BASE_DIR)]
    sessions[user_id] = {
        "conversation_id": None,
        "model": current_model,
        "workspace": current_ws,
        "favorites": current_favs,
    }
    save_sessions(sessions)
    logger.info(f"User {user_id} session completely reset (conversation_id cleared).")


def get_system_telemetry(user_workspace: str = "") -> str:
    """Collects real-time macOS telemetry (battery, RAM, disk, load, uptime, caffeinate)."""
    # 1. Battery
    batt_str = "Tidak terdeteksi"
    try:
        raw_batt = subprocess.check_output(["pmset", "-g", "batt"], text=True).strip()
        power_source = "🔌 AC Power" if "AC Power" in raw_batt else "🔋 Baterai"
        pct_match = re.search(r"(\d+%)", raw_batt)
        status_match = re.search(r"(discharging|charging|charged|finishing charge)", raw_batt, re.I)
        time_match = re.search(r"(\d+:\d+)\s+remaining", raw_batt)
        pct = pct_match.group(1) if pct_match else "?%"
        stat = status_match.group(1).capitalize() if status_match else ""
        rem = f" (~{time_match.group(1)})" if time_match else ""
        batt_str = f"{pct} ({power_source}, {stat}{rem})"
    except Exception as e:
        batt_str = f"Error: {e}"

    # 2. Caffeinate / Anti-sleep status
    caffeinate_status = "💤 Idle (Bisa Sleep)"
    try:
        pids = subprocess.check_output(["pgrep", "caffeinate"], text=True).strip()
        if pids:
            caffeinate_status = "☕ Aktif (Anti-Sleep ON)"
    except subprocess.CalledProcessError:
        pass
    except Exception:
        pass

    # 3. RAM usage
    ram_str = "Unknown"
    try:
        out_vm = subprocess.check_output(["vm_stat"], text=True)
        uname_m = subprocess.check_output(["uname", "-m"], text=True).strip()
        page_size = 16384 if "arm64" in uname_m else 4096
        free_pages = int(re.search(r"Pages free:\s+(\d+)", out_vm).group(1))
        spec_match = re.search(r"Pages speculative:\s+(\d+)", out_vm)
        spec_pages = int(spec_match.group(1)) if spec_match else 0
        total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        free_bytes = (free_pages + spec_pages) * page_size
        used_bytes = max(0, total_bytes - free_bytes)
        ram_str = f"{used_bytes / (1024**3):.1f} GB / {total_bytes / (1024**3):.1f} GB ({used_bytes / total_bytes * 100:.0f}%)"
    except Exception as e:
        ram_str = f"Error: {e}"

    # 4. Disk Usage
    try:
        du = shutil.disk_usage("/")
        free_gb = du.free / (1024**3)
        total_gb = du.total / (1024**3)
        used_pct = ((du.total - du.free) / du.total) * 100
        disk_str = f"{free_gb:.1f} GB free / {total_gb:.0f} GB ({used_pct:.0f}% terpakai)"
    except Exception as e:
        disk_str = f"Error: {e}"

    # 5. CPU Load
    try:
        l1, l5, l15 = os.getloadavg()
        load_str = f"{l1:.2f}, {l5:.2f}, {l15:.2f}"
    except Exception:
        load_str = "Unknown"

    # 6. Uptime
    try:
        raw_up = subprocess.check_output(["uptime"], text=True).strip()
        up_match = re.search(r"up\s+([^,]+)", raw_up)
        uptime_str = up_match.group(1).strip() if up_match else raw_up
    except Exception:
        uptime_str = "Unknown"

    ws_display = html.escape(user_workspace) if user_workspace else "Default"

    return (
        "🖥️ <b>MacBook Telemetry Hub</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🔋 <b>Baterai:</b> {html.escape(batt_str)}\n"
        f"☕ <b>Anti-Sleep:</b> {caffeinate_status}\n"
        f"🧠 <b>RAM:</b> {ram_str}\n"
        f"💾 <b>SSD:</b> {disk_str}\n"
        f"⚡ <b>CPU Load (1/5/15m):</b> <code>{load_str}</code>\n"
        f"⏱️ <b>Uptime:</b> {html.escape(uptime_str)}\n"
        f"📁 <b>Workspace:</b> <code>{ws_display}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>💡 Ketik <code>/caffeinate on</code> biar Mac nggak tidur pas ditinggal.</i>"
    )


def preprocess_and_resize_image(img_path: Path, max_dim: int = 1024, quality: int = 85) -> Path:
    """Downscales high-resolution images to accelerate AI vision processing and minimize RAM usage."""
    try:
        from PIL import Image
        with Image.open(img_path) as img:
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                opt_path = img_path.with_name(f"opt_{img_path.name}")
                img.save(opt_path, "JPEG", optimize=True, quality=quality)
                logger.info(f"Image compressed from {img_path.stat().st_size}B to {opt_path.stat().st_size}B")
                return opt_path
    except Exception as e:
        logger.warning(f"Could not resize image {img_path}: {e}")
    return img_path


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


def split_html_chunks(text: str, max_chars: int = 4000) -> list[str]:
    """Split formatted HTML text into chunks under Telegram's 4096 limit, preserving lines."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            if len(line) > max_chars:
                for i in range(0, len(line), max_chars):
                    chunks.append(line[i : i + max_chars])
            else:
                current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


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
    """Executes a prompt turn using NDJSON streaming with seamless 1-bubble real-time progress."""
    user_id = str(update.effective_user.id)

    sessions = load_sessions()
    user_data = sessions.get(user_id, {})
    conv_id = user_data.get("conversation_id")
    selected_model = user_data.get("model", DEFAULT_MODEL)
    model_label = AVAILABLE_MODELS.get(selected_model, selected_model)

    user_workspace = user_data.get("workspace") or str(DEFAULT_WORKSPACE)
    if not Path(user_workspace).is_dir():
        user_workspace = str(DEFAULT_WORKSPACE)

    # If this is the start of a new conversation turn, inject the casual persona instructions
    if not conv_id:
        cli_prompt = f"{TELEGRAM_PERSONA_INSTRUCTION}\n\n[Pesan Pengguna]:\n{user_prompt}"
    else:
        cli_prompt = user_prompt

    cmd = [AGY_PATH, "-p", cli_prompt, "--output-format", "stream-json"]
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
        # Wrap subprocess in global concurrency semaphore
        async with GLOBAL_SEMAPHORE:
            env = os.environ.copy()
            env["PATH"] = f"{Path.home()}/.local/bin:{env.get('PATH', '')}"

            # Execute strictly inside the user's dedicated workspace directory
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=user_workspace,
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

                    # Deterministic conversation_id from stream init
                    if event == "init":
                        new_conv = data.get("conversation_id")
                        if new_conv:
                            sessions[user_id] = {
                                "conversation_id": new_conv,
                                "model": selected_model,
                                "workspace": user_workspace,
                            }
                            save_sessions(sessions)

                    elif event == "step_update":
                        step = data.get("step_update", {})
                        stype = step.get("step_type")
                        delta = step.get("text_delta")
                        if delta:
                            accumulated_text += delta

                        if stype == "agent_response":
                            current_status = "✍️ Ngetik jawaban..."
                        elif stype == "tool_call" or "tool" in str(stype):
                            tool_name = step.get("tool_name", "alat sistem")
                            current_status = f"🛠️ Eksekusi {tool_name}..."
                        elif stype == "user_input":
                            current_status = "🧠 Mikir bentar..."

                    elif event == "result":
                        res = data.get("result", {})
                        final_res = res.get("response")
                        if final_res:
                            accumulated_text = final_res

                    # Single bubble debounced update (1.5s interval)
                    now = time.time()
                    if now - last_edit_time >= 1.5 and accumulated_text.strip():
                        last_edit_time = now
                        preview = (
                            accumulated_text[-350:]
                            if len(accumulated_text) > 350
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
        await update.message.reply_text(
            f"⚠️ Terjadi error saat mengeksekusi agy:\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
    finally:
        done_event.set()
        await heartbeat_task
        active_tasks.pop(user_id, None)

        # Morph the single bubble into the final clean answer seamlessly
        raw_final = accumulated_text.strip() or "(Tidak ada respon dari Antigravity)"
        cleaned_text, images = extract_images_from_text(raw_final)
        html_formatted = markdown_to_telegram_html(cleaned_text)
        chunks = split_html_chunks(html_formatted, max_chars=4000)

        # First chunk edits the existing status message (No bubble destruction/flicker)
        first_chunk = chunks[0] if chunks else "✅ <i>Beres!</i>"
        try:
            await status_msg.edit_text(first_chunk, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Error updating final bubble: {e}. Trying fallback...")
            try:
                clean_plain = html.unescape(re.sub(r"<[^>]+>", "", first_chunk))
                await status_msg.edit_text(clean_plain)
            except Exception:
                await update.message.reply_text(clean_plain)

        # Send any overflow chunks (>4000 chars) as subsequent replies
        for chunk in chunks[1:]:
            try:
                await update.message.reply_text(chunk, parse_mode="HTML")
            except Exception:
                clean_plain = html.unescape(re.sub(r"<[^>]+>", "", chunk))
                await update.message.reply_text(clean_plain)

        # Send extracted local images
        for img_path, caption in images:
            cap = f"🖼️ {caption}" if caption else None
            try:
                with open(img_path, "rb") as f:
                    await update.message.reply_photo(photo=f, caption=cap)
            except Exception as pe:
                logger.warning(f"Could not send photo {img_path}: {pe}. Sending as document...")
                try:
                    with open(img_path, "rb") as f:
                        await update.message.reply_document(document=f, caption=cap)
                except Exception as de:
                    logger.error(f"Failed to send image document {img_path}: {de}")
                    await update.message.reply_text(f"⚠️ Gagal mengirim file gambar: {img_path.name}")

        # Process next queued task if present
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
            f"📥 <b>Pesan masuk antrean (#{qsize})</b>\n"
            f"Tugas yang lagi jalan bakal diselesaikan dulu ya.",
            parse_mode="HTML",
            reply_markup=cancel_q_btn,
        )
        return

    await execute_agy_turn(update, context, user_prompt)


@check_auth
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))

    welcome = (
        "Yo! 🤖 <b>Antigravity Assistant siap nemenin lu ngoding!</b>\n\n"
        "Tanya apa aja, lempar cuplikan kode, atau kirim foto/screenshot error. Gua bakal bantu beresin langsung.\n\n"
        "<b>Perintah Cepat:</b>\n"
        f"• <code>/pwd</code> — Cek workspace aktif (saat ini: <code>{html.escape(current_ws)}</code>)\n"
        "• <code>/projects</code> — Switcher folder proyek via tombol tap\n"
        "• <code>/sys</code> — Pantau baterai, RAM, CPU & SSD Mac\n"
        "• <code>/caffeinate</code> — Mode Anti-Sleep biar Mac nggak tidur\n"
        "• <code>/screen</code> — Screenshot layar desktop Mac lu\n"
        "• <code>/get &lt;file&gt;</code> — Download file/laporan dari Mac ke HP\n"
        "• <code>/sh &lt;cmd&gt;</code> atau <code>$ &lt;cmd&gt;</code> — Terminal bash instan 200ms\n"
        "• <code>/model</code> — Ganti model AI (Gemini Flash, Claude Sonnet, Opus)\n"
        "• <code>/new</code> — Reset sesi percakapan untuk topik baru\n"
        "• <code>/menu</code> — Dashboard aksi cepat\n"
        "• <code>/help</code> — Panduan lengkap\n\n"
        "<i>💡 Tips: Tombol <b>[ ≡ Menu ]</b> di pojok kiri bawah selalu siap dipakai kapan aja.</i>"
    )
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())


@check_auth
async def pwd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current active workspace directory."""
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))
    await update.message.reply_text(
        f"📍 <b>Workspace Aktif Saat Ini:</b>\n<code>{html.escape(str(current_ws))}</code>",
        parse_mode="HTML",
    )


@check_auth
async def cd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change user active workspace directory."""
    user_id = str(update.effective_user.id)
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Format Perintah:</b>\n<code>/cd &lt;path&gt;</code>\n\n"
            "Contoh:\n"
            "• <code>/cd ~/Coding-Project/Laravel/laravel-web-berita</code>\n"
            "• <code>/cd ~/agy-workspace</code> (kembali ke default)",
            parse_mode="HTML",
        )
        return

    raw_path = " ".join(context.args).strip()
    target_path = Path(raw_path).expanduser().resolve()

    if not target_path.exists() or not target_path.is_dir():
        await update.message.reply_text(
            f"❌ <b>Folder nggak ketemu bro!</b>\nPath <code>{html.escape(str(target_path))}</code> nggak ada atau bukan folder direktori.",
            parse_mode="HTML",
        )
        return

    sessions = load_sessions()
    if user_id not in sessions:
        sessions[user_id] = {
            "conversation_id": None,
            "model": DEFAULT_MODEL,
            "workspace": str(target_path),
        }
    else:
        sessions[user_id]["workspace"] = str(target_path)
    save_sessions(sessions)

    await update.message.reply_text(
        f"📂 <b>Workspace Aktif Berhasil Dipindahkan!</b>\n"
        f"Lokasi: <code>{html.escape(str(target_path))}</code>\n\n"
        f"<i>Semua perintah dan inspeksi file berikutnya bakal jalan di folder ini.</i>",
        parse_mode="HTML",
    )


@check_auth
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel active subprocess and flush queue."""
    user_id = str(update.effective_user.id)
    cancelled_something = False

    proc = active_tasks.get(user_id)
    if proc:
        try:
            proc.terminate()
            cancelled_something = True
        except Exception as e:
            logger.error(f"Error terminating process: {e}")

    if user_id in user_queues:
        while not user_queues[user_id].empty():
            try:
                user_queues[user_id].get_nowait()
                cancelled_something = True
            except asyncio.QueueEmpty:
                break

    if cancelled_something:
        await update.message.reply_text("🛑 <b>Tugas dan antrean aktif berhasil disetop!</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ Lagi santai, nggak ada tugas atau antrean yang jalan kok.")


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
            sessions[user_id] = {
                "conversation_id": None,
                "model": model_key,
                "workspace": str(DEFAULT_WORKSPACE),
            }
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
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))

    keyboard = [
        [
            InlineKeyboardButton("📊 Git Status", callback_data="menu:git_status"),
            InlineKeyboardButton("🖥️ Mac Telemetry", callback_data="menu:telemetry"),
        ],
        [
            InlineKeyboardButton("📸 Screenshot Layar", callback_data="menu:screen"),
            InlineKeyboardButton("📂 Projects Switcher", callback_data="menu:projects"),
        ],
        [
            InlineKeyboardButton("☕ Toggle Anti-Sleep", callback_data="menu:caffeinate_toggle"),
            InlineKeyboardButton("🔄 Reset Sesi (/new)", callback_data="menu:reset_session"),
        ],
        [
            InlineKeyboardButton("📍 Cek PWD", callback_data="menu:pwd"),
            InlineKeyboardButton("🏠 Default Workspace", callback_data="menu:reset_ws"),
        ],
        [
            InlineKeyboardButton("ℹ️ Info Sesi", callback_data="menu:info"),
            InlineKeyboardButton("❌ Tutup Menu", callback_data="menu:close"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🎛️ <b>Quick Actions Hub</b>\n"
        f"📁 Workspace: <code>{html.escape(current_ws)}</code>\n\n"
        f"Pilih tindakan cepat:",
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
        await query.edit_message_text("⏳ Memeriksa status git di workspace...")
        sessions = load_sessions()
        current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "status", "-s",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=current_ws,
            )
            stdout, _ = await proc.communicate()
            res = stdout.decode().strip() or "Bersih (tidak ada file berubah)."
            await query.edit_message_text(f"📊 <b>Git Status ({html.escape(Path(current_ws).name)}):</b>\n<pre><code>{html.escape(res)}</code></pre>", parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ Gagal cek git: {e}")

    elif data == "menu:telemetry":
        sessions = load_sessions()
        current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))
        info = get_system_telemetry(current_ws)
        await query.edit_message_text(info, parse_mode="HTML")

    elif data == "menu:screen":
        await query.edit_message_text("📸 <i>Mengambil screenshot layar Mac...</i>", parse_mode="HTML")
        tmp_path = Path("/tmp") / f"mac_screen_{int(time.time())}.png"
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", str(tmp_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
                err_msg = stderr.decode().strip() or "could not create image from display"
                await query.edit_message_text(
                    f"⚠️ <b>Gagal Ambil Screenshot Layar</b>\n"
                    f"Penyebab: <code>{html.escape(err_msg)}</code>\n\n"
                    f"<i>Catatan: Layar Mac mungkin sedang sleep/terkunci, atau izin 'Screen Recording' belum diaktifkan di System Settings > Privacy & Security.</i>",
                    parse_mode="HTML"
                )
                return

            chat_id = update.effective_chat.id
            with open(tmp_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=f"📸 <b>Mac Desktop Snapshot</b>\n🕒 <i>{time.strftime('%H:%M:%S - %d %b %Y')}</i>",
                    parse_mode="HTML"
                )
            await query.delete_message()
        except Exception as e:
            await query.edit_message_text(f"❌ Error screenshot: {e}")
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    elif data == "menu:projects":
        sessions = load_sessions()
        u_data = sessions.get(user_id, {})
        current_ws = u_data.get("workspace", str(DEFAULT_WORKSPACE))
        favs = u_data.get("favorites") or [str(DEFAULT_WORKSPACE), str(BASE_DIR)]
        clean_favs = [f for f in dict.fromkeys(favs) if Path(f).exists()]
        if not clean_favs:
            clean_favs = [str(DEFAULT_WORKSPACE)]

        keyboard = []
        for idx, path_str in enumerate(clean_favs):
            p = Path(path_str)
            name = p.name or str(p)
            is_current = " ✅" if str(p) == str(current_ws) else ""
            keyboard.append([
                InlineKeyboardButton(f"📁 {name}{is_current}", callback_data=f"proj_switch:{idx}")
            ])
        bottom_row = []
        if current_ws not in clean_favs:
            bottom_row.append(InlineKeyboardButton("⭐ Bookmark Saat Ini", callback_data="proj_fav:add_current"))
        bottom_row.append(InlineKeyboardButton("❌ Tutup", callback_data="proj_fav:close"))
        keyboard.append(bottom_row)

        await query.edit_message_text(
            f"📂 <b>Project Workspace Switcher</b>\n"
            f"Workspace saat ini: <code>{html.escape(current_ws)}</code>\n\n"
            f"Pilih proyek tujuan untuk berpindah workspace:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "menu:caffeinate_toggle":
        global active_caffeinate_proc
        is_active = False
        try:
            res = subprocess.check_output(["pgrep", "caffeinate"], text=True).strip()
            if res:
                is_active = True
        except Exception:
            pass

        if is_active:
            # Turn off
            if active_caffeinate_proc and active_caffeinate_proc.returncode is None:
                active_caffeinate_proc.terminate()
                active_caffeinate_proc = None
            try:
                kproc = await asyncio.create_subprocess_exec("killall", "caffeinate")
                await kproc.wait()
            except Exception:
                pass
            await query.edit_message_text("💤 <b>Anti-Sleep Dimatikan.</b>\nMac sekarang dapat tidur normal.", parse_mode="HTML")
        else:
            # Turn on
            try:
                active_caffeinate_proc = await asyncio.create_subprocess_exec("caffeinate", "-dimsu")
                await query.edit_message_text("☕ <b>Anti-Sleep Dinyalakan!</b>\nMac tidak akan sleep saat Anda tinggalkan.", parse_mode="HTML")
            except Exception as e:
                await query.edit_message_text(f"❌ Gagal menyalakan anti-sleep: {e}")

    elif data == "menu:pwd":
        sessions = load_sessions()
        current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))
        await query.edit_message_text(f"📍 <b>Workspace Aktif:</b>\n<code>{html.escape(str(current_ws))}</code>", parse_mode="HTML")

    elif data == "menu:reset_ws":
        sessions = load_sessions()
        if user_id in sessions:
            sessions[user_id]["workspace"] = str(DEFAULT_WORKSPACE)
            save_sessions(sessions)
        await query.edit_message_text(f"🏠 <b>Workspace dikembalikan ke default:</b>\n<code>{DEFAULT_WORKSPACE}</code>", parse_mode="HTML")

    elif data == "menu:reset_session":
        await perform_full_reset(user_id)
        await query.edit_message_text("🔄 <b>Sesi berhasil direset total.</b>\nPesan berikutnya bakal mulai obrolan baru yang fresh!", parse_mode="HTML")

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
        conv = u_data.get("conversation_id") or "Fresh (Sesi Baru)"
        model = u_data.get("model", DEFAULT_MODEL)
        ws = u_data.get("workspace", str(DEFAULT_WORKSPACE))
        label = AVAILABLE_MODELS.get(model, model)
        await query.edit_message_text(
            f"ℹ️ <b>Informasi Sesi Pengguna</b>\n"
            f"• User ID: <code>{user_id}</code>\n"
            f"• Model AI: <code>{label}</code>\n"
            f"• Workspace: <code>{html.escape(ws)}</code>\n"
            f"• Active Conv ID:\n<code>{conv}</code>",
            parse_mode="HTML",
        )

    elif data == "menu:close":
        await query.delete_message()


@check_auth
async def sys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display real-time MacBook telemetry (battery, RAM, disk, load, uptime, caffeinate)."""
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))
    telemetry_text = get_system_telemetry(current_ws)
    await update.message.reply_text(telemetry_text, parse_mode="HTML")


@check_auth
async def caffeinate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage macOS anti-sleep mode (caffeinate)."""
    global active_caffeinate_proc
    args = context.args or []
    action = args[0].lower() if args else "status"

    if action in {"on", "start"}:
        if active_caffeinate_proc and active_caffeinate_proc.returncode is None:
            await update.message.reply_text("☕ Anti-sleep (caffeinate) sudah aktif dari tadi bro!")
            return
        try:
            active_caffeinate_proc = await asyncio.create_subprocess_exec("caffeinate", "-dimsu")
            await update.message.reply_text(
                "☕ <b>Anti-Sleep Aktif!</b>\nMac lu nggak bakal sleep/tidur sampai dimatikan dengan <code>/caffeinate off</code>.",
                parse_mode="HTML",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal menyalakan caffeinate: {e}")

    elif action in {"off", "stop"}:
        killed = False
        if active_caffeinate_proc and active_caffeinate_proc.returncode is None:
            active_caffeinate_proc.terminate()
            active_caffeinate_proc = None
            killed = True
        try:
            kproc = await asyncio.create_subprocess_exec("killall", "caffeinate")
            await kproc.wait()
            killed = True
        except Exception:
            pass

        if killed:
            await update.message.reply_text(
                "💤 <b>Anti-Sleep Dimatikan.</b>\nMac sekarang bisa sleep normal sesuai pengaturan sistem.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("ℹ️ Anti-sleep emang lagi nggak aktif kok.")

    else:
        is_active = False
        try:
            res = subprocess.check_output(["pgrep", "caffeinate"], text=True).strip()
            if res:
                is_active = True
        except Exception:
            pass

        status_text = "🟢 <b>Aktif (Anti-Sleep ON)</b>" if is_active else "⚪ <b>Mati (Sleep Normal)</b>"
        await update.message.reply_text(
            f"☕ <b>Status Anti-Sleep (Caffeinate):</b> {status_text}\n\n"
            "<b>Cara Pakai:</b>\n"
            "• <code>/caffeinate on</code> — Nyalakan anti-sleep tanpa batas waktu\n"
            "• <code>/caffeinate off</code> — Matikan anti-sleep biar Mac bisa hemat baterai",
            parse_mode="HTML",
        )


@check_auth
async def screen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Takes silent screenshot of Mac desktop and sends it as a photo."""
    msg = await update.message.reply_text("📸 <i>Mengambil screenshot layar Mac...</i>", parse_mode="HTML")
    tmp_path = Path("/tmp") / f"mac_screen_{int(time.time())}.png"
    try:
        proc = await asyncio.create_subprocess_exec(
            "screencapture", "-x", str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
            err_msg = stderr.decode().strip() or "could not create image from display"
            await msg.edit_text(
                f"⚠️ <b>Gagal Ambil Screenshot Layar</b>\n"
                f"Penyebab: <code>{html.escape(err_msg)}</code>\n\n"
                f"<i>Catatan: Layar Mac mungkin sedang sleep/terkunci (display sleep), atau izin 'Screen Recording' belum diaktifkan di System Settings > Privacy & Security.</i>",
                parse_mode="HTML",
            )
            return

        with open(tmp_path, "rb") as f:
            await update.message.reply_photo(
                photo=f,
                caption=f"📸 <b>Mac Desktop Snapshot</b>\n🕒 <i>{time.strftime('%H:%M:%S - %d %b %Y')}</i>",
                parse_mode="HTML",
            )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Error screenshot: {e}")
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@check_auth
async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display interactive project switcher with tap buttons."""
    user_id = str(update.effective_user.id)
    args = context.args or []
    sessions = load_sessions()
    u_data = sessions.get(user_id, {})
    current_ws = u_data.get("workspace", str(DEFAULT_WORKSPACE))
    favs = u_data.get("favorites") or [str(DEFAULT_WORKSPACE), str(BASE_DIR)]
    clean_favs = [f for f in dict.fromkeys(favs) if Path(f).exists()]
    if not clean_favs:
        clean_favs = [str(DEFAULT_WORKSPACE)]
    u_data["favorites"] = clean_favs
    sessions[user_id] = u_data
    save_sessions(sessions)

    if args and args[0].lower() == "add":
        raw_add = " ".join(args[1:]).strip() if len(args) > 1 else current_ws
        p_add = str(Path(raw_add).expanduser().resolve())
        if Path(p_add).is_dir():
            if p_add not in clean_favs:
                clean_favs.append(p_add)
                u_data["favorites"] = clean_favs
                sessions[user_id] = u_data
                save_sessions(sessions)
                await update.message.reply_text(f"⭐ <b>Folder berhasil dibookmark:</b>\n<code>{html.escape(p_add)}</code>", parse_mode="HTML")
            else:
                await update.message.reply_text("ℹ️ Folder ini sudah ada di bookmark favorit.")
        else:
            await update.message.reply_text(f"❌ Folder tidak valid: <code>{html.escape(p_add)}</code>", parse_mode="HTML")
        return

    keyboard = []
    for idx, path_str in enumerate(clean_favs):
        p = Path(path_str)
        name = p.name or str(p)
        is_current = " ✅" if str(p) == str(current_ws) else ""
        keyboard.append([
            InlineKeyboardButton(f"📁 {name}{is_current}", callback_data=f"proj_switch:{idx}")
        ])

    bottom_row = []
    if current_ws not in clean_favs:
        bottom_row.append(InlineKeyboardButton("⭐ Bookmark Folder Ini", callback_data="proj_fav:add_current"))
    bottom_row.append(InlineKeyboardButton("❌ Tutup", callback_data="proj_fav:close"))
    keyboard.append(bottom_row)

    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📂 <b>Project Workspace Switcher</b>\n"
        f"Workspace saat ini: <code>{html.escape(current_ws)}</code>\n\n"
        f"Tap tombol di bawah untuk langsung ganti project:",
        reply_markup=markup,
        parse_mode="HTML",
    )


async def projects_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Project Switcher callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    u_data = sessions.get(user_id, {})
    favs = u_data.get("favorites") or [str(DEFAULT_WORKSPACE), str(BASE_DIR)]
    current_ws = u_data.get("workspace", str(DEFAULT_WORKSPACE))

    if data.startswith("proj_switch:"):
        idx = int(data.split(":", 1)[1])
        if 0 <= idx < len(favs):
            new_path = favs[idx]
            u_data["workspace"] = new_path
            sessions[user_id] = u_data
            save_sessions(sessions)
            p_name = Path(new_path).name or new_path
            await query.edit_message_text(
                f"✅ <b>Workspace Berpindah!</b>\n\n"
                f"📁 Proyek: <b>{html.escape(p_name)}</b>\n"
                f"Lokasi: <code>{html.escape(new_path)}</code>\n\n"
                f"<i>Semua tugas koding & terminal instan bakal berjalan di folder ini.</i>",
                parse_mode="HTML",
            )
        else:
            await query.answer("Project tidak ditemukan.", show_alert=True)

    elif data == "proj_fav:add_current":
        if current_ws not in favs and Path(current_ws).exists():
            favs.append(current_ws)
            u_data["favorites"] = favs
            sessions[user_id] = u_data
            save_sessions(sessions)
            await query.answer("⭐ Workspace berhasil dibookmark!", show_alert=True)
            keyboard = []
            for idx, path_str in enumerate(favs):
                p = Path(path_str)
                name = p.name or str(p)
                is_current = " ✅" if str(p) == str(current_ws) else ""
                keyboard.append([
                    InlineKeyboardButton(f"📁 {name}{is_current}", callback_data=f"proj_switch:{idx}")
                ])
            keyboard.append([InlineKeyboardButton("❌ Tutup", callback_data="proj_fav:close")])
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.answer("Folder sudah ada di bookmark.", show_alert=True)

    elif data == "proj_fav:close":
        await query.delete_message()


@check_auth
async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send requested file or artifact from Mac to Telegram."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Format Perintah:</b>\n<code>/get &lt;nama_file_atau_path&gt;</code>\n\n"
            "Contoh:\n"
            "• <code>/get bot.py</code> (di workspace aktif)\n"
            "• <code>/get run.sh</code>\n"
            "• <code>/get ~/Coding-Project/app.zip</code>",
            parse_mode="HTML",
        )
        return

    raw_path = " ".join(context.args).strip()
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_ws = Path(sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE)))

    target_path = Path(raw_path).expanduser()
    if not target_path.is_absolute():
        target_path = (current_ws / target_path).resolve()
    else:
        target_path = target_path.resolve()

    try:
        target_path.relative_to(Path.home())
    except ValueError:
        await update.message.reply_text(
            "⛔ <b>Akses Dibatasi:</b> Hanya file di dalam direktori home user yang dapat diunduh demi keamanan.",
            parse_mode="HTML",
        )
        return

    if not target_path.exists():
        await update.message.reply_text(
            f"❌ <b>File tidak ditemukan:</b>\n<code>{html.escape(str(target_path))}</code>",
            parse_mode="HTML",
        )
        return

    if target_path.is_dir():
        items = sorted(list(target_path.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))[:20]
        item_list = "\n".join([f"• {'📁' if x.is_dir() else '📄'} <code>{html.escape(x.name)}</code>" for x in items])
        await update.message.reply_text(
            f"📁 <b>Target adalah Folder ({len(items)} item teratas):</b>\n{item_list}\n\n"
            f"<i>Gunakan <code>/get {html.escape(target_path.name)}/&lt;nama_file&gt;</code> untuk download.</i>",
            parse_mode="HTML",
        )
        return

    size_bytes = target_path.stat().st_size
    if size_bytes > 50 * 1024 * 1024:
        size_mb = size_bytes / (1024 * 1024)
        await update.message.reply_text(
            f"⚠️ Ukuran file terlalu besar ({size_mb:.1f} MB).\n"
            f"Batas upload bot Telegram adalah 50 MB.",
        )
        return

    size_kb = size_bytes / 1024
    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"

    msg = await update.message.reply_text(f"⏳ Mengirim <code>{html.escape(target_path.name)}</code> ({size_str})...", parse_mode="HTML")
    try:
        with open(target_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                caption=f"📄 <code>{html.escape(target_path.name)}</code> ({size_str})",
                parse_mode="HTML",
            )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Gagal mengirim file: {e}")


@check_auth
async def sh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes quick bash command instantly in active workspace without LLM turn."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Format Perintah:</b>\n<code>/sh &lt;command&gt;</code> atau <code>$ &lt;command&gt;</code>\n\n"
            "Contoh:\n"
            "• <code>/sh git status</code>\n"
            "• <code>/sh ls -la</code>\n"
            "• <code>/sh git log -n 3 --oneline</code>\n"
            "• <code>$ docker ps</code>",
            parse_mode="HTML",
        )
        return

    cmd_str = " ".join(context.args).strip()
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    current_ws = sessions.get(user_id, {}).get("workspace", str(DEFAULT_WORKSPACE))

    for pat in DANGEROUS_SH_PATTERNS:
        if re.search(pat, cmd_str, re.I):
            await update.message.reply_text("⛔ <b>Perintah Diblokir:</b> Terdeteksi perintah destruktif sistem berbahaya.", parse_mode="HTML")
            return

    status_msg = await update.message.reply_text(f"⚡ <i>Menjalankan:</i> <code>{html.escape(cmd_str)}</code>...", parse_mode="HTML")

    try:
        env = os.environ.copy()
        env["PATH"] = f"{Path.home()}/.local/bin:/opt/homebrew/bin:{env.get('PATH', '')}"

        proc = await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=current_ws,
                env=env,
            ),
            timeout=20.0,
        )
        stdout, stderr = await proc.communicate()
        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()

        combined = out_text
        if err_text:
            combined = f"{out_text}\n[STDERR]:\n{err_text}" if out_text else err_text
        if not combined:
            combined = "(Perintah selesai tanpa output / return code 0)"

        if len(combined) > 3500:
            combined = combined[:3500] + "\n... (output dipotong karena batas panjang pesan)"

        ret_emoji = "✅" if proc.returncode == 0 else f"⚠️ (exit {proc.returncode})"
        response = (
            f"⚡ <b>Output Terminal</b> {ret_emoji}\n"
            f"📁 <code>{html.escape(Path(current_ws).name)}</code> $ <code>{html.escape(cmd_str)}</code>\n\n"
            f"<pre><code>{html.escape(combined)}</code></pre>"
        )
        await status_msg.edit_text(response, parse_mode="HTML")
    except asyncio.TimeoutError:
        await status_msg.edit_text("⏱️ <b>Timeout:</b> Perintah berjalan melebihi batas 20 detik.", parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Error:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")


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
    await perform_full_reset(user_id)
    await update.message.reply_text(
        "🔄 <b>Sesi berhasil direset total!</b>\n"
        "Semua riwayat percakapan sebelumnya udah dilepas. Pesan berikutnya bakal mulai percakapan baru yang fresh.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@check_auth
async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sessions = load_sessions()
    conv_id = sessions.get(user_id, {}).get("conversation_id")
    if conv_id:
        await update.message.reply_text(f"📌 <b>Active Conversation ID:</b>\n<code>{conv_id}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("Belum ada sesi aktif. Kirim pesan apa aja buat mulai sesi.")


@check_auth
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>📖 Panduan Lengkap Antigravity Mobile Bridge</b>\n\n"
        "Ketik instruksi koding, lempar snippet, atau kirim foto untuk langsung berkolaborasi bareng AI.\n\n"
        "<b>🛠️ Navigasi & Workspace:</b>\n"
        "• <code>/projects</code> atau <code>/fav</code> — Tombol tap buat switch proyek\n"
        "• <code>/pwd</code> — Cek path folder workspace aktif\n"
        "• <code>/cd &lt;path&gt;</code> — Pindah direktori manual\n\n"
        "<b>💻 Host & Mobile Companion (Away from Mac):</b>\n"
        "• <code>/sys</code> atau <code>/status</code> — Cek baterai, RAM, CPU load, SSD Mac\n"
        "• <code>/caffeinate [on/off]</code> — Jaga Mac agar tidak sleep saat ditinggal\n"
        "• <code>/screen</code> — Screenshot layar desktop Mac silent & kirim ke HP\n"
        "• <code>/get &lt;path&gt;</code> — Download file/dokumen/laporan dari Mac ke HP\n"
        "• <code>/sh &lt;cmd&gt;</code> atau <code>$ &lt;cmd&gt;</code> — Jalankan bash instan tanpa LLM\n\n"
        "<b>🤖 AI & Session Management:</b>\n"
        "• <code>/model</code> — Ganti model AI (Gemini Flash, Claude Sonnet, Opus)\n"
        "• <code>/new</code> — Reset sesi percakapan bersih total\n"
        "• <code>/stop</code> atau <code>/cancel</code> — Batalkan proses yang sedang berjalan\n"
        "• <code>/menu</code> — Dashboard aksi cepat\n"
        "• <code>/session</code> — Cek ID sesi aktif Antigravity\n\n"
        "<i>💡 Tips: Tombol <b>[ ≡ Menu ]</b> di samping kolom chat memudahkan akses cepat kapan saja.</i>"
    )
    await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())


@check_auth
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Intercept plain text reset keywords to ensure users never get stuck
    lower_text = text.lower()
    if lower_text in {"/new", "/reset", "new", "reset", "🔄 reset", "🔄 reset sesi", "reset sesi"}:
        await new_command(update, context)
        return

    # Instant bash execution shortcut: $ <command>
    if text.startswith("$ "):
        sh_cmd = text[2:].strip()
        context.args = sh_cmd.split()
        await sh_command(update, context)
        return

    await enqueue_or_run_task(update, context, text)


@check_auth
async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photos sent by the user to the bot, downscaling for speed."""
    if not update.message or not update.message.photo:
        return

    photo = update.message.photo[-1]  # Highest resolution
    caption = update.message.caption or "Analisis gambar ini."

    file = await context.bot.get_file(photo.file_id)
    timestamp = int(time.time() * 1000)
    saved_path = DOWNLOADS_DIR / f"tele_photo_{timestamp}.jpg"

    await file.download_to_drive(custom_path=str(saved_path))
    logger.info(f"Downloaded user photo to {saved_path}")

    # Preprocess & downscale image with Pillow for fast vision inference
    optimized_path = preprocess_and_resize_image(saved_path, max_dim=1024, quality=85)

    prompt_with_image = (
        f"[User mengirim file gambar dari Telegram, tersimpan di: {optimized_path}]\n"
        f"{caption}"
    )
    await enqueue_or_run_task(update, context, prompt_with_image)


async def post_init(application):
    """Register native [≡ Menu] command list in Telegram client."""
    commands = [
        BotCommand("menu", "🎛️ Quick Actions Hub"),
        BotCommand("projects", "📂 Quick Project Switcher"),
        BotCommand("sys", "🖥️ Mac Telemetry (Baterai, RAM, CPU)"),
        BotCommand("caffeinate", "☕ Anti-Sleep Mode Mac"),
        BotCommand("screen", "📸 Screenshot Layar Mac"),
        BotCommand("get", "📥 Download File dari Mac"),
        BotCommand("sh", "⚡ Eksekusi Bash Instan"),
        BotCommand("pwd", "📍 Cek Lokasi Workspace"),
        BotCommand("cd", "📂 Pindah Folder Project"),
        BotCommand("model", "🤖 Ganti Model AI Antigravity"),
        BotCommand("new", "🔄 Reset Sesi Percakapan"),
        BotCommand("stop", "🛑 Batalkan Proses Berjalan"),
        BotCommand("help", "📖 Panduan Bantuan Lengkap"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands successfully registered to Telegram menu.")


def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN belum diset di .env!")
        return

    print(f"Menggunakan executable agy di: {AGY_PATH}")
    print(f"Default workspace: {DEFAULT_WORKSPACE}")
    if ALLOWED_USERS:
        print(f"Whitelist aktif untuk user ID: {', '.join(ALLOWED_USERS)}")
    else:
        print("PERINGATAN: Whitelist kosong, bot terbuka untuk publik.")

    # High performance HTTP client with connection pooling
    request_client = HTTPXRequest(
        connection_pool_size=16,
        read_timeout=60.0,
        write_timeout=20.0,
        connect_timeout=10.0,
        pool_timeout=5.0,
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request_client)
        .post_init(post_init)
        .build()
    )

    # Core & Mobile Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("sys", sys_command))
    app.add_handler(CommandHandler("status", sys_command))
    app.add_handler(CommandHandler("caffeinate", caffeinate_command))
    app.add_handler(CommandHandler("screen", screen_command))
    app.add_handler(CommandHandler("screenshot", screen_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("fav", projects_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("sh", sh_command))
    app.add_handler(CommandHandler("pwd", pwd_command))
    app.add_handler(CommandHandler("cd", cd_command))
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
    app.add_handler(CallbackQueryHandler(projects_callback_handler, pattern=r"^proj_"))
    app.add_handler(CallbackQueryHandler(cancel_callback_handler, pattern=r"^(cancel_task|cancel_queue):"))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("Bot v0.2.0 berjalan dengan Mobile Companion & Casual Persona. Tekan Ctrl+C untuk berhenti.")
    app.run_polling()


if __name__ == "__main__":
    main()
