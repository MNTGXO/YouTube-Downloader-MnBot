import asyncio
import logging
from pyrogram import Client
from config import Config
from plugins.mnbots import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mnbots")

app = Client(
    "mnbots",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins"),
)

async def main():
    await start_health_server()
    await app.start()
    logger.info("Bot started. Idling...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    logger.info("Starting MN Bots YT Downloader...")
    asyncio.run(main())
    
