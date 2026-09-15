"""
Smart News Intelligence — Phân tích tin tức thông minh bằng LLM.

3 khối chức năng:
1. LLM-Powered News Analyzer: Dùng OmniRouter để hiểu tin tức thay vì keyword matching
2. Event Impact Database: Lưu lịch sử phản ứng BTC sau sự kiện → dự đoán lần sau
3. Pre-Event Positioning: Tự điều chỉnh chiến lược trước/sau sự kiện lớn
"""
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

try:
    from core.config import Config
except ImportError:
    Config = None


# File luu lich su phan ung thi truong truoc/sau su kien
EVENT_HISTORY_FILE = "data/event_impact_history.json"


class NewsIntelligence:
    """
    Phan tich tin tuc thong minh ket hop LLM + lich su su kien.
    """

    def __init__(self):
        self.event_history: dict = {}
        self._load_event_history()
        self._llm_provider = None
        self._news_cache = {}
        self._cache_ttl = 300  # 5 phut
        # Tu dong ghi nhan ket qua su kien macro da qua vao Event Impact DB
        self.auto_record_enabled = True

    def _load_event_history(self):
        """Doc lich su su kien tu file."""
        if os.path.exists(EVENT_HISTORY_FILE):
            try:
                with open(EVENT_HISTORY_FILE, "r") as f:
                    self.event_history = json.load(f)
            except Exception as e:
                logger.error(f"[NewsIntel] Loi doc event history: {e}")
                self.event_history = {}

    def _save_event_history(self):
        """Luu lich su su kien (atomic write de tranh mat du lieu)."""
        os.makedirs(os.path.dirname(EVENT_HISTORY_FILE), exist_ok=True)
        tmp_file = EVENT_HISTORY_FILE + ".tmp"
        try:
            with open(tmp_file, "w") as f:
                json.dump(self.event_history, f, indent=2)
            os.replace(tmp_file, EVENT_HISTORY_FILE)  # Atomic on same filesystem
        except Exception as e:
            logger.error(f"[NewsIntel] Loi ghi event history: {e}")
            try:
                os.remove(tmp_file)
            except OSError:
                pass

    def _get_llm(self):
        """
        Lazy-load LLM client.

        Repo cung cap singleton `ai.llm_client.llm_client` (Khong co ham get_provider
        nhu ban truoc -> luon ImportError va phai fallback keyword).
        """
        if self._llm_provider is None:
            try:
                from ai.llm_client import llm_client
                self._llm_provider = llm_client
            except Exception as e:
                logger.warning(f"[NewsIntel] LLM khong kha dung: {e}")
        return self._llm_provider

    # ==========================================
    #  1. LLM-POWERED NEWS ANALYZER
    # ==========================================

    async def analyze_news_llm(self, headline: str, source: str = "") -> dict:
        """
        Dung LLM de phan tich tac dong cua tin tuc len crypto.
        Chi goi khi tin co impact >= HIGH de tiet kiem credit.

        Returns:
            {
                "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
                "confidence": 0.0 - 1.0,
                "impact_duration": "1-4h" | "4-12h" | "12-24h" | "24-48h",
                "reasoning": "...",
                "affected_coins": ["BTC", "ETH"],
                "trade_recommendation": "...",
            }
        """
        # M4 fix: ton trong cau hinh NEWS_LLM_FOR_HIGH_IMPACT
        if Config is not None and not Config.NEWS_LLM_FOR_HIGH_IMPACT:
            return self._keyword_fallback(headline)

        # Cache theo headline de tiet kiem LLM credit (_news_cache truoc day khong dung)
        cache_key = headline.strip().lower()[:200]
        cached = self._news_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < self._cache_ttl:
            return cached[1]

        llm = self._get_llm()
        if not llm or not llm.is_ready():
            # Fallback: keyword-based
            return self._keyword_fallback(headline)

        system_prompt = """Bạn là chuyên gia phân tích tác động tin tức lên thị trường crypto.
Phân tích headline sau và trả về JSON object (KHÔNG markdown, KHÔNG code block):
{
    "direction": "BULLISH" hoặc "BEARISH" hoặc "NEUTRAL",
    "confidence": số từ 0.0 đến 1.0 (mức độ chắc chắn),
    "impact_duration": "1-4h" hoặc "4-12h" hoặc "12-24h" hoặc "24-48h",
    "reasoning": "giải thích ngắn gọn tại sao (1-2 câu)",
    "affected_coins": ["BTC", "ETH"],
    "trade_recommendation": "khuyến nghị giao dịch ngắn gọn"
}

Quy tắc:
- Rate cut, dovish → BULLISH cho crypto
- Rate hike, hawkish → BEARISH cho crypto  
- CPI thấp hơn dự kiến → BULLISH (kỳ vọng cắt lãi suất)
- CPI cao hơn dự kiến → BEARISH
- ETF approved → BULLISH mạnh
- SEC enforcement → BEARISH
- Hack, exploit → BEARISH cho coin bị hack
- Nếu không rõ → NEUTRAL với confidence thấp"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Headline: {headline}\nSource: {source}"}
        ]

        try:
            response = await llm.complete(
                messages=messages,
                model=None,  # Dung model mac dinh (Config.OMNIROUTER_MODEL)
                max_tokens=500,
                temperature=0.2,
            )

            # Parse JSON response
            # Loai bo markdown code block neu co
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()

            result = json.loads(clean)

            # Validate
            direction = result.get("direction", "NEUTRAL").upper()
            if direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
                direction = "NEUTRAL"
            confidence = max(0, min(1, float(result.get("confidence", 0.5))))

            parsed = {
                "direction": direction,
                "confidence": confidence,
                "impact_duration": result.get("impact_duration", "4-12h"),
                "reasoning": result.get("reasoning", ""),
                "affected_coins": result.get("affected_coins", ["BTC"]),
                "trade_recommendation": result.get("trade_recommendation", ""),
                "method": "LLM",
            }
            logger.info(f"[NewsIntel] LLM: {headline[:60]}... → {direction} (conf={confidence:.0%})")
            self._news_cache[cache_key] = (time.time(), parsed)
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"[NewsIntel] LLM response khong phai JSON: {e}")
            return self._keyword_fallback(headline)
        except Exception as e:
            logger.error(f"[NewsIntel] LLM error: {e}")
            return self._keyword_fallback(headline)

    def _keyword_fallback(self, headline: str) -> dict:
        """Fallback ve keyword-based khi LLM khong kha dung."""
        try:
            from analytics.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            result = analyzer.analyze_text(headline)

            direction = result.get("sentiment", "neutral").upper()
            if direction == "BULLISH":
                confidence = min(0.7, 0.3 + abs(result.get("score", 0)) * 0.08)
            elif direction == "BEARISH":
                confidence = min(0.7, 0.3 + abs(result.get("score", 0)) * 0.08)
            else:
                direction = "NEUTRAL"
                confidence = 0.3

            return {
                "direction": direction,
                "confidence": confidence,
                "impact_duration": "4-12h",
                "reasoning": f"Keyword analysis: score={result.get('score', 0)}",
                "affected_coins": ["BTC"],
                "trade_recommendation": "",
                "method": "keyword_fallback",
            }
        except Exception:
            return {
                "direction": "NEUTRAL", "confidence": 0.2,
                "impact_duration": "4-12h", "reasoning": "Fallback",
                "affected_coins": ["BTC"], "trade_recommendation": "",
                "method": "error_fallback",
            }

    async def enrich_news_with_llm(self, news_items: list, max_items: int = 2) -> list:
        """
        Bo sung phan tich LLM cho nhung tin quan trong nhat (toi da max_items tin).

        Truoc day analyze_news_llm() va Config.NEWS_LLM_FOR_HIGH_IMPACT khong duoc dung o dau.
        Neu LLM tra confidence >= 0.6 thi ghi de sentiment/sentiment_score de
        get_news_bias() thuc su dung ket qua LLM.
        """
        if not news_items:
            return news_items
        if Config is not None and not Config.NEWS_LLM_FOR_HIGH_IMPACT:
            return news_items

        enriched = []
        used = 0
        for news in news_items:
            if used < max_items and news.get("is_important"):
                try:
                    analysis = await self.analyze_news_llm(
                        news.get("title", ""), news.get("source", "")
                    )
                    if analysis and analysis.get("method") == "LLM":
                        news = dict(news)
                        news["llm_analysis"] = analysis
                        if float(analysis.get("confidence", 0)) >= 0.6:
                            llm_dir = str(analysis.get("direction", "NEUTRAL")).lower()
                            news["sentiment"] = llm_dir
                            news["sentiment_score"] = (
                                3 if llm_dir == "bullish" else (-3 if llm_dir == "bearish" else 0)
                            )
                        used += 1
                except Exception as e:
                    logger.debug(f"[NewsIntel] LLM enrich error: {e}")
            enriched.append(news)

        if used:
            logger.info(f"[NewsIntel] Da phan tich LLM cho {used} tin quan trong")
        return enriched

    # ==========================================
    #  2. EVENT IMPACT DATABASE
    # ==========================================

    def record_event_outcome(
        self,
        event_type: str,
        event_date: str,
        before_price: float,
        after_1h_price: float,
        after_24h_price: float,
        actual_result: str = "",
        forecast: str = "",
    ):
        """
        Ghi nhan ket qua thuc te sau su kien.
        Dung de build database lich su phan ung.
        """
        key = f"{event_type}_{event_date}"

        change_1h = (after_1h_price - before_price) / before_price if before_price > 0 else 0
        change_24h = (after_24h_price - before_price) / before_price if before_price > 0 else 0

        if change_1h > 0.01:
            reaction = "BULLISH"
        elif change_1h < -0.01:
            reaction = "BEARISH"
        else:
            reaction = "NEUTRAL"

        self.event_history[key] = {
            "event_type": event_type,
            "event_date": event_date,
            "before_price": before_price,
            "after_1h_price": after_1h_price,
            "after_24h_price": after_24h_price,
            "change_1h_pct": round(change_1h * 100, 2),
            "change_24h_pct": round(change_24h * 100, 2),
            "reaction": reaction,
            "actual_result": actual_result,
            "forecast": forecast,
            "recorded_at": datetime.now().isoformat(),
        }
        self._save_event_history()
        logger.info(f"[NewsIntel] Recorded event: {key} → {reaction} ({change_1h:+.1%} / {change_24h:+.1%})")

    @staticmethod
    def _parse_event_dt(ev: dict) -> Optional[datetime]:
        """
        Parse thoi diem su kien ve datetime naive (local time).

        Ho tro ca ISO co timezone (live events) va chi co 'date' (built-in events),
        de so sanh duoc voi datetime.now() va chuyen sang epoch ms cho Binance.
        """
        raw = ev.get("datetime") or ""
        dt = None
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            dt = None
        if dt is None:
            try:
                dt = datetime.strptime(str(ev.get("date", ""))[:10], "%Y-%m-%d")
            except Exception:
                return None
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt

    async def _fetch_btc_prices_around(self, event_dt: datetime) -> Optional[tuple]:
        """
        Lay gia dong cua BTC (Binance public klines, khong can API key):
        - before    : candle 1h ket thuc ngay tai thoi diem su kien
        - after_1h  : +1h sau su kien
        - after_24h : +24h sau su kien

        Tra ve tuple (before, after_1h, after_24h) hoac None neu khong du du lieu.
        """
        try:
            import httpx
        except ImportError:
            logger.debug("[NewsIntel] httpx khong kha dung, bo qua auto-record")
            return None

        start_ms = int(event_dt.timestamp() * 1000) - 3600 * 1000
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={
                        "symbol": "BTCUSDT",
                        "interval": "1h",
                        "startTime": start_ms,
                        "limit": 26,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"[NewsIntel] Binance klines HTTP {resp.status_code}")
                    return None
                rows = resp.json()
        except Exception as e:
            logger.debug(f"[NewsIntel] Binance klines error: {e}")
            return None

        # Can it nhat 25 candle (t-1h .. t+24h)
        if not rows or len(rows) < 25:
            return None
        try:
            before = float(rows[0][4])
            after_1h = float(rows[1][4])
            after_24h = float(rows[24][4])
        except (IndexError, ValueError, TypeError):
            return None
        if before <= 0:
            return None
        return before, after_1h, after_24h

    async def auto_record_past_events(self, events: list, lookback_days: int = 7) -> int:
        """
        Tu dong ghi nhan ket qua cac su kien macro da qua vao Event Impact DB.

        Truoc day record_event_outcome() khong co caller nao -> DB luon rong
        -> get_historical_reaction() luon total_events=0 -> event_bias luon NEUTRAL.
        Chi xu ly su kien CRITICAL/HIGH da qua >= 24h (de co du gia +24h) va chua co trong DB.
        Toi da 5 su kien/chu ky de tranh goi API qua nhieu.

        Returns:
            So su kien ghi nhan duoc trong lan goi nay.
        """
        if not events or not self.auto_record_enabled:
            return 0

        now = datetime.now()
        cutoff = now - timedelta(days=lookback_days)
        recorded = 0

        for ev in events:
            if recorded >= 5:
                break
            if not ev.get("is_past"):
                continue
            if ev.get("impact") not in ("CRITICAL", "HIGH"):
                continue

            event_type = ev.get("type", "OTHER")
            event_date = ev.get("date", "")
            if not event_date:
                continue
            if f"{event_type}_{event_date}" in self.event_history:
                continue  # Da ghi nhan truoc do

            event_dt = self._parse_event_dt(ev)
            if event_dt is None or event_dt < cutoff:
                continue
            if (now - event_dt).total_seconds() < 24 * 3600:
                continue  # Chua du 24h de danh gia

            prices = await self._fetch_btc_prices_around(event_dt)
            if not prices:
                continue
            before_price, after_1h, after_24h = prices

            try:
                self.record_event_outcome(
                    event_type=event_type,
                    event_date=event_date,
                    before_price=before_price,
                    after_1h_price=after_1h,
                    after_24h_price=after_24h,
                    actual_result=str(ev.get("actual", "")),
                    forecast=str(ev.get("forecast", "")),
                )
                recorded += 1
            except Exception as e:
                logger.debug(f"[NewsIntel] Record outcome error {event_type}_{event_date}: {e}")

        return recorded

    def get_historical_reaction(self, event_type: str, limit: int = 10) -> dict:
        """
        Tra cuu lich su phan ung cua BTC sau su kien tuong tu.

        Returns:
            {
                "event_type": "FOMC",
                "total_events": 7,
                "bullish_count": 5,
                "bearish_count": 2,
                "bullish_pct": 71.4,
                "avg_1h_change": +2.3%,
                "avg_24h_change": +1.8%,
                "bias": "BULLISH",
                "confidence": 0.71,
                "recent_events": [...],
            }
        """
        relevant = [
            v for k, v in self.event_history.items()
            if v.get("event_type") == event_type
        ]

        # Sap xep theo thoi gian moi nhat
        relevant.sort(key=lambda x: x.get("event_date", ""), reverse=True)
        relevant = relevant[:limit]

        if not relevant:
            return {
                "event_type": event_type,
                "total_events": 0,
                "bias": "NEUTRAL",
                "confidence": 0,
                "message": f"Chua co du lieu lich su cho {event_type}. Bot se tu dong ghi nhan sau moi su kien.",
            }

        bullish = sum(1 for e in relevant if e["reaction"] == "BULLISH")
        bearish = sum(1 for e in relevant if e["reaction"] == "BEARISH")
        total = len(relevant)

        avg_1h = sum(e.get("change_1h_pct", 0) for e in relevant) / total
        avg_24h = sum(e.get("change_24h_pct", 0) for e in relevant) / total

        bullish_pct = bullish / total if total > 0 else 0.5

        if bullish_pct > 0.6:
            bias = "BULLISH"
        elif bullish_pct < 0.4:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return {
            "event_type": event_type,
            "total_events": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "bullish_pct": round(bullish_pct * 100, 1),
            "avg_1h_change": round(avg_1h, 2),
            "avg_24h_change": round(avg_24h, 2),
            "bias": bias,
            "confidence": round(abs(bullish_pct - 0.5) * 2, 2),  # 0-1, max khi 100% hoac 0%
            "recent_events": relevant[:5],
        }

    # ==========================================
    #  3. PRE-EVENT POSITIONING
    # ==========================================

    def get_event_adjustments(self, upcoming_events: list) -> dict:
        """
        Dua tren su kien sap dien ra, tinh toan dieu chinh chien luoc.

        Args:
            upcoming_events: list su kien tu MacroCalendar.get_all_events()

        Returns:
            {
                "has_critical_event": True/False,
                "leverage_mult": 0.5 - 1.0,
                "sl_mult": 1.0 - 1.6,
                "rating_adjust": -1 to 0,  # M7: chi tru sao cho HIGH; CRITICAL dung pause
                "should_pause_auto_trade": True/False,
                "event_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
                "event_confidence": 0.0 - 1.0,
                "warnings": [...],
                "recommendations": [...],
            }
        """
        result = {
            "has_critical_event": False,
            "leverage_mult": 1.0,
            "sl_mult": 1.0,
            "rating_adjust": 0,
            "should_pause_auto_trade": False,
            "event_bias": "NEUTRAL",
            "event_confidence": 0,
            "warnings": [],
            "recommendations": [],
        }

        if not upcoming_events:
            return result

        for ev in upcoming_events:
            if ev.get("is_past"):
                continue

            hours_until = ev.get("hours_until", 999)
            impact = ev.get("impact", "LOW")
            event_type = ev.get("type", "OTHER")

            # Su kien CRITICAL trong 24h
            if impact == "CRITICAL" and 0 < hours_until <= 24:
                result["has_critical_event"] = True
                result["leverage_mult"] = min(result["leverage_mult"], 0.5)  # Giam leverage 50%
                result["sl_mult"] = max(result["sl_mult"], 1.5)              # Mo rong SL 50%
                # M7 fix: KHONG cong don rating_adjust cho CRITICAL nua.
                # Truoc day CRITICAL bi tru 2 sao VA pause auto-trade (double penalty):
                # rating bi bien dang o ca tin hieu manual trong khi auto-trade
                # da duoc chan tu truoc. Chon 1 co che: CRITICAL = pause,
                # HIGH = tru sao. Canh bao van hien trong tin nhan Telegram/Zalo
                # de trader manual tu quyet dinh.
                result["should_pause_auto_trade"] = True

                # Check lich su
                hist = self.get_historical_reaction(event_type)
                if hist.get("total_events", 0) >= 3:
                    result["event_bias"] = hist["bias"]
                    result["event_confidence"] = hist["confidence"]

                result["warnings"].append(
                    f"🔴 {ev['title']} trong {hours_until:.0f}h — "
                    f"Bien dong du kien: {ev.get('info', {}).get('crypto_impact', 'manh')}"
                )
                result["recommendations"].append(
                    ev.get("info", {}).get("advice_before", "Giam leverage, mo rong SL")
                )

            # Su kien HIGH trong 24h
            elif impact in ("CRITICAL", "HIGH") and 0 < hours_until <= 24:
                result["leverage_mult"] = min(result["leverage_mult"], 0.7)
                result["sl_mult"] = max(result["sl_mult"], 1.3)
                result["rating_adjust"] = min(result["rating_adjust"], -1)

                result["warnings"].append(
                    f"🟡 {ev['title']} trong {hours_until:.0f}h"
                )

            # Su kien trong 48h
            elif impact in ("CRITICAL", "HIGH") and 0 < hours_until <= 48:
                result["leverage_mult"] = min(result["leverage_mult"], 0.85)
                result["sl_mult"] = max(result["sl_mult"], 1.15)

        return result

    # ==========================================
    #  4. COMPOSITE NEWS BIAS
    # ==========================================

    async def get_news_bias(self, recent_news: list = None, upcoming_events: list = None) -> dict:
        """
        Tong hop bias tu tin tuc + su kien.

        Returns:
            {
                "news_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
                "news_confidence": 0.0 - 1.0,
                "rating_adjust": -2 to +1,
                "leverage_mult": 0.5 - 1.0,
                "sl_mult": 1.0 - 1.6,
                "warnings": [...],
            }
        """
        # Event adjustments
        event_adj = self.get_event_adjustments(upcoming_events or [])

        # News sentiment (top 5 tin moi nhat)
        news_dir_score = 0
        if recent_news:
            for news in recent_news[:5]:
                sentiment = news.get("sentiment", "neutral")
                score = news.get("sentiment_score", 0)
                is_important = news.get("is_important", False)
                weight = 2 if is_important else 1
                if sentiment == "bullish":
                    news_dir_score += weight
                elif sentiment == "bearish":
                    news_dir_score -= weight

        # Combine
        if news_dir_score > 2:
            news_bias = "BULLISH"
            news_confidence = min(0.7, 0.3 + news_dir_score * 0.1)
        elif news_dir_score < -2:
            news_bias = "BEARISH"
            news_confidence = min(0.7, 0.3 + abs(news_dir_score) * 0.1)
        else:
            news_bias = "NEUTRAL"
            news_confidence = 0.3

        # Override voi event bias neu co
        if event_adj["has_critical_event"] and event_adj["event_bias"] != "NEUTRAL":
            news_bias = event_adj["event_bias"]
            news_confidence = max(news_confidence, event_adj["event_confidence"])

        # Rating adjust tu news + events
        news_rating = 0
        if news_bias == "BULLISH" and news_confidence > 0.5:
            news_rating = 1
        elif news_bias == "BEARISH" and news_confidence > 0.5:
            news_rating = -1

        total_rating_adjust = news_rating + event_adj["rating_adjust"]
        total_rating_adjust = max(-2, min(1, total_rating_adjust))

        return {
            "news_bias": news_bias,
            "news_confidence": round(news_confidence, 2),
            "rating_adjust": total_rating_adjust,
            "leverage_mult": event_adj["leverage_mult"],
            "sl_mult": event_adj["sl_mult"],
            "should_pause_auto_trade": event_adj["should_pause_auto_trade"],
            "warnings": event_adj["warnings"],
            "recommendations": event_adj["recommendations"],
            "news_score": news_dir_score,
            "event_details": event_adj,
        }
