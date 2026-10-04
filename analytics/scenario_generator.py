"""
Scenario Generator Module - Tự động Phân tích Kỹ thuật và Lên Kịch bản Chiến lược.
Áp dụng cho các tài sản chính: BTC, ETH, VÀNG (PAXG / XAU).
Phương pháp: Phân tích Cấu trúc Thị trường, Swing High/Low, Pivot Points, Fibonacci & ATR.
"""
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import pandas as pd

from analytics.technical import TechnicalAnalyzer

# Mapping biểu tượng chuẩn
SYMBOL_MAP = {
    "BTC": "BTC/USDT",
    "ETH": "ETH/USDT",
    "PAXG": "PAXG/USDT",
    "GOLD": "PAXG/USDT",
    "VANG": "PAXG/USDT",
    "XAU": "PAXG/USDT",
}

# Bước giá cảnh báo mặc định theo tài sản
DEFAULT_STEPS = {
    "BTC": 100.0,
    "ETH": 10.0,
    "PAXG": 5.0,
    "GOLD": 5.0,
}


class ScenarioGenerator:
    """
    Tự động phân tích dữ liệu nến kỹ thuật để xây dựng Kịch bản Chiến lược (Trading Scenarios)
    cho 2 chiều: Canh Short tại Cản và Canh Long tại Hỗ trợ.
    """

    def __init__(self, technical_analyzer: Optional[TechnicalAnalyzer] = None):
        self.analyzer = technical_analyzer or TechnicalAnalyzer()

    async def analyze_and_create_scenario(self, coin_symbol: str) -> Dict[str, dict]:
        """
        Phân tích 1 đồng coin/tài sản và tạo 2 kịch bản (1 Short cản trên, 1 Long hỗ trợ dưới).
        """
        coin_clean = coin_symbol.upper().replace("/USDT", "").replace("USDT", "")
        pair = SYMBOL_MAP.get(coin_clean, f"{coin_clean}/USDT")
        target_name = "VÀNG (PAXG)" if coin_clean in ("PAXG", "GOLD", "VANG", "XAU") else coin_clean

        # Lấy dữ liệu 50 nến 1h
        df = await self.analyzer.get_ohlcv(pair, timeframe="1h", limit=50)
        if df.empty or len(df) < 20:
            logger.error(f"Không đủ dữ liệu nến để phân tích kịch bản cho {pair}")
            return {}

        df = self.analyzer.calculate_indicators(df)
        latest = df.iloc[-1]
        current_price = float(latest["close"])

        atr = float(latest.get("atr", current_price * 0.015))
        if pd.isna(atr) or atr <= 0:
            atr = current_price * 0.015

        # Tính toán Swing High/Low trong 30 nến gần nhất
        recent_30 = df.tail(30)
        swing_high = float(recent_30["high"].max())
        swing_low = float(recent_30["low"].min())

        # Pivot Points
        pivot = float(latest.get("pivot", (latest["high"] + latest["low"] + latest["close"]) / 3))
        r1 = float(latest.get("resistance1", 2 * pivot - latest["low"]))
        r2 = float(latest.get("resistance2", pivot + (latest["high"] - latest["low"])))
        s1 = float(latest.get("support1", 2 * pivot - latest["high"]))
        s2 = float(latest.get("support2", pivot - (latest["high"] - latest["low"])))

        # Bollinger Bands & EMA
        bb_upper = float(latest.get("bb_upper", current_price + 2 * atr))
        bb_lower = float(latest.get("bb_lower", current_price - 2 * atr))
        ema50 = float(latest.get("ema50", current_price))

        step = DEFAULT_STEPS.get(coin_clean, max(round(current_price * 0.002, 2), 1.0))
        date_str = datetime.now().strftime("%b%d").upper()

        scenarios = {}

        # ==========================================
        # 1. KỊCH BẢN SHORT: CANH CẢN KHÁNG CỰ TRÊN
        # ==========================================
        # Chọn mức cản cao hơn giá hiện tại ít nhất 0.5% (đối với Vàng) hoặc 0.8% (đối với BTC/ETH)
        min_distance_pct = 0.004 if coin_clean in ("PAXG", "GOLD", "VANG", "XAU") else 0.007
        min_short_price = current_price * (1 + min_distance_pct)

        # Lựa chọn mức cản hợp lý: max của swing_high, r1, r2, bb_upper
        short_candidates = [p for p in [r1, r2, swing_high, bb_upper] if p >= min_short_price]
        if short_candidates:
            # Chọn cản gần nhất nhưng đủ an toàn
            trigger_short = min(short_candidates)
        else:
            # Nếu giá đang sát đỉnh mọi thời đại/nến, đặt cản cách 1.0% - 1.5%
            trigger_short = current_price * 1.012

        # Làm tròn giá theo đặc thù coin
        trigger_short = round(trigger_short, 0 if coin_clean == "BTC" else (1 if coin_clean in ("ETH", "PAXG") else 2))

        # Cảnh báo sớm: cách trigger khoảng 50% quãng đường từ giá hiện tại lên trigger
        early_short = current_price + (trigger_short - current_price) * 0.45
        early_short = round(early_short, 0 if coin_clean == "BTC" else (1 if coin_clean in ("ETH", "PAXG") else 2))

        # Stop Loss: Đặt trên trigger + 1.2 * ATR
        sl_short = round(trigger_short + 1.2 * atr, 0 if coin_clean == "BTC" else (1 if coin_clean in ("ETH", "PAXG") else 2))
        
        # Take Profit:
        # TP1: Về vùng pivot hoặc EMA50
        tp1_short = round(max(current_price * 0.995, pivot), 0 if coin_clean == "BTC" else 1)
        if tp1_short >= trigger_short:
            tp1_short = round(trigger_short - 1.0 * atr, 0 if coin_clean == "BTC" else 1)
        # TP2: Về vùng hỗ trợ s1 hoặc đáy cũ
        tp2_short = round(min(s1, trigger_short - 2.0 * atr), 0 if coin_clean == "BTC" else 1)
        tp3_short = round(tp2_short - 1.5 * atr, 0 if coin_clean == "BTC" else 1)

        short_id = f"{coin_clean}_SHORT_{date_str}"
        scenarios[short_id] = {
            "id": short_id,
            "coin": coin_clean,
            "target_name": target_name,
            "direction": "SHORT",
            "trigger_price": float(trigger_short),
            "early_warning_price": float(early_short),
            "alert_step": float(step),
            "last_alert_price": 0.0,
            "last_alert_time": 0.0,
            "alert_count": 0,
            "sl": float(sl_short),
            "tp1": float(tp1_short),
            "tp2": float(tp2_short),
            "tp3": float(tp3_short),
            "leverage": 10 if coin_clean != "PAXG" else 20,
            "auto_trade": True,
            "status": "ACTIVE",
            "description": f"Canh Short {target_name} tại cản kháng cự/Swing High {trigger_short:,.1f}$ khi chạm vùng quá mua hoặc rút râu đảo chiều.",
            "created_at": datetime.now().isoformat()
        }

        # ==========================================
        # 2. KỊCH BẢN LONG: CANH HỖ TRỢ BÊN DƯỚI
        # ==========================================
        max_long_price = current_price * (1 - min_distance_pct)
        long_candidates = [p for p in [s1, s2, swing_low, bb_lower] if p <= max_long_price]
        if long_candidates:
            trigger_long = max(long_candidates)
        else:
            trigger_long = current_price * 0.988

        trigger_long = round(trigger_long, 0 if coin_clean == "BTC" else (1 if coin_clean in ("ETH", "PAXG") else 2))

        # Cảnh báo sớm: cách trigger khoảng 50% quãng đường từ giá hiện tại xuống trigger
        early_long = current_price - (current_price - trigger_long) * 0.45
        early_long = round(early_long, 0 if coin_clean == "BTC" else (1 if coin_clean in ("ETH", "PAXG") else 2))

        # Stop Loss: Đặt dưới trigger - 1.2 * ATR
        sl_long = round(trigger_long - 1.2 * atr, 0 if coin_clean == "BTC" else (1 if coin_clean in ("ETH", "PAXG") else 2))

        # Take Profit:
        tp1_long = round(min(current_price * 1.005, pivot), 0 if coin_clean == "BTC" else 1)
        if tp1_long <= trigger_long:
            tp1_long = round(trigger_long + 1.0 * atr, 0 if coin_clean == "BTC" else 1)
        tp2_long = round(max(r1, trigger_long + 2.0 * atr), 0 if coin_clean == "BTC" else 1)
        tp3_long = round(tp2_long + 1.5 * atr, 0 if coin_clean == "BTC" else 1)

        long_id = f"{coin_clean}_LONG_{date_str}"
        scenarios[long_id] = {
            "id": long_id,
            "coin": coin_clean,
            "target_name": target_name,
            "direction": "LONG",
            "trigger_price": float(trigger_long),
            "early_warning_price": float(early_long),
            "alert_step": float(step),
            "last_alert_price": 0.0,
            "last_alert_time": 0.0,
            "alert_count": 0,
            "sl": float(sl_long),
            "tp1": float(tp1_long),
            "tp2": float(tp2_long),
            "tp3": float(tp3_long),
            "leverage": 10 if coin_clean != "PAXG" else 20,
            "auto_trade": True,
            "status": "ACTIVE",
            "description": f"Canh Scalp Long {target_name} tại vùng hỗ trợ/Swing Low {trigger_long:,.1f}$ khi giá quét thanh khoản đáy và rút chân.",
            "created_at": datetime.now().isoformat()
        }

        return scenarios

    async def generate_all(self, coins: List[str] = None) -> Dict[str, dict]:
        """Tự động phân tích và tạo kịch bản cho toàn bộ danh sách coin (mặc định BTC, ETH, VÀNG)."""
        coins = coins or ["BTC", "ETH", "PAXG"]
        all_scenarios = {}
        for coin in coins:
            try:
                res = await self.analyze_and_create_scenario(coin)
                all_scenarios.update(res)
            except Exception as e:
                logger.error(f"Lỗi tạo kịch bản cho {coin}: {e}")
        return all_scenarios
