import sys
import os
import asyncio
import pandas as pd
from datetime import datetime

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from execution.trade_engine import TradeEngine
from analytics.signal_tracker import SignalTracker
from analytics.signal_scanner import SignalScanner

async def test_scanner_smart_levels():
    print("=== Testing SignalScanner with Smart SL/TP ===")
    te = TradeEngine()
    te.auto_trade_enabled = True
    
    st = SignalTracker(trade_engine=te)
    
    # Instantiate SignalScanner
    scanner = SignalScanner(
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        trade_engine=te,
        signal_tracker=st
    )
    
    # We will mock the scanner's _scan_loop results to simulate a signal detection
    # Let's create a mock DataFrame with indicators that triggers a LONG signal (bull_score >= 3)
    df = pd.DataFrame({
        "close": [60000.0] * 50,
        "high": [60100.0] * 50,
        "low": [59900.0] * 50,
        "open": [60000.0] * 50,
        "volume": [10.0] * 50,
        "rsi": [25.0] * 50,           # RSI < 30 (+2 points)
        "macd": [-1.0] * 48 + [-0.5, 1.0],  # MACD Golden Cross (+2 points)
        "macd_signal": [0.0] * 50,
        "atr": [500.0] * 50,          # ATR value for Smart SL/TP
        "support1": [59000.0] * 50,
        "resistance1": [61000.0] * 50,
        "ema50": [58000.0] * 50,      # Price > ema50 (Trend Filter LONG passes)
        "ema200": [57000.0] * 50,     # Price > ema200
    })
    
    # We will trigger the processing logic on this mock data
    # Let's check how rating and smart levels are calculated:
    # 1. Base signal from TechnicalAnalyzer
    from analytics.technical import TechnicalAnalyzer
    ta = TechnicalAnalyzer()
    
    signal = ta.generate_signal(df, "BTC/USDT")
    print("Generated Base Signal:", signal)
    
    assert signal is not None, "Failed to generate base signal!"
    assert signal.get("direction") == "LONG", "Signal should be LONG!"
    
    # Simulate the key processing step inside scanner._scan_loop
    key = "BTC/USDT_1h"
    coin_name = "BTC"
    tf = "1h"
    direction = signal["direction"]
    entry = signal["price"]
    sl = signal["sl"]
    tp = signal["tp"]
    
    rating = scanner.calculate_signal_rating(signal, tf, "BULLISH")
    print("Calculated Rating:", rating)
    
    # Calculate Smart Levels
    from analytics.macro_calendar import MacroCalendar
    macro = MacroCalendar()
    risk_data = await macro.assess_risk()
    macro_risk = risk_data.get("risk_level", "NORMAL")
    await macro.close()
    
    smart_levels = ta.compute_smart_levels(
        df=df,
        direction=direction,
        leverage=10,
        macro_risk=macro_risk
    )
    
    print("Computed Smart Levels:", smart_levels)
    assert "error" not in smart_levels, "Failed to compute smart levels!"
    
    smart_sl = smart_levels["sl"]
    smart_tp1 = smart_levels["tp1"]
    smart_tp2 = smart_levels["tp2"]
    smart_tp3 = smart_levels["tp3"]
    
    # Open position via signal tracker
    signal_key = f"{coin_name}_{tf}"
    if signal_key in te.positions:
        del te.positions[signal_key]
        
    st.add_signal({
        "key": signal_key,
        "coin": coin_name,
        "type": "FUTURES",
        "direction": direction,
        "entry": entry,
        "sl": smart_sl,
        "tp1": round(smart_tp1, 2),
        "tp2": round(smart_tp2, 2),
        "tp3": round(smart_tp3, 2),
        "chat_id": 12345,
        "leverage": 10,
        "rating": rating,
        "tf": tf,
    })
    
    print("\nPositions in TradeEngine after auto-trade:", te.positions.keys())
    assert signal_key in te.positions, "Position should be opened in TradeEngine!"
    
    opened_pos = te.positions[signal_key]
    print("Opened Position SL:", opened_pos["sl"])
    print("Opened Position TP1:", opened_pos["tp1"])
    print("Opened Position TP2:", opened_pos["tp2"])
    print("Opened Position TP3:", opened_pos["tp3"])
    
    assert opened_pos["sl"] == smart_sl, "Opened position SL must match smart SL!"
    assert opened_pos["tp1"] == round(smart_tp1, 2), "Opened position TP1 must match smart TP1!"
    
    print("\nSCANNER SMART LEVELS TEST PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    asyncio.run(test_scanner_smart_levels())
