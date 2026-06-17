import sys
sys.path.append('.')
from data.database import db

games = [
    {
        "name": "DungeonCROSS",
        "symbol": "CROSS",
        "chain": "CROSS",
        "token_price": 0.062,
        "nft_floor_price": 15.0,
        "daily_roi_estimate": 1.5,
        "onchain_users_24h": 15000,
        "note": "Web3 MMORPG - 2 cach EARN (Free hoac Nap)"
    },
    {
        "name": "SEAL M",
        "symbol": "CROSS",
        "chain": "CROSS",
        "token_price": 0.062,
        "nft_floor_price": 0.0,
        "daily_roi_estimate": 2.0,
        "onchain_users_24h": 50000,
        "note": "Co hoi share 1 trieu $CROSS (03/2026)"
    },
    {
        "name": "Sunflower Land",
        "symbol": "SFL",
        "chain": "Polygon",
        "token_price": 0.060,
        "nft_floor_price": 10.0,
        "daily_roi_estimate": 0.5,
        "onchain_users_24h": 20000,
        "note": "Cap nhat nhieu thay doi moi nhat (03/05/2026)"
    }
]

for g in games:
    try:
        db.add_gamefi_project(**g)
        print(f"Added {g['name']}")
    except Exception as e:
        print(f"Failed to add {g['name']}: {str(e)}")
