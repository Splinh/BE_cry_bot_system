"""
Sentiment Analyzer - Phan tich tam ly thi truong tu tin tuc.
Dung keyword-based scoring (nhe, nhanh) + co the nang cap len AI/LLM sau.
"""
from loguru import logger


# Tu khoa tich cuc (Bullish)
BULLISH_KEYWORDS = [
    "surge", "surges", "surging", "rally", "rallies", "bullish",
    "breakout", "all-time high", "ath", "moon", "pump", "soar",
    "adoption", "approve", "approved", "approval", "etf approved",
    "partnership", "launch", "launches", "upgrade", "institutional",
    "buy", "accumulate", "whale buy", "inflow", "record high",
    "milestone", "growth", "positive", "optimistic", "recovery",
    "tang", "bung no", "dot pha", "ky luc", "tich cuc",
]

# Tu khoa tieu cuc (Bearish)
BEARISH_KEYWORDS = [
    "crash", "crashes", "dump", "dumps", "bearish", "plunge",
    "hack", "hacked", "exploit", "rug pull", "scam", "fraud",
    "ban", "banned", "restrict", "regulation", "sue", "sued",
    "lawsuit", "sec", "fine", "penalty", "liquidat", "outflow",
    "sell-off", "selloff", "fear", "panic", "collapse", "bankrupt",
    "delay", "postpone", "reject", "rejected", "warning",
    "giam", "sut", "sup do", "lua dao", "cam", "phat",
]

# Tu khoa trung lap / tin quan trong
IMPORTANT_KEYWORDS = [
    "breaking", "just in", "update", "report", "analysis",
    "federal reserve", "fed", "interest rate", "inflation",
    "cpi", "fomc", "gdp", "employment",
]

# === MACRO ECONOMIC KEYWORDS ===
# Tu khoa lien quan su kien kinh te vi mo
MACRO_BULLISH = [
    "rate cut", "rate reduction", "dovish", "dove",
    "quantitative easing", "qe", "stimulus", "inject",
    "soft landing", "disinflation", "cool",
    "lower than expected", "below forecast", "beat expectations",
    "etf approved", "etf approval", "spot etf",
    "regulation clarity", "pro-crypto", "crypto-friendly",
    "institutional adoption", "whale accumulation",
    "debt ceiling raised", "liquidity injection",
    "pause rate", "hold rate", "no change rate",
    "cat lai suat", "giam lai suat", "noi long",
]

MACRO_BEARISH = [
    "rate hike", "rate increase", "hawkish", "hawk",
    "quantitative tightening", "qt", "taper",
    "recession", "hard landing", "stagflation",
    "higher than expected", "above forecast", "miss expectations",
    "etf denied", "etf rejected", "etf delay",
    "crypto ban", "anti-crypto", "crackdown",
    "sec enforcement", "sec lawsuit", "sec charge",
    "bank collapse", "bank run", "banking crisis",
    "debt default", "government shutdown",
    "geopolitical", "war", "conflict escalat", "sanction",
    "tang lai suat", "that chat", "suy thoai",
]


class SentimentAnalyzer:
    """
    Phan tich sentiment (tam ly) cua tin tuc crypto.
    Tier 1: Keyword-based scoring (hien tai)
    Tier 2: AI/LLM integration (nang cap sau)
    """

    def analyze_text(self, text: str) -> dict:
        """
        Phan tich 1 doan text va tra ve:
        - sentiment: "bullish" | "bearish" | "neutral"
        - score: -10 den +10
        - keywords_found: danh sach tu khoa tim thay
        """
        text_lower = text.lower()

        bull_found = [kw for kw in BULLISH_KEYWORDS if kw in text_lower]
        bear_found = [kw for kw in BEARISH_KEYWORDS if kw in text_lower]
        important = [kw for kw in IMPORTANT_KEYWORDS if kw in text_lower]

        # Tinh diem
        bull_score = len(bull_found) * 2
        bear_score = len(bear_found) * 2

        # Tang trong so cho tu khoa manh
        strong_bull = ["etf approved", "all-time high", "ath", "institutional", "breakout"]
        strong_bear = ["hack", "rug pull", "scam", "bankrupt", "collapse", "sec"]

        for kw in strong_bull:
            if kw in text_lower:
                bull_score += 3

        for kw in strong_bear:
            if kw in text_lower:
                bear_score += 3

        # Macro keywords (strong weight)
        macro_bull_found = [kw for kw in MACRO_BULLISH if kw in text_lower]
        macro_bear_found = [kw for kw in MACRO_BEARISH if kw in text_lower]
        bull_score += len(macro_bull_found) * 3
        bear_score += len(macro_bear_found) * 3

        # Tong diem (-10 den +10)
        net_score = min(10, max(-10, bull_score - bear_score))

        if net_score >= 2:
            sentiment = "bullish"
        elif net_score <= -2:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
            "score": net_score,
            "bull_keywords": bull_found,
            "bear_keywords": bear_found,
            "important_keywords": important,
            "macro_bull_keywords": macro_bull_found,
            "macro_bear_keywords": macro_bear_found,
            "has_macro_impact": len(macro_bull_found) + len(macro_bear_found) > 0,
            "is_important": len(important) > 0 or len(macro_bull_found) + len(macro_bear_found) > 0,
        }

    def analyze_news_batch(self, news_list: list[dict]) -> list[dict]:
        """
        Phan tich sentiment cho 1 batch tin tuc.
        Moi tin se duoc them truong sentiment_analysis.
        """
        analyzed = []
        for news in news_list:
            title = news.get("title", "")
            analysis = self.analyze_text(title)

            # Ghi de sentiment tu keyword analysis (chinh xac hon)
            news_copy = news.copy()
            news_copy["sentiment"] = analysis["sentiment"]
            news_copy["sentiment_score"] = analysis["score"]
            news_copy["is_important"] = analysis["is_important"]
            analyzed.append(news_copy)

        # Sap xep: tin quan trong truoc, sentiment manh truoc
        analyzed.sort(key=lambda x: (x["is_important"], abs(x["sentiment_score"])), reverse=True)

        return analyzed

    def get_market_mood(self, news_list: list[dict]) -> dict:
        """
        Tinh tam ly chung cua thi truong tu nhieu tin.
        Tra ve mood tong the va diem trung binh.
        """
        if not news_list:
            return {"mood": "neutral", "avg_score": 0, "total_news": 0}

        scores = [n.get("sentiment_score", 0) for n in news_list]
        avg = sum(scores) / len(scores)

        if avg >= 2:
            mood = "BULLISH"
        elif avg <= -2:
            mood = "BEARISH"
        else:
            mood = "NEUTRAL"

        return {
            "mood": mood,
            "avg_score": round(avg, 2),
            "total_news": len(news_list),
            "bullish_count": sum(1 for s in scores if s > 0),
            "bearish_count": sum(1 for s in scores if s < 0),
            "neutral_count": sum(1 for s in scores if s == 0),
        }

    def analyze_macro_impact(self, event_type: str, headline: str = "") -> dict:
        """
        Phan tich tac dong cua su kien kinh te len crypto.
        event_type: FOMC, CPI, NFP, GDP, SEC, ETF
        headline: Tieu de tin tuc kem theo (VD: "Fed cuts rate by 25bps")
        """
        text_analysis = self.analyze_text(headline) if headline else {"sentiment": "neutral", "score": 0}

        # Default impact dua tren event type
        type_defaults = {
            "FOMC": {"volatility": "EXTREME", "typical_range": "5-15%", "duration": "24-48h"},
            "CPI": {"volatility": "HIGH", "typical_range": "3-8%", "duration": "12-24h"},
            "NFP": {"volatility": "MEDIUM", "typical_range": "2-5%", "duration": "6-12h"},
            "GDP": {"volatility": "LOW", "typical_range": "1-3%", "duration": "4-8h"},
            "FED_SPEECH": {"volatility": "HIGH", "typical_range": "2-8%", "duration": "4-12h"},
            "SEC": {"volatility": "HIGH", "typical_range": "5-20%", "duration": "24-72h"},
            "ETF": {"volatility": "EXTREME", "typical_range": "10-30%", "duration": "48-168h"},
        }

        defaults = type_defaults.get(event_type, {
            "volatility": "LOW", "typical_range": "1-2%", "duration": "2-4h"
        })

        # Scoring crypto impact tu headline
        crypto_direction = "NEUTRAL"
        confidence = 0

        if text_analysis["score"] >= 3:
            crypto_direction = "BULLISH"
            confidence = min(90, 50 + text_analysis["score"] * 8)
        elif text_analysis["score"] <= -3:
            crypto_direction = "BEARISH"
            confidence = min(90, 50 + abs(text_analysis["score"]) * 8)
        elif text_analysis["score"] != 0:
            crypto_direction = "BULLISH" if text_analysis["score"] > 0 else "BEARISH"
            confidence = 30 + abs(text_analysis["score"]) * 10

        return {
            "event_type": event_type,
            "headline_sentiment": text_analysis,
            "crypto_direction": crypto_direction,
            "confidence": confidence,
            **defaults,
            "recommendation": self._get_macro_recommendation(event_type, crypto_direction),
        }

    def _get_macro_recommendation(self, event_type: str, direction: str) -> str:
        """Tra ve khuyen nghi giao dich dua tren su kien macro."""
        if event_type in ("FOMC", "ETF"):
            if direction == "BULLISH":
                return "Su kien cuc lon BULLISH. Co the LONG voi leverage vua phai (5-10x). SL rong."
            elif direction == "BEARISH":
                return "Su kien cuc lon BEARISH. Can nhac SHORT hoac dong het lenh. Bao ve von."
            return "Su kien quan trong sap dien ra. Giam leverage, mo rong SL, hoac ngoi ngoai."
        elif event_type in ("CPI", "NFP"):
            if direction == "BULLISH":
                return "Du lieu tot hon ky vong → Bullish. Co the mo LONG voi SL chat."
            elif direction == "BEARISH":
                return "Du lieu xau hon ky vong → Bearish ngan han. Can than voi LONG positions."
            return "Theo doi du lieu thuc te so voi ky vong truoc khi hanh dong."
        return "Theo doi dien bien va phan ung cua thi truong."

