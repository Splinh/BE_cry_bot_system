from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from data.database import db
from api.auth import require_permission

router = APIRouter(
    prefix="/api/gamefi",
    tags=["GameFi"],
    dependencies=[Depends(require_permission("gamefi"))]
)

# ============================================
#  GAMEFI KNOWLEDGE BASE
#  Chi tiet ve tung game: cach choi, link, platform, earning model
# ============================================

GAMEFI_DATABASE = {
    "RDIA": {
        "floor": 14.99, "roi": 4.5, "chain": "ONEchain",
        "note": "Frost Kingdom - Chiến thuật SLG & Merge Web3 (NEXUS)",
        "category": "SLG / Medieval Merge Strategy",
        "platform": ["Web (HTML5)", "PC", "Android", "iOS"],
        "earn_model": "Mint & Burn (Cross Ramp) + 5% Revenue Share Pool",
        "website": "https://games.onechain.nexus/frostkingdom",
        "play_url": "https://games.onechain.nexus/frostkingdom",
        "marketplace_url": "https://games.onechain.nexus/frostkingdom",
        "how_to_earn": [
            "Chơi Server 4 → cày cấp Lâu Đài hoàn thành ONEquest nhận $ONE",
            "Thu thập vé tăng tốc ($SPDP), khiên ($SHLD), vé dịch chuyển ($CITY) → Mint qua Cross Ramp bán lấy $ONE/$ONEUSD",
            "Mở rương gom nguyên liệu ghép trang bị Tím/Cam → Seal thành Equipment NFT bán trên chợ",
            "Giữ/Stake $RDIA → nhận chia sẻ 5% tổng doanh thu nạp toàn game bằng $ONEUSD",
            "Mua gói Imperial Logistics Officer ($14.99) để mở khóa quyền Mint & Burn không giới hạn",
        ],
        "min_investment": "$0 (F2P cày ONEquest) hoặc $14.99 (Mở khóa Mint Cross Ramp)",
        "risk_level": "LOW",
        "status": "active",
    },
    "FROST": {
        "floor": 14.99, "roi": 4.5, "chain": "ONEchain",
        "note": "Frost Kingdom Server 4 - Đua Top & Mint Token",
        "category": "SLG / Medieval Merge Strategy",
        "platform": ["Web (HTML5)", "PC", "Android", "iOS"],
        "earn_model": "Play-to-Earn + ONEquest Missions + Cross Ramp",
        "website": "https://games.onechain.nexus/frostkingdom",
        "play_url": "https://games.onechain.nexus/frostkingdom",
        "marketplace_url": "https://games.onechain.nexus/frostkingdom",
        "how_to_earn": [
            "Đăng ký Server 4 qua link ref để nhận hoa hồng 2 đầu",
            "Tự động hóa cày cấp bằng frost_assistant.py chống ban",
            "Mint tài nguyên tích lũy ($SPDP, $CITY, $SHLD) bán cho đại gia đua top",
        ],
        "min_investment": "$0 - $14.99",
        "risk_level": "LOW",
        "status": "active",
    },
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
    enriched_projects = []
    for p in projects:
        p_dict = dict(p)
        sym = p_dict["symbol"].upper()
        if sym in GAMEFI_DATABASE:
            est = GAMEFI_DATABASE[sym]
            p_dict["category"] = est.get("category", "")
            p_dict["platform"] = est.get("platform", [])
            p_dict["earn_model"] = est.get("earn_model", "")
            p_dict["website"] = est.get("website", "")
            p_dict["play_url"] = est.get("play_url", "")
            p_dict["marketplace_url"] = est.get("marketplace_url", "")
            p_dict["how_to_earn"] = est.get("how_to_earn", [])
            p_dict["min_investment"] = est.get("min_investment", "")
            p_dict["risk_level"] = est.get("risk_level", "MEDIUM")
            p_dict["status"] = est.get("status", "unknown")
            p_dict["image"] = est.get("image", "")
            p_dict["price"] = p_dict.get("token_price", 0.0)
        else:
            p_dict["category"] = "GameFi / Unknown"
            p_dict["platform"] = []
            p_dict["earn_model"] = "Chưa xác định"
            p_dict["website"] = ""
            p_dict["play_url"] = ""
            p_dict["marketplace_url"] = ""
            p_dict["how_to_earn"] = ["⚠ Chưa có hướng dẫn chi tiết — cần research thêm"]
            p_dict["min_investment"] = "Chưa rõ"
            p_dict["risk_level"] = "HIGH"
            p_dict["status"] = "unknown"
            p_dict["image"] = ""
            p_dict["price"] = p_dict.get("token_price", 0.0)
        enriched_projects.append(p_dict)
    return {"projects": enriched_projects, "count": len(enriched_projects)}

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


# ============================================
#  FROST KINGDOM SERVER 4 MODULE & CALCULATOR
# ============================================

class FrostCalculatorRequest(BaseModel):
    speedup_5m_units: float = 0
    speedup_1h_units: float = 0
    speedup_8h_units: float = 0
    shields_8h_units: float = 0
    city_reloc_units: float = 0
    rdia_amount: float = 0
    diamonds_amount: float = 0
    chests_amount: float = 0
    pass_cost_usd: float = 14.99
    vnd_rate: float = 25400.0


class FrostAccountModel(BaseModel):
    name: str
    server: str = "Server 4"
    wallet_address: str = ""
    castle_level: int = 1
    has_pass: int = 0
    pass_expiry: str = ""
    rdia_balance: float = 0
    speedup_hours: float = 0
    referral_code: str = ""
    referred_by: str = ""
    note: str = ""


@router.post("/frost/calculator")
def calculate_frost_mint(req: FrostCalculatorRequest):
    """Tính toán chi tiết sản lượng quy đổi token on-chain và ROI từ kho đồ Frost Kingdom."""
    total_speedup_minutes = (
        5 * req.speedup_5m_units + 
        60 * req.speedup_1h_units + 
        480 * req.speedup_8h_units
    )
    total_speedup_hours = round(total_speedup_minutes / 60.0, 2)
    
    # Định giá thị trường tham khảo (theo sàn ONEchain)
    spdp_usd = round(total_speedup_hours * 0.042, 2)       # ~$4.2 / 100 giờ tăng tốc
    shld_usd = round(req.shields_8h_units * 0.85, 2)       # ~$0.85 / khiên 8h
    city_usd = round(req.city_reloc_units * 1.25, 2)       # ~$1.25 / vé dịch chuyển tím
    rdia_usd = round(req.rdia_amount * 3.50, 2)            # ~$3.50 / $RDIA (Hard cap 500k)
    rdia_monthly_dividend = round(req.rdia_amount * 0.48, 2) # Cổ tức 5% doanh thu hàng tháng ($ONEUSD)
    gear_nft_est_usd = round((req.chests_amount / 40.0) * 2.2, 2) if req.chests_amount > 0 else 0
    
    total_gross_usd = round(spdp_usd + shld_usd + city_usd + rdia_usd + gear_nft_est_usd, 2)
    net_profit_usd = round(total_gross_usd - req.pass_cost_usd, 2)
    roi_pct = round((net_profit_usd / req.pass_cost_usd) * 100, 1) if req.pass_cost_usd > 0 else 0
    
    total_vnd = round(total_gross_usd * req.vnd_rate)
    net_profit_vnd = round(net_profit_usd * req.vnd_rate)
    
    return {
        "success": True,
        "input_summary": {
            "total_speedup_hours": total_speedup_hours,
            "total_speedup_minutes": total_speedup_minutes,
            "rdia_amount": req.rdia_amount,
            "shields_count": req.shields_8h_units,
            "reloc_count": req.city_reloc_units,
            "chests_count": req.chests_amount,
        },
        "token_breakdown": {
            "spdp": {"token": "$SPDP", "hours": total_speedup_hours, "usd_value": spdp_usd},
            "shld": {"token": "$SHLD", "units": req.shields_8h_units, "usd_value": shld_usd},
            "city": {"token": "$CITY", "units": req.city_reloc_units, "usd_value": city_usd},
            "rdia": {
                "token": "$RDIA", 
                "units": req.rdia_amount, 
                "usd_value": rdia_usd,
                "est_monthly_dividend_oneusd": rdia_monthly_dividend
            },
            "equipment_nfts": {"est_usd_value": gear_nft_est_usd}
        },
        "financials": {
            "total_gross_usd": total_gross_usd,
            "total_gross_vnd": total_vnd,
            "pass_cost_usd": req.pass_cost_usd,
            "net_profit_usd": net_profit_usd,
            "net_profit_vnd": net_profit_vnd,
            "roi_pct": roi_pct,
            "recommendation": "LÃI ĐẬM - NÊN MINT NGAY" if net_profit_usd > 0 else "CẦN TÍCH LŨY THÊM"
        }
    }


@router.get("/frost/accounts")
def list_frost_accounts():
    """Lấy danh sách các tài khoản đang cày Frost Kingdom."""
    accounts = db.get_frost_accounts()
    return {"success": True, "accounts": accounts, "count": len(accounts)}


@router.post("/frost/accounts")
def add_frost_account(req: FrostAccountModel):
    """Thêm tài khoản cày game Frost Kingdom."""
    account_id = db.add_frost_account(
        name=req.name,
        server=req.server,
        wallet_address=req.wallet_address,
        castle_level=req.castle_level,
        has_pass=req.has_pass,
        pass_expiry=req.pass_expiry,
        rdia_balance=req.rdia_balance,
        speedup_hours=req.speedup_hours,
        referral_code=req.referral_code,
        referred_by=req.referred_by,
        note=req.note
    )
    return {"success": True, "account_id": account_id}


@router.put("/frost/accounts/{account_id}")
def update_frost_account(account_id: int, req: FrostAccountModel):
    """Cập nhật thông tin tài khoản."""
    db.update_frost_account(account_id, req.dict())
    return {"success": True}


@router.delete("/frost/accounts/{account_id}")
def delete_frost_account(account_id: int):
    """Xóa tài khoản."""
    db.remove_frost_account(account_id)
    return {"success": True}


@router.get("/frost/events")
def get_frost_events():
    """Lấy danh sách sự kiện, mốc level, và nhiệm vụ ONEquest Server 4."""
    return {
        "success": True,
        "server_info": {
            "current_server": "Server 4",
            "status": "ONLINE / OPEN",
            "ecosystem": "ONEchain / NEXUS",
            "core_token": "$RDIA",
            "gas_chain": "ONE",
            "cross_ramp_url": "https://games.onechain.nexus/frostkingdom",
            "onequest_url": "https://onechain.nexus"
        },
        "castle_milestones": [
            {"level": 5, "reward_one": 50, "reward_items": "Gói Tăng Tốc 5m x50, Rương Tím x10", "status": "Dễ"},
            {"level": 10, "reward_one": 150, "reward_items": "Vé Triệu Hồi SSR x5, Khiên 8h x2", "status": "Mục Tiêu Ngày 1"},
            {"level": 15, "reward_one": 350, "reward_items": "100 Kim Cương Đỏ (RDIA), Rương Cam x5", "status": "Mục Tiêu Tuần 1"},
            {"level": 20, "reward_one": 800, "reward_items": "Danh Hiệu Đua Top S4 + 500 $ONE", "status": "Đua Top"}
        ],
        "onequest_checklist": [
            {"id": "q1", "name": "Liên kết ví Web3 & Tạo nhân vật Server 4", "reward": "50 $ONE", "type": "Onboarding"},
            {"id": "q2", "name": "Theo dõi kênh X (Twitter) & Join Discord ONEchain", "reward": "30 $ONE", "type": "Social"},
            {"id": "q3", "name": "Gia nhập Top 10 Alliance và Cống hiến 5 lần", "reward": "40 $ONE", "type": "Alliance"},
            {"id": "q4", "name": "Đạt mốc Lâu Đài Cấp 10 (Castle Lv.10)", "reward": "150 $ONE", "type": "Progression"},
            {"id": "q5", "name": "Tự Ref / Giới thiệu bạn bè qua link Referral", "reward": "20% hoa hồng $ONE", "type": "Referral"}
        ],
        "tactical_tips": [
            "Ưu tiên nạp gói Đầu $0.99 để lấy Tướng Cam + Hàng chờ xây nhà thứ 2.",
            "Dùng tool frost_assistant.py để tự động click búa xây nhà và nhận quest 24/7.",
            "Tích lũy tối thiểu 500+ giờ tăng tốc rồi mới mua gói Imperial Logistics Officer $14.99 để mint một lần tiết kiệm phí.",
            "Tách biệt 3 profile trình duyệt và dùng địa chỉ nạp riêng trên sàn OKX/Binance để cashout an toàn."
        ]
    }

