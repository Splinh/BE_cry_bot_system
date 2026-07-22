import sys
import os
import asyncio
from datetime import datetime

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from execution.trade_engine import TradeEngine
from core.config import Config

async def test_circuit_breaker():
    print("=== Testing TradeEngine Circuit Breaker (Risk Guards) ===")
    te = TradeEngine()
    
    # Reset balance and daily stats for testing
    te.balance = 10000.0
    te.daily_realized_pnl = 0.0
    te.daily_start_balance = 10000.0
    te.daily_date = te._today()
    te.positions = {}
    te.auto_trade_enabled = True
    
    # Configure custom test limits
    te.max_daily_loss_usd = 200.0   # $200 limit
    te.max_daily_loss_pct = 0.02    # 2% of $10000 = $200 limit
    te.max_open_positions = 2       # Max 2 open positions
    
    # Check initial state
    assert not te.is_trading_locked(), "Trading should not be locked initially!"
    print("Initial check: trading is active.")

    # 1. Test Max Open Positions Limit
    print("\n--- Test Max Open Positions Limit ---")
    pos1 = te.open_manual_position("BTC", "LONG", 1000.0, leverage=10, current_price=60000.0)
    assert pos1 is not None, "Failed to open first position"
    print("Opened pos 1: BTC")

    pos2 = te.open_manual_position("ETH", "LONG", 1000.0, leverage=10, current_price=3000.0)
    assert pos2 is not None, "Failed to open second position"
    print("Opened pos 2: ETH")

    # This third position should be blocked by Max Open Positions guard
    pos3 = te.open_manual_position("SOL", "LONG", 1000.0, leverage=10, current_price=150.0)
    assert pos3 is None, "Should block third position due to Max Open Positions limit"
    assert "so lenh mo toi da" in te.last_error.lower(), f"Expected max positions error, got: {te.last_error}"
    print(f"Success: Third position blocked. Reason: {te.last_error}")

    # Close pos 1 to free slot
    te.close_position(pos1["key"], 60000.0, reason="MANUAL_CLOSE")
    print("Closed pos 1 to free space.")

    # 2. Test Daily Loss Circuit Breaker
    print("\n--- Test Daily Loss Circuit Breaker ---")
    # Simulate a realized loss of -$250 (limit is -$200)
    te._record_realized_pnl(-250.0)
    
    assert te.is_trading_locked(), "Trading should be locked after losing $250 (limit $200)"
    print(f"Success: Trading is locked. Current PnL: {te.daily_realized_pnl:.2f}")

    # Try opening a manual position when locked
    te.last_error = ""
    pos_locked = te.open_manual_position("BTC", "LONG", 500.0, leverage=10, current_price=60000.0)
    assert pos_locked is None, "Should not allow opening manual positions when trading is locked!"
    assert "lo/ngay" in te.last_error.lower(), f"Expected lock error, got: {te.last_error}"
    print(f"Success: Manual trade blocked during lock. Reason: {te.last_error}")

    # Try opening an automated position when locked
    pos_auto = te.open_position({
        "key": "BTC_1h",
        "coin": "BTC",
        "direction": "LONG",
        "entry": 60000.0,
        "sl": 59000.0,
        "tp": 63000.0,
        "rating": 5,
        "tf": "1h",
        "leverage": 10
    })
    assert pos_auto is None, "Should not allow opening auto positions when trading is locked!"
    print("Success: Automated trade blocked during lock.")
    
    print("\nALL CIRCUIT BREAKER TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    asyncio.run(test_circuit_breaker())
