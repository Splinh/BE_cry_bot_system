"""
Price Monitor - Theo doi gia lien tuc va canh bao bien dong.
Chay nhu 1 daemon (24/7), tu dong gui canh bao khi:
- Gia tang/giam > nguong (mac dinh 3%)
- Volume tang dot bien
"""
import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger
from data_ingestion.binance_ws import BinanceWebSocket
from notifiers.telegram_bot import TelegramNotifier

try:
    from data.database import db as _db
except Exception:
    _db = None


class PriceMonitor:
    """
    Giam sat gia lien tuc va gui canh bao ve Telegram
    khi co bien dong bat thuong.
    """

    def __init__(
        self,
        symbols: list[str] = None,
        alert_threshold_pct: float = 3.0,
        update_interval_min: int = 30,
    ):
        self.symbols = symbols or ["btcusdt", "ethusdt", "solusdt", "paxgusdt"]
        self.alert_threshold = alert_threshold_pct
        self.update_interval = update_interval_min * 60  # Convert to seconds
        self.ws = BinanceWebSocket()
        self.notifier = TelegramNotifier()
        self.last_alert: dict[str, datetime] = {}
        self.alert_cooldown = 300  # 5 phut giua 2 lan canh bao cung coin

    async def _on_price_update(self, data: dict):
        """Callback xu ly moi khi co gia moi tu WebSocket."""
        symbol = data.get("symbol", "")
        change = data.get("change_pct", 0)
        price = data.get("price", 0)

        # Kiem tra nguong bien dong
        if abs(change) >= self.alert_threshold:
            now = datetime.now()
            last = self.last_alert.get(symbol)
            if not last or (now - last).total_seconds() >= self.alert_cooldown:
                self.last_alert[symbol] = now
                coin_name = symbol.replace("USDT", "")
                logger.warning(f"CANH BAO: {coin_name} bien dong {change:+.2f}%!")
                await self.notifier.send_price_alert(
                    coin=coin_name,
                    price=price,
                    change_pct=change,
                )

        # Kiem tra price alerts cua user
        if price > 0 and _db:
            await self._check_price_alerts(symbol, price)

    async def _check_price_alerts(self, symbol: str, current_price: float):
        """Kiem tra va kich hoat price alerts khi gia cham muc target."""
        coin = symbol.upper().replace("USDT", "")
        try:
            alerts = _db.get_active_alerts()
            for alert in alerts:
                if alert["coin"] != coin:
                    continue
                target = alert["target_price"]
                direction = alert["direction"]
                triggered = (direction == "above" and current_price >= target) or \
                            (direction == "below" and current_price <= target)
                if triggered:
                    _db.deactivate_alert(alert["id"])
                    dir_text = "VUOT TREN" if direction == "above" else "XUONG DUOI"
                    msg = (
                        f"\U0001f514 <b>PRICE ALERT #{alert['id']}!</b>\n"
                        f"\U0001f4b0 <b>{coin}</b> da {dir_text} muc <code>${target:,.4f}</code>\n"
                        f"Gia hien tai: <code>${current_price:,.4f}</code>"
                    )
                    await self.notifier.send_message(msg, chat_id=alert["chat_id"])
                    logger.info(f"Price alert #{alert['id']} triggered: {coin} {direction} {target}")
        except Exception as e:
            logger.error(f"Price alert check error: {e}")

    async def send_periodic_update(self):
        """Gui bang gia tong hop dinh ky."""
        while True:
            await asyncio.sleep(self.update_interval)

            prices = self.ws.latest_prices
            if not prices:
                continue

            lines = ["<b>CAP NHAT GIA DINH KY</b>", ""]
            for symbol, data in sorted(prices.items()):
                name = symbol.replace("USDT", "")
                change = data.get("change_pct", 0)
                emoji = "+" if change >= 0 else ""
                lines.append(
                    f"<b>{name}:</b> <code>${data['price']:,.2f}</code> ({emoji}{change:.2f}%)"
                )

            now = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
            lines.append(f"\n<i>Thoi gian: {now}</i>")

            await self.notifier.send_message("\n".join(lines))
            logger.info(f"Da gui cap nhat gia dinh ky ({len(prices)} coins)")

    async def start(self):
        """Khoi dong Price Monitor (chay 24/7)."""
        logger.info(f"Price Monitor khoi dong: {len(self.symbols)} coins, nguong canh bao: {self.alert_threshold}%")

        # Dang ky callback canh bao gia
        self.ws.on_price_update(self._on_price_update)

        # Chay song song: WebSocket stream + Cap nhat dinh ky
        await asyncio.gather(
            self.ws.stream_tickers(self.symbols),
            self.send_periodic_update(),
        )

    def stop(self):
        self.ws.stop()
