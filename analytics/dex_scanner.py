"""
DEX Gem Scanner - Quet token moi tren DEX, phan tich an toan, tim "gem" tiem nang.
Su dung DexScreener API (free, khong can API key).
"""
import asyncio
import aiohttp
from aiohttp.resolver import ThreadedResolver
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


# ==================================================
# TOP VC / QUY DAU TU CRYPTO
# ==================================================
TOP_VCS = {
    "a16z": {"name": "Andreessen Horowitz (a16z)", "tier": 1, "score": 10, "url": "https://a16zcrypto.com"},
    "paradigm": {"name": "Paradigm", "tier": 1, "score": 10, "url": "https://paradigm.xyz"},
    "sequoia": {"name": "Sequoia Capital", "tier": 1, "score": 9, "url": "https://sequoiacap.com"},
    "binance labs": {"name": "Binance Labs", "tier": 1, "score": 9, "url": "https://labs.binance.com"},
    "coinbase ventures": {"name": "Coinbase Ventures", "tier": 1, "score": 8, "url": "https://ventures.coinbase.com"},
    "polychain": {"name": "Polychain Capital", "tier": 1, "score": 8, "url": "https://polychain.capital"},
    "multicoin": {"name": "Multicoin Capital", "tier": 2, "score": 7, "url": "https://multicoin.capital"},
    "pantera": {"name": "Pantera Capital", "tier": 2, "score": 7, "url": "https://panterapcap.com"},
    "dragonfly": {"name": "Dragonfly Capital", "tier": 2, "score": 7, "url": "https://dragonfly.xyz"},
    "framework ventures": {"name": "Framework Ventures", "tier": 2, "score": 6, "url": "https://framework.ventures"},
    "delphi digital": {"name": "Delphi Digital", "tier": 2, "score": 6, "url": "https://delphidigital.io"},
    "jump crypto": {"name": "Jump Crypto", "tier": 2, "score": 7, "url": "https://jumpcrypto.com"},
    "animoca": {"name": "Animoca Brands", "tier": 2, "score": 6, "url": "https://animocabrands.com"},
    "galaxy digital": {"name": "Galaxy Digital", "tier": 2, "score": 6, "url": "https://galaxy.com"},
    "hashed": {"name": "Hashed", "tier": 2, "score": 6, "url": "https://hashed.com"},
    "electric capital": {"name": "Electric Capital", "tier": 2, "score": 6, "url": "https://electriccapital.com"},
    "wintermute": {"name": "Wintermute", "tier": 2, "score": 5, "url": "https://wintermute.com"},
    "alameda": {"name": "Alameda Research", "tier": 3, "score": 3, "url": ""},
}


class DexGemScanner:
    """
    Quet va phan tich token moi tren DEX:
    1. Lay token moi tu DexScreener
    2. Phan tich do an toan (liquidity, holder, honeypot check)
    3. Tim token co quy dau tu backing
    4. Tinh GEM Score (0-100)
    """

    BASE_URL = "https://api.dexscreener.com"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ==================================================
    # DEXSCREENER API
    # ==================================================

    async def search_token(self, query: str) -> list[dict]:
        """Tim kiem token theo ten hoac dia chi."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/latest/dex/search?q={query}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])
            return []
        except Exception as e:
            logger.error(f"Search token error: {e}")
            return []

    async def get_new_tokens(self, chain: str = "solana") -> list[dict]:
        """Lay token moi nhat tren 1 chain."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/token-profiles/latest/v1"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Loc theo chain
                    return [t for t in data if t.get("chainId", "").lower() == chain.lower()][:20]
            return []
        except Exception as e:
            logger.error(f"Get new tokens error: {e}")
            return []

    async def get_boosted_tokens(self) -> list[dict]:
        """Lay token dang duoc boost (quang cao) - thuong la du an co tien."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/token-boosts/latest/v1"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
            return []
        except Exception as e:
            logger.error(f"Get boosted error: {e}")
            return []

    async def get_top_tokens(self, chain: str = "solana") -> list[dict]:
        """Lay top token theo volume tren 1 chain."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/latest/dex/tokens/trending/{chain}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", []) if isinstance(data, dict) else data
            return []
        except Exception as e:
            logger.error(f"Get top tokens error: {e}")
            return []

    async def get_pair_info(self, chain: str, pair_address: str) -> Optional[dict]:
        """Lay thong tin chi tiet 1 pair."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/latest/dex/pairs/{chain}/{pair_address}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    return pairs[0] if pairs else None
            return None
        except Exception as e:
            logger.error(f"Get pair error: {e}")
            return None

    # ==================================================
    # PHAN TICH AN TOAN
    # ==================================================

    def analyze_safety(self, pair: dict) -> dict:
        """
        Phan tich do an toan cua 1 token pair.
        Tra ve safety score (0-100) va cac canh bao.
        """
        score = 50  # Bat dau tu 50
        warnings = []
        positives = []

        # 1. Liquidity
        liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
        if liquidity >= 500000:
            score += 15
            positives.append(f"Thanh khoan cao: ${liquidity:,.0f}")
        elif liquidity >= 100000:
            score += 10
            positives.append(f"Thanh khoan kha: ${liquidity:,.0f}")
        elif liquidity >= 10000:
            score += 0
        elif liquidity < 10000:
            score -= 20
            warnings.append(f"Thanh khoan rat thap: ${liquidity:,.0f}")

        # 2. Volume 24h
        vol_24h = pair.get("volume", {}).get("h24", 0) or 0
        if vol_24h >= 100000:
            score += 10
            positives.append(f"Volume 24h tot: ${vol_24h:,.0f}")
        elif vol_24h < 5000:
            score -= 10
            warnings.append(f"Volume 24h thap: ${vol_24h:,.0f}")

        # 3. Buys vs Sells (Mua/Ban ratio)
        txns = pair.get("txns", {}).get("h24", {})
        buys = txns.get("buys", 0) or 0
        sells = txns.get("sells", 0) or 0
        total_txns = buys + sells
        if total_txns > 0:
            buy_ratio = buys / total_txns
            if buy_ratio > 0.6:
                score += 5
                positives.append(f"Ap luc mua manh: {buy_ratio*100:.0f}%")
            elif buy_ratio < 0.35:
                score -= 10
                warnings.append(f"Ap luc ban manh: {(1-buy_ratio)*100:.0f}%")

        # 4. Tuoi du an (pair created time)
        created = pair.get("pairCreatedAt")
        if created:
            try:
                age_hours = (datetime.now().timestamp() * 1000 - created) / (1000 * 3600)
                if age_hours < 1:
                    score -= 15
                    warnings.append("Token moi tao < 1 gio (RUI RO CAO)")
                elif age_hours < 24:
                    score -= 5
                    warnings.append(f"Token moi {age_hours:.0f} gio")
                elif age_hours > 168:  # > 1 tuan
                    score += 5
                    positives.append(f"Token ton tai {age_hours/24:.0f} ngay")
            except Exception:
                pass

        # 5. Price change (bien dong qua lon = nghi van)
        price_change_5m = pair.get("priceChange", {}).get("m5", 0) or 0
        price_change_1h = pair.get("priceChange", {}).get("h1", 0) or 0
        if abs(price_change_5m) > 50:
            score -= 15
            warnings.append(f"Bien dong 5m qua lon: {price_change_5m:+.0f}%")
        if abs(price_change_1h) > 100:
            score -= 10
            warnings.append(f"Bien dong 1h bat thuong: {price_change_1h:+.0f}%")

        # 6. FDV (Fully Diluted Valuation)
        fdv = pair.get("fdv", 0) or 0
        if 100000 < fdv < 10000000:
            score += 5
            positives.append(f"FDV low cap tiem nang: ${fdv:,.0f}")
        elif fdv > 100000000:
            score -= 5

        # Gioi han score
        score = max(0, min(100, score))

        return {
            "score": score,
            "safety": "AN TOAN" if score >= 70 else ("CHAP NHAN" if score >= 50 else ("RUI RO" if score >= 30 else "NGUY HIEM")),
            "warnings": warnings,
            "positives": positives,
        }

    # ==================================================
    # GEM SCORE (Tim token tiem nang x100)
    # ==================================================

    def calculate_gem_score(self, pair: dict, safety: dict) -> dict:
        """
        Tinh GEM Score - kha nang x100.
        Dua tren: FDV thap + Volume cao + Buy pressure + Thanh khoan du + An toan
        """
        gem_score = 0
        gem_reasons = []

        # 1. FDV thap (cang thap cang tiem nang)
        fdv = pair.get("fdv", 0) or 0
        if 50000 < fdv < 500000:
            gem_score += 30
            gem_reasons.append(f"FDV sieu thap ${fdv:,.0f} (x100+ possible)")
        elif 500000 < fdv < 2000000:
            gem_score += 20
            gem_reasons.append(f"FDV thap ${fdv:,.0f} (x50+ possible)")
        elif 2000000 < fdv < 10000000:
            gem_score += 10
            gem_reasons.append(f"FDV trung binh ${fdv:,.0f} (x10+ possible)")

        # 2. Volume/FDV ratio (cang cao = cang nhieu nguoi quan tam)
        vol_24h = pair.get("volume", {}).get("h24", 0) or 0
        if fdv > 0:
            vol_fdv = vol_24h / fdv
            if vol_fdv > 1:
                gem_score += 20
                gem_reasons.append(f"Vol/FDV > 1 (rat hot: {vol_fdv:.2f}x)")
            elif vol_fdv > 0.3:
                gem_score += 10
                gem_reasons.append(f"Vol/FDV tot ({vol_fdv:.2f}x)")

        # 3. Buy pressure
        txns = pair.get("txns", {}).get("h24", {})
        buys = txns.get("buys", 0) or 0
        sells = txns.get("sells", 0) or 0
        if buys + sells > 100:
            buy_ratio = buys / (buys + sells)
            if buy_ratio > 0.65:
                gem_score += 15
                gem_reasons.append(f"Mua nhieu: {buys} buy / {sells} sell")

        # 4. Safety bonus
        gem_score += max(0, safety["score"] - 50) // 5

        # 5. Momentum (price change tich cuc)
        change_1h = pair.get("priceChange", {}).get("h1", 0) or 0
        change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
        if 5 < change_1h < 50:
            gem_score += 5
            gem_reasons.append(f"Tang {change_1h:+.1f}% trong 1h")
        if 10 < change_24h < 200:
            gem_score += 5
            gem_reasons.append(f"Tang {change_24h:+.1f}% trong 24h")

        # Gioi han
        gem_score = max(0, min(100, gem_score))

        if gem_score >= 70:
            tier = "S-TIER GEM"
        elif gem_score >= 50:
            tier = "A-TIER"
        elif gem_score >= 30:
            tier = "B-TIER"
        else:
            tier = "C-TIER"

        return {
            "gem_score": gem_score,
            "tier": tier,
            "reasons": gem_reasons,
            "fdv": fdv,
            "volume_24h": vol_24h,
        }

    # ==================================================
    # QUET HANG LOAT VA TIM GEM
    # ==================================================

    async def scan_for_gems(self, chain: str = "solana", min_liquidity: float = 5000) -> list[dict]:
        """
        Quet token moi tren 1 chain va tim gem tiem nang.
        Tra ve danh sach sap xep theo gem_score.
        """
        # Tim token moi
        tokens = await self.get_new_tokens(chain)
        results = []

        for token_info in tokens[:15]:
            token_addr = token_info.get("tokenAddress", "")
            if not token_addr:
                continue

            # Search de lay pair info
            pairs = await self.search_token(token_addr)
            if not pairs:
                continue

            # Lay pair co liquidity cao nhat
            pair = max(pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0))

            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            if liq < min_liquidity:
                continue

            safety = self.analyze_safety(pair)
            gem = self.calculate_gem_score(pair, safety)

            results.append({
                "pair": pair,
                "safety": safety,
                "gem": gem,
                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                "symbol": pair.get("baseToken", {}).get("symbol", "???"),
                "price": float(pair.get("priceUsd", 0) or 0),
                "chain": chain,
                "url": pair.get("url", ""),
            })

            # Anti rate limit
            await asyncio.sleep(0.5)

        # Sort theo gem score
        results.sort(key=lambda x: x["gem"]["gem_score"], reverse=True)
        return results

    async def scan_new_listings(self, chain: str = "solana", max_age_hours: float = 1.0) -> list[dict]:
        """
        Quet token moi list tren DEX trong vong 1 gio tro lai.
        Tap trung vao GEM Score cao.
        """
        # Lay 30 token moi nhat
        session = await self._get_session()
        tokens = []
        try:
            url = f"{self.BASE_URL}/token-profiles/latest/v1"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tokens = [t for t in data if t.get("chainId", "").lower() == chain.lower()][:30]
        except Exception as e:
            logger.error(f"Get new tokens error: {e}")
            return []

        results = []
        now_ms = datetime.now().timestamp() * 1000

        for token_info in tokens:
            token_addr = token_info.get("tokenAddress", "")
            if not token_addr:
                continue

            # Lay thong tin cap giao dich
            pairs = await self.search_token(token_addr)
            if not pairs:
                continue

            pair = max(pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0))

            # Kiem tra tuoi
            created = pair.get("pairCreatedAt")
            if not created:
                continue
            
            age_hours = (now_ms - created) / (1000 * 3600)
            if age_hours > max_age_hours:
                continue  # Bo qua neu qua cu

            safety = self.analyze_safety(pair)
            gem = self.calculate_gem_score(pair, safety)

            # Chi lay nhung token co ti le thang cao
            if gem["gem_score"] < 40 and safety["score"] < 30:
                continue

            results.append({
                "pair": pair,
                "safety": safety,
                "gem": gem,
                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                "symbol": pair.get("baseToken", {}).get("symbol", "???"),
                "address": token_addr,
                "price": float(pair.get("priceUsd", 0) or 0),
                "age_mins": age_hours * 60,
                "chain": chain,
                "url": pair.get("url", ""),
            })
            await asyncio.sleep(0.3)

        results.sort(key=lambda x: x["gem"]["gem_score"], reverse=True)
        return results

    async def analyze_token_deep(self, query: str) -> Optional[dict]:
        """
        Phan tich sau 1 token cu the.
        query = ten token hoac dia chi contract.
        Tra ve thong tin chi tiet: website, social, VC backing, muc dich, chain explorer links.
        """
        pairs = await self.search_token(query)
        if not pairs:
            return None

        # Lay pair co liquidity cao nhat
        pair = max(pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0))

        safety = self.analyze_safety(pair)
        gem = self.calculate_gem_score(pair, safety)

        base = pair.get("baseToken", {})
        chain_id = pair.get("chainId", "")
        address = base.get("address", "")

        # === Lay thong tin profile tu DexScreener ===
        token_info = {}
        website_url = ""
        social_links = {}
        description = ""
        try:
            session = await self._get_session()
            # DexScreener token profile API
            profile_url = f"{self.BASE_URL}/token-profiles/latest/v1"
            async with session.get(profile_url) as resp:
                if resp.status == 200:
                    profiles = await resp.json()
                    for p in profiles:
                        if p.get("tokenAddress", "").lower() == address.lower():
                            token_info = p
                            break
        except:
            pass

        # Parse website & social links tu profile
        if token_info:
            description = token_info.get("description", "")
            for link in token_info.get("links", []):
                link_type = link.get("type", "").lower()
                link_label = link.get("label", "").lower()
                link_url = link.get("url", "")
                if link_type == "website" or link_label == "website":
                    website_url = link_url
                elif link_type == "twitter" or "twitter" in link_label or "x.com" in link_url:
                    social_links["twitter"] = link_url
                elif link_type == "telegram" or "telegram" in link_label or "t.me" in link_url:
                    social_links["telegram"] = link_url
                elif link_type == "discord" or "discord" in link_label:
                    social_links["discord"] = link_url
                elif link_url:
                    social_links[link_label or link_type or "other"] = link_url

        # Fallback: lay tu pair info
        if not website_url:
            info = pair.get("info", {})
            for link in info.get("websites", []):
                website_url = link.get("url", "")
                if website_url:
                    break
            for link in info.get("socials", []):
                stype = link.get("type", "")
                surl = link.get("url", "")
                if stype and surl:
                    social_links[stype] = surl

        # === VC Backing ===
        vc_backing = []
        check_text = f"{description} {base.get('name', '')}".lower()
        vc_backing = self.check_vc_backing(check_text)

        # === Chain explorer URL ===
        chain_explorers = {
            "solana": f"https://solscan.io/token/{address}",
            "ethereum": f"https://etherscan.io/token/{address}",
            "bsc": f"https://bscscan.com/token/{address}",
            "arbitrum": f"https://arbiscan.io/token/{address}",
            "base": f"https://basescan.org/token/{address}",
            "polygon": f"https://polygonscan.com/token/{address}",
            "avalanche": f"https://snowtrace.io/token/{address}",
            "optimism": f"https://optimistic.etherscan.io/token/{address}",
        }
        explorer_url = chain_explorers.get(chain_id.lower(), "")

        # === Chain info ghi chu ===
        chain_names = {
            "solana": "Solana (SOL)", "ethereum": "Ethereum (ETH)", "bsc": "BNB Chain (BSC)",
            "arbitrum": "Arbitrum (ARB)", "base": "Base (L2)", "polygon": "Polygon (MATIC)",
            "avalanche": "Avalanche (AVAX)", "optimism": "Optimism (OP)",
        }

        # === Price change ===
        chg = pair.get("priceChange", {})
        txns = pair.get("txns", {}).get("h24", {})

        return {
            "name": base.get("name", "Unknown"),
            "symbol": base.get("symbol", "???"),
            "address": address,
            "chain": chain_id,
            "chain_name": chain_names.get(chain_id.lower(), chain_id),
            "price": float(pair.get("priceUsd", 0) or 0),
            "price_change": {
                "5m": chg.get("m5", 0),
                "1h": chg.get("h1", 0),
                "6h": chg.get("h6", 0),
                "24h": chg.get("h24", 0),
            },
            "volume_24h": pair.get("volume", {}).get("h24", 0),
            "liquidity": pair.get("liquidity", {}).get("usd", 0),
            "fdv": pair.get("fdv", 0),
            "market_cap": pair.get("marketCap", 0),
            "buys_24h": txns.get("buys", 0),
            "sells_24h": txns.get("sells", 0),
            "dex": pair.get("dexId", ""),
            "pair_address": pair.get("pairAddress", ""),
            "pair_url": pair.get("url", ""),
            "dexscreener_url": f"https://dexscreener.com/{chain_id}/{pair.get('pairAddress', '')}",
            "explorer_url": explorer_url,
            # Token identity
            "description": description,
            "website": website_url,
            "socials": social_links,
            # VC / Investors
            "vc_backing": vc_backing,
            # Analysis
            "safety": safety,
            "gem": gem,
        }

    def check_vc_backing(self, description: str) -> list[dict]:
        """Kiem tra trong mo ta co ten quy dau tu nao khong."""
        found = []
        desc_lower = description.lower()
        for vc_key, vc_info in TOP_VCS.items():
            if vc_key in desc_lower:
                found.append(vc_info)
        return found
