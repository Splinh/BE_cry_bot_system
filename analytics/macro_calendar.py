"""
Macro Calendar — Theo doi lich su kien kinh te quan trong anh huong crypto.
FOMC, CPI, NFP, GDP, Fed Speeches, SEC Rulings, ETF Decisions.

Nguon du lieu:
1. Built-in calendar (FOMC/CPI/NFP schedule)
2. ForexFactory / Investing.com scraping (fallback)
3. CryptoPanic macro filter
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from loguru import logger


# ============================================
#  BUILT-IN ECONOMIC CALENDAR 2025-2026
# ============================================
# FOMC Meetings (Federal Reserve) — 8 cuoc hop/nam
# Nguon: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_MEETINGS = [
    # 2025
    {"date": "2025-01-29", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2025-03-19", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    {"date": "2025-05-07", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2025-06-18", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    {"date": "2025-07-30", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2025-09-17", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    {"date": "2025-10-29", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2025-12-17", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    # 2026
    {"date": "2026-01-28", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2026-03-18", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    {"date": "2026-05-06", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2026-06-17", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    {"date": "2026-07-29", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2026-09-16", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
    {"date": "2026-10-28", "type": "FOMC", "title": "FOMC Meeting", "impact": "CRITICAL"},
    {"date": "2026-12-16", "type": "FOMC", "title": "FOMC Meeting + Dot Plot", "impact": "CRITICAL"},
]

# CPI Release Dates (Bureau of Labor Statistics) — hang thang, thuong ngay 10-14
CPI_RELEASES = [
    # 2025
    {"date": "2025-01-15", "type": "CPI", "title": "CPI (Dec 2024)", "impact": "HIGH"},
    {"date": "2025-02-12", "type": "CPI", "title": "CPI (Jan 2025)", "impact": "HIGH"},
    {"date": "2025-03-12", "type": "CPI", "title": "CPI (Feb 2025)", "impact": "HIGH"},
    {"date": "2025-04-10", "type": "CPI", "title": "CPI (Mar 2025)", "impact": "HIGH"},
    {"date": "2025-05-13", "type": "CPI", "title": "CPI (Apr 2025)", "impact": "HIGH"},
    {"date": "2025-06-11", "type": "CPI", "title": "CPI (May 2025)", "impact": "HIGH"},
    {"date": "2025-07-10", "type": "CPI", "title": "CPI (Jun 2025)", "impact": "HIGH"},
    {"date": "2025-08-12", "type": "CPI", "title": "CPI (Jul 2025)", "impact": "HIGH"},
    {"date": "2025-09-10", "type": "CPI", "title": "CPI (Aug 2025)", "impact": "HIGH"},
    {"date": "2025-10-14", "type": "CPI", "title": "CPI (Sep 2025)", "impact": "HIGH"},
    {"date": "2025-11-12", "type": "CPI", "title": "CPI (Oct 2025)", "impact": "HIGH"},
    {"date": "2025-12-10", "type": "CPI", "title": "CPI (Nov 2025)", "impact": "HIGH"},
    # 2026
    {"date": "2026-01-14", "type": "CPI", "title": "CPI (Dec 2025)", "impact": "HIGH"},
    {"date": "2026-02-11", "type": "CPI", "title": "CPI (Jan 2026)", "impact": "HIGH"},
    {"date": "2026-03-11", "type": "CPI", "title": "CPI (Feb 2026)", "impact": "HIGH"},
    {"date": "2026-04-14", "type": "CPI", "title": "CPI (Mar 2026)", "impact": "HIGH"},
    {"date": "2026-05-12", "type": "CPI", "title": "CPI (Apr 2026)", "impact": "HIGH"},
    {"date": "2026-06-10", "type": "CPI", "title": "CPI (May 2026)", "impact": "HIGH"},
    {"date": "2026-07-14", "type": "CPI", "title": "CPI (Jun 2026)", "impact": "HIGH"},
    {"date": "2026-08-12", "type": "CPI", "title": "CPI (Jul 2026)", "impact": "HIGH"},
    {"date": "2026-09-15", "type": "CPI", "title": "CPI (Aug 2026)", "impact": "HIGH"},
    {"date": "2026-10-13", "type": "CPI", "title": "CPI (Sep 2026)", "impact": "HIGH"},
    {"date": "2026-11-10", "type": "CPI", "title": "CPI (Oct 2026)", "impact": "HIGH"},
    {"date": "2026-12-10", "type": "CPI", "title": "CPI (Nov 2026)", "impact": "HIGH"},
]

# Non-Farm Payrolls (Bureau of Labor Statistics) — hang thang, thuong thu 6 dau thang
NFP_RELEASES = [
    # 2025
    {"date": "2025-01-10", "type": "NFP", "title": "Non-Farm Payrolls (Dec)", "impact": "HIGH"},
    {"date": "2025-02-07", "type": "NFP", "title": "Non-Farm Payrolls (Jan)", "impact": "HIGH"},
    {"date": "2025-03-07", "type": "NFP", "title": "Non-Farm Payrolls (Feb)", "impact": "HIGH"},
    {"date": "2025-04-04", "type": "NFP", "title": "Non-Farm Payrolls (Mar)", "impact": "HIGH"},
    {"date": "2025-05-02", "type": "NFP", "title": "Non-Farm Payrolls (Apr)", "impact": "HIGH"},
    {"date": "2025-06-06", "type": "NFP", "title": "Non-Farm Payrolls (May)", "impact": "HIGH"},
    {"date": "2025-07-03", "type": "NFP", "title": "Non-Farm Payrolls (Jun)", "impact": "HIGH"},
    {"date": "2025-08-01", "type": "NFP", "title": "Non-Farm Payrolls (Jul)", "impact": "HIGH"},
    {"date": "2025-09-05", "type": "NFP", "title": "Non-Farm Payrolls (Aug)", "impact": "HIGH"},
    {"date": "2025-10-03", "type": "NFP", "title": "Non-Farm Payrolls (Sep)", "impact": "HIGH"},
    {"date": "2025-11-07", "type": "NFP", "title": "Non-Farm Payrolls (Oct)", "impact": "HIGH"},
    {"date": "2025-12-05", "type": "NFP", "title": "Non-Farm Payrolls (Nov)", "impact": "HIGH"},
    # 2026
    {"date": "2026-01-09", "type": "NFP", "title": "Non-Farm Payrolls (Dec)", "impact": "HIGH"},
    {"date": "2026-02-06", "type": "NFP", "title": "Non-Farm Payrolls (Jan)", "impact": "HIGH"},
    {"date": "2026-03-06", "type": "NFP", "title": "Non-Farm Payrolls (Feb)", "impact": "HIGH"},
    {"date": "2026-04-03", "type": "NFP", "title": "Non-Farm Payrolls (Mar)", "impact": "HIGH"},
    {"date": "2026-05-01", "type": "NFP", "title": "Non-Farm Payrolls (Apr)", "impact": "HIGH"},
    {"date": "2026-06-05", "type": "NFP", "title": "Non-Farm Payrolls (May)", "impact": "HIGH"},
    {"date": "2026-07-02", "type": "NFP", "title": "Non-Farm Payrolls (Jun)", "impact": "HIGH"},
    {"date": "2026-08-07", "type": "NFP", "title": "Non-Farm Payrolls (Jul)", "impact": "HIGH"},
    {"date": "2026-09-04", "type": "NFP", "title": "Non-Farm Payrolls (Aug)", "impact": "HIGH"},
    {"date": "2026-10-02", "type": "NFP", "title": "Non-Farm Payrolls (Sep)", "impact": "HIGH"},
    {"date": "2026-11-06", "type": "NFP", "title": "Non-Farm Payrolls (Oct)", "impact": "HIGH"},
    {"date": "2026-12-04", "type": "NFP", "title": "Non-Farm Payrolls (Nov)", "impact": "HIGH"},
]

# GDP Reports (Bureau of Economic Analysis) — hang quy
GDP_RELEASES = [
    {"date": "2025-01-30", "type": "GDP", "title": "GDP Q4 2024 (Advance)", "impact": "MEDIUM"},
    {"date": "2025-04-30", "type": "GDP", "title": "GDP Q1 2025 (Advance)", "impact": "MEDIUM"},
    {"date": "2025-07-30", "type": "GDP", "title": "GDP Q2 2025 (Advance)", "impact": "MEDIUM"},
    {"date": "2025-10-29", "type": "GDP", "title": "GDP Q3 2025 (Advance)", "impact": "MEDIUM"},
    {"date": "2026-01-29", "type": "GDP", "title": "GDP Q4 2025 (Advance)", "impact": "MEDIUM"},
    {"date": "2026-04-29", "type": "GDP", "title": "GDP Q1 2026 (Advance)", "impact": "MEDIUM"},
    {"date": "2026-07-29", "type": "GDP", "title": "GDP Q2 2026 (Advance)", "impact": "MEDIUM"},
    {"date": "2026-10-28", "type": "GDP", "title": "GDP Q3 2026 (Advance)", "impact": "MEDIUM"},
]

# Impact descriptions: phan tich anh huong len crypto
EVENT_IMPACT_MAP = {
    "FOMC": {
        "description": "Quyet dinh lai suat cua Fed. Rate cut → Bullish crypto, Rate hike → Bearish.",
        "crypto_impact": "Bien dong manh +/-5-15% trong 24h",
        "advice_before": "Can nhac giam leverage, mo rong SL truoc 24h",
        "advice_after": "Doi 30-60 phut sau thong bao de xac nhan xu huong",
    },
    "CPI": {
        "description": "Chi so lam phat. CPI thap hon du kien → Bullish (ky vong cat lai suat).",
        "crypto_impact": "Bien dong +/-3-8% trong 12h",
        "advice_before": "Tang SL buffer 30-50%",
        "advice_after": "Phan ung nhanh trong 1h dau, xu huong ro rang sau 2-4h",
    },
    "NFP": {
        "description": "So lieu viec lam. NFP manh → USD manh → Bearish crypto (ngan han).",
        "crypto_impact": "Bien dong +/-2-5% trong 6h",
        "advice_before": "Tang SL buffer 20-30%",
        "advice_after": "Xu huong thuong ro trong 1-2h",
    },
    "GDP": {
        "description": "Tang truong kinh te. GDP manh → thi truong chung tang, crypto theo.",
        "crypto_impact": "Bien dong +/-1-3%",
        "advice_before": "Theo doi nhung khong can thay doi chien luoc nhieu",
        "advice_after": "Anh huong ngan han, xu huong lon khong doi",
    },
    "FED_SPEECH": {
        "description": "Phat bieu cua Chu tich Fed. Hawkish → Bearish, Dovish → Bullish.",
        "crypto_impact": "Bien dong +/-2-8% tuy noi dung",
        "advice_before": "Theo doi tone phat bieu (hawkish/dovish)",
        "advice_after": "Phan ung nhanh, kiem tra keyword trong speech",
    },
    "SEC": {
        "description": "Quyet dinh cua SEC ve crypto (ETF, regulation, enforcement).",
        "crypto_impact": "Bien dong manh +/-5-20% (ETF approval/rejection)",
        "advice_before": "Theo doi thoi diem quyet dinh, can nhac hedge",
        "advice_after": "Xu huong ro rang ngay lap tuc",
    },
    "ETF": {
        "description": "Quyet dinh BTC/ETH ETF Spot hoac Options.",
        "crypto_impact": "Bien dong cuc manh +/-10-30%",
        "advice_before": "Day la su kien lon nhat, can chuan bi SL rong",
        "advice_after": "Phan ung manh va nhanh, khong nen nghi ngo",
    },
}

# ============================================
#  LIVE DATA FETCHER
# ============================================

# Investing.com Economic Calendar (free API alternative)
INVESTING_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


class MacroCalendar:
    """
    Theo doi lich su kien kinh te quan trong anh huong crypto.
    Ket hop built-in calendar + live data.
    """

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache = {"events": [], "ts": 0}
        self._cache_ttl = 3600  # Cache 1h

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def get_builtin_events(self, days_ahead: int = 30) -> list[dict]:
        """Lay su kien tu built-in calendar."""
        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)
        events = []

        for event_list in [FOMC_MEETINGS, CPI_RELEASES, NFP_RELEASES, GDP_RELEASES]:
            for ev in event_list:
                try:
                    ev_date = datetime.strptime(ev["date"], "%Y-%m-%d")
                    # Chi lay su kien sap toi (hoac vua qua 2 ngay)
                    if (now - timedelta(days=2)) <= ev_date <= cutoff:
                        hours_until = (ev_date - now).total_seconds() / 3600
                        events.append({
                            **ev,
                            "datetime": ev_date.isoformat(),
                            "hours_until": round(hours_until, 1),
                            "is_past": hours_until < 0,
                            "is_today": ev_date.date() == now.date(),
                            "is_upcoming_24h": 0 < hours_until <= 24,
                            "is_upcoming_48h": 0 < hours_until <= 48,
                            "source": "built-in",
                            "info": EVENT_IMPACT_MAP.get(ev["type"], {}),
                        })
                except Exception:
                    continue

        events.sort(key=lambda x: x["datetime"])
        return events

    async def fetch_live_events(self) -> list[dict]:
        """
        Lay su kien tu ForexFactory / FairEconomy API.
        Tra ve cac su kien HIGH/MEDIUM impact tuan nay.
        """
        import time as _time
        now_ts = _time.time()

        # Su dung cache
        if now_ts - self._cache["ts"] < self._cache_ttl and self._cache["events"]:
            return self._cache["events"]

        session = await self._get_session()
        events = []

        try:
            async with session.get(INVESTING_CALENDAR_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    now = datetime.now()

                    for item in data:
                        # Chi lay su kien USD (anh huong crypto nhieu nhat)
                        country = item.get("country", "")
                        if country not in ("USD", "ALL"):
                            continue

                        impact = item.get("impact", "").upper()
                        if impact not in ("HIGH", "MEDIUM", "HOLIDAY"):
                            continue

                        title = item.get("title", "")
                        date_str = item.get("date", "")

                        try:
                            ev_date = datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00", ""))
                        except Exception:
                            try:
                                ev_date = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
                            except Exception:
                                continue

                        hours_until = (ev_date - now).total_seconds() / 3600

                        # Map sang loai event
                        event_type = self._classify_event(title)

                        # Map impact
                        if impact == "HIGH":
                            mapped_impact = "HIGH"
                        elif "fomc" in title.lower() or "fed" in title.lower():
                            mapped_impact = "CRITICAL"
                        else:
                            mapped_impact = "MEDIUM"

                        events.append({
                            "date": ev_date.strftime("%Y-%m-%d"),
                            "time": ev_date.strftime("%H:%M"),
                            "type": event_type,
                            "title": title,
                            "impact": mapped_impact,
                            "datetime": ev_date.isoformat(),
                            "hours_until": round(hours_until, 1),
                            "is_past": hours_until < 0,
                            "is_today": ev_date.date() == now.date(),
                            "is_upcoming_24h": 0 < hours_until <= 24,
                            "is_upcoming_48h": 0 < hours_until <= 48,
                            "forecast": item.get("forecast", ""),
                            "previous": item.get("previous", ""),
                            "source": "forexfactory",
                            "info": EVENT_IMPACT_MAP.get(event_type, {}),
                        })

                    logger.info(f"[Macro] Fetched {len(events)} live events from ForexFactory")

        except Exception as e:
            logger.warning(f"[Macro] Live fetch failed: {e}, using built-in only")

        self._cache["events"] = events
        self._cache["ts"] = now_ts
        return events

    def _classify_event(self, title: str) -> str:
        """Phan loai su kien theo title."""
        t = title.lower()
        if "fomc" in t or "federal funds rate" in t or "fed interest" in t:
            return "FOMC"
        if "cpi" in t or "consumer price" in t or "inflation" in t:
            return "CPI"
        if "non-farm" in t or "nonfarm" in t or "payroll" in t:
            return "NFP"
        if "gdp" in t or "gross domestic" in t:
            return "GDP"
        if "fed chair" in t or "powell" in t or "fed speak" in t:
            return "FED_SPEECH"
        if "sec " in t or "securities" in t:
            return "SEC"
        if "etf" in t:
            return "ETF"
        if "unemployment" in t or "jobless" in t:
            return "JOBS"
        if "pmi" in t or "purchasing" in t:
            return "PMI"
        if "retail sales" in t:
            return "RETAIL"
        return "OTHER"

    async def get_all_events(self, days_ahead: int = 30) -> list[dict]:
        """Ket hop built-in + live events, loai bo trung lap."""
        builtin = self.get_builtin_events(days_ahead)
        live = await self.fetch_live_events()

        # Loai bo trung lap (cung ngay + cung type)
        seen = set()
        merged = []

        # Uu tien live events (co forecast/previous)
        for ev in live:
            key = f"{ev['date']}_{ev['type']}"
            if key not in seen:
                seen.add(key)
                merged.append(ev)

        # Bo sung built-in
        for ev in builtin:
            key = f"{ev['date']}_{ev['type']}"
            if key not in seen:
                seen.add(key)
                merged.append(ev)

        merged.sort(key=lambda x: x.get("datetime", ""))
        return merged

    async def get_next_critical(self) -> Optional[dict]:
        """Lay su kien CRITICAL/HIGH gan nhat sap dien ra."""
        events = await self.get_all_events(30)
        for ev in events:
            if ev.get("is_past"):
                continue
            if ev["impact"] in ("CRITICAL", "HIGH"):
                return ev
        return None

    async def assess_risk(self) -> dict:
        """
        Danh gia muc do rui ro hien tai dua tren events sap toi.
        Tra ve risk_level: NORMAL / HIGH / CRITICAL
        + canh bao cu the.
        """
        events = await self.get_all_events(7)
        now = datetime.now()
        warnings = []
        risk_level = "NORMAL"

        critical_24h = []
        high_24h = []
        high_48h = []

        for ev in events:
            if ev.get("is_past"):
                continue

            hours = ev.get("hours_until", 999)

            if ev["impact"] == "CRITICAL" and hours <= 24:
                critical_24h.append(ev)
            elif ev["impact"] in ("CRITICAL", "HIGH") and hours <= 24:
                high_24h.append(ev)
            elif ev["impact"] in ("CRITICAL", "HIGH") and hours <= 48:
                high_48h.append(ev)

        # Xac dinh risk level
        if critical_24h:
            risk_level = "CRITICAL"
            for ev in critical_24h:
                warnings.append({
                    "level": "🔴 CRITICAL",
                    "message": f"{ev['title']} trong {ev['hours_until']:.0f}h",
                    "advice": ev.get("info", {}).get("advice_before", "Can nhac giam leverage"),
                    "event": ev,
                })
        elif high_24h:
            risk_level = "HIGH"
            for ev in high_24h:
                warnings.append({
                    "level": "🟡 HIGH",
                    "message": f"{ev['title']} trong {ev['hours_until']:.0f}h",
                    "advice": ev.get("info", {}).get("advice_before", "Tang SL buffer"),
                    "event": ev,
                })
        elif high_48h:
            risk_level = "HIGH"
            for ev in high_48h:
                warnings.append({
                    "level": "🟡 CAUTION",
                    "message": f"{ev['title']} trong {ev['hours_until']:.0f}h",
                    "advice": "Theo doi va chuan bi",
                    "event": ev,
                })

        # Upcoming events tuan nay
        upcoming = [ev for ev in events if not ev.get("is_past")]

        return {
            "risk_level": risk_level,
            "warnings": warnings,
            "upcoming_count": len(upcoming),
            "critical_count": len(critical_24h),
            "high_count": len(high_24h),
            "next_critical": critical_24h[0] if critical_24h else (high_24h[0] if high_24h else None),
            "upcoming_events": upcoming[:10],
        }
