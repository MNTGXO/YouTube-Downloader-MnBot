# MN YT Downloader Bot

Pyrogram bot for downloading YouTube videos/audio via the MN Bots API.

## Features
- Send any YouTube URL → thumbnail preview → pick MP4 or MP3
- Quality selector (144p–1080p for video, 92–320kbps for audio)
- `/search <query>` — search YouTube and pick from results
- Progress bar during download & upload
- Koyeb / Docker ready

## Env vars
| Key | Description |
|-----|-------------|
| `API_ID` | Telegram API ID |
| `API_HASH` | Telegram API Hash |
| `BOT_TOKEN` | Bot token from @BotFather |
| `YT_API` | API base URL (default set) |
| `MAX_FILE_SIZE` | Max MB before sending link instead (default 2000) |

## Run locally
```bash
cp .env.example .env   # fill values
pip install -r requirements.txt
python bot.py
```

## Docker
```bash
docker build -t mn-ytdl .
docker run --env-file .env mn-ytdl
```

## Koyeb
1. Push to GitHub
2. Create a Worker service → Dockerfile buildpack
3. Set env vars in Koyeb dashboard
4. Deploy
