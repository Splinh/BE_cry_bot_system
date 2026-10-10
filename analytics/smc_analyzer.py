"""
Smart Money Concepts (SMC) & Liquidity Sweep Analyzer.
Chuyên phát hiện bẫy thanh khoản (Bull/Bear Trap), quét râu (Liquidity Sweep),
Fair Value Gap (FVG), và Order Blocks (OB) để bắt đỉnh/đáy đảo chiều với R:R cao.
"""
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from loguru import logger


class SMCAnalyzer:
    """
    Phân tích Smart Money Concepts trên dữ liệu nến OHLCV.
    """

    def __init__(self, wick_threshold: float = 0.45, fvg_min_pct: float = 0.0015):
        """
        :param wick_threshold: Tỷ lệ chiều dài râu nến tối thiểu so với toàn bộ cây nến để tính là sweep (mặc định 45%).
        :param fvg_min_pct: Độ rộng tối thiểu của Fair Value Gap so với giá để tránh nhiễu (mặc định 0.15%).
        """
        self.wick_threshold = wick_threshold
        self.fvg_min_pct = fvg_min_pct

    def detect_swings(self, df: pd.DataFrame, left: int = 2, right: int = 2) -> Dict[str, List[Dict[str, Any]]]:
        """
        Nhận diện đỉnh (Swing High) và đáy (Swing Low) cục bộ dựa trên mô hình Fractal.
        """
        if df is None or len(df) < (left + right + 1):
            return {"highs": [], "lows": []}

        highs = []
        lows = []
        n = len(df)

        for i in range(left, n - right):
            current_high = df["high"].iloc[i]
            current_low = df["low"].iloc[i]
            ts = df.index[i]
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            # Kiểm tra Swing High: cao hơn `left` nến trước và `right` nến sau
            is_swing_high = True
            for offset in range(-left, right + 1):
                if offset == 0:
                    continue
                if df["high"].iloc[i + offset] >= current_high:
                    is_swing_high = False
                    break

            if is_swing_high:
                highs.append({
                    "index": i,
                    "time": ts_str,
                    "price": float(current_high),
                    "type": "SWING_HIGH"
                })

            # Kiểm tra Swing Low: thấp hơn `left` nến trước và `right` nến sau
            is_swing_low = True
            for offset in range(-left, right + 1):
                if offset == 0:
                    continue
                if df["low"].iloc[i + offset] <= current_low:
                    is_swing_low = False
                    break

            if is_swing_low:
                lows.append({
                    "index": i,
                    "time": ts_str,
                    "price": float(current_low),
                    "type": "SWING_LOW"
                })

        return {"highs": highs, "lows": lows}

    def detect_liquidity_sweeps(self, df: pd.DataFrame, lookback: int = 40) -> List[Dict[str, Any]]:
        """
        Phát hiện bẫy thanh khoản (Liquidity Sweep / Fakeout):
        - Quét đỉnh cũ (Bearish Sweep / Short setup): Giá vượt Swing High nhưng rút râu trên dài, đóng nến nằm dưới Swing High.
        - Quét đáy cũ (Bullish Sweep / Long setup): Giá đâm thủng Swing Low nhưng rút chân dưới dài, đóng nến nằm trên Swing Low.
        """
        if df is None or len(df) < 15:
            return []

        swings = self.detect_swings(df, left=2, right=2)
        swing_highs = swings["highs"]
        swing_lows = swings["lows"]

        sweeps = []
        n = len(df)
        start_idx = max(0, n - lookback)

        for i in range(start_idx, n):
            row = df.iloc[i]
            open_p = float(row["open"])
            high_p = float(row["high"])
            low_p = float(row["low"])
            close_p = float(row["close"])
            candle_range = high_p - low_p
            ts = df.index[i]
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            if candle_range <= 0:
                continue

            upper_wick = high_p - max(open_p, close_p)
            lower_wick = min(open_p, close_p) - low_p
            body_size = abs(close_p - open_p)

            # 1. Bearish Sweep (Quét đỉnh thanh khoản -> Setup SHORT)
            # Tìm Swing High gần nhất trước nến này (cách ít nhất 2 nến)
            relevant_highs = [sh for sh in swing_highs if sh["index"] < i - 1 and sh["index"] >= i - 50]
            for sh in relevant_highs:
                sh_price = sh["price"]
                # Điều kiện: High nến đâm thủng đỉnh cũ nhưng Close quay giật lùi về dưới đỉnh cũ
                if high_p > sh_price and close_p < sh_price:
                    upper_wick_ratio = upper_wick / candle_range
                    if upper_wick_ratio >= self.wick_threshold:
                        # Khoảng quét vượt đỉnh
                        sweep_depth = (high_p - sh_price) / sh_price * 100
                        sweeps.append({
                            "type": "BEARISH_SWEEP",
                            "direction": "SHORT",
                            "time": ts_str,
                            "index": i,
                            "candle_close": close_p,
                            "swept_level": sh_price,
                            "wick_high": high_p,
                            "wick_ratio": round(upper_wick_ratio, 3),
                            "sweep_depth_pct": round(sweep_depth, 2),
                            "suggested_entry": close_p,
                            "suggested_sl": high_p * 1.002,  # SL ngay trên đỉnh râu quét 0.2% buffer
                            "reason": f"Quét thanh khoản đỉnh ${sh_price:,.2f} với râu trên chiếm {upper_wick_ratio*100:.1f}%"
                        })
                        break  # Tránh duplicate cùng nến

            # 2. Bullish Sweep (Quét đáy thanh khoản -> Setup LONG)
            relevant_lows = [sl for sl in swing_lows if sl["index"] < i - 1 and sl["index"] >= i - 50]
            for sl in relevant_lows:
                sl_price = sl["price"]
                # Điều kiện: Low nến đâm thủng đáy cũ nhưng Close rút chân trở lại trên đáy cũ
                if low_p < sl_price and close_p > sl_price:
                    lower_wick_ratio = lower_wick / candle_range
                    if lower_wick_ratio >= self.wick_threshold:
                        sweep_depth = (sl_price - low_p) / sl_price * 100
                        sweeps.append({
                            "type": "BULLISH_SWEEP",
                            "direction": "LONG",
                            "time": ts_str,
                            "index": i,
                            "candle_close": close_p,
                            "swept_level": sl_price,
                            "wick_low": low_p,
                            "wick_ratio": round(lower_wick_ratio, 3),
                            "sweep_depth_pct": round(sweep_depth, 2),
                            "suggested_entry": close_p,
                            "suggested_sl": low_p * 0.998,  # SL ngay dưới đáy râu quét 0.2% buffer
                            "reason": f"Quét thanh khoản đáy ${sl_price:,.2f} với rút chân chiếm {lower_wick_ratio*100:.1f}%"
                        })
                        break

        return sweeps

    def detect_fvg(self, df: pd.DataFrame, lookback: int = 30) -> List[Dict[str, Any]]:
        """
        Phát hiện Fair Value Gap (FVG / Imbalance):
        - Bullish FVG: Low(i) > High(i-2) (Khoảng trống nến tăng mạnh chưa được lấp)
        - Bearish FVG: High(i) < Low(i-2) (Khoảng trống nến giảm mạnh chưa được lấp)
        """
        if df is None or len(df) < 5:
            return []

        fvgs = []
        n = len(df)
        start_idx = max(2, n - lookback)

        for i in range(start_idx, n):
            ts = df.index[i]
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            # Bullish FVG: Gap giữa High nến i-2 và Low nến i
            high_2_prev = float(df["high"].iloc[i - 2])
            low_curr = float(df["low"].iloc[i])
            close_1_prev = float(df["close"].iloc[i - 1])
            open_1_prev = float(df["open"].iloc[i - 1])

            if low_curr > high_2_prev and close_1_prev > open_1_prev:
                gap = low_curr - high_2_prev
                gap_pct = gap / close_1_prev
                if gap_pct >= self.fvg_min_pct:
                    # Kiểm tra xem các nến sau nến i đã lấp gap chưa
                    is_mitigated = False
                    for future_idx in range(i + 1, n):
                        if float(df["low"].iloc[future_idx]) <= high_2_prev:
                            is_mitigated = True
                            break

                    fvgs.append({
                        "type": "BULLISH_FVG",
                        "direction": "LONG",
                        "time": ts_str,
                        "index": i,
                        "bottom": high_2_prev,
                        "top": low_curr,
                        "mid": (high_2_prev + low_curr) / 2,
                        "gap_pct": round(gap_pct * 100, 2),
                        "mitigated": is_mitigated,
                        "reason": f"Bullish FVG vùng [${high_2_prev:,.2f} - ${low_curr:,.2f}]"
                    })

            # Bearish FVG: Gap giữa Low nến i-2 và High nến i
            low_2_prev = float(df["low"].iloc[i - 2])
            high_curr = float(df["high"].iloc[i])
            if high_curr < low_2_prev and close_1_prev < open_1_prev:
                gap = low_2_prev - high_curr
                gap_pct = gap / close_1_prev
                if gap_pct >= self.fvg_min_pct:
                    is_mitigated = False
                    for future_idx in range(i + 1, n):
                        if float(df["high"].iloc[future_idx]) >= low_2_prev:
                            is_mitigated = True
                            break

                    fvgs.append({
                        "type": "BEARISH_FVG",
                        "direction": "SHORT",
                        "time": ts_str,
                        "index": i,
                        "top": low_2_prev,
                        "bottom": high_curr,
                        "mid": (low_2_prev + high_curr) / 2,
                        "gap_pct": round(gap_pct * 100, 2),
                        "mitigated": is_mitigated,
                        "reason": f"Bearish FVG vùng [${high_curr:,.2f} - ${low_2_prev:,.2f}]"
                    })

        return fvgs

    def detect_order_blocks(self, df: pd.DataFrame, lookback: int = 30) -> List[Dict[str, Any]]:
        """
        Nhận diện Order Block (Khối lệnh tích lũy trước nhịp phá vỡ cấu trúc):
        - Bullish OB: Cây nến giảm cuối cùng trước nhịp tăng phá đỉnh (Displacement Breakout).
        - Bearish OB: Cây nến tăng cuối cùng trước nhịp giảm phá đáy.
        """
        if df is None or len(df) < 10:
            return []

        obs = []
        n = len(df)
        start_idx = max(1, n - lookback)

        for i in range(start_idx, n - 2):
            prev_row = df.iloc[i - 1]
            curr_row = df.iloc[i]
            next_row = df.iloc[i + 1]

            curr_open = float(curr_row["open"])
            curr_close = float(curr_row["close"])
            curr_high = float(curr_row["high"])
            curr_low = float(curr_row["low"])

            next_open = float(next_row["open"])
            next_close = float(next_row["close"])

            ts = df.index[i]
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            # Bullish Order Block: Nến i là nến đỏ (Close < Open), nến i+1 là nến xanh bùng nổ phá vỡ High nến i và i-1
            if curr_close < curr_open and next_close > next_open:
                displacement = (next_close - next_open) / next_open
                if next_close > curr_high and displacement >= 0.008:
                    obs.append({
                        "type": "BULLISH_OB",
                        "direction": "LONG",
                        "time": ts_str,
                        "index": i,
                        "top": curr_high,
                        "bottom": curr_low,
                        "entry_zone": (curr_high + curr_low) / 2,
                        "reason": f"Bullish Order Block [${curr_low:,.2f} - ${curr_high:,.2f}]"
                    })

            # Bearish Order Block: Nến i là nến xanh (Close > Open), nến i+1 là nến đỏ sập mạnh phá vỡ Low nến i và i-1
            elif curr_close > curr_open and next_close < next_open:
                displacement = (next_open - next_close) / next_open
                if next_close < curr_low and displacement >= 0.008:
                    obs.append({
                        "type": "BEARISH_OB",
                        "direction": "SHORT",
                        "time": ts_str,
                        "index": i,
                        "top": curr_high,
                        "bottom": curr_low,
                        "entry_zone": (curr_high + curr_low) / 2,
                        "reason": f"Bearish Order Block [${curr_low:,.2f} - ${curr_high:,.2f}]"
                    })

        return obs

    def analyze(self, df: pd.DataFrame, current_price: Optional[float] = None, trigger_lookback: int = 5) -> Dict[str, Any]:
        """
        Tổng hợp toàn bộ chỉ báo SMC trên DataFrame và trả về tín hiệu giao dịch thông minh.
        :param trigger_lookback: Số nến gần nhất để kích hoạt tín hiệu giao dịch (mặc định 5 nến).
        """
        if df is None or len(df) < 20:
            return {
                "has_signal": False,
                "direction": "NEUTRAL",
                "sweeps": [],
                "fvgs": [],
                "order_blocks": [],
                "reasons": []
            }

        price = current_price or float(df["close"].iloc[-1])
        sweeps = self.detect_liquidity_sweeps(df, lookback=40)
        fvgs = self.detect_fvg(df, lookback=35)
        obs = self.detect_order_blocks(df, lookback=35)

        # Lọc các FVG chưa bị lấp (unmitigated)
        active_fvgs = [f for f in fvgs if not f.get("mitigated", False)]
        
        # Kiểm tra xem có sweep nào xuất hiện ở trigger_lookback nến gần nhất không
        n = len(df)
        recent_sweeps = [s for s in sweeps if s["index"] >= n - trigger_lookback]

        reasons = []
        direction = "NEUTRAL"
        confidence = 0
        suggested_entry = price
        suggested_sl = None
        suggested_tp = None

        if recent_sweeps:
            latest_sweep = recent_sweeps[-1]
            direction = latest_sweep["direction"]
            suggested_entry = latest_sweep["suggested_entry"]
            suggested_sl = latest_sweep["suggested_sl"]
            reasons.append(latest_sweep["reason"])
            confidence += 4

            # Tính TP mục tiêu: TP1 = Fib hoặc FVG đối diện
            if direction == "SHORT":
                # Tìm Bullish FVG hoặc Order Block ở dưới để làm TP
                bullish_targets = [f["mid"] for f in active_fvgs if f["direction"] == "LONG" and f["mid"] < price]
                if bullish_targets:
                    suggested_tp = max(bullish_targets)
                    reasons.append(f"TP tại Bullish FVG: ${suggested_tp:,.2f}")
                else:
                    sl_dist = abs(suggested_sl - suggested_entry)
                    suggested_tp = suggested_entry - sl_dist * 2.5  # RR 1:2.5
            else:
                bearish_targets = [f["mid"] for f in active_fvgs if f["direction"] == "SHORT" and f["mid"] > price]
                if bearish_targets:
                    suggested_tp = min(bearish_targets)
                    reasons.append(f"TP tại Bearish FVG: ${suggested_tp:,.2f}")
                else:
                    sl_dist = abs(suggested_entry - suggested_sl)
                    suggested_tp = suggested_entry + sl_dist * 2.5

        # Kiểm tra giá hiện tại có đang nằm trong FVG hoặc Order Block nào không
        for ob in obs[-4:]:
            if ob["bottom"] <= price <= ob["top"]:
                reasons.append(f"Giá đang trong {ob['reason']}")
                if direction == ob["direction"]:
                    confidence += 2

        for fvg in active_fvgs[-4:]:
            if fvg["bottom"] <= price <= fvg["top"]:
                reasons.append(f"Giá chạm {fvg['reason']}")
                if direction == fvg["direction"]:
                    confidence += 2

        has_signal = direction != "NEUTRAL" and confidence >= 4

        return {
            "has_signal": has_signal,
            "direction": direction,
            "confidence": confidence,
            "price": price,
            "suggested_entry": suggested_entry,
            "suggested_sl": suggested_sl,
            "suggested_tp": suggested_tp,
            "recent_sweeps": sweeps[-5:],
            "active_fvgs": active_fvgs[-5:],
            "order_blocks": obs[-5:],
            "reasons": reasons
        }
