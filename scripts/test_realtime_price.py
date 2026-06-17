"""
Script test: Lay gia BTC/ETH/SOL real-time tu Binance va gui ve Telegram.
Chay: python scripts/test_realtime_price.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_ingestion.binance_ws import BinanceWebSocket
from notifiers.telegram_bot import TelegramNotifier
from core.config import Config


async def main():
    Config.TELEGRAM_CHAT_ID = "8023393059"
    ws = BinanceWebSocket()
    notifier = TelegramNotifier()

    coins = ["btcusdt", "ethusdt", "solusdt"]
    print("Dang lay gia real-time tu Binance...")

    # Lay gia tung coin
    results = []
    for coin in coins:
        data = await ws.get_price_once(coin)
        if data:
            results.append(data)
            print(f"  {data['symbol']}: ${data['price']:,.2f} ({data['change_pct']:+.2f}%)")

    if not results:
        print("Khong lay duoc gia. Kiem tra ket noi mang.")
        return

    # Tao tin nhan tong hop gui ve Telegram
    lines = ["<b>BANG GIA CRYPTO REAL-TIME</b>", ""]
    for r in results:
        emoji = "+" if r["change_pct"] >= 0 else ""
        color = "green" if r["change_pct"] >= 0 else "red"
        name = r["symbol"].replace("USDT", "")
        lines.append(
            f"<b>{name}:</b> <code>${r['price']:,.2f}</code> ({emoji}{r['change_pct']:.2f}%)"
        )
    lines.append("")
    lines.append(f"<i>Cap nhat luc: {results[0].get('timestamp', 'N/A')[:19] if results else 'N/A'}</i>")

    await notifier.send_message("\n".join(lines))
    print("\nDa gui bang gia ve Telegram!")


if __name__ == "__main__":
    asyncio.run(main())
