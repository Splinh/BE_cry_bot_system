"""
Signal Tracker - Theo doi gia va thong bao khi cham TP1/TP2/TP3/SL.
Sau khi user nhan tin hieu, bot tu dong giam sat gia real-time.
Khi gia cham muc TP hoac SL -> gui canh bao ve Telegram.
"""
import asyncio
import html
from datetime import datetime
from typing import Optional

from loguru import logger

from data_ingestion.binance_ws import BinanceWebSocket
from notifiers.telegram_bot import TelegramNotifier
from execution.trade_engine import TradeEngine


class SignalTracker:
    """
    Giam sat cac tin hieu dang hoat dong.
    Khi gia cham TP1/TP2/TP3/SL -> gui thong bao Telegram va auto-trade.
    """

    def __init__(self, trade_engine: Optional[TradeEngine] = None):
        self.active_signals: dict[str, dict] = {}  # key = "BTC_SPOT" or "BTC_FUTURES"
        self.notifier = TelegramNotifier()
        self.trade_engine = trade_engine
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_signal(self, signal: dict):
        """
        Them 1 tin hieu vao danh sach theo doi.
        signal = {
            "key": "BTC_SPOT",
            "coin": "BTC",
            "type": "SPOT" or "FUTURES",
            "direction": "LONG" or "SHORT",
            "entry": 70000,
            "sl": 66500,
            "tp1": 73500, "tp1_hit": False,
            "tp2": 77000, "tp2_hit": False,
            "tp3": 84000, "tp3_hit": False,
            "chat_id": 8023393059,
            "created_at": "...",
        }
        """
        key = signal["key"]
        signal["tp1_hit"] = False
        signal["tp2_hit"] = False
        signal["tp3_hit"] = False
        signal["sl_hit"] = False
        signal["created_at"] = datetime.now().isoformat()
        self.active_signals[key] = signal
        logger.info(f"Dang theo doi: {key} | Entry: ${signal['entry']:,.2f}")
        
        # Thuc hien auto trade neu co engine
        if self.trade_engine:
            self.trade_engine.open_position(signal)

    def remove_signal(self, key: str):
        """Xoa tin hieu khoi danh sach theo doi."""
        if key in self.active_signals:
            del self.active_signals[key]
            logger.info(f"Ngung theo doi: {key}")

    async def check_price(self, coin: str) -> Optional[float]:
        """Lay gia hien tai tu WebSocket."""
        ws = BinanceWebSocket()
        symbol = f"{coin.lower()}usdt"
        try:
            data = await ws.get_price_once(symbol)
            return data["price"] if data else None
        except Exception:
            return None

    async def _check_signals_loop(self):
        """Vong lap kiem tra gia lien tuc."""
        while self._running:
            if not self.active_signals:
                await asyncio.sleep(10)
                continue

            # Lay danh sach coins can theo doi
            coins = set()
            for sig in self.active_signals.values():
                coins.add(sig["coin"])

            # Kiem tra gia tung coin
            for coin in coins:
                current_price = await self.check_price(coin)
                if current_price is None:
                    continue

                # Kiem tra tung signal cua coin nay
                keys_to_remove = []
                for key, sig in list(self.active_signals.items()):
                    if sig["coin"] != coin:
                        continue

                    is_long = sig["direction"] == "LONG"

                    # Kiem tra SL
                    if not sig["sl_hit"]:
                        sl_hit = (current_price <= sig["sl"]) if is_long else (current_price >= sig["sl"])
                        if sl_hit:
                            sig["sl_hit"] = True
                            loss_pct = abs(current_price - sig["entry"]) / sig["entry"] * 100
                            msg = f"\U0001f534 <b>STOP LOSS - {sig['type']}</b>\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += f"\U0001fa99 <b>Coin:</b> {coin}/USDT\n"
                            msg += f"\U0001f4cd <b>Entry:</b> ${sig['entry']:,.2f}\n"
                            msg += f"\U0001f6d1 <b>SL Hit:</b> ${current_price:,.2f}\n"
                            msg += f"\U0001f4c9 <b>Loss:</b> -{loss_pct:.2f}%\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += "Lenh da dong. Cat lo thanh cong."
                            await self.notifier.send_message(msg, chat_id=sig.get("chat_id"))
                            
                            if self.trade_engine:
                                self.trade_engine.close_position(key, current_price, reason="SL_HIT")
                                
                            keys_to_remove.append(key)
                            continue

                    # Kiem tra TP1
                    if not sig["tp1_hit"]:
                        tp1_hit = (current_price >= sig["tp1"]) if is_long else (current_price <= sig["tp1"])
                        if tp1_hit:
                            sig["tp1_hit"] = True
                            profit_pct = abs(current_price - sig["entry"]) / sig["entry"] * 100
                            msg = f"\U0001f7e2 <b>TP1 HIT! - {sig['type']}</b>\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += f"\U0001fa99 <b>Coin:</b> {coin}/USDT\n"
                            msg += f"\U0001f4cd <b>Entry:</b> ${sig['entry']:,.2f}\n"
                            msg += f"\U0001f3af <b>TP1:</b> ${sig['tp1']:,.2f}\n"
                            msg += f"\U0001f4b0 <b>Gia hien tai:</b> ${current_price:,.2f}\n"
                            msg += f"\U0001f4c8 <b>Profit:</b> +{profit_pct:.2f}%\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += "Nen chot 30% vi the. Dich SL len Entry."
                            await self.notifier.send_message(msg, chat_id=sig.get("chat_id"))
                            
                            if self.trade_engine:
                                self.trade_engine.partial_close(key, current_price, pct_to_close=0.3)

                    # Kiem tra TP2
                    if sig["tp1_hit"] and not sig["tp2_hit"]:
                        tp2_hit = (current_price >= sig["tp2"]) if is_long else (current_price <= sig["tp2"])
                        if tp2_hit:
                            sig["tp2_hit"] = True
                            profit_pct = abs(current_price - sig["entry"]) / sig["entry"] * 100
                            msg = f"\U0001f7e2 <b>TP2 HIT! - {sig['type']}</b>\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += f"\U0001fa99 <b>Coin:</b> {coin}/USDT\n"
                            msg += f"\U0001f4cd <b>Entry:</b> ${sig['entry']:,.2f}\n"
                            msg += f"\U0001f3af <b>TP2:</b> ${sig['tp2']:,.2f}\n"
                            msg += f"\U0001f4b0 <b>Gia hien tai:</b> ${current_price:,.2f}\n"
                            msg += f"\U0001f4c8 <b>Profit:</b> +{profit_pct:.2f}%\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += "Nen chot them 30%. Dich SL len TP1."
                            await self.notifier.send_message(msg, chat_id=sig.get("chat_id"))
                            
                            if self.trade_engine:
                                self.trade_engine.partial_close(key, current_price, pct_to_close=0.3)

                    # Kiem tra TP3
                    if sig["tp2_hit"] and not sig["tp3_hit"]:
                        tp3_hit = (current_price >= sig["tp3"]) if is_long else (current_price <= sig["tp3"])
                        if tp3_hit:
                            sig["tp3_hit"] = True
                            profit_pct = abs(current_price - sig["entry"]) / sig["entry"] * 100
                            msg = f"\U0001f7e2\U0001f7e2 <b>TP3 HIT! FULL TARGET - {sig['type']}</b>\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += f"\U0001fa99 <b>Coin:</b> {coin}/USDT\n"
                            msg += f"\U0001f4cd <b>Entry:</b> ${sig['entry']:,.2f}\n"
                            msg += f"\U0001f3af <b>TP3:</b> ${sig['tp3']:,.2f}\n"
                            msg += f"\U0001f4b0 <b>Gia hien tai:</b> ${current_price:,.2f}\n"
                            msg += f"\U0001f4c8 <b>Profit:</b> +{profit_pct:.2f}%\n"
                            msg += "\u2501" * 18 + "\n"
                            msg += "FULL TP! Chot het vi the. Xuat sac!"
                            await self.notifier.send_message(msg, chat_id=sig.get("chat_id"))
                            
                            if self.trade_engine:
                                self.trade_engine.close_position(key, current_price, reason="TP3_HIT")
                                
                            keys_to_remove.append(key)

                for key in keys_to_remove:
                    self.remove_signal(key)

            # Kiem tra moi 15 giay
            await asyncio.sleep(15)

    def load_active_positions(self):
        """Tai cac vi the dang OPEN/PARTIAL tu TradeEngine vao bo theo doi."""
        if not self.trade_engine:
            return
        
        count = 0
        for key, pos in self.trade_engine.positions.items():
            status = pos.get("status")
            if status in ("OPEN", "PARTIAL"):
                # Anh xa tu format position sang signal
                closed_pct = pos.get("closed_pct", 0.0)
                signal = {
                    "key": key,
                    "coin": pos.get("coin"),
                    "type": pos.get("type", "FUTURES"),
                    "direction": pos.get("direction"),
                    "entry": pos.get("entry_price"),
                    "sl": pos.get("sl"),
                    "tp1": pos.get("tp1"),
                    "tp2": pos.get("tp2"),
                    "tp3": pos.get("tp3"),
                    "chat_id": pos.get("chat_id") or self.notifier.chat_id,
                    "leverage": pos.get("leverage", 10),
                    "tf": pos.get("tf", "1h"),
                    "tp1_hit": closed_pct >= 0.3,
                    "tp2_hit": closed_pct >= 0.6,
                    "tp3_hit": False,
                    "sl_hit": False,
                    "created_at": pos.get("open_time", datetime.now().isoformat())
                }
                self.active_signals[key] = signal
                count += 1
                logger.info(f"🔄 Da khoi phuc vi the theo doi: {key} | Huong: {signal['direction']} | Trang thai: {status} | Da chot: {closed_pct*100}%")
        
        if count > 0:
            logger.success(f"🎉 Da khoi phuc thanh cong {count} vi the dang hoat dong vao Signal Tracker.")

    def start(self):
        """Bat dau theo doi (chay background)."""
        if not self._running:
            self.load_active_positions()
            self._running = True
            self._task = asyncio.ensure_future(self._check_signals_loop())
            logger.info("Signal Tracker da khoi dong.")

    def stop(self):
        """Dung theo doi."""
        self._running = False
        if self._task:
            self._task.cancel()

    def get_active_count(self) -> int:
        return len(self.active_signals)

    def list_active(self) -> list[dict]:
        """Liet ke cac tin hieu dang theo doi."""
        result = []
        for key, sig in self.active_signals.items():
            tp_status = ""
            if sig["tp3_hit"]:
                tp_status = "TP3 HIT"
            elif sig["tp2_hit"]:
                tp_status = "TP2 HIT, cho TP3"
            elif sig["tp1_hit"]:
                tp_status = "TP1 HIT, cho TP2"
            else:
                tp_status = "Dang cho TP1"

            result.append({
                "key": key,
                "coin": sig["coin"],
                "type": sig["type"],
                "direction": sig["direction"],
                "entry": sig["entry"],
                "sl": sig["sl"],
                "tp1": sig["tp1"],
                "tp2": sig["tp2"],
                "tp3": sig["tp3"],
                "status": tp_status,
            })
        return result
