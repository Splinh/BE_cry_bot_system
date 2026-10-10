"""
Multi-Timeframe Confluence Engine (MTF).
Kết nối phân tích 3 tầng thời gian:
1. Macro HTF (4h / 1d): Định vị xu hướng lớn và mức hỗ trợ/kháng cự vĩ mô.
2. Setup MTF (1h): Xác định vùng giá trị (Premium / Discount), FVG, Fibonacci.
3. Trigger LTF (15m): Bắt điểm kích hoạt vào lệnh và tối ưu điểm cắt lỗ (Tight SL) để tối đa hóa R:R.
"""
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
from loguru import logger

from analytics.technical import TechnicalAnalyzer
from analytics.smc_analyzer import SMCAnalyzer


class MultiTimeframeConfluence:
    """
    Bộ lọc và đánh giá đồng thuận đa khung thời gian.
    """

    def __init__(self, ta_engine: Optional[TechnicalAnalyzer] = None, smc_engine: Optional[SMCAnalyzer] = None):
        self.ta = ta_engine or TechnicalAnalyzer()
        self.smc = smc_engine or SMCAnalyzer()

    def analyze_htf_trend(self, df_htf: pd.DataFrame) -> Dict[str, Any]:
        """
        Phân tích xu hướng khung lớn (4h hoặc 1d).
        """
        if df_htf is None or len(df_htf) < 30:
            return {"trend": "NEUTRAL", "bias": 0, "reasons": ["Khung lớn chưa đủ dữ liệu"]}

        df_calc = self.ta.calculate_indicators(df_htf.copy())
        latest = df_calc.iloc[-1]
        price = float(latest["close"])

        ema20 = float(latest.get("ema20", price))
        ema50 = float(latest.get("ema50", price))
        ema200 = float(latest.get("ema200", price)) if pd.notna(latest.get("ema200")) else None
        adx = float(latest.get("adx", 0)) if pd.notna(latest.get("adx")) else 0

        bull_points = 0
        bear_points = 0
        reasons = []

        # 1. Cấu trúc EMA
        if ema20 > ema50:
            bull_points += 2
            reasons.append("HTF: EMA20 > EMA50 (Uptrend ngắn-trung hạn)")
        else:
            bear_points += 2
            reasons.append("HTF: EMA20 < EMA50 (Downtrend ngắn-trung hạn)")

        if ema200:
            if price > ema200:
                bull_points += 2
                reasons.append(f"HTF: Giá trên EMA200 (${ema200:,.1f}) - Macro Bullish")
            else:
                bear_points += 2
                reasons.append(f"HTF: Giá dưới EMA200 (${ema200:,.1f}) - Macro Bearish")

        # 2. Sức mạnh xu hướng ADX
        if adx >= 25:
            di_plus = float(latest.get("di_plus", 0))
            di_minus = float(latest.get("di_minus", 0))
            if di_plus > di_minus:
                bull_points += 1
                reasons.append(f"HTF: ADX mạnh ({adx:.0f}) phe Mua áp đảo")
            else:
                bear_points += 1
                reasons.append(f"HTF: ADX mạnh ({adx:.0f}) phe Bán áp đảo")

        if bull_points >= 4 and bull_points > bear_points:
            trend = "STRONG_BULLISH"
        elif bull_points > bear_points:
            trend = "BULLISH"
        elif bear_points >= 4 and bear_points > bull_points:
            trend = "STRONG_BEARISH"
        elif bear_points > bull_points:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"

        return {
            "trend": trend,
            "bull_points": bull_points,
            "bear_points": bear_points,
            "price": price,
            "ema50": ema50,
            "ema200": ema200,
            "reasons": reasons
        }

    def analyze_setup_mtf(self, df_mtf: pd.DataFrame) -> Dict[str, Any]:
        """
        Phân tích khung trung gian (1h): Xác định vị thế giá (Premium / Discount) và S/R.
        """
        if df_mtf is None or len(df_mtf) < 20:
            return {"zone": "EQUILIBRIUM", "reasons": []}

        df_calc = self.ta.calculate_indicators(df_mtf.copy())
        latest = df_calc.iloc[-1]
        price = float(latest["close"])

        # Tìm Swing Range trong 50 nến gần nhất
        recent = df_calc.tail(50)
        swing_high = float(recent["high"].max())
        swing_low = float(recent["low"].min())
        equilibrium = (swing_high + swing_low) / 2

        # Phân chia Premium / Discount
        # Dưới 50% -> Discount (Thích hợp Mua), Trên 50% -> Premium (Thích hợp Bán)
        fib_500 = equilibrium
        fib_618 = swing_high - (swing_high - swing_low) * 0.618
        fib_382 = swing_high - (swing_high - swing_low) * 0.382

        reasons = []
        if price < fib_618:
            zone = "DEEP_DISCOUNT"
            reasons.append(f"1H Setup: Vùng chiết khấu sâu (< Fib 61.8% ${fib_618:,.1f}) - Tối ưu cho LONG")
        elif price < equilibrium:
            zone = "DISCOUNT"
            reasons.append(f"1H Setup: Vùng chiết khấu (< 50% Range) - Thuận lợi cho LONG")
        elif price > fib_382:
            zone = "DEEP_PREMIUM"
            reasons.append(f"1H Setup: Vùng giá đắt (> Fib 38.2% ${fib_382:,.1f}) - Tối ưu cho SHORT")
        else:
            zone = "PREMIUM"
            reasons.append(f"1H Setup: Vùng giá cao (> 50% Range) - Thuận lợi cho SHORT")

        return {
            "zone": zone,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "equilibrium": equilibrium,
            "reasons": reasons
        }

    def evaluate_confluence(
        self,
        df_15m: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_4h: pd.DataFrame,
        symbol: str = "BTC/USDT"
    ) -> Dict[str, Any]:
        """
        Đánh giá đồng thuận toàn diện 3 khung:
        - 4H Trend
        - 1H Setup Zone
        - 15M Trigger & SMC Sweeps
        """
        htf_result = self.analyze_htf_trend(df_4h)
        setup_result = self.analyze_setup_mtf(df_1h)
        
        # 15m trigger: Chạy cả TechnicalAnalyzer lẫn SMCAnalyzer
        df_15m_calc = self.ta.calculate_indicators(df_15m.copy())
        sig_15m = self.ta.generate_signal(df_15m_calc, symbol)
        smc_15m = self.smc.analyze(df_15m)

        price = float(df_15m["close"].iloc[-1])
        htf_trend = htf_result["trend"]
        setup_zone = setup_result["zone"]

        reasons = []
        confluence_score = 0
        direction = "WAIT"

        # Đưa các lý do nền tảng vào
        reasons.extend(htf_result["reasons"][:2])
        reasons.extend(setup_result["reasons"][:1])

        # === KỊCH BẢN 1: THUẬN XU HƯỚNG VĨ MÔ (Trend Following MTF) ===
        if "BULLISH" in htf_trend:
            # Ưu tiên tìm LONG khi 1h ở Discount và 15m có trigger
            if setup_zone in ("DISCOUNT", "DEEP_DISCOUNT", "EQUILIBRIUM"):
                confluence_score += 3
                if sig_15m and sig_15m.get("direction") == "LONG":
                    confluence_score += 4
                    direction = "LONG"
                    reasons.append("15m: Technical Signal xuất hiện điểm MUA thuận Trend 4H")
                if smc_15m.get("direction") == "LONG":
                    confluence_score += 3
                    direction = "LONG"
                    reasons.append(f"15m SMC: {smc_15m['reasons'][0] if smc_15m['reasons'] else 'Quét đáy thanh khoản'}")

        elif "BEARISH" in htf_trend:
            # Ưu tiên tìm SHORT khi 1h ở Premium và 15m có trigger
            if setup_zone in ("PREMIUM", "DEEP_PREMIUM", "EQUILIBRIUM"):
                confluence_score += 3
                if sig_15m and sig_15m.get("direction") == "SHORT":
                    confluence_score += 4
                    direction = "SHORT"
                    reasons.append("15m: Technical Signal xuất hiện điểm BÁN thuận Trend 4H")
                if smc_15m.get("direction") == "SHORT":
                    confluence_score += 3
                    direction = "SHORT"
                    reasons.append(f"15m SMC: {smc_15m['reasons'][0] if smc_15m['reasons'] else 'Quét đỉnh thanh khoản'}")

        # === KỊCH BẢN 2: BẮT ĐẢO CHIỀU CỰC ĐẠI (SMC Reversal tại Key S/R) ===
        # Ví dụ trường hợp đỉnh $85,200: Dù 4H đang tăng, nhưng 1H ở Deep Premium và 15m quét râu đỉnh lịch sử!
        if smc_15m.get("has_signal") and smc_15m.get("confidence", 0) >= 4:
            smc_dir = smc_15m["direction"]
            if smc_dir == "SHORT" and setup_zone == "DEEP_PREMIUM":
                direction = "SHORT"
                confluence_score = max(confluence_score, 8)
                reasons.append("⚡ ĐẢO CHIỀU SMC: Quét râu đỉnh tại vùng cản Deep Premium (Bắt đỉnh sớm)")
            elif smc_dir == "LONG" and setup_zone == "DEEP_DISCOUNT":
                direction = "LONG"
                confluence_score = max(confluence_score, 8)
                reasons.append("⚡ ĐẢO CHIỀU SMC: Rút chân quét đáy tại vùng hỗ trợ Deep Discount (Bắt đáy sớm)")

        # === TÍNH TOÁN KẾ HOẠCH VÀO LỆNH (ENTRY / SL / TP) ===
        entry = price
        sl = None
        tp1 = None
        tp2 = None
        rr_ratio = 0.0

        if direction != "WAIT" and confluence_score >= 6:
            # Ưu tiên SL chặt chẽ theo cấu trúc 15m (SMC wick hoặc ATR 15m)
            atr_15m = float(df_15m_calc.iloc[-1].get("atr", price * 0.01))
            if smc_15m.get("suggested_sl") and smc_15m.get("direction") == direction:
                sl = smc_15m["suggested_sl"]
            else:
                sl = entry - atr_15m * 1.5 if direction == "LONG" else entry + atr_15m * 1.5

            sl_dist = abs(entry - sl)
            if sl_dist > 0:
                tp1 = entry + sl_dist * 2.0 if direction == "LONG" else entry - sl_dist * 2.0
                tp2 = entry + sl_dist * 3.5 if direction == "LONG" else entry - sl_dist * 3.5
                rr_ratio = round(abs(tp1 - entry) / sl_dist, 2)
        else:
            direction = "WAIT"

        is_confluent = direction != "WAIT" and confluence_score >= 6

        return {
            "is_confluent": is_confluent,
            "direction": direction,
            "confluence_score": confluence_score,
            "price": price,
            "htf_trend": htf_trend,
            "setup_zone": setup_zone,
            "entry": round(entry, 2),
            "sl": round(sl, 2) if sl else None,
            "tp1": round(tp1, 2) if tp1 else None,
            "tp2": round(tp2, 2) if tp2 else None,
            "rr_ratio": rr_ratio,
            "reasons": reasons
        }
