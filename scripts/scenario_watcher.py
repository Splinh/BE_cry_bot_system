"""
Scenario Watcher - Tự động theo dõi giá BTC theo thời gian thực và bắn thông báo
Đến Telegram, Zalo và Windows Toast/Beep khi giá chạm các mốc kịch bản 1 & 2.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
import requests
from loguru import logger

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from notifiers.telegram_bot import TelegramNotifier
from notifiers.zalo_bot import ZaloNotifier

try:
    import winsound
except ImportError:
    winsound = None

# Configure logger
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", level="INFO")
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
logger.add(os.path.join(BASE_DIR, "logs", "scenario_watcher.log"), rotation="5 MB", level="INFO")

# Thresholds
PRICE_EARLY_UP = 84800.0       # Cảnh báo sớm vượt nén tăng
PRICE_SHORT_ENTRY = 85300.0    # Vùng canh SHORT (Hướng 1)
PRICE_EARLY_DOWN = 84450.0     # Cảnh báo sớm thủng đáy nén
PRICE_LONG_ENTRY = 84100.0     # Vùng canh SCALP LONG (Hướng 2)

COOLDOWN_SECONDS = 300  # 5 phút cooldown cho mỗi loại cảnh báo để tránh spam

class ScenarioWatcher:
    def __init__(self):
        self.tg = TelegramNotifier()
        self.za = ZaloNotifier()
        self.last_alerts = {
            "early_up": 0,
            "short_entry": 0,
            "early_down": 0,
            "long_entry": 0,
        }
        self.running = True

    def fetch_price(self) -> float:
        """Lấy giá BTC từ Binance API."""
        urls = [
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    return float(data.get("price", 0.0))
            except Exception:
                continue
        return 0.0

    def sound_alert(self, freq=1000, duration=400):
        """Phát âm thanh cảnh báo trên Windows."""
        if winsound:
            try:
                winsound.Beep(freq, duration)
            except Exception:
                pass

    async def broadcast(self, message: str, sound_freq=1000):
        """Gửi đồng thời về Telegram và Zalo kèm âm thanh."""
        self.sound_alert(sound_freq, 500)
        logger.warning(f"📢 BROADCAST: {message}")
        
        # Gửi Telegram
        try:
            await self.tg.send_message(message)
        except Exception as e:
            logger.error(f"Lỗi gửi Telegram: {e}")
            
        # Gửi Zalo
        try:
            await self.za.send_message(message)
        except Exception as e:
            logger.error(f"Lỗi gửi Zalo: {e}")

    async def run(self):
        start_price = self.fetch_price()
        logger.info(f"🚀 Scenario Watcher đã khởi động. Giá ban đầu: ${start_price:,.2f}")
        
        init_msg = (
            f"🤖 <b>[CryptoBot System]</b> Đã kích hoạt chế độ theo dõi kịch bản BTC!\n\n"
            f"💵 <b>Giá bắt đầu:</b> <code>${start_price:,.2f}</code>\n"
            f"🎯 <b>Mốc canh SHORT (Hướng 1):</b> <code>từ $85,300 trở lên</code>\n"
            f"🎯 <b>Mốc canh LONG (Hướng 2):</b> <code>từ $84,100 trở xuống</code>\n"
            f"⚡ <b>Cảnh báo sớm:</b> <code>$84,800</code> (Tăng) | <code>$84,450</code> (Giảm)\n\n"
            f"<i>Bot sẽ tự động thông báo ngay khi giá chạm các mốc trên!</i>"
        )
        await self.broadcast(init_msg, sound_freq=800)

        check_counter = 0
        while self.running:
            try:
                price = self.fetch_price()
                if price <= 0:
                    await asyncio.sleep(3)
                    continue

                now = time.time()
                check_counter += 1

                # Log mỗi 20 lần check (~1 phút)
                if check_counter % 20 == 0:
                    logger.info(f"👀 Đang theo dõi... BTC = ${price:,.2f}")

                # 1. KÍCH HOẠT HƯỚNG 1 (SHORT ENTRY)
                if price >= PRICE_SHORT_ENTRY:
                    if now - self.last_alerts["short_entry"] > COOLDOWN_SECONDS:
                        self.last_alerts["short_entry"] = now
                        msg = (
                            f"🔴 <b>[KÍCH HOẠT HƯỚNG 1 - SHORT ENTRY!]</b>\n\n"
                            f"💰 <b>Giá BTC hiện tại:</b> <code>${price:,.2f}</code>\n"
                            f"📍 <b>Khu vực cản:</b> 85,300$ – 85,600$ (Retest đỉnh cũ/S-R Flip)\n\n"
                            f"🎯 <b>KẾ HOẠCH HÀNH ĐỘNG:</b>\n"
                            f"• Quan sát nến 5M/15M xem có tín hiệu từ chối (Pinbar/Bearish Engulfing).\n"
                            f"• <b>Entry:</b> {price:,.1f}$\n"
                            f"• <b>Stop Loss (SL):</b> 86,250$\n"
                            f"• <b>Take Profit (TP):</b> 84,000$ (TP1) | 83,000$ (TP2)"
                        )
                        await self.broadcast(msg, sound_freq=1500)

                # 2. CẢNH BÁO SỚM HƯỚNG LÊN (BREAKOUT 84,800)
                elif price >= PRICE_EARLY_UP:
                    if now - self.last_alerts["early_up"] > COOLDOWN_SECONDS:
                        self.last_alerts["early_up"] = now
                        msg = (
                            f"⚠️ <b>[CẢNH BÁO SỚM] BTC BỨT PHÁ HỘP NÉN!</b>\n\n"
                            f"📈 <b>Giá hiện tại:</b> <code>${price:,.2f}</code> (vượt mốc 84,800$)\n"
                            f"👉 Đà rướn đang hướng lên vùng cản <b>85,300$ - 85,600$</b>.\n"
                            f"<i>Chuẩn bị sẵn sàng setup Short theo Hướng 1 khi chạm cản!</i>"
                        )
                        await self.broadcast(msg, sound_freq=1200)

                # 3. KÍCH HOẠT HƯỚNG 2 (SCALP LONG ENTRY)
                elif price <= PRICE_LONG_ENTRY:
                    if now - self.last_alerts["long_entry"] > COOLDOWN_SECONDS:
                        self.last_alerts["long_entry"] = now
                        msg = (
                            f"🟢 <b>[KÍCH HOẠT HƯỚNG 2 - SCALP LONG ENTRY!]</b>\n\n"
                            f"💰 <b>Giá BTC hiện tại:</b> <code>${price:,.2f}</code>\n"
                            f"📍 <b>Khu vực hỗ trợ:</b> 83,800$ – 84,100$ (Đáy quét râu cũ)\n\n"
                            f"🎯 <b>KẾ HOẠCH HÀNH ĐỘNG:</b>\n"
                            f"• Quan sát nến rút chân 5M/15M hoặc phân kỳ RSI.\n"
                            f"• <b>Entry:</b> {price:,.1f}$\n"
                            f"• <b>Stop Loss (SL):</b> 83,300$\n"
                            f"• <b>Take Profit (TP):</b> 85,000$ – 85,300$"
                        )
                        await self.broadcast(msg, sound_freq=1500)

                # 4. CẢNH BÁO SỚM HƯỚNG XUỐNG (BREAKDOWN 84,450)
                elif price <= PRICE_EARLY_DOWN:
                    if now - self.last_alerts["early_down"] > COOLDOWN_SECONDS:
                        self.last_alerts["early_down"] = now
                        msg = (
                            f"⚠️ <b>[CẢNH BÁO SỚM] BTC THỦNG ĐÁY NÉN!</b>\n\n"
                            f"📉 <b>Giá hiện tại:</b> <code>${price:,.2f}</code> (thủng mốc 84,450$)\n"
                            f"👉 Giá đang trượt về vùng hỗ trợ <b>83,800$ – 84,100$</b>.\n"
                            f"<i>Chuẩn bị quan sát tín hiệu rút chân để bắt sóng hồi theo Hướng 2!</i>"
                        )
                        await self.broadcast(msg, sound_freq=900)

            except Exception as e:
                logger.error(f"Lỗi vòng lặp theo dõi: {e}")

            await asyncio.sleep(3)

if __name__ == "__main__":
    watcher = ScenarioWatcher()
    try:
        asyncio.run(watcher.run())
    except KeyboardInterrupt:
        logger.info("Đã dừng Scenario Watcher.")
