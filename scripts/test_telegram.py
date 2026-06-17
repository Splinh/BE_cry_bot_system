"""
Test Script: Gui tin nhan chao mung dau tien ve Telegram.
Chay: python scripts/test_telegram.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.config import Config
from notifiers.telegram_bot import TelegramNotifier


async def main():
    # Force reload .env
    Config.TELEGRAM_CHAT_ID = "8023393059"

    notifier = TelegramNotifier()

    # 1. Tin nhan chao mung
    welcome = (
        "<b>CRYPTO BOT SYSTEM - ONLINE!</b>\n"
        "========================\n"
        "Ket noi Telegram thanh cong!\n"
        "He thong san sang hoat dong.\n"
        "========================\n"
        "Modules dang phat trien:\n"
        "  - Real-time Price Tracker\n"
        "  - News Crawler & Sentiment AI\n"
        "  - Trading Signal Generator\n"
        "  - Airdrop Automation\n"
        "========================\n"
    )
    await notifier.send_message(welcome)

    # 2. Demo tin hieu trading mau
    await notifier.send_signal(
        coin="BTC/USDT",
        direction="LONG",
        entry=87500.00,
        sl=86200.00,
        tp=92000.00,
        reason="RSI oversold H4 + Volume spike",
    )

    print("Da gui 2 tin nhan test ve Telegram thanh cong!")


if __name__ == "__main__":
    asyncio.run(main())
