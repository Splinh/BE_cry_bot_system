from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from data.database import db

router = APIRouter(prefix="/api/gamefi", tags=["GameFi"])

# ============================================
#  GAMEFI KNOWLEDGE BASE
#  Chi tiet ve tung game: cach choi, link, platform, earning model
# ============================================

GAMEFI_DATABASE = {
    "AXS": {
        "floor": 15.0, "roi": 1.5, "chain": "Ronin",
        "note": "Axie Infinity - Game nhập vai thẻ bài",
        "category": "Card Battle / Turn-based RPG",
        "platform": ["PC", "Mobile (Android/iOS)"],
        "earn_model": "Play-to-Earn (PvP Arena + Adventure)",
        "website": "https://axieinfinity.com",
        "play_url": "https://app.axieinfinity.com",
        "marketplace_url": "https://app.axieinfinity.com/marketplace",
        "how_to_earn": [
            "Mua 3 Axie NFT để bắt đầu (hoặc chơi Free trial)",
            "Chiến đấu PvP Arena → kiếm AXS + SLP",
            "Farm Adventure mode → kiếm SLP (Smooth Love Potion)",
            "Breed Axie → bán NFT trên Marketplace",
            "Stake AXS → nhận reward APY ~20-40%",
        ],
        "min_investment": "$15-50 (3 Axie cơ bản) hoặc $0 (Free trial)",
        "risk_level": "MEDIUM",
        "status": "active",
    },
    "SAND": {
        "floor": 50.0, "roi": 2.0, "chain": "ETH",
        "note": "The Sandbox - Metaverse & Đất ảo",
        "category": "Metaverse / Voxel World Builder",
        "platform": ["PC (Windows/Mac)", "Web Browser"],
        "earn_model": "Create-to-Earn + Land Ownership",
        "website": "https://www.sandbox.game",
        "play_url": "https://www.sandbox.game/en/map",
        "marketplace_url": "https://www.sandbox.game/en/shop",
        "how_to_earn": [
            "Mua LAND NFT → cho thuê hoặc tổ chức event",
            "Tạo game/experience bằng Game Maker (miễn phí) → kiếm SAND từ lượt chơi",
            "Tạo ASSET (vật phẩm 3D voxel) → bán trên Marketplace",
            "Tham gia Alpha Season → hoàn thành quest kiếm SAND + NFT",
            "Stake SAND → nhận reward",
        ],
        "min_investment": "$0 (tạo game miễn phí) hoặc ~$500+ (mua LAND)",
        "risk_level": "HIGH",
        "status": "active",
    },
    "MANA": {
        "floor": 30.0, "roi": 1.0, "chain": "ETH",
        "note": "Decentraland - Thế giới ảo 3D",
        "category": "Metaverse / Social Virtual World",
        "platform": ["Web Browser", "Desktop App"],
        "earn_model": "Create-to-Earn + Land & Wearable",
        "website": "https://decentraland.org",
        "play_url": "https://play.decentraland.org",
        "marketplace_url": "https://market.decentraland.org",
        "how_to_earn": [
            "Mua LAND → xây dựng scene → thu phí tham quan/event",
            "Tạo Wearables (quần áo avatar) → bán trên Marketplace",
            "Tham gia các event/game trong Decentraland → kiếm MANA/POAP",
            "Tổ chức event cho brand → nhận commission",
            "DAO Governance → vote và nhận reward",
        ],
        "min_investment": "$0 (khám phá miễn phí) hoặc ~$1000+ (LAND)",
        "risk_level": "HIGH",
        "status": "active",
    },
    "GALA": {
        "floor": 100.0, "roi": 3.0, "chain": "GALA",
        "note": "Gala Games - Nền tảng game blockchain đa thể loại",
        "category": "Gaming Platform / Multi-game Ecosystem",
        "platform": ["PC", "Mobile", "Web"],
        "earn_model": "Play-to-Earn + Node Operation",
        "website": "https://gala.com",
        "play_url": "https://gala.com/games",
        "marketplace_url": "https://gala.com/marketplace",
        "how_to_earn": [
            "Chạy Gala Node → kiếm GALA hàng ngày (cần mua Node License)",
            "Chơi các game: Town Star (farm), Spider Tanks (PvP), Mirandus (RPG)",
            "Mua NFT in-game → trade trên Marketplace",
            "Tham gia seasonal event → kiếm reward",
            "Stake GALA → nhận APY",
        ],
        "min_investment": "$0 (free-to-play games) hoặc ~$100 (Node License)",
        "risk_level": "MEDIUM",
        "status": "active",
    },
    "IMX": {
        "floor": 20.0, "roi": 0.8, "chain": "IMX",
        "note": "Immutable X - L2 cho NFT Gaming",
        "category": "Layer 2 / NFT Trading Platform",
        "platform": ["Web", "PC"],
        "earn_model": "Trade-to-Earn + Staking",
        "website": "https://www.immutable.com",
        "play_url": "https://www.immutable.com/games",
        "marketplace_url": "https://market.immutable.com",
        "how_to_earn": [
            "Trade NFT trên Immutable Marketplace (0% gas fee)",
            "Chơi Gods Unchained (card game) → kiếm GODS token + card NFT",
            "Chơi Guild of Guardians (mobile RPG) → kiếm NFT",
            "Stake IMX → nhận reward",
            "Cung cấp liquidity → farming yield",
        ],
        "min_investment": "$0 (Gods Unchained F2P) hoặc $10-50 (mua card pack)",
        "risk_level": "LOW",
        "status": "active",
    },
    "FLOKI": {
        "floor": 15.0, "roi": 0.5, "chain": "BSC",
        "note": "Valhalla - Viking MMORPG by Floki",
        "category": "MMORPG / Metaverse",
        "platform": ["PC (Unreal Engine)", "Mobile (dự kiến)"],
        "earn_model": "Play-to-Earn + NFT Trading",
        "website": "https://floki.com",
        "play_url": "https://valhalla.floki.com",
        "marketplace_url": "https://floki.com/nft",
        "how_to_earn": [
            "Chơi Valhalla MMORPG → kiếm in-game token",
            "Farm NFT vật phẩm/hero → bán trên marketplace",
            "Tham gia PvP/Guild War → reward ranking",
            "Stake FLOKI → nhận passive income",
            "FlokiFi Locker → cung cấp dịch vụ lock liquidity",
        ],
        "min_investment": "$0 (F2P) hoặc $15+ (mua NFT hero)",
        "risk_level": "HIGH",
        "status": "beta",
    },
    "BEAT": {
        "floor": 25.0, "roi": 1.2, "chain": "SOL",
        "note": "Audiera - Tap-to-Earn thế hệ mới",
        "category": "Tap-to-Earn / Music Game",
        "platform": ["Mobile (Telegram Mini App)", "Web"],
        "earn_model": "Tap-to-Earn + Social Task",
        "website": "https://audiera.io",
        "play_url": "https://t.me/AudieraBot",
        "marketplace_url": "",
        "how_to_earn": [
            "Mở Telegram Bot → tap kiếm token BEAT hàng ngày",
            "Hoàn thành daily tasks (follow Twitter, join group...)",
            "Mời bạn bè → nhận referral bonus",
            "Nâng cấp mining power → tăng thu nhập/h",
            "Chờ TGE (Token Generation Event) → bán token trên sàn",
        ],
        "min_investment": "$0 (hoàn toàn miễn phí)",
        "risk_level": "LOW",
        "status": "active",
    },
    "SFL": {
        "floor": 10.0, "roi": 0.5, "chain": "Polygon",
        "note": "Sunflower Land - Nông trại mô phỏng Web3",
        "category": "Farming Simulation / Social",
        "platform": ["Web Browser", "Mobile (PWA)"],
        "earn_model": "Play-to-Earn (Farming + Crafting)",
        "website": "https://sunflower-land.com",
        "play_url": "https://sunflower-land.com/play",
        "marketplace_url": "https://opensea.io/collection/sunflower-land",
        "how_to_earn": [
            "Trồng rau/hoa → harvest → bán lấy SFL token",
            "Craft vật phẩm/công cụ → trade với NPC hoặc player",
            "Thu thập resource hiếm → bán NFT trên OpenSea",
            "Tham gia seasonal event → kiếm limited NFT",
            "Farm expansion → tăng thu nhập hàng ngày",
        ],
        "min_investment": "$0 (free mint farm NFT trên Polygon)",
        "risk_level": "LOW",
        "status": "active",
    },
    "CROSS": {
        "floor": 15.0, "roi": 1.5, "chain": "CROSS",
        "note": "Seal M / DungeonCROSS - MMORPG Blockchain",
        "category": "MMORPG / Action RPG",
        "platform": ["PC", "Mobile (Android/iOS)"],
        "earn_model": "Play-to-Earn (Farm + PvP + Boss)",
        "website": "https://crossverse.io",
        "play_url": "https://dungeoncross.io",
        "marketplace_url": "https://marketplace.crossverse.io",
        "how_to_earn": [
            "Farm mob/boss → drop item NFT → bán trên marketplace",
            "PvP Arena ranking → reward CROSS token hàng tuần",
            "Craft equipment → bán cho player khác",
            "Tham gia Guild War → chia reward pool",
            "Seal M airdrop: chơi để share pool 1 triệu $CROSS",
        ],
        "min_investment": "$0 (F2P) hoặc $15-50 (mua equipment NFT để farm nhanh hơn)",
        "risk_level": "MEDIUM",
        "status": "active",
    },
    "GOMINING": {
        "floor": 50.0, "roi": 0.8, "chain": "ETH",
        "note": "GoMining - Bitcoin Mining NFT",
        "category": "Mining Simulation / DeFi",
        "platform": ["Web App", "Mobile"],
        "earn_model": "NFT Mining (hashrate ảo → BTC thật)",
        "website": "https://gomining.com",
        "play_url": "https://app.gomining.com",
        "marketplace_url": "https://app.gomining.com/nft",
        "how_to_earn": [
            "Mua NFT Miner → cung cấp hashrate ảo",
            "NFT mine BTC thật hàng ngày (dựa trên hashrate)",
            "Nâng cấp NFT → tăng hashrate → tăng thu nhập",
            "Trade NFT Miner trên marketplace",
            "Stake GOMINING → boost mining power",
        ],
        "min_investment": "$50-200 (mua NFT Miner cơ bản)",
        "risk_level": "MEDIUM",
        "status": "active",
    },
    "APE": {
        "floor": 80.0, "roi": 0.3, "chain": "ETH",
        "note": "ApeCoin - Bored Ape Yacht Club ecosystem",
        "category": "Metaverse / Community Token",
        "platform": ["Web", "PC (Otherside)"],
        "earn_model": "Staking + Metaverse (Otherside)",
        "website": "https://apecoin.com",
        "play_url": "https://otherside.xyz",
        "marketplace_url": "https://opensea.io/collection/boredapeyachtclub",
        "how_to_earn": [
            "Stake APE → nhận APY reward",
            "Mua Otherdeed LAND NFT → chờ Otherside metaverse launch",
            "Hold BAYC/MAYC NFT → nhận airdrop + exclusive access",
            "Participate DAO governance → nhận incentive",
            "Trade NFT collection → profit flip",
        ],
        "min_investment": "$0 (stake APE) hoặc $500+ (Otherdeed NFT)",
        "risk_level": "HIGH",
        "status": "active",
    },
}


@router.get("/scan")
async def scan_gamefi_tokens():
    """
    Quet cac token GameFi dang thinh hanh hoac co von hoa lon tu Coingecko.
    Tich hop tinh toan tu dong uoc luong ROI & NFT Floor + rich metadata.
    """
    import httpx
    
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "category": "gaming",
        "order": "market_cap_desc",
        "per_page": 15,
        "page": 1,
        "sparkline": "false"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    def _add_estimates(token):
        symbol = token["symbol"].upper()
        price = token["price"]
        rank = token["rank"]
        
        if symbol in GAMEFI_DATABASE:
            est = GAMEFI_DATABASE[symbol]
            token["nft_floor_price"] = est["floor"]
            token["daily_roi_estimate"] = est["roi"]
            token["chain"] = est["chain"]
            token["note"] = est["note"]
            token["category"] = est.get("category", "")
            token["platform"] = est.get("platform", [])
            token["earn_model"] = est.get("earn_model", "")
            token["website"] = est.get("website", "")
            token["play_url"] = est.get("play_url", "")
            token["marketplace_url"] = est.get("marketplace_url", "")
            token["how_to_earn"] = est.get("how_to_earn", [])
            token["min_investment"] = est.get("min_investment", "")
            token["risk_level"] = est.get("risk_level", "MEDIUM")
            token["status"] = est.get("status", "unknown")
        else:
            # Uoc luong cho game chua co trong DB
            floor = max(10.0, round(price * 200, 2))
            roi = round(floor * 0.02, 2)
            token["nft_floor_price"] = floor
            token["daily_roi_estimate"] = roi
            token["chain"] = "Unknown"
            token["note"] = f"Quét tự động từ CoinGecko (Hạng #{rank})"
            token["category"] = "GameFi / Unknown"
            token["platform"] = []
            token["earn_model"] = "Chưa xác định"
            token["website"] = ""
            token["play_url"] = ""
            token["marketplace_url"] = ""
            token["how_to_earn"] = ["⚠ Chưa có thông tin chi tiết — cần research thêm"]
            token["min_investment"] = "Chưa rõ"
            token["risk_level"] = "HIGH"
            token["status"] = "unknown"
        return token
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                result = []
                for item in data:
                    token = {
                        "name": item.get("name", ""),
                        "symbol": item.get("symbol", "").upper(),
                        "price": float(item.get("current_price") or 0),
                        "image": item.get("image", ""),
                        "price_change_24h": float(item.get("price_change_percentage_24h") or 0),
                        "volume_24h": float(item.get("total_volume") or 0),
                        "rank": int(item.get("market_cap_rank") or 999),
                    }
                    result.append(_add_estimates(token))
                return {"success": True, "tokens": result, "source": "coingecko"}
    except Exception as e:
        from loguru import logger
        logger.warning(f"Coingecko GameFi scan failed: {e}. Using offline fallback.")
        
    # Offline Fallback
    fallback_tokens = [
        {"name": "Audiera", "symbol": "BEAT", "price": 1.68, "image": "", "price_change_24h": 2.45, "volume_24h": 62320190, "rank": 107},
        {"name": "The9bit", "symbol": "9BIT", "price": 0.042, "image": "", "price_change_24h": -1.15, "volume_24h": 8332205, "rank": 128},
        {"name": "FLOKI", "symbol": "FLOKI", "price": 0.000185, "image": "", "price_change_24h": 5.23, "volume_24h": 42985428, "rank": 143},
        {"name": "Axie Infinity", "symbol": "AXS", "price": 0.94, "image": "", "price_change_24h": -0.85, "volume_24h": 20109374, "rank": 191},
        {"name": "The Sandbox", "symbol": "SAND", "price": 0.051, "image": "", "price_change_24h": 1.25, "volume_24h": 13878706, "rank": 218},
        {"name": "ApeCoin", "symbol": "APE", "price": 0.128, "image": "", "price_change_24h": -3.42, "volume_24h": 23349897, "rank": 224},
        {"name": "Decentraland", "symbol": "MANA", "price": 0.066, "image": "", "price_change_24h": 0.45, "volume_24h": 10951410, "rank": 225},
        {"name": "GALA", "symbol": "GALA", "price": 0.0025, "image": "", "price_change_24h": -1.82, "volume_24h": 19562655, "rank": 228},
        {"name": "Immutable", "symbol": "IMX", "price": 0.14, "image": "", "price_change_24h": 4.12, "volume_24h": 7748313, "rank": 237},
        {"name": "GoMining Token", "symbol": "GOMINING", "price": 0.269, "image": "", "price_change_24h": -0.52, "volume_24h": 11351559, "rank": 254},
        {"name": "Sunflower Land", "symbol": "SFL", "price": 0.06, "image": "", "price_change_24h": 1.05, "volume_24h": 42000, "rank": 1205},
        {"name": "Seal M", "symbol": "CROSS", "price": 0.062, "image": "", "price_change_24h": 0.0, "volume_24h": 250000, "rank": 1500}
    ]
    result = [_add_estimates(t) for t in fallback_tokens]
    return {"success": True, "tokens": result, "source": "offline_fallback"}


# Token detail endpoint
@router.get("/detail/{symbol}")
async def get_gamefi_detail(symbol: str):
    """Lay thong tin chi tiet ve 1 game (cach choi, link, ROI...)."""
    sym = symbol.upper()
    if sym in GAMEFI_DATABASE:
        info = GAMEFI_DATABASE[sym]
        return {"success": True, "symbol": sym, "info": info}
    return {"success": False, "error": f"Không tìm thấy thông tin chi tiết cho {sym}"}


class GameFiProject(BaseModel):
    name: str
    symbol: str
    chain: str = "SOL"
    token_price: float = 0
    nft_floor_price: float = 0
    daily_roi_estimate: float = 0
    onchain_users_24h: int = 0
    note: str = ""

@router.get("/")
def get_projects():
    projects = db.get_gamefi_projects()
    return {"projects": projects, "count": len(projects)}

@router.post("/")
def add_project(req: GameFiProject):
    db.add_gamefi_project(
        name=req.name,
        symbol=req.symbol,
        chain=req.chain,
        token_price=req.token_price,
        nft_floor_price=req.nft_floor_price,
        daily_roi_estimate=req.daily_roi_estimate,
        onchain_users_24h=req.onchain_users_24h,
        note=req.note
    )
    return {"success": True}

@router.put("/{project_id}")
def update_project(project_id: int, req: GameFiProject):
    db.update_gamefi_project(project_id, req.dict())
    return {"success": True}

@router.delete("/{project_id}")
def delete_project(project_id: int):
    db.remove_gamefi_project(project_id)
    return {"success": True}
