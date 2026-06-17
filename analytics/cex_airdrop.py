"""
CEX Airdrop Scanner - Quet cac su kien Airdrop tien tuoi, khong von/it von.
Bao gom: Binance (Megadrop, Launchpool, Web3 Wallet), Bybit (Launchpool, Web3), OKX (Jumpstart).
"""
import asyncio
import aiohttp
from datetime import datetime
from loguru import logger


class CexAirdropScanner:
    """
    Tim kiem cac su kien Airdrop "tien tuoi" dang dien ra tren cac san lon.
    """

    def __init__(self):
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def scan_binance_airdrops(self) -> list[dict]:
        """
        Quet Binance Announcements (Catalog 48, 49) de tim Megadrop, Launchpool, Web3.
        """
        session = await self._get_session()
        results = []
        
        # 49 = Latest Binance News, 48 = New Cryptocurrency Listing, 161 = Binance Web3
        catalogs = [48, 49, 161]
        
        keywords = ["megadrop", "launchpool", "web3 wallet airdrop", "airdrop", "hodler airdrops"]
        
        try:
            for cat in catalogs:
                url = f"https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId={cat}&pageNo=1&pageSize=20"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = data.get("data", {}).get("articles", [])
                        
                        for art in articles:
                            title = art.get("title", "")
                            title_lower = title.lower()
                            
                            # Kiem tra xem co trung keyword khong
                            if any(k in title_lower for k in keywords):
                                code = art.get("code", "")
                                link = f"https://www.binance.com/en/support/announcement/{code}"
                                timestamp = art.get("releaseDate", 0)
                                if timestamp:
                                    date_str = datetime.fromtimestamp(timestamp/1000).strftime("%Y-%m-%d")
                                else:
                                    date_str = "Recent"

                                # Danh gia loai airdrop de xem luong von can thiet
                                capital = "KHONG VON / IT VON"
                                if "launchpool" in title_lower:
                                    capital = "CAN VON (Stake BNB/FDUSD)"
                                elif "megadrop" in title_lower:
                                    capital = "WEB3 TASK (It von gas)"
                                elif "web3 wallet" in title_lower:
                                    capital = "WEB3 TASK (It von gas)"

                                results.append({
                                    "exchange": "Binance",
                                    "title": title,
                                    "link": link,
                                    "date": date_str,
                                    "capital": capital,
                                    "timestamp": timestamp,
                                })
                                
        except Exception as e:
            logger.error(f"Binance airdrop scan error: {e}")
            
        return results

    async def scan_bybit_airdrops(self) -> list[dict]:
        """
        Quet Bybit Announcements de tim Launchpool, ByStarter, Web3 Airdrop.
        """
        session = await self._get_session()
        results = []
        keywords = ["launchpool", "bystarter", "airdrop", "web3", "ido"]
        
        try:
            url = "https://api.bybit.com/v5/announcements/index?locale=en-US&limit=20"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    announcements = data.get("result", {}).get("list", [])
                    
                    for item in announcements:
                        title = item.get("title", "")
                        title_lower = title.lower()
                        
                        if any(k in title_lower for k in keywords):
                            link = item.get("url", "https://announcements.bybit.com/")
                            timestamp = item.get("dateTimestamp", 0)
                            if timestamp:
                                date_str = datetime.fromtimestamp(timestamp/1000).strftime("%Y-%m-%d")
                            else:
                                date_str = "Recent"
                                
                            capital = "KHONG VON / IT VON"
                            if "launchpool" in title_lower:
                                capital = "CAN VON (Stake MNT/USDT)"
                            elif "ido" in title_lower or "web3" in title_lower:
                                capital = "WEB3 TASK (Phi Gas tren mang tuong ung)"
                                
                            results.append({
                                "exchange": "Bybit",
                                "title": title,
                                "link": link,
                                "date": date_str,
                                "capital": capital,
                                "timestamp": timestamp,
                            })
        except Exception as e:
            logger.error(f"Bybit airdrop scan error: {e}")
            
        return results

    async def get_all_airdrops(self) -> list[dict]:
        """
        Lay tat ca airdrop tu cac san, sap xep theo thoi gian moi nhat.
        """
        binance_tasks = self.scan_binance_airdrops()
        bybit_tasks = self.scan_bybit_airdrops()
        
        results = await asyncio.gather(binance_tasks, bybit_tasks)
        
        all_airdrops = []
        for res_list in results:
            all_airdrops.extend(res_list)
            
        # Loc bo trung lap theo link
        seen_links = set()
        unique_airdrops = []
        for a in all_airdrops:
            if a["link"] not in seen_links:
                seen_links.add(a["link"])
                unique_airdrops.append(a)
                
        # Sort theo timestamp moi nhat
        unique_airdrops.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        # Chi tra ve cac event trong vong 14 ngay tro lai day de dam bao con han
        now_ms = datetime.now().timestamp() * 1000
        recent_airdrops = [
            a for a in unique_airdrops 
            if (now_ms - a.get("timestamp", 0)) < 14 * 24 * 3600 * 1000
        ]
        
        return recent_airdrops
