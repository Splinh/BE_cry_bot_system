"""
Binance WebSocket Client - Lay gia Crypto Real-time.
Module nay ket noi truc tiep vao Binance WebSocket API
de nhan du lieu gia theo thoi gian thuc (< 100ms delay).
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Callable, Optional

import websockets
from loguru import logger


# Binance WebSocket endpoint
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
BINANCE_WS_STREAM = "wss://stream.binance.com:9443/stream?streams="

# Fallback symbols khi khong truyen symbols vao stream_tickers()
DEFAULT_SYMBOLS = ["btcusdt", "ethusdt", "solusdt", "paxgusdt"]

# Gioi han gia WS -> bi coi la "cu" sau bao lau (giay).
# Mini ticker Binance cap nhat moi ~1s; 30s la nhip mach bao dong an toan.
STALE_AFTER_SECONDS = 30.0


class BinanceWebSocket:
    """
    Client ket noi WebSocket voi Binance de lay:
    - Gia ticker real-time (miniTicker)
    - Du lieu nen (Kline/Candlestick)
    """

    def __init__(self):
        self.ws = None
        self.running = False
        self.callbacks: list[Callable] = []
        self.latest_prices: dict[str, dict] = {}
        # Danh sach symbol dang subscribe (luoi nguon su that cho stream_tickers)
        self.symbols: list[str] = []
        # Epoch cua ban gia moi nhat nhan duoc tu WS (0 = chua co gi)
        self.last_update_ts: float = 0.0
        # Tang moi khi danh sach symbols doi -> buoc WS phai reconnect
        self._generation: int = 0

    def on_price_update(self, callback: Callable):
        """Dang ky ham callback khi co gia moi."""
        self.callbacks.append(callback)

    def is_stale(self, max_age: float = STALE_AFTER_SECONDS) -> bool:
        """True neu WS chua co du lieu, hoac du lieu moi nhat da qua cu."""
        if not self.latest_prices or self.last_update_ts <= 0:
            return True
        return (time.time() - self.last_update_ts) > max_age

    def add_symbols(self, symbols) -> bool:
        """
        Them symbol vao danh sach subscribe. Tra True neu danh sach da doi
        (=> stream_tickers() se phai reconnect de lay stream moi).
        """
        current = {s.lower() for s in self.symbols}
        new = {str(s).lower() for s in symbols if s and str(s).lower() not in current}
        if not new:
            return False
        self.symbols = sorted(current | new)
        self._generation += 1
        logger.info(
            f"Binance WS: +{len(new)} symbols (tong {len(self.symbols)}) -> yeu cau reconnect"
        )
        return True

    async def _notify_callbacks(self, data: dict):
        """Goi tat ca callback da dang ky."""
        for cb in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def stream_tickers(self, symbols: list[str] = None):
        """
        Stream gia real-time cua nhieu coin cung luc.
        symbols: ["btcusdt", "ethusdt", "solusdt"]

        Luu y: danh sach symbol duoc khoi tao 1 lan tu `symbols`, sau do co the
        bo sung runtime qua `add_symbols()`. Moi khi danh sach doi, vong lap se
        thoat khoi connection hien tai va reconnect voi stream moi.
        """
        if symbols:
            self.symbols = sorted({str(s).lower() for s in symbols})
        elif not self.symbols:
            self.symbols = sorted(DEFAULT_SYMBOLS)

        self.running = True
        logger.info(f"Ket noi Binance WebSocket: {len(self.symbols)} coins...")

        while self.running:
            generation = self._generation
            streams = "/".join(f"{s}@miniTicker" for s in self.symbols)
            url = f"{BINANCE_WS_STREAM}{streams}"

            try:
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    logger.success(f"Da ket noi Binance WebSocket! ({len(self.symbols)} streams)")
                    while self.running:
                        # Co symbol moi -> dung connection hien tai de lay stream moi
                        if self._generation != generation:
                            logger.info("Danh sach symbols thay doi -> reconnect WebSocket...")
                            break

                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        msg = json.loads(raw)
                        data = msg.get("data", msg)

                        price_data = {
                            "symbol": data.get("s", ""),
                            "price": float(data.get("c", 0)),
                            "open": float(data.get("o", 0)),
                            "high": float(data.get("h", 0)),
                            "low": float(data.get("l", 0)),
                            "volume": float(data.get("v", 0)),
                            "quote_volume": float(data.get("q", 0)),
                            "change_pct": float(data.get("P", 0)) if "P" in data else 0,
                            "timestamp": datetime.now().isoformat(),
                        }

                        # Tinh % thay doi neu API khong tra ve
                        if price_data["change_pct"] == 0 and price_data["open"] > 0:
                            price_data["change_pct"] = round(
                                ((price_data["price"] - price_data["open"]) / price_data["open"]) * 100, 2
                            )

                        self.latest_prices[price_data["symbol"]] = price_data
                        self.last_update_ts = time.time()
                        await self._notify_callbacks(price_data)

            except asyncio.TimeoutError:
                logger.warning("WebSocket timeout, reconnecting...")
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket disconnected, reconnecting in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WebSocket error: {e}, reconnecting in 5s...")
                await asyncio.sleep(5)
            finally:
                self.ws = None
                if self.running and self._generation == generation:
                    # Reset timestamp de cac consumer biet du lieu da cu
                    # (tranh tu hien gia "cu" nhu gia moi)
                    self.last_update_ts = 0.0

    async def get_price_once(self, symbol: str = "btcusdt") -> Optional[dict]:
        """Lay gia 1 lan duy nhat (khong stream lien tuc)."""
        url = f"{BINANCE_WS_URL}/{symbol.lower()}@miniTicker"
        try:
            async with websockets.connect(url) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(raw)
                return {
                    "symbol": data.get("s", ""),
                    "price": float(data.get("c", 0)),
                    "open": float(data.get("o", 0)),
                    "high": float(data.get("h", 0)),
                    "low": float(data.get("l", 0)),
                    "volume": float(data.get("v", 0)),
                    "change_pct": round(
                        ((float(data.get("c", 0)) - float(data.get("o", 1))) / float(data.get("o", 1))) * 100, 2
                    ),
                }
        except Exception as e:
            logger.error(f"Loi lay gia {symbol}: {e}")
            return None

    def stop(self):
        """Dung stream."""
        self.running = False
        logger.info("Da dung Binance WebSocket.")
