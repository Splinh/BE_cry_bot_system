"""
Script lấy Chat ID từ Telegram Bot.
Chạy: python scripts/get_chat_id.py

Hướng dẫn:
1. Mở Telegram, tìm bot bạn vừa tạo (theo username).
2. Bấm /start hoặc gửi 1 tin nhắn bất kỳ cho bot.
3. Chạy script này -> Chat ID sẽ hiện ra.
4. Copy Chat ID và điền vào file .env (TELEGRAM_CHAT_ID=...)
"""
import sys
import os
import asyncio

# Thêm thư mục gốc dự án vào Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram import Bot
from core.config import Config


async def get_chat_id():
    """Lấy Chat ID từ tin nhắn mới nhất gửi đến Bot."""
    bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)

    print("=" * 50)
    print("🔍 ĐANG TÌM CHAT ID...")
    print("=" * 50)
    print(f"Bot Token: {Config.TELEGRAM_BOT_TOKEN[:20]}...****")
    print()

    try:
        updates = await bot.get_updates()

        if not updates:
            print("❌ Không tìm thấy tin nhắn nào!")
            print()
            print("👉 Hãy làm theo các bước sau:")
            print("   1. Mở Telegram")
            print("   2. Tìm bot của bạn (theo Username)")
            print("   3. Bấm /start hoặc gửi 1 tin nhắn bất kỳ")
            print("   4. Chạy lại script này")
            return

        # Lấy tất cả Chat ID unique
        chat_ids = {}
        for update in updates:
            if update.message:
                chat_id = update.message.chat_id
                username = update.message.from_user.username or "N/A"
                first_name = update.message.from_user.first_name or "N/A"
                chat_ids[chat_id] = {
                    "username": username,
                    "first_name": first_name,
                    "text": update.message.text or "(No text)",
                }

        print("✅ TÌM THẤY CÁC CHAT ID SAU:")
        print("-" * 50)
        for cid, info in chat_ids.items():
            print(f"  👤 Tên: {info['first_name']} (@{info['username']})")
            print(f"  🆔 Chat ID: {cid}")
            print(f"  💬 Tin nhắn: {info['text']}")
            print("-" * 50)

        print()
        print("📋 Hãy copy Chat ID ở trên và điền vào file .env:")
        print(f"   TELEGRAM_CHAT_ID={list(chat_ids.keys())[0]}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")


if __name__ == "__main__":
    asyncio.run(get_chat_id())
