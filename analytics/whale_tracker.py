"""
Whale & Smart Money Tracker — Theo dõi dòng tiền cá mập.

Thu thập dữ liệu miễn phí từ Binance Futures API (qua ccxt):
- Open Interest (OI) changes
- Funding Rate extremes
- Long/Short Ratio (Global + Top Traders)
- Order Book depth analysis (whale walls)
- Liquidation data

Kết hợp thành Whale Score để điều chỉnh tín hiệu trading.
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from aiohttp.resolver import ThreadedResolver
from loguru import logger

try:
    from core.config import Config
except ImportError:
    Config = None


class WhaleTracker:
    """
    Thu thap va phan tich du lieu ca map tu Binance Futures API.

    Cac endpoint dang dung (fundingRate, openInterestHist, longShortRatio,
    topLongShortPositionRatio, takerlongshortRatio, depth) deu la PUBLIC, khong can API key.
    Rieng endpoint liquidation (allForceOrders/forceOrders) la USER_DATA -> can API key,
    nen da bi loai khoi whale score (xem analyze_liquidations).
    """

    BINANCE_FAPI = "https://fapi.binance.com"

    # Thresholds
    FUNDING_EXTREME_HIGH = 0.0005     # 0.05% per 8h = cao bat thuong
    FUNDING_EXTREME_LOW = -0.0003     # -0.03% = thap bat thuong
    FUNDING_CONSECUTIVE = 3           # So ky lien tiep extreme
    OI_SURGE_PCT = 0.05              # OI tang > 5% trong 4h
    OI_DROP_PCT = -0.08              # OI giam > 8% trong 1h
    LS_RETAIL_EXTREME_LONG = 0.75    # 75%+ retail LONG
    LS_RETAIL_EXTREME_SHORT = 0.70   # 70%+ retail SHORT
    WALL_MULT = 10                   # Order book wall = 10x avg level
    FLOW_LARGE_BTC = 500             # > 500 BTC = large transfer
    SIDEWAYS_RANGE_PCT = 3.0         # M6: bien dong gia < 3% trong 4h = sideway

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache = {}
        self._cache_ts = {}
        # M4 fix: dung WHALE_SCAN_INTERVAL tu Config lam TTL cache (truoc day hardcode 120s)
        if Config is not None:
            self._cache_ttl = max(60, int(Config.WHALE_SCAN_INTERVAL))
            self._whale_alert_key = Config.WHALE_ALERT_API_KEY or ""
            self._whale_alert_enabled = bool(self._whale_alert_key)
        else:
            self._cache_ttl = 300
            self._whale_alert_key = ""
            self._whale_alert_enabled = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _is_cached(self, key: str) -> bool:
        return key in self._cache and (time.time() - self._cache_ts.get(key, 0)) < self._cache_ttl

    def _set_cache(self, key: str, value):
        self._cache[key] = value
        self._cache_ts[key] = time.time()

    # ==========================================
    #  DATA FETCHERS (Binance Public API)
    # ==========================================

    async def _fetch_json(self, url: str, params: dict = None) -> Optional[dict | list]:
        """Generic JSON fetcher with error handling."""
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"[Whale] HTTP {resp.status} from {url}")
                    return None
        except Exception as e:
            logger.error(f"[Whale] Fetch error {url}: {e}")
            return None

    async def get_funding_rate(self, symbol: str = "BTCUSDT", limit: int = 10) -> list:
        """Lay lich su funding rate."""
        cache_key = f"funding_{symbol}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": limit}
        )
        result = data or []
        self._set_cache(cache_key, result)
        return result

    async def get_open_interest(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        """Lay Open Interest hien tai."""
        cache_key = f"oi_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/fapi/v1/openInterest",
            {"symbol": symbol}
        )
        self._set_cache(cache_key, data)
        return data

    async def get_oi_history(self, symbol: str = "BTCUSDT", period: str = "5m", limit: int = 48) -> list:
        """Lay lich su Open Interest (4h = 48 candles x 5m)."""
        cache_key = f"oi_hist_{symbol}_{period}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/futures/data/openInterestHist",
            {"symbol": symbol, "period": period, "limit": limit}
        )
        result = data or []
        self._set_cache(cache_key, result)
        return result

    async def get_long_short_ratio(self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 10) -> list:
        """Lay Global Long/Short Account Ratio."""
        cache_key = f"ls_ratio_{symbol}_{period}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period, "limit": limit}
        )
        result = data or []
        self._set_cache(cache_key, result)
        return result

    async def get_top_trader_positions(self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 10) -> list:
        """Lay Top Trader Long/Short Position Ratio."""
        cache_key = f"top_pos_{symbol}_{period}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/futures/data/topLongShortPositionRatio",
            {"symbol": symbol, "period": period, "limit": limit}
        )
        result = data or []
        self._set_cache(cache_key, result)
        return result

    async def get_order_book(self, symbol: str = "BTCUSDT", limit: int = 500) -> Optional[dict]:
        """Lay order book depth."""
        cache_key = f"ob_{symbol}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/fapi/v1/depth",
            {"symbol": symbol, "limit": limit}
        )
        self._set_cache(cache_key, data)
        return data

    async def get_recent_liquidations(self, symbol: str = "BTCUSDT", limit: int = 100) -> list:
        """
        [DEPRECATED - luon tra ve rong] Lay danh sach thanh ly gan day.

        Binance da bo endpoint public nay:
        - /fapi/v1/allForceOrders -> HTTP 404
        - /fapi/v1/forceOrders    -> HTTP 401 (USER_DATA, can API key + chu ky HMAC)
        Giu lai de tham chieu; khong dung trong compute_whale_bias().
        """
        cache_key = f"liq_{symbol}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/fapi/v1/forceOrders",
            {"symbol": symbol, "limit": limit}
        )
        result = data or []
        self._set_cache(cache_key, result)
        return result

    async def get_taker_buy_sell_volume(self, symbol: str = "BTCUSDT", period: str = "5m", limit: int = 12) -> list:
        """Lay Taker Buy/Sell Volume ratio (1h = 12 x 5m)."""
        cache_key = f"taker_{symbol}_{period}_{limit}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/futures/data/takerlongshortRatio",
            {"symbol": symbol, "period": period, "limit": limit}
        )
        result = data or []
        self._set_cache(cache_key, result)
        return result

    # ==========================================
    #  SIGNAL ANALYZERS
    # ==========================================

    async def _fetch_price_context(self, symbol: str = "BTCUSDT", hours: int = 4) -> Optional[dict]:
        """
        M6: Lay boi canh gia tu klines futures PUBLIC (khong can API key)
        de kiem tra "price sideway" khi phan tich Open Interest.

        Returns:
            {"range_pct": % bien dong cao-thap, "trend_pct": % thay doi gia, "close": ...}
            hoac None neu khong du du lieu.
        """
        cache_key = f"px_{symbol}_{hours}h"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        data = await self._fetch_json(
            f"{self.BINANCE_FAPI}/fapi/v1/klines",
            {"symbol": symbol, "interval": "1h", "limit": hours + 1},
        )
        if not isinstance(data, list) or len(data) < 2:
            return None
        try:
            highs = [float(k[2]) for k in data]
            lows = [float(k[3]) for k in data]
            opens = [float(k[1]) for k in data]
            closes = [float(k[4]) for k in data]
        except (IndexError, ValueError, TypeError):
            return None

        close = closes[-1]
        if close <= 0:
            return None
        ctx = {
            "range_pct": (max(highs) - min(lows)) / close * 100,
            "trend_pct": (closes[-1] - opens[0]) / opens[0] * 100 if opens[0] > 0 else 0.0,
            "close": close,
        }
        self._set_cache(cache_key, ctx)
        return ctx

    async def analyze_funding(self, symbol: str = "BTCUSDT") -> dict:
        """
        Phan tich Funding Rate.
        Funding cuc doan = ca map sap dao chieu.
        """
        rates = await self.get_funding_rate(symbol, limit=10)
        if not rates or len(rates) < 3:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong du du lieu funding"}

        # Lay 3 ky gan nhat
        recent = rates[-3:]
        recent_values = []
        for r in recent:
            try:
                recent_values.append(float(r.get("fundingRate", 0)))
            except (ValueError, TypeError):
                recent_values.append(0)

        current_rate = recent_values[-1] if recent_values else 0
        avg_rate = sum(recent_values) / len(recent_values) if recent_values else 0

        # Consecutive extreme check
        high_count = sum(1 for r in recent_values if r > self.FUNDING_EXTREME_HIGH)
        low_count = sum(1 for r in recent_values if r < self.FUNDING_EXTREME_LOW)

        if high_count >= self.FUNDING_CONSECUTIVE:
            return {
                "signal": "FUNDING_EXTREME_HIGH",
                "direction": "SHORT",  # Qua nhieu LONG -> sap dump
                "weight": 2,
                "detail": f"Funding {current_rate:.4%} ({high_count} ky lien tiep cao) → Retail qua LONG, ca map sap dump",
                "funding_rate": current_rate,
            }
        elif low_count >= self.FUNDING_CONSECUTIVE:
            return {
                "signal": "FUNDING_EXTREME_LOW",
                "direction": "LONG",  # Qua nhieu SHORT -> sap pump
                "weight": 2,
                "detail": f"Funding {current_rate:.4%} ({low_count} ky lien tiep am) → Retail qua SHORT, ca map sap pump",
                "funding_rate": current_rate,
            }
        elif abs(current_rate) > self.FUNDING_EXTREME_HIGH:
            dir_hint = "SHORT" if current_rate > 0 else "LONG"
            return {
                "signal": "FUNDING_ELEVATED",
                "direction": dir_hint,
                "weight": 1,
                "detail": f"Funding {current_rate:.4%} cao bat thuong → Canh giac dao chieu",
                "funding_rate": current_rate,
            }

        return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": f"Funding {current_rate:.4%} binh thuong", "funding_rate": current_rate}

    async def analyze_open_interest(self, symbol: str = "BTCUSDT") -> dict:
        """
        Phan tich bien dong Open Interest ket hop boi canh gia (M6).
        - OI surge + gia sideway (range <= SIDEWAYS_RANGE_PCT) = breakout sap den.
        - OI surge nhung gia da bien dong = the da bat dau (khong con pre-breakout).
        - OI drop manh = mass liquidation/exit (kem theo huong gia de biet trend con song khong).
        """
        oi_hist = await self.get_oi_history(symbol, period="5m", limit=48)
        if not oi_hist or len(oi_hist) < 12:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong du du lieu OI"}

        try:
            oi_values = [float(x.get("sumOpenInterest", 0)) for x in oi_hist]
        except (ValueError, TypeError):
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Loi parse OI data"}

        current_oi = oi_values[-1]
        # M6 fix: khi du 48 candles (4h) thi lay oi_values[0]; khi thieu data thi dung earliest available
        oi_4h_ago = oi_values[0]  # earliest available (max 4h ago if 48 candles)
        oi_1h_ago = oi_values[-12] if len(oi_values) >= 12 else oi_values[0]

        if oi_4h_ago > 0:
            oi_change_4h = (current_oi - oi_4h_ago) / oi_4h_ago
        else:
            oi_change_4h = 0

        if oi_1h_ago > 0:
            oi_change_1h = (current_oi - oi_1h_ago) / oi_1h_ago
        else:
            oi_change_1h = 0

        # M6 fix: canh bao truoc khi danh gia OI — docstring noi
        # "OI surge + price sideway = breakout sap den" nhung code truoc day
        # chi dua tren OI, khong kiem tra gia.
        px = await self._fetch_price_context(symbol, hours=4)
        range_pct = px.get("range_pct", 0.0) if px else 0.0
        trend_pct = px.get("trend_pct", 0.0) if px else 0.0
        price_note = f"Gia 4h: range {range_pct:.1f}%, trend {trend_pct:+.1f}%" if px else "Khong co du lieu gia"

        # OI surge (buildup) — breakout imminent (chi khi gia van sideway)
        if oi_change_4h > self.OI_SURGE_PCT:
            if px is None:
                # Khong lay duoc gia -> giu nguyen signal cu (thieu du lieu thi khong chan)
                return {
                    "signal": "OI_SURGE",
                    "direction": "NEUTRAL",  # Khong biet huong breakout
                    "weight": 1,
                    "detail": f"OI tang {oi_change_4h:+.1%} trong 4h → Breakout sap xay ra, ca map dang tich luy lenh ({price_note})",
                    "oi_change_4h": oi_change_4h,
                    "oi_change_1h": oi_change_1h,
                }
            if range_pct <= self.SIDEWAYS_RANGE_PCT:
                return {
                    "signal": "OI_SURGE",
                    "direction": "NEUTRAL",  # Khong biet huong breakout
                    "weight": 1,
                    "detail": (
                        f"OI tang {oi_change_4h:+.1%} trong 4h + gia sideway (range {range_pct:.1f}%) "
                        f"→ Breakout sap xay ra, ca map dang tich luy lenh"
                    ),
                    "oi_change_4h": oi_change_4h,
                    "oi_change_1h": oi_change_1h,
                    "price_range_pct": range_pct,
                }
            # Gia da bien dong manh → breakout co the DA xay ra, khong con "sap den"
            return {
                "signal": None,
                "direction": "NEUTRAL",
                "weight": 0,
                "detail": (
                    f"OI tang {oi_change_4h:+.1%} nhung gia da bien dong {range_pct:.1f}% "
                    f"trong 4h ({trend_pct:+.1f}%) → The da bat dau, khong con pre-breakout"
                ),
                "oi_change_4h": oi_change_4h,
                "oi_change_1h": oi_change_1h,
                "price_range_pct": range_pct,
                "price_trend_pct": trend_pct,
            }

        # OI drop (mass exit/liquidation) — bo sung boi canh gia de biet trend con song khong
        if oi_change_1h < self.OI_DROP_PCT:
            if px is not None and trend_pct < 0:
                detail = (
                    f"OI giam {oi_change_1h:+.1%} trong 1h + gia giam {trend_pct:+.1f}% "
                    f"→ Mass liquidation/exit, trend het luc"
                )
            elif px is not None:
                detail = (
                    f"OI giam {oi_change_1h:+.1%} trong 1h nhung gia van tang {trend_pct:+.1f}% "
                    f"→ Short squeeze, xu huong con song"
                )
            else:
                detail = f"OI giam {oi_change_1h:+.1%} trong 1h → Mass liquidation/exit, trend het luc"
            return {
                "signal": "OI_DUMP",
                "direction": "NEUTRAL",  # Trend hien tai het luc
                "weight": 2,
                "detail": detail + f" ({price_note})",
                "oi_change_4h": oi_change_4h,
                "oi_change_1h": oi_change_1h,
                "price_trend_pct": trend_pct,
            }

        return {
            "signal": None, "direction": "NEUTRAL", "weight": 0,
            "detail": f"OI binh thuong (4h: {oi_change_4h:+.1%}, 1h: {oi_change_1h:+.1%})",
            "oi_change_4h": oi_change_4h, "oi_change_1h": oi_change_1h,
        }

    async def analyze_long_short(self, symbol: str = "BTCUSDT") -> dict:
        """
        Phan tich Long/Short Ratio.
        Retail thien lech → ca map thuong trade nguoc.
        So sanh global ratio vs top trader ratio.
        """
        global_ls = await self.get_long_short_ratio(symbol, period="1h", limit=5)
        top_ls = await self.get_top_trader_positions(symbol, period="1h", limit=5)

        if not global_ls:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong du du lieu L/S"}

        try:
            latest_global = float(global_ls[-1].get("longShortRatio", 1.0))
            global_long_pct = float(global_ls[-1].get("longAccount", 0.5))
        except (ValueError, TypeError, IndexError):
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Loi parse L/S data"}

        # Top trader data
        top_long_pct = 0.5
        if top_ls:
            try:
                top_long_pct = float(top_ls[-1].get("longAccount", 0.5))
            except (ValueError, TypeError):
                pass

        signals = []

        # Retail extreme
        if global_long_pct > self.LS_RETAIL_EXTREME_LONG:
            signals.append({
                "signal": "RETAIL_OVERLEVERAGED_LONG",
                "direction": "SHORT",
                "weight": 2,
                "detail": f"Retail {global_long_pct:.0%} LONG → Ca map sap dump de thanh ly",
            })
        elif (1 - global_long_pct) > self.LS_RETAIL_EXTREME_SHORT:
            signals.append({
                "signal": "RETAIL_OVERLEVERAGED_SHORT",
                "direction": "LONG",
                "weight": 2,
                "detail": f"Retail {(1 - global_long_pct):.0%} SHORT → Ca map sap pump de thanh ly",
            })

        # Smart money divergence
        divergence = top_long_pct - global_long_pct
        if abs(divergence) > 0.10:  # > 10% divergence
            smart_dir = "LONG" if divergence > 0 else "SHORT"
            signals.append({
                "signal": "SMART_MONEY_DIVERGENCE",
                "direction": smart_dir,
                "weight": 3,
                "detail": (
                    f"Top Traders: {top_long_pct:.0%} LONG vs Retail: {global_long_pct:.0%} LONG "
                    f"→ Smart Money dang {smart_dir}, theo chan ca map"
                ),
            })

        if signals:
            # Tra ve signal manh nhat
            best = max(signals, key=lambda s: s["weight"])
            best["global_long_pct"] = global_long_pct
            best["top_long_pct"] = top_long_pct
            return best

        return {
            "signal": None, "direction": "NEUTRAL", "weight": 0,
            "detail": f"L/S ratio binh thuong (Retail Long: {global_long_pct:.0%}, Top: {top_long_pct:.0%})",
            "global_long_pct": global_long_pct, "top_long_pct": top_long_pct,
        }

    async def analyze_order_book(self, symbol: str = "BTCUSDT") -> dict:
        """
        Phan tich order book depth.
        Phat hien tuong mua/ban lon (whale walls).
        """
        ob = await self.get_order_book(symbol, limit=500)
        if not ob or "bids" not in ob or "asks" not in ob:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong co du lieu order book"}

        try:
            bids = [(float(p), float(q)) for p, q in ob["bids"][:200]]
            asks = [(float(p), float(q)) for p, q in ob["asks"][:200]]
        except (ValueError, TypeError):
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Loi parse order book"}

        if not bids or not asks:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Order book rong"}

        # Tinh avg qty
        avg_bid_qty = sum(q for _, q in bids) / len(bids)
        avg_ask_qty = sum(q for _, q in asks) / len(asks)

        # Tim walls
        bid_walls = [(p, q) for p, q in bids if q > avg_bid_qty * self.WALL_MULT]
        ask_walls = [(p, q) for p, q in asks if q > avg_ask_qty * self.WALL_MULT]

        # Tong volume 2 phia
        total_bid_vol = sum(p * q for p, q in bids[:100])
        total_ask_vol = sum(p * q for p, q in asks[:100])
        imbalance = (total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol) if (total_bid_vol + total_ask_vol) > 0 else 0

        signals = []

        if bid_walls:
            largest_wall = max(bid_walls, key=lambda x: x[1])
            signals.append({
                "signal": "BID_WALL",
                "direction": "LONG",
                "weight": 1,
                "detail": f"Tuong mua lon tai ${largest_wall[0]:,.1f} ({largest_wall[1]:.2f} BTC, {largest_wall[1]/avg_bid_qty:.0f}x avg) → Ca map do gia",
            })

        if ask_walls:
            largest_wall = max(ask_walls, key=lambda x: x[1])
            signals.append({
                "signal": "ASK_WALL",
                "direction": "SHORT",
                "weight": 1,
                "detail": f"Tuong ban lon tai ${largest_wall[0]:,.1f} ({largest_wall[1]:.2f} BTC, {largest_wall[1]/avg_ask_qty:.0f}x avg) → Ca map chan gia",
            })

        # Imbalance analysis
        if abs(imbalance) > 0.3:
            dir_hint = "LONG" if imbalance > 0 else "SHORT"
            signals.append({
                "signal": "ORDER_BOOK_IMBALANCE",
                "direction": dir_hint,
                "weight": 2,
                "detail": f"Order book lech {imbalance:+.0%} {'mua' if imbalance > 0 else 'ban'} → Ap luc {'tang' if imbalance > 0 else 'giam'} gia",
            })

        if signals:
            best = max(signals, key=lambda s: s["weight"])
            best["imbalance"] = round(imbalance, 3)
            best["bid_walls_count"] = len(bid_walls)
            best["ask_walls_count"] = len(ask_walls)
            return best

        return {
            "signal": None, "direction": "NEUTRAL", "weight": 0,
            "detail": f"Order book can bang (imbalance: {imbalance:+.1%})",
            "imbalance": round(imbalance, 3),
        }

    async def analyze_liquidations(self, symbol: str = "BTCUSDT") -> dict:
        """
        [DEPRECATED - khong con duoc goi tu compute_whale_bias] Phan tich du lieu thanh ly.
        Liquidation cascade = vung gia da bi quet → ca map da lay thanh khoan.

        Ly do loai bo: endpoint liquidation cua Binance la USER_DATA (can API key),
        khong the lay bang public API nhu cac analyzer khac.
        """
        liqs = await self.get_recent_liquidations(symbol, limit=100)
        if not liqs:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong co du lieu liquidation"}

        now = time.time() * 1000  # ms
        one_hour = 3600 * 1000

        # Loc thanh ly trong 1h qua
        recent_liqs = []
        for liq in liqs:
            try:
                liq_time = int(liq.get("time", 0))
                if now - liq_time < one_hour:
                    recent_liqs.append({
                        "side": liq.get("side", ""),
                        "price": float(liq.get("price", 0)),
                        "qty": float(liq.get("origQty", 0)),
                        "time": liq_time,
                    })
            except (ValueError, TypeError):
                continue

        if not recent_liqs:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong co thanh ly trong 1h qua"}

        long_liq_vol = sum(l["price"] * l["qty"] for l in recent_liqs if l["side"] == "SELL")  # Long bi thanh ly = sell
        short_liq_vol = sum(l["price"] * l["qty"] for l in recent_liqs if l["side"] == "BUY")  # Short bi thanh ly = buy
        total_liq = long_liq_vol + short_liq_vol

        # Neu thanh ly lon > $5M trong 1h
        if total_liq > 5_000_000:
            dominant_side = "LONG_LIQUIDATED" if long_liq_vol > short_liq_vol else "SHORT_LIQUIDATED"
            # Sau khi thanh ly xong, gia thuong dao nguoc (ca map da quet xong)
            reversal_dir = "LONG" if dominant_side == "LONG_LIQUIDATED" else "SHORT"
            return {
                "signal": "LIQUIDATION_CASCADE",
                "direction": reversal_dir,
                "weight": 2,
                "detail": (
                    f"Thanh ly lon trong 1h: ${total_liq/1e6:.1f}M "
                    f"(LONG: ${long_liq_vol/1e6:.1f}M, SHORT: ${short_liq_vol/1e6:.1f}M) "
                    f"→ Ca map da quet {dominant_side.split('_')[0]}, xu huong sap dao chieu sang {reversal_dir}"
                ),
                "total_liq_usd": total_liq,
                "long_liq_usd": long_liq_vol,
                "short_liq_usd": short_liq_vol,
            }

        return {
            "signal": None, "direction": "NEUTRAL", "weight": 0,
            "detail": f"Thanh ly binh thuong trong 1h: ${total_liq/1e6:.1f}M",
            "total_liq_usd": total_liq,
        }

    async def analyze_external_whale_flows(self, symbol: str = "BTCUSDT") -> dict:
        """
        [OPTIONAL] Phan tich dong tien ca map tu whale-alert.io.

        Chi chay khi Config.WHALE_ALERT_API_KEY duoc cau hinh (free tier: 10 calls/min).
        Logic: tien lon RUT KHOI san (outflow) = tich luy → BULLISH;
               tien lon CHAY VAO san (inflow) = chuan bi xa hang → BEARISH.
        """
        if not self._whale_alert_enabled:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0,
                    "detail": "Whale alert khong bat (thieu WHALE_ALERT_API_KEY)"}

        # whale-alert.io chi ho tro mot so blockchain/currency
        coin = symbol.replace("USDT", "").lower()
        if coin not in ("btc", "eth", "sol"):
            return {"signal": None, "direction": "NEUTRAL", "weight": 0,
                    "detail": f"Whale alert khong ho tro {coin.upper()}"}

        start = int(time.time()) - 3600  # 1h qua
        data = await self._fetch_json(
            "https://api.whale-alert.io/v1/transactions",
            {
                "api_key": self._whale_alert_key,
                "min_value": 5_000_000,   # >= $5M
                "start": start,
                "currency": coin,
            },
        )
        if not isinstance(data, dict) or data.get("result") != "success":
            return {"signal": None, "direction": "NEUTRAL", "weight": 0,
                    "detail": "Whale alert khong tra ve du lieu"}

        inflow = 0.0   # chay vao san
        outflow = 0.0  # roi khoi san
        for tx in data.get("transactions", []):
            try:
                amount_usd = float(tx.get("amount_usd", 0) or 0)
            except (TypeError, ValueError):
                continue
            from_type = str((tx.get("from") or {}).get("owner_type", "")).lower()
            to_type = str((tx.get("to") or {}).get("owner_type", "")).lower()
            if to_type == "exchange":
                inflow += amount_usd
            elif from_type == "exchange":
                outflow += amount_usd

        net = outflow - inflow
        detail = (
            f"Whale-alert 1h: ra khoi san ${outflow/1e6:.1f}M | vao san ${inflow/1e6:.1f}M "
            f"| net {net/1e6:+.1f}M"
        )

        if net >= 50_000_000:
            return {"signal": "EXCHANGE_OUTFLOW", "direction": "LONG", "weight": 2,
                    "detail": detail + " → Tien lon roi khoi san, tich luy", "net_flow_usd": net}
        if net <= -50_000_000:
            return {"signal": "EXCHANGE_INFLOW", "direction": "SHORT", "weight": 2,
                    "detail": detail + " → Tien lon chay vao san, chuan bi xa hang", "net_flow_usd": net}
        return {"signal": None, "direction": "NEUTRAL", "weight": 0,
                "detail": detail, "net_flow_usd": net}

    async def analyze_taker_volume(self, symbol: str = "BTCUSDT") -> dict:
        """
        Phan tich Taker Buy/Sell Volume.
        Taker buy dominance = buyers aggressive → bullish.
        """
        data = await self.get_taker_buy_sell_volume(symbol, period="5m", limit=12)
        if not data or len(data) < 3:
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Khong du du lieu taker volume"}

        try:
            ratios = [float(x.get("buySellRatio", 1.0)) for x in data[-6:]]
        except (ValueError, TypeError):
            return {"signal": None, "direction": "NEUTRAL", "weight": 0, "detail": "Loi parse taker data"}

        avg_ratio = sum(ratios) / len(ratios)

        if avg_ratio > 1.3:
            return {
                "signal": "TAKER_BUY_DOMINANT",
                "direction": "LONG",
                "weight": 1,
                "detail": f"Taker Buy/Sell ratio {avg_ratio:.2f} → Buyers dang aggressive, momentum tang",
                "buy_sell_ratio": avg_ratio,
            }
        elif avg_ratio < 0.7:
            return {
                "signal": "TAKER_SELL_DOMINANT",
                "direction": "SHORT",
                "weight": 1,
                "detail": f"Taker Buy/Sell ratio {avg_ratio:.2f} → Sellers dang aggressive, momentum giam",
                "buy_sell_ratio": avg_ratio,
            }

        return {
            "signal": None, "direction": "NEUTRAL", "weight": 0,
            "detail": f"Taker volume can bang (ratio: {avg_ratio:.2f})",
            "buy_sell_ratio": avg_ratio,
        }

    # ==========================================
    #  COMPOSITE WHALE SCORE
    # ==========================================

    async def compute_whale_bias(self, symbol: str = "BTCUSDT") -> dict:
        """
        Tong hop TAT CA whale indicators thanh 1 whale bias.
        Chay song song tat ca analyzers de toi uu thoi gian.

        Returns:
            {
                "whale_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
                "whale_confidence": 0.0 - 1.0,
                "signals": [...],
                "warnings": [...],
                "rating_adjust": -2 to +2,
                "detail_summary": "...",
            }
        """
        try:
            # Chay song song tat ca analyzers dung endpoint PUBLIC cua Binance.
            # M1 fix: analyze_liquidations() da bi loai vi endpoint
            # /fapi/v1/allForceOrders (404) va /fapi/v1/forceOrders (401 - can API key)
            # deu khong lay duoc du lieu, gay spam log moi chu ky ma khong co tac dung.
            analyzers = [
                self.analyze_funding(symbol),
                self.analyze_open_interest(symbol),
                self.analyze_long_short(symbol),
                self.analyze_order_book(symbol),
                self.analyze_taker_volume(symbol),
            ]
            # Optional: whale-alert.io (chi khi co WHALE_ALERT_API_KEY)
            if self._whale_alert_enabled:
                analyzers.append(self.analyze_external_whale_flows(symbol))

            results = await asyncio.gather(*analyzers, return_exceptions=True)

            active_signals = []
            warnings = []
            bull_weight = 0
            bear_weight = 0

            for res in results:
                if isinstance(res, Exception):
                    logger.warning(f"[Whale] Analyzer error: {res}")
                    continue
                if not isinstance(res, dict):
                    continue

                if res.get("signal"):
                    active_signals.append(res)
                    direction = res.get("direction", "NEUTRAL")
                    weight = res.get("weight", 0)

                    if direction == "LONG":
                        bull_weight += weight
                    elif direction == "SHORT":
                        bear_weight += weight

                    # Warnings cho signals quan trong
                    if weight >= 2:
                        warnings.append(res.get("detail", ""))

            # Determine bias
            net_weight = bull_weight - bear_weight
            total_weight = bull_weight + bear_weight

            if net_weight >= 3:
                whale_bias = "BULLISH"
                rating_adjust = 2
            elif net_weight >= 1:
                whale_bias = "BULLISH"
                rating_adjust = 1
            elif net_weight <= -3:
                whale_bias = "BEARISH"
                rating_adjust = -2
            elif net_weight <= -1:
                whale_bias = "BEARISH"
                rating_adjust = -1
            else:
                whale_bias = "NEUTRAL"
                rating_adjust = 0

            confidence = min(1.0, total_weight / 8) if total_weight > 0 else 0.0

            # Summary
            detail_parts = [s.get("detail", "") for s in active_signals if s.get("detail")]
            detail_summary = " | ".join(detail_parts[:3]) if detail_parts else "Khong co tin hieu ca map dac biet"

            result = {
                "whale_bias": whale_bias,
                "whale_confidence": round(confidence, 2),
                "signals": active_signals,
                "warnings": warnings,
                "rating_adjust": rating_adjust,
                "bull_weight": bull_weight,
                "bear_weight": bear_weight,
                "detail_summary": detail_summary,
                "timestamp": datetime.now().isoformat(),
            }

            logger.info(
                f"[Whale] {symbol}: {whale_bias} (conf={confidence:.0%}) | "
                f"Bull={bull_weight} Bear={bear_weight} | "
                f"Active signals: {len(active_signals)}"
            )
            return result

        except Exception as e:
            logger.error(f"[Whale] compute_whale_bias error: {e}")
            return {
                "whale_bias": "NEUTRAL",
                "whale_confidence": 0,
                "signals": [],
                "warnings": [],
                "rating_adjust": 0,
                "detail_summary": f"Loi: {str(e)[:100]}",
            }
