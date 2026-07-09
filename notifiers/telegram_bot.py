"""
Telegram Bot Notifier Module
Gửi thông báo (tin nhắn, ảnh, cảnh báo) về Telegram cá nhân.
"""
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from loguru import logger
from core.config import Config


class TelegramNotifier:
    """
    Lớp quản lý gửi tin nhắn qua Telegram Bot.
    Hỗ trợ: Text, HTML format, và ảnh.
    """

    def __init__(self):
        self.bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.group_chat_id = Config.TELEGRAM_GROUP_CHAT_ID

    async def send_message(self, text: str, parse_mode: str = ParseMode.HTML, chat_id = None):
        """Gửi tin nhắn về Telegram (hỗ trợ gửi nhiều đích nếu không chỉ định chat_id cụ thể)."""
        targets = []
        if chat_id:
            targets.append(chat_id)
        else:
            if self.chat_id:
                targets.append(self.chat_id)
            if self.group_chat_id:
                targets.append(self.group_chat_id)

        if not targets:
            logger.debug("TelegramNotifier không có chat_id đích nào để gửi.")
            return

        for target in targets:
            try:
                await self.bot.send_message(
                    chat_id=target,
                    text=text,
                    parse_mode=parse_mode,
                )
                logger.info(f"📨 Đã gửi tin nhắn Telegram tới {target}: {text[:50]}...")
            except Exception as e:
                logger.error(f"❌ Lỗi gửi Telegram tới {target}: {e}")

    async def send_signal(
        self,
        coin: str,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        reason: str = "",
        rating: int = 3,
    ):
        """Gửi tín hiệu giao dịch (Trading Signal) về Telegram kèm độ tin cậy."""
        emoji = "🟢" if direction.upper() == "LONG" else "🔴"
        risk_reward = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

        rating_stars = "⭐" * rating
        rating_label = ""
        if rating == 5:
            rating_label = "🔥 CỰC MẠNH (Xác suất cao)"
        elif rating == 4:
            rating_label = "✨ MẠNH (Ưu tiên)"
        elif rating == 3:
            rating_label = "⚡ TRUNG BÌNH"
        elif rating == 2:
            if "canh bao" in reason.lower() or "nguoc xu huong" in reason.lower():
                rating_label = "🎣 BẮT ĐÁY MẠO HIỂM"
            else:
                rating_label = "⚖️ TRUNG BÌNH YẾU"
        else:
            rating_label = "⚠️ YẾU (Nhiễu / Bỏ qua)"

        msg = (
            f"{emoji} <b>TÍN HIỆU {direction.upper()}</b> {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>Coin:</b> {coin}\n"
            f"⭐ <b>Độ tin cậy:</b> {rating_stars} ({rating_label})\n"
            f"📍 <b>Entry:</b> ${entry:,.2f}\n"
            f"🛑 <b>Stop Loss:</b> ${sl:,.2f}\n"
            f"🎯 <b>Take Profit:</b> ${tp:,.2f}\n"
            f"📊 <b>R:R Ratio:</b> 1:{risk_reward:.1f}\n"
        )
        if reason:
            msg += f"💡 <b>Lý do:</b> {reason}\n"
        msg += f"━━━━━━━━━━━━━━━━━━"

        await self.send_message(msg)

    async def send_price_alert(self, coin: str, price: float, change_pct: float):
        """Gửi cảnh báo biến động giá mạnh."""
        emoji = "📈" if change_pct > 0 else "📉"
        color = "🟢" if change_pct > 0 else "🔴"

        msg = (
            f"{emoji} <b>CẢNH BÁO GIÁ</b>\n"
            f"{color} <b>{coin}:</b> ${price:,.2f} ({change_pct:+.2f}%)\n"
        )
        await self.send_message(msg)

    async def send_news_alert(self, title: str, source: str, sentiment: str, url: str = ""):
        """Gửi cảnh báo tin tức nóng."""
        sentiment_map = {
            "bullish": "🟢 TÍCH CỰC",
            "bearish": "🔴 TIÊU CỰC",
            "neutral": "⚪ TRUNG LẬP",
        }
        label = sentiment_map.get(sentiment.lower(), "⚪ TRUNG LẬP")

        msg = (
            f"📰 <b>TIN NÓNG CRYPTO</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 {title}\n"
            f"🏢 Nguồn: {source}\n"
            f"🎯 Đánh giá: {label}\n"
        )
        if url:
            msg += f"🔗 <a href='{url}'>Đọc thêm</a>\n"
        msg += "━━━━━━━━━━━━━━━━━━"

        await self.send_message(msg)

    async def send_airdrop_report(self, project: str, wallets_done: int, total_wallets: int, tasks_completed: list):
        """Gửi báo cáo tiến trình Airdrop."""
        task_list = "\n".join([f"  ✅ {t}" for t in tasks_completed])
        msg = (
            f"🪂 <b>BÁO CÁO AIRDROP</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 Dự án: <b>{project}</b>\n"
            f"👛 Ví hoàn thành: {wallets_done}/{total_wallets}\n"
            f"📋 Tasks:\n{task_list}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        await self.send_message(msg)


# --- Hàm tiện ích (dùng nhanh ở bất cứ đâu) ---
async def quick_send(text: str):
    """Gửi nhanh 1 tin nhắn mà không cần khởi tạo class."""
    notifier = TelegramNotifier()
    await notifier.send_message(text)
