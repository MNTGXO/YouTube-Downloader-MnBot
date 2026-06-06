"""
Minimal HTTP health check server on :8080 for Koyeb.
Called from bot.py before app.run().
"""
import asyncio
import logging
from aiohttp import web

logger = logging.getLogger("mnbots.health")

PORT = 8080

async def handle(_req: web.Request) -> web.Response:
    return web.Response(text="OK")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/health", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health check server listening on :{PORT}")
  
