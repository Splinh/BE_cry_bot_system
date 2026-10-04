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

    def fetch_prices(self, symbols: list) -> dict:
        """Lấy giá nhiều coin cùng lúc qua Binance API."""
        prices = {}
        for coin in symbols:
            coin_clean = coin.upper().replace("USDT", "")
            symbol = f"{coin_clean}USDT"
            urls = [
                f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
            ]
            for url in urls:
                try:
                    r = requests.get(url, timeout=3)
                    if r.status_code == 200:
                        prices[coin_clean] = float(r.json().get("price", 0.0))
                        break
                except Exception:
                    continue
        return prices

    async def run(self):
        prices = self.fetch_prices(["BTC", "ETH", "PAXG"])
        btc_price = prices.get("BTC", 0.0)
        logger.info(f"🚀 Scenario Watcher Daemon đã khởi động. Giá ban đầu: BTC=${btc_price:,.2f}, ETH=${prices.get('ETH', 0):,.2f}, PAXG=${prices.get('PAXG', 0):,.2f}")

        check_counter = 0
        while self.running:
            try:
                # Lấy danh sách các coin đang có kịch bản ACTIVE
                active_coins = list({s.get("coin", "BTC").upper() for s in self.scenario_manager.get_active_scenarios()})
                if not active_coins:
                    active_coins = ["BTC", "ETH", "PAXG"]

                current_prices = self.fetch_prices(active_coins)
                check_counter += 1
                if check_counter % 20 == 0:
                    summary = ", ".join([f"{c}: ${p:,.2f}" for c, p in current_prices.items() if p > 0])
                    logger.info(f"👀 Đang giám sát kịch bản... {summary}")

                # Kiểm tra giá cho từng coin
                for coin, p in current_prices.items():
                    if p > 0:
                        await self.scenario_manager.check_price(coin, p)

            except Exception as e:
                logger.error(f"Lỗi vòng lặp Scenario Watcher: {e}")

            await asyncio.sleep(3)

if __name__ == "__main__":
    app = ScenarioWatcherApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Đã dừng Scenario Watcher.")
