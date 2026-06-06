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
    r"https?://(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"[\w\-]{11}"
)

# ── helpers ──────────────────────────────────────────────────────────────────

def extract_yt_url(text: str) -> str | None:
    m = YT_REGEX.search(text)
    return m.group(0) if m else None


def vid_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w\-]{11})", url)
    return m.group(1) if m else url


async def api_get(path: str, **params) -> dict:
    url = f"{YT_API}/{path}"
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, timeout=timeout) as r:
            r.raise_for_status()
            return await r.json(content_type=None)


def progress_bar(done: int, total: int, width: int = 16) -> str:
    pct = done / total if total else 0
    filled = int(width * pct)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {pct*100:.1f}%"


async def download_file(url: str, dest: Path, status_msg: Message) -> None:
    start = time.time()
    last_edit = 0.0
    timeout = aiohttp.ClientTimeout(total=3600)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(256 * 1024):
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
                            await status_msg.edit_text(
                                f"⬇️ **Downloading...**\n{bar}\n"
                                f"`{done/1e6:.1f} / {total/1e6:.1f} MB`"
                                f"  •  `{speed/1e6:.2f} MB/s`"
                                f"  •  ETA `{int(eta)}s`"
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception:
                            pass


def fmt_buttons(vid_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 MP4 (Video)", callback_data=f"fmt:mp4:{vid_id}"),
            InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"fmt:mp3:{vid_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
    ])


def quality_buttons(qualities: list, vid_id: str, kind: str) -> InlineKeyboardMarkup:
    buttons, row = [], []
    for q in qualities:
        label = f"{q}p" if kind == "mp4" else f"{q}kbps"
        row.append(InlineKeyboardButton(label, callback_data=f"dl:{kind}:{vid_id}:{q}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(buttons)


def search_buttons(results: list) -> InlineKeyboardMarkup:
    videos = [r for r in results if r.get("type") == "video"][:8]
    buttons = [
        [InlineKeyboardButton(f"▶ {v['title'][:45]}", callback_data=f"sr:{v['videoId']}")]
        for v in videos
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(buttons)


async def send_info_card(target, vid_id: str, title: str, thumb: str):
    """Send thumbnail + format buttons. target = Message to reply to."""
    markup = fmt_buttons(vid_id)
    caption = f"**{title}**\n\nChoose format:"
    try:
        if thumb:
            await target.reply_photo(thumb, caption=caption, reply_markup=markup)
            return
    except Exception:
        pass
    await target.reply(caption, reply_markup=markup)


# ── /start ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("start"))
async def cmd_start(_c: Client, msg: Message):
    await msg.reply(
        "👋 **MN YT Downloader**\n\n"
        "Send a YouTube link to download it.\n"
        "Use `/search <query>` to search YouTube.\n"
        "Use `/help` for more info.",
        quote=True,
    )


# ── /help ────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("help"))
async def cmd_help(_c: Client, msg: Message):
    await msg.reply(
        "**📖 Help**\n\n"
        "**Send a YouTube URL** — I fetch the title and let you pick:\n"
        "  `🎬 MP4` — video at 144p / 360p / 480p / 720p / 1080p\n"
        "  `🎵 MP3` — audio at 92 / 128 / 256 / 320 kbps\n\n"
        "**`/search <query>`** — search and pick a video from results\n\n"
        "Files over 2 GB are sent as a direct link instead.",
        quote=True,
    )


# ── /search ──────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("search"))
async def cmd_search(_c: Client, msg: Message):
    parts = msg.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return await msg.reply("Usage: `/search <query>`", quote=True)
    query = parts[1].strip()

    status = await msg.reply("🔍 Searching...", quote=True)
    try:
        results = await api_get("search", s=query)
    except Exception as e:
        return await status.edit_text(f"❌ Search failed: `{e}`")

    videos = [r for r in results if r.get("type") == "video"]
    if not videos:
        return await status.edit_text("❌ No video results found.")

    await status.edit_text(
        f"🔎 Results for `{query}` — pick one:",
        reply_markup=search_buttons(results),
    )


# ── URL handler ───────────────────────────────────────────────────────────────
# Uses a custom filter so it only fires when a real YT URL is present.

def _is_yt_url(_, __, msg: Message) -> bool:
    return bool(msg.text and extract_yt_url(msg.text))

yt_url_filter = filters.create(_is_yt_url)

@Client.on_message(yt_url_filter)
async def handle_url(_c: Client, msg: Message):
    yt_url = extract_yt_url(msg.text)
    vid_id = vid_id_from_url(yt_url)

    status = await msg.reply("🔄 Fetching info...", quote=True)
    try:
        info = await api_get("info", url=yt_url)
    except Exception as e:
        return await status.edit_text(f"❌ Failed to fetch info: `{e}`")

    title = info.get("title", "Unknown")
    thumb = info.get("thumbnail", "")

    try:
        await status.delete()
    except Exception:
        pass

    await send_info_card(msg, vid_id, title, thumb)


# ── cb: search result pick ────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^sr:([\w\-]{11})$"))
async def cb_search_result(_c: Client, cq: CallbackQuery):
    vid_id = cq.data[3:]
    yt_url = f"https://youtu.be/{vid_id}"
    await cq.answer()
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass

    status = await cq.message.reply("🔄 Fetching info...")
    try:
        info = await api_get("info", url=yt_url)
    except Exception as e:
        return await status.edit_text(f"❌ Failed: `{e}`")

    title = info.get("title", "Unknown")
    thumb = info.get("thumbnail", "")
    try:
        await status.delete()
    except Exception:
        pass
    await send_info_card(cq.message, vid_id, title, thumb)


# ── cb: format chosen → fetch qualities ──────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^fmt:(mp4|mp3):([\w\-]{11})$"))
async def cb_format(_c: Client, cq: CallbackQuery):
    parts = cq.data.split(":")   # fmt, kind, vid_id
    kind, vid_id = parts[1], parts[2]
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer("Fetching qualities...")
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass

    status = await cq.message.reply("⏳ Fetching available qualities...")
    try:
        data = await api_get("mp4" if kind == "mp4" else "mp3", url=yt_url)
    except Exception as e:
        return await status.edit_text(f"❌ Error: `{e}`")

    qualities = data.get("availableQuality", [])
    if not qualities:
        return await status.edit_text("❌ No qualities returned by API.")

    icon = "🎬" if kind == "mp4" else "🎵"
    label = "Video" if kind == "mp4" else "Audio"
    await status.edit_text(
        f"{icon} Select **{label}** quality:",
        reply_markup=quality_buttons(qualities, vid_id, kind),
    )


# ── cb: quality chosen → download & upload ────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl:(mp4|mp3):([\w\-]{11}):(\d+)$"))
async def cb_download(_c: Client, cq: CallbackQuery):
    parts = cq.data.split(":")   # dl, kind, vid_id, quality
    kind, vid_id, quality = parts[1], parts[2], int(parts[3])
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer("Starting download...")
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass

    status = await cq.message.reply("⏳ Preparing...")
    dest: Path | None = None
    try:
        data = await api_get("mp4" if kind == "mp4" else "mp3", url=yt_url, quality=quality)

        if not data.get("status"):
            return await status.edit_text("❌ API returned failure.")

        dl_url: str = data["url"]
        filename: str = data.get("filename", f"{vid_id}.{kind}")
        q_label: str = data.get("quality", str(quality))
        dest = DOWNLOAD_DIR / filename

        await status.edit_text("⬇️ **Downloading...**\n`Starting...`")
        await download_file(dl_url, dest, status)

        size_mb = dest.stat().st_size / 1e6
        caption = (
            f"{'🎬' if kind == 'mp4' else '🎵'} **{filename}**\n"
            f"Quality: `{q_label}`  •  Size: `{size_mb:.1f} MB`"
        )

        if size_mb > Config.MAX_FILE_SIZE:
            return await status.edit_text(
                f"⚠️ File too large (`{size_mb:.0f} MB`) for Telegram.\n"
                f"[Direct Link]({dl_url})",
                disable_web_page_preview=True,
            )

        await status.edit_text(f"📤 Uploading `{filename}`...")

        if kind == "mp4":
            await cq.message.reply_video(
                str(dest), caption=caption, supports_streaming=True
            )
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
        try:
            await status.edit_text(f"❌ Failed: `{e}`")
        except Exception:
            pass
    finally:
        if dest and dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass


# ── cb: cancel ────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl:cancel$"))
async def cb_cancel(_c: Client, cq: CallbackQuery):
    await cq.answer("Cancelled.")
    try:
        await cq.message.edit_reply_markup(None)
        await cq.message.edit_text("❌ Cancelled.")
    except Exception:
        pass
