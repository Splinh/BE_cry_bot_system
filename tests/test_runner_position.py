import sys
import os
import asyncio
import pandas as pd

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from execution.trade_engine import TradeEngine
from analytics.technical import TechnicalAnalyzer

async def test_runner_position_and_chandelier():
    print("=== Testing Runner Position & Chandelier ATR Trailing Stop ===")
    te = TradeEngine()
    te.balance = 100000.0
    te.daily_realized_pnl = 0.0
    te.daily_start_balance = 100000.0
    te.positions = {}
    te.auto_trade_enabled = True
    te.max_margin_per_trade_usd = 50000.0
    te.max_margin_per_trade_pct = 0.50
    te.max_total_margin_usd = 80000.0
    te.max_total_margin_pct = 0.80

    ta = TechnicalAnalyzer()

    # 1. Test Widened Smart SL Breathing Room
    df = pd.DataFrame({
        "close": [60000.0] * 50,
        "high": [60200.0] * 50,
        "low": [59800.0] * 50,
        "open": [60000.0] * 50,
        "volume": [10.0] * 50,
        "rsi": [25.0] * 50,
        "macd": [-1.0] * 48 + [-0.5, 1.0],
        "macd_signal": [0.0] * 50,
        "atr": [500.0] * 50,
        "support1": [59000.0] * 50,
        "resistance1": [61000.0] * 50,
        "ema50": [58000.0] * 50,
        "ema200": [57000.0] * 50,
    })

    smart_levels = ta.compute_smart_levels(df, direction="LONG", leverage=10)
    print("Widened Smart Levels (x10 leverage):", smart_levels)
    
    # Check that SL has sufficient breathing room (atr_distance = 500 * 1.8 = 900)
    sl_dist = 60000.0 - smart_levels["sl"]
    assert sl_dist >= 900.0, f"SL distance should be at least 900 (1.8x ATR), got: {sl_dist}"
    print(f"Success: SL distance is {sl_dist:.1f} ($60,000 -> ${smart_levels['sl']:.1f})")

    # 2. Test 4-Stage Partial Close & Runner Mode
    print("\n--- Test 4-Stage Partial Close & Runner Mode ---")
    pos = te.open_manual_position(
        coin="BTC",
        direction="LONG",
        usdt_size=10000.0,
        leverage=10,
        current_price=60000.0,
        smart_levels={
            "sl": 58500.0,
            "tp1": 61200.0,
            "tp2": 62500.0,
            "tp3": 64000.0,
            "atr": 500.0
        }
    )
    sig_key = pos["key"]
    assert pos["status"] == "OPEN", "Position should be OPEN initially"
    assert pos["closed_pct"] == 0.0, "Initial closed_pct should be 0.0"

    # Price moves slightly before TP1 ($60,500) -> SL should NOT be modified prematurely!
    prices_pre_tp1 = {"BTCUSDT": {"price": 60500.0}}
    te.check_sl_tp(prices_pre_tp1)
    pos_pre_tp1 = te.positions[sig_key]
    assert pos_pre_tp1["sl"] == 58500.0, f"Expected initial SL (58500) preserved before TP1, got {pos_pre_tp1['sl']}"
    print("Success: SL preserved with full breathing room before TP1.")

    # Price hits TP1 ($61,200) -> 25% closed & SL locked to Break-Even (Entry $60,000)
    prices_tp1 = {"BTCUSDT": {"price": 61250.0}}
    te.check_sl_tp(prices_tp1)
    pos_after_tp1 = te.positions[sig_key]
    assert pos_after_tp1["closed_pct"] == 0.25, f"Expected closed_pct 0.25 after TP1, got {pos_after_tp1['closed_pct']}"
    assert pos_after_tp1["sl"] == 60000.0, f"Expected SL locked to Break-Even ($60,000) after TP1, got {pos_after_tp1['sl']}"
    print("Success: TP1 hit -> 25% closed & SL locked to Break-Even ($60,000).")

    # Price hits TP2 ($62,500) -> 25% more closed (50% total) & SL locked to TP1 ($61,200)
    prices_tp2 = {"BTCUSDT": {"price": 62550.0}}
    te.check_sl_tp(prices_tp2)
    pos_after_tp2 = te.positions[sig_key]
    assert pos_after_tp2["closed_pct"] == 0.50, f"Expected closed_pct 0.50 after TP2, got {pos_after_tp2['closed_pct']}"
    assert pos_after_tp2["sl"] == 61200.0, f"Expected SL locked to TP1 ($61,200) after TP2, got {pos_after_tp2['sl']}"
    print("Success: TP2 hit -> 50% total closed, SL locked to TP1 ($61,200).")

    # Price hits TP3 ($64,000) -> 25% more closed (75% total) & Runner Mode activated
    prices_tp3 = {"BTCUSDT": {"price": 64100.0}}
    te.check_sl_tp(prices_tp3)
    pos_after_tp3 = te.positions[sig_key]
    assert pos_after_tp3["closed_pct"] == 0.75, f"Expected closed_pct 0.75 after TP3, got {pos_after_tp3['closed_pct']}"
    assert pos_after_tp3["runner_mode"] == True, "Runner mode should be active after TP3"
    print("Success: TP3 hit -> 75% total closed, Runner Mode ACTIVE!")

    # 3. Test Chandelier ATR Trailing Stop (3.5x ATR) on Runner Position
    print("\n--- Test Chandelier ATR Trailing Stop (3.5x ATR) ---")
    # Price surges to peak $68,000
    prices_surge = {"BTCUSDT": {"price": 68000.0}}
    te.check_sl_tp(prices_surge)
    pos_surge = te.positions[sig_key]
    # Chandelier SL = peak (68000) - 3.5 * ATR (500) = 66250
    expected_chandelier_sl = 68000.0 - 3.5 * 500.0
    print(f"Peak: ${pos_surge['peak_price']}, Chandelier SL: ${pos_surge['sl']}")
    assert pos_surge["sl"] == expected_chandelier_sl, f"Expected Chandelier SL {expected_chandelier_sl}, got {pos_surge['sl']}"
    print("Success: Chandelier ATR Trail raised SL to peak - 3.5*ATR.")

    # Price drops below Chandelier SL ($66,200 < $66,250) -> Runner Position Closes
    prices_drop = {"BTCUSDT": {"price": 66200.0}}
    closed = te.check_sl_tp(prices_drop)
    assert te.positions[sig_key]["status"] == "CLOSED", "Runner position should be CLOSED when hitting Chandelier SL"
    print("Success: Runner Position closed at Chandelier SL after riding $60,000 -> $68,000 swing move!")

    # 4. Test Position Sizing Normalization
    print("\n--- Test Position Sizing Normalization ---")
    # Test with standard 10% max margin per trade
    te.max_margin_per_trade_pct = 0.10
    te.max_margin_per_trade_usd = 10000.0

    # Test very close SL (e.g. SL only 0.2% away: 60000 -> 59880)
    size_close_sl = te.calculate_position_size(entry_price=60000.0, stop_loss=59880.0, leverage=10)
    margin_close_sl = size_close_sl / 10
    print(f"Close SL (0.2%): Size = ${size_close_sl:,.2f}, Margin = ${margin_close_sl:,.2f}")
    assert margin_close_sl <= te.balance * 0.10 + 1e-5, f"Margin should not exceed 10% of balance, got {margin_close_sl}"

    # Test wider SL (e.g. SL 3% away: 60000 -> 58200)
    size_wide_sl = te.calculate_position_size(entry_price=60000.0, stop_loss=58200.0, leverage=10)
    margin_wide_sl = size_wide_sl / 10
    print(f"Wide SL (3.0%): Size = ${size_wide_sl:,.2f}, Margin = ${margin_wide_sl:,.2f}")
    assert margin_wide_sl >= te.balance * 0.03 - 1e-5, f"Margin should be at least 3% of balance, got {margin_wide_sl}"
    print("Success: Position sizing is well balanced across tight and wide stop losses.")

    print("\nALL RUNNER POSITION AND CHANDELIER TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    asyncio.run(test_runner_position_and_chandelier())
