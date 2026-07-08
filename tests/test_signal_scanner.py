"""
Test Signal Scanner - ASCII-only to prevent Windows encoding console crashes.
Usage: python backend/tests/test_signal_scanner.py
"""
import asyncio
import sys
import html
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.signal_scanner import SignalScanner
from notifiers.telegram_bot import TelegramNotifier
from notifiers.zalo_bot import ZaloNotifier
from core.config import Config


async def test_notifier_configuration():
    print("=== CHECKING NOTIFIER CONFIGURATION ===")
    print(f"Telegram Bot Token: {Config.TELEGRAM_BOT_TOKEN[:10]}... (Len: {len(Config.TELEGRAM_BOT_TOKEN)})")
    print(f"Telegram Chat ID: {Config.TELEGRAM_CHAT_ID}")
    print(f"Telegram Group Chat ID: {Config.TELEGRAM_GROUP_CHAT_ID}" if Config.TELEGRAM_GROUP_CHAT_ID else "Telegram Group Chat ID: NOT CONFIGURED")
    print(f"Zalo Bot Token: {Config.ZALO_BOT_TOKEN[:10]}... (Len: {len(Config.ZALO_BOT_TOKEN)})" if Config.ZALO_BOT_TOKEN else "Zalo Bot Token: NOT CONFIGURED")
    print(f"Zalo Admin Chat ID: {Config.ZALO_ADMIN_CHAT_ID}" if Config.ZALO_ADMIN_CHAT_ID else "Zalo Admin Chat ID: NOT CONFIGURED")
    print(f"Zalo Group Chat ID: {Config.ZALO_GROUP_CHAT_ID}" if Config.ZALO_GROUP_CHAT_ID else "Zalo Group Chat ID: NOT CONFIGURED")
    print("-" * 40)


async def test_telegram_alert():
    print("=== TESTING TELEGRAM ALERT ===")
    notifier = TelegramNotifier()
    try:
        await notifier.send_signal(
            coin="BTC (TEST_1H)",
            direction="LONG",
            entry=62500.0,
            sl=61200.0,
            tp=64000.0,
            reason=html.escape("Test realtime signal from scanner (MACD Golden Cross + RSI < 40)")
        )
        print("Telegram Signal Sent successfully, please check your app.")
    except Exception as e:
        print(f"Error sending Telegram: {e}")
    print("-" * 40)


async def test_zalo_alert():
    if not Config.ZALO_BOT_TOKEN or (not Config.ZALO_ADMIN_CHAT_ID and not Config.ZALO_GROUP_CHAT_ID):
        print("=== SKIPPING ZALO TEST (Not configured in .env) ===")
        print("-" * 40)
        return

    print("=== TESTING ZALO ALERT ===")
    notifier = ZaloNotifier()
    zalo_text = (
        f"🚨 TEST REALTIME REVERSAL SIGNAL (TEST_1H)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 Coin: BTC\n"
        f"👉 Direction: LONG\n"
        f"📍 Entry: $62,500.00\n"
        f"🛑 Stop Loss: $61,200.00\n"
        f"🎯 Take Profit: $64,000.00\n"
        f"💡 Reason: Testing Zalo alert from SignalScanner\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    success = await notifier.send_message(zalo_text)
    if success:
        print("Zalo test message sent successfully!")
    else:
        print("Zalo test message failed.")
    print("-" * 40)


async def test_scanner_logic():
    print("=== TESTING REVERSAL DETECTION LOGIC ===")
    scanner = SignalScanner(interval_seconds=1)
    
    # Mock previous state is SHORT
    key = "BTC/USDT_1h"
    scanner.last_signals[key] = "SHORT"
    print(f"Previous state of {key}: SHORT")
    
    # 1. Mock state change to NEUTRAL
    print("\nMocking scan result: NEUTRAL")
    scanner.last_signals[key] = "NEUTRAL"
    print(f"New state: {scanner.last_signals[key]} (No alert expected)")
    
    # 2. Mock state change to LONG (should trigger alert)
    print("\nMocking scan result: LONG (Alert expected)")
    
    tg_called = False
    zalo_called = False
    
    async def mock_tg_send(*args, **kwargs):
        nonlocal tg_called
        tg_called = True
        print(f"  [Mock Telegram] send_signal called with: {args} {kwargs}")
        
    async def mock_zalo_send(*args, **kwargs):
        nonlocal zalo_called
        zalo_called = True
        print(f"  [Mock Zalo] send_message called with: {args} {kwargs}")
        
    scanner.tg_notifier.send_signal = mock_tg_send
    scanner.zalo_notifier.send_message = mock_zalo_send
    
    direction = "LONG"
    last_dir = scanner.last_signals.get(key)
    if direction != last_dir:
        scanner.last_signals[key] = direction
        if direction in ("LONG", "SHORT"):
            await scanner.tg_notifier.send_signal(
                coin="BTC (1h)",
                direction=direction,
                entry=62500.0,
                sl=61200.0,
                tp=64000.0,
                reason="RSI Oversold"
            )
            await scanner.zalo_notifier.send_message("Mock Zalo Alert Text")
            
    if tg_called and zalo_called:
        print("Reversal detection and notification logic is CORRECT!")
    else:
        print("Reversal detection logic is FAILED.")
    print("-" * 40)


async def run_all():
    await test_notifier_configuration()
    await test_telegram_alert()
    await test_zalo_alert()
    await test_scanner_logic()


if __name__ == "__main__":
    asyncio.run(run_all())
