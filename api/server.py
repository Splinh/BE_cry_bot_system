"""
Web API Server (FastAPI) - FULL FEATURED
Phan anh toan bo chuc nang cua Telegram Bot len Web Dashboard.
"""
import os
import json
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from loguru import logger
import httpx
from analytics.technical import TechnicalAnalyzer

app = FastAPI(title="Crypto Bot Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth router
from api.auth import router as auth_router
app.include_router(auth_router)

# GameFi router
from api.gamefi import router as gamefi_router
app.include_router(gamefi_router)

# Users management router
from api.users import router as users_router
app.include_router(users_router)

# Instances inject tu main.py
ctx = {
    "trade_engine": None,
    "telegram_manager": None,
    "twitter_manager": None,
    "status": None,
    "signal_tracker": None,
    "listing_scanner": None,
    "security": None,
    "wallet_manager": None,
    "price_monitor": None,
}

def inject_instances(trade_engine, tele_mgr, twit_mgr, system_status,
                     signal_tracker=None, listing_scanner=None, security=None,
                     wallet_manager=None, price_monitor=None):
    ctx["trade_engine"] = trade_engine
    ctx["telegram_manager"] = tele_mgr
    ctx["twitter_manager"] = twit_mgr
    ctx["status"] = system_status
    ctx["signal_tracker"] = signal_tracker
    ctx["listing_scanner"] = listing_scanner
    ctx["security"] = security
    ctx["wallet_manager"] = wallet_manager
    ctx["price_monitor"] = price_monitor

# ============================================
#  OVERVIEW
# ============================================

@app.get("/")
def health():
    return {"status": "ok"}

@app.get("/api/overview")
def get_overview():
    status = ctx["status"] or {}
    te = ctx["trade_engine"]
    tele = ctx["telegram_manager"]
    twit = ctx["twitter_manager"]
    wm = ctx["wallet_manager"]

    portfolio = te.get_portfolio_status() if te else {}
    wallet_summary = wm.get_summary() if wm else {}

    admin_count = 0
    sf = "data/security/security_config.json"
    if os.path.exists(sf):
        try:
            with open(sf) as f:
                admin_count = len(json.load(f).get("admin_ids", []))
        except: pass

    return {
        "status": status.get("status", "Running"),
        "version": status.get("version", "1.0"),
        "uptime_minutes": status.get("uptime_minutes", 0),
        "admin_count": admin_count,
        "balance": portfolio.get("balance", 0),
        "total_pnl": portfolio.get("total_pnl", 0),
        "win_rate": portfolio.get("win_rate", 0),
        "total_trades": portfolio.get("total_trades", 0),
        "open_positions_count": portfolio.get("open_positions", 0),
        "auto_trade": portfolio.get("auto_trade", False),
        "tele_bots": len(tele.workers) if tele else 0,
        "twitter_bots": len(twit.workers) if twit else 0,
        "total_wallets": wallet_summary.get("total_wallets", 0),
        "active_wallets": wallet_summary.get("active_wallets", 0),
    }

# ============================================
#  TRADING
# ============================================

import httpx
import time as _time

_price_cache = {"prices": {}, "ts": 0}

def _get_latest_prices() -> dict:
    """Lay gia real-time tu Binance REST API (cache 2s)."""
    now = _time.time()
    if now - _price_cache["ts"] < 2 and _price_cache["prices"]:
        return _price_cache["prices"]
    
    # Thu lay tu WebSocket truoc
    pm = ctx.get("price_monitor")
    if pm and hasattr(pm, 'ws') and pm.ws.latest_prices:
        _price_cache["prices"] = pm.ws.latest_prices
        _price_cache["ts"] = now
        return _price_cache["prices"]
    
    # Fallback: Binance REST API
    endpoints = [
        "https://api.binance.com/api/v3/ticker/24hr",
        "https://api1.binance.com/api/v3/ticker/24hr",
        "https://api2.binance.com/api/v3/ticker/24hr",
        "https://api3.binance.com/api/v3/ticker/24hr",
    ]
    for url in endpoints:
        try:
            resp = httpx.get(url,
                             params={"symbols": '["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","DOTUSDT","MATICUSDT"]'},
                             timeout=5)
            if resp.status_code == 200:
                result = {}
                for t in resp.json():
                    result[t["symbol"]] = {
                        "price": float(t.get("lastPrice", 0)),
                        "change_pct": float(t.get("priceChangePercent", 0)),
                        "high": float(t.get("highPrice", 0)),
                        "low": float(t.get("lowPrice", 0)),
                        "volume": float(t.get("volume", 0)),
                        "open": float(t.get("openPrice", 0)),
                    }
                _price_cache["prices"] = result
                _price_cache["ts"] = now
                return result
        except Exception as e:
            logger.warning(f"Binance REST price fetch error for {url}: {e}")
    
    return _price_cache["prices"]

@app.get("/api/prices")
def get_prices():
    """Tra ve gia real-time cua cac coins chinh."""
    prices = _get_latest_prices()
    return {
        "prices": {k: {
            "price": v.get("price", 0),
            "change_pct": v.get("change_pct", 0),
            "high": v.get("high", 0),
            "low": v.get("low", 0),
            "volume": v.get("volume", 0),
        } for k, v in prices.items()},
        "count": len(prices),
    }

# DexScreener price cache for GEM tokens
_gem_price_cache: dict = {}  # pair_address -> {price, timestamp}
_GEM_CACHE_TTL = 10  # seconds

def _fetch_gem_prices(te) -> dict:
    """Fetch live prices from DexScreener for all GEM positions."""
    global _gem_price_cache
    now = _time.time()
    
    # Collect pair addresses that need price update
    pairs_to_fetch = []  # (pair_address, chain)
    for k, p in te.positions.items():
        if p.get("type") == "GEM" and p.get("pair_address"):
            pa = p["pair_address"]
            cached = _gem_price_cache.get(pa)
            if not cached or (now - cached.get("ts", 0)) > _GEM_CACHE_TTL:
                chain = p.get("chain", "solana").lower()
                pairs_to_fetch.append((pa, chain))
    
    if not pairs_to_fetch:
        return _gem_price_cache
    
    try:
        for pa, chain in pairs_to_fetch[:10]:  # Max 10 to avoid rate limit
            try:
                resp = httpx.get(
                    f"https://api.dexscreener.com/latest/dex/pairs/{chain}/{pa}",
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    pair = data.get("pair") or (data.get("pairs", [{}])[0] if data.get("pairs") else {})
                    if pair and pair.get("priceUsd"):
                        _gem_price_cache[pa] = {
                            "price": float(pair["priceUsd"]),
                            "ts": now,
                            "change_5m": pair.get("priceChange", {}).get("m5", 0),
                            "change_1h": pair.get("priceChange", {}).get("h1", 0),
                            "change_24h": pair.get("priceChange", {}).get("h24", 0),
                        }
            except Exception:
                pass
    except Exception as e:
        logger.error(f"DexScreener fetch error: {e}")
    
    return _gem_price_cache

@app.get("/api/trading")
def get_trading():
    te = ctx["trade_engine"]
    if not te: return {"error": "Not init"}
    s = te.get_portfolio_status()
    
    # Lay gia real-time (CEX)
    latest = _get_latest_prices()
    
    # Fetch DexScreener prices for GEM positions
    gem_prices = _fetch_gem_prices(te)
    
    # Tinh live PnL cho tung position (chi hien OPEN/PARTIAL, bo CLOSED)
    positions = []
    total_unrealized = 0.0
    for k, p in te.positions.items():
        if p.get("status") == "CLOSED":
            continue  # Da dong, bo qua (se bi cleanup sau 30s)
        pos = dict(**p, id=k, _key=k)
        coin = p.get("coin", "")
        pos_type = p.get("type", "FUTURES")
        
        current_price = 0
        change_24h = 0
        
        if pos_type == "GEM" and p.get("pair_address"):
            # Use DexScreener price for GEM tokens
            gem_data = gem_prices.get(p["pair_address"], {})
            current_price = gem_data.get("price", 0)
            change_24h = gem_data.get("change_24h", 0)
        else:
            # Use CEX price
            symbol_key = f"{coin}USDT"
            current_price = latest.get(symbol_key, {}).get("price", 0)
            change_24h = latest.get(symbol_key, {}).get("change_pct", 0)
        
        if current_price > 0:
            entry = p.get("entry_price", 0)
            size = p.get("usdt_size", 0)
            direction = p.get("direction", "LONG")
            remaining_pct = 1.0 - p.get("closed_pct", 0)
            
            if direction == "LONG":
                pnl = ((current_price - entry) / entry) * size * remaining_pct
                pnl_pct = ((current_price - entry) / entry) * 100 if entry > 0 else 0
            else:
                pnl = ((entry - current_price) / entry) * size * remaining_pct
                pnl_pct = ((entry - current_price) / entry) * 100 if entry > 0 else 0
            
            pos["pnl"] = round(pnl, 2)
            pos["current_price"] = current_price
            pos["pnl_pct"] = round(pnl_pct, 2)
            pos["change_24h"] = change_24h
            pos["liq_price"] = p.get("liq_price", 0.0)
            pos["fees_paid"] = p.get("fees_paid", 0.0)
            total_unrealized += pnl
        else:
            pos["current_price"] = 0
            pos["pnl_pct"] = 0
            pos["change_24h"] = 0
        
        positions.append(pos)
    
    return {
        "auto_trade_enabled": s["auto_trade"],
        "balance": s["balance"],
        "total_pnl": s["total_pnl"],
        "unrealized_pnl": round(total_unrealized, 2),
        "win_rate_percent": s["win_rate"],
        "total_trades": s["total_trades"],
        "open_positions": positions,
    }

class TradingConfigReq(BaseModel):
    live_mode: bool

@app.get("/api/trading/config")
def get_trading_config():
    from data.database import db
    from core.config import Config
    
    live_mode = db.get_live_mode()
    has_api_keys = bool(Config.BINANCE_API_KEY and Config.BINANCE_API_SECRET)
    
    return {
        "live_mode": live_mode,
        "has_api_keys": has_api_keys
    }

@app.post("/api/trading/config")
def update_trading_config(req: TradingConfigReq):
    from data.database import db
    from core.config import Config
    
    if req.live_mode:
        if not Config.BINANCE_API_KEY or not Config.BINANCE_API_SECRET:
            raise HTTPException(400, "Không thể bật Live Mode do chưa cấu hình BINANCE_API_KEY/SECRET trong .env")
            
    db.set_live_mode(req.live_mode)
    logger.info(f"[Web] Live Mode -> {req.live_mode}")
    return {"success": True, "live_mode": req.live_mode}

@app.get("/api/trading/history")
def get_history():
    te = ctx["trade_engine"]
    return {"history": te.history[-50:] if te else []}

@app.post("/api/trading/toggle")
def toggle_trade():
    te = ctx["trade_engine"]
    if not te: raise HTTPException(500, "No trade engine")
    te.auto_trade_enabled = not te.auto_trade_enabled
    te._save_data()
    logger.info(f"[Web] Auto-Trade -> {te.auto_trade_enabled}")
    return {"success": True, "auto_trade_enabled": te.auto_trade_enabled}

class ManualTradeReq(BaseModel):
    coin: str = "BTC"
    direction: str = "LONG"  # LONG or SHORT
    usdt_size: float = 100    # Volume in USDT
    leverage: int = 1         # 1-125x
    wallet_id: Optional[int] = None     # Wallet ID to use
    wallet_label: Optional[str] = ""    # Wallet label for display

@app.post("/api/trading/open")
async def open_manual_trade(req: ManualTradeReq):
    """Mo lenh thu cong voi Smart SL/TP (ATR + S/R + Fibonacci)."""
    te = ctx["trade_engine"]
    if not te: raise HTTPException(500, "No trade engine")
    
    # Lay gia hien tai
    prices = _get_latest_prices()
    symbol = f"{req.coin.upper()}USDT"
    current_price = prices.get(symbol, {}).get("price", 0)
    
    # Fallback: lay truc tiep tu Binance cho token ko co trong cache
    if current_price <= 0:
        for host in ["api.binance.com", "api1.binance.com", "api2.binance.com", "api3.binance.com"]:
            try:
                resp = httpx.get(f"https://{host}/api/v3/ticker/price",
                                params={"symbol": symbol}, timeout=5)
                if resp.status_code == 200:
                    current_price = float(resp.json().get("price", 0))
                    break
            except Exception:
                pass
    
    if current_price <= 0:
        raise HTTPException(400, f"Khong lay duoc gia {req.coin}")
    
    if req.leverage < 1 or req.leverage > 125:
        raise HTTPException(400, "Leverage phai tu 1-125x")
    
    # === SMART SL/TP: Tinh ATR + S/R + Fibonacci ===
    smart_levels = None
    try:
        from analytics.technical import TechnicalAnalyzer
        from analytics.macro_calendar import MacroCalendar
        
        ta_engine = TechnicalAnalyzer()
        
        # Chon timeframe dua tren leverage
        if req.leverage >= 50: tf = "5m"
        elif req.leverage >= 20: tf = "15m"
        elif req.leverage >= 10: tf = "1h"
        elif req.leverage >= 5: tf = "4h"
        else: tf = "1d"
        
        try:
            df = await ta_engine.get_ohlcv(f"{req.coin.upper()}/USDT", tf, limit=100)
            if not df.empty and len(df) >= 20:
                df = ta_engine.calculate_indicators(df)
                
                # Lay macro risk
                macro = MacroCalendar()
                try:
                    risk_data = await macro.assess_risk()
                    macro_risk = risk_data.get("risk_level", "NORMAL")
                except Exception:
                    macro_risk = "NORMAL"
                finally:
                    await macro.close()
                
                smart_levels = ta_engine.compute_smart_levels(
                    df, direction=req.direction.upper(),
                    leverage=req.leverage, macro_risk=macro_risk,
                )
                logger.info(
                    f"[SmartSL/TP] {req.coin} {req.direction} x{req.leverage} | "
                    f"Method: {smart_levels.get('method')} | "
                    f"SL: ${smart_levels.get('sl', 0):,.2f} | "
                    f"TP1: ${smart_levels.get('tp1', 0):,.2f} | "
                    f"ATR: ${smart_levels.get('atr', 0):.4f} | "
                    f"Macro: {macro_risk}"
                )
        except Exception as e:
            logger.warning(f"Smart SL/TP failed, fallback to fixed %: {e}")
        finally:
            await ta_engine.close()
    except Exception as e:
        logger.warning(f"Smart SL/TP import error: {e}")
    
    pos = te.open_manual_position(
        coin=req.coin.upper(),
        direction=req.direction.upper(),
        usdt_size=req.usdt_size,
        leverage=req.leverage,
        current_price=current_price,
        smart_levels=smart_levels,
        wallet_id=req.wallet_id,
        wallet_label=req.wallet_label or "",
    )
    
    if not pos:
        raise HTTPException(400, "Khong the mo lenh. Kiem tra so du.")
    
    # Them smart levels info cho frontend
    if smart_levels:
        pos["sl_method"] = smart_levels.get("method", "")
        pos["atr"] = smart_levels.get("atr", 0)
        pos["macro_risk"] = smart_levels.get("macro_risk", "NORMAL")
        te._save_data()
    
    is_dca = pos.get("dca_count", 0) > 0
    return {"success": True, "position": pos, "is_dca": is_dca}

@app.post("/api/trading/close/{sig_key}")
def close_position_web(sig_key: str):
    """Dong lenh tu Web Dashboard."""
    te = ctx["trade_engine"]
    if not te: raise HTTPException(500, "No trade engine")
    
    if sig_key not in te.positions:
        raise HTTPException(404, "Khong tim thay lenh")
    
    prices = _get_latest_prices()
    pos = te.positions[sig_key]
    symbol = f"{pos['coin']}USDT"
    current_price = prices.get(symbol, {}).get("price", 0)
    
    # Fallback: lay truc tiep tu Binance
    if current_price <= 0:
        for host in ["api.binance.com", "api1.binance.com", "api2.binance.com", "api3.binance.com"]:
            try:
                resp = httpx.get(f"https://{host}/api/v3/ticker/price",
                                params={"symbol": symbol}, timeout=5)
                if resp.status_code == 200:
                    current_price = float(resp.json().get("price", 0))
                    break
            except Exception:
                pass
    
    if current_price <= 0:
        raise HTTPException(400, "Khong lay duoc gia hien tai")
    
    te.close_position(sig_key, current_price, reason="WEB_CLOSE")
    return {"success": True, "close_price": current_price}

# ============================================
#  NAP / RUT TIEN
# ============================================

class DepositWithdrawReq(BaseModel):
    amount: float = 100
    note: str = ""

@app.post("/api/trading/deposit")
def deposit_funds(req: DepositWithdrawReq):
    te = ctx["trade_engine"]
    if not te: raise HTTPException(500, "No trade engine")
    result = te.deposit(req.amount, req.note)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Loi nap tien"))
    return result

@app.post("/api/trading/withdraw")
def withdraw_funds(req: DepositWithdrawReq):
    te = ctx["trade_engine"]
    if not te: raise HTTPException(500, "No trade engine")
    result = te.withdraw(req.amount, req.note)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Loi rut tien"))
    return result

@app.get("/api/trading/balance-history")
def get_balance_history():
    te = ctx["trade_engine"]
    if not te: return {"history": []}
    return {"history": te.balance_history[-50:], "balance": te.balance}

# ============================================
#  AUTO SL/TP BACKGROUND MONITOR
# ============================================

_sl_tp_events: list = []  # Luu cac su kien SL/TP gan nhat

@app.get("/api/trading/sl-tp-events")
def get_sl_tp_events():
    """Lay cac su kien SL/TP gan nhat (frontend poll de hien toast)."""
    events = list(_sl_tp_events)
    _sl_tp_events.clear()
    return {"events": events}

@app.on_event("startup")
async def start_sl_tp_monitor():
    """Background loop kiem tra SL/TP moi 3 giay."""
    async def monitor_loop():
        await asyncio.sleep(5)  # Cho system khoi dong
        while True:
            try:
                te = ctx.get("trade_engine")
                if te:
                    # Cleanup positions da dong qua 30s
                    te._cleanup_closed()
                    
                    if len([p for p in te.positions.values() if p.get("status") != "CLOSED"]) > 0:
                        prices = _get_latest_prices()
                        if prices:
                            closed = te.check_sl_tp(prices)
                            for c in closed:
                                logger.warning(
                                    f"AUTO SL/TP: {c['reason']} | Key: {c['key']} | "
                                    f"Price: ${c['price']:,.2f} | PnL: ${c['pnl']:.2f}"
                                )
                                _sl_tp_events.append(c)
            except Exception as e:
                logger.error(f"SL/TP monitor error: {e}")
            await asyncio.sleep(3)
    asyncio.create_task(monitor_loop())

@app.get("/api/trading/scalping")
def get_scalping_signals():
    """
    Tin hieu scalping don bay cao - dua tren chi bao ky thuat that.
    Su dung TechnicalAnalyzer voi cac timeframe ngan (5m, 15m).
    """
    prices = _get_latest_prices()
    if not prices:
        return {"signals": []}
    
    scalp_signals = []
    for symbol, data in prices.items():
        if not symbol.endswith("USDT"):
            continue
        
        coin = symbol.replace("USDT", "")
        price = data.get("price", 0)
        change_24h = data.get("change_pct", 0)
        high = data.get("high", 0)
        low = data.get("low", 0)
        vol = data.get("volume", 0)
        
        if price <= 0:
            continue
        
        # Tinh bien dong va range
        day_range_pct = ((high - low) / low * 100) if low > 0 else 0
        
        # Vi tri trong range ngay
        if high > low:
            position_in_range = (price - low) / (high - low)
        else:
            position_in_range = 0.5
        
        # Support/Resistance tu range
        support = low
        resistance = high
        mid = (high + low) / 2
        
        # Scoring system
        bull_score = 0
        bear_score = 0
        reasons = []
        
        # 1. Momentum
        if change_24h < -4:
            bull_score += 2
            reasons.append(f"Oversold ({change_24h:+.1f}% 24h)")
        elif change_24h < -2:
            bull_score += 1
            reasons.append(f"Giam ({change_24h:+.1f}% 24h)")
        elif change_24h > 4:
            bear_score += 2
            reasons.append(f"Overbought ({change_24h:+.1f}% 24h)")
        elif change_24h > 2:
            bear_score += 1
            reasons.append(f"Tang ({change_24h:+.1f}% 24h)")
        
        # 2. Vi tri trong range
        if position_in_range < 0.2:
            bull_score += 2
            reasons.append("Sat day range")
        elif position_in_range < 0.35:
            bull_score += 1
            reasons.append("Gan day range")
        elif position_in_range > 0.8:
            bear_score += 2
            reasons.append("Sat dinh range")
        elif position_in_range > 0.65:
            bear_score += 1
            reasons.append("Gan dinh range")
        
        # 3. Range rong = co hoi scalp
        if day_range_pct > 5:
            reasons.append(f"Range rong {day_range_pct:.1f}%")
            if position_in_range < 0.4:
                bull_score += 1
            elif position_in_range > 0.6:
                bear_score += 1
        
        # Xac dinh direction
        total_score = max(bull_score, bear_score)
        if total_score < 2:
            continue
        
        direction = "LONG" if bull_score > bear_score else "SHORT"
        confidence = min(95, 40 + total_score * 12 + (day_range_pct * 2))
        
        # ===== LEVERAGE-AWARE SL/TP =====
        # Leverage cao -> dung support/resistance chat hon
        # SL dat tai support (LONG) hoac resistance (SHORT)
        # TP dat o muc Fibonacci tu entry -> support/resistance doi dien
        
        for lev, tf_label in [(5, "4h"), (10, "1h"), (25, "15m"), (50, "5m")]:
            # SL % chat theo leverage
            max_sl_pct = 0.8 / lev  # max loss = 80% margin
            
            if direction == "LONG":
                valid_support = support if support < price else price * 0.99
                sl_from_pct = price * (1 - max_sl_pct)
                sl = max(valid_support, sl_from_pct)
                
                valid_resistance = resistance if resistance > price else price * 1.01
                room_to_r = valid_resistance - price
                tp1 = price + room_to_r * 0.382  # Fib 38.2%
                tp2 = price + room_to_r * 0.618  # Fib 61.8%
                tp3 = valid_resistance
            else:
                valid_resistance = resistance if resistance > price else price * 1.01
                sl_from_pct = price * (1 + max_sl_pct)
                sl = min(valid_resistance, sl_from_pct)
                
                valid_support = support if support < price else price * 0.99
                room_to_s = price - valid_support
                tp1 = price - room_to_s * 0.382
                tp2 = price - room_to_s * 0.618
                tp3 = valid_support
            
            actual_sl_pct = abs(price - sl) / price
            actual_tp1_pct = abs(tp1 - price) / price
            
            # RR ratio
            rr = actual_tp1_pct / actual_sl_pct if actual_sl_pct > 0 else 0
            
            # ROI/Risk voi leverage
            potential_roi = actual_tp1_pct * lev * 100
            max_loss = actual_sl_pct * lev * 100
            
            # Liq price
            if direction == "LONG":
                liq = price * (1 - 1/lev)
            else:
                liq = price * (1 + 1/lev)
            
            scalp_signals.append({
                "coin": coin,
                "price": TechnicalAnalyzer._round_price(price, price),
                "direction": direction,
                "leverage": lev,
                "timeframe": tf_label,
                "type": "SPOT" if lev == 1 else "FUTURES",
                "confidence": round(confidence),
                "reasons": reasons,
                "sl": TechnicalAnalyzer._round_price(sl, price),
                "tp1": TechnicalAnalyzer._round_price(tp1, price),
                "tp2": TechnicalAnalyzer._round_price(tp2, price),
                "tp3": TechnicalAnalyzer._round_price(tp3, price),
                "sl_pct": round(actual_sl_pct * 100, 2),
                "tp1_pct": round(actual_tp1_pct * 100, 2),
                "rr_ratio": round(rr, 2),
                "potential_roi": round(potential_roi, 1),
                "max_loss": round(max_loss, 1),
                "liq_price": TechnicalAnalyzer._round_price(liq, price),
                "change_24h": round(change_24h, 2),
                "day_range_pct": round(day_range_pct, 1),
                "support": TechnicalAnalyzer._round_price(support, price),
                "resistance": TechnicalAnalyzer._round_price(resistance, price),
            })
    
    # Sap xep: confidence cao + RR ratio tot nhat
    scalp_signals.sort(key=lambda x: (x["confidence"], x["rr_ratio"]), reverse=True)
    return {"signals": scalp_signals}

@app.get("/api/trading/analyze/{coin}")
async def leverage_analyze(coin: str, leverage: int = 10, market_type: str = "futures", timeframe: str = "auto"):
    """
    Phan tich ky thuat chi tiet cho 1 coin voi leverage cu the.
    Tra ve entry/SL/TP toi uu dua tren ATR + S/R + Fibonacci + Macro Events.
    timeframe: 'auto' (chon theo leverage), hoac '1m','5m','15m','30m','1h','4h','1d'
    """
    from analytics.technical import TechnicalAnalyzer
    from analytics.macro_calendar import MacroCalendar
    
    VALID_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
    
    # Chon timeframe: neu user chon thi dung, khong thi auto theo leverage
    if timeframe != "auto" and timeframe in VALID_TIMEFRAMES:
        pass  # use user-selected timeframe
    else:
        # Auto chon theo leverage
        if leverage >= 50: timeframe = "5m"
        elif leverage >= 20: timeframe = "15m"
        elif leverage >= 10: timeframe = "1h"
        elif leverage >= 5: timeframe = "4h"
        else: timeframe = "1d"
    
    ta_engine = TechnicalAnalyzer()
    macro = MacroCalendar()
    try:
        symbol = f"{coin.upper()}/USDT"
        df = await ta_engine.get_ohlcv(symbol, timeframe, limit=100)
        if df.empty:
            return {"error": f"Khong lay duoc du lieu {symbol}"}
        
        df = ta_engine.calculate_indicators(df)
        base_signal = ta_engine.generate_signal(df, symbol)
        
        if not base_signal:
            return {"error": "Khong tao duoc tin hieu"}
        
        latest = df.iloc[-1]
        price = latest["close"]
        
        raw_direction = base_signal.get("direction", "NEUTRAL")
        direction = raw_direction if raw_direction in ("LONG", "SHORT") else "LONG"
        
        # === MACRO RISK ASSESSMENT ===
        macro_context = {"risk_level": "NORMAL", "warnings": [], "upcoming_events": []}
        try:
            macro_context = await macro.assess_risk()
        except Exception as e:
            logger.warning(f"Macro risk check failed: {e}")
        
        macro_risk = macro_context.get("risk_level", "NORMAL")
        
        # === SMART SL/TP (ATR + S/R + Fibonacci) ===
        smart_levels = ta_engine.compute_smart_levels(
            df, direction=direction, leverage=leverage, macro_risk=macro_risk,
        )
        
        sl = smart_levels["sl"]
        tp1 = smart_levels["tp1"]
        tp2 = smart_levels["tp2"]
        tp3 = smart_levels["tp3"]
        sl_pct = smart_levels["sl_pct"] / 100
        tp1_pct = smart_levels["tp1_pct"] / 100
        rr = smart_levels["rr_ratio"]
        liq = smart_levels.get("liq_price") or (price * (1 - 1/leverage) if direction == "LONG" else price * (1 + 1/leverage))
        
        # Generate Smart AI Recommendation
        reasons_list = base_signal.get("reasons", [])
        reasons_str = ", ".join(reasons_list) if reasons_list else "Không có lý do cụ thể"
        
        if raw_direction in ("LONG", "SHORT"):
            ai_recommendation = f"Khuyến nghị VÀO LỆNH {raw_direction}. Lý do: {reasons_str}. Xu hướng đồng thuận."
            is_recommended = True
        else:
            if any("Huy " in r for r in reasons_list):
                ai_recommendation = f"KHÔNG NÊN VÀO LỆNH. Tín hiệu bị bộ lọc xu hướng hủy: {reasons_str}."
            else:
                ai_recommendation = f"KHÔNG NÊN VÀO LỆNH. Thị trường đang đi ngang lưỡng lự (Neutral). Bull: {base_signal.get('bull_score')} | Bear: {base_signal.get('bear_score')}."
            is_recommended = False

        # Extract indicator values safely
        def _sf(v, d=0): return TechnicalAnalyzer._round_price(v, price) if v is not None and v == v else d
        
        base_signal.update({
            "ai_recommendation": ai_recommendation,
            "is_recommended": is_recommended,
            "entry": TechnicalAnalyzer._round_price(price, price),
            "price": TechnicalAnalyzer._round_price(price, price),
            "leverage": leverage,
            "timeframe": timeframe,
            "market_type": market_type.upper(),
            "direction": raw_direction,
            "trade_direction": direction,
            "sl": TechnicalAnalyzer._round_price(sl, price),
            "tp1": TechnicalAnalyzer._round_price(tp1, price),
            "tp2": TechnicalAnalyzer._round_price(tp2, price),
            "tp3": TechnicalAnalyzer._round_price(tp3, price),
            "sl_pct": round(sl_pct * 100, 3),
            "tp1_pct": round(tp1_pct * 100, 3),
            "rr_ratio": round(rr, 2),
            "potential_roi": round(tp1_pct * leverage * 100, 1),
            "max_loss": round(sl_pct * leverage * 100, 1),
            "liq_price": TechnicalAnalyzer._round_price(liq, price),
            "recommended_leverage": smart_levels.get("recommended_leverage"),
            "ideal_sl_pct": smart_levels.get("ideal_sl_pct"),
            "leverage_warning": smart_levels.get("leverage_warning"),
            "support": TechnicalAnalyzer._round_price(smart_levels.get("support", 0), price),
            "resistance": TechnicalAnalyzer._round_price(smart_levels.get("resistance", 0), price),
            "support2": TechnicalAnalyzer._round_price(smart_levels.get("support2", 0), price),
            "resistance2": TechnicalAnalyzer._round_price(smart_levels.get("resistance2", 0), price),
            "bb_lower": _sf(latest.get("bb_lower")),
            "bb_upper": _sf(latest.get("bb_upper")),
            "ema20": _sf(latest.get("ema20")),
            "atr": round(smart_levels.get("atr", 0), 6),
            "sl_method": smart_levels.get("method", ""),
            "sl_method_detail": smart_levels.get("method_detail", ""),
            "macro_risk": macro_risk,
            "macro_context": {
                "risk_level": macro_context.get("risk_level", "NORMAL"),
                "warnings": macro_context.get("warnings", [])[:3],
                "next_event": macro_context.get("next_critical"),
                "upcoming_count": macro_context.get("upcoming_count", 0),
            },
            "indicators": {
                "rsi": _sf(latest.get("rsi"), 0),
                "macd": _sf(latest.get("macd"), 0),
                "adx": _sf(latest.get("adx"), 0),
                "vwap": _sf(latest.get("vwap"), 0),
                "atr": round(smart_levels.get("atr", 0), 4),
            },
        })
        
        # === LIMIT ENTRY SIGNALS ===
        try:
            limit_entries = ta_engine.compute_limit_entries(df, leverage=leverage)
            base_signal["limit_entries"] = limit_entries
        except Exception as e:
            logger.warning(f"Limit entry computation failed: {e}")
            base_signal["limit_entries"] = []
        
        return base_signal
    finally:
        await ta_engine.close()
        await macro.close()

# ============================================
#  SIGNALS
# ============================================

@app.get("/api/signals")
def get_signals():
    st = ctx["signal_tracker"]
    if not st: return {"signals": []}
    signals = []
    for key, sig in st.active_signals.items():
        s = sig.copy()
        s["key"] = key
        signals.append(s)
    return {"signals": signals, "count": len(signals)}

# ============================================
#  WALLETS
# ============================================

@app.get("/api/wallets")
def get_wallets():
    wm = ctx["wallet_manager"]
    if not wm: return {"wallets": [], "summary": {}}
    safe = wm.list_wallets(show_keys=False)
    summary = wm.get_summary()
    return {"wallets": safe, "summary": summary}

class CreateWalletReq(BaseModel):
    label: Optional[str] = ""
    count: Optional[int] = 1

@app.post("/api/wallets/create")
def create_wallet(req: CreateWalletReq):
    wm = ctx["wallet_manager"]
    if not wm: raise HTTPException(500, "Wallet Manager not init")
    
    if req.count and req.count > 1:
        created = wm.create_batch(count=min(req.count, 20), prefix=req.label or "Web")
        return {"success": True, "created": len(created), "total": len(wm.wallets)}
    else:
        w = wm.create_wallet(label=req.label or "")
        return {"success": True, "address": w["address"], "label": w["label"], "total": len(wm.wallets)}

@app.get("/api/wallets/export")
def export_wallets():
    wm = ctx["wallet_manager"]
    if not wm: return {"addresses": ""}
    return {"addresses": wm.export_addresses()}

# ============================================
#  SOCIAL BOTNET
# ============================================

@app.get("/api/social")
def get_social():
    tele = ctx["telegram_manager"]
    twit = ctx["twitter_manager"]
    tc = len(tele.workers) if tele else 0
    tw = len(twit.workers) if twit else 0
    return {"telegram_workers_count": tc, "twitter_workers_count": tw, "is_active": tc + tw > 0}

class ClaimReq(BaseModel):
    bot_username: str
    command: str

@app.post("/api/social/claimall")
def claimall(req: ClaimReq):
    tele = ctx["telegram_manager"]
    if not tele or not tele.workers: raise HTTPException(400, "No Tele sessions")
    logger.info(f"[Web] Mass claim: {req.command} -> {req.bot_username}")
    asyncio.ensure_future(tele.claim_all_bots(req.bot_username, req.command))
    return {"success": True, "bots": len(tele.workers)}

class RaidReq(BaseModel):
    tweet_id: str

@app.post("/api/social/raid")
def raid(req: RaidReq):
    twit = ctx["twitter_manager"]
    if not twit or not twit.workers: raise HTTPException(400, "No Twitter accounts")
    import threading
    threading.Thread(target=twit.raid_tweet, args=(req.tweet_id,), daemon=True).start()
    return {"success": True, "accounts": len(twit.workers)}

# ============================================
#  CEX AIRDROPS
# ============================================

@app.get("/api/airdrops")
async def get_airdrops():
    try:
        from analytics.cex_airdrop import CexAirdropScanner
        scanner = CexAirdropScanner()
        data = await scanner.get_all_airdrops()
        return {"airdrops": data}
    except Exception as e:
        return {"airdrops": [], "error": str(e)}

# ============================================
#  SECURITY & AUDIT
# ============================================

@app.get("/api/security/audit")
def get_audit():
    af = "data/security/audit_log.json"
    if not os.path.exists(af):
        return {"logs": []}
    try:
        with open(af) as f:
            logs = json.load(f)
        return {"logs": logs[-30:]}
    except:
        return {"logs": []}

# ============================================
#  MACRO CALENDAR & ECONOMIC EVENTS
# ============================================

@app.get("/api/macro/calendar")
async def get_macro_calendar(days: int = 30):
    """Lay toan bo su kien kinh te sap toi (FOMC, CPI, NFP, GDP...)."""
    from analytics.macro_calendar import MacroCalendar
    macro = MacroCalendar()
    try:
        events = await macro.get_all_events(days_ahead=min(days, 90))
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error(f"Macro calendar error: {e}")
        return {"events": [], "error": str(e)}
    finally:
        await macro.close()

@app.get("/api/macro/next")
async def get_macro_next():
    """Lay su kien CRITICAL/HIGH gan nhat sap dien ra."""
    from analytics.macro_calendar import MacroCalendar
    macro = MacroCalendar()
    try:
        event = await macro.get_next_critical()
        return {"event": event}
    except Exception as e:
        logger.error(f"Macro next error: {e}")
        return {"event": None, "error": str(e)}
    finally:
        await macro.close()

@app.get("/api/macro/risk")
async def get_macro_risk():
    """Danh gia muc do rui ro hien tai dua tren events sap toi."""
    from analytics.macro_calendar import MacroCalendar
    macro = MacroCalendar()
    try:
        risk = await macro.assess_risk()
        return risk
    except Exception as e:
        logger.error(f"Macro risk error: {e}")
        return {"risk_level": "NORMAL", "warnings": [], "error": str(e)}
    finally:
        await macro.close()

# ============================================
#  DEX GEM SCANNER (Tim Keo)
# ============================================

def _flatten_gem(raw: dict) -> dict:
    """Flatten nested dex scanner result thanh dict dep cho FE."""
    pair = raw.get("pair", {})
    safety = raw.get("safety", {})
    gem = raw.get("gem", {})
    base = pair.get("baseToken", {})
    quote = pair.get("quoteToken", {})
    liq = pair.get("liquidity", {})
    txns = pair.get("txns", {}).get("h24", {})
    chg = pair.get("priceChange", {})
    
    return {
        "name": raw.get("name") or base.get("name", "Unknown"),
        "symbol": raw.get("symbol") or base.get("symbol", "???"),
        "address": base.get("address", raw.get("address", "")),
        "chain": raw.get("chain", pair.get("chainId", "")),
        "price": raw.get("price", 0),
        "gem_score": gem.get("gem_score", 0),
        "safety_score": safety.get("score", 0),
        "liquidity": liq.get("usd", 0),
        "fdv": pair.get("fdv", 0),
        "market_cap": pair.get("marketCap", 0),
        "volume_24h": pair.get("volume", {}).get("h24", 0),
        "buys_24h": txns.get("buys", 0),
        "sells_24h": txns.get("sells", 0),
        "price_change_5m": chg.get("m5", 0),
        "price_change_1h": chg.get("h1", 0),
        "price_change_24h": chg.get("h24", 0),
        "age_mins": raw.get("age_mins"),
        "warnings": safety.get("warnings", []),
        "pair_address": pair.get("pairAddress", ""),
        # Links
        "url": raw.get("url") or pair.get("url", ""),
        "dexscreener_url": f"https://dexscreener.com/{raw.get('chain', 'solana')}/{pair.get('pairAddress', '')}",
        "pair_created_at": pair.get("pairCreatedAt"),
    }

@app.get("/api/gems/scan")
async def scan_gems(chain: str = "solana"):
    """Quet va tim gem tiem nang tren DEX."""
    try:
        from analytics.dex_scanner import DexGemScanner
        scanner = DexGemScanner()
        gems = await scanner.scan_for_gems(chain=chain, min_liquidity=5000)
        await scanner.close()
        flat = [_flatten_gem(g) for g in gems[:15]]
        return {"gems": flat, "chain": chain, "count": len(gems)}
    except Exception as e:
        logger.error(f"Gem scan error: {e}")
        return {"gems": [], "error": str(e)}

@app.get("/api/gems/new")
async def scan_new_listings_dex(chain: str = "solana", hours: float = 1.0):
    """Quet token moi list tren DEX trong vong n gio."""
    try:
        from analytics.dex_scanner import DexGemScanner
        scanner = DexGemScanner()
        tokens = await scanner.scan_new_listings(chain=chain, max_age_hours=hours)
        await scanner.close()
        flat = [_flatten_gem(t) for t in tokens[:20]]
        return {"tokens": flat, "chain": chain, "max_hours": hours}
    except Exception as e:
        logger.error(f"New listings scan error: {e}")
        return {"tokens": [], "error": str(e)}

@app.get("/api/gems/analyze")
async def analyze_token(query: str = ""):
    """Phan tich sau 1 token (ten hoac dia chi contract)."""
    if not query:
        return {"error": "query required"}
    try:
        from analytics.dex_scanner import DexGemScanner
        scanner = DexGemScanner()
        result = await scanner.analyze_token_deep(query)
        await scanner.close()
        return {"result": result}
    except Exception as e:
        logger.error(f"Token analysis error: {e}")
        return {"result": None, "error": str(e)}

# ============================================
#  GEM TOKEN BUY (Paper Trading)
# ============================================

class GemBuyReq(BaseModel):
    symbol: str          # Token symbol (e.g. "PEPE")
    name: str = ""       # Token name
    price: float         # Current price
    chain: str = ""      # Chain (solana, ethereum, etc.)
    volume: float = 100  # USDT volume
    pair_address: str = ""  # DexScreener pair address for live price
    wallet_id: Optional[int] = None
    wallet_label: Optional[str] = ""

@app.post("/api/gems/buy")
def buy_gem_token(req: GemBuyReq):
    """Mua gem token (paper trading) - tao position va track PnL."""
    te = ctx["trade_engine"]
    if not te: raise HTTPException(500, "No trade engine")
    
    if req.price <= 0:
        raise HTTPException(400, "Gia token khong hop le")
    if req.volume <= 0:
        raise HTTPException(400, "Volume phai > 0")
    
    # Tao position key
    sig_key = f"GEM_{req.symbol.upper()}_{int(_time.time())}"
    
    # Tru balance
    if req.volume > te.balance:
        raise HTTPException(400, f"Khong du so du. Balance: ${te.balance:.2f}")
    
    te.balance -= req.volume
    
    # Tinh SL/TP cho gem (SPOT, khong co leverage)
    entry = req.price
    sl = entry * 0.85     # SL -15%
    tp1 = entry * 1.30    # TP1 +30%
    tp2 = entry * 1.80    # TP2 +80%
    tp3 = entry * 3.00    # TP3 +200% (3x)
    
    pos = {
        "coin": req.symbol.upper(),
        "name": req.name,
        "direction": "LONG",
        "type": "GEM",
        "chain": req.chain,
        "entry_price": entry,
        "usdt_size": req.volume,
        "leverage": 1,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "status": "OPEN",
        "pnl": 0.0,
        "closed_pct": 0.0,
        "pair_address": req.pair_address,
        "open_time": _time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    
    if req.wallet_id:
        pos["wallet_id"] = req.wallet_id
        pos["wallet_label"] = req.wallet_label or f"Wallet #{req.wallet_id}"
    
    te.positions[sig_key] = pos
    te._save_data()
    
    logger.success(f"GEM BUY: {req.symbol} @ ${entry} | Volume: ${req.volume} | Chain: {req.chain}")
    
    return {
        "success": True,
        "position": pos,
        "key": sig_key,
        "sl": sl,
        "tp1": tp1,
        "tp3": tp3,
    }

# ============================================
#  CEX LISTING SCANNER (Tim token sap len Binance)
# ============================================

@app.get("/api/listing/potential")
async def find_potential():
    """Tim token da co Gate/MEXC nhung chua co Binance."""
    ls = ctx["listing_scanner"]
    if not ls:
        from analytics.listing_scanner import ListingScanner
        ls = ListingScanner()
    try:
        potentials = await ls.find_potential_listings()
        return {"tokens": potentials[:30], "count": len(potentials)}
    except Exception as e:
        logger.error(f"Potential listing error: {e}")
        return {"tokens": [], "error": str(e)}

@app.get("/api/listing/binance-news")
async def binance_news():
    """Lay thong bao listing moi tu Binance."""
    ls = ctx["listing_scanner"]
    if not ls:
        from analytics.listing_scanner import ListingScanner
        ls = ListingScanner()
    try:
        news = await ls.check_new_binance_listings()
        return {"listings": news}
    except Exception as e:
        return {"listings": [], "error": str(e)}

# ============================================
#  MACRO CALENDAR (Su kien kinh te)
# ============================================

@app.get("/api/macro/calendar")
async def get_macro_calendar(days: int = 30):
    """Lay lich su kien kinh te quan trong (FOMC, CPI, NFP, GDP...)."""
    from analytics.macro_calendar import MacroCalendar
    mc = MacroCalendar()
    try:
        events = await mc.get_all_events(days)
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error(f"Macro calendar error: {e}")
        return {"events": mc.get_builtin_events(days), "count": 0, "fallback": True}
    finally:
        await mc.close()

@app.get("/api/macro/next")
async def get_next_macro_event():
    """Lay su kien CRITICAL/HIGH gan nhat sap dien ra."""
    from analytics.macro_calendar import MacroCalendar
    mc = MacroCalendar()
    try:
        next_event = await mc.get_next_critical()
        return {"event": next_event}
    except Exception as e:
        return {"event": None, "error": str(e)}
    finally:
        await mc.close()

@app.get("/api/macro/risk")
async def get_macro_risk():
    """Danh gia muc do rui ro hien tai dua tren su kien sap toi."""
    from analytics.macro_calendar import MacroCalendar
    mc = MacroCalendar()
    try:
        risk = await mc.assess_risk()
        return risk
    except Exception as e:
        return {"risk_level": "NORMAL", "warnings": [], "error": str(e)}
    finally:
        await mc.close()

# ============================================
#  BACKTESTING ENGINE
# ============================================

class BacktestReq(BaseModel):
    coin: str = "BTC"
    timeframe: str = "1h"
    days: int = 30
    leverage: int = 1
    risk_per_trade: float = 0.02
    sl_pct: float = 0.02
    tp1_pct: float = 0.03
    tp2_pct: float = 0.06
    tp3_pct: float = 0.10
    min_score: int = 3

@app.post("/api/backtest/run")
async def run_backtest(req: BacktestReq):
    """Chay backtest chien luoc TA tren du lieu lich su."""
    try:
        from analytics.backtester import BacktestEngine
        engine = BacktestEngine()
        result = await engine.run(
            symbol=f"{req.coin.upper()}/USDT",
            timeframe=req.timeframe,
            days=req.days,
            leverage=req.leverage,
            risk_per_trade=req.risk_per_trade,
            sl_pct=req.sl_pct,
            tp1_pct=req.tp1_pct,
            tp2_pct=req.tp2_pct,
            tp3_pct=req.tp3_pct,
            min_score=req.min_score,
        )
        return result
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        return {"error": str(e)}

@app.get("/api/backtest/presets")
def get_backtest_presets():
    """Tra ve cac preset chien luoc co san."""
    from analytics.backtester import BacktestEngine
    return {"presets": BacktestEngine.PRESETS}

# ============================================
#  LIMIT ORDERS (Lenh Cho)
# ============================================

# In-memory limit orders (persist to file)
_limit_orders_file = "data/limit_orders.json"

def _load_limit_orders() -> list:
    if os.path.exists(_limit_orders_file):
        try:
            with open(_limit_orders_file) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _save_limit_orders(orders: list):
    os.makedirs(os.path.dirname(_limit_orders_file), exist_ok=True)
    try:
        with open(_limit_orders_file, "w") as f:
            json.dump(orders, f, indent=2)
    except Exception as e:
        logger.error(f"Save limit orders error: {e}")

class LimitOrderReq(BaseModel):
    coin: str = "BTC"
    direction: str = "LONG"
    trigger_price: float
    usdt_size: float = 100
    leverage: int = 1
    expiry_hours: float = 24  # Tu dong huy sau N gio

@app.get("/api/orders/pending")
def get_pending_orders():
    orders = _load_limit_orders()
    # Loc cac lenh het han
    now = datetime.now().isoformat()
    active = [o for o in orders if o.get("status") == "PENDING" and o.get("expires_at", "9") > now]
    return {"orders": active, "count": len(active)}

@app.post("/api/orders/create")
def create_limit_order(req: LimitOrderReq):
    orders = _load_limit_orders()
    
    # Lay gia hien tai de validate
    prices = _get_latest_prices()
    symbol = f"{req.coin.upper()}USDT"
    current_price = prices.get(symbol, {}).get("price", 0)
    
    # Validate: LONG limit phai o duoi gia hien tai, SHORT o tren
    if current_price > 0:
        if req.direction == "LONG" and req.trigger_price >= current_price:
            raise HTTPException(400, f"Gia limit LONG phai thap hon gia hien tai (${current_price:,.2f})")
        if req.direction == "SHORT" and req.trigger_price <= current_price:
            raise HTTPException(400, f"Gia limit SHORT phai cao hon gia hien tai (${current_price:,.2f})")
    
    from datetime import timedelta
    order_id = f"LO_{req.coin.upper()}_{int(_time.time())}"
    now = datetime.now()
    
    order = {
        "id": order_id,
        "coin": req.coin.upper(),
        "direction": req.direction.upper(),
        "trigger_price": req.trigger_price,
        "usdt_size": req.usdt_size,
        "leverage": req.leverage,
        "status": "PENDING",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=req.expiry_hours)).isoformat(),
        "current_price": current_price,
    }
    orders.append(order)
    _save_limit_orders(orders)
    
    logger.info(f"[LimitOrder] Created: {req.direction} {req.coin} @ ${req.trigger_price:,.2f} | Size: ${req.usdt_size}")
    return {"success": True, "order": order}

@app.delete("/api/orders/cancel/{order_id}")
def cancel_limit_order(order_id: str):
    orders = _load_limit_orders()
    for o in orders:
        if o["id"] == order_id and o["status"] == "PENDING":
            o["status"] = "CANCELLED"
            o["cancelled_at"] = datetime.now().isoformat()
            _save_limit_orders(orders)
            logger.info(f"[LimitOrder] Cancelled: {order_id}")
            return {"success": True}
    raise HTTPException(404, "Order not found")

@app.get("/api/orders/filled")
def get_filled_orders():
    orders = _load_limit_orders()
    filled = [o for o in orders if o.get("status") == "FILLED"]
    return {"orders": filled[-30:], "count": len(filled)}

# Background monitor cho Limit Orders
_limit_order_events: list = []

@app.get("/api/orders/events")
def get_order_events():
    """Lay cac su kien limit order vua khop (frontend poll de toast)."""
    events = list(_limit_order_events)
    _limit_order_events.clear()
    return {"events": events}

@app.on_event("startup")
async def start_limit_order_monitor():
    """Background loop kiem tra limit orders moi 3s."""
    async def monitor_loop():
        await asyncio.sleep(8)
        while True:
            try:
                te = ctx.get("trade_engine")
                if te:
                    orders = _load_limit_orders()
                    prices = _get_latest_prices()
                    now = datetime.now().isoformat()
                    changed = False
                    
                    for o in orders:
                        if o["status"] != "PENDING":
                            continue
                        # Het han?
                        if o.get("expires_at", "9") < now:
                            o["status"] = "EXPIRED"
                            changed = True
                            continue
                        
                        symbol = f"{o['coin']}USDT"
                        current = prices.get(symbol, {}).get("price", 0)
                        if current <= 0:
                            continue
                        
                        triggered = False
                        if o["direction"] == "LONG" and current <= o["trigger_price"]:
                            triggered = True
                        elif o["direction"] == "SHORT" and current >= o["trigger_price"]:
                            triggered = True
                        
                        if triggered:
                            pos = te.open_manual_position(
                                coin=o["coin"],
                                direction=o["direction"],
                                usdt_size=o["usdt_size"],
                                leverage=o["leverage"],
                                current_price=current,
                            )
                            if pos:
                                o["status"] = "FILLED"
                                o["filled_at"] = now
                                o["filled_price"] = current
                                changed = True
                                _limit_order_events.append({
                                    "id": o["id"],
                                    "coin": o["coin"],
                                    "direction": o["direction"],
                                    "trigger": o["trigger_price"],
                                    "filled": current,
                                    "size": o["usdt_size"],
                                })
                                logger.success(
                                    f"[LimitOrder] FILLED: {o['direction']} {o['coin']} "
                                    f"@ ${current:,.2f} (trigger: ${o['trigger_price']:,.2f})"
                                )
                    
                    if changed:
                        _save_limit_orders(orders)
            except Exception as e:
                logger.error(f"Limit order monitor error: {e}")
            await asyncio.sleep(3)
    asyncio.create_task(monitor_loop())

# ============================================
#  DCA MODE (Dollar Cost Averaging)
# ============================================

_dca_plans_file = "data/dca_plans.json"

def _load_dca_plans() -> list:
    if os.path.exists(_dca_plans_file):
        try:
            with open(_dca_plans_file) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _save_dca_plans(plans: list):
    os.makedirs(os.path.dirname(_dca_plans_file), exist_ok=True)
    try:
        with open(_dca_plans_file, "w") as f:
            json.dump(plans, f, indent=2)
    except Exception as e:
        logger.error(f"Save DCA plans error: {e}")

class DCACreateReq(BaseModel):
    coin: str = "BTC"
    amount_per_buy: float = 50     # USDT moi lan mua
    interval: str = "daily"        # hourly, daily, weekly
    total_buys: int = 30           # Tong so lan mua (0 = vo han)
    leverage: int = 1

@app.get("/api/dca/plans")
def get_dca_plans():
    plans = _load_dca_plans()
    active = [p for p in plans if p.get("status") in ("ACTIVE", "PAUSED")]
    return {"plans": active, "count": len(active)}

@app.post("/api/dca/create")
def create_dca_plan(req: DCACreateReq):
    plans = _load_dca_plans()
    plan_id = f"DCA_{req.coin.upper()}_{int(_time.time())}"
    
    # Tinh interval seconds
    interval_map = {"hourly": 3600, "daily": 86400, "weekly": 604800}
    interval_sec = interval_map.get(req.interval, 86400)
    
    plan = {
        "id": plan_id,
        "coin": req.coin.upper(),
        "amount_per_buy": req.amount_per_buy,
        "interval": req.interval,
        "interval_sec": interval_sec,
        "total_buys": req.total_buys,
        "leverage": req.leverage,
        "status": "ACTIVE",
        "buys_done": 0,
        "total_invested": 0,
        "avg_entry": 0,
        "prices_bought": [],
        "created_at": datetime.now().isoformat(),
        "last_buy_at": None,
        "next_buy_at": datetime.now().isoformat(),  # Mua ngay lan dau
    }
    plans.append(plan)
    _save_dca_plans(plans)
    
    logger.info(f"[DCA] Created: {req.coin} ${req.amount_per_buy}/{req.interval} x{req.total_buys}")
    return {"success": True, "plan": plan}

@app.post("/api/dca/toggle/{plan_id}")
def toggle_dca_plan(plan_id: str):
    plans = _load_dca_plans()
    for p in plans:
        if p["id"] == plan_id:
            if p["status"] == "ACTIVE":
                p["status"] = "PAUSED"
            elif p["status"] == "PAUSED":
                p["status"] = "ACTIVE"
            _save_dca_plans(plans)
            return {"success": True, "status": p["status"]}
    raise HTTPException(404, "Plan not found")

@app.delete("/api/dca/delete/{plan_id}")
def delete_dca_plan(plan_id: str):
    plans = _load_dca_plans()
    for p in plans:
        if p["id"] == plan_id:
            p["status"] = "DELETED"
            _save_dca_plans(plans)
            return {"success": True}
    raise HTTPException(404, "Plan not found")

@app.get("/api/dca/history")
def get_dca_history():
    plans = _load_dca_plans()
    # Tra ve tat ca plans (ke ca completed) kem lich su mua
    return {"plans": plans, "count": len(plans)}

# Background scheduler cho DCA
@app.on_event("startup")
async def start_dca_scheduler():
    """Background loop thuc hien DCA mua theo lich."""
    async def dca_loop():
        await asyncio.sleep(10)
        while True:
            try:
                te = ctx.get("trade_engine")
                if te:
                    plans = _load_dca_plans()
                    now = datetime.now()
                    now_str = now.isoformat()
                    changed = False
                    
                    for p in plans:
                        if p["status"] != "ACTIVE":
                            continue
                        
                        # Kiem tra da het so lan mua chua
                        if p["total_buys"] > 0 and p["buys_done"] >= p["total_buys"]:
                            p["status"] = "COMPLETED"
                            changed = True
                            continue
                        
                        # Kiem tra da den gio mua chua
                        next_buy = p.get("next_buy_at")
                        if not next_buy or next_buy > now_str:
                            continue
                        
                        # Lay gia hien tai
                        prices = _get_latest_prices()
                        symbol = f"{p['coin']}USDT"
                        current_price = prices.get(symbol, {}).get("price", 0)
                        if current_price <= 0:
                            continue
                        
                        # Check balance
                        margin = p["amount_per_buy"] / p["leverage"]
                        if margin > te.balance:
                            logger.warning(f"[DCA] {p['coin']}: Khong du so du (can ${margin:.2f})")
                            continue
                        
                        # Mo lenh
                        pos = te.open_manual_position(
                            coin=p["coin"],
                            direction="LONG",
                            usdt_size=p["amount_per_buy"],
                            leverage=p["leverage"],
                            current_price=current_price,
                        )
                        
                        if pos:
                            p["buys_done"] += 1
                            p["total_invested"] += p["amount_per_buy"]
                            p["prices_bought"].append({
                                "price": current_price,
                                "amount": p["amount_per_buy"],
                                "time": now_str,
                            })
                            # Tinh avg entry
                            total_qty = sum(b["amount"] / b["price"] for b in p["prices_bought"])
                            total_cost = sum(b["amount"] for b in p["prices_bought"])
                            p["avg_entry"] = round(total_cost / total_qty, 6) if total_qty > 0 else 0
                            
                            p["last_buy_at"] = now_str
                            from datetime import timedelta
                            p["next_buy_at"] = (now + timedelta(seconds=p["interval_sec"])).isoformat()
                            changed = True
                            
                            logger.success(
                                f"[DCA] BUY #{p['buys_done']}: {p['coin']} "
                                f"@ ${current_price:,.2f} | ${p['amount_per_buy']} | "
                                f"Avg: ${p['avg_entry']:,.2f}"
                            )
                    
                    if changed:
                        _save_dca_plans(plans)
            except Exception as e:
                logger.error(f"DCA scheduler error: {e}")
            await asyncio.sleep(30)  # Check moi 30s
    asyncio.create_task(dca_loop())

# ============================================
#  SERVER
# ============================================

async def run_server(port=8000):
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"Web API on port {port}...")
    await server.serve()

