"""
Zalo Notification Module
Gửi thông báo tin nhắn qua Zalo Bot Platform API (bot.zaloplatforms.com).
"""
import httpx
from loguru import logger
from core.config import Config


class ZaloNotifier:
    """
    Lớp quản lý gửi tin nhắn qua Zalo Bot (bot.zaloplatforms.com).
    Hỗ trợ gửi tới cả cá nhân (admin) và nhóm (group).
    """

    def __init__(self):
        self.token = Config.ZALO_BOT_TOKEN
        self.admin_chat_id = Config.ZALO_ADMIN_CHAT_ID
        self.group_chat_id = Config.ZALO_GROUP_CHAT_ID
        # Tương thích ngược:
        self.chat_id = self.admin_chat_id or Config.ZALO_USER_ID
        self.access_token = Config.ZALO_ACCESS_TOKEN
        self.user_id = Config.ZALO_USER_ID

    async def send_message(self, text: str, chat_id: str = None) -> bool:
        """
        Gửi tin nhắn dạng văn bản (text) qua Zalo Bot API.
        Nếu truyền chat_id cụ thể, sẽ gửi đến chat_id đó.
        Nếu không truyền chat_id, sẽ gửi đến tất cả các chat_id được cấu hình (admin & group).
        """
        if not self.token:
            logger.debug("ZaloNotifier chưa được cấu hình (thiếu ZALO_BOT_TOKEN).")
            return False

        # Xác định danh sách các chat ID cần gửi nhận thông báo
        targets = []
        if chat_id:
            targets.append(chat_id)
        else:
            if self.admin_chat_id:
                targets.append(self.admin_chat_id)
            if self.group_chat_id:
                targets.append(self.group_chat_id)

        if not targets:
            logger.debug("ZaloNotifier không có chat_id đích nào để gửi (thiếu ZALO_ADMIN_CHAT_ID và ZALO_GROUP_CHAT_ID).")
            return False

        headers = {
            "Content-Type": "application/json",
        }
        success = True

        try:
            async with httpx.AsyncClient() as client:
                for target in targets:
                    url = f"https://bot-api.zaloplatforms.com/bot{self.token}/sendMessage"
                    payload = {
                        "chat_id": target,
                        "text": text
                    }
                    resp = await client.post(url, headers=headers, json=payload, timeout=10)
                    if resp.status_code == 200:
                        logger.info(f"📨 Đã gửi tin nhắn Zalo Bot tới {target}: {text[:50]}...")
                    else:
                        logger.error(f"❌ Lỗi HTTP Zalo Bot API tới {target} (Status {resp.status_code}): {resp.text}")
                        success = False
        except Exception as e:
            logger.error(f"❌ Lỗi kết nối gửi Zalo Bot: {e}")
            success = False

        return success


