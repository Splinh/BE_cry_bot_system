import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

from execution.trade_engine import TradeEngine

def run_test():
    print("=== Starting Conflict & Reversal Logic Tests ===")
    
    # Initialize TradeEngine
    engine = TradeEngine()
    engine.auto_trade_enabled = True
    
    # Reset balance for clean test
    engine.balance = 10000.0
    engine.positions = {}
    engine.history = []
    
    # 1. Test Correlated Cross-Asset protection
    # Open SHORT BTC (1h, 3 stars)
    print("\n1. Opening initial SHORT BTC (1h, 3 stars) position...")
    btc_signal = {
        "key": "BTC_1h_initial",
        "coin": "BTC",
        "type": "FUTURES",
        "direction": "SHORT",
        "entry": 60000.0,
        "sl": 61000.0,
        "tp1": 59000.0,
        "leverage": 10,
        "rating": 3,
        "tf": "1h"
    }
    pos_btc = engine.open_position(btc_signal)
    if pos_btc:
        print(f"   Opened BTC Position. Size: ${pos_btc['usdt_size']:.2f}, Margin: ${pos_btc['margin']:.2f}, SL: ${pos_btc['sl']:.2f}")
    else:
        print("   Failed to open BTC Position.")

    # Open SHORT SOL (1h, 3 stars)
    print("\n2. Opening initial SHORT SOL (1h, 3 stars) position...")
    sol_signal = {
        "key": "SOL_1h_initial",
        "coin": "SOL",
        "type": "FUTURES",
        "direction": "SHORT",
        "entry": 80.0,
        "sl": 82.0,
        "tp1": 78.0,
        "leverage": 10,
        "rating": 3,
        "tf": "1h"
    }
    pos_sol = engine.open_position(sol_signal)
    if pos_sol:
        print(f"   Opened SOL Position. Size: ${pos_sol['usdt_size']:.2f}, Margin: ${pos_sol['margin']:.2f}, SL: ${pos_sol['sl']:.2f}")
    else:
        print("   Failed to open SOL Position.")

    # Trigger LONG ETH (4h, 4 stars) - Strong counter-trend signal on correlated asset
    print("\n3. Triggering LONG ETH (4h, 4 stars) signal...")
    eth_signal = {
        "key": "ETH_4h_strong",
        "coin": "ETH",
        "type": "FUTURES",
        "direction": "LONG",
        "entry": 1800.0,
        "sl": 1750.0,
        "tp1": 1850.0,
        "leverage": 10,
        "rating": 4,
        "tf": "4h"
    }
    
    # Run open_position which should trigger protection on BTC and SOL
    pos_eth = engine.open_position(eth_signal)
    if pos_eth:
        print(f"   Opened ETH Position. Size: ${pos_eth['usdt_size']:.2f}, Margin: ${pos_eth['margin']:.2f}")
    else:
        print("   Failed to open ETH Position.")

    # Verify BTC and SOL positions
    btc_pos = engine.positions.get("BTC_1h_initial")
    sol_pos = engine.positions.get("SOL_1h_initial")
    
    print("\n--- Verification of Cross-Asset Protection ---")
    if btc_pos:
        print(f"   BTC SL: ${btc_pos['sl']:.2f} (Expected: Entry price 60000.0)")
        print(f"   BTC Closed Pct: {btc_pos['closed_pct']*100:.1f}% (Expected: 50.0%)")
        assert btc_pos['sl'] == 60000.0, "BTC SL did not move to entry!"
        assert btc_pos['closed_pct'] == 0.5, "BTC was not partially closed by 50%!"
    else:
        print("   Error: BTC position not found!")
        
    if sol_pos:
        print(f"   SOL SL: ${sol_pos['sl']:.2f} (Expected: Entry price 80.0)")
        print(f"   SOL Closed Pct: {sol_pos['closed_pct']*100:.1f}% (Expected: 50.0%)")
        assert sol_pos['sl'] == 80.0, "SOL SL did not move to entry!"
        assert sol_pos['closed_pct'] == 0.5, "SOL was not partially closed by 50%!"
    else:
        print("   Error: SOL position not found!")

    print("   => Cross-Asset Protection test: PASSED")

    # 2. Test Direct Same-Asset Reversal
    print("\n4. Triggering SHORT ETH (1h, 3 stars) signal while LONG ETH is open...")
    # This should be ignored because of lower rating (3 < 4) and smaller timeframe (1h < 4h)
    eth_weak_short = {
        "key": "ETH_1h_weak_short",
        "coin": "ETH",
        "type": "FUTURES",
        "direction": "SHORT",
        "entry": 1810.0,
        "sl": 1850.0,
        "tp1": 1780.0,
        "leverage": 10,
        "rating": 3,
        "tf": "1h"
    }
    pos_eth_ignored = engine.open_position(eth_weak_short)
    if pos_eth_ignored is None:
        print("   Correctly ignored weak contrary signal on ETH.")
    else:
        print("   Error: Weak contrary signal was NOT ignored!")
        
    print("\n5. Triggering SHORT ETH (4h, 4 stars) signal while LONG ETH is open...")
    # This should trigger reversal: Close LONG ETH, Open SHORT ETH
    eth_strong_short = {
        "key": "ETH_4h_strong_short",
        "coin": "ETH",
        "type": "FUTURES",
        "direction": "SHORT",
        "entry": 1810.0,
        "sl": 1850.0,
        "tp1": 1780.0,
        "leverage": 10,
        "rating": 4,
        "tf": "4h"
    }
    pos_eth_short = engine.open_position(eth_strong_short)
    
    print("\n--- Verification of Direct Reversal ---")
    old_eth_pos = engine.positions.get("ETH_4h_strong")
    new_eth_pos = engine.positions.get("ETH_4h_strong_short")
    
    if old_eth_pos:
        print(f"   Old ETH Status: {old_eth_pos['status']} (Expected: CLOSED)")
        print(f"   Old ETH Close Reason: {old_eth_pos.get('close_reason')} (Expected: REVERSAL_SIGNAL)")
        assert old_eth_pos['status'] == "CLOSED", "Old ETH position was not closed!"
        assert old_eth_pos.get('close_reason') == "REVERSAL_SIGNAL", "Old ETH close reason is not REVERSAL_SIGNAL!"
    else:
        print("   Old ETH position not found in positions dict.")

    if new_eth_pos:
        print(f"   New ETH Direction: {new_eth_pos['direction']} (Expected: SHORT)")
        assert new_eth_pos['direction'] == "SHORT", "New ETH position is not SHORT!"
    else:
        print("   Error: New ETH position was not opened!")
        
    print("   => Direct Same-Asset Reversal test: PASSED")
    print("\n=== All Tests Passed Successfully! ===")

if __name__ == "__main__":
    run_test()
