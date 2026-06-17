"""
Script tong hop: Phan tich TA + Tin tuc + Gia real-time -> Gui Telegram.
Chay: python scripts/test_full_analysis.py

Day la ban demo ghep 3 module lai voi nhau:
1. Lay gia real-time tu Binance
2. Cao tin tuc tu CryptoPanic + RSS
3. Phan tich ky thuat (RSI, MACD) + Sentiment tin tuc
4. Gui ket qua tong hop ve Telegram
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.config import Config
from analytics.technical import TechnicalAnalyzer
from analytics.sentiment import SentimentAnalyzer
from data_ingestion.news_crawler import NewsCrawler
from notifiers.telegram_bot import TelegramNotifier


async def main():
    Config.TELEGRAM_CHAT_ID = "8023393059"

    analyzer = TechnicalAnalyzer()
    sentiment = SentimentAnalyzer()
    crawler = NewsCrawler()
    notifier = TelegramNotifier()

    coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    try:
        # ========================================
        # PHAN 1: PHAN TICH KY THUAT (TA)
        # ========================================
        print("=" * 50)
        print("PHAN TICH KY THUAT")
        print("=" * 50)

        ta_results = []
        for coin in coins:
            print(f"\nDang phan tich {coin}...")
            signal = await analyzer.analyze(coin, "1h")
            if signal:
                ta_results.append(signal)
                direction = signal["direction"]
                price = signal["price"]
                rsi = signal.get("rsi", "N/A")
                reasons = " | ".join(signal.get("reasons", []))
                print(f"  {coin}: ${price:,.2f} | {direction} | RSI: {rsi:.1f}")
                print(f"  Ly do: {reasons}")

        # ========================================
        # PHAN 2: TIN TUC & SENTIMENT
        # ========================================
        print(f"\n{'=' * 50}")
        print("TIN TUC & SENTIMENT")
        print("=" * 50)

        news = await crawler.fetch_cryptopanic("hot", limit=5)
        if not news:
            news = await crawler.fetch_rss(limit_per_source=2)

        analyzed_news = sentiment.analyze_news_batch(news)
        market_mood = sentiment.get_market_mood(analyzed_news)

        print(f"\nTam ly thi truong: {market_mood['mood']} (Score: {market_mood['avg_score']})")
        for n in analyzed_news[:5]:
            s = n.get("sentiment", "neutral")
            emoji = {"bullish": "+", "bearish": "-", "neutral": "o"}
            print(f"  [{emoji.get(s, 'o')}] {n['title'][:70]}...")

        # ========================================
        # PHAN 3: GUI KET QUA VE TELEGRAM
        # ========================================

        # 3a. Gui bang phan tich ky thuat
        ta_lines = ["<b>PHAN TICH KY THUAT (H1)</b>", ""]
        for sig in ta_results:
            name = sig["symbol"].replace("/USDT", "")
            d = sig["direction"]
            if d == "LONG":
                emoji = "LONG"
            elif d == "SHORT":
                emoji = "SHORT"
            else:
                emoji = "TRUNG LAP"

            ta_lines.append(f"<b>{name}:</b> <code>${sig['price']:,.2f}</code>")

            rsi_val = sig.get("rsi")
            if rsi_val is not None:
                ta_lines.append(f"  RSI: {rsi_val:.1f} | Xu huong: {emoji}")
            else:
                ta_lines.append(f"  Xu huong: {emoji}")

            reasons_str = ", ".join(sig.get("reasons", [])[:2])
            if reasons_str:
                ta_lines.append(f"  {reasons_str}")
            ta_lines.append("")

        await notifier.send_message("\n".join(ta_lines))

        # 3b. Gui tin hieu neu co (Long/Short)
        for sig in ta_results:
            if sig["direction"] in ("LONG", "SHORT") and "entry" in sig:
                await notifier.send_signal(
                    coin=sig["symbol"],
                    direction=sig["direction"],
                    entry=sig["entry"],
                    sl=sig["sl"],
                    tp=sig["tp"],
                    reason=" + ".join(sig.get("reasons", [])[:3]),
                )

        # 3c. Gui tin tuc nong
        mood_emoji = {"BULLISH": "TICH CUC", "BEARISH": "TIEU CUC", "NEUTRAL": "TRUNG LAP"}
        news_lines = [
            f"<b>TIN TUC CRYPTO</b>",
            f"Tam ly: <b>{mood_emoji.get(market_mood['mood'], 'TRUNG LAP')}</b> "
            f"(Score: {market_mood['avg_score']:+.1f})",
            "",
        ]
        for n in analyzed_news[:5]:
            s = n.get("sentiment", "neutral")
            s_map = {"bullish": "[+]", "bearish": "[-]", "neutral": "[o]"}
            title = n["title"][:80]
            source = n.get("source", "")
            url = n.get("url", "")

            if url:
                news_lines.append(f"{s_map.get(s, '[o]')} <a href='{url}'>{title}</a>")
            else:
                news_lines.append(f"{s_map.get(s, '[o]')} {title}")
            if source:
                news_lines.append(f"    <i>{source}</i>")

        await notifier.send_message("\n".join(news_lines))

        print(f"\n{'=' * 50}")
        print("DA GUI TAT CA KET QUA VE TELEGRAM!")
        print("=" * 50)

    finally:
        await analyzer.close()
        await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())
