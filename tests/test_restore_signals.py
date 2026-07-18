import sys
import os
import asyncio
from datetime import datetime

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from execution.trade_engine import TradeEngine
from analytics.signal_tracker import SignalTracker
from analytics.technical import TechnicalAnalyzer

async def test_restore():
    print("=== Testing Restore Positions on Startup ===")
    te = TradeEngine()
    
    # Verify te loaded some positions
    print("Loaded positions in TradeEngine:", list(te.positions.keys()))
    
    st = SignalTracker(trade_engine=te)
    # Call load_active_positions
    st.load_active_positions()
    
    print("Active signals in SignalTracker after restore:", list(st.active_signals.keys()))
    
    # Assert
    active_count = len([p for p in te.positions.values() if p.get("status") in ("OPEN", "PARTIAL")])
    tracker_count = len(st.active_signals)
    print(f"Active positions in TradeEngine: {active_count}")
    print(f"Active signals in SignalTracker: {tracker_count}")
    
    assert tracker_count == active_count, "Mismatch between active positions and tracker signals!"
    print("Restore test passed successfully!")

async def test_analyze_full():
    print("\n=== Testing TechnicalAnalyzer.analyze_full ===")
    ta = TechnicalAnalyzer()
    df, signal = await ta.analyze_full("BTC/USDT", "1h")
    
    print("DataFrame empty?", df.empty)
    print("DataFrame shape:", df.shape if not df.empty else "N/A")
    print("Signal generated:", signal)
    
    assert not df.empty, "DataFrame should not be empty!"
    assert signal is not None, "Signal dict should not be None!"
    print("analyze_full test passed successfully!")

async def test_latest_prices():
    print("\n=== Testing _get_latest_prices with missing coins ===")
    from api.server import _get_latest_prices, ctx
    import api.server as server
    
    # Setup test environment
    te = TradeEngine()
    # Add a mock position in DOGE
    te.positions["MANUAL_DOGE_LONG_TEST"] = {
        "coin": "DOGE",
        "direction": "LONG",
        "status": "OPEN",
        "entry_price": 0.07,
        "sl": 0.065,
        "tp1": 0.08,
        "tp2": 0.085,
        "tp3": 0.09,
        "usdt_size": 100.0,
        "leverage": 10
    }
    
    # Inject te into api server context
    ctx["trade_engine"] = te
    
    # Clear cache to force refresh
    server._price_cache = {"prices": {}, "ts": 0}
    
    # Call _get_latest_prices
    prices = _get_latest_prices()
    
    print("Prices cache keys:", list(prices.keys()))
    assert "DOGEUSDT" in prices, "DOGEUSDT price should be fetched and merged from REST API fallback!"
    print("DOGEUSDT Price:", prices["DOGEUSDT"])
    print("_get_latest_prices test passed successfully!")

async def main():
    try:
        await test_restore()
        await test_analyze_full()
        await test_latest_prices()
        print("\nALL TESTS PASSED SUCCESSFULLY!")
    except Exception as e:
        print("\nTEST FAILED:", str(e))
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
