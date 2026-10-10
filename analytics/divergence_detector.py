"""
Divergence & Mean Reversion Detector.
Phát hiện phân kỳ RSI và MACD (Phân kỳ thường đảo chiều & Phân kỳ ẩn tiếp diễn).
Kết hợp chặt chẽ với MarketRegimeDetector:
- Khi thị trường RANGING: Bắt đỉnh/đáy biên Bollinger Bands & chốt lời tại Mean (VWAP / EMA20).
- Khi thị trường TRENDING: Bắt nhịp hồi Hidden Divergence thuận xu hướng chính.
"""
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
from loguru import logger

from analytics.technical import TechnicalAnalyzer


class DivergenceDetector:
    """
    Phát hiện phân kỳ RSI, MACD Histogram và tạo tín hiệu Mean Reversion.
    """

    def __init__(self, ta_engine: Optional[TechnicalAnalyzer] = None):
        self.ta = ta_engine or TechnicalAnalyzer()

    def find_local_extrema(self, series: pd.Series, order: int = 3) -> Dict[str, List[int]]:
        """
        Tìm các đỉnh và đáy cục bộ trong một chuỗi số liệu (RSI hoặc Giá).
        """
        peaks = []
        troughs = []
        n = len(series)

        for i in range(order, n - order):
            val = series.iloc[i]
            if pd.isna(val):
                continue

            # Kiểm tra đỉnh cục bộ
            is_peak = True
            for offset in range(-order, order + 1):
                if offset == 0:
                    continue
                neighbor = series.iloc[i + offset]
                if pd.isna(neighbor) or neighbor >= val:
                    is_peak = False
                    break
            if is_peak:
                peaks.append(i)

            # Kiểm tra đáy cục bộ
            is_trough = True
            for offset in range(-order, order + 1):
                if offset == 0:
                    continue
                neighbor = series.iloc[i + offset]
                if pd.isna(neighbor) or neighbor <= val:
                    is_trough = False
                    break
            if is_trough:
                troughs.append(i)

        return {"peaks": peaks, "troughs": troughs}

    def detect_rsi_divergence(self, df: pd.DataFrame, lookback: int = 40) -> List[Dict[str, Any]]:
        """
        Phát hiện phân kỳ RSI so với Giá:
        - Regular Bullish: Price LL (Lower Low), RSI HL (Higher Low) -> Đảo chiều TĂNG
        - Regular Bearish: Price HH (Higher High), RSI LH (Lower High) -> Đảo chiều GIẢM
        - Hidden Bullish: Price HL (Higher Low), RSI LL (Lower Low) -> Tiếp diễn TĂNG
        - Hidden Bearish: Price LH (Lower High), RSI HH (Higher High) -> Tiếp diễn GIẢM
        """
        if df is None or len(df) < 30 or "rsi" not in df.columns:
            return []

        price_series = df["close"]
        rsi_series = df["rsi"]
        n = len(df)
        start_idx = max(0, n - lookback)

        price_extrema = self.find_local_extrema(price_series, order=2)
        rsi_extrema = self.find_local_extrema(rsi_series, order=2)

        divergences = []

        # 1. Quét phân kỳ ĐÁY (Bullish Divergences)
        price_troughs = [idx for idx in price_extrema["troughs"] if idx >= start_idx]
        if len(price_troughs) >= 2:
            for k in range(len(price_troughs) - 1):
                t1 = price_troughs[k]
                t2 = price_troughs[k + 1]

                # Khoảng cách giữa 2 đáy từ 4 đến 35 nến
                if not (4 <= (t2 - t1) <= 35):
                    continue

                p1, p2 = price_series.iloc[t1], price_series.iloc[t2]
                r1, r2 = rsi_series.iloc[t1], rsi_series.iloc[t2]

                ts2 = df.index[t2]
                ts2_str = ts2.isoformat() if hasattr(ts2, "isoformat") else str(ts2)

                # Regular Bullish Divergence: Giá tạo đáy thấp hơn nhưng RSI tạo đáy cao hơn
                if p2 < p1 * 0.998 and r2 > r1 + 1.5:
                    divergences.append({
                        "type": "REGULAR_BULLISH",
                        "indicator": "RSI",
                        "direction": "LONG",
                        "trigger_index": t2,
                        "time": ts2_str,
                        "price1": float(p1),
                        "price2": float(p2),
                        "rsi1": float(r1),
                        "rsi2": float(r2),
                        "reason": f"Phân kỳ thường RSI đáy: Giá giảm (${p1:,.1f} -> ${p2:,.1f}) nhưng RSI tăng ({r1:.1f} -> {r2:.1f})"
                    })

                # Hidden Bullish Divergence: Giá tạo đáy cao hơn nhưng RSI giảm sâu hơn
                elif p2 > p1 * 1.002 and r2 < r1 - 1.5:
                    divergences.append({
                        "type": "HIDDEN_BULLISH",
                        "indicator": "RSI",
                        "direction": "LONG",
                        "trigger_index": t2,
                        "time": ts2_str,
                        "price1": float(p1),
                        "price2": float(p2),
                        "rsi1": float(r1),
                        "rsi2": float(r2),
                        "reason": f"Phân kỳ ẩn RSI: Giá giữ đáy cao hơn (${p1:,.1f} -> ${p2:,.1f}) tiếp diễn xu hướng tăng"
                    })

        # 2. Quét phân kỳ ĐỈNH (Bearish Divergences)
        price_peaks = [idx for idx in price_extrema["peaks"] if idx >= start_idx]
        if len(price_peaks) >= 2:
            for k in range(len(price_peaks) - 1):
                pk1 = price_peaks[k]
                pk2 = price_peaks[k + 1]

                if not (4 <= (pk2 - pk1) <= 35):
                    continue

                p1, p2 = price_series.iloc[pk1], price_series.iloc[pk2]
                r1, r2 = rsi_series.iloc[pk1], rsi_series.iloc[pk2]

                ts2 = df.index[pk2]
                ts2_str = ts2.isoformat() if hasattr(ts2, "isoformat") else str(ts2)

                # Regular Bearish Divergence: Giá tạo đỉnh cao hơn nhưng RSI đuối dần (Lower High)
                if p2 > p1 * 1.002 and r2 < r1 - 1.5:
                    divergences.append({
                        "type": "REGULAR_BEARISH",
                        "indicator": "RSI",
                        "direction": "SHORT",
                        "trigger_index": pk2,
                        "time": ts2_str,
                        "price1": float(p1),
                        "price2": float(p2),
                        "rsi1": float(r1),
                        "rsi2": float(r2),
                        "reason": f"Phân kỳ thường RSI đỉnh: Giá tăng (${p1:,.1f} -> ${p2:,.1f}) nhưng RSI suy yếu ({r1:.1f} -> {r2:.1f})"
                    })

                # Hidden Bearish Divergence: Giá tạo đỉnh thấp hơn nhưng RSI bật cao
                elif p2 < p1 * 0.998 and r2 > r1 + 1.5:
                    divergences.append({
                        "type": "HIDDEN_BEARISH",
                        "indicator": "RSI",
                        "direction": "SHORT",
                        "trigger_index": pk2,
                        "time": ts2_str,
                        "price1": float(p1),
                        "price2": float(p2),
                        "rsi1": float(r1),
                        "rsi2": float(r2),
                        "reason": f"Phân kỳ ẩn RSI: Giá tạo đỉnh thấp hơn (${p1:,.1f} -> ${p2:,.1f}) tiếp diễn xu hướng giảm"
                    })

        return divergences

    def analyze(self, df: pd.DataFrame, market_regime: str = "RANGING") -> Dict[str, Any]:
        """
        Tổng hợp phân kỳ kết hợp với dải Bollinger Bands và trạng thái thị trường.
        :param market_regime: "RANGING" | "TRENDING" | "VOLATILE"
        """
        if df is None or len(df) < 30:
            return {"has_signal": False, "direction": "NEUTRAL", "reasons": []}

        df_calc = self.ta.calculate_indicators(df.copy())
        divergences = self.detect_rsi_divergence(df_calc, lookback=35)

        latest = df_calc.iloc[-1]
        price = float(latest["close"])
        bb_upper = float(latest.get("bb_upper", price * 1.02))
        bb_lower = float(latest.get("bb_lower", price * 0.98))
        bb_mid = float(latest.get("bb_mid", price))
        vwap = float(latest.get("vwap", price))

        n = len(df)
        # Lọc các phân kỳ xuất hiện trong 6 nến gần nhất
        recent_divs = [d for d in divergences if d["trigger_index"] >= n - 6]

        has_signal = False
        direction = "NEUTRAL"
        reasons = []
        target_tp = bb_mid
        suggested_sl = None

        if recent_divs:
            div = recent_divs[-1]
            div_type = div["type"]
            div_dir = div["direction"]

            # Phù hợp với Regime:
            # - RANGING: Đánh mạnh Regular Divergence (bắt đảo chiều tại biên)
            # - TRENDING: Ưu tiên Hidden Divergence (đánh thuận xu hướng)
            if market_regime == "RANGING":
                if "REGULAR" in div_type:
                    has_signal = True
                    direction = div_dir
                    reasons.append(div["reason"])
                    reasons.append("Mean Reversion: Chốt lời mục tiêu tại trục giữa BB / VWAP")

                    if direction == "LONG":
                        # Chạm dải dưới BB càng tăng độ tin cậy
                        if price <= bb_lower * 1.005:
                            reasons.append(f"Giá chạm dải dưới BB (${bb_lower:,.1f})")
                        suggested_sl = price * 0.985
                        target_tp = (bb_mid + vwap) / 2
                    else:
                        if price >= bb_upper * 0.995:
                            reasons.append(f"Giá chạm dải trên BB (${bb_upper:,.1f})")
                        suggested_sl = price * 1.015
                        target_tp = (bb_mid + vwap) / 2

            elif market_regime == "TRENDING":
                if "HIDDEN" in div_type:
                    has_signal = True
                    direction = div_dir
                    reasons.append(div["reason"])
                    reasons.append("Trend Continuation: Vào lệnh thuận theo xu hướng chính sau nhịp điều chỉnh")
                    suggested_sl = price * 0.98 if direction == "LONG" else price * 1.02
                    target_tp = price * 1.04 if direction == "LONG" else price * 0.96

        return {
            "has_signal": has_signal,
            "direction": direction,
            "market_regime": market_regime,
            "price": price,
            "suggested_sl": round(suggested_sl, 2) if suggested_sl else None,
            "target_tp": round(target_tp, 2) if target_tp else None,
            "recent_divergences": recent_divs,
            "all_divergences": divergences[-6:],
            "reasons": reasons
        }
