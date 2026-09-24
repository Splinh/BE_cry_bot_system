"""
Trade Engine - He thong giao dich tu dong (Paper Trading).
Cho phep mo vi gia lap 10,000 USDT de tu dong vao lenh theo tin hieu.
Tu dong tinh PnL, chot loi, cat lo.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from loguru import logger
from typing import Optional

VN_TZ = timezone(timedelta(hours=7))

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

    # OKX Simulation Constants
    OKX_FUTURES_TAKER_FEE = 0.0005  # 0.05%
    OKX_SPOT_TAKER_FEE = 0.0010     # 0.10%
    OKX_MMR = 0.004                 # 0.4% Maintenance Margin Ratio
    CORRELATED_COINS = {"BTC", "ETH", "SOL"}

    def __init__(self):
        self.balance: float = self.INITIAL_BALANCE
        self.positions: dict = {}  # key: signal_key, value: dict
        self.history: list = []
        self.balance_history: list = []  # Lich su nap/rut
        self.auto_trade_enabled: bool = False
        self.last_sync: str = ""
        self.test_start_time: str = ""
        self.last_error: str = ""
        self.test_start_balance: float = self.INITIAL_BALANCE

        # === Risk management: hard caps tu Config (don vi PCT theo balance + USD tuyet doi) ===
        self.risk_per_trade: float = Config.RISK_PER_TRADE
        self.max_leverage: int = Config.MAX_LEVERAGE
        self.max_margin_per_trade_pct: float = Config.MAX_MARGIN_PER_TRADE_PCT
        self.max_margin_per_trade_usd: float = Config.MAX_MARGIN_PER_TRADE_USD
        self.max_total_margin_pct: float = Config.MAX_TOTAL_MARGIN_PCT
        self.max_total_margin_usd: float = Config.MAX_TOTAL_MARGIN_USD
        self.max_open_positions: int = Config.MAX_OPEN_POSITIONS
        self.max_daily_loss_usd: float = Config.MAX_DAILY_LOSS_USD
        self.max_daily_loss_pct: float = Config.MAX_DAILY_LOSS_PCT
        self.sl_pct_floor: float = Config.SL_PCT_FLOOR
        self.chandelier_atr_multiplier: float = Config.CHANDELIER_ATR_MULTIPLIER
        self.atr_fallback_pct: float = Config.ATR_FALLBACK_PCT

        # Theo doi lo/lai trong ngay de kich hoat khoa giao dich (circuit breaker)
        self.daily_date: str = ""          # YYYY-MM-DD cua phien hien tai
        self.daily_realized_pnl: float = 0.0
        self.daily_start_balance: float = 0.0

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
                    self.daily_date = data.get("daily_date", "")
                    self.daily_realized_pnl = data.get("daily_realized_pnl", 0.0)
                    self.daily_start_balance = data.get("daily_start_balance", 0.0)
                    self.test_start_time = data.get("test_start_time", "")
                    self.test_start_balance = data.get("test_start_balance", self.balance)
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
                    "daily_date": self.daily_date,
                    "daily_realized_pnl": self.daily_realized_pnl,
                    "daily_start_balance": self.daily_start_balance,
                    "test_start_time": self.test_start_time,
                    "test_start_balance": self.test_start_balance,
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

    @staticmethod
    def compare_timeframes(tf1: str, tf2: str) -> int:
        """
        So sanh 2 khung thoi gian.
        Tra ve:
           -1 neu tf1 < tf2
            0 neu tf1 == tf2
            1 neu tf1 > tf2
        """
        order = {"15m": 1, "1h": 2, "4h": 3, "1d": 4}
        val1 = order.get(str(tf1).lower(), 0)
        val2 = order.get(str(tf2).lower(), 0)
        if val1 < val2:
            return -1
        elif val1 > val2:
            return 1
        return 0

    def get_current_price_sync(self, coin: str) -> float:
        """Lay gia hien tai cua 1 dong coin dong bo."""
        import ccxt
        try:
            exchange = ccxt.binance({"enableRateLimit": True})
            ticker = exchange.fetch_ticker(f"{coin.upper()}/USDT")
            return float(ticker["last"])
        except Exception as e:
            logger.error(f"Loi lay gia dong bo cho {coin}: {e}")
            return 0.0

    def send_notification_sync(self, text: str):
        """Gui thong bao Telegram & Zalo bat dong bo tu moi truong dong bo."""
        try:
            import asyncio
            from notifiers.telegram_bot import TelegramNotifier
            from notifiers.zalo_bot import ZaloNotifier

            async def _send():
                try:
                    tg = TelegramNotifier()
                    await tg.send_message(text, chat_id=tg.chat_id)
                except Exception as e:
                    logger.error(f"Loi gui Telegram: {e}")
                try:
                    zalo = ZaloNotifier()
                    await zalo.send_message(text)
                except Exception as e:
                    logger.error(f"Loi gui Zalo: {e}")

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_send())
            else:
                loop.run_until_complete(_send())
        except Exception as e:
            logger.error(f"Loi gui thong bao sync: {e}")

    # ==========================================
    #  RISK GUARDS (hard caps tuyet doi)
    # ==========================================

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _roll_daily(self):
        """Reset bo dem lo/lai khi sang ngay moi (tinh theo gio local)."""
        today = self._today()
        if self.daily_date != today:
            self.daily_date = today
            self.daily_realized_pnl = 0.0
            self.daily_start_balance = self.balance
            self._save_data()

    def _record_realized_pnl(self, pnl: float):
        """Cong don PnL da chot vao bo dem ngay (goi tu partial_close/close_position)."""
        self._roll_daily()
        self.daily_realized_pnl += pnl

    def current_total_margin(self) -> float:
        """Tong margin dang bi khoa boi cac lenh mo (phan chua chot)."""
        total = 0.0
        for pos in self.positions.values():
            if pos.get("status") == "CLOSED":
                continue
            rem_pct = 1.0 - pos.get("closed_pct", 0.0)
            total += pos.get("margin", 0.0) * max(rem_pct, 0.0)
        return total

    def daily_loss_limit_usd(self) -> float:
        """Nguong lo/ngay tuyet doi = min(cap USD, cap % balance dau ngay)."""
        base = self.daily_start_balance or self.balance
        pct_cap = base * self.max_daily_loss_pct
        return min(self.max_daily_loss_usd, pct_cap)

    def is_trading_locked(self) -> bool:
        """True neu da cham nguong lo/ngay -> khoa mo lenh moi (circuit breaker)."""
        self._roll_daily()
        return self.daily_realized_pnl <= -self.daily_loss_limit_usd()

    def can_open_position(self, margin_required: float, leverage: int = 1) -> tuple:
        """
        Kiem tra tat ca hard cap truoc khi mo lenh.
        Return (ok: bool, reason: str). reason rong neu ok.
        """
        self._roll_daily()

        if leverage < 1 or leverage > self.max_leverage:
            return False, f"Đòn bẩy {leverage}x vượt giới hạn an toàn (cho phép 1-{self.max_leverage}x)."

        if self.is_trading_locked():
            return False, (f"Da cham gioi han lo/ngay "
                           f"(${self.daily_realized_pnl:.2f} / -${self.daily_loss_limit_usd():.2f}). Khoa den ngay mai.")

        open_count = sum(1 for p in self.positions.values() if p.get("status") != "CLOSED")
        if open_count >= self.max_open_positions:
            return False, f"Da dat so lenh mo toi da ({self.max_open_positions})."

        margin_cap = min(self.max_margin_per_trade_usd, self.balance * self.max_margin_per_trade_pct)
        if margin_required > margin_cap + 1e-9:
            return False, f"Margin/lenh ${margin_required:.2f} vuot cap ${margin_cap:.2f}."

        total_cap = min(self.max_total_margin_usd, self.balance * self.max_total_margin_pct)
        if self.current_total_margin() + margin_required > total_cap + 1e-9:
            return False, (f"Tong margin ${self.current_total_margin() + margin_required:.2f} "
                           f"vuot cap ${total_cap:.2f}.")

        if margin_required > self.balance:
            return False, f"Khong du so du (can ${margin_required:.2f}, co ${self.balance:.2f})."

        return True, ""

    # ==========================================
    #  DCA (gop lenh cung coin trong cung vi)
    # ==========================================

    def find_open_position_by_coin(self, coin: str) -> Optional[tuple]:
        """Tra ve (key, pos) cua lenh dang mo cho coin, hoac None."""
        coin = coin.upper()
        for k, p in self.positions.items():
            if p.get("status") != "CLOSED" and p.get("coin", "").upper() == coin:
                return k, p
        return None

    def _apply_dca(self, pos: dict, add_size: float, add_entry: float) -> Optional[float]:
        """
        Gop them khoi luong vao vi the cung chieu (DCA nhu cac san):
        - Binh quan gia vao (weighted theo usdt_size)
        - Cong don size + margin, tru margin moi khoi balance
        - GIU NGUYEN SL/TP & tien do chot (closed_pct) cua lenh goc
        Tra ve margin da tru, hoac None neu khong du so du.
        """
        leverage = pos.get("leverage", 1) or 1
        add_margin = add_size / leverage
        if add_margin > self.balance:
            return None

        old_size = pos.get("usdt_size", 0.0)
        new_total = old_size + add_size
        if new_total <= 0:
            return None

        avg_entry = (old_size * pos.get("entry_price", add_entry) + add_size * add_entry) / new_total
        pos["entry_price"] = avg_entry
        pos["usdt_size"] = new_total
        pos["margin"] = round(pos.get("margin", 0.0) + add_margin, 2)
        pos["dca_count"] = pos.get("dca_count", 0) + 1
        pos["last_dca_time"] = datetime.now().isoformat()
        if pos.get("status") == "CLOSED":
            pos["status"] = "OPEN"

        self.balance -= add_margin
        self._save_data()
        return add_margin

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
                liq = pos.get("liq_price")
                if not liq:
                    liq = entry * (1 - 1 / leverage + self.OKX_MMR) if direction == "LONG" else entry * (1 + 1 / leverage - self.OKX_MMR)
                
                if direction == "LONG":
                    if current_price <= liq:
                        result = self.close_position(sig_key, current_price, reason="LIQUIDATED")
                        if result:
                            closed_trades.append({"key": sig_key, "reason": "LIQUIDATED", "price": current_price, "pnl": result.get("pnl", 0)})
                        continue
                else:
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

            # Kiem tra TP3 (chot 25% tiep theo -> tong 75%, kich hoat 25% Runner Position)
            if tp3 > 0 and closed_pct < 0.75:
                if (direction == "LONG" and current_price >= tp3) or \
                   (direction == "SHORT" and current_price <= tp3):
                    result = self.partial_close(sig_key, current_price, pct_to_close=0.25)
                    if result:
                        pos["runner_mode"] = True
                        self._update_trailing_sl(sig_key, current_price)
                        closed_trades.append({"key": sig_key, "reason": "TP3_HIT_RUNNER_START", "price": current_price, "pnl": result.get("pnl", 0)})
                        continue

            # Kiem tra TP2 (chot 25% phan tiep theo -> tong 50%)
            if tp2 > 0 and closed_pct < 0.50:
                if (direction == "LONG" and current_price >= tp2) or \
                   (direction == "SHORT" and current_price <= tp2):
                    result = self.partial_close(sig_key, current_price, pct_to_close=0.25)
                    if result:
                        self._update_trailing_sl(sig_key, current_price)
                        closed_trades.append({"key": sig_key, "reason": "TP2_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                        continue

            # Kiem tra TP1 (chot 25% dau tien)
            if tp1 > 0 and closed_pct < 0.25:
                if (direction == "LONG" and current_price >= tp1) or \
                   (direction == "SHORT" and current_price <= tp1):
                    result = self.partial_close(sig_key, current_price, pct_to_close=0.25)
                    if result:
                        self._update_trailing_sl(sig_key, current_price)
                        closed_trades.append({"key": sig_key, "reason": "TP1_HIT", "price": current_price, "pnl": result.get("pnl", 0)})
                        continue

            # Trailing Stop Loss (Chandelier ATR Trail): dich SL theo peak/trough
            if sig_key in self.positions:
                self._update_trailing_sl(sig_key, current_price)

        return closed_trades

    def _update_trailing_sl(self, sig_key: str, current_price: float):
        """
        Trailing SL (Chandelier ATR Trail + Multi-Stage Profit Lock):
        - Chandelier (luôn active, improve-only): SL = peak/trough -+ CHANDELIER_ATR_MULTIPLIER * ATR,
          chỉ kéo khi mức mới TỐT HƠN SL hiện tại và còn nằm đúng phía so với giá hiện tại.
        - Giai đoạn 1: closed_pct >= 0.25 (Đã chạm TP1) -> Khóa SL về Entry (Hòa vốn / Break-Even).
        - Giai đoạn 2: closed_pct >= 0.50 (Đã chạm TP2) -> Khóa SL lên TP1 (Khóa một phần lợi nhuận cứng).
        - Giai đoạn 3: closed_pct >= 0.75 hoặc runner_mode=True (Đã chạm TP3) -> Runner tiếp tục chạy bằng Chandelier (đã active từ đầu).
        """
        pos = self.positions.get(sig_key)
        if not pos or not pos.get("trailing_sl", True):
            return

        if current_price <= 0:
            return

        direction = pos.get("direction", "LONG")
        entry = pos.get("entry_price", 0)
        sl = pos.get("sl", 0)
        tp1 = pos.get("tp1", 0)
        closed_pct = pos.get("closed_pct", 0)

        # ATR từ signal/Smart Levels; fallback = ATR_FALLBACK_PCT * entry
        atr = pos.get("atr", 0)
        if not atr or atr <= 0:
            atr = entry * self.atr_fallback_pct if entry > 0 else 0
        if atr <= 0:
            return

        new_sl = sl
        if direction == "LONG":
            peak = max(pos.get("peak_price", entry), current_price)
            pos["peak_price"] = round(peak, 4)

            # Giai đoạn 1: Sau TP1 -> Lock Break-Even (Entry), chỉ kéo khi entry còn dưới giá hiện tại
            if closed_pct >= 0.25 and entry > 0 and entry < current_price:
                new_sl = max(new_sl, entry)

            # Giai đoạn 2: Sau TP2 -> Lock TP1, chỉ kéo khi tp1 còn dưới giá hiện tại
            if closed_pct >= 0.50 and tp1 > 0 and tp1 < current_price:
                new_sl = max(new_sl, tp1)

            # Chandelier ATR Trailing Stop (luôn active, improve-only) từ đỉnh cao nhất
            chandelier_sl = peak - self.chandelier_atr_multiplier * atr
            if chandelier_sl > new_sl and chandelier_sl < current_price:
                new_sl = round(chandelier_sl, 4)

        else:  # SHORT
            trough = min(pos.get("trough_price", entry), current_price)
            pos["trough_price"] = round(trough, 4)

            # Giai đoạn 1: Sau TP1 -> Lock Break-Even (Entry), chỉ kéo khi entry còn trên giá hiện tại
            if closed_pct >= 0.25 and entry > 0 and entry > current_price:
                new_sl = min(new_sl, entry) if new_sl > 0 else entry

            # Giai đoạn 2: Sau TP2 -> Lock TP1, chỉ kéo khi tp1 còn trên giá hiện tại
            if closed_pct >= 0.50 and tp1 > 0 and tp1 > current_price:
                new_sl = min(new_sl, tp1) if new_sl > 0 else tp1

            # Chandelier ATR Trailing Stop (luôn active, improve-only) từ đáy thấp nhất
            chandelier_sl = trough + self.chandelier_atr_multiplier * atr
            if (new_sl <= 0 or chandelier_sl < new_sl) and chandelier_sl > current_price:
                new_sl = round(chandelier_sl, 4)

        if new_sl != sl:
            pos["sl"] = new_sl
            logger.info(f"TRAILING SL [{sig_key}]: {sl:.4f} -> {new_sl:.4f} (Stage closed_pct={closed_pct:.0%})")
            self._save_data()

    def calculate_position_size(self, entry_price: float, stop_loss: float, leverage: int = 1) -> float:
        """
        Tính toán khối lượng giao dịch (USDT Size) dựa theo rủi ro, leverage và margin chuẩn hóa.
        - Invariant: loss tại SL (size * raw_sl_pct) <= balance * risk_per_trade.
        - Tránh phóng đại size khi SL quá gần (sàn SL% = SL_PCT_FLOOR khi tính size).
        - Margin mỗi lệnh bị khống chế bởi min(max_margin_per_trade_usd, balance * max_margin_per_trade_pct).
        """
        if entry_price <= 0 or stop_loss <= 0 or entry_price == stop_loss:
            return 0.0

        risk_amount = self.balance * self.risk_per_trade  # 2% balance
        raw_sl_pct = abs(entry_price - stop_loss) / entry_price
        
        # Sàn SL% tối thiểu (SL_PCT_FLOOR) khi tính size, tránh SL quá gần làm bùng nổ size
        sl_pct_for_size = max(raw_sl_pct, self.sl_pct_floor)

        # Size theo risk formula
        pos_size = risk_amount / sl_pct_for_size

        # Margin cap mỗi lệnh: min(giới hạn USD tuyệt đối, % balance) — đồng bộ can_open_position.
        # Cap chỉ GIẢM size; đã bỏ sàn min-margin 3% để giữ invariant loss-at-SL <= risk_per_trade.
        margin_cap = min(self.max_margin_per_trade_usd, self.balance * self.max_margin_per_trade_pct)
        pos_size = min(pos_size, margin_cap * leverage)

        # Đảm bảo không vượt quá số dư khả dụng
        max_possible_size = (self.balance * 0.95) * leverage
        return round(min(pos_size, max_possible_size), 2)

    def open_manual_position(self, coin: str, direction: str, usdt_size: float,
                             leverage: int = 1, current_price: float = 0,
                             smart_levels: Optional[dict] = None,
                             wallet_id: Optional[int] = None,
                             wallet_label: str = "") -> Optional[dict]:
        """
        Mo lenh thu cong tu Web Dashboard.
        - Cung coin + cung direction + cung wallet -> DCA (gop lenh, binh quan gia)
        - Cung coin + cung direction + khac wallet -> Mo lenh rieng
        - Cung coin + khac direction -> Mo lenh rieng (hedge)
        """
        if usdt_size <= 0 or current_price <= 0:
            return None

        is_live = sqlite_db and sqlite_db.get_live_mode()
        margin_required = usdt_size / leverage

        if is_live:
            self.sync_binance_balance()

        # Enforce Risk Guards
        ok, reason = self.can_open_position(margin_required, leverage=leverage)
        if not ok:
            self.last_error = reason
            logger.warning(f"Manual trade blocked: {reason}")
            return None

        if margin_required > self.balance:
            self.last_error = f"Khong du so du. Can ${margin_required:.2f}, co ${self.balance:.2f}"
            logger.warning(f"Manual trade: {self.last_error}")
            return None

        # Thực thi lệnh Live trên Binance Futures
        live_order = None
        if is_live:
            try:
                live_order = self._execute_binance_trade(coin, direction, usdt_size, leverage)
                if live_order and live_order.get("success"):
                    current_price = live_order["price"]
            except Exception as e:
                logger.error(f"Failed to place live order on Binance: {e}")
                return None

        # Tim lenh da mo: cung coin + cung direction + cung wallet
        existing_key = None
        for pos_key, pos_data in self.positions.items():
            if (pos_data["coin"] == coin.upper()
                and pos_data.get("direction") == direction.upper()
                and pos_data.get("status") != "CLOSED"
                and pos_data.get("wallet_id") == wallet_id
                and pos_data.get("live", False) == is_live):
                existing_key = pos_key
                break
        
        # === DCA: Gop vao lenh cu (cung coin + direction + wallet) ===
        if existing_key:
            pos = self.positions[existing_key]
            old_size = pos.get("usdt_size", 0)
            old_entry = pos.get("entry_price", current_price)
            new_total_size = old_size + usdt_size
            
            # Binh quan gia vao (weighted average)
            avg_entry = (old_size * old_entry + usdt_size * current_price) / new_total_size
            
            # OKX fee calculation
            fee_rate = self.OKX_FUTURES_TAKER_FEE if leverage > 1 else self.OKX_SPOT_TAKER_FEE
            new_open_fee = usdt_size * fee_rate

            # Cap nhat position
            pos["entry_price"] = avg_entry
            pos["usdt_size"] = new_total_size
            pos["margin"] = round(pos.get("margin", 0) + margin_required, 2)
            pos["dca_count"] = pos.get("dca_count", 0) + 1
            pos["last_dca_time"] = datetime.now().isoformat()
            pos["last_dca_price"] = current_price
            pos["fees_paid"] = round(pos.get("fees_paid", 0) + new_open_fee, 4)
            
            # Re-calculate Liquidation Price for DCA
            if leverage > 1:
                new_liq = avg_entry * (1 - 1 / leverage + self.OKX_MMR) if direction.upper() == "LONG" else avg_entry * (1 + 1 / leverage - self.OKX_MMR)
                pos["liq_price"] = round(new_liq, 4)
            else:
                pos["liq_price"] = 0.0

            if is_live and live_order:
                pos["live_qty"] = pos.get("live_qty", 0.0) + live_order["amount"]
                pos["binance_order_ids"] = pos.get("binance_order_ids", []) + [live_order["order_id"]]
            
            # Re-calculate SL/TP dua tren gia binh quan moi
            if smart_levels and not smart_levels.get("error"):
                pos["sl"] = round(smart_levels["sl"], 4)
                pos["tp1"] = round(smart_levels["tp1"], 4)
                pos["tp2"] = round(smart_levels["tp2"], 4)
                pos["tp3"] = round(smart_levels["tp3"], 4)
                pos["atr"] = smart_levels.get("atr", 0) or pos.get("atr", 0)

            # Refresh peak/trough theo gia moi sau khi DCA binh quan
            if direction.upper() == "LONG":
                pos["peak_price"] = round(max(pos.get("peak_price", avg_entry), current_price), 4)
            else:
                pos["trough_price"] = round(min(pos.get("trough_price", avg_entry), current_price), 4)
            
            if not is_live:
                self.balance -= (margin_required + new_open_fee)
            else:
                self.sync_binance_balance()
            
            self._save_data()
            
            logger.success(
                f"DCA #{pos['dca_count']}: {direction} {coin} x{leverage} | "
                f"+${usdt_size:.2f} -> Total: ${new_total_size:.2f} | "
                f"Avg Entry: ${avg_entry:,.2f} (was ${old_entry:,.2f}) | "
                f"Wallet: {wallet_label or 'Default'} | Live: {is_live}"
            )
            return pos

        # === Mo lenh moi ===
        # Smart SL/TP
        if smart_levels and not smart_levels.get("error"):
            sl = smart_levels["sl"]
            tp1 = smart_levels["tp1"]
            tp2 = smart_levels["tp2"]
            tp3 = smart_levels["tp3"]
            sl_method = smart_levels.get("method", "ATR+S/R+Fib")
            logger.info(f"Smart SL/TP: {sl_method} | ATR={smart_levels.get('atr', 0):.4f}")
        else:
            # Fallback: % co dinh theo leverage
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

        sig_key = f"MANUAL_{coin.upper()}_{direction}_{datetime.now().strftime('%H%M%S%f')}"

        # OKX Simulation Calculations
        fee_rate = self.OKX_FUTURES_TAKER_FEE if leverage > 1 else self.OKX_SPOT_TAKER_FEE
        open_fee = usdt_size * fee_rate
        
        if leverage > 1:
            liq_price = current_price * (1 - 1 / leverage + self.OKX_MMR) if direction.upper() == "LONG" else current_price * (1 + 1 / leverage - self.OKX_MMR)
        else:
            liq_price = 0.0

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
            "open_time": datetime.now(VN_TZ).isoformat(),
            "close_time": None,
            "close_price": 0.0,
            "pnl": 0.0,
            "status": "OPEN",
            "closed_pct": 0.0,
            "manual": True,
            "wallet_id": wallet_id,
            "wallet_label": wallet_label or "",
            "dca_count": 0,
            "live": is_live,
            "fee_rate": fee_rate,
            "fees_paid": round(open_fee, 4),
            "liq_price": round(liq_price, 4),
            "trailing_sl": True,
            "peak_price": current_price,
            "trough_price": current_price,
            "runner_mode": False,
            "atr": smart_levels.get("atr", 0) if smart_levels else 0,
        }

        if is_live and live_order:
            pos["live_qty"] = live_order["amount"]
            pos["binance_order_ids"] = [live_order["order_id"]]

        self.positions[sig_key] = pos
        if not is_live:
            self.balance -= (margin_required + open_fee)
        else:
            self.sync_binance_balance()

        self._save_data()

        logger.success(
            f"MANUAL TRADE: {direction} {coin} x{leverage} | "
            f"Size: ${usdt_size:.2f} | Margin: ${margin_required:.2f} | "
            f"Entry: ${current_price:,.2f} | SL: ${sl:,.2f} | "
            f"Liq: ~${liq_price:,.2f} | Wallet: {wallet_label or 'Default'} | Live: {is_live}"
        )
        return pos

    def open_position(self, signal: dict) -> Optional[dict]:
        """
        Mo 1 lenh gia lap hoac thuc te tu Signal do AI tao ra.
        Chi vao lenh khi auto_trade_enabled = True.
        """
        if not self.auto_trade_enabled:
            return None

        is_live = sqlite_db and sqlite_db.get_live_mode()
        sig_key = signal["key"]
        coin = signal.get("coin", "").upper()
        direction = signal.get("direction", "LONG").upper()
        entry = signal.get("entry", signal.get("price", 0))
        sl = signal.get("sl", 0)
        rating = signal.get("rating", 3)
        tf = signal.get("tf", "1h")

        if entry <= 0 or sl <= 0:
            logger.warning(f"TradeEngine: Signal thieu entry/sl -> Bo qua")
            return None

        # 1. KIỂM TRA ĐẢO CHIỀU TRỰC TIẾP TRÊN CÙNG ĐỒNG COIN
        same_coin_pos_key = None
        same_coin_pos_data = None
        for pos_key, pos_data in self.positions.items():
            if pos_data.get("coin", "").upper() == coin and pos_data.get("status") != "CLOSED" and pos_data.get("live", False) == is_live:
                same_coin_pos_key = pos_key
                same_coin_pos_data = pos_data
                break

        if same_coin_pos_data:
            existing_dir = same_coin_pos_data.get("direction", "LONG").upper()
            if existing_dir != direction and rating >= 4 and self.compare_timeframes(tf, same_coin_pos_data.get("tf", "1h")) >= 0:
                # Thực hiện đảo chiều vị thế: Đóng lệnh cũ
                current_price = self.get_current_price_sync(coin) or entry
                logger.info(f"🔄 [Đảo Chiều] Đóng {coin} {existing_dir} cũ (giá {current_price}) để mở {direction} mới.")
                self.close_position(same_coin_pos_key, current_price, reason="REVERSAL_SIGNAL")
                
                msg_text = (
                    f"🔄 <b>ĐẢO CHIỀU VỊ THẾ - {coin}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Phát hiện tín hiệu <b>{direction} ({tf})</b> cực mạnh ({rating} sao).\n"
                    f"Hệ thống đã tự động đóng vị thế <b>{existing_dir}</b> cũ để chuẩn bị mở vị thế <b>{direction}</b> mới.\n"
                    f"Giá đóng vị thế cũ: ${current_price:,.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━"
                )
                self.send_notification_sync(msg_text)
            else:
                logger.warning(f"TradeEngine: Bo qua {sig_key} vi dang co lenh mo voi {coin} (Live: {is_live})")
                return None

        # 2. PHÒNG VỆ XU HƯỚNG CHÉO (CORRELATION PROTECTION)
        if coin in self.CORRELATED_COINS and rating >= 4 and tf in ("4h", "1d"):
            for pos_key, pos_data in list(self.positions.items()):
                pos_coin = pos_data.get("coin", "").upper()
                pos_status = pos_data.get("status", "")
                pos_dir = pos_data.get("direction", "").upper()
                pos_live = pos_data.get("live", False)
                
                if (pos_coin in self.CORRELATED_COINS and pos_coin != coin 
                        and pos_status != "CLOSED" and pos_live == is_live 
                        and pos_dir != direction):
                    # Vị thế đối nghịch trên đồng coin tương quan. Áp dụng phòng vệ:
                    # a) Dời SL về Entry (chỉ khi entry hợp lệ và tốt hơn SL hiện tại)
                    entry_p = pos_data.get("entry_price", 0)
                    cur_sl = pos_data.get("sl", 0)
                    if entry_p > 0:
                        if pos_dir == "LONG":
                            if cur_sl <= 0 or entry_p > cur_sl:
                                pos_data["sl"] = entry_p
                        else:  # SHORT
                            if cur_sl <= 0 or entry_p < cur_sl:
                                pos_data["sl"] = entry_p
                    
                    # b) Chốt lời / Giảm vị thế 50%
                    opp_price = self.get_current_price_sync(pos_coin) or entry_p
                    logger.info(f"⚠️ [Phòng Vệ Chéo] Giảm 50% vị thế {pos_coin} {pos_dir} ở giá {opp_price} do có tín hiệu {direction} {coin} mạnh.")
                    self.partial_close(pos_key, opp_price, pct_to_close=0.5)
                    
                    msg_text = (
                        f"⚠️ <b>PHÒNG VỆ XU HƯỚNG CHÉO (HEDGE)</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"Tín hiệu mới: { '🟢' if direction == 'LONG' else '🔴' } <b>{direction} {coin} ({tf})</b> cực mạnh ({rating} sao).\n"
                        f"Hệ thống đã tự động phòng vệ vị thế đối nghịch đang mở:\n"
                        f"• Đã dời SL vị thế <b>{pos_coin} {pos_dir}</b> về Entry (${entry_p:,.4f}).\n"
                        f"• Đã tự động chốt lời/giảm volume vị thế 50% ở giá ${opp_price:,.4f}.\n"
                        f"━━━━━━━━━━━━━━━━━━"
                    )
                    self.send_notification_sync(msg_text)

        # Tinh toan khoi luong
        leverage = signal.get("leverage", 1)
        usdt_size = self.calculate_position_size(entry, sl, leverage)
        if usdt_size <= 10:  # Size < 10$ ko dang vao
            logger.warning(f"TradeEngine: Size qua xiu (${usdt_size:.2f}) -> Bo qua")
            return None

        # Tinh TP fallback neu signal chi co 1 tp
        single_tp = signal.get("tp", 0)
        tp1 = signal.get("tp1", single_tp or (entry * 1.02 if direction == "LONG" else entry * 0.98))
        tp2 = signal.get("tp2", entry * 1.05 if direction == "LONG" else entry * 0.95)
        tp3 = signal.get("tp3", entry * 1.09 if direction == "LONG" else entry * 0.91)

        # Mo lenh
        margin_required = usdt_size / leverage

        if is_live:
            self.sync_binance_balance()

        # Enforce Risk Guards
        ok, reason = self.can_open_position(margin_required, leverage=leverage)
        if not ok:
            logger.warning(f"Auto trade blocked: {reason}")
            msg_blocked = (
                f"⚠️ <b>TÍN HIỆU BỊ CHẶN (RISK GUARD)</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Không thể tự động mở vị thế <b>{direction} {coin}</b> ({tf}).\n"
                f"Lý do: <b>{reason}</b>\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            self.send_notification_sync(msg_blocked)
            return None

        if margin_required > self.balance:
            logger.warning(f"Auto trade: Khong du so du. Can ${margin_required:.2f}, co ${self.balance:.2f}")
            return None

        live_order = None
        if is_live:
            try:
                live_order = self._execute_binance_trade(signal["coin"], direction, usdt_size, leverage)
                if live_order and live_order.get("success"):
                    entry = live_order["price"]
            except Exception as e:
                logger.error(f"Failed to place live order on Binance: {e}")
                return None

        # OKX Simulation Calculations
        fee_rate = self.OKX_FUTURES_TAKER_FEE if leverage > 1 else self.OKX_SPOT_TAKER_FEE
        open_fee = usdt_size * fee_rate
        
        if leverage > 1:
            liq_price = entry * (1 - 1 / leverage + self.OKX_MMR) if direction.upper() == "LONG" else entry * (1 + 1 / leverage - self.OKX_MMR)
        else:
            liq_price = 0.0

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
            "leverage": leverage,
            "margin": round(margin_required, 2),
            "open_time": datetime.now(VN_TZ).isoformat(),
            "close_time": None,
            "close_price": 0.0,
            "pnl": 0.0,
            "status": "OPEN",  # OPEN, PARTIAL, CLOSED
            "closed_pct": 0.0,  # Phan tram da chot loi
            "live": is_live,
            "fee_rate": fee_rate,
            "fees_paid": round(open_fee, 4),
            "liq_price": round(liq_price, 4),
            "tf": tf,
            "rating": rating,
            "trailing_sl": True,
            "peak_price": entry,
            "trough_price": entry,
            "runner_mode": False,
            "atr": signal.get("atr", 0),
            "ai_details": signal.get("ai_details", {}),
        }

        if is_live and live_order:
            pos["live_qty"] = live_order["amount"]
            pos["binance_order_ids"] = [live_order["order_id"]]

        self.positions[sig_key] = pos
        
        # Tru so du (Gia lap ky quy - Margin + Phí mở)
        if not is_live:
            self.balance -= (margin_required + open_fee)
        else:
            self.sync_binance_balance()
        self._save_data()

        logger.success(f"TRADE MO LENH: {direction} {pos['coin']} | Size: ${usdt_size:.2f} | Entry: {entry} | Live: {is_live}")
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
        leverage = pos.get("leverage", 1)
        closed_size = pos["usdt_size"] * pct_to_close
        closed_margin = closed_size / leverage
        pnl = closed_size * price_diff_pct

        is_live = pos.get("live", False)
        if is_live:
            try:
                live_qty = pos.get("live_qty", 0.0)
                qty_to_close = live_qty * pct_to_close
                if qty_to_close > 0:
                    self._execute_binance_close(pos["coin"], pos["direction"], qty_to_close)
            except Exception as e:
                logger.error(f"Failed to partial close live order on Binance for {sig_key}: {e}")

        if is_live:
            self.sync_binance_balance()
        else:
            fee_rate = pos.get("fee_rate", self.OKX_FUTURES_TAKER_FEE if leverage > 1 else self.OKX_SPOT_TAKER_FEE)
            close_fee = closed_size * fee_rate
            self.balance += (closed_margin + pnl - close_fee)
            pos["fees_paid"] = round(pos.get("fees_paid", 0.0) + close_fee, 4)

        pos["closed_pct"] += pct_to_close
        pos["pnl"] += pnl
        
        logger.info(f"TRADE CHOT 1 PHAN ({pct_to_close*100}%): {sig_key} | Gia chot: {close_price} | PnL tang: ${pnl:.2f} | Fees tang: ${close_fee if not is_live else 0:.4f} | Live: {is_live}")

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

        leverage = pos.get("leverage", 1)
        rem_size = pos["usdt_size"] * rem_pct
        rem_margin = rem_size / leverage
        pnl = rem_size * price_diff_pct

        is_live = pos.get("live", False)
        if is_live:
            try:
                live_qty = pos.get("live_qty", 0.0)
                if live_qty > 0:
                    self._execute_binance_close(pos["coin"], pos["direction"], live_qty)
            except Exception as e:
                logger.error(f"Failed to close live order on Binance for {sig_key}: {e}")

        if is_live:
            self.sync_binance_balance()
        else:
            fee_rate = pos.get("fee_rate", self.OKX_FUTURES_TAKER_FEE if leverage > 1 else self.OKX_SPOT_TAKER_FEE)
            close_fee = rem_size * fee_rate
            self.balance += (rem_margin + pnl - close_fee)
            pos["fees_paid"] = round(pos.get("fees_paid", 0.0) + close_fee, 4)

        pos["status"] = "CLOSED"
        pos["close_time"] = datetime.now(VN_TZ).isoformat()
        pos["close_price"] = close_price
        pos["close_reason"] = reason
        pos["pnl"] += pnl
        pos["_closed_at"] = datetime.now(VN_TZ).isoformat()

        logger.info(f"TRADE DONG LENH: {sig_key} | Ly do: {reason} | PnL phan cuoi: ${pnl:.2f} | Fees phan cuoi: ${close_fee if not is_live else 0:.4f} | Tong PnL: ${pos['pnl']:.2f} | Live: {is_live}")

        # === AI Intelligence: Post-trade Analysis & ML Training ===
        # H3 fix: chay trong background task de khong block event loop
        def _ai_post_trade(pos_copy, sig_key):
            """Sync function chay trong thread rieng."""
            try:
                from analytics.trade_analyzer import TradeAnalyzer
                analyzer = TradeAnalyzer()
                analysis = analyzer.analyze_trade(pos_copy)
                if analysis:
                    logger.info(
                        f"🧠 [TradeAnalyzer] {pos_copy.get('coin')} {pos_copy.get('direction')}: "
                        f"{analysis['outcome']} | Pattern: {analysis['pattern']} | "
                        f"Efficiency: {analysis.get('sl_tp_analysis', {}).get('efficiency', 0):.0f}%"
                    )
            except Exception as e:
                logger.debug(f"[AI] TradeAnalyzer error (non-fatal): {e}")

            try:
                from analytics.ml_signal_booster import get_booster
                import numpy as np
                booster = get_booster()
                ai_details = pos_copy.get("ai_details", {})
                if ai_details and ai_details.get("ml", {}).get("_features") is not None:
                    features = np.array(ai_details["ml"]["_features"])
                    label = 1 if pos_copy.get("pnl", 0) > 0 else 0
                    # add_training_sample() tu dong retrain khi du nguong.
                    # Doan nay chay trong worker thread (run_in_executor) nen train()
                    # khong block event loop.
                    booster.add_training_sample(features, label, pos_copy.get("pnl", 0), sig_key)
                    logger.info(f"🧠 [MLBooster] Training sample added: {'WIN' if label else 'LOSS'} (total: {len(booster.training_data)})")
            except Exception as e:
                logger.debug(f"[AI] MLBooster training error (non-fatal): {e}")

        try:
            import asyncio
            pos_copy = dict(pos)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None  # Dang o thread ngoai event loop (vd FastAPI threadpool / script sync)
            if loop is not None:
                loop.run_in_executor(None, _ai_post_trade, pos_copy, sig_key)
            else:
                _ai_post_trade(pos_copy, sig_key)
        except Exception as e:
            logger.debug(f"[AI] Post-trade scheduling error: {e}")

        # Dua vao history
        self.history.append(dict(pos))
        self._save_data()
        return pos

    def _cleanup_closed(self):
        """Xoa cac position da dong qua 30 giay khoi dict positions."""
        now = datetime.now()
        keys_to_remove = []
        for k, p in self.positions.items():
            if p.get("status") == "CLOSED" and p.get("_closed_at"):
                try:
                    closed_at = datetime.fromisoformat(p["_closed_at"])
                    if (now - closed_at).total_seconds() > 30:
                        keys_to_remove.append(k)
                except:
                    keys_to_remove.append(k)
        for k in keys_to_remove:
            del self.positions[k]
        if keys_to_remove:
            self._save_data()
        
    def set_trailing_sl(self, sig_key: str, enable: bool) -> bool:
        """Bat/tat Trailing Stop Loss cho 1 position."""
        if sig_key not in self.positions:
            return False
        self.positions[sig_key]["trailing_sl"] = enable
        self._save_data()
        logger.info(f"Trailing SL [{sig_key}]: {'ON' if enable else 'OFF'}")
        return True

    def sync_binance_balance(self) -> float:
        """Đồng bộ số dư thực tế từ Binance Futures về hệ thống."""
        import ccxt
        from core.config import Config
        if not Config.BINANCE_API_KEY or not Config.BINANCE_API_SECRET:
            return self.balance
            
        try:
            exchange = ccxt.binance({
                "apiKey": Config.BINANCE_API_KEY,
                "secret": Config.BINANCE_API_SECRET,
                "enableRateLimit": True,
                "options": {"defaultType": "future"}
            })
            balance_data = exchange.fetch_balance()
            real_balance = float(balance_data.get("total", {}).get("USDT", self.balance))
            self.balance = real_balance
            if sqlite_db:
                sqlite_db.update_balance(self.balance)
            return real_balance
        except Exception as e:
            logger.error(f"Error syncing Binance balance: {e}")
            return self.balance

    def _execute_binance_trade(self, symbol: str, direction: str, size_usdt: float, leverage: int) -> dict:
        """Thực hiện đặt lệnh thực tế trên Binance Futures."""
        import ccxt
        from core.config import Config
        
        if not Config.BINANCE_API_KEY or not Config.BINANCE_API_SECRET:
            logger.error("Binance API keys not configured in .env!")
            raise Exception("Binance API keys not configured")
            
        try:
            exchange = ccxt.binance({
                "apiKey": Config.BINANCE_API_KEY,
                "secret": Config.BINANCE_API_SECRET,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future"
                }
            })
            
            ccxt_symbol = f"{symbol.upper()}/USDT"
            
            try:
                exchange.set_leverage(leverage, ccxt_symbol)
            except Exception as le:
                logger.warning(f"Failed to set leverage: {le}")
                
            exchange.load_markets()
            ticker = exchange.fetch_ticker(ccxt_symbol)
            price = ticker["last"]
            
            raw_qty = size_usdt / price
            qty = exchange.amount_to_precision(ccxt_symbol, raw_qty)
            
            side = "buy" if direction.upper() == "LONG" else "sell"
            logger.info(f"[Live Trading] Placing order: {side.upper()} {qty} {ccxt_symbol}")
            
            order = exchange.create_market_order(
                symbol=ccxt_symbol,
                side=side,
                amount=float(qty)
            )
            
            logger.success(f"[Live Trading] Order placed successfully! ID: {order['id']}")
            return {
                "success": True,
                "order_id": order["id"],
                "price": order.get("price") or price,
                "amount": order.get("amount") or float(qty),
                "timestamp": order.get("timestamp")
            }
        except Exception as e:
            logger.error(f"[Live Trading] Error placing Binance order: {e}")
            raise e

    def _execute_binance_close(self, symbol: str, direction: str, qty: float) -> dict:
        """Thực hiện đóng vị thế thực tế trên Binance Futures."""
        import ccxt
        from core.config import Config
        
        if not Config.BINANCE_API_KEY or not Config.BINANCE_API_SECRET:
            logger.error("Binance API keys not configured in .env!")
            raise Exception("Binance API keys not configured")
            
        try:
            exchange = ccxt.binance({
                "apiKey": Config.BINANCE_API_KEY,
                "secret": Config.BINANCE_API_SECRET,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future"
                }
            })
            
            ccxt_symbol = f"{symbol.upper()}/USDT"
            side = "sell" if direction.upper() == "LONG" else "buy"
            logger.info(f"[Live Trading] Closing order: {side.upper()} {qty} {ccxt_symbol}")
            
            order = exchange.create_market_order(
                symbol=ccxt_symbol,
                side=side,
                amount=qty,
                params={"reduceOnly": True}
            )
            logger.success(f"[Live Trading] Close order placed successfully! ID: {order['id']}")
            return {"success": True, "order_id": order["id"]}
        except Exception as e:
            logger.error(f"[Live Trading] Error closing Binance position: {e}")
            raise e

    def get_portfolio_status(self) -> dict:
        """Tra lai trang thai tai khoan de lam bao cao."""
        if sqlite_db and sqlite_db.get_live_mode():
            self.sync_binance_balance()
            
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

    def reset_portfolio(self, initial_balance: float = None):
        """Xóa sạch lịch sử giao dịch và số dư để bắt đầu một chu kỳ test mới."""
        if initial_balance is None:
            initial_balance = self.INITIAL_BALANCE
            
        self.balance = initial_balance
        self.positions = {}
        self.history = []
        self.balance_history = []
        self.daily_realized_pnl = 0.0
        self.daily_start_balance = initial_balance
        self.test_start_time = datetime.now().isoformat()
        self.test_start_balance = initial_balance
        
        # Lưu dữ liệu local
        self._save_data()
        
        # Xóa trong SQLite
        if sqlite_db:
            try:
                conn = sqlite_db._get_conn()
                with conn:
                    conn.execute("DELETE FROM positions")
                    conn.execute("DELETE FROM balance_history")
                sqlite_db.update_balance(self.balance, self.auto_trade_enabled)
                sqlite_db.add_balance_record("DEP", self.balance, self.balance, f"Khởi tạo chu kỳ test mới với số vốn ${self.balance:,.2f}")
                logger.info("Database reset successfully for paper trading.")
            except Exception as e:
                logger.error(f"Error resetting database: {e}")

    def generate_profit_report(self) -> dict:
        """Tạo báo cáo lợi nhuận chi tiết cho chu kỳ test."""
        # Đọc lịch sử giao dịch từ SQLite hoặc local history
        if sqlite_db:
            try:
                closed_trades = sqlite_db.get_closed_positions(limit=1000)
            except Exception as e:
                logger.error(f"Error fetching closed trades: {e}")
                closed_trades = self.history
        else:
            closed_trades = self.history
            
        total_trades = len(closed_trades)
        
        # Phân tích theo đồng coin (BTC, ETH, SOL)
        coin_stats = {}
        wins = 0
        total_pnl = 0.0
        largest_win = 0.0
        largest_loss = 0.0
        
        long_wins = 0
        long_count = 0
        short_wins = 0
        short_count = 0
        
        for t in closed_trades:
            # t có thể là dict hoặc Row
            t_dict = dict(t) if not isinstance(t, dict) else t
            coin = t_dict.get("coin", "UNKNOWN").upper()
            pnl = t_dict.get("pnl", 0.0)
            direction = t_dict.get("direction", "LONG")
            
            total_pnl += pnl
            if pnl > 0:
                wins += 1
                if pnl > largest_win:
                    largest_win = pnl
            else:
                if pnl < largest_loss:
                    largest_loss = pnl
                    
            if direction == "LONG":
                long_count += 1
                if pnl > 0:
                    long_wins += 1
            elif direction == "SHORT":
                short_count += 1
                if pnl > 0:
                    short_wins += 1
                    
            if coin not in coin_stats:
                coin_stats[coin] = {"count": 0, "wins": 0, "pnl": 0.0}
            coin_stats[coin]["count"] += 1
            coin_stats[coin]["pnl"] += pnl
            if pnl > 0:
                coin_stats[coin]["wins"] += 1
                 
        # Định dạng kết quả thống kê từng coin
        coin_report = []
        for coin, stat in coin_stats.items():
            coin_report.append({
                "coin": coin,
                "total_trades": stat["count"],
                "pnl": round(stat["pnl"], 2),
                "win_rate": round(stat["wins"] / stat["count"] * 100, 1) if stat["count"] > 0 else 0.0
            })
             
        # Thời gian chạy thử nghiệm
        start_time_str = getattr(self, "test_start_time", "")
        if start_time_str:
            try:
                start_dt = datetime.fromisoformat(start_time_str)
                elapsed = datetime.now() - start_dt
                days_elapsed = elapsed.days + (elapsed.seconds / 86400.0)
            except:
                days_elapsed = 0.0
        else:
            days_elapsed = 0.0
            start_time_str = datetime.now().isoformat()
             
        initial_bal = getattr(self, "test_start_balance", self.balance)
        if initial_bal <= 0:
            initial_bal = self.INITIAL_BALANCE
        current_bal = self.balance
        roi = (current_bal - initial_bal) / initial_bal * 100 if initial_bal > 0 else 0.0
         
        return {
            "test_start_time": start_time_str,
            "days_elapsed": round(days_elapsed, 2),
            "initial_balance": round(initial_bal, 2),
            "current_balance": round(current_bal, 2),
            "net_pnl": round(total_pnl, 2),
            "roi_pct": round(roi, 2),
            "total_trades": total_trades,
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0.0,
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "long_stats": {
                "count": long_count,
                "win_rate": round(long_wins / long_count * 100, 1) if long_count > 0 else 0.0
            },
            "short_stats": {
                "count": short_count,
                "win_rate": round(short_wins / short_count * 100, 1) if short_count > 0 else 0.0
            },
            "coin_breakdown": coin_report
        }
