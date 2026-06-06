import os

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    YT_API = os.environ.get("YT_API", "https://youtube-downloader.mn-bots.workers.dev")
    MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 2000))  # MB
    DOWNLOAD_DIR = "/tmp/mnbots"
