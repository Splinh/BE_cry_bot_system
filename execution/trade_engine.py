"""
Trade Engine - He thong giao dich tu dong (Paper Trading).
Cho phep mo vi gia lap 10,000 USDT de tu dong vao lenh theo tin hieu.
Tu dong tinh PnL, chot loi, cat lo.
"""
import os
import json
from datetime import datetime
from loguru import logger
from typing import Optional

from core.config import Config

# SQLite database
try:
    from data.database import db as sqlite_db
except Exception:
    sqlite_db = None


class TradeEngine:
    """
    Paper Trading Engine.
    Luu tru so du ao (Virtual Balance) va cac lenh dang mo (Open Positions).
    """
    DATA_FILE = "data/paper_trading.json"
    INITIAL_BALANCE = 10000.0  # 10k USDT

    def __init__(self):
        self.balance: float = self.INITIAL_BALANCE
        self.positions: dict = {}  # key: signal_key, value: dict
        self.history: list = []
        self.balance_history: list = []  # Lich su nap/rut
        self.auto_trade_enabled: bool = False
        self.last_sync: str = ""
        
        # Risk management: risk 2% tai khoan cho moi lenh (neu cham SL)
        self.risk_per_trade: float = 0.02

        self._load_data()

    def _load_data(self):
        """Doc du lieu vi demo (neu co)."""
        if os.path.exists(self.DATA_FILE):
            try:
                with open(self.DATA_FILE, "r") as f:
                    data = json.load(f)
                    self.balance = data.get("balance", self.INITIAL_BALANCE)
                    self.positions = data.get("positions", {})
                    self.history = data.get("history", [])
                    self.balance_history = data.get("balance_history", [])
                    self.auto_trade_enabled = data.get("auto_trade", False)
            except Exception as e:
                logger.error(f"Loi doc file paper trading: {e}")
        else:
            self._save_data()

    def _save_data(self):
        """Luu trang thai xuong file JSON + SQLite."""
        os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
        try:
            with open(self.DATA_FILE, "w") as f:
                json.dump({
                    "balance": self.balance,
                    "positions": self.positions,
                    "history": self.history[-100:],
                    "balance_history": self.balance_history[-50:],
                    "auto_trade": self.auto_trade_enabled,
                    "last_sync": datetime.now().isoformat()
                }, f, indent=4)
        except Exception as e:
            logger.error(f"Loi ghi file paper trading: {e}")
        
        # Sync to SQLite
        if sqlite_db:
            try:
                sqlite_db.update_balance(self.balance, self.auto_trade_enabled)
                for key, pos in self.positions.items():
                    sqlite_db.save_position(key, pos)
            except Exception as e:
                logger.error(f"SQLite sync error: {e}")

    def toggle_auto_trade(self, enable: bool) -> bool:
        """Bat/Tat che do tu dong vao lenh."""
        self.auto_trade_enabled = enable
        self._save_data()
        return self.auto_trade_enabled

    # ==========================================
    #  NAP / RUT TIEN (Paper Trading)
    # ==========================================

    def deposit(self, amount: float, note: str = "") -> dict:
        """Nap tien vao balance (paper trading)."""
        if amount <= 0:
            return {"success": False, "error": "So tien phai > 0"}
        self.balance += amount
        record = {
            "type": "DEPOSIT",
            "amount": amount,
            "balance_after": round(self.balance, 2),
            "note": note or "Nap tien",
            "time": datetime.now().isoformat(),
        }
        self.balance_history.append(record)
        self._save_data()
        logger.success(f"DEPOSIT +${amount:.2f} | Balance: ${self.balance:.2f} | {note}")
        return {"success": True, **record}

    def withdraw(self, amount: float, note: str = "") -> dict:
        """Rut tien tu balance (paper trading)."""
        if amount <= 0:
            return {"success": False, "error": "So tien phai > 0"}
        if amount > self.balance:
            return {"success": False, "error": f"Khong du so du. Balance: ${self.balance:.2f}"}
        self.balance -= amount
        record = {
            "type": "WITHDRAW",
            "amount": amount,
            "balance_after": round(self.balance, 2),
            "note": note or "Rut tien",
            "time": datetime.now().isoformat(),
        }
        self.balance_history.append(record)
        self._save_data()
        logger.success(f"WITHDRAW -${amount:.2f} | Balance: ${self.balance:.2f} | {note}")
        return {"success": True, **record}

    # ==========================================
    #  AUTO SL/TP MONITOR
    # ==========================================

    def check_sl_tp(self, prices: dict) -> list:
        """
        Kiem tra tat ca positions dang mo.
        Neu gia cham SL/TP -> tu dong dong lenh.
        Return list cac lenh da dong.
        """
        closed_trades = []
        keys_to_check = list(self.positions.keys())

        for sig_key in keys_to_check:
            if sig_key not in self.positions:
                continue
            pos = self.positions[sig_key]
            if pos.get("status") == "CLOSED":
                continue

            coin = pos.get("coin", "")
            symbol = f"{coin}USDT"
            current_price = prices.get(symbol, {}).get("price", 0)
            if current_price <= 0:
                continue

            direction = pos.get("direction", "LONG")
            entry = pos.get("entry_price", 0)
            sl = pos.get("sl", 0)
            tp1 = pos.get("tp1", 0)
            tp2 = pos.get("tp2", 0)
            tp3 = pos.get("tp3", 0)
            leverage = pos.get("leverage", 1)
            closed_pct = pos.get("closed_pct", 0)

            # Kiem tra LIQUIDATION
            if leverage > 1 and entry > 0:
                if direction == "LONG":
                    liq = entry * (1 - 1 / leverage)
                    if current_price <= liq:
                        result = self.close_position(sig_key, current_price, reason="LIQUIDATED")
                        if result:
                            closed_trades.append({"key": sig_key, "reason": "LIQUIDATED", "price": current_price, "pnl": result.get("pnl", 0)})
                        continue
                else:
                    liq = entry * (1 + 1 / leverage)
                    if current_price >= liq:
                        result = self.close_position(sig_key, current_price, reason="LIQUIDATED")
                        if result:
                            closed_trades.append({"key": sig_key, "reason": "LIQUIDATED", "price": current_price, "pnl": result.get("pnl", 0)})
                        continue

            # Kiem tra SL
            if sl > 0:
                if direction == "LONG" and current_price <= sl:
                    result = self.close_position(sig_key, current_price, reason="SL_HIT")
                    if result:
                        closed_trades.append({"key": sig_key, "reason": "SL_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                    continue
                elif direction == "SHORT" and current_price >= sl:
                    result = self.close_position(sig_key, current_price, reason="SL_HIT")
                    if result:
                        closed_trades.append({"key": sig_key, "reason": "SL_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                    continue

            # Kiem tra TP3 (dong het)
            if tp3 > 0:
                if direction == "LONG" and current_price >= tp3:
                    result = self.close_position(sig_key, current_price, reason="TP3_HIT")
                    if result:
                        closed_trades.append({"key": sig_key, "reason": "TP3_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                    continue
                elif direction == "SHORT" and current_price <= tp3:
                    result = self.close_position(sig_key, current_price, reason="TP3_HIT")
                    if result:
                        closed_trades.append({"key": sig_key, "reason": "TP3_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                    continue

            # Kiem tra TP2 (chot 30% phan con lai)
            if tp2 > 0 and closed_pct < 0.6:
                if (direction == "LONG" and current_price >= tp2) or \
                   (direction == "SHORT" and current_price <= tp2):
                    result = self.partial_close(sig_key, current_price, pct_to_close=0.3)
                    if result:
                        closed_trades.append({"key": sig_key, "reason": "TP2_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                    continue

            # Kiem tra TP1 (chot 30%)
            if tp1 > 0 and closed_pct < 0.3:
                if (direction == "LONG" and current_price >= tp1) or \
                   (direction == "SHORT" and current_price <= tp1):
                    result = self.partial_close(sig_key, current_price, pct_to_close=0.3)
                    if result:
                        closed_trades.append({"key": sig_key, "reason": "TP1_HIT", "price": current_price, "pnl": result.get("pnl", 0)})

            # Trailing Stop Loss: dich SL len khi gia tang thuan chieu
            if sig_key in self.positions:
                self._update_trailing_sl(sig_key, current_price)

        return closed_trades

    def _update_trailing_sl(self, sig_key: str, current_price: float):
        """
        Trailing SL: tu dong dich SL de bao ve loi nhuan.
        - Khi gia qua TP1 -> dich SL len break-even (entry)
        - Khi gia qua TP2 -> dich SL len TP1
        Logic chi ap dung neu trailing_sl=True trong position.
        """
        pos = self.positions.get(sig_key)
        if not pos or not pos.get("trailing_sl"):
            return

        direction = pos.get("direction", "LONG")
        entry = pos.get("entry_price", 0)
        sl = pos.get("sl", 0)
        tp1 = pos.get("tp1", 0)
        tp2 = pos.get("tp2", 0)

        new_sl = sl
        if direction == "LONG":
            if tp2 > 0 and current_price >= tp2 and tp1 > sl:
                new_sl = tp1   # Dich SL len TP1
            elif tp1 > 0 and current_price >= tp1 and entry > sl:
                new_sl = entry  # Dich SL len break-even
        else:  # SHORT
            if tp2 > 0 and current_price <= tp2 and tp1 < sl:
                new_sl = tp1
            elif tp1 > 0 and current_price <= tp1 and entry < sl:
                new_sl = entry

        if new_sl != sl:
            pos["sl"] = new_sl
            logger.info(f"TRAILING SL [{sig_key}]: {sl:.4f} -> {new_sl:.4f}")
            self._save_data()

    def calculate_position_size(self, entry_price: float, stop_loss: float) -> float:
        """
        Tinh toan khoi luong Giao dich (USDT Size) dua theo rui ro.
        Cong thuc: Risk_Amount = Balance * Risk%
                   SL_Percent = abs(Entry - SL) / Entry
                   Position_Size = Risk_Amount / SL_Percent
        """
        if entry_price <= 0 or stop_loss <= 0 or entry_price == stop_loss:
            return 0.0

        risk_amount = self.balance * self.risk_per_trade
        sl_pct = abs(entry_price - stop_loss) / entry_price
        
        # Tranh chia cho 0 hoac SL qua be
        if sl_pct < 0.001:
            sl_pct = 0.001

        pos_size = risk_amount / sl_pct
        
        # Bao ve an toan: Max size = 20% tai khoan tren 1 lenh (Danh cho Margin)
        max_size = self.balance * 0.2
        return min(pos_size, max_size)

    def open_manual_position(self, coin: str, direction: str, usdt_size: float,
                              leverage: int = 1, current_price: float = 0,
                              smart_levels: Optional[dict] = None) -> Optional[dict]:
        """
        Mo lenh thu cong tu Web Dashboard.
        User tu chon volume (USDT size) va leverage.
        SL/TP tu dong tinh: uu tien smart_levels (ATR+S/R) > fallback % co dinh.
        """
        if usdt_size <= 0 or current_price <= 0:
            return None
        
        # Kiem tra du so du (margin = size / leverage)
        margin_required = usdt_size / leverage
        if margin_required > self.balance:
            logger.warning(f"Manual trade: Khong du so du. Can ${margin_required:.2f}, co ${self.balance:.2f}")
            return None
        
        # Kiem tra da co vi the cung coin chua
        for pos_key, pos_data in self.positions.items():
            if pos_data["coin"] == coin.upper():
                logger.warning(f"Manual trade: Da co lenh mo voi {coin}")
                return None

        # === SMART SL/TP (ATR + S/R + Fibonacci) ===
        if smart_levels and not smart_levels.get("error"):
            sl = smart_levels["sl"]
            tp1 = smart_levels["tp1"]
            tp2 = smart_levels["tp2"]
            tp3 = smart_levels["tp3"]
            sl_method = smart_levels.get("method", "ATR+S/R+Fib")
            logger.info(f"Smart SL/TP: {sl_method} | ATR={smart_levels.get('atr', 0):.4f}")
        else:
            # === FALLBACK: % CO DINH THEO LEVERAGE ===
            sl_method = "Fixed %"
            if leverage >= 50:
                sl_pct = 0.005
                tp_pcts = [0.01, 0.02, 0.04]
            elif leverage >= 20:
                sl_pct = 0.01
                tp_pcts = [0.02, 0.04, 0.08]
            elif leverage >= 10:
                sl_pct = 0.02
                tp_pcts = [0.03, 0.06, 0.12]
            elif leverage >= 5:
                sl_pct = 0.03
                tp_pcts = [0.05, 0.10, 0.20]
            else:
                sl_pct = 0.05
                tp_pcts = [0.05, 0.10, 0.20]

            if direction == "LONG":
                sl = current_price * (1 - sl_pct)
                tp1 = current_price * (1 + tp_pcts[0])
                tp2 = current_price * (1 + tp_pcts[1])
                tp3 = current_price * (1 + tp_pcts[2])
            else:
                sl = current_price * (1 + sl_pct)
                tp1 = current_price * (1 - tp_pcts[0])
                tp2 = current_price * (1 - tp_pcts[1])
                tp3 = current_price * (1 - tp_pcts[2])

        sig_key = f"MANUAL_{coin.upper()}_{direction}_{datetime.now().strftime('%H%M%S')}"

        pos = {
            "key": sig_key,
            "coin": coin.upper(),
            "type": "FUTURES" if leverage > 1 else "SPOT",
            "direction": direction,
            "entry_price": current_price,
            "sl": round(sl, 4),
            "tp1": round(tp1, 4),
            "tp2": round(tp2, 4),
            "tp3": round(tp3, 4),
            "usdt_size": usdt_size,
            "leverage": leverage,
            "margin": round(margin_required, 2),
            "open_time": datetime.now().isoformat(),
            "close_time": None,
            "close_price": 0.0,
            "pnl": 0.0,
            "status": "OPEN",
            "closed_pct": 0.0,
            "manual": True,
        }

        self.positions[sig_key] = pos
        self.balance -= margin_required
        self._save_data()

        liq_price = current_price * (1 - 1/leverage) if direction == "LONG" else current_price * (1 + 1/leverage)
        logger.success(
            f"MANUAL TRADE: {direction} {coin} x{leverage} | "
            f"Size: ${usdt_size:.2f} | Margin: ${margin_required:.2f} | "
            f"Entry: ${current_price:,.2f} | SL: ${sl:,.2f} | "
            f"Liq: ~${liq_price:,.2f}"
        )
        return pos

    def open_position(self, signal: dict) -> Optional[dict]:
        """
        Mo 1 lenh gia lap tu Signal do AI tao ra.
        Chi vao lenh khi auto_trade_enabled = True.
        """
        if not self.auto_trade_enabled:
            return None

        sig_key = signal["key"]
        
        # Da co vi the cho coin nay chua? De hieu, moi coin chi choi 1 lenh
        for pos_key, pos_data in self.positions.items():
            if pos_data["coin"] == signal["coin"]:
                logger.warning(f"Paper trade: Bo qua {sig_key} vi dang co lenh mo voi {signal['coin']}")
                return None

        entry = signal.get("entry", signal.get("price", 0))
        sl = signal.get("sl", 0)
        direction = signal.get("direction", "LONG")

        if entry <= 0 or sl <= 0:
            logger.warning(f"Paper trade: Signal thieu entry/sl -> Bo qua")
            return None

        # Tinh toan khoi luong
        usdt_size = self.calculate_position_size(entry, sl)
        if usdt_size <= 10:  # Size < 10$ ko dang vao
            logger.warning(f"Paper trade: Size qua xiu (${usdt_size:.2f}) -> Bo qua")
            return None

        # Tinh TP fallback neu signal chi co 1 tp
        single_tp = signal.get("tp", 0)
        tp1 = signal.get("tp1", single_tp or (entry * 1.02 if direction == "LONG" else entry * 0.98))
        tp2 = signal.get("tp2", entry * 1.05 if direction == "LONG" else entry * 0.95)
        tp3 = signal.get("tp3", entry * 1.09 if direction == "LONG" else entry * 0.91)

        # Mo lenh
        pos = {
            "key": sig_key,
            "coin": signal.get("coin", ""),
            "type": signal.get("type", "FUTURES"),
            "direction": direction,
            "entry_price": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "usdt_size": usdt_size,
            "leverage": signal.get("leverage", 1),
            "open_time": datetime.now().isoformat(),
            "close_time": None,
            "close_price": 0.0,
            "pnl": 0.0,
            "status": "OPEN",  # OPEN, PARTIAL, CLOSED
            "closed_pct": 0.0  # Phan tram da chot loi
        }

        self.positions[sig_key] = pos
        
        # Tru so du (Gia lap ky quy - Margin)
        # Giua Spot va Futures deu tru thang Size cho de hieu
        self.balance -= usdt_size
        self._save_data()

        logger.success(f"PAPER TRADE MO LENH: {direction} {pos['coin']} | Size: ${usdt_size:.2f} | Entry: {entry}")
        return pos

    def partial_close(self, sig_key: str, close_price: float, pct_to_close: float = 0.3) -> Optional[dict]:
        """
        Chot loi tung phan (vi du khi cham TP1, chot 30%).
        """
        if sig_key not in self.positions:
            return None

        pos = self.positions[sig_key]
        if pos["status"] == "CLOSED":
            return None

        # Kiem tra da chot het chua
        if pos["closed_pct"] + pct_to_close > 1.0:
            pct_to_close = 1.0 - pos["closed_pct"]

        if pct_to_close <= 0:
            return None

        is_long = pos["direction"] == "LONG"
        price_diff_pct = (close_price - pos["entry_price"]) / pos["entry_price"]
        if not is_long:
            price_diff_pct = -price_diff_pct

        # Tinh PnL cua phan nay
        closed_size = pos["usdt_size"] * pct_to_close
        pnl = closed_size * price_diff_pct

        # Cap nhat tong L/L vao vi
        self.balance += (closed_size + pnl)  # Tra lai goc va cong/tru lai

        pos["closed_pct"] += pct_to_close
        pos["pnl"] += pnl
        
        logger.info(f"PAPER TRADE CHOT 1 PHAN ({pct_to_close*100}%): {sig_key} | Gia chot: {close_price} | PnL tang: ${pnl:.2f}")

        # Neu da chot het => Chuyen sang Close hoan toan
        if pos["closed_pct"] >= 0.99:
            return self.close_position(sig_key, close_price, reason="CHOT HET_TP3")
        
        pos["status"] = "PARTIAL"
        self._save_data()
        return pos

    def close_position(self, sig_key: str, close_price: float, reason: str = "SL_HIT") -> Optional[dict]:
        """
        Dong toan bo phan con lai cua vi the (khi cham SL, hoac TP3).
        """
        if sig_key not in self.positions:
            return None

        pos = self.positions[sig_key]
        if pos["status"] == "CLOSED":
            return None

        rem_pct = 1.0 - pos["closed_pct"]
        if rem_pct <= 0:
            return None

        is_long = pos["direction"] == "LONG"
        price_diff_pct = (close_price - pos["entry_price"]) / pos["entry_price"]
        if not is_long:
            price_diff_pct = -price_diff_pct

        rem_size = pos["usdt_size"] * rem_pct
        pnl = rem_size * price_diff_pct

        # Hoan tra goc va PnL vao Balance
        self.balance += (rem_size + pnl)

        pos["status"] = "CLOSED"
        pos["close_time"] = datetime.now().isoformat()
        pos["close_price"] = close_price
        pos["close_reason"] = reason
        pos["pnl"] += pnl

        logger.info(f"PAPER TRADE DONG LENH: {sig_key} | Ly do: {reason} | PnL phan cuoi: ${pnl:.2f} | Tong PnL: ${pos['pnl']:.2f}")

        # Dua vao history va xoa khoi open positions
        self.history.append(pos)
        del self.positions[sig_key]

        self._save_data()
        return pos
        
    def set_trailing_sl(self, sig_key: str, enable: bool) -> bool:
        """Bat/tat Trailing Stop Loss cho 1 position."""
        if sig_key not in self.positions:
            return False
        self.positions[sig_key]["trailing_sl"] = enable
        self._save_data()
        logger.info(f"Trailing SL [{sig_key}]: {'ON' if enable else 'OFF'}")
        return True

    def get_portfolio_status(self) -> dict:
        """Tra lai trang thai tai khoan de lam bao cao."""
        total_pnl = sum([h.get("pnl", 0) for h in self.history])
        win_count = sum([1 for h in self.history if h.get("pnl", 0) > 0])
        total_trades = len(self.history)
        winrate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
        
        return {
            "balance": self.balance,
            "open_positions": len(self.positions),
            "total_trades": total_trades,
            "win_rate": winrate,
            "total_pnl": total_pnl,
            "auto_trade": self.auto_trade_enabled
        }
