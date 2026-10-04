"""
Scenario Watcher Daemon - Tự động theo dõi giá BTC / ETH / VÀNG (PAXG) theo thời gian thực.
Tích hợp ScenarioManager để Cảnh báo sớm và TỰ ĐỘNG VÀO LỆNH (Auto-Trade) khi chạm mốc kịch bản.

- Khi chạy bên trong bot (main.py): truyền vào trade_engine / signal_tracker dùng chung của bot,
  KHÔNG tạo engine riêng (tránh 2 engine cùng ghi đè data/paper_trading.json).
- Khi chạy độc lập (python scripts/scenario_watcher.py): tự tạo engine riêng.
"""
import asyncio
import json
import os
import sys

import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from analytics.scenario_manager import ScenarioManager

DEFAULT_COINS = ["BTC", "ETH", "PAXG"]
CHECK_INTERVAL_SECONDS = 3
HTTP_TIMEOUT = (3, 3)  # (connect, read)


class ScenarioWatcherApp:
    def __init__(self, trade_engine=None, signal_tracker=None):
        if trade_engine is None:
            from execution.trade_engine import TradeEngine
            trade_engine = TradeEngine()
        if signal_tracker is None:
            from analytics.signal_tracker import SignalTracker
            signal_tracker = SignalTracker(trade_engine=trade_engine)

        self.trade_engine = trade_engine
        self.signal_tracker = signal_tracker
        self.scenario_manager = ScenarioManager(
            trade_engine=self.trade_engine,
            signal_tracker=self.signal_tracker
        )
        self.running = True
        self._session = requests.Session()

    def _fetch_prices_sync(self, coins: list) -> dict:
        """
        Lấy giá nhiều coin bằng 1 request duy nhất (Binance hỗ trợ tham số symbols=[...]).
        Hàm đồng bộ -> luôn gọi qua asyncio.to_thread để không chặn event loop của bot.
        """
        clean = sorted({c.upper().replace("USDT", "") for c in coins if c})
        if not clean:
            return {}
        symbols = [f"{c}USDT" for c in clean]
        prices = {}

        # 1 request cho tất cả symbol
        try:
            r = self._session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbols": json.dumps(symbols, separators=(",", ":"))},
                timeout=HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                for item in r.json():
                    sym = item.get("symbol", "")
                    if sym.endswith("USDT"):
                        prices[sym[:-4]] = float(item.get("price", 0.0))
        except Exception as e:
            logger.debug(f"Batch price request lỗi: {e}")

        # Fallback từng symbol (Futures) cho coin còn thiếu
        for coin in clean:
            if prices.get(coin, 0) > 0:
                continue
            try:
                r = self._session.get(
                    "https://fapi.binance.com/fapi/v1/ticker/price",
                    params={"symbol": f"{coin}USDT"},
                    timeout=HTTP_TIMEOUT,
                )
                if r.status_code == 200:
                    prices[coin] = float(r.json().get("price", 0.0))
            except Exception:
                continue
        return prices

    async def fetch_prices(self, coins: list) -> dict:
        return await asyncio.to_thread(self._fetch_prices_sync, coins)

    async def run(self):
        prices = await self.fetch_prices(DEFAULT_COINS)
        logger.info(
            "🚀 Scenario Watcher đã khởi động. Giá ban đầu: "
            + ", ".join(f"{c}=${p:,.2f}" for c, p in prices.items())
        )

        check_counter = 0
        while self.running:
            try:
                active_coins = list({s.get("coin", "BTC").upper() for s in self.scenario_manager.get_active_scenarios()})
                if active_coins:
                    current_prices = await self.fetch_prices(active_coins)

                    check_counter += 1
                    if check_counter % 20 == 0:
                        summary = ", ".join(f"{c}: ${p:,.2f}" for c, p in current_prices.items() if p > 0)
                        logger.info(f"👀 Đang giám sát kịch bản... {summary}")

                    for coin, p in current_prices.items():
                        if p > 0:
                            await self.scenario_manager.check_price(coin, p)
            except Exception as e:
                logger.error(f"Lỗi vòng lặp Scenario Watcher: {e}")

            await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    # Chỉ cấu hình logger khi chạy độc lập - KHÔNG đụng vào logger của bot khi được import
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", level="INFO")
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    logger.add(os.path.join(BASE_DIR, "logs", "scenario_watcher.log"), rotation="10 MB", level="INFO")

    app = ScenarioWatcherApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Đã dừng Scenario Watcher.")
