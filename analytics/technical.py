"""
Technical Analysis Engine - Tinh toan chi bao ky thuat.
Su dung pandas_ta de tinh RSI, MACD, EMA, Bollinger Bands.
Ket hop nhieu chi bao de sinh tin hieu Long/Short.
"""
import asyncio
from typing import Optional
from datetime import datetime

import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from loguru import logger
import aiohttp
from aiohttp.resolver import ThreadedResolver


class TechnicalAnalyzer:
    """
    Engine phan tich ky thuat:
    - Lay du lieu nen (OHLCV) tu Binance qua ccxt
    - Tinh RSI, MACD, EMA, Bollinger Bands
    - Sinh tin hieu Long/Short dua tren da chi bao
    """

    def __init__(self):
        self.exchange = self._create_exchange()

    def _create_exchange(self, endpoint: str = "api.binance.com"):
        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        session = aiohttp.ClientSession(connector=connector)
        exchange = ccxt.binance({
            "enableRateLimit": True,
            "session": session
        })
        if endpoint != "api.binance.com":
            for key, val in list(exchange.urls["api"].items()):
                if isinstance(val, str) and "api.binance.com" in val:
                    exchange.urls["api"][key] = val.replace("api.binance.com", endpoint)
        return exchange

    async def _close_exchange_instance(self, exchange):
        if exchange:
            session = getattr(exchange, "session", None)
            try:
                await exchange.close()
            except:
                pass
            if session and not session.closed:
                try:
                    await session.close()
                except:
                    pass

    async def close(self):
        await self._close_exchange_instance(self.exchange)

    async def get_ohlcv(self, symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 100) -> pd.DataFrame:
        """Lay du lieu nen (Open, High, Low, Close, Volume) tu Binance."""
        endpoints = [
            "api.binance.com",
            "api-gcp.binance.com",
            "api1.binance.com",
            "api2.binance.com",
            "api3.binance.com",
        ]
        # Dong exchange hien tai de khoi tao lai
        await self._close_exchange_instance(self.exchange)
            
        for endpoint in endpoints:
            try:
                self.exchange = self._create_exchange(endpoint)
                ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                logger.info(f"Lay {len(df)} nen {symbol} {timeframe} tu endpoint {endpoint}")
                return df
            except Exception as e:
                logger.warning(f"Loi lay OHLCV {symbol} tu endpoint {endpoint}: {e}")
                await self._close_exchange_instance(self.exchange)
        
        # Khoi tao lai exchange mac dinh truoc khi ket thuc
        self.exchange = self._create_exchange()
        return pd.DataFrame()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Tinh tat ca chi bao ky thuat tren DataFrame."""
        if df.empty:
            return df

        # RSI (14 ky) - Vung qua ban < 30, qua mua > 70
        df["rsi"] = ta.rsi(df["close"], length=14)

        # MACD (12, 26, 9)
        macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd is not None:
            df["macd"] = macd.iloc[:, 0]        # MACD line
            df["macd_signal"] = macd.iloc[:, 1]  # Signal line
            df["macd_hist"] = macd.iloc[:, 2]    # Histogram

        # EMA 20 va EMA 50
        df["ema20"] = ta.ema(df["close"], length=20)
        df["ema50"] = ta.ema(df["close"], length=50)

        # Bollinger Bands (20, 2)
        bb = ta.bbands(df["close"], length=20, std=2)
        if bb is not None:
            df["bb_upper"] = bb.iloc[:, 0]
            df["bb_mid"] = bb.iloc[:, 1]
            df["bb_lower"] = bb.iloc[:, 2]

        # Volume trung binh 20 ky
        df["vol_avg20"] = df["volume"].rolling(window=20).mean()
        df["vol_spike"] = df["volume"] > (df["vol_avg20"] * 1.5)

        # === CHI BAO MOI ===

        # VWAP (Volume Weighted Average Price)
        df["vwap"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum() / df["volume"].cumsum()

        # ADX (Average Directional Index) - Do manh xu huong
        adx_result = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx_result is not None:
            df["adx"] = adx_result.iloc[:, 0]        # ADX
            df["di_plus"] = adx_result.iloc[:, 1]     # +DI
            df["di_minus"] = adx_result.iloc[:, 2]    # -DI

        # Support / Resistance (Pivot Points)
        df["pivot"] = (df["high"] + df["low"] + df["close"]) / 3
        df["support1"] = 2 * df["pivot"] - df["high"]
        df["resistance1"] = 2 * df["pivot"] - df["low"]
        df["support2"] = df["pivot"] - (df["high"] - df["low"])
        df["resistance2"] = df["pivot"] + (df["high"] - df["low"])

        # Fibonacci Retracement (tinh tu high/low 50 nen gan nhat)
        recent = df.tail(50)
        swing_high = recent["high"].max()
        swing_low = recent["low"].min()
        diff = swing_high - swing_low
        df["fib_236"] = swing_high - diff * 0.236
        df["fib_382"] = swing_high - diff * 0.382
        df["fib_500"] = swing_high - diff * 0.500
        df["fib_618"] = swing_high - diff * 0.618

        # EMA 200 (xu huong lon)
        if len(df) >= 200:
            df["ema200"] = ta.ema(df["close"], length=200)
        else:
            df["ema200"] = float("nan")

        # ATR (Average True Range) - Do bien dong thuc te
        atr_result = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr_result is not None:
            df["atr"] = atr_result
        else:
            df["atr"] = float("nan")

        return df

    def compute_smart_levels(
        self,
        df: pd.DataFrame,
        direction: str = "LONG",
        leverage: int = 1,
        macro_risk: str = "NORMAL",  # NORMAL / HIGH / CRITICAL
    ) -> dict:
        """
        Tinh Smart SL/TP dua tren ATR + Support/Resistance + Fibonacci.
        Thay the logic % co dinh bang muc gia thuc te tu thi truong.

        ATR Multiplier:
        - Leverage thap (1-5x): SL = ATR * 2.0 (thoai mai)
        - Leverage trung binh (10-20x): SL = ATR * 1.0 (chat)
        - Leverage cao (25-50x): SL = ATR * 0.5 (cuc chat)
        - Leverage cuc cao (50+): SL = ATR * 0.3

        Macro Risk Adjustment:
        - NORMAL: Khong thay doi
        - HIGH: ATR * 1.3 (mo rong SL 30%)
        - CRITICAL: ATR * 1.6 (mo rong SL 60%)
        """
        if df.empty or len(df) < 20:
            return {"error": "Khong du du lieu"}

        latest = df.iloc[-1]
        price = float(latest["close"])
        atr = float(latest.get("atr", 0))

        # Fallback: tinh ATR don gian neu chua co
        if atr <= 0 or pd.isna(atr):
            recent = df.tail(14)
            tr = (recent["high"] - recent["low"]).mean()
            atr = float(tr) if tr > 0 else price * 0.02

        # === ATR MULTIPLIER theo leverage ===
        # Tang len so voi truoc de SL/TP khong qua chat voi don bay lon
        if leverage >= 50:
            atr_mult = 0.5      # 0.3 -> 0.5 (rong hon)
        elif leverage >= 25:
            atr_mult = 0.7      # 0.5 -> 0.7
        elif leverage >= 10:
            atr_mult = 1.0
        elif leverage >= 5:
            atr_mult = 1.5
        else:
            atr_mult = 2.0

        # === MACRO RISK ADJUSTMENT ===
        macro_mult = 1.0
        if macro_risk == "HIGH":
            macro_mult = 1.3  # Mo rong SL 30% truoc su kien quan trong
        elif macro_risk == "CRITICAL":
            macro_mult = 1.6  # Mo rong SL 60% truoc FOMC/CPI

        atr_distance = atr * atr_mult * macro_mult

        # === MINIMUM DISTANCE GUARD (leverage-aware) ===
        # Leverage cao can nhieu room hon de tranh bi quet SL trong vai phut
        # min_pct dam bao SL cach entry it nhat X% cua gia
        if leverage >= 100:
            min_pct = 0.004     # 0.4% — 125x liq = 0.8%, SL cach 50% liq
        elif leverage >= 50:
            min_pct = 0.006     # 0.6% — 50x liq = 2%, SL cach 30% liq
        elif leverage >= 25:
            min_pct = 0.008     # 0.8%
        elif leverage >= 10:
            min_pct = 0.010     # 1.0%
        else:
            min_pct = 0.015     # 1.5% cho leverage thap, cho thoai mai

        min_sl_distance = max(atr * 0.7, price * min_pct)
        # Dam bao atr_distance khong nho hon min
        atr_distance = max(atr_distance, min_sl_distance)

        # === LAY S/R LEVELS ===
        support1 = self._safe_float(latest.get("support1"), price * 0.97)
        support2 = self._safe_float(latest.get("support2"), price * 0.95)
        resistance1 = self._safe_float(latest.get("resistance1"), price * 1.03)
        resistance2 = self._safe_float(latest.get("resistance2"), price * 1.05)
        bb_lower = self._safe_float(latest.get("bb_lower"), price * 0.98)
        bb_upper = self._safe_float(latest.get("bb_upper"), price * 1.02)

        # Fibonacci levels (da tinh san trong df)
        fib_382 = self._safe_float(latest.get("fib_382"), price * 0.96)
        fib_500 = self._safe_float(latest.get("fib_500"), price * 0.95)
        fib_618 = self._safe_float(latest.get("fib_618"), price * 0.94)

        # Liquidation price
        if leverage > 1:
            if direction == "LONG":
                liq_price = price * (1 - 0.9 / leverage)
            else:
                liq_price = price * (1 + 0.9 / leverage)
        else:
            liq_price = 0

        method_parts = []  # Ghi lai phuong phap tinh

        if direction == "LONG":
            # === SL cho LONG ===
            atr_sl = price - atr_distance
            method_parts.append(f"ATR SL: ${atr_sl:.2f}")

            # Tim support gan nhat duoi gia
            supports_below = sorted(
                [s for s in [support1, support2, bb_lower, fib_618]
                 if s < price and s > 0],
                reverse=True
            )

            if supports_below:
                nearest_support = supports_below[0]
                # SL = max(ATR-based, nearest support - buffer)
                sr_sl = nearest_support - atr * 0.2  # Nho duoi support 1 chut
                sl = max(atr_sl, sr_sl)  # Lay muc cao hon (an toan hon)
                method_parts.append(f"S/R adjusted: ${sl:.2f}")
            else:
                sl = atr_sl

            # Dam bao SL khong vuot liq price
            if liq_price > 0 and sl <= liq_price:
                sl = liq_price + atr * 0.1
                method_parts.append("Liq-protected")

            # === MIN DISTANCE GUARD cho SL ===
            if abs(price - sl) < min_sl_distance:
                sl = price - min_sl_distance
                method_parts.append(f"Min-guard SL: ${sl:.2f}")

            # === TP cho LONG ===
            # Tim resistance tren gia
            resistances_above = sorted(
                [r for r in [resistance1, resistance2, bb_upper]
                 if r > price and r > 0]
            )

            if resistances_above:
                target_r = resistances_above[-1]  # Resistance xa nhat
                room = target_r - price
                # Dam bao room it nhat = 2x SL distance (RR >= 1:1 cho TP1)
                min_room = abs(price - sl) * 3
                room = max(room, min_room)
                tp1 = price + room * 0.382  # Fib 38.2%
                tp2 = price + room * 0.618  # Fib 61.8%
                tp3 = price + room
            else:
                tp1 = price + atr_distance * 1.5
                tp2 = price + atr_distance * 3.0
                tp3 = price + atr_distance * 5.0

            # === MIN TP GUARD ===
            min_tp1 = price + atr_distance * 1.5
            min_tp2 = price + atr_distance * 3.0
            min_tp3 = price + atr_distance * 5.0
            tp1 = max(tp1, min_tp1)
            tp2 = max(tp2, min_tp2)
            tp3 = max(tp3, min_tp3)

        else:  # SHORT
            # === SL cho SHORT ===
            atr_sl = price + atr_distance
            method_parts.append(f"ATR SL: ${atr_sl:.2f}")

            resistances_above = sorted(
                [r for r in [resistance1, resistance2, bb_upper]
                 if r > price and r > 0]
            )

            if resistances_above:
                nearest_resistance = resistances_above[0]
                sr_sl = nearest_resistance + atr * 0.2
                sl = min(atr_sl, sr_sl)
                method_parts.append(f"S/R adjusted: ${sl:.2f}")
            else:
                sl = atr_sl

            if liq_price > 0 and sl >= liq_price:
                sl = liq_price - atr * 0.1
                method_parts.append("Liq-protected")

            # === MIN DISTANCE GUARD cho SL ===
            if abs(sl - price) < min_sl_distance:
                sl = price + min_sl_distance
                method_parts.append(f"Min-guard SL: ${sl:.2f}")

            # === TP cho SHORT ===
            supports_below = sorted(
                [s for s in [support1, support2, bb_lower]
                 if s < price and s > 0],
                reverse=True
            )

            if supports_below:
                target_s = supports_below[-1]  # Support xa nhat
                room = price - target_s
                # Dam bao room it nhat = 2x SL distance
                min_room = abs(sl - price) * 3
                room = max(room, min_room)
                tp1 = price - room * 0.382
                tp2 = price - room * 0.618
                tp3 = price - room
            else:
                tp1 = price - atr_distance * 1.5
                tp2 = price - atr_distance * 3.0
                tp3 = price - atr_distance * 5.0

            # === MIN TP GUARD ===
            min_tp1 = price - atr_distance * 1.5
            min_tp2 = price - atr_distance * 3.0
            min_tp3 = price - atr_distance * 5.0
            tp1 = min(tp1, min_tp1)
            tp2 = min(tp2, min_tp2)
            tp3 = min(tp3, min_tp3)

        # Tinh cac chi so
        sl_pct = abs(price - sl) / price
        tp1_pct = abs(tp1 - price) / price
        rr_ratio = tp1_pct / sl_pct if sl_pct > 0 else 0

        return {
            "sl": round(sl, 6),
            "tp1": round(tp1, 6),
            "tp2": round(tp2, 6),
            "tp3": round(tp3, 6),
            "atr": round(atr, 6),
            "atr_distance": round(atr_distance, 6),
            "sl_pct": round(sl_pct * 100, 3),
            "tp1_pct": round(tp1_pct * 100, 3),
            "rr_ratio": round(rr_ratio, 2),
            "potential_roi": round(tp1_pct * leverage * 100, 1),
            "max_loss": round(sl_pct * leverage * 100, 1),
            "liq_price": round(liq_price, 2) if liq_price > 0 else None,
            "support": round(support1, 6),
            "resistance": round(resistance1, 6),
            "support2": round(support2, 6),
            "resistance2": round(resistance2, 6),
            "method": "ATR+S/R+Fib",
            "method_detail": " | ".join(method_parts),
            "macro_risk": macro_risk,
            "leverage": leverage,
        }

    def compute_limit_entries(
        self,
        df: pd.DataFrame,
        leverage: int = 1,
    ) -> list:
        """
        Phan tich cac muc gia tot de dat lenh cho (limit order).
        Dua tren Support/Resistance, Fibonacci, Bollinger Bands, EMA, VWAP.
        Tra ve list cac entry zone sap xep theo do manh (score).
        """
        if df.empty or len(df) < 20:
            return []

        latest = df.iloc[-1]
        price = float(latest["close"])
        atr = float(latest.get("atr", 0))
        if atr <= 0 or pd.isna(atr):
            atr = price * 0.02

        entries = []

        # === S/R Levels ===
        support1 = self._safe_float(latest.get("support1"), 0)
        support2 = self._safe_float(latest.get("support2"), 0)
        resistance1 = self._safe_float(latest.get("resistance1"), 0)
        resistance2 = self._safe_float(latest.get("resistance2"), 0)

        # Buy limit tai Support (chi khi support duoi gia hien tai)
        if support1 > 0 and support1 < price:
            dist_pct = abs(price - support1) / price * 100
            if dist_pct > 0.1 and dist_pct < 5:
                entries.append({
                    "direction": "LONG",
                    "entry_price": round(support1, 4),
                    "type": "LIMIT_BUY",
                    "reason": f"Support S1 (Pivot Point)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 8 if dist_pct < 2 else 6,
                    "zone": "support",
                })

        if support2 > 0 and support2 < price:
            dist_pct = abs(price - support2) / price * 100
            if dist_pct > 0.3 and dist_pct < 8:
                entries.append({
                    "direction": "LONG",
                    "entry_price": round(support2, 4),
                    "type": "LIMIT_BUY",
                    "reason": f"Support S2 (Pivot Point manh)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 9 if dist_pct < 3 else 7,
                    "zone": "support",
                })

        # Sell limit tai Resistance
        if resistance1 > 0 and resistance1 > price:
            dist_pct = abs(resistance1 - price) / price * 100
            if dist_pct > 0.1 and dist_pct < 5:
                entries.append({
                    "direction": "SHORT",
                    "entry_price": round(resistance1, 4),
                    "type": "LIMIT_SELL",
                    "reason": f"Resistance R1 (Pivot Point)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 8 if dist_pct < 2 else 6,
                    "zone": "resistance",
                })

        if resistance2 > 0 and resistance2 > price:
            dist_pct = abs(resistance2 - price) / price * 100
            if dist_pct > 0.3 and dist_pct < 8:
                entries.append({
                    "direction": "SHORT",
                    "entry_price": round(resistance2, 4),
                    "type": "LIMIT_SELL",
                    "reason": f"Resistance R2 (Pivot Point manh)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 9 if dist_pct < 3 else 7,
                    "zone": "resistance",
                })

        # === Fibonacci Levels ===
        fib_382 = self._safe_float(latest.get("fib_382"), 0)
        fib_500 = self._safe_float(latest.get("fib_500"), 0)
        fib_618 = self._safe_float(latest.get("fib_618"), 0)

        for fib_level, fib_name, base_score in [
            (fib_618, "Fibonacci 61.8%", 9),
            (fib_500, "Fibonacci 50.0%", 7),
            (fib_382, "Fibonacci 38.2%", 6),
        ]:
            if fib_level > 0 and fib_level < price:
                dist_pct = abs(price - fib_level) / price * 100
                if dist_pct > 0.2 and dist_pct < 10:
                    entries.append({
                        "direction": "LONG",
                        "entry_price": round(fib_level, 4),
                        "type": "LIMIT_BUY",
                        "reason": f"{fib_name} (Buy Zone)",
                        "distance_pct": round(dist_pct, 2),
                        "score": base_score,
                        "zone": "fibonacci",
                    })

        # === Bollinger Bands ===
        bb_lower = self._safe_float(latest.get("bb_lower"), 0)
        bb_upper = self._safe_float(latest.get("bb_upper"), 0)

        if bb_lower > 0 and bb_lower < price:
            dist_pct = abs(price - bb_lower) / price * 100
            if dist_pct > 0.2 and dist_pct < 6:
                entries.append({
                    "direction": "LONG",
                    "entry_price": round(bb_lower, 4),
                    "type": "LIMIT_BUY",
                    "reason": "Bollinger Band duoi (qua ban)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 8,
                    "zone": "bollinger",
                })

        if bb_upper > 0 and bb_upper > price:
            dist_pct = abs(bb_upper - price) / price * 100
            if dist_pct > 0.2 and dist_pct < 6:
                entries.append({
                    "direction": "SHORT",
                    "entry_price": round(bb_upper, 4),
                    "type": "LIMIT_SELL",
                    "reason": "Bollinger Band tren (qua mua)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 8,
                    "zone": "bollinger",
                })

        # === EMA levels ===
        ema20 = self._safe_float(latest.get("ema20"), 0)
        ema50 = self._safe_float(latest.get("ema50"), 0)

        if ema20 > 0 and ema20 < price:
            dist_pct = abs(price - ema20) / price * 100
            if dist_pct > 0.1 and dist_pct < 4:
                entries.append({
                    "direction": "LONG",
                    "entry_price": round(ema20, 4),
                    "type": "LIMIT_BUY",
                    "reason": "EMA20 (ho tro dong)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 7,
                    "zone": "ema",
                })

        if ema50 > 0 and ema50 < price:
            dist_pct = abs(price - ema50) / price * 100
            if dist_pct > 0.2 and dist_pct < 6:
                entries.append({
                    "direction": "LONG",
                    "entry_price": round(ema50, 4),
                    "type": "LIMIT_BUY",
                    "reason": "EMA50 (ho tro xu huong)",
                    "distance_pct": round(dist_pct, 2),
                    "score": 8,
                    "zone": "ema",
                })

        # === VWAP ===
        vwap = self._safe_float(latest.get("vwap"), 0)
        if vwap > 0:
            dist_pct = abs(price - vwap) / price * 100
            if dist_pct > 0.1 and dist_pct < 5:
                if vwap < price:
                    entries.append({
                        "direction": "LONG",
                        "entry_price": round(vwap, 4),
                        "type": "LIMIT_BUY",
                        "reason": "VWAP (gia binh quan theo volume)",
                        "distance_pct": round(dist_pct, 2),
                        "score": 7,
                        "zone": "vwap",
                    })
                else:
                    entries.append({
                        "direction": "SHORT",
                        "entry_price": round(vwap, 4),
                        "type": "LIMIT_SELL",
                        "reason": "VWAP (gia binh quan theo volume)",
                        "distance_pct": round(dist_pct, 2),
                        "score": 7,
                        "zone": "vwap",
                    })

        # Sap xep theo score giam dan
        entries.sort(key=lambda x: x["score"], reverse=True)
        return entries[:8]  # Top 8 muc gia tot nhat

    @staticmethod
    def _safe_float(val, fallback: float = 0.0) -> float:
        """An toan chuyen ve float, xu ly NaN."""
        if val is None:
            return fallback
        try:
            f = float(val)
            if pd.isna(f):
                return fallback
            return f
        except (ValueError, TypeError):
            return fallback

    def generate_signal(self, df: pd.DataFrame, symbol: str = "BTC/USDT") -> Optional[dict]:
        """
        Sinh tin hieu giao dich dua tren nhieu chi bao.
        Tra ve dict chua thong tin signal hoac None.
        """
        if df.empty or len(df) < 50:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = latest["close"]

        # === HE THONG TINH DIEM (SCORING) ===
        bull_score = 0  # Diem Long
        bear_score = 0  # Diem Short
        reasons = []

        # 1. RSI
        rsi = latest.get("rsi", 50)
        if rsi is not None:
            if rsi < 30:
                bull_score += 2
                reasons.append(f"RSI qua ban ({rsi:.1f})")
            elif rsi < 40:
                bull_score += 1
                reasons.append(f"RSI thap ({rsi:.1f})")
            elif rsi > 70:
                bear_score += 2
                reasons.append(f"RSI qua mua ({rsi:.1f})")
            elif rsi > 60:
                bear_score += 1
                reasons.append(f"RSI cao ({rsi:.1f})")

        # 2. MACD cat len/xuong
        macd = latest.get("macd")
        macd_sig = latest.get("macd_signal")
        prev_macd = prev.get("macd")
        prev_sig = prev.get("macd_signal")
        if all(v is not None for v in [macd, macd_sig, prev_macd, prev_sig]):
            if pd.notna(macd) and pd.notna(macd_sig) and pd.notna(prev_macd) and pd.notna(prev_sig):
                if prev_macd < prev_sig and macd > macd_sig:
                    bull_score += 2
                    reasons.append("MACD cat len (Golden Cross)")
                elif prev_macd > prev_sig and macd < macd_sig:
                    bear_score += 2
                    reasons.append("MACD cat xuong (Death Cross)")

        # 3. EMA Trend
        ema20 = latest.get("ema20")
        ema50 = latest.get("ema50")
        if ema20 is not None and ema50 is not None and pd.notna(ema20) and pd.notna(ema50):
            if price > ema20 > ema50:
                bull_score += 1
                reasons.append("Gia tren EMA20, EMA50 (Uptrend)")
            elif price < ema20 < ema50:
                bear_score += 1
                reasons.append("Gia duoi EMA20, EMA50 (Downtrend)")

        # 4. Bollinger Bands
        bb_lower = latest.get("bb_lower")
        bb_upper = latest.get("bb_upper")
        if bb_lower is not None and pd.notna(bb_lower) and price <= bb_lower:
            bull_score += 1
            reasons.append("Gia cham Bollinger Band duoi")
        if bb_upper is not None and pd.notna(bb_upper) and price >= bb_upper:
            bear_score += 1
            reasons.append("Gia cham Bollinger Band tren")

        # 5. Volume Spike
        if latest.get("vol_spike", False):
            reasons.append("Volume tang dot bien")

        # === CHI BAO MOI ===

        # 6. VWAP
        vwap = latest.get("vwap")
        if vwap is not None and pd.notna(vwap):
            if price > vwap * 1.01:
                bull_score += 1
                reasons.append("Gia tren VWAP (tang)")
            elif price < vwap * 0.99:
                bear_score += 1
                reasons.append("Gia duoi VWAP (giam)")

        # 7. ADX (Xu huong manh > 25)
        adx = latest.get("adx")
        di_plus = latest.get("di_plus")
        di_minus = latest.get("di_minus")
        if adx is not None and pd.notna(adx) and adx > 25:
            if di_plus is not None and di_minus is not None and pd.notna(di_plus) and pd.notna(di_minus):
                if di_plus > di_minus:
                    bull_score += 1
                    reasons.append(f"ADX manh ({adx:.0f}), +DI chiem uu the")
                else:
                    bear_score += 1
                    reasons.append(f"ADX manh ({adx:.0f}), -DI chiem uu the")

        # 8. Fibonacci (gia gan muc ho tro/khang cu)
        fib_618 = latest.get("fib_618")
        fib_382 = latest.get("fib_382")
        if fib_618 is not None and pd.notna(fib_618):
            if abs(price - fib_618) / price < 0.01:  # Gan muc Fib 61.8%
                bull_score += 1
                reasons.append("Gia tai Fibonacci 61.8% (ho tro manh)")
        if fib_382 is not None and pd.notna(fib_382):
            if abs(price - fib_382) / price < 0.01:  # Gan muc Fib 38.2%
                bear_score += 1
                reasons.append("Gia tai Fibonacci 38.2% (khang cu)")

        # 9. Support / Resistance
        support1 = latest.get("support1")
        resistance1 = latest.get("resistance1")
        if support1 is not None and pd.notna(support1):
            if abs(price - support1) / price < 0.005:
                bull_score += 1
                reasons.append("Gia tai vung ho tro S1")
        if resistance1 is not None and pd.notna(resistance1):
            if abs(price - resistance1) / price < 0.005:
                bear_score += 1
                reasons.append("Gia tai vung khang cu R1")

        # === RA QUYET DINH ===
        min_score = 3  # Can it nhat 3 diem de ra tin hieu

        if bull_score >= min_score and bull_score > bear_score:
            direction = "LONG"
        elif bear_score >= min_score and bear_score > bull_score:
            direction = "SHORT"
        else:
            direction = None

        # --- TREND FILTERS (Ngan chan giao dich nguoc xu huong) ---
        ema50 = latest.get("ema50")
        ema200 = latest.get("ema200")
        
        if direction == "LONG":
            if ema50 is not None and pd.notna(ema50) and price < ema50:
                direction = None
                reasons.append("Huy LONG: Gia duoi EMA50 (Nguoc xu huong)")
            elif ema200 is not None and pd.notna(ema200) and price < ema200:
                direction = None
                reasons.append("Huy LONG: Gia duoi EMA200 (Nguoc xu huong)")
        elif direction == "SHORT":
            if ema50 is not None and pd.notna(ema50) and price > ema50:
                direction = None
                reasons.append("Huy SHORT: Gia tren EMA50 (Nguoc xu huong)")
            elif ema200 is not None and pd.notna(ema200) and price > ema200:
                direction = None
                reasons.append("Huy SHORT: Gia tren EMA200 (Nguoc xu huong)")

        if direction == "LONG":
            sl = price * 0.985   # Stop Loss -1.5%
            tp = price * 1.035   # Take Profit +3.5%
        elif direction == "SHORT":
            sl = price * 1.015   # Stop Loss +1.5%
            tp = price * 0.965   # Take Profit -3.5%
        else:
            # Khong du diem hoac bi trend filter loc -> khong ra tin hieu, tra ve trang thai phan tich
            return {
                "symbol": symbol,
                "price": price,
                "direction": "NEUTRAL",
                "bull_score": bull_score,
                "bear_score": bear_score,
                "rsi": rsi,
                "reasons": reasons if reasons else ["Chua co tin hieu ro rang"],
                "timestamp": datetime.now().isoformat(),
            }

        return {
            "symbol": symbol,
            "price": price,
            "direction": direction,
            "entry": round(price, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "bull_score": bull_score,
            "bear_score": bear_score,
            "rsi": rsi,
            "reasons": reasons,
            "timestamp": datetime.now().isoformat(),
        }

    async def analyze(self, symbol: str = "BTC/USDT", timeframe: str = "1h") -> Optional[dict]:
        """
        Pipeline day du: Lay du lieu -> Tinh chi bao -> Sinh tin hieu.
        """
        df = await self.get_ohlcv(symbol, timeframe)
        if df.empty:
            return None

        df = self.calculate_indicators(df)
        signal = self.generate_signal(df, symbol)
        return signal
