"""
API-only entrypoint for server/VPS deployment.
Runs FastAPI backend WITHOUT Telegram bot (no bot token needed).
Usage: python run_api.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from loguru import logger
from execution.trade_engine import TradeEngine
from analytics.signal_tracker import SignalTracker
from analytics.listing_scanner import ListingScanner
from core.security import SecurityManager
from airdrop.social.telegram_worker import TelegramManager
from airdrop.social.twitter_worker import TwitterManager
from airdrop.wallet_manager import WalletManager
from data_ingestion.price_monitor import PriceMonitor
from api.server import run_server, inject_instances

# Init instances (same as main.py but without Telegram bot)
trade_engine = TradeEngine()
signal_tracker = SignalTracker(trade_engine=trade_engine)
listing_scanner = ListingScanner()
security = SecurityManager()
telegram_manager = TelegramManager()
twitter_manager = TwitterManager()
price_monitor = PriceMonitor()
wallet_manager = WalletManager()

system_status = {
    "status": "Running (API-only)",
    "version": "1.0",
    "uptime_minutes": 0,
    "total_ping_count": 0
}

def main():
    # Inject instances into API
    inject_instances(
        trade_engine, telegram_manager, twitter_manager, system_status,
        signal_tracker=signal_tracker, listing_scanner=listing_scanner,
        security=security, wallet_manager=wallet_manager,
        price_monitor=price_monitor
    )

    logger.success("API server starting on port 8000 (API-only mode, no Telegram bot)")

    async def start():
        api_task = asyncio.create_task(run_server(port=8000))
        # Keep alive + uptime counter
        while True:
            system_status["uptime_minutes"] += 1
            await asyncio.sleep(60)

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("API server stopped.")

if __name__ == "__main__":
    main()
