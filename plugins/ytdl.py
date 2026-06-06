import os
import re
import time
import asyncio
import logging
import aiohttp
import aiofiles
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import FloodWait
from config import Config

logger = logging.getLogger("mnbots.ytdl")

YT_API = Config.YT_API
DOWNLOAD_DIR = Path(Config.DOWNLOAD_DIR)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

YT_REGEX = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"[\w\-]{11}"
)

# ─── helpers ────────────────────────────────────────────────────────────────

def extract_url(text: str) -> str | None:
    m = YT_REGEX.search(text)
    return m.group(0) if m else None


async def api_get(session: aiohttp.ClientSession, path: str, **params) -> dict:
    url = f"{YT_API}/{path}"
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=120)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def fetch_info(session, yt_url: str) -> dict:
    return await api_get(session, "info", url=yt_url)


async def fetch_mp4(session, yt_url: str, quality: int | None = None) -> dict:
    params = {"url": yt_url}
    if quality:
        params["quality"] = quality
    return await api_get(session, "mp4", **params)


async def fetch_mp3(session, yt_url: str, quality: int | None = None) -> dict:
    params = {"url": yt_url}
    if quality:
        params["quality"] = quality
    return await api_get(session, "mp3", **params)


async def search_yt(session, query: str) -> list:
    return await api_get(session, "search", s=query)


def progress_bar(done: int, total: int, width: int = 16) -> str:
    pct = done / total if total else 0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct*100:.1f}%"


async def download_file(url: str, dest: Path, msg: Message) -> Path:
    start = time.time()
    last_edit = 0.0
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3600)) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(1024 * 256):
                    await f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last_edit >= 3:
                        last_edit = now
                        elapsed = now - start
                        speed = done / elapsed if elapsed else 0
                        eta = (total - done) / speed if speed and total else 0
                        bar = progress_bar(done, total)
                        try:
                            await msg.edit(
                                f"⬇️ **Downloading...**\n"
                                f"{bar}\n"
                                f"`{done/1e6:.1f} / {total/1e6:.1f} MB`  "
                                f"• `{speed/1e6:.2f} MB/s`  "
                                f"• ETA `{int(eta)}s`"
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception:
                            pass
    return dest


def quality_buttons(qualities: list, vid_id: str, kind: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for q in qualities:
        label = f"{q}p" if kind == "mp4" else f"{q}kbps"
        cb = f"dl:{kind}:{vid_id}:{q}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(buttons)


def search_result_buttons(results: list) -> InlineKeyboardMarkup:
    buttons = []
    videos = [r for r in results if r.get("type") == "video"][:8]
    for v in videos:
        title = v["title"][:40]
        vid_id = v["videoId"]
        buttons.append([InlineKeyboardButton(f"▶ {title}", callback_data=f"sr:{vid_id}")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(buttons)


def vid_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w\-]{11})", url)
    return m.group(1) if m else url


# ─── /start ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, msg: Message):
    await msg.reply(
        "👋 **Welcome to MN YT Downloader!**\n\n"
        "**What I can do:**\n"
        "• Send a YouTube link → choose MP4 or MP3 quality\n"
        "• `/search <query>` → search YouTube and pick a video\n"
        "• `/help` → detailed usage\n\n"
        "Just paste a YouTube URL to get started. 🚀",
        quote=True
    )


# ─── /help ──────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("help") & filters.private)
async def cmd_help(client: Client, msg: Message):
    await msg.reply(
        "**📖 MN YT Downloader — Help**\n\n"
        "**Direct download:**\n"
        "  Send any YouTube URL. I'll show video info and ask format.\n\n"
        "**Quality selection:**\n"
        "  After choosing MP4/MP3 you get quality buttons.\n"
        "  Supports: `144p 360p 480p 720p 1080p` for video\n"
        "  Supports: `92 128 256 320 kbps` for audio\n\n"
        "**Search:**\n"
        "  `/search lofi hip hop` — search YouTube, pick from results\n\n"
        "**Notes:**\n"
        "  • Files > 2 GB sent as link\n"
        "  • Shorts, full videos, embeds all supported",
        quote=True
    )


# ─── /search ────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("search"))
async def cmd_search(client: Client, msg: Message):
    query = msg.text.split(None, 1)[1].strip() if len(msg.text.split()) > 1 else ""
    if not query:
        return await msg.reply("Usage: `/search <query>`", quote=True)

    status = await msg.reply("🔍 Searching YouTube...", quote=True)
    try:
        async with aiohttp.ClientSession() as session:
            results = await search_yt(session, query)
    except Exception as e:
        return await status.edit(f"❌ Search failed: `{e}`")

    videos = [r for r in results if r.get("type") == "video"]
    if not videos:
        return await status.edit("❌ No video results found.")

    markup = search_result_buttons(results)
    await status.edit(
        f"🔎 **Results for:** `{query}`\nPick a video:",
        reply_markup=markup
    )


# ─── YouTube URL handler ─────────────────────────────────────────────────────

@Client.on_message(filters.text & ~filters.command(["start", "help", "search"]))
async def handle_url(client: Client, msg: Message):
    yt_url = extract_url(msg.text)
    if not yt_url:
        return

    status = await msg.reply("🔄 Fetching info...", quote=True)
    try:
        async with aiohttp.ClientSession() as session:
            info = await fetch_info(session, yt_url)
    except Exception as e:
        return await status.edit(f"❌ Failed to fetch info: `{e}`")

    title = info.get("title", "Unknown")
    thumb = info.get("thumbnail", "")
    vid_id = vid_id_from_url(yt_url)

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 MP4 (Video)", callback_data=f"fmt:mp4:{vid_id}"),
            InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"fmt:mp3:{vid_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
    ])

    caption = f"**{title}**\n\nChoose format:"
    try:
        if thumb:
            await status.delete()
            await msg.reply_photo(thumb, caption=caption, reply_markup=markup)
        else:
            await status.edit(caption, reply_markup=markup)
    except Exception:
        await status.edit(caption, reply_markup=markup)


# ─── Callback: format selection ──────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^fmt:(mp4|mp3):(.+)$"))
async def cb_format(client: Client, cq: CallbackQuery):
    _, kind, vid_id = cq.data.split(":", 2)
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer("Fetching qualities...")
    await cq.message.edit_reply_markup(None)

    status = await cq.message.reply("⏳ Fetching available qualities...")
    try:
        async with aiohttp.ClientSession() as session:
            if kind == "mp4":
                data = await fetch_mp4(session, yt_url)
            else:
                data = await fetch_mp3(session, yt_url)
    except Exception as e:
        return await status.edit(f"❌ Error: `{e}`")

    qualities = data.get("availableQuality", [])
    if not qualities:
        return await status.edit("❌ No qualities available.")

    markup = quality_buttons(qualities, vid_id, kind)
    icon = "🎬" if kind == "mp4" else "🎵"
    await status.edit(
        f"{icon} Select quality for **{'Video' if kind == 'mp4' else 'Audio'}**:",
        reply_markup=markup
    )


# ─── Callback: search result selection ───────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^sr:(.+)$"))
async def cb_search_result(client: Client, cq: CallbackQuery):
    vid_id = cq.data.split(":", 1)[1]
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer()
    await cq.message.edit_reply_markup(None)

    status = await cq.message.reply("🔄 Fetching info...")
    try:
        async with aiohttp.ClientSession() as session:
            info = await fetch_info(session, yt_url)
    except Exception as e:
        return await status.edit(f"❌ Failed: `{e}`")

    title = info.get("title", "Unknown")
    thumb = info.get("thumbnail", "")

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 MP4", callback_data=f"fmt:mp4:{vid_id}"),
            InlineKeyboardButton("🎵 MP3", callback_data=f"fmt:mp3:{vid_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
    ])

    caption = f"**{title}**\n\nChoose format:"
    try:
        if thumb:
            await status.delete()
            await cq.message.reply_photo(thumb, caption=caption, reply_markup=markup)
        else:
            await status.edit(caption, reply_markup=markup)
    except Exception:
        await status.edit(caption, reply_markup=markup)


# ─── Callback: quality → download ────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl:(mp4|mp3):(.+):(\d+)$"))
async def cb_download(client: Client, cq: CallbackQuery):
    _, kind, vid_id, quality_str = cq.data.split(":", 3)
    quality = int(quality_str)
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer("Starting download...")
    await cq.message.edit_reply_markup(None)

    status = await cq.message.reply("⏳ Preparing download...")
    dest = None
    try:
        async with aiohttp.ClientSession() as session:
            if kind == "mp4":
                data = await fetch_mp4(session, yt_url, quality)
            else:
                data = await fetch_mp3(session, yt_url, quality)

        if not data.get("status"):
            return await status.edit("❌ API returned failure status.")

        dl_url = data["url"]
        filename = data.get("filename", f"{vid_id}.{kind}")
        q_label = data.get("quality", "")

        dest = DOWNLOAD_DIR / filename

        # Download
        await status.edit("⬇️ **Downloading...**\n`Starting...`")
        await download_file(dl_url, dest, status)

        file_size = dest.stat().st_size
        size_mb = file_size / 1e6

        # Upload to Telegram
        await status.edit(f"📤 **Uploading** `{filename}`...")
        caption = (
            f"{'🎬' if kind == 'mp4' else '🎵'} **{filename}**\n"
            f"Quality: `{q_label}`  •  Size: `{size_mb:.1f} MB`\n"
            f"via @MNBotsYTDL"
        )

        if size_mb > Config.MAX_FILE_SIZE:
            await status.edit(
                f"⚠️ File is `{size_mb:.0f} MB`, too large to send via Telegram.\n"
                f"[Direct Download Link]({dl_url})"
            )
        elif kind == "mp4":
            await cq.message.reply_video(
                str(dest),
                caption=caption,
                supports_streaming=True,
            )
            await status.delete()
        else:
            await cq.message.reply_audio(
                str(dest),
                caption=caption,
                title=filename.rsplit("(", 1)[0].strip(),
            )
            await status.delete()

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.exception("Download/upload failed")
        await status.edit(f"❌ Failed: `{e}`")
    finally:
        try:
            if dest and dest.exists():
                dest.unlink()
        except Exception:
            pass


# ─── Callback: cancel ────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl:cancel$"))
async def cb_cancel(client: Client, cq: CallbackQuery):
    await cq.answer("Cancelled.")
    await cq.message.edit_reply_markup(None)
    await cq.message.edit_text("❌ Cancelled.")
