"""
Market Regime Detector — Nhận biết trạng thái thị trường.
Phân loại TRENDING / RANGING / VOLATILE để điều chỉnh chiến lược bot.

Không dùng ML — hoàn toàn rule-based dựa trên:
- ADX (lực xu hướng)
- Bollinger Band Width (biến động giá)
- ATR/Price ratio (biến động tương đối)
- EMA alignment (sắp xếp đường trung bình)
- Volume trend (xu hướng khối lượng)
"""
import pandas as pd
import numpy as np
from loguru import logger
from typing import Optional


class MarketRegimeDetector:
    """
    Detect trang thai thi truong tu DataFrame OHLCV da co chi bao.
    Output: regime + adjustments cho bot.
    """

    # Regime constants
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"

    def detect(self, df: pd.DataFrame) -> dict:
        """
        Phan tich DataFrame (da co indicators tu TechnicalAnalyzer.calculate_indicators)
        va tra ve regime + recommended adjustments.

        Returns:
            {
                "regime": "TRENDING" | "RANGING" | "VOLATILE",
                "confidence": 0.0 - 1.0,
                "trend_direction": "BULLISH" | "BEARISH" | "NEUTRAL",
                "details": {...},
                "adjustments": {
                    "min_score_adjust": 0 or +1 or +2,
                    "leverage_mult": 0.5 - 1.0,
                    "sl_mult": 0.8 - 1.5,
                    "tp_mult": 0.7 - 1.3,
                    "max_positions_mult": 0.5 - 1.0,
                    "rating_adjust": -1 to +1,
                }
            }
        """
        if df is None or df.empty or len(df) < 30:
            return self._default_result()

        try:
            latest = df.iloc[-1]
            scores = {"trending": 0, "ranging": 0, "volatile": 0}
            details = {}

            # === 1. ADX Analysis ===
            adx = self._safe(latest.get("adx"))
            if adx is not None:
                details["adx"] = round(adx, 1)
                if adx > 30:
                    scores["trending"] += 3
                elif adx > 25:
                    scores["trending"] += 2
                elif adx < 15:
                    scores["ranging"] += 3
                elif adx < 20:
                    scores["ranging"] += 2
                else:
                    scores["ranging"] += 1

            # === 2. Bollinger Band Width ===
            bb_upper = self._safe(latest.get("bb_upper"))
            bb_lower = self._safe(latest.get("bb_lower"))
            bb_mid = self._safe(latest.get("bb_mid"))
            if all(v is not None for v in [bb_upper, bb_lower, bb_mid]) and bb_mid > 0:
                bb_width = (bb_upper - bb_lower) / bb_mid
                details["bb_width"] = round(bb_width, 4)

                # So sanh voi BB width trung binh 20 ky
                if len(df) >= 20:
                    bb_widths = []
                    for i in range(-20, 0):
                        row = df.iloc[i]
                        u = self._safe(row.get("bb_upper"))
                        l = self._safe(row.get("bb_lower"))
                        m = self._safe(row.get("bb_mid"))
                        if all(v is not None for v in [u, l, m]) and m > 0:
                            bb_widths.append((u - l) / m)
                    if bb_widths:
                        avg_width = np.mean(bb_widths)
                        width_ratio = bb_width / avg_width if avg_width > 0 else 1
                        details["bb_width_ratio"] = round(width_ratio, 2)

                        if width_ratio > 1.8:
                            scores["volatile"] += 3
                        elif width_ratio > 1.3:
                            scores["trending"] += 2
                        elif width_ratio < 0.6:
                            scores["ranging"] += 3
                        elif width_ratio < 0.8:
                            scores["ranging"] += 2

            # === 3. ATR/Price Ratio ===
            atr = self._safe(latest.get("atr"))
            price = self._safe(latest.get("close"))
            if atr is not None and price is not None and price > 0:
                atr_pct = atr / price
                details["atr_pct"] = round(atr_pct * 100, 3)

                # So sanh voi ATR trung binh
                if len(df) >= 14:
                    recent_atrs = []
                    for i in range(-14, 0):
                        a = self._safe(df.iloc[i].get("atr"))
                        p = self._safe(df.iloc[i].get("close"))
                        if a is not None and p is not None and p > 0:
                            recent_atrs.append(a / p)
                    if recent_atrs:
                        avg_atr = np.mean(recent_atrs)
                        atr_ratio = atr_pct / avg_atr if avg_atr > 0 else 1
                        details["atr_ratio"] = round(atr_ratio, 2)

                        if atr_ratio > 2.0:
                            scores["volatile"] += 3
                        elif atr_ratio > 1.5:
                            scores["volatile"] += 2
                        elif atr_ratio < 0.6:
                            scores["ranging"] += 2

            # === 4. EMA Alignment ===
            ema20 = self._safe(latest.get("ema20"))
            ema50 = self._safe(latest.get("ema50"))
            if all(v is not None for v in [price, ema20, ema50]) and price > 0:
                # Aligned = price > ema20 > ema50 (bull) or price < ema20 < ema50 (bear)
                if price > ema20 > ema50:
                    scores["trending"] += 2
                    details["ema_alignment"] = "BULLISH_ALIGNED"
                elif price < ema20 < ema50:
                    scores["trending"] += 2
                    details["ema_alignment"] = "BEARISH_ALIGNED"
                else:
                    # EMAs tangled/crossed = ranging
                    ema_spread = abs(ema20 - ema50) / price
                    if ema_spread < 0.005:  # < 0.5% apart
                        scores["ranging"] += 2
                        details["ema_alignment"] = "TANGLED"
                    else:
                        details["ema_alignment"] = "MIXED"

            # === 5. Volume Trend ===
            if len(df) >= 20:
                recent_vol = df["volume"].tail(5).mean()
                avg_vol = df["volume"].tail(20).mean()
                if avg_vol > 0:
                    vol_ratio = recent_vol / avg_vol
                    details["vol_ratio"] = round(vol_ratio, 2)

                    if vol_ratio > 2.0:
                        scores["volatile"] += 2
                    elif vol_ratio > 1.3:
                        scores["trending"] += 1
                    elif vol_ratio < 0.5:
                        scores["ranging"] += 2

            # === 6. Price Action — Directional Movement ===
            if len(df) >= 10 and price is not None:
                price_10_ago = self._safe(df.iloc[-10].get("close"))
                if price_10_ago is not None and price_10_ago > 0:
                    directional_move = abs(price - price_10_ago) / price_10_ago
                    details["directional_move_pct"] = round(directional_move * 100, 2)

                    if directional_move > 0.05:   # > 5% in 10 candles
                        scores["trending"] += 2
                    elif directional_move < 0.01:  # < 1%
                        scores["ranging"] += 2

            # === DETERMINE REGIME ===
            max_score = max(scores.values())
            if max_score == 0:
                regime = self.RANGING
                confidence = 0.3
            else:
                total = sum(scores.values())
                if scores["volatile"] >= scores["trending"] and scores["volatile"] >= scores["ranging"]:
                    regime = self.VOLATILE
                elif scores["trending"] >= scores["ranging"]:
                    regime = self.TRENDING
                else:
                    regime = self.RANGING
                confidence = scores[regime.lower()] / total if total > 0 else 0.5

            # Trend direction
            trend_direction = "NEUTRAL"
            if regime == self.TRENDING:
                if details.get("ema_alignment") == "BULLISH_ALIGNED":
                    trend_direction = "BULLISH"
                elif details.get("ema_alignment") == "BEARISH_ALIGNED":
                    trend_direction = "BEARISH"
                elif price is not None and ema50 is not None:
                    trend_direction = "BULLISH" if price > ema50 else "BEARISH"

            # === ADJUSTMENTS ===
            adjustments = self._compute_adjustments(regime, confidence)

            result = {
                "regime": regime,
                "confidence": round(confidence, 2),
                "trend_direction": trend_direction,
                "scores": scores,
                "details": details,
                "adjustments": adjustments,
            }

            logger.info(
                f"[Regime] {regime} (conf={confidence:.0%}) | "
                f"Trend={trend_direction} | Scores: T={scores['trending']} R={scores['ranging']} V={scores['volatile']}"
            )
            return result

        except Exception as e:
            logger.error(f"[Regime] Error: {e}")
            return self._default_result()

    def _compute_adjustments(self, regime: str, confidence: float) -> dict:
        """Tinh toan dieu chinh chien luoc dua tren regime."""
        if regime == self.TRENDING:
            return {
                "min_score_adjust": 0,          # Giu nguyen min_score
                "leverage_mult": 1.0,           # Leverage binh thuong
                "sl_mult": 0.9,                 # Thu hep SL 10% (trend ho tro)
                "tp_mult": 1.3,                 # Mo rong TP 30% (cho trend chay)
                "max_positions_mult": 1.0,      # So lenh binh thuong
                "rating_adjust": 1 if confidence > 0.6 else 0,  # +1 sao neu trend manh
            }
        elif regime == self.RANGING:
            return {
                "min_score_adjust": 1,          # Tang min_score +1 (chi trade khi du manh)
                "leverage_mult": 0.7,           # Giam leverage 30%
                "sl_mult": 1.0,                 # Giu nguyen SL
                "tp_mult": 0.7,                 # Thu hep TP 30% (khong co trend de chay)
                "max_positions_mult": 0.6,      # Giam so lenh 40%
                "rating_adjust": -1,            # -1 sao (sideway = nguy hiem)
            }
        else:  # VOLATILE
            return {
                "min_score_adjust": 2,          # Tang min_score +2 (rat than trong)
                "leverage_mult": 0.5,           # Giam leverage 50%
                "sl_mult": 1.5,                 # Mo rong SL 50% (tranh bi quet)
                "tp_mult": 1.0,                 # Giu TP binh thuong
                "max_positions_mult": 0.4,      # Chi mo 40% so lenh binh thuong
                "rating_adjust": -1,            # -1 sao
            }

    def _default_result(self) -> dict:
        return {
            "regime": self.RANGING,
            "confidence": 0.3,
            "trend_direction": "NEUTRAL",
            "scores": {"trending": 0, "ranging": 0, "volatile": 0},
            "details": {},
            "adjustments": self._compute_adjustments(self.RANGING, 0.3),
        }

    @staticmethod
    def _safe(val) -> Optional[float]:
        if val is None:
            return None
        try:
            f = float(val)
            if pd.isna(f):
                return None
            return f
        except (ValueError, TypeError):
            return None
