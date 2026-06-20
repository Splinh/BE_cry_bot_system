"""
Interactive Telegram Bot - Go ten token -> Nhan bao cao phan tich.
Chay: python main.py

Bot se lang nghe tin nhan tu Telegram:
- Go ten token (VD: BTC, ETH, SOL, DOGE) -> Phan tich day du + bao cao Entry/SL/TP
- /scan -> Quet nhanh top 3 coin (BTC, ETH, SOL)
- /news -> Tin tuc nong nhat
- /menu -> Hien thi menu lenh
"""
import asyncio
import html
import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from loguru import logger

from core.config import Config
from analytics.technical import TechnicalAnalyzer
from analytics.sentiment import SentimentAnalyzer
from data_ingestion.news_crawler import NewsCrawler
from data_ingestion.binance_ws import BinanceWebSocket
from airdrop.wallet_manager import WalletManager
from airdrop.onchain_bot import OnChainBot, NETWORKS
from airdrop.farming_bot import AirdropFarmer
from analytics.signal_tracker import SignalTracker
from analytics.macro_calendar import MacroCalendar
from analytics.dex_scanner import DexGemScanner
from analytics.listing_scanner import ListingScanner
from analytics.cex_airdrop import CexAirdropScanner
from core.security import SecurityManager
from execution.trade_engine import TradeEngine
from data.database import db as _db

from airdrop.social.telegram_worker import TelegramManager
from airdrop.social.twitter_worker import TwitterManager
from airdrop.wallet_manager import WalletManager
from data_ingestion.price_monitor import PriceMonitor

from api.server import run_server, inject_instances

# Global instances
trade_engine = TradeEngine()
signal_tracker = SignalTracker(trade_engine=trade_engine)
listing_scanner = ListingScanner()
security = SecurityManager()
telegram_manager = TelegramManager()
twitter_manager = TwitterManager()
price_monitor = PriceMonitor()
wallet_manager = WalletManager()

# Fake system status dict for overview API
system_status = {
    "status": "Running",
    "version": "1.0",
    "uptime_minutes": 0,
    "total_ping_count": 0
}


# ============================================
#  HANDLER: GO TEN TOKEN -> BAO CAO
# ============================================

async def analyze_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xu ly khi user go ten token (VD: BTC, ETH, SOL)."""
    text = update.message.text.strip().upper()

    # Loc ky tu, chi giu lai chu cai
    token = re.sub(r'[^A-Z0-9]', '', text)
    if not token or len(token) > 10:
        return  # Bo qua tin nhan khong hop le

    symbol = f"{token}/USDT"
    symbol_raw = f"{token}USDT"

    await update.message.reply_text(f"Dang phan tich {token}... vui long cho 5-10 giay")

    analyzer = TechnicalAnalyzer()
    sentiment_analyzer = SentimentAnalyzer()
    crawler = NewsCrawler()
    ws = BinanceWebSocket()

    try:
        # 1. Lay gia hien tai
        price_data = await ws.get_price_once(symbol_raw.lower())
        current_price = price_data["price"] if price_data else 0

        # 2. Phan tich ky thuat nhieu khung gio
        signals = {}
        timeframes = {"15m": "15 phut", "1h": "1 gio", "4h": "4 gio", "1d": "1 ngay"}

        for tf, tf_label in timeframes.items():
            try:
                signal = await analyzer.analyze(symbol, tf)
                if signal:
                    signals[tf] = signal
            except Exception as e:
                logger.warning(f"Loi phan tich {symbol} {tf}: {e}")

        if not signals and current_price == 0:
            await update.message.reply_text(
                f"Khong tim thay du lieu cho <b>{token}</b>.\n"
                f"Thu lai voi ten token chinh xac (VD: BTC, ETH, SOL, DOGE, XRP...)",
                parse_mode="HTML",
            )
            return

        # 3. Tin tuc lien quan
        news = await crawler.fetch_by_coin(token, limit=3)
        analyzed_news = sentiment_analyzer.analyze_news_batch(news) if news else []
        market_mood = sentiment_analyzer.get_market_mood(analyzed_news)

        # 4. TACH LOGIC: SPOT (chi mua, xu huong dai) vs FUTURES (long/short, ngan han)
        # =====================================================================

        mood_score = market_mood.get("avg_score", 0)

        # --- FUTURES: Dung tat ca khung gio (15m, 1h, 4h, 1d) ---
        fut_bull = sum(s.get("bull_score", 0) for s in signals.values())
        fut_bear = sum(s.get("bear_score", 0) for s in signals.values())
        if mood_score > 0:
            fut_bull += int(mood_score)
        elif mood_score < 0:
            fut_bear += abs(int(mood_score))

        if fut_bull > fut_bear and fut_bull >= 4:
            fut_direction = "LONG"
            fut_confidence = min(95, 50 + (fut_bull - fut_bear) * 5)
        elif fut_bear > fut_bull and fut_bear >= 4:
            fut_direction = "SHORT"
            fut_confidence = min(95, 50 + (fut_bear - fut_bull) * 5)
        else:
            fut_direction = "NEUTRAL"
            fut_confidence = 30

        # --- SPOT: Chi dung khung 4h va 1d (xu huong dai han) ---
        spot_bull = 0
        spot_reasons = []
        for tf in ["4h", "1d"]:
            sig = signals.get(tf)
            if sig:
                spot_bull += sig.get("bull_score", 0)
                if sig.get("direction") == "LONG":
                    spot_reasons.extend(sig.get("reasons", [])[:2])

        # Cong diem sentiment
        if mood_score > 0:
            spot_bull += int(mood_score)
            spot_reasons.append("Tin tuc tich cuc")

        if spot_bull >= 3:
            spot_direction = "MUA"
            spot_confidence = min(95, 50 + spot_bull * 5)
        else:
            spot_direction = "CHUA NEN MUA"
            spot_confidence = 30

        # 5. Tinh Entry/SL/TP
        price = current_price or (signals.get("1h", {}).get("price", 0))

        # --- SPOT: TP rong hon (dai han), SL rong hon ---
        if price > 0 and spot_direction == "MUA":
            entry_spot = price
            sl_spot = round(price * 0.95, 2)       # SL -5%
            tp1_spot = round(price * 1.05, 2)       # TP1 +5%
            tp2_spot = round(price * 1.10, 2)       # TP2 +10%
            tp3_spot = round(price * 1.20, 2)       # TP3 +20%
        else:
            entry_spot = sl_spot = tp1_spot = tp2_spot = tp3_spot = 0

        # --- FUTURES: TP chat hon (ngan han), SL chat hon ---
        if price > 0 and fut_direction in ("LONG", "SHORT"):
            entry_futures = price
            if fut_direction == "LONG":
                sl_futures = round(price * 0.985, 2)    # SL -1.5%
                tp1_futures = round(price * 1.02, 2)    # TP1 +2%
                tp2_futures = round(price * 1.04, 2)    # TP2 +4%
                tp3_futures = round(price * 1.07, 2)    # TP3 +7%
            else:  # SHORT
                sl_futures = round(price * 1.015, 2)    # SL +1.5%
                tp1_futures = round(price * 0.98, 2)    # TP1 -2%
                tp2_futures = round(price * 0.96, 2)    # TP2 -4%
                tp3_futures = round(price * 0.93, 2)    # TP3 -7%
        else:
            entry_futures = sl_futures = tp1_futures = tp2_futures = tp3_futures = 0

        # ========================================
        # TAO BAO CAO STYLE DEP
        # ========================================

        change = price_data.get("change_pct", 0) if price_data else 0

        # Emoji tong hop dua tren Futures (vi no bao quat hon)
        if fut_direction == "LONG":
            dir_emoji = "\U0001f7e2"
            dir_label = "LONG"
        elif fut_direction == "SHORT":
            dir_emoji = "\U0001f534"
            dir_label = "SHORT"
        else:
            dir_emoji = "\u26aa"
            dir_label = "CHO"

        # === MESSAGE 1: BAO CAO TONG HOP ===
        msg = f"{dir_emoji} <b>PHAN TICH {token}/USDT</b> {dir_emoji}\n"
        msg += "\u2501" * 18 + "\n"
        if price > 0:
            price_emoji = "\U0001f4c8" if change >= 0 else "\U0001f4c9"
            msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
            msg += f"{price_emoji} <b>Gia:</b> ${price:,.2f} ({change:+.2f}%)\n"

        # Spot va Futures khuyen nghi rieng
        spot_emoji = "\U0001f7e2" if spot_direction == "MUA" else "\u26aa"
        fut_emoji_label = "\U0001f7e2" if fut_direction == "LONG" else ("\U0001f534" if fut_direction == "SHORT" else "\u26aa")
        msg += f"\n\U0001f4b0 <b>SPOT:</b> {spot_emoji} {spot_direction} ({spot_confidence}%)\n"
        msg += f"\U0001f4ca <b>FUTURES:</b> {fut_emoji_label} {fut_direction} ({fut_confidence}%)\n"
        msg += "\u2501" * 18 + "\n\n"

        # Chi bao tung khung gio
        msg += "\U0001f50d <b>CHI BAO KY THUAT</b>\n"
        for tf, tf_label in timeframes.items():
            sig = signals.get(tf)
            if sig:
                d = sig["direction"]
                rsi = sig.get("rsi")
                if d == "LONG":
                    tf_icon = "\U0001f7e2"
                elif d == "SHORT":
                    tf_icon = "\U0001f534"
                else:
                    tf_icon = "\u26aa"
                rsi_str = f" | RSI: {rsi:.0f}" if rsi is not None else ""
                reasons_list = sig.get("reasons", [])[:2]
                reasons_str = html.escape(", ".join(reasons_list)) if reasons_list else ""
                # Danh dau khung gio dai han cho Spot
                spot_tag = " [SPOT]" if tf in ("4h", "1d") else ""
                msg += f"  {tf_icon} <b>{tf_label}{spot_tag}:</b> {d}{rsi_str}\n"
                if reasons_str:
                    msg += f"      \U0001f4a1 {reasons_str}\n"
        msg += "\n"

        # Tin tuc
        if analyzed_news:
            mood_map = {"BULLISH": "\U0001f7e2 TICH CUC", "BEARISH": "\U0001f534 TIEU CUC", "NEUTRAL": "\u26aa TRUNG LAP"}
            msg += f"\U0001f4f0 <b>TIN TUC:</b> {mood_map.get(market_mood['mood'], 'TRUNG LAP')}\n"
            for n in analyzed_news[:3]:
                s = n.get("sentiment", "neutral")
                s_icon = {"bullish": "\U0001f7e2", "bearish": "\U0001f534", "neutral": "\u26aa"}
                title = html.escape(n["title"][:65])
                msg += f"  {s_icon.get(s, '\u26aa')} {title}\n"
            msg += "\n"

        msg += "\u2501" * 18 + "\n"
        msg += "\u26a0\ufe0f <i>NFA - Khong phai loi khuyen dau tu.</i>"

        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

        # === MESSAGE 2: TIN HIEU SPOT (chi khi MUA/LONG) ===
        if entry_spot > 0:
            rr_spot = abs(tp2_spot - entry_spot) / abs(entry_spot - sl_spot) if abs(entry_spot - sl_spot) > 0 else 0
            spot_msg = f"\U0001f7e2 <b>TIN HIEU MUA - SPOT (Dai han)</b> \U0001f7e2\n"
            spot_msg += "\u2501" * 18 + "\n"
            spot_msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
            spot_msg += f"\U0001f4cd <b>Entry:</b> ${entry_spot:,.2f}\n"
            spot_msg += f"\U0001f6d1 <b>Stop Loss:</b> ${sl_spot:,.2f} (-5%)\n"
            spot_msg += f"\U0001f3af <b>TP1:</b> ${tp1_spot:,.2f} (+5%)\n"
            spot_msg += f"\U0001f3af <b>TP2:</b> ${tp2_spot:,.2f} (+10%)\n"
            spot_msg += f"\U0001f3af <b>TP3:</b> ${tp3_spot:,.2f} (+20%)\n"
            spot_msg += f"\U0001f4ca <b>R:R Ratio:</b> 1:{rr_spot:.1f}\n"
            spot_reasons_str = html.escape(" + ".join(spot_reasons[:3])) if spot_reasons else ""
            if spot_reasons_str:
                spot_msg += f"\U0001f4a1 <b>Ly do:</b> {spot_reasons_str}\n"
            spot_msg += f"\U0001f4c5 <b>Khung:</b> 4H + 1D (xu huong dai han)\n"
            spot_msg += "\u2501" * 18
            await update.message.reply_text(spot_msg, parse_mode="HTML")
        elif spot_direction == "CHUA NEN MUA":
            wait_msg = f"\u26aa <b>SPOT: CHUA NEN MUA {token}</b>\n"
            wait_msg += "\u2501" * 18 + "\n"
            wait_msg += "Xu huong dai han (4H/1D) chua du dieu kien.\n"
            wait_msg += "Nen cho them tin hieu tich cuc tu khung lon.\n"
            wait_msg += "\u2501" * 18
            await update.message.reply_text(wait_msg, parse_mode="HTML")

        # === MESSAGE 3: TIN HIEU FUTURES (LONG hoac SHORT) ===
        if entry_futures > 0:
            rr_fut = abs(tp2_futures - entry_futures) / abs(entry_futures - sl_futures) if abs(entry_futures - sl_futures) > 0 else 0
            fut_emoji_msg = "\U0001f7e2" if fut_direction == "LONG" else "\U0001f534"
            fut_msg = f"{fut_emoji_msg} <b>TIN HIEU {fut_direction} - FUTURES (5-10x)</b> {fut_emoji_msg}\n"
            fut_msg += "\u2501" * 18 + "\n"
            fut_msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
            fut_msg += f"\U0001f4cd <b>Entry:</b> ${entry_futures:,.2f}\n"
            fut_msg += f"\U0001f6d1 <b>Stop Loss:</b> ${sl_futures:,.2f}\n"
            fut_msg += f"\U0001f3af <b>TP1:</b> ${tp1_futures:,.2f}\n"
            fut_msg += f"\U0001f3af <b>TP2:</b> ${tp2_futures:,.2f}\n"
            fut_msg += f"\U0001f3af <b>TP3:</b> ${tp3_futures:,.2f}\n"
            fut_msg += f"\U0001f4ca <b>R:R Ratio:</b> 1:{rr_fut:.1f}\n"
            fut_msg += f"\u26a0\ufe0f <b>Leverage:</b> 5-10x (Rui ro cao)\n"
            fut_msg += "\u2501" * 18
            await update.message.reply_text(fut_msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Loi phan tich {token}: {e}")
        await update.message.reply_text(f"Co loi khi phan tich {token}: {str(e)[:100]}")
    finally:
        await analyzer.close()
        await crawler.close()


# ============================================
#  COMMAND HANDLERS
# ============================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /start - Chao mung."""
    msg = (
        "<b>CRYPTO BOT SYSTEM</b>\n"
        "=" * 30 + "\n\n"
        "Chao ban! Toi la bot phan tich crypto.\n\n"
        "<b>PHAN TICH:</b>\n"
        "  Go ten token (VD: <code>BTC</code>) -> Bao cao tong hop\n"
        "  <code>/spot BTC</code> -> Tin hieu MUA (dai han)\n"
        "  <code>/futures ETH</code> -> Tin hieu Long/Short\n\n"
        "<b>THEO DOI:</b>\n"
        "  /signals - Xem tin hieu dang theo doi\n\n"
        "<b>TIN TUC:</b>\n"
        "  /scan - Quet nhanh BTC, ETH, SOL\n"
        "  /news - Tin tuc nong nhat\n\n"
        "<b>AIRDROP:</b>\n"
        "  /wallet - Tao vi | /wallets - Xem vi\n"
        "  /balance - So du | /networks - Mang\n"
        "  /farm - Farming | /claim - Claim\n"
        "  /menu - Hien thi menu\n"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /menu - Hien thi menu."""
    await cmd_start(update, context)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /scan - Quet nhanh top coins."""
    await update.message.reply_text("Dang quet BTC, ETH, SOL... cho 15-20 giay")

    analyzer = TechnicalAnalyzer()
    ws = BinanceWebSocket()

    try:
        coins = [("BTC", "btcusdt"), ("ETH", "ethusdt"), ("SOL", "solusdt")]
        lines = ["<b>QUET NHANH TOP COINS (H1)</b>", "=" * 30, ""]

        for name, raw in coins:
            # Gia real-time
            pdata = await ws.get_price_once(raw)
            price = pdata["price"] if pdata else 0
            change = pdata.get("change_pct", 0) if pdata else 0

            # TA
            signal = await analyzer.analyze(f"{name}/USDT", "1h")
            direction = signal.get("direction", "N/A") if signal else "N/A"
            rsi = signal.get("rsi") if signal else None

            if direction == "LONG":
                icon = "LONG"
            elif direction == "SHORT":
                icon = "SHORT"
            else:
                icon = "---"

            rsi_str = f"RSI:{rsi:.0f}" if rsi is not None else ""
            lines.append(f"<b>{name}:</b> <code>${price:,.2f}</code> ({change:+.2f}%)")
            lines.append(f"  {icon} {rsi_str}")

            reasons = signal.get("reasons", [])[:2] if signal else []
            if reasons:
                lines.append(f"  {html.escape(', '.join(reasons))}")
            lines.append("")

        lines.append("<i>Go ten token de xem chi tiet (VD: BTC)</i>")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        await analyzer.close()


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /news - Tin tuc nong."""
    await update.message.reply_text("Dang cao tin tuc...")

    crawler = NewsCrawler()
    sentiment_analyzer = SentimentAnalyzer()

    try:
        news = await crawler.fetch_cryptopanic("hot", limit=8)
        if not news:
            news = await crawler.fetch_rss(limit_per_source=3)

        analyzed = sentiment_analyzer.analyze_news_batch(news)
        mood = sentiment_analyzer.get_market_mood(analyzed)

        mood_label = {"BULLISH": "TICH CUC", "BEARISH": "TIEU CUC", "NEUTRAL": "TRUNG LAP"}
        lines = [
            "<b>TIN TUC CRYPTO MOI NHAT</b>",
            f"Tam ly thi truong: <b>{mood_label.get(mood['mood'], 'TRUNG LAP')}</b> (Score: {mood['avg_score']:+.1f})",
            "=" * 30,
            "",
        ]

        for n in analyzed[:8]:
            s = n.get("sentiment", "neutral")
            s_icon = {"bullish": "[+]", "bearish": "[-]", "neutral": "[o]"}
            title = html.escape(n["title"][:75])
            source = html.escape(n.get("source", ""))
            url = n.get("url", "")

            if url:
                lines.append(f"{s_icon.get(s, '[o]')} <a href='{url}'>{title}</a>")
            else:
                lines.append(f"{s_icon.get(s, '[o]')} {title}")
            if source:
                lines.append(f"    <i>- {source}</i>")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    finally:
        await crawler.close()


# ============================================
#  AIRDROP COMMANDS
# ============================================

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /wallet - Tao vi moi."""
    wm = WalletManager()

    # Kiem tra tham so: /wallet 5 -> tao 5 vi
    count = 1
    if context.args:
        try:
            count = min(int(context.args[0]), 20)  # Toi da 20 vi/lan
        except ValueError:
            pass

    if count == 1:
        wallet = wm.create_wallet()
        msg = f"\U0001f7e2 <b>DA TAO VI MOI</b>\n"
        msg += "\u2501" * 18 + "\n"
        msg += f"\U0001f4cb <b>ID:</b> #{wallet['id']}\n"
        msg += f"\U0001f4cb <b>Label:</b> {wallet['label']}\n"
        msg += f"\U0001f4cd <b>Address:</b>\n<code>{wallet['address']}</code>\n"
        msg += "\u2501" * 18 + "\n"
        msg += "\u26a0\ufe0f Private Key da duoc ma hoa va luu an toan."
    else:
        wallets = wm.create_batch(count)
        msg = f"\U0001f7e2 <b>DA TAO {count} VI MOI</b>\n"
        msg += "\u2501" * 18 + "\n"
        for w in wallets:
            msg += f"#{w['id']} | <code>{w['address'][:10]}...{w['address'][-6:]}</code>\n"
        msg += "\u2501" * 18 + "\n"
        msg += f"Tong vi: {len(wm.wallets)} | Go /wallets de xem tat ca"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /wallets - Xem danh sach vi."""
    wm = WalletManager()
    wallets = wm.list_wallets()

    if not wallets:
        await update.message.reply_text("Chua co vi nao. Go /wallet de tao vi moi.")
        return

    summary = wm.get_summary()
    msg = f"\U0001f4bc <b>DANH SACH VI ({summary['total_wallets']} vi)</b>\n"
    msg += "\u2501" * 18 + "\n"
    for w in wallets:
        active_mark = "\U0001f7e2" if w['tx_count'] > 0 else "\u26aa"
        nets = ", ".join(w.get('networks', [])) if w.get('networks') else "-"
        msg += f"{active_mark} #{w['id']} <b>{w['label']}</b>\n"
        msg += f"   <code>{w['address'][:12]}...{w['address'][-6:]}</code>\n"
        msg += f"   TX: {w['tx_count']} | Mang: {nets}\n"
    msg += "\u2501" * 18 + "\n"
    msg += f"Active: {summary['active_wallets']} | Tong TX: {summary['total_transactions']}"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /balance [network] - Kiem tra so du."""
    wm = WalletManager()
    if not wm.wallets:
        await update.message.reply_text("Chua co vi nao. Go /wallet de tao vi moi.")
        return

    network = "ethereum"
    if context.args:
        net_input = context.args[0].lower()
        if net_input in NETWORKS:
            network = net_input

    net_info = NETWORKS[network]
    await update.message.reply_text(f"Dang kiem tra so du tren {net_info['name']}...")

    bot = OnChainBot(wm)
    results = await bot.check_all_balances(network)

    msg = f"\U0001f4b0 <b>SO DU - {net_info['name']}</b>\n"
    msg += "\u2501" * 18 + "\n"
    total = 0
    for r in results:
        if "error" in r:
            msg += f"\U0001f534 #{r.get('wallet_id', '?')}: Loi\n"
        else:
            bal = r['balance']
            total += bal
            bal_str = f"{bal:.6f}" if bal > 0 else "0"
            emoji = "\U0001f7e2" if bal > 0 else "\u26aa"
            msg += f"{emoji} #{r['wallet_id']}: <code>{bal_str} {r['symbol']}</code>\n"

    msg += "\u2501" * 18 + "\n"
    msg += f"\U0001f4ca Tong: <b>{total:.6f} {net_info['symbol']}</b>"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_networks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /networks - Hien thi mang ho tro."""
    msg = "\U0001f310 <b>MANG HO TRO</b>\n"
    msg += "\u2501" * 18 + "\n"
    for key, net in NETWORKS.items():
        msg += f"  \U0001f7e2 <b>{net['name']}</b> ({net['symbol']})\n"
        msg += f"    Lenh: /balance {key}\n"
    msg += "\u2501" * 18 + "\n"
    msg += "VD: <code>/balance arbitrum</code>"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /farm [network] - Farming airdrop (swap tao volume)."""
    wm = WalletManager()
    if not wm.wallets:
        await update.message.reply_text("Chua co vi. Go /wallet de tao vi truoc.")
        return

    network = "arbitrum"
    if context.args:
        net = context.args[0].lower()
        if net in NETWORKS:
            network = net

    wallet_ids = [w["id"] for w in wm.wallets]
    await update.message.reply_text(
        f"\U0001f3af Bat dau farming tren {NETWORKS[network]['name']}...\n"
        f"So vi: {len(wallet_ids)} | Swap ETH -> USDC\n"
        f"Random delay 10-60s giua cac giao dich."
    )

    farmer = AirdropFarmer(wm)
    results = await farmer.farm_batch(wallet_ids, amount_eth=0.0005, network=network)

    msg = f"\U0001f4ca <b>KET QUA FARMING</b>\n"
    msg += "\u2501" * 18 + "\n"
    msg += f"\U0001f7e2 Thanh cong: {results['success']}\n"
    msg += f"\U0001f534 That bai: {results['failed']}\n"
    msg += f"Tong TX: {results['total_tx']}\n"
    msg += "\u2501" * 18
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /claim [contract] [network] - Claim airdrop."""
    if not context.args:
        msg = "\U0001f4cb <b>CACH DUNG /claim</b>\n"
        msg += "\u2501" * 18 + "\n"
        msg += "<code>/claim 0x... ethereum</code>\n\n"
        msg += "Trong do:\n"
        msg += "  - Tham so 1: Dia chi contract claim\n"
        msg += "  - Tham so 2: Mang (ethereum, arbitrum...)\n\n"
        msg += "Bot se tu dong claim cho TAT CA vi cua ban.\n"
        msg += "Go /networks de xem mang ho tro."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    contract = context.args[0]
    network = context.args[1] if len(context.args) > 1 else "ethereum"

    if network not in NETWORKS:
        await update.message.reply_text(f"Mang '{network}' khong ho tro. Go /networks")
        return

    wm = WalletManager()
    if not wm.wallets:
        await update.message.reply_text("Chua co vi. Go /wallet de tao vi truoc.")
        return

    wallet_ids = [w["id"] for w in wm.wallets]
    await update.message.reply_text(
        f"\U0001f3af Dang claim cho {len(wallet_ids)} vi...\n"
        f"Contract: <code>{contract[:10]}...{contract[-6:]}</code>\n"
        f"Mang: {NETWORKS[network]['name']}",
        parse_mode="HTML",
    )

    farmer = AirdropFarmer(wm)
    results = await farmer.claim_batch(wallet_ids, contract, network)

    msg = f"\U0001f4ca <b>KET QUA CLAIM</b>\n"
    msg += "\u2501" * 18 + "\n"
    msg += f"\U0001f7e2 Thanh cong: {results['success']}\n"
    msg += f"\U0001f534 That bai: {results['failed']}\n"
    msg += "\u2501" * 18
    await update.message.reply_text(msg, parse_mode="HTML")


# ============================================
#  SIGNAL COMMANDS: /spot, /futures, /signals
# ============================================

async def _analyze_and_signal(update, token: str, signal_type: str):
    """Ham chung: phan tich va gui tin hieu Spot hoac Futures."""
    symbol = f"{token}/USDT"
    symbol_raw = f"{token}USDT"

    await update.message.reply_text(f"Dang phan tich {token} ({signal_type})... cho 5-10 giay")

    analyzer = TechnicalAnalyzer()
    ws = BinanceWebSocket()
    chat_id = update.effective_chat.id

    try:
        # Lay gia
        price_data = await ws.get_price_once(symbol_raw.lower())
        price = price_data["price"] if price_data else 0

        if price == 0:
            await update.message.reply_text(f"Khong lay duoc gia {token}.")
            return

        change = price_data.get("change_pct", 0) if price_data else 0

        if signal_type == "SPOT":
            # SPOT: Chi dung 4h va 1d
            timeframes = {"4h": "4 gio", "1d": "1 ngay"}
        else:
            # FUTURES: Dung tat ca
            timeframes = {"15m": "15 phut", "1h": "1 gio", "4h": "4 gio", "1d": "1 ngay"}

        signals = {}
        for tf, _ in timeframes.items():
            try:
                sig = await analyzer.analyze(symbol, tf)
                if sig:
                    signals[tf] = sig
            except Exception:
                pass

        # Tinh diem
        bull = sum(s.get("bull_score", 0) for s in signals.values())
        bear = sum(s.get("bear_score", 0) for s in signals.values())

        if signal_type == "SPOT":
            # Spot chi co MUA
            if bull >= 3:
                direction = "MUA"
                confidence = min(95, 50 + bull * 5)
                entry = price
            else:
                # Khong du dieu kien MUA
                msg = f"\u26aa <b>SPOT: CHUA NEN MUA {token}</b>\n"
                msg += "\u2501" * 18 + "\n"
                msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT | ${price:,.2f}\n"
                msg += f"Bull: {bull} | Bear: {bear}\n"
                msg += "Xu huong 4H/1D chua du tich cuc.\n"
                msg += "Cho them tin hieu tu khung lon.\n"
                msg += "\u2501" * 18
                await update.message.reply_text(msg, parse_mode="HTML")
                return
        else:
            # Futures: Long hoac Short
            if bull > bear and bull >= 4:
                direction = "LONG"
                confidence = min(95, 50 + (bull - bear) * 5)
                entry = price
            elif bear > bull and bear >= 4:
                direction = "SHORT"
                confidence = min(95, 50 + (bear - bull) * 5)
                entry = price
            else:
                msg = f"\u26aa <b>FUTURES: CHUA CO TIN HIEU {token}</b>\n"
                msg += "\u2501" * 18 + "\n"
                msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT | ${price:,.2f}\n"
                msg += f"Bull: {bull} | Bear: {bear}\n"
                msg += "Chua du dieu kien vao lenh.\n"
                msg += "\u2501" * 18
                await update.message.reply_text(msg, parse_mode="HTML")
                return

        # === 1. MACRO EVENT RISK FILTER ===
        from analytics.macro_calendar import MacroCalendar
        macro = MacroCalendar()
        macro_risk = "NORMAL"
        macro_risk_data = {}
        try:
            macro_risk_data = await macro.assess_risk()
            macro_risk = macro_risk_data.get("risk_level", "NORMAL")
        except Exception as e:
            logger.warning(f"Macro check failed: {e}")
        finally:
            await macro.close()

        is_blocked_by_macro = False
        blocked_reason = ""
        if macro_risk == "CRITICAL" and macro_risk_data.get("warnings"):
            for w in macro_risk_data["warnings"]:
                ev = w.get("event", {})
                hours = ev.get("hours_until", 999)
                if 0 <= hours <= 4:
                    is_blocked_by_macro = True
                    blocked_reason = f"Su kien cuc ky quan trong ({ev.get('title')}) sap dien ra trong {hours:.1f} gio."
                    break

        if is_blocked_by_macro:
            msg = f"\u26a0\ufe0f <b>GIAO DICH BI CHAN: RUI RO VI MO LON</b>\n"
            msg += "\u2501" * 18 + "\n"
            msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
            msg += f"\u26a0\ufe0f <b>Ly do:</b> {blocked_reason}\n"
            msg += "Hay kien nhan doi su kien ket thuc de dam bao an toan von."
            await update.message.reply_text(msg, parse_mode="HTML")
            return

        # === 2. NEWS SENTIMENT FILTER ===
        sentiment_analyzer = SentimentAnalyzer()
        crawler = NewsCrawler()
        news_sentiment = 0
        market_mood_lbl = "TRUNG LAP"
        try:
            news = await crawler.fetch_by_coin(token, limit=8)
            if not news:
                news = await crawler.fetch_cryptopanic("hot", limit=5)
            analyzed_news = sentiment_analyzer.analyze_news_batch(news) if news else []
            market_mood = sentiment_analyzer.get_market_mood(analyzed_news)
            news_sentiment = market_mood.get("avg_score", 0)
            market_mood_lbl = market_mood.get("mood", "NEUTRAL")
        except Exception as e:
            logger.warning(f"Sentiment check failed: {e}")
        finally:
            await crawler.close()

        if direction in ("LONG", "MUA") and market_mood_lbl == "BEARISH":
            msg = f"\u26a0\ufe0f <b>BO QUA TIN HIEU LONG: XUNG DOT TIN TUC</b>\n"
            msg += "\u2501" * 18 + "\n"
            msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
            msg += f"\u26a0\ufe0f <b>Ly do:</b> Tin hieu ky thuat LONG nhung tin tuc dang tieu cuc (BEARISH).\n"
            msg += f"Diem tin tuc: {news_sentiment:+.1f}\n"
            await update.message.reply_text(msg, parse_mode="HTML")
            return

        if direction == "SHORT" and market_mood_lbl == "BULLISH":
            msg = f"\u26a0\ufe0f <b>BO QUA TIN HIEU SHORT: XUNG DOT TIN TUC</b>\n"
            msg += "\u2501" * 18 + "\n"
            msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
            msg += f"\u26a0\ufe0f <b>Ly do:</b> Tin hieu ky thuat SHORT nhung tin tuc dang tich cuc (BULLISH).\n"
            msg += f"Diem tin tuc: {news_sentiment:+.1f}\n"
            await update.message.reply_text(msg, parse_mode="HTML")
            return

        # === 3. SMART SL/TP LEVELS (ATR + S/R + Fibonacci) ===
        smart_levels = None
        leverage = 10 if signal_type == "FUTURES" else 1
        try:
            df = await analyzer.get_ohlcv(symbol, "1h", limit=100)
            if not df.empty and len(df) >= 20:
                df = analyzer.calculate_indicators(df)
                smart_levels = analyzer.compute_smart_levels(
                    df, direction="LONG" if direction in ("LONG", "MUA") else "SHORT",
                    leverage=leverage, macro_risk=macro_risk
                )
        except Exception as e:
            logger.warning(f"Smart levels calculation failed: {e}")

        if smart_levels and not smart_levels.get("error"):
            sl = smart_levels["sl"]
            tp1 = smart_levels["tp1"]
            tp2 = smart_levels["tp2"]
            tp3 = smart_levels["tp3"]
            sl_method = smart_levels.get("sl_method_detail", smart_levels.get("method", "ATR+S/R"))
        else:
            sl_method = "Fixed % (Fallback)"
            if signal_type == "SPOT":
                sl = round(price * 0.95, 2)
                tp1 = round(price * 1.05, 2)
                tp2 = round(price * 1.10, 2)
                tp3 = round(price * 1.20, 2)
            else:
                if direction == "LONG":
                    sl = round(price * 0.985, 2)
                    tp1 = round(price * 1.02, 2)
                    tp2 = round(price * 1.04, 2)
                    tp3 = round(price * 1.07, 2)
                else:
                    sl = round(price * 1.015, 2)
                    tp1 = round(price * 0.98, 2)
                    tp2 = round(price * 0.96, 2)
                    tp3 = round(price * 0.93, 2)

        # Tinh R:R
        rr = abs(tp2 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

        # Gui tin hieu
        if signal_type == "SPOT":
            emoji = "\U0001f7e2"
            dir_text = "MUA"
        else:
            emoji = "\U0001f7e2" if direction == "LONG" else "\U0001f534"
            dir_text = direction

        # Chi bao chi tiet
        reasons = []
        for tf, tf_label in timeframes.items():
            sig = signals.get(tf)
            if sig:
                d = sig["direction"]
                rsi = sig.get("rsi")
                icon = "\U0001f7e2" if d == "LONG" else ("\U0001f534" if d == "SHORT" else "\u26aa")
                rsi_str = f" RSI:{rsi:.0f}" if rsi is not None else ""
                reasons_list = sig.get("reasons", [])[:2]
                r_str = html.escape(", ".join(reasons_list)) if reasons_list else ""
                reasons.append(f"  {icon} <b>{tf_label}:</b> {d}{rsi_str}")
                if r_str:
                    reasons.append(f"      \U0001f4a1 {r_str}")

        msg = f"{emoji} <b>TIN HIEU {dir_text} - {signal_type}</b> {emoji}\n"
        msg += "\u2501" * 18 + "\n"
        msg += f"\U0001fa99 <b>Coin:</b> {token}/USDT\n"
        msg += f"\U0001f4cd <b>Entry:</b> ${entry:,.2f}\n"
        msg += f"\U0001f6d1 <b>Stop Loss:</b> ${sl:,.2f} ({sl_method})\n"
        msg += f"\U0001f3af <b>TP1:</b> ${tp1:,.2f}\n"
        msg += f"\U0001f3af <b>TP2:</b> ${tp2:,.2f}\n"
        msg += f"\U0001f3af <b>TP3:</b> ${tp3:,.2f}\n"
        msg += f"\U0001f4ca <b>R:R Ratio:</b> 1:{rr:.1f}\n"
        msg += f"\U0001f4ca <b>Do tin cay:</b> {confidence}%\n"
        msg += f"\U0001f4f0 <b>Tam ly news:</b> {market_mood_lbl} ({news_sentiment:+.1f})\n"
        if signal_type == "FUTURES":
            msg += f"\u26a0\ufe0f <b>Leverage:</b> {leverage}x\n"
        msg += "\u2501" * 18 + "\n\n"
        msg += "\U0001f50d <b>CHI BAO:</b>\n"
        msg += "\n".join(reasons) + "\n\n"
        msg += "\u2501" * 18 + "\n"
        msg += "\U0001f514 <i>Bot se tu dong thong bao khi cham TP1/TP2/TP3/SL!</i>"

        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

        # DANG KY THEO DOI TU DONG
        signal_key = f"{token}_{signal_type}"
        signal_tracker.add_signal({
            "key": signal_key,
            "coin": token,
            "type": signal_type,
            "direction": direction if signal_type == "FUTURES" else "LONG",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "chat_id": chat_id,
            "leverage": leverage,
        })

        await update.message.reply_text(
            f"\U0001f514 Da bat dau theo doi {token} {signal_type}.\n"
            f"Bot se gui thong bao khi cham TP1/TP2/TP3 hoac SL.\n"
            f"Go /signals de xem tat ca tin hieu dang theo doi."
        )

    finally:
        await analyzer.close()


async def cmd_spot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /spot BTC - Tin hieu Spot (chi MUA, dai han)."""
    if not context.args:
        await update.message.reply_text("Nhap ten token. VD: <code>/spot BTC</code>", parse_mode="HTML")
        return
    token = context.args[0].strip().upper()
    await _analyze_and_signal(update, token, "SPOT")


async def cmd_futures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /futures ETH - Tin hieu Futures (Long/Short)."""
    if not context.args:
        await update.message.reply_text("Nhap ten token. VD: <code>/futures ETH</code>", parse_mode="HTML")
        return
    token = context.args[0].strip().upper()
    await _analyze_and_signal(update, token, "FUTURES")


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /signals - Xem cac tin hieu dang theo doi."""
    active = signal_tracker.list_active()

    if not active:
        await update.message.reply_text(
            "\u26aa Khong co tin hieu nao dang theo doi.\n"
            "Go <code>/spot BTC</code> hoac <code>/futures ETH</code> de tao tin hieu.",
            parse_mode="HTML",
        )
        return

    msg = f"\U0001f514 <b>TIN HIEU DANG THEO DOI ({len(active)})</b>\n"
    msg += "\u2501" * 18 + "\n"
    for s in active:
        d_emoji = "\U0001f7e2" if s["direction"] in ("LONG", "MUA") else "\U0001f534"
        msg += f"\n{d_emoji} <b>{s['coin']}/USDT - {s['type']}</b>\n"
        msg += f"  {s['direction']} | Entry: ${s['entry']:,.2f}\n"
        msg += f"  SL: ${s['sl']:,.2f} | TP1: ${s['tp1']:,.2f}\n"
        msg += f"  TP2: ${s['tp2']:,.2f} | TP3: ${s['tp3']:,.2f}\n"
        msg += f"  Trang thai: {s['status']}\n"

    msg += "\n" + "\u2501" * 18
    await update.message.reply_text(msg, parse_mode="HTML")


# ============================================
#  DEX GEM COMMANDS: /gem, /check, /scan_dex
# ============================================

async def cmd_gem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /gem [chain] - Tim kem tiem nang x100 tren DEX."""
    chain = "solana"
    if context.args:
        chain = context.args[0].lower()

    await update.message.reply_text(
        f"\U0001f48e Dang quet token moi tren {chain.upper()}...\n"
        f"Tim kiem gem tiem nang x100. Cho 10-20 giay."
    )

    scanner = DexGemScanner()
    try:
        gems = await scanner.scan_for_gems(chain)

        if not gems:
            await update.message.reply_text(f"Khong tim thay gem moi tren {chain}. Thu chain khac: solana, ethereum, bsc, arbitrum, base")
            return

        # Gui top 5 gems
        msg = f"\U0001f48e <b>TOP GEM - {chain.upper()}</b> \U0001f48e\n"
        msg += "\u2501" * 18 + "\n"

        for i, g in enumerate(gems[:5], 1):
            gem = g["gem"]
            safety = g["safety"]
            pair = g["pair"]

            # Tier emoji
            if gem["tier"] == "S-TIER GEM":
                tier_emoji = "\U0001f451"  # crown
            elif gem["tier"] == "A-TIER":
                tier_emoji = "\U0001f7e2"
            elif gem["tier"] == "B-TIER":
                tier_emoji = "\U0001f7e1"  # yellow
            else:
                tier_emoji = "\u26aa"

            change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            pair_url = pair.get("url", "")

            # Token name la link den DexScreener
            name_escaped = html.escape(g['name'][:25])
            sym_escaped = html.escape(g['symbol'])
            if pair_url:
                msg += f"\n{tier_emoji} <b>#{i} <a href='{pair_url}'>{sym_escaped}</a></b> ({name_escaped})\n"
            else:
                msg += f"\n{tier_emoji} <b>#{i} {sym_escaped}</b> ({name_escaped})\n"

            msg += f"  \U0001f4b0 ${g['price']:.6f}" if g['price'] < 1 else f"  \U0001f4b0 ${g['price']:,.4f}"
            msg += f" ({change_24h:+.0f}% 24h)\n"
            msg += f"  \U0001f48e GEM: <b>{gem['gem_score']}/100</b> ({gem['tier']})\n"
            msg += f"  \U0001f6e1 Safe: {safety['score']}/100 ({safety['safety']})\n"
            msg += f"  \U0001f4ca FDV: ${gem['fdv']:,.0f} | Liq: ${liq:,.0f}\n"
            # Contract address
            token_addr = pair.get("baseToken", {}).get("address", "")
            if token_addr:
                msg += f"  \U0001f4cb CA: <code>{token_addr}</code>\n"

        msg += "\n" + "\u2501" * 18 + "\n"
        msg += "\U0001f50d <code>/check [ten]</code> phan tich sau\n"
        msg += "\U0001f6d2 <code>/buy [CA] [so tien]</code> mua truc tiep"

        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    finally:
        await scanner.close()


async def cmd_newtoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lenh /newtoken [chain]
    Tim token moi list trong 1 gio tro lai co Score cao nhat.
    """
    chain = context.args[0].lower() if context.args else "solana"
    
    await update.message.reply_text(
        f"\U0001f575\ufe0f Dang quet cac token MOI LIST (< 1 gio) tren {chain.upper()}...\n"
        "Viec nay co the mat 10-15s."
    )

    scanner = DexGemScanner()
    try:
        results = await scanner.scan_new_listings(chain=chain, max_age_hours=1.0)
        
        if not results:
            await update.message.reply_text(f"\U0001f6ab Khong co token nao moi list & tieu chuan trong 1h qua tren {chain}.")
            return

        msg = f"\U0001f6a8 <b>NEW LISTINGS (<1 GIO) - {chain.upper()}</b>\n"
        msg += "\u2501" * 18 + "\n"
        
        for i, r in enumerate(results[:10], 1):
            gem = r["gem"]
            safe = r["safety"]
            
            # Icon phan loai
            if gem["gem_score"] >= 70: icon = "\U0001f525"
            elif gem["gem_score"] >= 40: icon = "\u2b50"
            else: icon = "\U0001f7e1"
            
            msg += f"{icon} <b>#{i} <a href='{r['url']}'>{r['name']}</a></b> ({r['symbol']})\n"
            msg += f"  \u23f1 Tuoi: {r['age_mins']:.0f} phut\n"
            msg += f"  \U0001f4b0 Gia: ${r['price']:.6f}\n"
            msg += f"  \U0001f4a0 GEM Score: <b>{gem['gem_score']}/100</b>\n"
            msg += f"  \U0001f6e1 Safety: {safe['safety']}\n"
            msg += f"  \U0001f4cb CA: <code>{r['address']}</code>\n\n"
            
        msg += "\u2501" * 18 + "\n"
        msg += "Go <code>/buy [CA] [amount]</code> de MUA NGAY."
        
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Loi /newtoken: {e}")
        await update.message.reply_text("\U0001f534 Co loi truoc luc quet token moi.")
    finally:
        await scanner.close()


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /check [token] - Phan tich sau 1 token DEX."""
    if not context.args:
        msg = "\U0001f50d <b>CACH DUNG /check</b>\n"
        msg += "\u2501" * 18 + "\n"
        msg += "<code>/check PEPE</code> - Tim theo ten\n"
        msg += "<code>/check 0x6982...abc</code> - Tim theo dia chi\n"
        msg += "\nBot se phan tich: safety, gem score, FDV, volume...\n"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"\U0001f50d Dang phan tich {html.escape(query)}...", parse_mode="HTML")

    scanner = DexGemScanner()
    try:
        result = await scanner.analyze_token_deep(query)

        if not result:
            await update.message.reply_text(f"Khong tim thay token '{html.escape(query)}' tren DEX.", parse_mode="HTML")
            return

        safety = result["safety"]
        gem = result["gem"]

        # Safety emoji
        if safety["score"] >= 70:
            safe_emoji = "\U0001f7e2"
        elif safety["score"] >= 50:
            safe_emoji = "\U0001f7e1"
        else:
            safe_emoji = "\U0001f534"

        # Gem tier emoji
        if gem["tier"] == "S-TIER GEM":
            gem_emoji = "\U0001f451\U0001f48e"
        elif gem["tier"] == "A-TIER":
            gem_emoji = "\U0001f48e"
        else:
            gem_emoji = "\u2b50"

        msg = f"{gem_emoji} <b>PHAN TICH: "
        if result.get('pair_url'):
            msg += f"<a href='{result['pair_url']}'>{html.escape(result['symbol'])}</a>"
        else:
            msg += html.escape(result['symbol'])
        msg += "</b>\n"
        msg += f"<i>{html.escape(result['name'])}</i>\n"
        msg += "\u2501" * 18 + "\n"

        # Gia va bien dong
        p = result['price']
        price_str = f"${p:.8f}" if p < 0.001 else (f"${p:.4f}" if p < 1 else f"${p:,.2f}")
        msg += f"\U0001f4b0 <b>Gia:</b> {price_str}\n"
        pc = result["price_change"]
        msg += f"\U0001f4c8 <b>Bien dong:</b> 5m: {pc.get('5m', 0) or 0:+.1f}% | 1h: {pc.get('1h', 0) or 0:+.1f}% | 24h: {pc.get('24h', 0) or 0:+.1f}%\n"

        # On-chain metrics
        msg += "\n\U0001f4ca <b>ON-CHAIN</b>\n"
        liq = result.get('liquidity', 0) or 0
        vol = result.get('volume_24h', 0) or 0
        fdv = result.get('fdv', 0) or 0
        mc = result.get('market_cap', 0) or 0
        msg += f"  Liquidity: ${liq:,.0f}\n"
        msg += f"  Volume 24h: ${vol:,.0f}\n"
        msg += f"  FDV: ${fdv:,.0f}\n"
        if mc:
            msg += f"  Market Cap: ${mc:,.0f}\n"

        # Transactions
        txns = result.get('txns_24h', {})
        buys = txns.get('buys', 0) or 0
        sells = txns.get('sells', 0) or 0
        msg += f"  Buy/Sell 24h: {buys}/{sells}\n"

        # Safety
        msg += f"\n{safe_emoji} <b>AN TOAN: {safety['score']}/100 ({safety['safety']})</b>\n"
        for w in safety['warnings'][:3]:
            msg += f"  \U0001f534 {html.escape(w)}\n"
        for p_item in safety['positives'][:3]:
            msg += f"  \U0001f7e2 {html.escape(p_item)}\n"

        # Gem Score
        msg += f"\n{gem_emoji} <b>GEM SCORE: {gem['gem_score']}/100 ({gem['tier']})</b>\n"
        for r in gem['reasons'][:4]:
            msg += f"  \U0001f48e {html.escape(r)}\n"

        msg += "\n" + "\u2501" * 18 + "\n"
        msg += f"\U0001f517 Chain: {result['chain']} | DEX: {result.get('dex', '')}\n"
        # Contract address
        if result.get('address'):
            msg += f"\U0001f4cb <b>Contract:</b>\n<code>{result['address']}</code>\n"
        if result.get('pair_url'):
            msg += f"\U0001f310 <a href='{result['pair_url']}'>Xem tren DexScreener</a>\n"
        msg += "\n\U0001f6d2 Mua: <code>/buy {addr} 0.001</code>\n".format(addr=result.get('address', '0x...'))
        msg += "\u26a0\ufe0f <i>DYOR - Luon nghien cuu ky truoc khi dau tu.</i>"

        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    finally:
        await scanner.close()


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lenh /buy [contract] [so_tien] [chain] [wallet_id]
    Mua token truc tiep tren DEX bang vi cua ban.
    VD: /buy 0x6982...abc 0.001 arbitrum 1
    """
    if not context.args or len(context.args) < 2:
        msg = "\U0001f6d2 <b>CACH DUNG /buy</b>\n"
        msg += "\u2501" * 18 + "\n"
        msg += "<code>/buy [CA] [so_ETH]</code>\n"
        msg += "<code>/buy [CA] [so_ETH] [chain]</code>\n"
        msg += "<code>/buy [CA] [so_ETH] [chain] [wallet_id]</code>\n\n"
        msg += "<b>Vi du:</b>\n"
        msg += "<code>/buy 0x6982...abc 0.001</code>\n"
        msg += "<code>/buy 0x6982...abc 0.002 base</code>\n"
        msg += "<code>/buy 0x6982...abc 0.001 arbitrum 2</code>\n\n"
        msg += "Mac dinh: chain=arbitrum, wallet=#1\n"
        msg += "Go /wallets de xem vi, /networks de xem chain"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    token_address = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("So tien khong hop le. VD: 0.001")
        return

    chat_id = update.effective_chat.id

    # === SECURITY CHECKS ===
    # 1. Whitelist + PIN
    access = security.check_access(chat_id, "buy")
    if not access["allowed"]:
        await update.message.reply_text(f"\U0001f6e1 {access['reason']}", parse_mode="HTML")
        return

    # 2. TX Limit
    tx_check = security.check_tx_limit(chat_id, amount)
    if not tx_check["allowed"]:
        await update.message.reply_text(f"\U0001f534 {tx_check['reason']}")
        return

    # 3. Honeypot check
    chain = context.args[2].lower() if len(context.args) > 2 else "arbitrum"
    if security.config.get("honeypot_check"):
        hp = await security.check_honeypot(token_address, chain)
        if hp.get("checked") and not hp.get("safe"):
            warnings = "\n".join(f"  \U0001f534 {w}" for w in hp.get("warnings", []))
            await update.message.reply_text(
                f"\U0001f6a8 <b>CANH BAO HONEYPOT!</b>\n"
                f"Token nay KHONG an toan:\n{warnings}\n\n"
                f"Buy tax: {hp.get('buy_tax', 0):.1f}% | Sell tax: {hp.get('sell_tax', 0):.1f}%\n"
                f"Giao dich bi HUY de bao ve ban.",
                parse_mode="HTML",
            )
            return
    wallet_id = int(context.args[3]) if len(context.args) > 3 else 1

    if chain not in NETWORKS:
        await update.message.reply_text(f"Chain '{chain}' khong ho tro. Go /networks")
        return

    wm = WalletManager()
    wallet = wm.get_wallet(wallet_id)
    if not wallet:
        await update.message.reply_text(f"Khong tim thay vi #{wallet_id}. Go /wallet de tao vi.")
        return

    # Hien thi xac nhan
    net = NETWORKS[chain]
    confirm_msg = f"\U0001f6d2 <b>XAC NHAN MUA</b>\n"
    confirm_msg += "\u2501" * 18 + "\n"
    confirm_msg += f"\U0001f4cb <b>Token:</b> <code>{token_address[:10]}...{token_address[-6:]}</code>\n"
    confirm_msg += f"\U0001f4b0 <b>So tien:</b> {amount} {net['symbol']}\n"
    confirm_msg += f"\U0001f310 <b>Chain:</b> {net['name']}\n"
    confirm_msg += f"\U0001f4bc <b>Vi:</b> #{wallet_id} ({wallet['address'][:10]}...)\n"
    confirm_msg += "\u2501" * 18 + "\n"
    confirm_msg += "Dang thuc hien swap..."
    await update.message.reply_text(confirm_msg, parse_mode="HTML")

    # Thuc hien swap
    bot = OnChainBot(wm)
    try:
        result = await bot.swap_eth_for_token(
            wallet_id=wallet_id,
            router_address=_get_dex_router(chain),
            token_address=token_address,
            amount_ether=amount,
            network=chain,
            weth_address=_get_weth(chain),
        )

        if "error" in result:
            msg = f"\U0001f534 <b>MUA THAT BAI</b>\n"
            msg += f"Loi: {html.escape(str(result['error'])[:200])}\n"
            msg += "\nKiem tra: so du vi, contract address, chain."
        else:
            security.record_tx(chat_id, amount, "buy")
            msg = f"\U0001f7e2 <b>MUA THANH CONG!</b>\n"
            msg += "\u2501" * 18 + "\n"
            msg += f"\U0001f4cb <b>TX:</b> <code>{result['tx_hash'][:16]}...</code>\n"
            msg += f"\U0001f4b0 <b>Da swap:</b> {amount} {net['symbol']}\n"
            msg += f"\U0001f310 <a href='{result.get('explorer', '')}'>Xem giao dich</a>\n"
            msg += "\u2501" * 18

        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"\U0001f534 Loi: {html.escape(str(e)[:200])}", parse_mode="HTML")


def _get_dex_router(chain: str) -> str:
    """Lay dia chi router DEX theo chain."""
    routers = {
        "arbitrum": "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",  # SushiSwap
        "base": "0x2626664c2603336E57B271c5C0b26F421741e481",      # Uniswap V3
        "ethereum": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",   # Uniswap V2
        "bsc": "0x10ED43C718714eb63d5aA57B78B54704E256024E",        # PancakeSwap
        "polygon": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",    # QuickSwap
        "optimism": "0xE592427A0AEce92De3Edee1F18E0157C05861564",   # Uniswap V3
        "avalanche": "0x60aE616a2155Ee3d9A68541Ba4544862310933d4",  # TraderJoe
        "fantom": "0xF491e7B69E4244ad4002BC14e878a34207E38c29",     # SpookySwap
        "linea": "0x80e38291e06339d10AAB483C65695D004dBD5C69",      # SyncSwap
        "blast": "0x44889b52b71E60De6ed7dE82E2939fcc52fB2B4E",      # Thruster
        "cronos": "0x145863Eb42Cf62847A6Ca784e6416C1682b1b2Ae",     # VVS Finance
        "mantle": "0x319B69888b0d11cEC22B1114688381d2cBdAe283",     # Agni Finance
    }
    return routers.get(chain, routers["arbitrum"])


def _get_weth(chain: str) -> str:
    """Lay dia chi WETH theo chain."""
    weth = {
        "arbitrum": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "base": "0x4200000000000000000000000000000000000006",
        "ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "bsc": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",        # WBNB
        "polygon": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",    # WPOL
        "optimism": "0x4200000000000000000000000000000000000006",
        "avalanche": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",  # WAVAX
        "fantom": "0x21be370D5312f44cB42ce377BC9b8a0cEF1A4C83",     # WFTM
        "linea": "0xe5D7C2a44FfDDf6b295A15c148167daaAf5Cf34f",      # WETH
        "blast": "0x4300000000000000000000000000000000000004",       # WETH
        "cronos": "0x5C7F8A570d578ED84E63fdFA7b1eE72dEae1AE23",     # WCRO
        "mantle": "0x78c1b0C915c4FAA5FffA6CAbf0219DA63d7f4cb8",     # WMNT
    }
    return weth.get(chain, weth["arbitrum"])


# ============================================
#  LISTING COMMANDS: /listing, /monitor
# ============================================

async def cmd_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lenh /listing - Tim token co kha nang sap len Binance.
    So sanh danh sach Gate.io/MEXC vs Binance.
    """
    await update.message.reply_text(
        "\U0001f6a8 Dang quet token tren Binance, Gate.io, MEXC...\n"
        "Tim token co kha nang sap len Binance. Cho 10-15 giay."
    )

    scanner = ListingScanner()
    try:
        results = await scanner.find_potential_listings()

        if not results:
            await update.message.reply_text("Khong tim thay token tiem nang nao.")
            return

        # Hien thi top 15 token co kha nang cao nhat
        top = results[:15]

        msg = "\U0001f6a8 <b>TOKEN TIEM NANG SẮP LEN BINANCE</b>\n"
        msg += "\u2501" * 20 + "\n"
        msg += f"Tong: {len(results)} token | Hien thi top {len(top)}\n\n"

        for i, r in enumerate(top, 1):
            if r["confidence"] == "CAO":
                emoji = "\U0001f525"  # fire
            else:
                emoji = "\U0001f7e1"

            exchanges = ", ".join(r["on_exchanges"])
            msg += f"{emoji} <b>#{i} {r['symbol']}</b>\n"
            msg += f"  Da co: {exchanges}\n"
            msg += f"  Chua co: Binance\n"
            msg += f"  Kha nang: <b>{r['confidence']}</b> ({r['score']}%)\n"
            msg += f"  \U0001f50d <code>/check {r['symbol']}</code>\n\n"

        msg += "\u2501" * 20 + "\n"
        msg += "\U0001f525 = CAO (co tren Gate + MEXC)\n"
        msg += "\U0001f7e1 = TRUNG BINH (chi 1 san)\n\n"
        msg += "\U0001f514 Go <code>/monitor</code> de theo doi listing moi tu dong."

        await update.message.reply_text(msg, parse_mode="HTML")
    finally:
        await scanner.close()


async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /monitor - Bat/tat giam sat listing moi tu dong."""
    if listing_scanner._running:
        listing_scanner.stop_monitor()
        await update.message.reply_text(
            "\U0001f534 Da TAT giam sat listing.\n"
            "Go /monitor de bat lai."
        )
    else:
        listing_scanner.start_monitor(interval=300)  # 5 phut
        await update.message.reply_text(
            "\U0001f7e2 <b>DA BAT GIAM SAT LISTING!</b>\n"
            "\u2501" * 18 + "\n"
            "Bot se kiem tra moi 5 phut:\n"
            "  \U0001f534 Token moi len Binance\n"
            "  \U0001f4f0 Thong bao listing tu Binance\n\n"
            "Khi phat hien listing moi -> Gui canh bao tuc thi!\n"
            "Go /monitor lan nua de TAT.",
            parse_mode="HTML",
        )


# ============================================
#  SECURITY COMMANDS
# ============================================

async def cmd_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /security - Xem trang thai bao mat."""
    chat_id = update.effective_chat.id
    status = security.get_security_status()

    wl_emoji = "\U0001f7e2" if status['whitelist'] else "\U0001f534"
    pin_emoji = "\U0001f7e2" if status['pin_enabled'] else "\U0001f534"
    hp_emoji = "\U0001f7e2" if status['honeypot_check'] else "\U0001f534"

    is_admin = security.is_admin(chat_id)
    is_wl = security.is_whitelisted(chat_id)

    msg = "\U0001f6e1 <b>TRANG THAI BAO MAT</b>\n"
    msg += "\u2501" * 20 + "\n"
    msg += f"{wl_emoji} Whitelist: {'BAT' if status['whitelist'] else 'TAT'} ({status['whitelist_count']} users)\n"
    msg += f"{pin_emoji} PIN giao dich: {'BAT' if status['pin_enabled'] else 'TAT'}\n"
    msg += f"\U0001f4b0 Gioi han TX: {status['tx_limit']}\n"
    msg += f"\u23f1 Rate limit: {status['rate_limit']}\n"
    msg += f"{hp_emoji} Honeypot check: {'BAT' if status['honeypot_check'] else 'TAT'}\n"
    msg += "\u2501" * 20 + "\n"
    msg += f"Chat ID cua ban: <code>{chat_id}</code>\n"
    msg += f"Quyen: {'ADMIN' if is_admin else ('Whitelist' if is_wl else 'Chua xac nhan')}\n"
    msg += "\n<b>LENH BAO MAT:</b>\n"
    msg += "  /setpin [4-8 so] - Dat PIN\n"
    msg += "  /pin [PIN] - Xac nhan PIN\n"
    msg += "  /whitelist [Chat ID] - Them user\n"
    msg += "  /setlimit [so ETH] - Gioi han TX\n"
    msg += "  /audit - Xem nhat ky\n"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_setpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /setpin [PIN] - Dat PIN bao mat."""
    chat_id = update.effective_chat.id

    # Auto-add lam admin neu chua co admin nao
    if not security.config["admin_ids"]:
        security.add_admin(chat_id)

    if not security.is_admin(chat_id):
        await update.message.reply_text("Chi admin moi duoc dat PIN.")
        return

    if not context.args:
        await update.message.reply_text("Nhap PIN (4-8 so). VD: <code>/setpin 1234</code>", parse_mode="HTML")
        return

    pin = context.args[0]
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 8:
        await update.message.reply_text("PIN phai tu 4-8 chu so.")
        return

    security.set_pin(pin)
    await update.message.reply_text(
        "\U0001f512 <b>DA DAT PIN THANH CONG!</b>\n"
        "Cac lenh /buy, /send, /claim, /farm se can xac nhan PIN.\n"
        "Go <code>/pin [PIN]</code> de mo khoa (hieu luc 15 phut).\n"
        "\u26a0\ufe0f Xoa tin nhan chua PIN ngay!",
        parse_mode="HTML",
    )


async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /pin [PIN] - Xac nhan PIN de mo khoa giao dich."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Go: <code>/pin [ma PIN]</code>", parse_mode="HTML")
        return

    pin = context.args[0]
    if security.verify_pin(pin, chat_id):
        await update.message.reply_text(
            "\U0001f513 <b>MO KHOA THANH CONG!</b>\n"
            "Ban co the giao dich trong 15 phut.\n"
            "\u26a0\ufe0f Xoa tin nhan chua PIN ngay!",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("\U0001f534 PIN sai! Thu lai.")


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /whitelist [chat_id] - Them user vao whitelist."""
    chat_id = update.effective_chat.id

    # Auto-add lam admin neu chua co
    if not security.config["admin_ids"]:
        security.add_admin(chat_id)
        await update.message.reply_text(
            f"\U0001f451 Ban da duoc them lam ADMIN (Chat ID: <code>{chat_id}</code>).\n"
            "Whitelist da bat. Chi ban va nguoi duoc them moi dung duoc bot.",
            parse_mode="HTML",
        )
        return

    if not security.is_admin(chat_id):
        await update.message.reply_text("Chi admin moi them whitelist.")
        return

    if not context.args:
        wl = security.config['whitelist_ids']
        msg = "\U0001f4cb <b>WHITELIST</b>\n"
        msg += "\u2501" * 18 + "\n"
        for wid in wl:
            admin = " (Admin)" if wid in security.config['admin_ids'] else ""
            msg += f"  \U0001f7e2 <code>{wid}</code>{admin}\n"
        msg += f"\nTong: {len(wl)} users\n"
        msg += "Them: <code>/whitelist [Chat ID]</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        new_id = int(context.args[0])
        security.add_whitelist(new_id)
        await update.message.reply_text(
            f"\U0001f7e2 Da them <code>{new_id}</code> vao whitelist.",
            parse_mode="HTML",
        )
    except ValueError:
        await update.message.reply_text("Chat ID phai la so.")


async def cmd_setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /setlimit [so ETH] - Thay doi gioi han giao dich."""
    chat_id = update.effective_chat.id

    if not security.config["admin_ids"]:
        security.add_admin(chat_id)

    if not security.is_admin(chat_id):
        await update.message.reply_text("Chi admin.")
        return

    if not context.args:
        msg = "\U0001f4b0 <b>GIOI HAN GIAO DICH</b>\n"
        msg += "\u2501" * 18 + "\n"
        msg += f"  Moi TX: {security.config['tx_limit_per_tx']} ETH\n"
        msg += f"  Moi ngay: {security.config['tx_limit_daily']} ETH\n"
        msg += "\nThay doi: <code>/setlimit 0.5</code> (per TX)\n"
        msg += "<code>/setlimit 0.5 5.0</code> (per TX + daily)"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        per_tx = float(context.args[0])
        daily = float(context.args[1]) if len(context.args) > 1 else per_tx * 10
        security.config["tx_limit_per_tx"] = per_tx
        security.config["tx_limit_daily"] = daily
        security._save_config()
        await update.message.reply_text(
            f"\U0001f7e2 Da cap nhat gioi han:\n"
            f"  Moi TX: {per_tx} ETH\n"
            f"  Moi ngay: {daily} ETH",
        )
    except ValueError:
        await update.message.reply_text("So khong hop le.")


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /audit - Xem nhat ky hoat dong."""
    chat_id = update.effective_chat.id

    if not security.is_admin(chat_id) and security.config["admin_ids"]:
        await update.message.reply_text("Chi admin.")
        return

    logs = security.get_audit_log(15)
    if not logs:
        await update.message.reply_text("Chua co log nao.")
        return

    msg = "\U0001f4cb <b>NHAT KY HOAT DONG</b>\n"
    msg += "\u2501" * 20 + "\n"
    for entry in reversed(logs):
        t = entry.get('time', '')[:16]
        act = entry.get('action', '')
        detail = html.escape(entry.get('detail', '')[:40])
        msg += f"<code>{t}</code> {act}"
        if detail:
            msg += f" | {detail}"
        msg += "\n"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_freeairdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lenh /freeairdrop - Tim cac su kien airdrop tren CEX."""
    await update.message.reply_text(
        "\U0001f575\ufe0f Dang quet Megadrop, Launchpool, Web3 Airdrop tren Binance & Bybit...\n"
        "Viec nay co the mat 5-10 giay."
    )
    
    scanner = CexAirdropScanner()
    try:
        airdrops = await scanner.get_all_airdrops()
        if not airdrops:
            await update.message.reply_text("Hien tai khong co su kien Airdrop/Launchpool nao dang chu y.")
            return
            
        msg = "\U0001f381 <b>KEO AIRDROP / LAUNCHPOOL (TIEN TUOI)</b>\n"
        msg += "\u2501" * 18 + "\n"
        
        for i, ad in enumerate(airdrops[:15], 1):
            ex = ad["exchange"]
            emoji = "\U0001f7e1" if ex == "Binance" else "\U0001f535"
            cap = ad["capital"]
            
            msg += f"{emoji} <b>#{i} {ex}</b>: <a href='{ad['link']}'>{html.escape(ad['title'])}</a>\n"
            msg += f"   \U0001f4b0 {cap}\n"
            msg += f"   \U0001f4c5 {ad['date']}\n\n"
            
        msg += "\u2501" * 18 + "\n"
        msg += "<i>Luu y: Bai dang cang moi thi kha nang tham gia duoc cang cao.</i>\n"
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Loi /freeairdrop: {e}")
        await update.message.reply_text("\U0001f534 Co loi khi lay du lieu airdrop cua san.")
    finally:
        await scanner.close()


# ============================================
#  PAPER TRADING COMMANDS
# ============================================

async def cmd_autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bat/tat che do tu dong vao lenh (Auto Trading)."""
    if not context.args:
        status = "BẬT" if trade_engine.auto_trade_enabled else "TẮT"
        await update.message.reply_text(f"Auto-trade hien dang: {status}. Dung `/autotrade on|off` de thay doi.")
        return

    arg = context.args[0].lower()
    if arg == "on":
        trade_engine.toggle_auto_trade(True)
        await update.message.reply_text("\U0001f7e2 Đã <b>BẬT</b> giao dịch tự động. Bot se tu dong vao lenh paper trade khi co tin hieu AI.", parse_mode="HTML")
    elif arg == "off":
        trade_engine.toggle_auto_trade(False)
        await update.message.reply_text("\U0001f534 Đã <b>TẮT</b> giao dịch tự động.", parse_mode="HTML")
    else:
        await update.message.reply_text("Sai cu phap. Dung <code>/autotrade on</code> hoac <code>/autotrade off</code>.", parse_mode="HTML")

async def cmd_paper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem trang thai tai khoan Paper Trading."""
    status = trade_engine.get_portfolio_status()
    
    msg = "\U0001f4bc <b>VÍ GIẢ LẬP (PAPER TRADING)</b>\n"
    msg += "\u2501" * 18 + "\n"
    
    pnl_icon = "\U0001f4c8" if status["total_pnl"] >= 0 else "\U0001f4c9"
    balance_text = f"${status['balance']:,.2f} USDT"
    
    msg += f"\U0001f4b0 <b>Số dư hiện tại:</b> {balance_text}\n"
    msg += f"{pnl_icon} <b>Tổng PnL:</b> ${status['total_pnl']:,.2f}\n"
    msg += f"\U0001f4ca <b>Số lệnh đã đóng:</b> {status['total_trades']}\n"
    msg += f"\U0001f3af <b>Win Rate:</b> {status['win_rate']:.1f}%\n"
    msg += f"\U0001f504 <b>Lệnh đang mở:</b> {status['open_positions']}\n"
    
    auto_status = "BẬT \U0001f7e2" if status["auto_trade"] else "TẮT \U0001f534"
    msg += f"\u2699\ufe0f <b>Auto-Trade:</b> {auto_status}\n"
    
    # Hien thi cac lenh dang mo
    if trade_engine.positions:
        msg += "\n\U0001f516 <b>LỆNH ĐANG MỞ (Real-time):</b>\n"
        
        # Khoi tao Websocket de lay gia hien tai
        ws = BinanceWebSocket()
        unrealized_pnl_total = 0.0
        
        for i, (key, pos) in enumerate(trade_engine.positions.items(), 1):
            dir_icon = "\U0001f7e2" if pos["direction"] == "LONG" else "\U0001f534"
            coin = pos['coin']
            entry = pos['entry_price']
            size = pos['usdt_size']
            realized_pnl = pos['pnl']  # PnL da chot 1 phan
            
            # Lay gia hien tai tu Binance
            symbol = f"{coin.lower()}usdt"
            try:
                price_data = await ws.get_price_once(symbol)
                current_price = price_data["price"] if price_data else entry
            except:
                current_price = entry
                
            # Tinh PnL chua chot (Unrealized)
            is_long = pos["direction"] == "LONG"
            price_diff_pct = (current_price - entry) / entry
            if not is_long:
                price_diff_pct = -price_diff_pct
                
            # Chi tinh tren phan size con lai (chua chot)
            rem_pct = 1.0 - pos.get("closed_pct", 0.0)
            rem_size = size * rem_pct
            unrealized_pnl = rem_size * price_diff_pct
            
            unrealized_pnl_total += unrealized_pnl
            
            # Mau sac cho PnL
            total_pos_pnl = realized_pnl + unrealized_pnl
            pnl_str = f"+${total_pos_pnl:.2f}" if total_pos_pnl >= 0 else f"-${abs(total_pos_pnl):.2f}"
            
            msg += f"  {i}. {dir_icon} <b>{coin}</b> | Size: ${size:.1f}\n"
            msg += f"     Entry: ${entry:.4f} | Cur: ${current_price:.4f}\n"
            msg += f"     PnL: <b>{pnl_str}</b> ({price_diff_pct*100:+.2f}%)\n"
            
        # Hien thi them uoc tinh tong Balance neu dong het lenh bay gio
        est_balance = status['balance'] + unrealized_pnl_total
        msg += f"\n\U0001f4b0 <b>Ước tính (Equity):</b> ${est_balance:,.2f}\n"

    msg += "\u2501" * 18 + "\n"
    msg += "Dung <code>/autotrade on|off</code> de thay doi."
    
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_trailsl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bat/tat Trailing Stop Loss cho position. VD: /trailsl BTC on"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Cu phap: <code>/trailsl [coin] on|off</code>\n"
            "VD: <code>/trailsl BTC on</code>\n\n"
            "Trailing SL se tu dong dich Stop Loss len:\n"
            "- Gia qua TP1 → SL len break-even\n"
            "- Gia qua TP2 → SL len TP1",
            parse_mode="HTML"
        )
        return

    coin = context.args[0].upper()
    mode = context.args[1].lower()

    # Tim position chua dong cua coin nay
    target_key = None
    for key, pos in trade_engine.positions.items():
        if pos.get("coin") == coin and pos.get("status") != "CLOSED":
            target_key = key
            break

    if not target_key:
        await update.message.reply_text(f"\U0001f534 Khong co lenh mo nao voi <b>{coin}</b>.", parse_mode="HTML")
        return

    enable = mode == "on"
    trade_engine.set_trailing_sl(target_key, enable)
    status_text = "\U0001f7e2 BẬT" if enable else "\U0001f534 TẮT"
    await update.message.reply_text(
        f"\U0001f50d Trailing Stop Loss <b>{status_text}</b> cho <b>{coin}</b>.\n"
        f"SL hien tai: <code>${trade_engine.positions[target_key]['sl']:.4f}</code>",
        parse_mode="HTML"
    )

# ============================================
#  PRICE ALERT COMMANDS
# ============================================

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dat canh bao gia. VD: /alert BTC 100000 above"""
    chat_id = update.effective_chat.id

    if len(context.args) < 3:
        await update.message.reply_text(
            "\U0001f514 <b>Dat canh bao gia</b>\n"
            "━" * 18 + "\n"
            "Cu phap: <code>/alert [coin] [gia] [above|below]</code>\n\n"
            "Vi du:\n"
            "- <code>/alert BTC 100000 above</code> (canh bao khi BTC vuot 100k)\n"
            "- <code>/alert ETH 2000 below</code> (canh bao khi ETH duoi 2000)\n\n"
            "Xem danh sach alerts: <code>/alerts</code>",
            parse_mode="HTML"
        )
        return

    coin = context.args[0].upper()
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("\U0001f534 Gia khong hop le. VD: <code>/alert BTC 100000 above</code>", parse_mode="HTML")
        return

    direction = context.args[2].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text("\U0001f534 Phai chon <code>above</code> hoac <code>below</code>.", parse_mode="HTML")
        return

    alert_id = _db.add_price_alert(chat_id, coin, target, direction)
    dir_text = "VUOT TREN" if direction == "above" else "XUONG DUOI"
    await update.message.reply_text(
        f"✅ Da dat canh bao #{alert_id}:\n"
        f"\U0001f4b0 <b>{coin}</b> khi gia {dir_text} <code>${target:,.2f}</code>\n\n"
        f"Bot se tu dong thong bao khi dieu kien xay ra.",
        parse_mode="HTML"
    )

async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem va xoa danh sach price alerts."""
    chat_id = update.effective_chat.id

    # Xoa alert neu co tham so ID
    if context.args and context.args[0].lower() == "del" and len(context.args) > 1:
        try:
            alert_id = int(context.args[1])
            _db.delete_alert(alert_id, chat_id)
            await update.message.reply_text(f"\U0001f5d1 Da xoa alert #{alert_id}.", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("Cu phap: <code>/alerts del [id]</code>", parse_mode="HTML")
        return

    alerts = _db.get_active_alerts(chat_id)
    if not alerts:
        await update.message.reply_text(
            "\U0001f514 Chua co price alert nao.\n"
            "Dat alert: <code>/alert BTC 100000 above</code>",
            parse_mode="HTML"
        )
        return

    msg = "\U0001f514 <b>PRICE ALERTS CUA BAN</b>\n"
    msg += "━" * 18 + "\n"
    for a in alerts:
        dir_icon = "⬆️" if a["direction"] == "above" else "⬇️"
        msg += f"#{a['id']} {dir_icon} <b>{a['coin']}</b> {a['direction']} <code>${a['target_price']:,.4f}</code>\n"
    msg += "━" * 18 + "\n"
    msg += "Xoa: <code>/alerts del [id]</code>"
    await update.message.reply_text(msg, parse_mode="HTML")

# ============================================
#  SOCIAL AUTOMATION COMMANDS
# ============================================

async def cmd_social(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kiem tra trang thai Bot-net (Tele + Twitter)."""
    msg = "\U0001f310 <b>TRẠNG THÁI SOCIAL AUTOMATION</b>\n"
    msg += "\u2501" * 18 + "\n"
    msg += f"\U0001f4e4 <b>Telegram Bots:</b> {len(telegram_manager.workers)} Sessions\n"
    msg += f"\U0001f426 <b>Twitter Bots:</b> {len(twitter_manager.workers)} Accounts\n"
    msg += "\u2501" * 18 + "\n"
    msg += "Lenh hoat dong:\n"
    msg += "- <code>/claimall [bot_user] [cmd]</code>: Tap-to-earn hang loat\n"
    msg += "- <code>/retweet [tweet_id]</code>: X-Raid (Like+RT)\n"
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_claimall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ra lenh cho all Tele bot claim app. VD: /claimall blumcrypto_bot /start"""
    if len(context.args) < 2:
        await update.message.reply_text("Cu phap: `/claimall [bot_username] [lenh]`\nVD: `/claimall blumcrypto_bot /start`", parse_mode="Markdown")
        return
        
    bot_user = context.args[0]
    cmd = " ".join(context.args[1:])
    
    if len(telegram_manager.workers) == 0:
        await update.message.reply_text("\U0001f534 Chua ket noi Session Telegram nao. Vui long them tai khoan vao config truoc.")
        return
        
    await update.message.reply_text(f"\U0001f680 Dang dieu dong {len(telegram_manager.workers)} acc gui `{cmd}` den `{bot_user}`...", parse_mode="Markdown")
    
    # Chay ngam (Fire and forget) de ko block Telegram bot
    asyncio.ensure_future(telegram_manager.claim_all_bots(bot_user, cmd))

async def cmd_retweet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Binh doan Twitter vao Raid. VD: /retweet 123456789"""
    if not context.args:
        await update.message.reply_text("Cu phap: `/retweet [tweet_id]`", parse_mode="Markdown")
        return
        
    tweet_id = context.args[0]
    if len(twitter_manager.workers) == 0:
        await update.message.reply_text("\U0001f534 Chua ket noi acc Twitter nao!")
        return
        
    await update.message.reply_text(f"\U0001f525 X-RAID KICH HOAT! Dang cho {len(twitter_manager.workers)} acc vao Like & Retweet vong lap...")
    
    # Twitter chay delay lau, dua ra background thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, twitter_manager.raid_tweet, tweet_id)


#  MAIN - KHOI DONG BOT
# ============================================

def main():
    """Khoi dong Telegram Bot."""
    token = Config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN chua duoc cau hinh!")
        return

    logger.info("Khoi dong Crypto Bot...")

    # Tao ung dung
    app = Application.builder().token(token).build()

    # Dang ky lenh
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("news", cmd_news))

    # Airdrop commands
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("wallets", cmd_wallets))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("networks", cmd_networks))
    app.add_handler(CommandHandler("farm", cmd_farm))
    app.add_handler(CommandHandler("claim", cmd_claim))

    # Signal commands
    app.add_handler(CommandHandler("spot", cmd_spot))
    app.add_handler(CommandHandler("futures", cmd_futures))
    app.add_handler(CommandHandler("signals", cmd_signals))

    # Paper Trading / Auto-Trade commands
    app.add_handler(CommandHandler("autotrade", cmd_autotrade))
    app.add_handler(CommandHandler("paper", cmd_paper))
    app.add_handler(CommandHandler("trailsl", cmd_trailsl))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))

    # DEX Gem commands
    app.add_handler(CommandHandler("gem", cmd_gem))
    app.add_handler(CommandHandler("newtoken", cmd_newtoken))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("buy", cmd_buy))

    # Social Automation
    app.add_handler(CommandHandler("social", cmd_social))
    app.add_handler(CommandHandler("claimall", cmd_claimall))
    app.add_handler(CommandHandler("retweet", cmd_retweet))

    # Listing & CEX Airdrop commands
    app.add_handler(CommandHandler("listing", cmd_listing))
    app.add_handler(CommandHandler("monitor", cmd_monitor))
    app.add_handler(CommandHandler("freeairdrop", cmd_freeairdrop))

    # Security commands
    app.add_handler(CommandHandler("security", cmd_security))
    app.add_handler(CommandHandler("setpin", cmd_setpin))
    app.add_handler(CommandHandler("pin", cmd_pin))
    app.add_handler(CommandHandler("whitelist", cmd_whitelist))
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))
    app.add_handler(CommandHandler("audit", cmd_audit))

    # Bat ky tin nhan text nao -> phan tich token
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_token))

    # Khoi dong Signal Tracker
    signal_tracker.start()
    logger.info("Signal Tracker da khoi dong.")
    
    # Truyen instance sang API
    inject_instances(
        trade_engine, telegram_manager, twitter_manager, system_status,
        signal_tracker=signal_tracker, listing_scanner=listing_scanner,
        security=security, wallet_manager=wallet_manager,
        price_monitor=price_monitor
    )

    logger.success("Bot da san sang! Go ten token tren Telegram hoac truy cap http://localhost:8000/docs")
    logger.info("Nhan Ctrl+C de dung bot.")

    # --- Khoi dong API va Telegram song song ---
    # Thay vi chi app.run_polling() se block, ta can chay ca 2
    
    async def start_services():
        # Khoi tao API task
        api_task = asyncio.create_task(run_server(port=8000))
        
        # Khoi dong Telegram Bot task
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Keep alive
        while True:
            system_status["uptime_minutes"] += 1
            await asyncio.sleep(60)
            
    try:
        # Chay event loop chinh
        asyncio.run(start_services())
    except KeyboardInterrupt:
        logger.info("Bot da dung lai!")

if __name__ == "__main__":
    main()
