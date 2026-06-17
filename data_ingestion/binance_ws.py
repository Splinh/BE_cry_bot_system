"""
Binance WebSocket Client - Lay gia Crypto Real-time.
Module nay ket noi truc tiep vao Binance WebSocket API
de nhan du lieu gia theo thoi gian thuc (< 100ms delay).
"""
import asyncio
import json
from datetime import datetime
from typing import Callable, Optional

import websockets
from loguru import logger


# Binance WebSocket endpoint
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
BINANCE_WS_STREAM = "wss://stream.binance.com:9443/stream?streams="


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

    def on_price_update(self, callback: Callable):
        """Dang ky ham callback khi co gia moi."""
        self.callbacks.append(callback)

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

    async def stream_tickers(self, symbols: list[str]):
        """
        Stream gia real-time cua nhieu coin cung luc.
        symbols: ["btcusdt", "ethusdt", "solusdt"]
        """
        streams = "/".join([f"{s.lower()}@miniTicker" for s in symbols])
        url = f"{BINANCE_WS_STREAM}{streams}"

        self.running = True
        logger.info(f"Ket noi Binance WebSocket: {len(symbols)} coins...")

        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    logger.success(f"Da ket noi Binance WebSocket!")
                    while self.running:
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
                        await self._notify_callbacks(price_data)

            except asyncio.TimeoutError:
                logger.warning("WebSocket timeout, reconnecting...")
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket disconnected, reconnecting in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WebSocket error: {e}, reconnecting in 5s...")
                await asyncio.sleep(5)

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
