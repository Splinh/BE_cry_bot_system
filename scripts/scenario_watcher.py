"""
Scenario Watcher Daemon - Tự động theo dõi giá BTC theo thời gian thực.
Tích hợp ScenarioManager để Cảnh báo sớm và TỰ ĐỘNG VÀO LỆNH (Auto-Trade) khi chạm mốc kịch bản.
"""
import asyncio
import os
import sys
import time
import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from execution.trade_engine import TradeEngine
from analytics.signal_tracker import SignalTracker
from analytics.scenario_manager import ScenarioManager

try:
    import winsound
except ImportError:
    winsound = None

logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", level="INFO")
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
logger.add(os.path.join(BASE_DIR, "logs", "scenario_watcher.log"), rotation="10 MB", level="INFO")

class ScenarioWatcherApp:
    def __init__(self):
        self.trade_engine = TradeEngine()
        self.signal_tracker = SignalTracker(trade_engine=self.trade_engine)
        self.scenario_manager = ScenarioManager(
            trade_engine=self.trade_engine,
            signal_tracker=self.signal_tracker
        )
        self.running = True

    def fetch_price(self) -> float:
        urls = [
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    return float(r.json().get("price", 0.0))
            except Exception:
                continue
        return 0.0

    async def run(self):
        start_price = self.fetch_price()
        logger.info(f"🚀 Scenario Watcher Daemon đã khởi động. Giá ban đầu: ${start_price:,.2f}")
        
        status_text = self.scenario_manager.format_status_message(start_price)
        init_msg = (
            f"🤖 <b>[CryptoBot System]</b> Đã cập nhật chế độ AUTO-TRADE theo kịch bản!\n\n"
            f"{status_text}\n"
            f"<i>Bot sẽ tự động quét và khớp lệnh khi giá chạm điểm xác nhận xác suất cao.</i>"
        )
        await self.scenario_manager.broadcast(init_msg)

        check_counter = 0
        while self.running:
            try:
                price = self.fetch_price()
                if price <= 0:
                    await asyncio.sleep(3)
                    continue

                check_counter += 1
                if check_counter % 20 == 0:
                    logger.info(f"👀 Đang giám sát kịch bản... BTC = ${price:,.2f}")

                # Kiểm tra thị trường với ScenarioManager (Cảnh báo + Auto Trade)
                await self.scenario_manager.check_price("BTC", price)

            except Exception as e:
                logger.error(f"Lỗi vòng lặp Scenario Watcher: {e}")

            await asyncio.sleep(3)

if __name__ == "__main__":
    app = ScenarioWatcherApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Đã dừng Scenario Watcher.")
