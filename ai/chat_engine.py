"""
Chat Engine - Trợ lý AI của bot.

Flow:
1. _parse_question()   : nhận diện coin + intent từ câu hỏi tự nhiên
2. _build_context()    : thu thập dữ liệu thật (giá + kỹ thuật + tin tức + sentiment) chạy song song
3. _build_messages()   : ghép system prompt (role + rule + dữ liệu) + history + câu hỏi
4. ask()               : gọi LLM qua llm_client, lưu history, có fallback phân tích kỹ thuật thuần

Nguyên tắc CHỐNG HALLUCINATE: LLM chỉ được dựa vào dữ liệu context đã thu thập,
không được tự bịa giá trị. Nếu thiếu dữ liệu -> nói thiếu.
"""
import asyncio
import re
import time
from collections import deque
from typing import Optional

from loguru import logger

from ai.llm_client import llm_client, LLMError
from analytics.technical import TechnicalAnalyzer
from analytics.sentiment import SentimentAnalyzer
from data_ingestion.news_crawler import NewsCrawler
from data_ingestion.binance_ws import BinanceWebSocket
from core.config import Config


class ChatEngine:
    """Trợ lý AI: câu hỏi tự nhiên -> trả lời có dữ liệu thật."""

    # Alias đặc biệt (inject từ analyze_token để nhất quán)
    COIN_ALIASES = {"GOLD": "PAXG", "XAU": "PAXG"}

    # Các từ thường gặp trong câu hỏi tiếng Việt/Anh KHÔNG phải coin
    STOPWORDS = {
        "THE", "AND", "FOR", "YOU", "NOT", "HOW", "WHY", "WHAT", "WHEN",
        "BTCUSDT", "ETHUSDT", "HOM", "NAY", "KHONG", "VI", "SAO", "NAO",
        "GI", "ROI", "THE", "NHIEU", "DAU", "DAY", "CHUA", "CON", "NEN",
        "THI", "SAO", "LAM", "AY", "VAY", "MINH", "TOI", "HIEU", "QUA",
    }

    def __init__(self, max_history: Optional[int] = None):
        self._history: dict[int, deque] = {}
        self._max_history = max_history or Config.LLM_MAX_HISTORY

    # ============================
    #  1. INTENT PARSER
    # ============================

    def _parse_question(self, question: str) -> dict:
        """Nhận diện coin và intent từ câu hỏi."""
        q_upper = question.upper()

        # Tìm symbol trong câu hỏi (ưu tiên coin phổ biến trước để tránh match nhầm)
        common = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
                  "LINK", "DOT", "MATIC", "TRX", "LTC", "NEAR", "APT", "ARB",
                  "OP", "SUI", "TON", "PEPE", "SHIB", "WIF", "BONK", "PAXG",
                  "GOLD", "XAU"]
        coin = None
        for c in common:
            if re.search(rf"\b{c}\b", q_upper):
                coin = c
                break

        if coin is None:
            # Fallback: chi nhan cac tu duoc go HOA san trong nguyen van (dang ticker).
            # KHONG uppercase ca cau - neu khong cac tu tieng Viet thuong
            # ("thi truong") se bi nhan nham la coin (TRUONG).
            for word in re.findall(r"\b[A-Z0-9]{2,10}\b", question):
                if not word[0].isalpha():
                    continue  # bo qua so (VD "69000")
                if word in self.STOPWORDS:
                    continue
                coin = word
                break

        if coin:
            coin = self.COIN_ALIASES.get(coin, coin)

        # Intent: ngắn gọn, chỉ để gợi ý giọng điệu trả lời, không thay đổi flow
        q_lower = question.lower()
        if any(k in q_lower for k in ("long", "short", "mua", "bán", "ban ",
                                      "vào lệnh", "vao lenh", "entry", "nên", "nen ")):
            intent = "entry"
        elif any(k in q_lower for k in ("tin tức", "tin tuc", "news", "tin gì", "tin gi")):
            intent = "news"
        else:
            intent = "trend"

        return {"coin": coin, "intent": intent}

    # ============================
    #  2. CONTEXT BUILDER
    # ============================

    async def _build_context(self, coin: Optional[str]) -> str:
        """
        Thu thập dữ liệu thật thành block ngắn gọn cho prompt.
        Chạy song song bằng asyncio.gather. coin=None -> context tổng quan (BTC làm chuẩn).
        """
        analyzer = TechnicalAnalyzer()
        crawler = NewsCrawler()

        # Fear & Greed (lấy qua cache của API server nếu có)
        fng_value, fng_sent = None, None
        try:
            from api.server import get_fear_and_greed
            fng = get_fear_and_greed()
            fng_value = fng.get("value")
            fng_sent = fng.get("sentiment")
        except Exception:
            pass

        # Coin chính để lấy kỹ thuật/giá (mặc định BTC làm chuẩn thị trường)
        target = coin or "BTC"
        symbol = f"{target}/USDT"
        symbol_raw = f"{target}USDT".lower()

        async def get_price():
            try:
                ws = BinanceWebSocket()
                data = await ws.get_price_once(symbol_raw)
                return data.get("price") if data else None
            except Exception as e:
                logger.warning(f"ChatEngine get_price {target} lỗi: {e}")
                return None

        async def get_signal_4h():
            try:
                return await analyzer.analyze(symbol, "4h")
            except Exception as e:
                logger.warning(f"ChatEngine analyze 4h {symbol} lỗi: {e}")
                return None

        async def get_signal_1d():
            try:
                return await analyzer.analyze(symbol, "1d")
            except Exception as e:
                logger.warning(f"ChatEngine analyze 1d {symbol} lỗi: {e}")
                return None

        async def get_news():
            try:
                return await crawler.fetch_by_coin(target, limit=3)
            except Exception as e:
                logger.warning(f"ChatEngine fetch_news {target} lỗi: {e}")
                return []

        price, sig_4h, sig_1d, news = await asyncio.gather(
            get_price(), get_signal_4h(), get_signal_1d(), get_news()
        )

        # Sentiment tin tức
        mood = None
        if news:
            try:
                sa = SentimentAnalyzer()
                mood = sa.get_market_mood(sa.analyze_news_batch(news))
            except Exception as e:
                logger.warning(f"ChatEngine sentiment lỗi: {e}")

        # ----- Build block text ngắn gọn (tiết kiệm token) -----
        now = time.strftime("%d/%m/%Y %H:%M UTC", time.gmtime())
        lines = [f"DỮ LIỆU THỊ TRƯỜNG THỰC (cập nhật {now}):"]

        if price:
            lines.append(f"- Giá {target}/USDT hiện tại: {price}")
        else:
            lines.append(f"- Giá {target}/USDT: không lấy được")

        for label, sig in (("4h", sig_4h), ("1d", sig_1d)):
            if sig:
                lines.append(
                    f"- Kỹ thuật {target} khung {label}: hướng={sig.get('direction', '?')}, "
                    f"bull={sig.get('bull_score', 0)}, bear={sig.get('bear_score', 0)}, "
                    f"RSI={sig.get('rsi', '?')}"
                )
                reasons = sig.get("reasons", [])
                if reasons:
                    lines.append(f"  Lý do: {'; '.join(str(r) for r in reasons[:3])}")

        if fng_value is not None:
            lines.append(f"- Chỉ số Fear & Greed: {fng_value}/100 ({fng_sent})")

        if mood:
            lines.append(
                f"- Sentiment tin tức {target}: score={mood.get('avg_score', 0)} "
                f"({mood.get('label', '?')})"
            )

        if news:
            lines.append(f"- Tin tức {target} mới nhất:")
            for n in news[:3]:
                lines.append(f"  * {n.get('title', '')}")

        lines.append(
            "Lưu ý: đây là DỮ LIỆU THẬT đã thu thập. KHÔNG được bịa giá trị khác "
            "ngoài số liệu trên. Nếu dữ liệu thiếu thì nói thiếu."
        )
        return "\n".join(lines)

    # ============================
    #  3. MESSAGE BUILDER
    # ============================

    def _build_messages(self, question: str, context: str, history: deque) -> list[dict]:
        system_prompt = (
            "Bạn là 'Trợ Lý AI' của hệ thống Crypto Bot - trợ lý giao dịch crypto thông minh. "
            "QUY TẮC BẮT BUỘC:\n"
            "1. Trả lời bằng TIẾNG VIỆT, ngắn gọn, dễ hiểu, dùng bullet point.\n"
            "2. CHỈ dựa trên DỮ LIỆU THỊ TRƯỜNG THỰC được cung cấp trong prompt này. "
            "Tuyệt đối không được tự bịa giá trị hoặc số liệu không có trong dữ liệu.\n"
            "3. Khi đủ dữ liệu, nếu khuyến nghị thì nói rõ: xu hướng (LONG/SHORT/ĐỢI), "
            "thận trọng với mức giá, ưu tiên dẫn giải thích lý do kỹ thuật.\n"
            "4. Nếu câu hỏi ngoài phạm vi crypto/thị trường -> trả lời ngắn và dẫn lại topic thị trường.\n"
            "5. Luôn kết thúc câu trả lời bằng dòng: "
            "'⚠️ Đây là phân tích tự động, không phải lời khuyên tài chính. Tự quyết định và chịu trách nhiệm.'"
        )

        messages = [{"role": "system", "content": system_prompt + "\n\n" + context}]
        # History giúp hỏi tiếp theo (VD: "còn SOL thì sao?")
        for turn in list(history)[-self._max_history:]:
            messages.append(turn)
        messages.append({"role": "user", "content": question})
        return messages

    # ============================
    #  4. PUBLIC API
    # ============================

    def reset_history(self, chat_id: int) -> None:
        self._history.pop(chat_id, None)

    def get_history_len(self, chat_id: int) -> int:
        return len(self._history.get(chat_id, deque()))

    async def ask(self, question: str, chat_id: int = 0) -> dict:
        """
        Câu hỏi -> dict {answer, coin, intent, used_fallback, model, latency_ms}.

        Nếu LLM lỗi -> fallback: trả phân tích kỹ thuật thuần từ dữ liệu đã thu thập
        (vẫn có giá trị dùng ngay, không để bot im lặng).
        """
        start = time.time()
        parsed = self._parse_question(question)
        coin, intent = parsed["coin"], parsed["intent"]

        context = await self._build_context(coin)

        history = self._history.setdefault(chat_id, deque(maxlen=self._max_history))

        result = {
            "answer": "",
            "coin": coin,
            "intent": intent,
            "used_fallback": False,
            "model": llm_client.get_model(),
            "latency_ms": 0,
        }

        # --- Thử LLM ---
        try:
            if not llm_client.is_ready():
                raise LLMError("LLM chưa được cấu hình (thiếu API key)")

            messages = self._build_messages(question, context, history)
            result["answer"] = await llm_client.complete(messages)
        except LLMError as e:
            logger.error(f"ChatEngine LLM lỗi: {e}")
            result["answer"] = self._fallback_answer(context, str(e))
            result["used_fallback"] = True
        except Exception as e:
            logger.error(f"ChatEngine lỗi không xác định: {e}")
            result["answer"] = self._fallback_answer(context, str(e))
            result["used_fallback"] = True

        # Lưu history (cả khi fallback - user vẫn coi là câu trả lời)
        history.append({"role": "user", "content": question})
        history.append({
            "role": "assistant",
            "content": result["answer"][:2000],
        })

        result["latency_ms"] = int((time.time() - start) * 1000)
        return result

    # ============================
    #  5. FALLBACK (LLM chết vẫn trả lời được)
    # ============================

    def _fallback_answer(self, context: str, error: str) -> str:
        """LLM lỗi -> dọn context thành phân tích kỹ thuật thuần (HTML)."""
        lines = [
            "\U0001F916 <b>TRỢ LÝ AI TẠM THỜI KHÔNG KHẢ DỤNG</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"<i>Nguyên nhân: LLM ({Config.LLM_PROVIDER}) lỗi - {error}</i>",
            "",
            "<b>Kết quả phân tích kỹ thuật mới nhất:</b>",
            "",
        ]
        for line in context.split("\n"):
            if line.startswith("Lưu ý"):
                continue
            lines.append(f"◽ {line}")
        lines += [
            "",
            "\u26A0\uFE0F Đây là phân tích tự động, không phải lời khuyên tài chính.",
        ]
        return "\n".join(lines)
