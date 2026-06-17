"""
News Crawler - Cao tin tuc Crypto tu nhieu nguon.
Nguon chinh: CryptoPanic API (mien phi, tong hop 50+ bao).
Nguon phu: RSS Feed tu CoinTelegraph, CoinDesk.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
import feedparser
from loguru import logger


# CryptoPanic API (Free tier - khong can API key cho public posts)
CRYPTOPANIC_API = "https://cryptopanic.com/api/free/v1/posts/"

# RSS Feeds
RSS_FEEDS = {
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
}


class NewsCrawler:
    """
    Crawler tin tuc Crypto tu nhieu nguon.
    Ho tro:
    - CryptoPanic API (tin tuc tong hop, co phan loai sentiment)
    - RSS Feeds (CoinTelegraph, CoinDesk)
    """

    def __init__(self, cryptopanic_token: Optional[str] = None):
        self.cryptopanic_token = cryptopanic_token
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_cryptopanic(self, filter_type: str = "hot", limit: int = 5) -> list[dict]:
        """
        Lay tin tu CryptoPanic.
        filter_type: "hot" | "rising" | "bullish" | "bearish" | "important"
        """
        session = await self._get_session()
        params = {"filter": filter_type, "public": "true"}
        if self.cryptopanic_token:
            params["auth_token"] = self.cryptopanic_token

        try:
            async with session.get(CRYPTOPANIC_API, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for post in data.get("results", [])[:limit]:
                        votes = post.get("votes", {})
                        # Tinh sentiment tu votes
                        pos = votes.get("positive", 0) + votes.get("liked", 0)
                        neg = votes.get("negative", 0) + votes.get("disliked", 0)

                        if pos > neg * 1.5:
                            sentiment = "bullish"
                        elif neg > pos * 1.5:
                            sentiment = "bearish"
                        else:
                            sentiment = "neutral"

                        results.append({
                            "title": post.get("title", ""),
                            "source": post.get("source", {}).get("title", "Unknown"),
                            "url": post.get("url", ""),
                            "sentiment": sentiment,
                            "published": post.get("published_at", ""),
                            "currencies": [c.get("code", "") for c in post.get("currencies", [])],
                        })
                    logger.info(f"CryptoPanic: lay duoc {len(results)} tin ({filter_type})")
                    return results
                else:
                    logger.warning(f"CryptoPanic API error: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"CryptoPanic fetch error: {e}")
            return []

    async def fetch_rss(self, limit_per_source: int = 3) -> list[dict]:
        """Lay tin tu RSS Feeds."""
        all_news = []

        for source_name, rss_url in RSS_FEEDS.items():
            try:
                session = await self._get_session()
                async with session.get(rss_url) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)

                        for entry in feed.entries[:limit_per_source]:
                            # Loc tin trong 24h
                            pub_date = entry.get("published_parsed")
                            if pub_date:
                                pub_dt = datetime(*pub_date[:6])
                                if datetime.now() - pub_dt > timedelta(hours=24):
                                    continue

                            all_news.append({
                                "title": entry.get("title", ""),
                                "source": source_name,
                                "url": entry.get("link", ""),
                                "sentiment": "neutral",  # RSS khong co sentiment, can AI phan tich
                                "published": entry.get("published", ""),
                                "currencies": [],
                            })
                logger.info(f"RSS {source_name}: lay duoc {len([n for n in all_news if n['source'] == source_name])} tin")
            except Exception as e:
                logger.error(f"RSS {source_name} error: {e}")

        return all_news

    async def fetch_all(self, limit: int = 5) -> list[dict]:
        """Lay tin tu tat ca nguon."""
        cryptopanic_news = await self.fetch_cryptopanic("hot", limit)
        rss_news = await self.fetch_rss(limit_per_source=2)

        all_news = cryptopanic_news + rss_news

        # Sap xep theo thoi gian moi nhat
        all_news.sort(key=lambda x: x.get("published", ""), reverse=True)

        return all_news[:limit * 2]  # Tra ve toi da limit*2 tin

    async def fetch_by_coin(self, coin: str, limit: int = 5) -> list[dict]:
        """Lay tin lien quan den 1 coin cu the (VD: BTC, ETH, SOL)."""
        session = await self._get_session()
        params = {
            "currencies": coin.upper(),
            "public": "true",
            "filter": "hot",
        }
        if self.cryptopanic_token:
            params["auth_token"] = self.cryptopanic_token

        try:
            async with session.get(CRYPTOPANIC_API, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for post in data.get("results", [])[:limit]:
                        results.append({
                            "title": post.get("title", ""),
                            "source": post.get("source", {}).get("title", "Unknown"),
                            "url": post.get("url", ""),
                            "sentiment": "neutral",
                            "published": post.get("published_at", ""),
                            "currencies": [coin.upper()],
                        })
                    return results
                return []
        except Exception as e:
            logger.error(f"CryptoPanic coin fetch error: {e}")
            return []
