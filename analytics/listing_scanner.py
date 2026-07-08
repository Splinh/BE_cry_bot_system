"""
CEX Listing Scanner - Phat hien token sap len san CEX.
Quet thong bao tu Binance, Gate.io, MEXC, Kucoin, CoinGecko.
Khi phat hien listing moi -> thong bao Telegram de mua som tren DEX.
"""
import asyncio
import re
import aiohttp
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from aiohttp.resolver import ThreadedResolver

from notifiers.telegram_bot import TelegramNotifier
from core.config import Config


# ==================================================
# NGUON DU LIEU LISTING
# ==================================================
LISTING_SOURCES = {
    "binance": {
        "name": "Binance",
        "announce_url": "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
        "tier": 1,  # San lon nhat -> pump manh nhat
    },
    "coinbase": {
        "name": "Coinbase",
        "tier": 1,
    },
    "gate": {
        "name": "Gate.io",
        "api_url": "https://api.gateio.ws/api/v4/spot/currency_pairs",
        "tier": 2,  # Thuong list TRUOC Binance
    },
    "mexc": {
        "name": "MEXC",
        "api_url": "https://api.mexc.com/api/v3/exchangeInfo",
        "tier": 2,  # Thuong list TRUOC Binance
    },
    "kucoin": {
        "name": "Kucoin",
        "tier": 2,
    },
}


class ListingScanner:
    """
    Quet va phat hien token sap len san CEX.
    Chien luoc: Tim token da list tren san nho (Gate, MEXC) nhung chua co tren Binance
    -> Kha nang cao se len Binance -> Mua truoc tren DEX.
    """

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.notifier = TelegramNotifier()
        self.known_binance: set = set()
        self.known_gate: set = set()
        self.known_mexc: set = set()
        self._running = False
        self._task = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=20),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ==================================================
    # LAY DANH SACH TOKEN TREN TUNG SAN
    # ==================================================

    async def get_binance_pairs(self) -> set:
        """Lay danh sach tat ca trading pair tren Binance."""
        session = await self._get_session()
        try:
            url = "https://api.binance.com/api/v3/exchangeInfo"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    symbols = set()
                    for s in data.get("symbols", []):
                        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                            symbols.add(s["baseAsset"])
                    return symbols
        except Exception as e:
            logger.error(f"Binance pairs error: {e}")
        return set()

    async def get_gate_pairs(self) -> set:
        """Lay danh sach trading pair tren Gate.io."""
        session = await self._get_session()
        try:
            url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    symbols = set()
                    for pair in data:
                        if pair.get("trade_status") == "tradable" and "_USDT" in pair.get("id", ""):
                            base = pair["id"].split("_")[0]
                            symbols.add(base)
                    return symbols
        except Exception as e:
            logger.error(f"Gate pairs error: {e}")
        return set()

    async def get_mexc_pairs(self) -> set:
        """Lay danh sach trading pair tren MEXC."""
        session = await self._get_session()
        try:
            url = "https://api.mexc.com/api/v3/exchangeInfo"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    symbols = set()
                    for s in data.get("symbols", []):
                        if s.get("status") == "1" and s.get("quoteAsset") == "USDT":
                            symbols.add(s["baseAsset"])
                    return symbols
        except Exception as e:
            logger.error(f"MEXC pairs error: {e}")
        return set()

    async def get_binance_announcements(self) -> list[dict]:
        """Lay thong bao listing moi tu Binance."""
        session = await self._get_session()
        try:
            url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
            payload = {
                "type": 1,
                "catalogId": 48,  # New listing category
                "pageNo": 1,
                "pageSize": 10,
            }
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    articles = data.get("data", {}).get("catalogs", [{}])[0].get("articles", [])
                    results = []
                    for a in articles:
                        title = a.get("title", "")
                        # Tim ten token trong tieu de
                        tokens = re.findall(r'\(([A-Z]{2,10})\)', title)
                        results.append({
                            "title": title,
                            "tokens": tokens,
                            "time": a.get("releaseDate"),
                            "url": f"https://www.binance.com/en/support/announcement/{a.get('code', '')}",
                        })
                    return results
        except Exception as e:
            logger.error(f"Binance announcements error: {e}")
        return []

    async def get_coingecko_new(self) -> list[dict]:
        """Lay token moi duoc add tren CoinGecko (thuong list CEX som)."""
        session = await self._get_session()
        try:
            url = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # CoinGecko tra ve tat ca coins, lay 50 cuoi (moi nhat)
                    return data[-50:] if len(data) > 50 else data
        except Exception as e:
            logger.error(f"CoinGecko error: {e}")
        return []

    # ==================================================
    # PHAT HIEN TOKEN SAP LEN SAN LON
    # ==================================================

    async def _enrich_token_links(self, token: dict) -> dict:
        """
        Enrich 1 token voi links tu CoinGecko + exchange trade URLs.
        """
        symbol = token["symbol"]
        links = {}

        # 1. Exchange trade links (direct buy)
        on_exchanges = token.get("on_exchanges", [])
        if "Gate.io" in on_exchanges:
            links["gate_trade"] = f"https://www.gate.io/trade/{symbol}_USDT"
        if "MEXC" in on_exchanges:
            links["mexc_trade"] = f"https://www.mexc.com/exchange/{symbol}_USDT"

        # 2. CoinGecko search for project links
        try:
            session = await self._get_session()
            search_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    coins = data.get("coins", [])
                    # Tim coin co symbol match (case-insensitive)
                    matched = None
                    for c in coins:
                        if c.get("symbol", "").upper() == symbol.upper():
                            matched = c
                            break
                    if not matched and coins:
                        matched = coins[0]  # fallback to first result

                    if matched:
                        cg_id = matched.get("id", "")
                        links["coingecko"] = f"https://www.coingecko.com/en/coins/{cg_id}"

                        # Lay chi tiet de co website, twitter, telegram
                        detail_url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false"
                        async with session.get(detail_url) as detail_resp:
                            if detail_resp.status == 200:
                                detail = await detail_resp.json()
                                homepage = detail.get("links", {}).get("homepage", [])
                                if homepage and homepage[0]:
                                    links["website"] = homepage[0]

                                twitter = detail.get("links", {}).get("twitter_screen_name", "")
                                if twitter:
                                    links["twitter"] = f"https://x.com/{twitter}"

                                tg = detail.get("links", {}).get("telegram_channel_identifier", "")
                                if tg:
                                    links["telegram"] = f"https://t.me/{tg}"

                                chat_urls = detail.get("links", {}).get("chat_url", [])
                                if chat_urls:
                                    for url in chat_urls:
                                        if url and "discord" in url:
                                            links["discord"] = url
                                            break
        except Exception as e:
            logger.debug(f"CoinGecko enrich error for {symbol}: {e}")

        token["links"] = links
        return token

    async def find_potential_listings(self) -> list[dict]:
        """
        Tim token co kha nang sap len Binance/Coinbase:
        - Da co tren Gate.io hoac MEXC (san nho list truoc)
        - Chua co tren Binance
        -> Kha nang cao Binance se list -> Mua truoc!
        """
        logger.info("Dang quet danh sach token tren cac san...")

        # Lay danh sach tu 3 san song song
        binance_task = asyncio.create_task(self.get_binance_pairs())
        gate_task = asyncio.create_task(self.get_gate_pairs())
        mexc_task = asyncio.create_task(self.get_mexc_pairs())

        binance = await binance_task
        gate = await gate_task
        mexc = await mexc_task

        logger.info(f"Binance: {len(binance)} | Gate: {len(gate)} | MEXC: {len(mexc)} pairs")

        # Tim token co tren Gate/MEXC nhung CHUA co tren Binance
        gate_only = gate - binance
        mexc_only = mexc - binance
        both_not_binance = (gate & mexc) - binance  # Co tren CA HAI nhung chua Binance = xac suat cao nhat

        results = []

        # Uu tien: Co tren CA HAI Gate + MEXC -> kha nang len Binance cao nhat
        for token in both_not_binance:
            results.append({
                "symbol": token,
                "on_exchanges": ["Gate.io", "MEXC"],
                "not_on": "Binance",
                "confidence": "CAO",
                "score": 90,
                "reason": "Da co tren Gate.io VA MEXC, chua len Binance",
            })

        # Token chi co tren Gate (thuong list som hon)
        for token in gate_only - both_not_binance:
            results.append({
                "symbol": token,
                "on_exchanges": ["Gate.io"],
                "not_on": "Binance",
                "confidence": "TRUNG BINH",
                "score": 60,
                "reason": "Co tren Gate.io, chua len Binance",
            })

        # Token chi co tren MEXC
        for token in mexc_only - both_not_binance:
            results.append({
                "symbol": token,
                "on_exchanges": ["MEXC"],
                "not_on": "Binance",
                "confidence": "TRUNG BINH",
                "score": 55,
                "reason": "Co tren MEXC, chua len Binance",
            })

        # Sort theo score
        results.sort(key=lambda x: x["score"], reverse=True)

        # Loc stablecoin va token pho bien
        skip = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USD", "EUR", "GBP", "BTC", "ETH"}
        results = [r for r in results if r["symbol"] not in skip]

        # Enrich top 30 tokens voi contact links tu CoinGecko
        top_tokens = results[:30]
        enriched = []
        for i, token in enumerate(top_tokens):
            try:
                token = await self._enrich_token_links(token)
            except Exception as e:
                logger.debug(f"Enrich skip {token['symbol']}: {e}")
                token["links"] = {}
            enriched.append(token)
            # Rate limit - delay nho giua cac request
            if i < len(top_tokens) - 1:
                await asyncio.sleep(0.3)

        # Ghep lai: enriched top 30 + phan con lai (khong enrich)
        remaining = results[30:]
        for r in remaining:
            r["links"] = {}
        
        return enriched + remaining

    async def check_new_binance_listings(self) -> list[dict]:
        """Kiem tra thong bao listing moi tu Binance."""
        announcements = await self.get_binance_announcements()

        new_listings = []
        for ann in announcements:
            title_lower = ann["title"].lower()
            if "will list" in title_lower or "new listing" in title_lower or "adds" in title_lower:
                for token in ann["tokens"]:
                    new_listings.append({
                        "symbol": token,
                        "exchange": "Binance",
                        "title": ann["title"],
                        "url": ann["url"],
                        "time": ann.get("time"),
                        "alert": "BINANCE LISTING - MUA NGAY TREN DEX!",
                    })

        return new_listings

    # ==================================================
    # GIAM SAT LIEN TUC (DAEMON)
    # ==================================================

    async def _monitor_loop(self, check_interval: int = 300):
        """
        Vong lap giam sat listing moi moi 5 phut.
        Khi phat hien Binance listing moi -> gui canh bao Telegram.
        """
        # Lan dau: luu danh sach hien tai
        self.known_binance = await self.get_binance_pairs()
        logger.info(f"Listing Monitor: Da luu {len(self.known_binance)} Binance pairs")

        while self._running:
            try:
                await asyncio.sleep(check_interval)

                # Kiem tra Binance pairs moi
                current = await self.get_binance_pairs()
                new_pairs = current - self.known_binance

                if new_pairs:
                    for token in new_pairs:
                        msg = f"\U0001f6a8\U0001f6a8 <b>BINANCE LISTING MOI!</b>\n"
                        msg += "\u2501" * 18 + "\n"
                        msg += f"\U0001fa99 <b>Token:</b> {token}\n"
                        msg += f"\U0001f4c5 <b>Thoi gian:</b> {datetime.now().strftime('%H:%M %d/%m')}\n"
                        msg += "\u2501" * 18 + "\n"
                        msg += "Token moi len Binance!\n"
                        msg += f"Go <code>/check {token}</code> de phan tich."
                        await self.notifier.send_message(msg)
                        logger.warning(f"NEW BINANCE LISTING: {token}")

                    self.known_binance = current

                # Kiem tra announcements
                new_ann = await self.check_new_binance_listings()
                if new_ann:
                    for ann in new_ann[:3]:
                        msg = f"\U0001f6a8 <b>THONG BAO LISTING!</b>\n"
                        msg += "\u2501" * 18 + "\n"
                        msg += f"\U0001fa99 <b>{ann['symbol']}</b> sap len {ann['exchange']}!\n"
                        msg += f"\U0001f4f0 {ann['title'][:80]}\n"
                        msg += f"\U0001f517 <a href='{ann['url']}'>Doc thong bao</a>\n"
                        msg += "\u2501" * 18 + "\n"
                        msg += "MUA SOM TREN DEX TRUOC KHI PUMP!"
                        await self.notifier.send_message(msg)

            except Exception as e:
                logger.error(f"Monitor error: {e}")

    def start_monitor(self, interval: int = 300):
        """Bat dau giam sat (background)."""
        if not self._running:
            self._running = True
            self._task = asyncio.ensure_future(self._monitor_loop(interval))
            logger.info(f"Listing Monitor khoi dong (kiem tra moi {interval}s)")

    def stop_monitor(self):
        self._running = False
        if self._task:
            self._task.cancel()
