"""
Backtesting Engine - Test chien luoc TA tren du lieu lich su.
Cho phep chay thu chien luoc tren du lieu nen qua khu,
do luong hieu suat (Win Rate, Sharpe Ratio, Max Drawdown, Profit Factor).
"""
import math
from datetime import datetime
from typing import Optional
from loguru import logger

import pandas as pd
import numpy as np


class BacktestEngine:
    """
    Chay backtest chien luoc TA tren du lieu lich su.
    Su dung TechnicalAnalyzer de tinh chi bao va sinh tin hieu,
    sau do gia lap giao dich voi SL/TP.
    """

    # Preset strategies
    PRESETS = {
        "conservative": {
            "label": "An Toan",
            "description": "SL chat, TP xa. Phu hop thi truong sideway.",
            "risk_per_trade": 0.01,
            "sl_pct": 0.015,
            "tp1_pct": 0.02,
            "tp2_pct": 0.04,
            "tp3_pct": 0.07,
            "min_score": 4,
            "leverage": 1,
        },
        "balanced": {
            "label": "Can Bang",
            "description": "SL/TP vua phai. Phu hop da so thi truong.",
            "risk_per_trade": 0.02,
            "sl_pct": 0.02,
            "tp1_pct": 0.03,
            "tp2_pct": 0.06,
            "tp3_pct": 0.10,
            "min_score": 3,
            "leverage": 1,
        },
        "aggressive": {
            "label": "Manh Tay",
            "description": "Leverage cao, SL rong. Chi dung khi trending.",
            "risk_per_trade": 0.03,
            "sl_pct": 0.03,
            "tp1_pct": 0.05,
            "tp2_pct": 0.10,
            "tp3_pct": 0.20,
            "min_score": 3,
            "leverage": 5,
        },
        "scalping": {
            "label": "Scalping",
            "description": "Leverage cuc cao, SL/TP cuc chat. Timeframe ngan.",
            "risk_per_trade": 0.01,
            "sl_pct": 0.005,
            "tp1_pct": 0.01,
            "tp2_pct": 0.02,
            "tp3_pct": 0.04,
            "min_score": 2,
            "leverage": 25,
        },
    }

    def __init__(self):
        self.initial_balance = 10000.0

    async def run(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        days: int = 30,
        leverage: int = 1,
        risk_per_trade: float = 0.02,
        sl_pct: float = 0.02,
        tp1_pct: float = 0.03,
        tp2_pct: float = 0.06,
        tp3_pct: float = 0.10,
        min_score: int = 3,
    ) -> dict:
        """
        Chay backtest day du.
        1. Lay OHLCV lich su
        2. Tinh chi bao ky thuat
        3. Gia lap giao dich
        4. Tinh metrics
        """
        from analytics.technical import TechnicalAnalyzer

        ta_engine = TechnicalAnalyzer()

        try:
            # Tinh so nen can lay dua tren timeframe va so ngay
            limit = self._calc_candle_count(timeframe, days)
            limit = min(limit, 1000)  # Binance max 1000

            logger.info(
                f"[Backtest] {symbol} | TF: {timeframe} | "
                f"Days: {days} | Candles: {limit} | Lev: x{leverage}"
            )

            # 1. Lay du lieu
            df = await ta_engine.get_ohlcv(symbol, timeframe, limit=limit)
            if df.empty or len(df) < 50:
                return {"error": f"Khong du du lieu ({len(df)} candles). Can it nhat 50."}

            # 2. Tinh chi bao
            df = ta_engine.calculate_indicators(df)

            # 3. Gia lap giao dich
            result = self._simulate_trades(
                df=df,
                symbol=symbol,
                leverage=leverage,
                risk_per_trade=risk_per_trade,
                sl_pct=sl_pct,
                tp1_pct=tp1_pct,
                tp2_pct=tp2_pct,
                tp3_pct=tp3_pct,
                min_score=min_score,
            )

            result["symbol"] = symbol
            result["timeframe"] = timeframe
            result["days"] = days
            result["leverage"] = leverage
            result["candles"] = len(df)
            result["period"] = {
                "start": df.index[0].isoformat() if hasattr(df.index[0], 'isoformat') else str(df.index[0]),
                "end": df.index[-1].isoformat() if hasattr(df.index[-1], 'isoformat') else str(df.index[-1]),
            }

            return result

        except Exception as e:
            logger.error(f"[Backtest] Error: {e}")
            return {"error": str(e)}
        finally:
            await ta_engine.close()

    def _calc_candle_count(self, timeframe: str, days: int) -> int:
        """Tinh so nen can thiet tu timeframe va so ngay."""
        tf_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "6h": 360,
            "8h": 480, "12h": 720, "1d": 1440, "1w": 10080,
        }
        minutes_per_candle = tf_minutes.get(timeframe, 60)
        total_minutes = days * 24 * 60
        return total_minutes // minutes_per_candle

    def _simulate_trades(
        self,
        df: pd.DataFrame,
        symbol: str,
        leverage: int,
        risk_per_trade: float,
        sl_pct: float,
        tp1_pct: float,
        tp2_pct: float,
        tp3_pct: float,
        min_score: int,
    ) -> dict:
        """
        Duyet qua tung nen, sinh signal va gia lap giao dich.
        Logic tuong tu TradeEngine nhung offline.
        """
        balance = self.initial_balance
        trades = []          # Completed trades
        signals_list = []    # All signals generated
        equity_curve = []    # Balance over time
        open_position = None # Current open position (1 at a time)

        # Duyet tu nen 50 tro di (can du du lieu cho indicators)
        for i in range(50, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            price = row["close"]
            timestamp = df.index[i]
            ts_str = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)

            # === KIEM TRA POSITION DANG MO ===
            if open_position is not None:
                entry = open_position["entry_price"]
                direction = open_position["direction"]
                pos_sl = open_position["sl"]
                pos_tp1 = open_position["tp1"]
                pos_tp2 = open_position["tp2"]
                pos_tp3 = open_position["tp3"]
                closed_pct = open_position.get("closed_pct", 0)
                usdt_size = open_position["usdt_size"]

                # Kiem tra Liquidation
                if leverage > 1 and entry > 0:
                    if direction == "LONG":
                        liq = entry * (1 - 1 / leverage)
                        if row["low"] <= liq:
                            pnl = -usdt_size * (1 - closed_pct)
                            balance += pnl
                            open_position["close_price"] = liq
                            open_position["pnl"] = open_position.get("pnl", 0) + pnl
                            open_position["close_reason"] = "LIQUIDATED"
                            open_position["close_time"] = ts_str
                            trades.append(open_position)
                            open_position = None
                            equity_curve.append({"time": ts_str, "balance": round(balance, 2)})
                            continue
                    else:
                        liq = entry * (1 + 1 / leverage)
                        if row["high"] >= liq:
                            pnl = -usdt_size * (1 - closed_pct)
                            balance += pnl
                            open_position["close_price"] = liq
                            open_position["pnl"] = open_position.get("pnl", 0) + pnl
                            open_position["close_reason"] = "LIQUIDATED"
                            open_position["close_time"] = ts_str
                            trades.append(open_position)
                            open_position = None
                            equity_curve.append({"time": ts_str, "balance": round(balance, 2)})
                            continue

                # Kiem tra SL (dung high/low cua nen)
                if direction == "LONG" and row["low"] <= pos_sl:
                    rem_pct = 1.0 - closed_pct
                    rem_size = usdt_size * rem_pct
                    pnl_pct = (pos_sl - entry) / entry
                    pnl = rem_size * pnl_pct * leverage
                    balance += rem_size + pnl
                    open_position["close_price"] = pos_sl
                    open_position["pnl"] = open_position.get("pnl", 0) + pnl
                    open_position["close_reason"] = "SL_HIT"
                    open_position["close_time"] = ts_str
                    trades.append(open_position)
                    open_position = None
                    equity_curve.append({"time": ts_str, "balance": round(balance, 2)})
                    continue
                elif direction == "SHORT" and row["high"] >= pos_sl:
                    rem_pct = 1.0 - closed_pct
                    rem_size = usdt_size * rem_pct
                    pnl_pct = (entry - pos_sl) / entry
                    pnl = rem_size * pnl_pct * leverage
                    balance += rem_size + pnl
                    open_position["close_price"] = pos_sl
                    open_position["pnl"] = open_position.get("pnl", 0) + pnl
                    open_position["close_reason"] = "SL_HIT"
                    open_position["close_time"] = ts_str
                    trades.append(open_position)
                    open_position = None
                    equity_curve.append({"time": ts_str, "balance": round(balance, 2)})
                    continue

                # Kiem tra TP3 (dong het)
                if direction == "LONG" and row["high"] >= pos_tp3:
                    rem_pct = 1.0 - closed_pct
                    rem_size = usdt_size * rem_pct
                    pnl_pct = (pos_tp3 - entry) / entry
                    pnl = rem_size * pnl_pct * leverage
                    balance += rem_size + pnl
                    open_position["close_price"] = pos_tp3
                    open_position["pnl"] = open_position.get("pnl", 0) + pnl
                    open_position["close_reason"] = "TP3_HIT"
                    open_position["close_time"] = ts_str
                    trades.append(open_position)
                    open_position = None
                    equity_curve.append({"time": ts_str, "balance": round(balance, 2)})
                    continue
                elif direction == "SHORT" and row["low"] <= pos_tp3:
                    rem_pct = 1.0 - closed_pct
                    rem_size = usdt_size * rem_pct
                    pnl_pct = (entry - pos_tp3) / entry
                    pnl = rem_size * pnl_pct * leverage
                    balance += rem_size + pnl
                    open_position["close_price"] = pos_tp3
                    open_position["pnl"] = open_position.get("pnl", 0) + pnl
                    open_position["close_reason"] = "TP3_HIT"
                    open_position["close_time"] = ts_str
                    trades.append(open_position)
                    open_position = None
                    equity_curve.append({"time": ts_str, "balance": round(balance, 2)})
                    continue

                # Kiem tra TP2 (chot 30%)
                if closed_pct < 0.6:
                    hit_tp2 = (direction == "LONG" and row["high"] >= pos_tp2) or \
                              (direction == "SHORT" and row["low"] <= pos_tp2)
                    if hit_tp2:
                        pct_close = 0.3
                        close_size = usdt_size * pct_close
                        if direction == "LONG":
                            pnl_pct = (pos_tp2 - entry) / entry
                        else:
                            pnl_pct = (entry - pos_tp2) / entry
                        pnl = close_size * pnl_pct * leverage
                        balance += close_size + pnl
                        open_position["closed_pct"] = closed_pct + pct_close
                        open_position["pnl"] = open_position.get("pnl", 0) + pnl

                # Kiem tra TP1 (chot 30%)
                if open_position and open_position.get("closed_pct", 0) < 0.3:
                    hit_tp1 = (direction == "LONG" and row["high"] >= pos_tp1) or \
                              (direction == "SHORT" and row["low"] <= pos_tp1)
                    if hit_tp1:
                        pct_close = 0.3
                        close_size = usdt_size * pct_close
                        if direction == "LONG":
                            pnl_pct = (pos_tp1 - entry) / entry
                        else:
                            pnl_pct = (entry - pos_tp1) / entry
                        pnl = close_size * pnl_pct * leverage
                        balance += close_size + pnl
                        open_position["closed_pct"] = open_position.get("closed_pct", 0) + pct_close
                        open_position["pnl"] = open_position.get("pnl", 0) + pnl

            # === SINH SIGNAL MOI (chi khi khong co position mo) ===
            if open_position is None and balance > 50:
                signal = self._generate_signal_at(df, i, min_score)

                if signal and signal["direction"] in ("LONG", "SHORT"):
                    signals_list.append({
                        "time": ts_str,
                        "price": price,
                        "direction": signal["direction"],
                        "score": signal.get("score", 0),
                        "reasons": signal.get("reasons", []),
                    })

                    direction = signal["direction"]

                    # Tinh SL/TP
                    if direction == "LONG":
                        sl = price * (1 - sl_pct)
                        tp1 = price * (1 + tp1_pct)
                        tp2 = price * (1 + tp2_pct)
                        tp3 = price * (1 + tp3_pct)
                    else:
                        sl = price * (1 + sl_pct)
                        tp1 = price * (1 - tp1_pct)
                        tp2 = price * (1 - tp2_pct)
                        tp3 = price * (1 - tp3_pct)

                    # Tinh position size (risk-based)
                    risk_amount = balance * risk_per_trade
                    if sl_pct > 0:
                        pos_size = risk_amount / sl_pct
                    else:
                        pos_size = risk_amount
                    pos_size = min(pos_size, balance * 0.2)  # Max 20% balance

                    if pos_size >= 10:  # Min $10
                        margin = pos_size / leverage
                        if margin <= balance:
                            balance -= margin

                            open_position = {
                                "coin": symbol.replace("/USDT", "").replace("USDT", ""),
                                "direction": direction,
                                "entry_price": price,
                                "sl": round(sl, 6),
                                "tp1": round(tp1, 6),
                                "tp2": round(tp2, 6),
                                "tp3": round(tp3, 6),
                                "usdt_size": round(pos_size, 2),
                                "margin": round(margin, 2),
                                "leverage": leverage,
                                "open_time": ts_str,
                                "pnl": 0.0,
                                "closed_pct": 0.0,
                                "score": signal.get("score", 0),
                            }

            # Ghi equity curve moi 10 nen
            if i % 10 == 0 or i == len(df) - 1:
                # Tinh unrealized PnL
                unrealized = 0
                if open_position:
                    entry = open_position["entry_price"]
                    size = open_position["usdt_size"]
                    rem = 1.0 - open_position.get("closed_pct", 0)
                    if open_position["direction"] == "LONG":
                        unrealized = ((price - entry) / entry) * size * rem * leverage
                    else:
                        unrealized = ((entry - price) / entry) * size * rem * leverage

                equity_curve.append({
                    "time": ts_str,
                    "balance": round(balance + unrealized, 2),
                })

        # Force-close open position tai gia cuoi cung
        if open_position is not None:
            last_price = df.iloc[-1]["close"]
            last_ts = df.index[-1]
            ts_str = last_ts.isoformat() if hasattr(last_ts, 'isoformat') else str(last_ts)
            entry = open_position["entry_price"]
            direction = open_position["direction"]
            rem_pct = 1.0 - open_position.get("closed_pct", 0)
            rem_size = open_position["usdt_size"] * rem_pct

            if direction == "LONG":
                pnl_pct = (last_price - entry) / entry
            else:
                pnl_pct = (entry - last_price) / entry

            pnl = rem_size * pnl_pct * leverage
            balance += rem_size + pnl
            open_position["close_price"] = last_price
            open_position["pnl"] = open_position.get("pnl", 0) + pnl
            open_position["close_reason"] = "END_OF_DATA"
            open_position["close_time"] = ts_str
            trades.append(open_position)

        # === TINH METRICS ===
        metrics = self._calc_metrics(trades, balance)

        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": trades[-100:],  # Max 100 trades cho FE
            "signals": signals_list[-200:],  # Max 200 signals
            "total_signals": len(signals_list),
        }

    def _generate_signal_at(self, df: pd.DataFrame, idx: int, min_score: int) -> Optional[dict]:
        """
        Sinh signal tai vi tri idx trong DataFrame.
        Tuong tu TechnicalAnalyzer.generate_signal() nhung cho phep tuy chinh min_score.
        """
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        price = row["close"]

        bull = 0
        bear = 0
        reasons = []

        # 1. RSI
        rsi = row.get("rsi")
        if rsi is not None and not (isinstance(rsi, float) and math.isnan(rsi)):
            if rsi < 30:
                bull += 2; reasons.append(f"RSI qua ban ({rsi:.0f})")
            elif rsi < 40:
                bull += 1; reasons.append(f"RSI thap ({rsi:.0f})")
            elif rsi > 70:
                bear += 2; reasons.append(f"RSI qua mua ({rsi:.0f})")
            elif rsi > 60:
                bear += 1; reasons.append(f"RSI cao ({rsi:.0f})")

        # 2. MACD crossover
        macd = row.get("macd")
        macd_sig = row.get("macd_signal")
        prev_macd = prev.get("macd")
        prev_sig = prev.get("macd_signal")
        if all(v is not None and not (isinstance(v, float) and math.isnan(v))
               for v in [macd, macd_sig, prev_macd, prev_sig]):
            if prev_macd < prev_sig and macd > macd_sig:
                bull += 2; reasons.append("MACD Golden Cross")
            elif prev_macd > prev_sig and macd < macd_sig:
                bear += 2; reasons.append("MACD Death Cross")

        # 3. EMA trend
        ema20 = row.get("ema20")
        ema50 = row.get("ema50")
        if ema20 is not None and ema50 is not None:
            if not (math.isnan(ema20) or math.isnan(ema50)):
                if price > ema20 > ema50:
                    bull += 1; reasons.append("Uptrend (EMA)")
                elif price < ema20 < ema50:
                    bear += 1; reasons.append("Downtrend (EMA)")

        # 4. Bollinger Bands
        bb_lower = row.get("bb_lower")
        bb_upper = row.get("bb_upper")
        if bb_lower is not None and not math.isnan(bb_lower) and price <= bb_lower:
            bull += 1; reasons.append("Cham BB duoi")
        if bb_upper is not None and not math.isnan(bb_upper) and price >= bb_upper:
            bear += 1; reasons.append("Cham BB tren")

        # 5. ADX
        adx = row.get("adx")
        di_p = row.get("di_plus")
        di_m = row.get("di_minus")
        if adx is not None and not math.isnan(adx) and adx > 25:
            if di_p is not None and di_m is not None:
                if not (math.isnan(di_p) or math.isnan(di_m)):
                    if di_p > di_m:
                        bull += 1; reasons.append(f"ADX manh +DI ({adx:.0f})")
                    else:
                        bear += 1; reasons.append(f"ADX manh -DI ({adx:.0f})")

        # 6. VWAP
        vwap = row.get("vwap")
        if vwap is not None and not math.isnan(vwap):
            if price > vwap * 1.01:
                bull += 1; reasons.append("Tren VWAP")
            elif price < vwap * 0.99:
                bear += 1; reasons.append("Duoi VWAP")

        # 7. Support / Resistance
        s1 = row.get("support1")
        r1 = row.get("resistance1")
        if s1 is not None and not math.isnan(s1):
            if abs(price - s1) / price < 0.005:
                bull += 1; reasons.append("Tai Support S1")
        if r1 is not None and not math.isnan(r1):
            if abs(price - r1) / price < 0.005:
                bear += 1; reasons.append("Tai Resistance R1")

        # Decision
        score = max(bull, bear)
        if score < min_score:
            return None

        direction = "LONG" if bull > bear else "SHORT" if bear > bull else None
        if direction is None:
            return None

        return {
            "direction": direction,
            "score": score,
            "bull": bull,
            "bear": bear,
            "reasons": reasons,
        }

    def _calc_metrics(self, trades: list, final_balance: float) -> dict:
        """Tinh cac chi so hieu suat tu danh sach trades."""
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "max_drawdown": 0,
                "sharpe_ratio": 0,
                "profit_factor": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "largest_win": 0,
                "largest_loss": 0,
                "initial_balance": self.initial_balance,
                "final_balance": round(final_balance, 2),
                "return_pct": 0,
                "sl_count": 0,
                "tp1_count": 0,
                "tp2_count": 0,
                "tp3_count": 0,
                "liq_count": 0,
            }

        pnls = [t.get("pnl", 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = (len(wins) / len(trades) * 100) if trades else 0

        # Profit Factor = tong lai / tong lo
        total_win = sum(wins) if wins else 0
        total_loss = abs(sum(losses)) if losses else 0
        profit_factor = (total_win / total_loss) if total_loss > 0 else float("inf") if total_win > 0 else 0

        # Sharpe Ratio (annualized, giu don gian)
        if len(pnls) > 1:
            pnl_arr = np.array(pnls)
            avg_return = np.mean(pnl_arr)
            std_return = np.std(pnl_arr)
            sharpe = (avg_return / std_return) * math.sqrt(len(pnls)) if std_return > 0 else 0
        else:
            sharpe = 0

        # Max Drawdown
        running_balance = self.initial_balance
        peak = running_balance
        max_dd = 0
        for t in trades:
            running_balance += t.get("pnl", 0)
            if running_balance > peak:
                peak = running_balance
            dd = (peak - running_balance) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Close reason counts
        sl_count = sum(1 for t in trades if t.get("close_reason") == "SL_HIT")
        tp1_count = sum(1 for t in trades if t.get("close_reason") == "TP1_HIT")
        tp2_count = sum(1 for t in trades if t.get("close_reason") == "TP2_HIT")
        tp3_count = sum(1 for t in trades if t.get("close_reason") == "TP3_HIT")
        liq_count = sum(1 for t in trades if t.get("close_reason") == "LIQUIDATED")

        return {
            "total_trades": len(trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(np.mean(wins), 2) if wins else 0,
            "avg_loss": round(np.mean(losses), 2) if losses else 0,
            "largest_win": round(max(pnls), 2) if pnls else 0,
            "largest_loss": round(min(pnls), 2) if pnls else 0,
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999,
            "initial_balance": self.initial_balance,
            "final_balance": round(final_balance, 2),
            "return_pct": round((final_balance - self.initial_balance) / self.initial_balance * 100, 2),
            "sl_count": sl_count,
            "tp1_count": tp1_count,
            "tp2_count": tp2_count,
            "tp3_count": tp3_count,
            "liq_count": liq_count,
        }
